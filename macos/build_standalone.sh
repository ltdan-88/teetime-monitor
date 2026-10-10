#!/bin/bash
# Builds the self-contained Mac app for friends who have no Homebrew, no Python and no
# terminal (2026-10-10): macos/dist/TeetimeMonitor-<version>-arm64.zip, holding
# TeetimeMonitor.app with its own Python runtime and this backend inside. Apple Silicon only,
# macOS 14+, ad-hoc signed (no Apple Developer account, so NOT notarized: the first launch on
# another Mac needs right-click -> Open, see docs/MAC-APP.md).
#
# Needs: the Command Line Tools (swiftc, codesign, ditto) and uv (https://docs.astral.sh/uv/).
# Downloads python-build-standalone via `uv python install` and the project's dependency
# wheels from PyPI; nothing else touches the network. Idempotent: the work directory is
# wiped and rebuilt every time. The Homebrew install path is untouched -- this script only
# stages a COPY of the app that build.sh makes, so macos/TeetimeMonitor.app stays as it was.
#
#   macos/build_standalone.sh            -> macos/dist/TeetimeMonitor-<v>-arm64.zip (+ .sha256)
#   PYTHON_SERIES=3.12 (default)         which CPython minor version to embed
#   macos/verify_standalone.sh           -> checks the result in a clean environment
set -euo pipefail
cd "$(dirname "$0")"
MACOS_DIR=$(pwd -P)
REPO=$(cd .. && pwd -P)
STARTED=$(date +%s)
# The build runs the embedded python several times; none of those runs may leave bytecode
# behind (it would carry the build directory in its file names). Bytecode is made once, below.
export PYTHONDONTWRITEBYTECODE=1

PYTHON_SERIES=${PYTHON_SERIES:-3.12}
# build.sh passes this to swiftc: without it the binary's minimum macOS is whatever the
# BUILD machine runs (a macos-latest runner is newer than 14), and a friend on macOS 14
# would get "requires a newer version of macOS" however LSMinimumSystemVersion reads.
export TEETIME_MONITOR_SWIFT_TARGET=${TEETIME_MONITOR_SWIFT_TARGET:-arm64-apple-macosx14.0}

if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
    echo "error: this builds an Apple Silicon app and must run on an Apple Silicon Mac (got $(uname -s) $(uname -m); a Rosetta shell counts as x86_64)" >&2
    exit 1
fi
for tool in uv swiftc codesign ditto lipo otool shasum; do
    command -v "$tool" >/dev/null || { echo "error: $tool not found" >&2; exit 1; }
done

VERSION=$(grep -m1 '^version = ' ../pyproject.toml | sed -E 's/version = "(.*)"/\1/')
WORK="$MACOS_DIR/build-standalone"
DIST="$MACOS_DIR/dist"
STAGE="$WORK/stage"
APP="$STAGE/TeetimeMonitor.app"
RES="$APP/Contents/Resources"
PYDIR="$RES/python"
ZIP="$DIST/TeetimeMonitor-$VERSION-arm64.zip"

echo "==> TeetimeMonitor $VERSION (arm64, standalone)"
rm -rf "$WORK"
mkdir -p "$STAGE" "$DIST"
# Resolved before anything below can fail halfway and leave a stale zip next to a new build.
rm -f "$ZIP" "$ZIP.sha256"

# (a) The ordinary app, exactly as Homebrew builds it, then a private copy to extend.
echo "==> build.sh"
./build.sh >/dev/null
ditto TeetimeMonitor.app "$APP"

# (b) A relocatable arm64 CPython (python-build-standalone, fetched by uv). --no-bin: do not
# put shims in ~/.local/bin; --install-dir: keep it out of the user's own uv cache of Pythons.
echo "==> embedded CPython $PYTHON_SERIES"
uv python install "$PYTHON_SERIES" --install-dir "$WORK/pbs" --no-bin >/dev/null
PBS=$(find "$WORK/pbs" -maxdepth 1 -type d -name "cpython-$PYTHON_SERIES.*-macos-aarch64-none" | sort | tail -1)
[ -n "$PBS" ] || { echo "error: no arm64 CPython $PYTHON_SERIES installed by uv" >&2; exit 1; }
ditto "$PBS" "$PYDIR"
PY="$PYDIR/bin/python3"
[ "$(lipo -archs "$PYDIR/bin/python$PYTHON_SERIES")" = arm64 ] || { echo "error: embedded python is not arm64-only" >&2; exit 1; }

