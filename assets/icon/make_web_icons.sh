#!/bin/bash
# Regenerates the web UI's icons (src/webui/static/icons/*.png) from the Teetime Monitor icon artwork (make_icon.swift), edge to edge
# (iOS rounds the corners itself). Needs only the Command Line Tools. Commit the resulting PNGs.
set -euo pipefail
cd "$(dirname "$0")"
OUT=../../src/webui/static/icons
mkdir -p "$OUT"
swiftc -O -o /tmp/make_icon make_icon.swift
/tmp/make_icon /tmp/icon_bleed_1024.png --full-bleed
for s in 32 64 180 192 512; do
  sips -z $s $s /tmp/icon_bleed_1024.png --out "$OUT/icon-$s.png" >/dev/null
done
mv "$OUT/icon-180.png" "$OUT/apple-touch-icon.png"
echo "wrote $OUT/*.png"
