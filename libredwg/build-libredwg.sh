#!/usr/bin/env bash
# Reproducible build of the prebuilt LibreDWG binaries published in this repo.
# Source: GNU LibreDWG 0.14, unmodified. https://ftp.gnu.org/gnu/libredwg/libredwg-0.14.tar.xz
# Verified 2026-09-22: a fresh build with this script on Ubuntu 24.04 x64 (gcc 13) reproduces the
# published dwg2dxf / dwgread / dwglayers byte-for-byte except the 20-byte NT_GNU_BUILD_ID note.
set -eu
SRC_SHA="62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275"
W="$(mktemp -d)"; cd "$W"
cp "$(dirname "$0")/libredwg-0.14.tar.xz" . 2>/dev/null || curl -sSL -o libredwg-0.14.tar.xz https://ftp.gnu.org/gnu/libredwg/libredwg-0.14.tar.xz
echo "$SRC_SHA  libredwg-0.14.tar.xz" | sha256sum -c
tar xf libredwg-0.14.tar.xz && cd libredwg-0.14
./configure --prefix="$W/prefix" --disable-bindings --disable-python --disable-shared --enable-static
make -j"$(nproc)" && make install
mkdir -p "$W/ldwg-min"
for b in dwg2dxf dwgread dwglayers; do cp "$W/prefix/bin/$b" "$W/ldwg-min/" && strip "$W/ldwg-min/$b"; done
tar czf "$W/libredwg-0.14-ubuntu2404-x64-min.tar.gz" -C "$W" ldwg-min
sha256sum "$W/libredwg-0.14-ubuntu2404-x64-min.tar.gz"
echo "output: $W/libredwg-0.14-ubuntu2404-x64-min.tar.gz"