# Strip what a read-only, app-private runtime never uses: tests, IDLE, Tk, demos, the
# build-time config, docs, headers, pip. `encodings` stays whole (a missing codec is a
# crash that only some machines/locales would find).
(
    cd "$PYDIR"
    L="lib/python$PYTHON_SERIES"
    # libpython3.12.dylib is for programs that EMBED Python; the interpreter itself is
    # statically linked (otool -L python3.12 names no libpython), 17 MB of dead weight.
    rm -rf include share lib/pkgconfig lib/libpython*.dylib lib/itcl* lib/tcl* lib/tk* lib/thread* lib/libtcl* lib/libtk* \
        "$L/test" "$L/idlelib" "$L/idle_test" "$L/tkinter" "$L/turtledemo" "$L/turtle.py" "$L/lib2to3" \
        "$L/ensurepip" "$L/pydoc_data" "$L/config-"* "$L/lib-dynload/_tkinter"* \
        "$L/site-packages/pip" "$L/site-packages/pip-"*.dist-info "$L/unittest/test" \
        "$L/distutils/tests" "$L/__pycache__"
    # Every console script in python's own bin/ has an absolute build-machine shebang or
    # belongs to a tool we dropped; only the interpreter stays. Our launchers are in ../bin.
    find bin -mindepth 1 ! -name "python" ! -name "python3" ! -name "python$PYTHON_SERIES" -delete
    find . -name "__pycache__" -type d -prune -exec rm -rf {} +
)

# (c) This project, non-editable, runtime dependencies only (no [dev] extra), built from a
# COPY of the sources so setuptools' build/ and egg-info never land in the working tree.
echo "==> installing teetime-monitor $VERSION and its dependencies"
SRC="$WORK/src"
mkdir -p "$SRC"
cp "$REPO/pyproject.toml" "$REPO/README.md" "$REPO/LICENSE" "$SRC/"
ditto "$REPO/src" "$SRC/src"
find "$SRC" -name "__pycache__" -type d -prune -exec rm -rf {} +
# The marker uv ships says "managed by uv, do not modify" -- true for a user's install, not
# for this one build step, hence the flag; the marker file itself stays in the bundle.
# The dependencies come from uv.lock -- the exact set CI tests and `uv run` uses -- not from
# whatever PyPI resolves today (an unlocked install once shipped anthropic 1.13 / pydantic 2.14
# next to a lock of 1.7 / 2.13.5). --frozen: never rewrite the lock; --no-hashes: the pins
# alone are enough here and keep uv's installer from demanding hashes for the project itself.
uv export --frozen --no-dev --no-emit-project --no-hashes --no-header --quiet -o "$WORK/requirements.txt"
[ -s "$WORK/requirements.txt" ] || { echo "error: uv export produced no requirements from uv.lock" >&2; exit 1; }
uv pip install --python "$PY" --break-system-packages --no-cache --quiet -r "$WORK/requirements.txt"
uv pip install --python "$PY" --break-system-packages --no-cache --quiet --no-deps "$SRC"
SP="$PYDIR/lib/python$PYTHON_SERIES/site-packages"
# Console scripts uv wrote into python/bin (absolute shebangs) and the install records that
# name the build directory: neither belongs in a relocatable bundle.
find "$PYDIR/bin" -mindepth 1 ! -name "python" ! -name "python3" ! -name "python$PYTHON_SERIES" -delete
for dist in "$SP"/*.dist-info; do
    rm -f "$dist/direct_url.json"
    [ -f "$dist/RECORD" ] && sed -i '' '/direct_url\.json,/d' "$dist/RECORD"
done
rm -rf "$SP/pip" "$SP"/pip-*.dist-info "$SP"/*.dist-info/sboms
# uv rewrites python's build-time paths to wherever it unpacked the runtime (here: the work
# directory). Nothing reads them at run time, but they would name this machine; put back the
# placeholder python-build-standalone itself uses.
sed -i '' "s#$PBS#/install#g" "$PYDIR/lib/python$PYTHON_SERIES/_sysconfigdata__darwin_darwin.py"
# Our own METADATA carries the whole README as its long description; the bundle needs only
# the header block (Name, Version, Requires-Dist ...), and the README names Homebrew paths.
"$PY" -I - "$SP"/teetime_monitor-*.dist-info/METADATA <<'PYEOF'
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
open(path, "w", encoding="utf-8").write(text.split("\n\n", 1)[0] + "\n")
PYEOF

# (d) One launcher per [project.scripts] entry, derived from pyproject.toml. Each is a tiny
# /bin/sh script that finds the bundle from its own location. -I = isolated mode: no
# PYTHON* variables, no user site, and -- the point -- no current directory on sys.path (a
# bare `python -c` would import a stray ./src from wherever the app happens to be started).
# -B and the two exported variables: the signed bundle must never be written to.
echo "==> launchers"
mkdir -p "$RES/bin"
"$PY" -I - "$REPO/pyproject.toml" "$RES/bin" <<'PYEOF'
import os
import sys
import tomllib

pyproject, bin_dir = sys.argv[1:3]
with open(pyproject, "rb") as handle:
    scripts = tomllib.load(handle)["project"]["scripts"]
TEMPLATE = """#!/bin/sh
# Generated by macos/build_standalone.sh from pyproject.toml [project.scripts]: {name} = {target}
self=$0
while [ -L "$self" ]; do
    link=$(readlink "$self")
    case $link in /*) self=$link ;; *) self=$(dirname "$self")/$link ;; esac
done
here=$(cd "$(dirname "$self")" && pwd -P)
PYTHONNOUSERSITE=1
PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE PYTHONDONTWRITEBYTECODE
exec "$here/../python/bin/python3" -I -B -c 'import sys; sys.argv[0] = "{name}"; from {module} import {function}; sys.exit({function}())' "$@"
"""
for name, target in sorted(scripts.items()):
    module, _, function = target.partition(":")
    if not module or not function.isidentifier():
        sys.exit(f"[project.scripts] {name} = {target!r} is not module:function")
    path = os.path.join(bin_dir, name)
    with open(path, "w", encoding="utf-8") as out:
        out.write(TEMPLATE.format(name=name, target=target, module=module, function=function))
    os.chmod(path, 0o755)
    print(f"  {name} -> {target}")
PYEOF

# (e) Bytecode now, at build time: first runs are fast and, the bundle being sealed by the
# signature, nothing may be written there later. unchecked-hash = never compared with the
# source's mtime (which a zip round trip does not promise to keep); -s drops the build
# directory from the file names stored inside.
echo "==> bytecode"
find "$PYDIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
"$PY" -I -m compileall -q -f -j 0 --invalidation-mode unchecked-hash -s "$PYDIR" -p /Resources/python "$PYDIR/lib" >/dev/null

# (g) Info.plist: build.sh already writes LSMinimumSystemVersion and the pyproject version;
# confirm rather than assume, so a future edit to build.sh cannot silently ship a wrong one.
PLIST="$APP/Contents/Info.plist"
plist() { /usr/libexec/PlistBuddy -c "Print :$1" "$PLIST"; }
[ "$(plist LSMinimumSystemVersion)" = "14.0" ] || { echo "error: LSMinimumSystemVersion is not 14.0" >&2; exit 1; }
[ "$(plist CFBundleShortVersionString)" = "$VERSION" ] || { echo "error: CFBundleShortVersionString is not $VERSION" >&2; exit 1; }
[ "$(plist CFBundleVersion)" = "$VERSION" ] || { echo "error: CFBundleVersion is not $VERSION" >&2; exit 1; }
# The binary's own minimum OS (what the kernel/dyld enforce), not just the plist's promise.
minos=$(otool -l "$APP/Contents/MacOS/TeetimeMonitor" | awk '/LC_BUILD_VERSION/{f=1} f&&/minos/{print $2; exit}')
[ "$minos" = "14.0" ] || { echo "error: TeetimeMonitor binary targets macOS $minos, not 14.0" >&2; exit 1; }

# (f) Ad-hoc signing. Apple Silicon refuses to run a Mach-O that is not signed at all, and
# the wheels/pbs files were modified or copied, so every Mach-O gets its own signature
# first (inner before outer), then the app seals the lot. Plain ad hoc: no hardened runtime
# (it means nothing without notarization, and would block the unsigned-library loading
# Python extension modules do), no timestamp (no server to ask).
echo "==> signing (ad hoc)"
MACHO="$WORK/macho.list"
find "$PYDIR" -type f \( -name '*.so' -o -name '*.dylib' -o -perm +111 \) -print0 \
    | xargs -0 file | grep -E ': +Mach-O' | sed -E 's/: +Mach-O.*//' > "$MACHO"
