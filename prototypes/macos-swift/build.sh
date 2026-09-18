#!/bin/bash
# Builds a double-clickable .app with nothing but the Command Line Tools --
# no Xcode, no dependencies, no package manager. See README.md.
set -euo pipefail
cd "$(dirname "$0")"
APP="TeetimeMonitor.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -parse-as-library -O -o "$APP/Contents/MacOS/TeetimeMonitor" Sources/*.swift
# The bundled club-directory snapshot (add-a-club's offline fallback, see
# ClubDirectoryStore.swift) -- a static data file, not code, so it's copied in
# rather than compiled. Same file the Python package ships as src/
# club_directory_seed.json; kept in sync by hand, same tradeoff as duplicating
# theme.py's CUSTOM_THEMES hex values into Theme.swift already is.
cp ../../src/club_directory_seed.json "$APP/Contents/Resources/club_directory_seed.json"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>TeetimeMonitor</string>
  <key>CFBundleDisplayName</key><string>teetime-monitor</string>
  <key>CFBundleIdentifier</key><string>dev.local.teetime.prototype</string>
  <key>CFBundleExecutable</key><string>TeetimeMonitor</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --sign - "$APP" >/dev/null 2>&1
echo "built $APP"
