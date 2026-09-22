#!/usr/bin/env python3
"""Inventory a DWG/DXF: version, units, extents, layers, entity census, layouts, blocks
(with nested block-reference counts), attributes, text, xrefs, proxy objects, conversion warnings.

    dwg_census.py <file.dwg|file.dxf> [--out DIR] [--texts] [--top N]

Writes to DIR (default: <file>_census/):
    census.json     everything below, machine-readable
    census.txt      human summary (also printed)
    texts.txt       every TEXT/MTEXT/ATTRIB string with layer and location (modelspace + inside blocks)
    blocks.csv      block name, direct inserts from modelspace, total nested inserts, flattened entity count
    warnings.txt    dwg2dxf warning summary (DWG input only)
The DXF produced from a DWG is kept in DIR for the other scripts.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cadlib  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", help="output directory")
    ap.add_argument("--texts", action="store_true", help="also print text strings to stdout")
    ap.add_argument("--top", type=int, default=30, help="rows shown per table in the summary")
    a = ap.parse_args()

    src = Path(a.src)
    out = Path(a.out) if a.out else src.with_name(src.stem + "_census")
    out.mkdir(parents=True, exist_ok=True)
    dxf, logf = cadlib.ensure_dxf(src, out)
    warnings = cadlib.warning_summary(logf)

    cadlib.log(f"loading {dxf.name} ({dxf.stat().st_size/1e6:.1f} MB)")
    doc = cadlib.readfile(dxf)
    msp = doc.modelspace()
    count = cadlib.flattened_counter(doc)

    # --- header / units / extents
    x0, y0, x1, y1 = cadlib.extents(doc)
    insunits = doc.header.get("$INSUNITS", 0)
    units_name = {0: "unitless", 1: "inch", 2: "foot", 4: "mm", 5: "cm", 6: "m"}.get(insunits, str(insunits))

    # --- modelspace census
    ent_types = Counter(e.dxftype() for e in msp)
    layer_use = Counter(e.dxf.layer for e in msp)
    layers = []
    for l in doc.layers:
        layers.append({
            "name": l.dxf.name, "color": l.dxf.color, "linetype": l.dxf.linetype,
            "off": l.is_off(), "frozen": l.is_frozen(), "locked": l.is_locked(),
            "msp_entities": layer_use.get(l.dxf.name, 0),
        })

    # --- blocks: direct inserts, nested inserts, flattened size, xrefs
    direct = Counter(e.dxf.name for e in msp.query("INSERT"))
    nested: Counter[str] = Counter()

    def walk(name: str, mult: int, depth: int, seen: set) -> None:
        if depth > 12 or name not in doc.blocks:
            return
        for e in doc.blocks[name].query("INSERT"):
            nested[e.dxf.name] += mult
            walk(e.dxf.name, mult, depth + 1, seen)

    for name, n in direct.items():
        walk(name, n, 0, set())

    blocks = []
    xrefs = []
    for blk in doc.blocks:
        name = blk.name
        rec = blk.block_record
        if name.startswith("*Model_Space") or name.startswith("*Paper_Space"):
            continue
        if rec.is_xref:
            xrefs.append({"name": name, "path": rec.dxf.get("xref_path", "")})
        attdefs = [ad.dxf.tag for ad in blk.query("ATTDEF")]
        blocks.append({
            "name": name, "direct_inserts": direct.get(name, 0), "total_inserts": direct.get(name, 0) + nested.get(name, 0),
            "flattened_entities": count(name), "own_entities": len(blk), "attdefs": attdefs, "xref": rec.is_xref,
        })
    blocks.sort(key=lambda b: (-b["total_inserts"], -b["flattened_entities"], b["name"]))

    # --- attributes on inserts (modelspace + nested, tag → values)
    attrib_values: dict[str, Counter] = defaultdict(Counter)

    def collect_attribs(layout_or_block):
        for ins in layout_or_block.query("INSERT"):
            for at in ins.attribs:
                attrib_values[at.dxf.tag][at.dxf.text] += 1

    collect_attribs(msp)
    for blk in doc.blocks:
        if not blk.name.startswith("*"):
            collect_attribs(blk)

    # --- texts (modelspace + block definitions)
    texts: list[dict] = []

    def collect_text(container, where: str):
        for e in container.query("TEXT MTEXT ATTRIB ATTDEF"):
            t = e.dxftype()
            s = e.plain_text() if t == "MTEXT" else e.dxf.text
            s = " | ".join(p.strip() for p in (s or "").splitlines() if p.strip())
            if not s:
                continue
            p = e.dxf.insert if t != "MTEXT" else e.dxf.insert
            texts.append({"where": where, "type": t, "layer": e.dxf.layer, "text": s, "x": round(p.x, 3), "y": round(p.y, 3)})

    collect_text(msp, "MODEL")
    for blk in doc.blocks:
        if not blk.name.startswith("*Model_Space") and not blk.name.startswith("*Paper_Space"):
            collect_text(blk, f"BLOCK:{blk.name}")
    for name in doc.layouts.names():
        if name != "Model":
            collect_text(doc.layouts.get(name), f"LAYOUT:{name}")

    # --- layouts
    layouts = []
    for name in doc.layouts.names():
        lay = doc.layouts.get(name)
        rec = {"name": name, "entities": len(lay)}
        if name != "Model":
            vps = list(lay.query("VIEWPORT"))
            rec["viewports"] = max(0, len(vps) - 1)  # first VIEWPORT is the paper itself
            try:
                rec["paper_size_mm"] = [round(v, 1) for v in lay.get_paper_limits()[1]]
            except Exception:
                pass
        layouts.append(rec)

    # --- gaps to state
    proxies = ent_types.get("ACAD_PROXY_ENTITY", 0) + sum(
        1 for blk in doc.blocks for e in blk if e.dxftype() == "ACAD_PROXY_ENTITY")
    images = ent_types.get("IMAGE", 0) + ent_types.get("OLE2FRAME", 0) + ent_types.get("WIPEOUT", 0)
    hatch_warn = sum(n for n, k in warnings if "HATCH" in k.upper())

    flattened_total = sum(count(e.dxf.name) * max(1, cadlib._array_count(e)) if e.dxftype() == "INSERT" else 1 for e in msp)

    result = {
        "source": str(src), "dxf": str(dxf), "dxfversion": doc.dxfversion,
        "insunits": insunits, "insunits_name": units_name,
        "extents": {"xmin": x0, "ymin": y0, "xmax": x1, "ymax": y1, "width": x1 - x0, "height": y1 - y0},
        "modelspace_entities": len(msp), "modelspace_flattened_entities": flattened_total,
        "entity_types": dict(ent_types.most_common()),
        "layers": layers, "layouts": layouts,
        "blocks": blocks, "xrefs": xrefs,
        "attribute_tags": {k: dict(v.most_common(50)) for k, v in attrib_values.items()},
        "text_count": len(texts),
        "gaps": {"proxy_entities": proxies, "image_ole_wipeout": images, "hatch_warnings": hatch_warn,
                 "unstable_or_unknown_objects": sum(n for n, k in warnings if "Unstable" in k or "Unknown" in k or "Unhandled" in k)},
        "dwg2dxf_warnings": [{"count": n, "message": k} for n, k in warnings],
    }
    (out / "census.json").write_text(json.dumps(result, indent=2, default=str))

    with open(out / "texts.txt", "w") as fh:
        for t in texts:
            fh.write(f"{t['where']}\t{t['type']}\t{t['layer']}\t{t['x']}\t{t['y']}\t{t['text']}\n")
    with open(out / "blocks.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["block", "direct_inserts", "total_inserts", "flattened_entities", "own_entities", "attdefs", "xref"])
        for b in blocks:
            w.writerow([b["name"], b["direct_inserts"], b["total_inserts"], b["flattened_entities"], b["own_entities"], ";".join(b["attdefs"]), b["xref"]])
    with open(out / "warnings.txt", "w") as fh:
        for n, k in warnings:
            fh.write(f"{n:7d}  {k}\n")

    # --- human summary
    L = []
    L.append(f"{src.name}: {doc.dxfversion}, $INSUNITS={insunits} ({units_name}), extents {x1-x0:.1f} x {y1-y0:.1f} "
             f"from ({x0:.1f},{y0:.1f}) — units are an assumption to verify against coordinate magnitudes")
    L.append(f"modelspace: {len(msp)} entities, {flattened_total} after expanding block references; "
             f"{len(layers)} layers, {len(blocks)} blocks, {len(xrefs)} xrefs, {len(texts)} text strings")
    L.append("entity types: " + ", ".join(f"{k} {v}" for k, v in ent_types.most_common(a.top)))
    L.append("layers (msp entities): " + ", ".join(f"{l['name']} {l['msp_entities']}" + (" [off]" if l['off'] else "") + (" [frozen]" if l['frozen'] else "") for l in layers[:a.top]))
    L.append("layouts: " + ", ".join(f"{l['name']} ({l['entities']} ent" + (f", {l.get('viewports')} vp" if 'viewports' in l else "") + ")" for l in layouts))
    if blocks:
        L.append("top blocks (total inserts / flattened entities):")
        for b in blocks[:a.top]:
            L.append(f"  {b['total_inserts']:5d}  {b['flattened_entities']:7d}  {b['name']}" + (f"  attdefs={b['attdefs']}" if b["attdefs"] else ""))
    if xrefs:
        L.append("xrefs (ask for these files): " + ", ".join(f"{x['name']} → {x['path']}" for x in xrefs))
    g = result["gaps"]
    L.append(f"gaps: proxy entities {g['proxy_entities']}, image/OLE/wipeout {g['image_ole_wipeout']}, "
             f"hatch warnings {g['hatch_warnings']}, unstable/unknown objects {g['unstable_or_unknown_objects']}")
    if warnings:
        L.append("dwg2dxf warnings: " + "; ".join(f"{k} x{n}" for n, k in warnings[:8]))
    summary = "\n".join(L)
    (out / "census.txt").write_text(summary + "\n")
    print(summary)
    if a.texts:
        print("--- texts")
        for t in texts:
            print(f"{t['where']}\t{t['layer']}\t{t['text']}")
    print(f"→ {out}/census.json, texts.txt, blocks.csv, warnings.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
