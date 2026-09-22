#!/usr/bin/env python3
"""Re-host a working DXF into a fresh ezdxf document so it is deliverable-grade.

    clean_export.py <work.dxf> <out.dxf> [--r2013] [--strip-xdata] [--layouts all|model]

Why: a DXF produced by LibreDWG (or edited on top of one) carries unstable objects that break
doc.saveas() and can trip AutoCAD's audit. This script imports tables (layers, linetypes, text
styles, dimstyles), block definitions, modelspace and paper-space layouts into ezdxf.new("R2018"),
bakes draw order into entity order, removes degenerate entities, then runs doc.audit() — the
result must be 0 errors / 0 fixes or the script exits non-zero.

Outputs <out.dxf> (AC1032, opens natively in AutoCAD/BricsCAD/ZWCAD/DraftSight/QCAD) and, with
--r2013, <out>_R2013.dxf for older readers. The recipient does Save As → DWG if a DWG is required.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cadlib  # noqa: E402

DEGENERATE_TOL = 1e-9


def is_degenerate(e) -> bool:
    t = e.dxftype()
    try:
        if t == "LINE":
            return (e.dxf.start - e.dxf.end).magnitude < DEGENERATE_TOL
        if t == "LWPOLYLINE":
            return len(e) < 2
        if t == "POLYLINE":
            return len(e.vertices) < 2
        if t in ("CIRCLE", "ARC"):
            return e.dxf.radius <= DEGENERATE_TOL
        if t in ("TEXT", "MTEXT"):
            s = e.plain_text() if t == "MTEXT" else e.dxf.text
            return not (s or "").strip()
    except Exception:
        return False
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--r2013", action="store_true", help="also write an R2013 (AC1027) copy")
    ap.add_argument("--strip-xdata", action="store_true", help="drop XDATA/app data on every entity")
    ap.add_argument("--layouts", choices=["all", "model"], default="all")
    a = ap.parse_args()

    import ezdxf
    from ezdxf.addons.importer import Importer

    src = cadlib.readfile(Path(a.src))
    dst = ezdxf.new("R2018", setup=True)
    for k in ("$INSUNITS", "$MEASUREMENT", "$LTSCALE", "$DIMSCALE", "$EXTMIN", "$EXTMAX", "$LIMMIN", "$LIMMAX"):
        if k in src.header:
            try:
                dst.header[k] = src.header[k]
            except Exception:
                pass
    dst.units = src.units

    imp = Importer(src, dst)
    imp.import_tables()  # layers, linetypes, styles, dimstyles
    # anonymous *D blocks are dimension geometry and are recreated per DIMENSION below
    imp.import_blocks([b.name for b in src.blocks
                       if not b.name.startswith(("*Model_Space", "*Paper_Space", "*D"))])
    from collections import Counter
    dropped: Counter = Counter()

    def import_layout_entities(entities, target):
        before = Counter(e.dxftype() for e in entities)
        imp.import_entities(entities, target)
        # ezdxf 1.4 Importer never calls post_bind_hook(), so copied DIMENSIONs lose their
        # geometry block and audit() deletes them — bind them by hand.
        for d in target.query("DIMENSION"):
            if d.dxf.get("geometry") is None and d.virtual_block_content:
                d.post_bind_hook()
        after = Counter(e.dxftype() for e in target)
        for t, n in before.items():
            if after.get(t, 0) < n:
                dropped[t] += n - after.get(t, 0)

    def clean(container):
        removed = 0
        for e in list(container):
            if is_degenerate(e):
                container.delete_entity(e)
                removed += 1
            elif a.strip_xdata:
                try:
                    e.discard_xdata_all() if hasattr(e, "discard_xdata_all") else None
                    if e.has_xdata:
                        for appid in list(e.xdata.data.keys()) if e.xdata else []:
                            e.discard_xdata(appid)
                except Exception:
                    pass
        return removed

    removed = clean(src.modelspace())
    # bake draw order: entities are emitted in list order; SORTENTSTABLE handles are dropped by the importer
    try:
        order = src.modelspace().get_sortents_table()
        if order and len(order):
            handles = {h for _, h in order}
            keyed = {e.dxf.handle: e for e in src.modelspace()}
            ordered = [keyed[h] for _, h in sorted(order, key=lambda p: p[0]) if h in keyed]
            rest = [e for e in src.modelspace() if e.dxf.handle not in handles]
            import_layout_entities(rest + ordered, dst.modelspace())
        else:
            import_layout_entities(list(src.modelspace()), dst.modelspace())
    except Exception:
        import_layout_entities(list(src.modelspace()), dst.modelspace())

    if a.layouts == "all":
        src_names = [n for n in src.layouts.names() if n != "Model"]
        for name in src_names:
            removed += clean(src.layouts.get(name))
            try:
                src_lay = src.layouts.get(name)
                dst_lay = dst.layouts.get(name) if name in dst.layouts.names() else imp.recreate_source_layout(name)
                import_layout_entities([e for e in src_lay if e.dxftype() != "VIEWPORT" or e.dxf.id != 1],
                                       dst_lay)
            except Exception as ex:
                cadlib.log(f"layout {name}: {ex}")
        # drop the default empty Layout1 ezdxf.new() created when the source has no layout of that name
        for n in list(dst.layouts.names()):
            if n != "Model" and n not in src_names and len(dst.layouts.names()) > 2:
                dst.layouts.delete(n)
    imp.finalize()

    auditor = dst.audit()
    n_err, n_fix = len(auditor.errors), len(auditor.fixes)
    dst.saveas(a.dst)
    msg = f"wrote {a.dst}: {len(dst.modelspace())} msp entities, {len(dst.layers)} layers, " \
          f"{len(list(dst.blocks))} blocks, removed {removed} degenerate; audit errors={n_err} fixes={n_fix}"
    if a.r2013:
        p = Path(a.dst)
        p13 = p.with_name(p.stem + "_R2013" + p.suffix)
        d13 = ezdxf.readfile(a.dst)
        d13.dxfversion = "AC1027"
        d13.saveas(p13)
        msg += f"; also {p13}"
    print(msg)
    if dropped:
        print("NOT carried over (unsupported by the ezdxf importer — state this to the recipient): "
              + ", ".join(f"{t} x{n}" for t, n in dropped.most_common()))
    if n_err or n_fix:
        for x in list(auditor.errors)[:10] + list(auditor.fixes)[:10]:
            print("  ", getattr(x, "code", ""), getattr(x, "message", x))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
