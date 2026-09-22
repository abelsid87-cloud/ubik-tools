#!/usr/bin/env python3
"""Render a DWG/DXF layout to PNG (and optionally vector PDF) — draw once, save many crops.

    dwg_render.py <file.dwg|file.dxf> [--out DIR] [--layout Model] [--dpi 120]
                  [--fit header|bbox] [--extents x0 y0 x1 y1] [--margin 0.02]
                  [--crop x0 y0 x1 y1 NAME]... [--pdf] [--auto-lod 500000] [--hatch] [--figsize 24 17]

Outputs in DIR (default <file>_render/): <layout>.png (full extents), <layout>_<NAME>.png per crop,
<layout>_view.png (downscaled ≤2000 px for viewing with Read), <layout>.pdf with --pdf.

--fit header uses $EXTMIN/$EXTMAX (what the author last saved); bbox recomputes from modelspace
geometry, ignoring XLINE/RAY (infinite lines). Default: bbox when header extents are more than
5x the geometry, else header.
--auto-lod N: if the modelspace flattens to more than N entities, a level-of-detail copy is
built with lod_reduce.py and rendered instead (stated in the output).
Hatches are ignored unless --hatch (LibreDWG hatch export is unreliable). Proxy entities render
from their proxy graphics only; IMAGE/OLE are never rendered — say so when they exist.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cadlib  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out")
    ap.add_argument("--layout", default="Model")
    ap.add_argument("--dpi", type=int, default=120)
    ap.add_argument("--fit", choices=["auto", "header", "bbox"], default="auto")
    ap.add_argument("--extents", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"), help="force the frame (use the same values on two renders you want to compare)")
    ap.add_argument("--margin", type=float, default=0.02, help="margin as a fraction of the larger extent")
    ap.add_argument("--crop", nargs=5, action="append", metavar=("X0", "Y0", "X1", "Y1", "NAME"), default=[])
    ap.add_argument("--crop-dpi", type=int, default=200)
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--auto-lod", type=int, default=500_000)
    ap.add_argument("--hatch", action="store_true")
    ap.add_argument("--figsize", nargs=2, type=float, default=[24, 17])
    a = ap.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import ezdxf.bbox
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration, HatchPolicy
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    src = Path(a.src)
    out = Path(a.out) if a.out else src.with_name(src.stem + "_render")
    out.mkdir(parents=True, exist_ok=True)
    dxf, _ = cadlib.ensure_dxf(src, out)

    cadlib.log(f"loading {dxf.name}")
    doc = cadlib.readfile(dxf)
    msp = doc.modelspace()
    count = cadlib.flattened_counter(doc)
    flat = sum(count(e.dxf.name) if e.dxftype() == "INSERT" else 1 for e in msp)
    lod_note = ""
    if flat > a.auto_lod and a.layout == "Model":
        lod = out / (dxf.stem + "_lod.dxf")
        cadlib.log(f"{flat} flattened entities > {a.auto_lod}: building LOD copy {lod.name}")
        subprocess.check_call([sys.executable, str(Path(__file__).with_name("lod_reduce.py")), str(dxf), str(lod)])
        doc = cadlib.readfile(lod)
        msp = doc.modelspace()
        lod_note = " [LOD copy: nested detail blocks drawn as boxes]"

    layout = msp if a.layout == "Model" else doc.layouts.get(a.layout)

    # extents
    hx0, hy0, hx1, hy1 = cadlib.extents(doc)
    if a.layout == "Model":
        geo = ezdxf.bbox.extents((e for e in msp if e.dxftype() not in ("XLINE", "RAY")), fast=True)
        if geo.has_data:
            bx0, by0, bx1, by1 = geo.extmin.x, geo.extmin.y, geo.extmax.x, geo.extmax.y
        else:
            bx0, by0, bx1, by1 = hx0, hy0, hx1, hy1
    else:
        try:
            (bx0, by0), (bx1, by1) = layout.get_paper_limits()
        except Exception:
            bx0, by0, bx1, by1 = hx0, hy0, hx1, hy1
        hx0, hy0, hx1, hy1 = bx0, by0, bx1, by1
    fit = a.fit
    if fit == "auto":
        hw, bw = max(hx1 - hx0, hy1 - hy0), max(bx1 - bx0, by1 - by0)
        fit = "bbox" if (bw > 0 and hw > 5 * bw) or hw <= 0 else "header"
    x0, y0, x1, y1 = (bx0, by0, bx1, by1) if fit == "bbox" else (hx0, hy0, hx1, hy1)
    if a.extents:
        x0, y0, x1, y1 = a.extents
        fit = "forced"
    m = a.margin * max(x1 - x0, y1 - y0, 1e-9)

    cfg = Configuration(
        background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR,
        hatch_policy=HatchPolicy.NORMAL if a.hatch else HatchPolicy.IGNORE,
    )
    fig = plt.figure(figsize=a.figsize)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ctx = RenderContext(doc)
    ctx.set_current_layout(layout)
    cadlib.log("drawing (once)…")
    Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(layout, finalize=False)
    ax.set_aspect("equal", adjustable="box")

    base = out / a.layout.replace(" ", "_")
    ax.set_xlim(x0 - m, x1 + m)
    ax.set_ylim(y0 - m, y1 + m)
    full = base.with_suffix(".png")
    fig.savefig(full, dpi=a.dpi, facecolor="white")
    if a.pdf:
        fig.savefig(base.with_suffix(".pdf"), facecolor="white")
    written = [full]
    for cx0, cy0, cx1, cy1, name in a.crop:
        ax.set_xlim(float(cx0), float(cx1))
        ax.set_ylim(float(cy0), float(cy1))
        p = out / f"{base.name}_{name}.png"
        fig.savefig(p, dpi=a.crop_dpi, facecolor="white")
        written.append(p)

    # viewing copy ≤ 2000 px
    try:
        from PIL import Image

        im = Image.open(full)
        im.thumbnail((2000, 2000))
        view = out / f"{base.name}_view.png"
        im.save(view)
        written.append(view)
    except Exception as ex:  # pragma: no cover
        cadlib.log(f"no viewing copy: {ex}")

    gaps = []
    for t in ("IMAGE", "OLE2FRAME", "WIPEOUT", "ACAD_PROXY_ENTITY", "HATCH"):
        n = len(layout.query(t))
        if n:
            gaps.append(f"{t} x{n}")
    print(f"rendered {a.layout} fit={fit} extents ({x0:.1f},{y0:.1f})–({x1:.1f},{y1:.1f}){lod_note}")
    if gaps:
        print("present but rendered partially or not at all: " + ", ".join(gaps) + ("" if a.hatch else " (hatches ignored)"))
    for p in written:
        print(f"→ {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
