"""Shared helpers for the UBIK CAD scripts (ezdxf + LibreDWG)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

LIBREDWG_BIN = Path(os.environ.get("LIBREDWG_BIN", "/opt/libredwg/bin"))


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def ensure_dxf(src: Path, workdir: Path) -> tuple[Path, Path | None]:
    """Return (dxf_path, dwg2dxf_log_or_None). Converts a DWG with LibreDWG when needed.

    Conversion is skipped when a DXF newer than the DWG already sits in workdir.
    """
    src = Path(src)
    if src.suffix.lower() == ".dxf":
        return src, None
    if src.suffix.lower() != ".dwg":
        raise SystemExit(f"unsupported input {src.suffix}; expected .dwg or .dxf")
    workdir.mkdir(parents=True, exist_ok=True)
    dxf = workdir / (src.stem + ".dxf")
    logf = workdir / (src.stem + ".dwg2dxf.log")
    if dxf.exists() and dxf.stat().st_mtime >= src.stat().st_mtime and dxf.stat().st_size > 0:
        log(f"reusing {dxf}")
        return dxf, (logf if logf.exists() else None)
    exe = LIBREDWG_BIN / "dwg2dxf"
    if not exe.exists():
        raise SystemExit(f"{exe} missing — run cad/bootstrap.sh first")
    log(f"dwg2dxf {src.name} → {dxf.name} (about 1 min per 100 MB)")
    with open(logf, "w") as fh:
        rc = subprocess.call([str(exe), "-y", "-o", str(dxf), str(src)], stdout=fh, stderr=subprocess.STDOUT)
    if rc != 0 or not dxf.exists() or dxf.stat().st_size == 0:
        raise SystemExit(f"dwg2dxf failed (rc={rc}); see {logf}")
    return dxf, logf


def warning_summary(logf: Path | None, top: int = 12) -> list[tuple[int, str]]:
    if not logf or not Path(logf).exists():
        return []
    c: Counter[str] = Counter()
    pat = re.compile(r"(Warning|Error): ([A-Za-z_ ]+)")
    with open(logf, errors="replace") as fh:
        for line in fh:
            m = pat.search(line)
            if m:
                c[f"{m.group(1)}: {m.group(2).strip()}"] += 1
    return [(n, k) for k, n in c.most_common(top)]


def readfile(dxf: Path):
    """ezdxf.readfile with the LibreDWG-specific save patch applied for working copies."""
    import ezdxf
    import ezdxf.document as _d

    # LibreDWG leaves MATERIAL objects unstable; doc.saveas() then raises in _update_header_vars.
    # Patching keeps working copies saveable. Deliverables are always rebuilt via clean_export.py.
    _d.Drawing._update_header_vars = lambda self: None  # type: ignore[assignment]
    return ezdxf.readfile(str(dxf))


def flattened_counter(doc) -> "callable":
    """Return count(block_name) → number of primitive entities after expanding nested INSERTs."""
    blocks = doc.blocks

    @lru_cache(maxsize=None)
    def count(name: str, depth: int = 0) -> int:
        if depth > 12:
            return 0
        try:
            blk = blocks[name]
        except KeyError:
            return 0
        n = 0
        for e in blk:
            if e.dxftype() == "INSERT":
                n += count(e.dxf.name, depth + 1) * max(1, _array_count(e))
            else:
                n += 1
        return n

    return count


def _array_count(ins) -> int:
    try:
        return max(1, int(ins.dxf.get("row_count", 1)) * int(ins.dxf.get("column_count", 1)))
    except Exception:
        return 1


def extents(doc):
    """Drawing extents: header $EXTMIN/$EXTMAX when sane, else computed from modelspace."""
    try:
        (x0, y0, _), (x1, y1, _) = doc.header["$EXTMIN"], doc.header["$EXTMAX"]
        if x1 > x0 and y1 > y0 and abs(x0) < 1e14 and abs(x1) < 1e14:
            return x0, y0, x1, y1
    except Exception:
        pass
    import ezdxf.bbox

    bb = ezdxf.bbox.extents(doc.modelspace(), fast=True)
    if not bb.has_data:
        return 0.0, 0.0, 1.0, 1.0
    return bb.extmin.x, bb.extmin.y, bb.extmax.x, bb.extmax.y
