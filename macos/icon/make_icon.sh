#!/bin/bash
# Regenerates icon/TeetimeMonitor.icns from make_icon.swift (needs only the Command
# Line Tools + macOS's iconutil). Commit the resulting .icns -- build.sh just copies it.
set -euo pipefail
cd "$(dirname "$0")"
swiftc -O -o /tmp/make_icon make_icon.swift
/tmp/make_icon icon_1024.png
SET=TeetimeMonitor.iconset
rm -rf "$SET" && mkdir "$SET"
for s in 16 32 128 256 512; do
  sips -z $s $s icon_1024.png --out "$SET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) icon_1024.png --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o TeetimeMonitor.icns
rm -rf "$SET"
echo "wrote icon/TeetimeMonitor.icns"
