#!/usr/bin/env python3
"""Compare an ezdxf render against the client's PDF plot to find content the render is missing.

    compare_plot.py <render.png> <plot.pdf|plot.png> [--page 1] [--grid 48 32] [--out DIR]
                    [--ink 0.02] [--ratio 0.25] [--dpi 110]

Both images are converted to ink masks (non-white pixels), resized to the same size, and split
into a grid. A cell is reported MISSING when the plot has ink coverage ≥ --ink and the render
has less than --ratio of that coverage; EXTRA when the reverse holds (content the plot hides:
frozen layers, clipped viewports). Writes diff.png (plot in grey, missing cells red, extra cells
blue) and diff.json, prints a summary and exits 1 when any cell is MISSING.

Precondition: render the SAME layout the PDF was plotted from (a paper-space layout for a sheet
plot: dwg_render.py --layout <name>) so the two images share the same frame. A modelspace render
against a sheet plot will report the title block as missing — that is expected and stated.
Typical missing causes: hatches (rendered with IGNORE), IMAGE/OLE (never rendered), proxy objects
with no proxy graphics, xrefs not supplied, plot styles that hide layers.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def to_mask(path: Path, page: int, dpi: int):
    from PIL import Image, ImageOps

    if path.suffix.lower() == ".pdf":
        tmp = Path(tempfile.mkdtemp())
        subprocess.check_call(["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page), "-png", str(path), str(tmp / "p")])
        pngs = sorted(tmp.glob("p*.png"))
        if not pngs:
            raise SystemExit(f"pdftoppm produced no page for {path} page {page}")
        path = pngs[0]
    im = Image.open(path).convert("L")
    im = ImageOps.autocontrast(im)
    return im


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("render")
    ap.add_argument("plot")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--grid", nargs=2, type=int, default=[48, 32], metavar=("COLS", "ROWS"))
    ap.add_argument("--out")
    ap.add_argument("--ink", type=float, default=0.02, help="min plot ink fraction for a cell to count as content")
    ap.add_argument("--ratio", type=float, default=0.25, help="render/plot ink ratio below which a cell is MISSING")
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--threshold", type=int, default=200, help="grey level below which a pixel is ink")
    a = ap.parse_args()

    import numpy as np
    from PIL import Image

    render = Path(a.render)
    plot = Path(a.plot)
    out = Path(a.out) if a.out else render.with_name(render.stem + "_vs_" + plot.stem)
    out.mkdir(parents=True, exist_ok=True)

    r = to_mask(render, 1, a.dpi)
    p = to_mask(plot, a.page, a.dpi)
    W, H = p.size
    r = r.resize((W, H))
    rm = (np.asarray(r) < a.threshold)
    pm = (np.asarray(p) < a.threshold)
    if abs((render_ar := Image.open(render).size[0] / Image.open(render).size[1]) - W / H) > 0.05:
        print(f"note: aspect ratios differ (render {render_ar:.2f} vs plot {W/H:.2f}) — frames are probably not the same layout")

    cols, rows = a.grid
    cw, ch = W / cols, H / rows
    missing, extra, common = [], [], 0
    for j in range(rows):
        for i in range(cols):
            y0, y1, x0, x1 = int(j * ch), int((j + 1) * ch), int(i * cw), int((i + 1) * cw)
            pc = pm[y0:y1, x0:x1].mean()
            rc = rm[y0:y1, x0:x1].mean()
            if pc >= a.ink and rc < a.ratio * pc:
                missing.append({"col": i, "row": j, "plot_ink": round(float(pc), 4), "render_ink": round(float(rc), 4)})
            elif rc >= a.ink and pc < a.ratio * rc:
                extra.append({"col": i, "row": j, "plot_ink": round(float(pc), 4), "render_ink": round(float(rc), 4)})
            elif pc >= a.ink:
                common += 1

    # diff image
    base = np.stack([np.where(pm, 120, 255)] * 3, axis=-1).astype(np.uint8)
    for c, colour in ((missing, (220, 40, 40)), (extra, (40, 90, 220))):
        for cell in c:
            y0, y1, x0, x1 = int(cell["row"] * ch), int((cell["row"] + 1) * ch), int(cell["col"] * cw), int((cell["col"] + 1) * cw)
            block = base[y0:y1, x0:x1].astype(int)
            base[y0:y1, x0:x1] = ((block * 0.5) + (np.array(colour) * 0.5)).astype(np.uint8)
    diff = Image.fromarray(base)
    diff.thumbnail((2000, 2000))
    diff.save(out / "diff.png")
    total = len(missing) + len(extra) + common
    summary = {
        "render": str(render), "plot": str(plot), "page": a.page, "grid": [cols, rows],
        "cells_with_content": total, "missing": len(missing), "extra": len(extra), "common": common,
        "missing_cells": missing, "extra_cells": extra,
    }
    (out / "diff.json").write_text(json.dumps(summary, indent=2))
    pct = (100.0 * len(missing) / total) if total else 0.0
    print(f"{total} content cells: {common} match, {len(missing)} MISSING in render ({pct:.1f}%), {len(extra)} extra in render")
    if missing:
        rows_hit = sorted({m['row'] for m in missing})
        print(f"missing cells span rows {rows_hit[0]}–{rows_hit[-1]} of {rows} (top=0); inspect {out/'diff.png'} (red = missing, blue = extra)")
    print(f"→ {out/'diff.png'}, {out/'diff.json'}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
