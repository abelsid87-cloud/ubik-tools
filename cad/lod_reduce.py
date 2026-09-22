#!/usr/bin/env python3
"""Level-of-detail copy of a large DXF so it renders inside the sandbox memory budget.

    lod_reduce.py <in.dxf> <out_lod.dxf> [--threshold 40] [--all]

Every block that is NOT inserted directly from modelspace and has more than --threshold
flattened entities (equipment/steel details: filters, pumps, angle steel, HSS columns) is
replaced by one closed LWPOLYLINE rectangle of its extents on layer 0, colour 8.
Blocks inserted directly from modelspace are kept intact by default (they are the plant
items you want to see); pass --all to box those too.

Measured on a 97 MB Vertiv layout: 3.3 M → 74 k flattened entities; render 2 min at 3.6 GB.
The output is a WORKING COPY (saved through the LibreDWG patch); never ship it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cadlib  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--threshold", type=int, default=40, help="flattened entities above which a nested block is boxed")
    ap.add_argument("--all", action="store_true", help="also box blocks inserted directly from modelspace")
    a = ap.parse_args()

    import ezdxf.bbox

    doc = cadlib.readfile(Path(a.src))
    msp = doc.modelspace()
    count = cadlib.flattened_counter(doc)
    direct = {e.dxf.name for e in msp.query("INSERT")}

    before = sum(count(e.dxf.name) if e.dxftype() == "INSERT" else 1 for e in msp)
    boxed, boxed_entities = 0, 0
    # Reduce leaf-most blocks first so parents see reduced children only if they themselves qualify.
    names = [b.name for b in doc.blocks if not b.name.startswith("*Model_Space") and not b.name.startswith("*Paper_Space")]
    names.sort(key=lambda n: count(n))
    for name in names:
        if (name in direct and not a.all) or name.startswith("*D"):
            continue  # *D blocks carry dimension graphics — boxing them erases the dimensions
        n = count(name)
        if n <= a.threshold:
            continue
        blk = doc.blocks[name]
        bb = ezdxf.bbox.extents(blk, fast=True)
        if not bb.has_data:
            continue
        (x0, y0, _), (x1, y1, _) = bb.extmin, bb.extmax
        for e in list(blk):
            blk.delete_entity(e)
        blk.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": "0", "color": 8})
        boxed += 1
        boxed_entities += n
    count.cache_clear()
    after = sum(count(e.dxf.name) if e.dxftype() == "INSERT" else 1 for e in msp)
    doc.saveas(a.dst)
    print(f"boxed {boxed} blocks ({boxed_entities} entities) — modelspace flattened {before} → {after}; wrote {a.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
