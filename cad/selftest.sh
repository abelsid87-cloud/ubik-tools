#!/usr/bin/env bash
# End-to-end regression test of the UBIK CAD toolchain on the bundled fixture.
#   selftest.sh [DIR]     (DIR: where the scripts live; default = this script's directory)
# Fetches cad/fixtures/example_2018.dwg (+ expected.json) from the repo when not present next to
# the scripts, runs census → render → lod → clean_export → compare, and checks the census against
# expected.json. Exit 0 = SELFTEST_OK, 1 = a step failed, 2 = census mismatch.
set -u
HERE="${1:-$(cd "$(dirname "$0")" && pwd)}"
RAW="https://raw.githubusercontent.com/abelsid87-cloud/ubik-tools/main/cad"
W="$(mktemp -d)"
FIX="$HERE/fixtures"
mkdir -p "$FIX"
for f in example_2018.dwg expected.json; do
  [ -s "$FIX/$f" ] || curl -sSL -m 120 -o "$FIX/$f" "$RAW/fixtures/$f" || { echo "SELFTEST_FAIL fetch $f"; exit 1; }
done
fail() { echo "SELFTEST_FAIL $*"; echo "workdir kept: $W"; exit 1; }

echo "[1/5] census";       python3 "$HERE/dwg_census.py" "$FIX/example_2018.dwg" --out "$W/census" >"$W/census.out" 2>&1 || fail census
echo "[2/5] render";       python3 "$HERE/dwg_render.py" "$W/census/example_2018.dxf" --out "$W/render" --crop 0 0 12000 8000 zoom >"$W/render.out" 2>&1 || fail render
echo "[3/5] lod_reduce";   python3 "$HERE/lod_reduce.py" "$W/census/example_2018.dxf" "$W/lod.dxf" --threshold 8 >"$W/lod.out" 2>&1 || fail lod
echo "[4/5] clean_export"; python3 "$HERE/clean_export.py" "$W/census/example_2018.dxf" "$W/clean.dxf" --r2013 >"$W/clean.out" 2>&1 || fail clean_export
echo "[5/5] compare_plot"; python3 "$HERE/dwg_render.py" "$W/census/example_2018.dxf" --out "$W/ref" --pdf --hatch --extents 0 0 12000 8000 >/dev/null 2>&1 || fail ref-render
python3 "$HERE/dwg_render.py" "$W/clean.dxf" --out "$W/cln" --extents 0 0 12000 8000 >/dev/null 2>&1 || fail clean-render
python3 "$HERE/compare_plot.py" "$W/cln/Model.png" "$W/ref/Model.pdf" --out "$W/cmp" >"$W/cmp.out" 2>&1
CMP_RC=$?   # 1 expected: clean.dxf lacks the HATCH/WIPEOUT the reference PDF shows

python3 - "$W/census/census.json" "$FIX/expected.json" "$W/clean.dxf" "$W/cmp/diff.json" "$CMP_RC" <<'EOF' || exit 2
import json, sys
c = json.load(open(sys.argv[1])); e = json.load(open(sys.argv[2]))
import ezdxf
d = ezdxf.readfile(sys.argv[3]); a = d.audit()
cmp = json.load(open(sys.argv[4])); cmp_rc = int(sys.argv[5])
bad = []
def chk(name, got, want):
    if got != want: bad.append(f"{name}: got {got!r}, expected {want!r}")
chk("dxfversion", c["dxfversion"], e["dxfversion"])
chk("layers", sorted(l["name"] for l in c["layers"]), sorted(e["layers"]))
chk("modelspace_entities", c["modelspace_entities"], e["modelspace_entities"])
chk("modelspace_flattened_entities", c["modelspace_flattened_entities"], e["modelspace_flattened_entities"])
for t, n in e["entity_types"].items(): chk(f"entity {t}", c["entity_types"].get(t, 0), n)
chk("text_count", c["text_count"], e["text_count"])
chk("blocks_with_inserts", {b["name"]: b["total_inserts"] for b in c["blocks"] if b["total_inserts"]}, e["blocks_with_inserts"])
chk("clean msp entities", len(d.modelspace()), e["clean_msp_entities"])
chk("clean dimensions", len(d.modelspace().query("DIMENSION")), e["clean_dimensions"])
chk("clean audit", [len(a.errors), len(a.fixes)], [0, 0])
chk("compare exit", cmp_rc, e["compare_exit"])
if not (e["compare_missing_min"] <= cmp["missing"] <= e["compare_missing_max"]):
    bad.append(f"compare missing cells {cmp['missing']} outside {e['compare_missing_min']}–{e['compare_missing_max']}")
if bad:
    print("SELFTEST_MISMATCH"); [print("  " + b) for b in bad]; sys.exit(1)
print(f"census {c['modelspace_entities']} msp / {c['modelspace_flattened_entities']} flattened, {len(c['layers'])} layers; clean {len(d.modelspace())} msp, audit 0/0; compare missing {cmp['missing']} cells")
EOF
rm -rf "$W"
echo "SELFTEST_OK"
