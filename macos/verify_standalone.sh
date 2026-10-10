#!/bin/bash
# Checks a macos/build_standalone.sh zip the way a friend's Mac would meet it (2026-10-10):
# unzipped into a temp directory and run in a CLEAN environment -- an empty HOME, a PATH of
# /usr/bin:/bin only (no Homebrew, no venv, no uv), the app's config/data pointed at temp
# directories. No network is used. Exits non-zero on any failure, with a PASS/FAIL summary.
#
#   macos/verify_standalone.sh [path/to/TeetimeMonitor-<version>-arm64.zip]
#
# Default: the newest zip in macos/dist. Not covered here (needs a second Mac): Gatekeeper's
# first-launch prompt for a downloaded, quarantined, not-notarized app, and macOS 14 itself.
set -uo pipefail
cd "$(dirname "$0")"
MACOS_DIR=$(pwd -P)
REPO=$(cd .. && pwd -P)
REAL_HOME=$HOME

ZIP=${1:-$(ls -t "$MACOS_DIR"/dist/TeetimeMonitor-*-arm64.zip 2>/dev/null | head -1)}
[ -n "$ZIP" ] && [ -f "$ZIP" ] || { echo "error: no zip given and none in macos/dist (run macos/build_standalone.sh)" >&2; exit 2; }
ZIP=$(cd "$(dirname "$ZIP")" && pwd -P)/$(basename "$ZIP")

