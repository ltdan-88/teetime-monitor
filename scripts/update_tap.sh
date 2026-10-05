#!/usr/bin/env bash
# Point the Homebrew tap's formula at a released tag: bump url + sha256, commit, push.
# Used by .github/workflows/release.yml (with a token) and by hand:
#   scripts/update_tap.sh 0.66.0 [path/to/homebrew-teetime-monitor]
# Idempotent: exits 0 without committing when the formula is already at that version.
set -euo pipefail

version="${1:?usage: update_tap.sh <version> [tap-dir]}"
tap="${2:-/opt/homebrew/Library/Taps/ltdan-88/homebrew-teetime-monitor}"
formula="$tap/Formula/teetime-monitor.rb"
url="https://github.com/ltdan-88/teetime-monitor/archive/refs/tags/v${version}.tar.gz"

[ -f "$formula" ] || { echo "formula not found: $formula" >&2; exit 1; }

# The tag tarball can lag the tag push by a few seconds; retry before giving up.
sha=""
for attempt in 1 2 3 4 5 6; do
  if sha=$(curl -fsSL "$url" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())') && [ -n "$sha" ]; then
    break
  fi
  sleep 5
done
[ -n "$sha" ] || { echo "could not download $url" >&2; exit 1; }

python3 - "$formula" "$url" "$sha" <<'PY'
import re, sys
path, url, sha = sys.argv[1:4]
text = open(path, encoding="utf-8").read()
new = re.sub(r'(?m)^(\s*url ")[^"]*(")', lambda m: f'{m.group(1)}{url}{m.group(2)}', text, count=1)
new = re.sub(r'(?m)^(\s*sha256 ")[0-9a-f]{64}(")', lambda m: f'{m.group(1)}{sha}{m.group(2)}', new, count=1)
open(path, "w", encoding="utf-8").write(new)
PY

cd "$tap"
if git diff --quiet -- Formula/teetime-monitor.rb; then
  echo "formula already at v${version}"
  exit 0
fi
git add Formula/teetime-monitor.rb
git commit -q -m "teetime-monitor ${version}"
git push -q
echo "tap updated to v${version} (sha256 ${sha})"
