# Provenance of libredwg-0.14-ubuntu2404-x64-min.tar.gz

- Program: GNU LibreDWG 0.14 — https://www.gnu.org/software/libredwg/ — GPL-3.0-or-later.
- Source: `libredwg-0.14.tar.xz` in this folder, byte-identical to https://ftp.gnu.org/gnu/libredwg/libredwg-0.14.tar.xz,
  SHA-256 `62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275`. **No source modifications.**
- Build: `build-libredwg.sh` (configure `--disable-bindings --disable-python --disable-shared --enable-static`, Ubuntu 24.04 x64, gcc 13, `strip`).
- Reproducibility check, 2026-09-22: a fresh build with that script differs from the published `dwg2dxf`, `dwgread`
  and `dwglayers` only in the 20-byte `NT_GNU_BUILD_ID` note (bytes 889–908 of each file); every other byte is identical.
  Published tarball SHA-256 `24801bc22c36730d6cd519da51424c65aa78cb95317cb4227429691371624252`.
- The corresponding source is provided here to meet GPL-3 §6 for the binaries.