TMP=$(mktemp -d "${TMPDIR:-/tmp}/tm-verify.XXXXXX") || exit 2
TMP=$(cd "$TMP" && pwd -P)
APP_PID=""
cleanup() {
    [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null
    pkill -f "^$TMP/unzipped/TeetimeMonitor.app/Contents/MacOS/TeetimeMonitor" 2>/dev/null
    rm -rf "$TMP"
}
trap cleanup EXIT

PASSED=0
FAILED=0
WARNED=0
RESULTS=()
pass() { PASSED=$((PASSED + 1)); RESULTS+=("PASS  $1"); echo "PASS  $1"; }
fail() { FAILED=$((FAILED + 1)); RESULTS+=("FAIL  $1${2:+ -- $2}"); echo "FAIL  $1${2:+ -- $2}"; }
check() { # check "name" command...   (stdout/stderr of the command go to $TMP/last.out)
    local name=$1; shift
    if "$@" >"$TMP/last.out" 2>&1; then pass "$name"; else fail "$name" "$(head -c 400 "$TMP/last.out" | tr '\n' ' ')"; fi
}

# The clean environment every app command below runs in.
HOME_DIR="$TMP/home"; CFG="$TMP/cfg"; DATA="$TMP/data"
mkdir -p "$HOME_DIR" "$CFG" "$DATA"
clean() { env -i HOME="$HOME_DIR" PATH=/usr/bin:/bin TEETIME_MONITOR_CONFIG_DIR="$CFG" TEETIME_MONITOR_DATA_DIR="$DATA" "$@"; }

echo "==> unzip $(basename "$ZIP")"
mkdir -p "$TMP/unzipped"
ditto -x -k "$ZIP" "$TMP/unzipped" || { echo "error: cannot unzip" >&2; exit 2; }
APP="$TMP/unzipped/TeetimeMonitor.app"
[ -d "$APP" ] || { echo "error: no TeetimeMonitor.app inside the zip" >&2; exit 2; }
RES="$APP/Contents/Resources"
BIN="$RES/bin"
PY="$RES/python/bin/python3"
VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist")
STAMP="$TMP/stamp"; touch "$STAMP"

# (0) the checksum next to the zip, when there is one
if [ -f "$ZIP.sha256" ]; then
    check "sha256 file matches the zip" bash -c "cd '$(dirname "$ZIP")' && shasum -a 256 -c '$(basename "$ZIP").sha256'"
fi

# (1) signature
check "codesign --verify --deep --strict" codesign --verify --deep --strict "$APP"
check "ad-hoc signature, no hardened runtime" bash -c "codesign -dv '$APP' 2>&1 | grep -q 'Signature=adhoc' && ! codesign -dv '$APP' 2>&1 | grep -q 'flags=.*runtime'"

# Architecture and minimum macOS of the app itself
check "app binary is arm64-only" bash -c "[ \"\$(lipo -archs '$APP/Contents/MacOS/TeetimeMonitor')\" = arm64 ]"
check "app binary targets macOS 14.0" bash -c "otool -l '$APP/Contents/MacOS/TeetimeMonitor' | awk '/LC_BUILD_VERSION/{f=1} f&&/minos/{print \$2; exit}' | grep -qx 14.0"
check "Info.plist: macOS 14.0 minimum" bash -c "[ \"\$(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' '$APP/Contents/Info.plist')\" = 14.0 ]"

# (2) version and doctor from the bundled bin alone
clean "$BIN/teetime-monitor" --version >"$TMP/version.out" 2>&1
if [ "$(cat "$TMP/version.out")" = "teetime-monitor $VERSION" ]; then pass "teetime-monitor --version = $VERSION"; else fail "teetime-monitor --version" "got: $(head -c 200 "$TMP/version.out")"; fi
clean "$BIN/teetime-monitor" --doctor --offline >"$TMP/doctor.out" 2>&1
doctor_status=$?
if [ $doctor_status -eq 0 ]; then pass "--doctor --offline exits 0"; else fail "--doctor --offline" "exit $doctor_status: $(grep -E '^\[FAIL' "$TMP/doctor.out" | head -c 300)"; fi
if grep -E '^\[INFO\] +Python ' "$TMP/doctor.out" | grep -qF "$RES/python/"; then
    pass "doctor reports the bundled Python ($(grep -E '^\[INFO\] +Python ' "$TMP/doctor.out" | sed -E 's/.*Python +//'))"
else
    fail "doctor reports the bundled Python" "$(grep -E 'Python' "$TMP/doctor.out" | head -2 | tr '\n' ' ')"
fi
check "doctor ran against the temp folders" bash -c "grep -q 'Config folder.*$CFG' '$TMP/doctor.out' && grep -q 'Data folder.*$DATA' '$TMP/doctor.out'"

# The shipped dependencies are the locked ones (uv.lock), the set CI tests -- not today's PyPI.
check "installed package versions match uv.lock" clean "$PY" -I - "$REPO/uv.lock" <<'PYEOF'
import importlib.metadata
import re
import sys
import tomllib

locked = {re.sub(r"[-_.]+", "-", p["name"]).lower(): p["version"] for p in tomllib.load(open(sys.argv[1], "rb"))["package"]}
bad = []
count = 0
for dist in importlib.metadata.distributions():
    name = re.sub(r"[-_.]+", "-", dist.metadata["Name"]).lower()
    if name == "teetime-monitor":
        continue
    count += 1
    if locked.get(name) != dist.version:
        bad.append(f"{name} {dist.version} (lock: {locked.get(name)})")
if bad or not count:
    sys.exit("differs from uv.lock: " + "; ".join(bad))
print(f"{count} packages, all as locked")
PYEOF

# (3) every launcher in Resources/bin runs, and the set equals pyproject's [project.scripts]
expected=$(clean "$PY" -I -c 'import sys, tomllib; print("\n".join(sorted(tomllib.load(open(sys.argv[1], "rb"))["project"]["scripts"])))' "$REPO/pyproject.toml" 2>/dev/null)
actual=$(ls "$BIN" | sort)
if [ -n "$expected" ] && [ "$expected" = "$actual" ]; then pass "launchers = pyproject [project.scripts] ($(echo "$actual" | wc -l | tr -d ' '))"; else fail "launchers = pyproject [project.scripts]" "expected: $(echo $expected) / found: $(echo $actual)"; fi
for launcher in $actual; do
    case $launcher in
        teetime-monitor) args=(--version) ;;
        teetime-monitor-scrape) args=(--help) ;;
        # The helpers' contract is stdin JSON in, stdout JSON out, with no --help; with no
        # arguments and nothing on stdin each must answer with its own JSON error object.
        *) args=() ;;
    esac
    clean "$BIN/$launcher" "${args[@]+"${args[@]}"}" </dev/null >"$TMP/l.out" 2>"$TMP/l.err"
    code=$?
    case $launcher in
        teetime-monitor|teetime-monitor-scrape)
            if [ $code -eq 0 ] && [ -s "$TMP/l.out" ]; then pass "launcher $launcher ${args[*]}"; else fail "launcher $launcher ${args[*]}" "exit $code $(head -c 200 "$TMP/l.err")"; fi ;;
        *)
            if grep -q Traceback "$TMP/l.err"; then
                fail "launcher $launcher (no args)" "$(tail -3 "$TMP/l.err" | tr '\n' ' ')"
            elif clean "$PY" -I -c 'import json, sys; o = json.loads(sys.stdin.read().strip().splitlines()[-1]); sys.exit(0 if isinstance(o, dict) else 1)' <"$TMP/l.out" 2>/dev/null; then
                pass "launcher $launcher (answers with JSON, exit $code)"
            else
                fail "launcher $launcher (no args)" "exit $code, stdout: $(head -c 200 "$TMP/l.out") stderr: $(head -c 200 "$TMP/l.err")"
            fi ;;
    esac
