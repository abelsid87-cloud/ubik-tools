#!/usr/bin/env bash
# UBIK CAD toolchain bootstrap — idempotent. Run at the start of any DWG/DXF task.
#
#   curl -sSL https://raw.githubusercontent.com/abelsid87-cloud/ubik-tools/main/cad/bootstrap.sh | bash
#
# Installs: ezdxf + matplotlib (pip), LibreDWG 0.14 prebuilt binaries → /opt/libredwg/bin,
#           UBIK CAD scripts → /opt/ubik-cad (verified against cad/SHA256SUMS).
# Prints one final status line: CAD_OK or CAD_FAIL <reason>.
set -u
RAW="https://raw.githubusercontent.com/abelsid87-cloud/ubik-tools/main"
PREBUILT="$RAW/libredwg-0.14-ubuntu2404-x64-min.tar.gz"
PREBUILT_SHA256="24801bc22c36730d6cd519da51424c65aa78cb95317cb4227429691371624252"
BIN=/opt/libredwg/bin
DEST=/opt/ubik-cad
SCRIPTS="dwg_census.py lod_reduce.py dwg_render.py clean_export.py compare_plot.py selftest.sh cadlib.py"
TMP="$(mktemp -d)"

fail() { echo "CAD_FAIL $*"; exit 1; }

# 1. Python deps
python3 -c "import ezdxf, matplotlib" 2>/dev/null || \
  pip install ezdxf matplotlib --break-system-packages -q 2>/dev/null || \
  pip install ezdxf matplotlib -q 2>/dev/null || fail "pip install ezdxf/matplotlib"
python3 -c "import ezdxf, matplotlib" 2>/dev/null || fail "ezdxf import"

# 2. LibreDWG binaries
if [ ! -x "$BIN/dwg2dxf" ]; then
  if curl -sSL -m 180 -o "$TMP/ldwg.tgz" "$PREBUILT" \
     && echo "$PREBUILT_SHA256  $TMP/ldwg.tgz" | sha256sum -c --quiet 2>/dev/null; then
    mkdir -p "$BIN" && tar xzf "$TMP/ldwg.tgz" -C "$TMP" && cp "$TMP"/ldwg-min/* "$BIN"/ && chmod +x "$BIN"/*
  else
    echo "prebuilt download/checksum failed — building LibreDWG 0.14 from source (~6 min)"
    ( cd "$TMP" && curl -sSL -m 180 -o libredwg.tar.xz https://ftp.gnu.org/gnu/libredwg/libredwg-0.14.tar.xz \
      && tar xf libredwg.tar.xz && cd libredwg-0.14 \
      && ./configure --prefix=/opt/libredwg --disable-bindings --disable-python --disable-shared --enable-static >"$TMP/cfg.log" 2>&1 \
      && make -j"$(nproc)" >"$TMP/make.log" 2>&1 && make install >"$TMP/inst.log" 2>&1 ) || fail "libredwg source build (logs in $TMP)"
  fi
fi
"$BIN/dwg2dxf" --version >/dev/null 2>&1 || fail "dwg2dxf not runnable"

# 3. Scripts, verified against the published checksum list
mkdir -p "$DEST"
curl -sSL -m 60 -o "$DEST/SHA256SUMS" "$RAW/cad/SHA256SUMS" || fail "fetch SHA256SUMS"
for s in $SCRIPTS; do
  curl -sSL -m 60 -o "$DEST/$s" "$RAW/cad/$s" || fail "fetch $s"
done
( cd "$DEST" && grep -E "  ($(echo $SCRIPTS | sed 's/ /|/g'))\$" SHA256SUMS | sha256sum -c --quiet ) || fail "script checksum mismatch — do not use $DEST"
chmod +x "$DEST"/*.sh "$DEST"/*.py

# 4. Optional: pdftoppm for PDF-plot comparison (not fatal)
command -v pdftoppm >/dev/null 2>&1 || echo "note: pdftoppm missing — compare_plot.py needs poppler-utils"

rm -rf "$TMP"
echo "libredwg: $("$BIN/dwg2dxf" --version 2>&1 | head -1)  ezdxf: $(python3 -c 'import ezdxf;print(ezdxf.__version__)')  scripts: $DEST"
echo "CAD_OK"
