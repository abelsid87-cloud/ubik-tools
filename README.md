# ubik-tools

Tooling that UBIK's Claude sessions pull at start-up. Public repository: nothing here may contain client material.

## cad/ — DWG/DXF toolchain (read any DWG/DXF, write DXF)

One-line bootstrap in a fresh Linux sandbox (Ubuntu 24.04 x64, Python 3):

```bash
curl -sSL https://raw.githubusercontent.com/abelsid87-cloud/ubik-tools/main/cad/bootstrap.sh | bash
```

Installs ezdxf + matplotlib, the prebuilt LibreDWG 0.14 binaries (`/opt/libredwg/bin`, SHA-256 verified) and the scripts below into `/opt/ubik-cad` (verified against `cad/SHA256SUMS`). Ends with `CAD_OK` or `CAD_FAIL <reason>`.

| Script | Purpose |
|---|---|
| `dwg_census.py <file.dwg\|dxf> [--out DIR]` | DWG→DXF (LibreDWG) + inventory: version, units, extents, layers, entity census, layouts, blocks with nested reference counts, attributes, all text, xrefs, proxy/image/hatch gaps, conversion warnings → `census.json/.txt`, `texts.txt`, `blocks.csv`, `warnings.txt` |
| `dwg_render.py <file> [--layout L] [--crop x0 y0 x1 y1 NAME]… [--pdf] [--extents …]` | Draw once, save full sheet + crops + a ≤2000 px viewing copy; auto LOD above 500 k flattened entities |
| `lod_reduce.py <in.dxf> <out.dxf> [--threshold 40]` | Level-of-detail working copy for >50 MB drawings (nested detail blocks → extents boxes) |
| `clean_export.py <work.dxf> <out.dxf> [--r2013]` | Re-host into a fresh ezdxf document for delivery: tables, blocks, all layouts, and dimensions re-bound to new geometry blocks (the ezdxf 1.4 importer copies DIMENSION entities without their anonymous `*D` blocks, and `audit()` then removes them); `audit()` must be 0/0; reports entity types the importer cannot carry |
| `compare_plot.py <render.png> <plot.pdf>` | Grid ink comparison of a render against the client's PDF plot; red cells = content missing from the render; exit 1 when anything is missing |
| `selftest.sh` | Runs the whole chain on `fixtures/example_2018.dwg` and checks it against `fixtures/expected.json` → `SELFTEST_OK` |

`cadlib.py` holds the shared helpers (LibreDWG call, warning summary, flattened block counts, the `_update_header_vars` patch that keeps LibreDWG-converted documents saveable as working copies).

Capability boundary: **read any DWG/DXF, write DXF only.** DXF (AC1032) opens natively in AutoCAD, BricsCAD, ZWCAD, DraftSight and QCAD; the recipient does *Save As → DWG* when a DWG is required. LibreDWG's DWG writer is not deliverable-grade and is never used; ODA File Converter is excluded (commercial use requires ODA membership).

Known gaps, stated in every hand-over: AEC objects (AutoCAD MEP/Civil 3D) arrive as proxy entities with graphics only; IMAGE/OLE are never rendered; hatches from LibreDWG conversion are unreliable (rendered with IGNORE by default); the ezdxf importer drops REGION, 3DSOLID, WIPEOUT, TOLERANCE, MULTILEADER, MLINE, LIGHT and similar on clean export (listed by the script).

### Fixture
`cad/fixtures/example_2018.dwg` is `test/test-data/example_2018.dwg` from the [LibreDWG](https://www.gnu.org/software/libredwg/) test suite, GPL-3.0-or-later, used unmodified for the self-test only.

### Updating
Edit a script → run `bash cad/selftest.sh` → regenerate `cad/SHA256SUMS` (`cd cad && sha256sum *.py *.sh > SHA256SUMS`) → commit. A checksum mismatch makes `bootstrap.sh` refuse the scripts.

## libredwg-0.14-ubuntu2404-x64-min.tar.gz
`dwg2dxf`, `dwgread`, `dwglayers` built from the **unmodified** GNU LibreDWG 0.14 source (GPL-3) on Ubuntu 24.04 x64, static, stripped. SHA-256 `24801bc22c36730d6cd519da51424c65aa78cb95317cb4227429691371624252`. Source tarball, reproducible build script and the byte-comparison record are in `libredwg/` (`SOURCE.md`). Environments whose egress policy blocks `raw.githubusercontent.com` cannot use the bootstrap; there, `libredwg/build-libredwg.sh` against the GNU mirror, or a registry-hosted build, is the route.