done

# (4) end to end, no network: a fixture database written by the BUNDLED python through the
# project's own storage API, then the bundled picks launcher against the development
# environment's `python -m src.picks_cli` with the same arguments.
TODAY=$(date +%Y-%m-%d)
FROM=$(date -v+1d +%Y-%m-%d)
DB="$DATA/0000001.db"
COURSE="18 Loch Tee 1"
clean "$PY" -I -B - "$DB" "$COURSE" "$TODAY" <<'PYEOF' >"$TMP/fixture.out" 2>&1
import sys
from datetime import date, timedelta

from src import global_preferences, paths, storage
from src.models import Schedule, Slot, SunTimes, WeatherPoint

db, course, today = sys.argv[1:4]
paths.ensure_dirs()
# Both windows open, so a pick exists whatever weekday tomorrow is.
global_preferences.save_preferences(
    {"availability": {"weekday_window": {"after": None, "before": None}, "weekend_window": {"after": None, "before": None}}}
)
base = date.fromisoformat(today)
times = ["08:10", "09:10", "10:10", "13:00", "15:00"]
for offset in (1, 2, 3):
    day = (base + timedelta(days=offset)).isoformat()
    slots = [Slot(time=t, booked=(4 if t == "09:10" else (offset % 3)), capacity=4) for t in times]
    weather = [
        WeatherPoint(time=t, precipitation_probability=5 if t < "12:00" else 60, precipitation_mm=0.0, wind_speed_kph=8.0,
                     temperature_c=14.0 + i, weather_code=1)
        for i, t in enumerate(times)
    ]
    storage.save_schedule(
        Schedule(date=day, course=course, slots=slots, weather=weather, sun_times=SunTimes(sunrise="07:30", sunset="19:30")),
        path=__import__("pathlib").Path(db),
    )
print("fixture ok")
PYEOF
if [ "$(cat "$TMP/fixture.out")" = "fixture ok" ] && [ -s "$DB" ]; then pass "fixture database written by the bundled python"; else fail "fixture database" "$(head -c 400 "$TMP/fixture.out")"; fi

PICKS_ARGS=(--db-path "$DB" --course "$COURSE" --from "$FROM" --days 3)
clean "$BIN/teetime-monitor-picks" "${PICKS_ARGS[@]}" </dev/null >"$TMP/picks.bundled" 2>"$TMP/picks.bundled.err"
bundled_status=$?
# The development side keeps the real PATH/HOME (uv and its cache live there); only the app's
# own folders are redirected, so it reads exactly the same fixture and preferences.
if command -v uv >/dev/null; then
    (cd "$REPO" && env TEETIME_MONITOR_CONFIG_DIR="$CFG" TEETIME_MONITOR_DATA_DIR="$DATA" uv run python -m src.picks_cli "${PICKS_ARGS[@]}") \
        </dev/null >"$TMP/picks.dev" 2>"$TMP/picks.dev.err"
    dev_status=$?
else
    dev_status=127; echo "uv not found" >"$TMP/picks.dev.err"