# Some wheels (charset_normalizer) are universal2; this download is arm64-only, so drop the
# Intel half (smaller, and nothing can ever run it).
THINNED=0
while IFS= read -r file; do
    if [ "$(lipo -archs "$file")" != arm64 ]; then
        lipo -thin arm64 "$file" -output "$file.thin" && mv "$file.thin" "$file"
        THINNED=$((THINNED + 1))
    fi
done < "$MACHO"
SIGNED=0
while IFS= read -r file; do
    # codesign chats on stderr ("replacing existing signature") for every file; only a failure matters.
    out=$(codesign --force --sign - --timestamp=none "$file" 2>&1) || { echo "$out" >&2; exit 1; }
    SIGNED=$((SIGNED + 1))
done < "$MACHO"
echo "  $SIGNED nested Mach-O files signed ($THINNED thinned from universal2 to arm64)"
out=$(codesign --force --sign - --timestamp=none "$APP" 2>&1) || { echo "$out" >&2; exit 1; }
codesign --verify --deep --strict "$APP"
echo "  codesign --verify --deep --strict: ok"

# (h) Zip with ditto (keeps the symlinks, permissions and signature a plain `zip` can break).
echo "==> zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
( cd "$DIST" && shasum -a 256 "$(basename "$ZIP")" > "$(basename "$ZIP").sha256" )

SECONDS_TAKEN=$(( $(date +%s) - STARTED ))
echo "built   $ZIP"
echo "sha256  $(cut -d' ' -f1 "$ZIP.sha256")"
echo "zip     $(du -h "$ZIP" | cut -f1)    app on disk  $(du -sh "$APP" | cut -f1)    python $("$PY" -I -c 'import platform; print(platform.python_version())')"
echo "time    ${SECONDS_TAKEN}s"