fi
if [ $bundled_status -ne 0 ] || [ $dev_status -ne 0 ]; then
    fail "picks: bundled vs development output" "exit bundled=$bundled_status dev=$dev_status: $(head -c 300 "$TMP/picks.bundled.err") $(head -c 300 "$TMP/picks.dev.err")"
else
    clean "$PY" -I - "$TMP/picks.bundled" "$TMP/picks.dev" "$FROM" <<'PYEOF' >"$TMP/picks.cmp" 2>&1
import json
import sys

bundled = json.load(open(sys.argv[1]))
dev = json.load(open(sys.argv[2]))
if bundled != dev:
    sys.exit(f"outputs differ:\n bundled: {json.dumps(bundled, sort_keys=True)[:600]}\n dev:     {json.dumps(dev, sort_keys=True)[:600]}")
days = [key for key in bundled if not key.startswith("_")]
if len(days) != 3 or days[0] != sys.argv[3]:
    sys.exit(f"unexpected date keys {days}")
picked = [key for key in days if bundled[key] and bundled[key].get("time")]
if not picked:
    sys.exit(f"no day has a pick -- the comparison would prove nothing: {bundled}")
print(f"identical; picks: " + ", ".join(f"{key} {bundled[key]['time']}" for key in picked))
PYEOF
    if [ $? -eq 0 ]; then pass "picks: bundled output identical to development ($(cat "$TMP/picks.cmp"))"; else fail "picks: bundled vs development output" "$(head -c 700 "$TMP/picks.cmp")"; fi
fi

# (5) static checks: nothing in the bundle may name this machine or Homebrew.
BUILD_HOME_PREFIX=$(echo "$REPO" | sed -E 's#^(/Users/[^/]+).*#\1#')
# Two library files mention these strings in documentation only (a Windows path in a docstring,
# platformdirs' note on $HOMEBREW_PREFIX); they are the only allowed hits.
ALLOWED_TEXT='lib/python3.12/ntpath.py|lib/python3.12/site-packages/platformdirs/macos.py'
text_hits=$(grep -rIl -e '/opt/homebrew' -e '/Users/' -e "$REPO" "$APP" 2>/dev/null | sed "s#^$APP/Contents/Resources/python/##; s#^$APP/##" | grep -vE "^($ALLOWED_TEXT)$")
if [ -z "$text_hits" ]; then pass "no launcher or text file names /opt/homebrew, /Users/ or the repo path"; else fail "text files naming /opt/homebrew, /Users/ or the repo path" "$(echo "$text_hits" | head -8 | tr '\n' ' ')"; fi
# Binaries: bytecode and Mach-O must not carry the repo path or the build user's home. The app's
# own executable legitimately contains the literal /opt/homebrew/bin (the Homebrew install's
# search directory), so only it is exempt from that one string.
bin_hits=$(grep -rl -e "$REPO" -e "$BUILD_HOME_PREFIX/" "$APP" 2>/dev/null | sed "s#^$APP/##")
# Same two documentation hits as bytecode, plus the cryptography wheel's statically linked
# OpenSSL, whose compiled-in default config directory is the builder's Homebrew path
# (OPENSSLDIR); nothing here uses it -- HTTPS trust comes from the macOS keychain (src/net.py).
ALLOWED_BINARY='lib/python3.12/site-packages/platformdirs/__pycache__/macos.cpython-312.pyc|lib/python3.12/site-packages/cryptography/hazmat/bindings/_rust.abi3.so'
bin_hits="$bin_hits $(grep -rl -e '/opt/homebrew' "$APP/Contents/Resources" 2>/dev/null | sed "s#^$APP/Contents/Resources/python/##; s#^$APP/##" | grep -vE "^($ALLOWED_BINARY|$ALLOWED_TEXT)$")"
bin_hits=$(echo $bin_hits)
if [ -z "$bin_hits" ]; then pass "no binary file (Mach-O, bytecode) names /opt/homebrew, the repo path or the build user's home"; else fail "binary files naming /opt/homebrew, the repo path or the build user's home" "$(echo "$bin_hits" | tr ' ' '\n' | head -8 | tr '\n' ' ')"; fi
bad_links=""
macho=$(find "$RES/python" "$APP/Contents/MacOS" -type f \( -name '*.so' -o -name '*.dylib' -o -perm +111 \) -print0 | xargs -0 file | grep -E ': +Mach-O' | sed -E 's/: +Mach-O.*//')
macho_count=$(echo "$macho" | wc -l | tr -d ' ')
while IFS= read -r file; do
    [ -n "$file" ] || continue
    # Every dependency must be a system library or relative to the file itself.
    links=$(otool -L "$file" | tail -n +2 | awk '{print $1}' | grep -vE '^(/usr/lib/|/System/Library/|@loader_path/|@executable_path/|@rpath/)' || true)
    [ -n "$links" ] && bad_links="$bad_links ${file#$APP/}: $(echo $links)"
done <<<"$macho"
if [ -z "$bad_links" ]; then pass "otool -L: $macho_count Mach-O files link only system libraries (none to /opt/homebrew or /usr/local)"; else fail "otool -L found non-system links" "$bad_links"; fi
check "every Mach-O is arm64-only" bash -c "echo \"$macho\" | while IFS= read -r f; do [ \"\$(lipo -archs \"\$f\")\" = arm64 ] || { echo \"\$f\"; exit 1; }; done"

# (6) the app itself starts and stays up, started the way a friend starts it: through Launch
# Services (`open -n`), with the clean folders passed as --env. On a CI runner without a usable
# GUI session this cannot be told apart from a broken app, and the zip itself is fine, so
# there (GITHUB_ACTIONS set) a failure is reported as WARN and does not block the upload.
mkdir -p "$TMP/home/Library"
APP_BIN="$APP/Contents/MacOS/TeetimeMonitor"
open -n --env HOME="$HOME_DIR" --env TEETIME_MONITOR_CONFIG_DIR="$CFG" --env TEETIME_MONITOR_DATA_DIR="$DATA" "$APP" >"$TMP/app.out" 2>&1
sleep 5
APP_PID=$(pgrep -f "^$APP_BIN" | head -1)
if [ -n "$APP_PID" ] && kill -0 "$APP_PID" 2>/dev/null; then
    pass "TeetimeMonitor.app (open -n) is still running after 5 s"
elif [ -n "${GITHUB_ACTIONS:-}" ]; then
    WARNED=$((WARNED + 1)); RESULTS+=("WARN  TeetimeMonitor.app did not stay running under open -n (CI runner: not blocking)")
    echo "WARN  TeetimeMonitor.app did not stay running under open -n (CI runner: not blocking) $(head -c 300 "$TMP/app.out")"
else
    fail "TeetimeMonitor.app (open -n) is still running after 5 s" "$(head -c 300 "$TMP/app.out")"
fi
crash=$(find "$REAL_HOME/Library/Logs/DiagnosticReports" -maxdepth 2 -name 'TeetimeMonitor*' -newer "$STAMP" 2>/dev/null | head -3)
if [ -z "$crash" ]; then pass "no crash report written"; else fail "crash report written" "$crash"; fi
[ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null
sleep 1
APP_PID=""

# The bundle is sealed: nothing above (launchers, picks, doctor, the app) may have written to it.
check "bundle untouched by all of the above (signature still valid)" codesign --verify --deep --strict "$APP"
new_files=$(find "$APP" -newer "$STAMP" 2>/dev/null | head -5)
if [ -z "$new_files" ]; then pass "no file in the bundle was created or modified during the run"; else fail "files changed inside the bundle" "$new_files"; fi

echo
echo "zip        $(du -h "$ZIP" | cut -f1) ($(basename "$ZIP"))"
echo "unzipped   $(du -sh "$APP" | cut -f1)"
echo "version    $VERSION   python $(clean "$PY" -I -c 'import platform; print(platform.python_version())')"
echo
echo "---- summary ----"
printf '%s\n' "${RESULTS[@]}" | grep -E '^(FAIL|WARN)' || true
if [ "$FAILED" -eq 0 ]; then echo "PASS: all $PASSED checks passed$([ "$WARNED" -gt 0 ] && echo " ($WARNED warning)")"; exit 0; fi
echo "FAIL: $FAILED of $((PASSED + FAILED)) checks failed"
exit 1
