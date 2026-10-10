#!/usr/bin/env python3
"""Builds the portable Linux app (2026-10-10): linux/dist/TeetimeMonitor-<version>-linux-x86_64.tar.gz.

For friends with no Python and no package manager rights: unpack anywhere, run ./TeetimeMonitor.sh in
a terminal. Nothing is installed and nothing is written outside the unpacked folder -- the launcher
points the app's config and data at `userdata/` next to it (TEETIME_MONITOR_CONFIG_DIR /
TEETIME_MONITOR_DATA_DIR, see src/paths.py).

The runtime is python-build-standalone's relocatable CPython 3.12 (pinned by URL and SHA-256); the
dependency wheels are manylinux x86_64 wheels from PyPI (glibc 2.28 or newer, i.e. RHEL/Alma 8,
Debian 10, Ubuntu 18.10 and everything since). Same shape as windows/build_portable.py.

Runs on any OS with `uv`, so the assembly can be checked on a Mac; only the bytecode step needs Linux.

  python linux/build_portable.py            -> linux/dist/TeetimeMonitor-<v>-linux-x86_64.tar.gz (+ .sha256)
  python linux/verify_portable.py [tarball] -> checks the result in a clean environment (Linux only)
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = REPO / "linux" / "build-portable"
DIST = REPO / "linux" / "dist"

PBS_RELEASE = "20261009"
PYTHON_VERSION = "3.12.15"
PBS_NAME = f"cpython-{PYTHON_VERSION}+{PBS_RELEASE}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PBS_URL = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_RELEASE}/{PBS_NAME.replace('+', '%2B')}"
PBS_SHA256 = "ffa8f85f1b56e88b687f08d743d817015524b86a9365fd921243132b80f1a36d"
PYTHON_SERIES = "3.12"

TOP = "TeetimeMonitor"  # the folder inside the tarball

# -I: no PYTHON* variables, no user site, and no current directory on sys.path (a stray ./src in the
# directory the app is started from must never be imported). -B: do not write bytecode into the folder.
LAUNCHER = """#!/bin/sh
# Teetime Monitor, portable. Run it in a terminal: ./TeetimeMonitor.sh   (--doctor checks the setup)
# Your settings, logins and tee-time history live in the "userdata" folder next to this file
# (copy that folder into a newer version's folder to keep them).
self=$0
while [ -L "$self" ]; do
    link=$(readlink "$self")
    case $link in /*) self=$link ;; *) self=$(dirname "$self")/$link ;; esac
done
here=$(cd "$(dirname "$self")" && pwd -P) || exit 1
TEETIME_MONITOR_CONFIG_DIR=$here/userdata/config
TEETIME_MONITOR_DATA_DIR=$here/userdata/data
PYTHONNOUSERSITE=1
umask 077   # the password file and the history are created readable by this user only
export TEETIME_MONITOR_CONFIG_DIR TEETIME_MONITOR_DATA_DIR PYTHONNOUSERSITE
exec "$here/app/python/bin/python3" -I -B -c 'import sys; sys.argv[0] = "teetime-monitor"; from src.tui import main; sys.exit(main())' "$@"
"""

README = """TEETIME MONITOR - portable Linux version
========================================

Nothing to install. No Python, no root rights.

START
  1. Unpack the archive anywhere you like:      tar xzf TeetimeMonitor-*-linux-x86_64.tar.gz
  2. Open a terminal in the new TeetimeMonitor folder and run:      ./TeetimeMonitor.sh
     (a modern terminal with colours and UTF-8 looks best: GNOME Terminal, Konsole, kitty, ...)

KEEP IT / REMOVE IT
  Your settings, logins and history are stored in the "userdata" folder inside this folder -
  nowhere else. To remove everything, delete the folder. To update, unpack the new version and
  copy your old "userdata" folder into it. Your pc caddie password is stored as plain text in
  userdata/config/.env (created readable by your user only) - do not put the folder on a shared drive.

IF SOMETHING GOES WRONG
  Run   ./TeetimeMonitor.sh --doctor   - it checks the setup (network, certificates, login).
  Needs a 64-bit Intel/AMD Linux with glibc 2.28 or newer (Debian 10, Ubuntu 20.04, RHEL 8 or
  newer). Not for Alpine (musl) and not for ARM (Raspberry Pi).

More: https://github.com/ltdan-88/teetime-monitor
"""


def version() -> str:
    with open(REPO / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def run(cmd: list, **kwargs) -> None:
    print("  $", " ".join(str(part) for part in cmd), flush=True)
    subprocess.run([str(part) for part in cmd], check=True, **kwargs)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_runtime() -> Path:
    """python-build-standalone's tarball, checked against the pinned hash (cached across builds)."""
    cache = WORK.parent / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / PBS_NAME
    if not target.exists() or sha256_of(target) != PBS_SHA256:
        print(f"==> downloading {PBS_URL}")
        with urllib.request.urlopen(PBS_URL, timeout=300) as response:
            target.write_bytes(response.read())
    if sha256_of(target) != PBS_SHA256:
        sys.exit(f"error: {target.name} does not match the pinned SHA-256 (got {sha256_of(target)})")
    return target


def requirements() -> Path:
    """The locked dependency set (what CI tests); uv.lock is git-ignored, so resolve one if absent."""
    if not (REPO / "uv.lock").exists():
        print("no uv.lock in this checkout -- resolving one")
        run(["uv", "lock", "--quiet"], cwd=REPO)
    out = WORK / "requirements.txt"
    run(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes", "--no-header", "--quiet", "-o", out],
        cwd=REPO,
    )
    if not out.stat().st_size:
        sys.exit("error: uv export produced no requirements")
    return out


def build() -> Path:
    ver = version()
    if WORK.exists():
        shutil.rmtree(WORK)
    stage = WORK / "stage" / TOP
    app = stage / "app"
    app.mkdir(parents=True)
    DIST.mkdir(parents=True, exist_ok=True)
    tar_path = DIST / f"TeetimeMonitor-{ver}-linux-x86_64.tar.gz"
    for stale in (tar_path, tar_path.with_name(tar_path.name + ".sha256")):
        stale.unlink(missing_ok=True)

    print(f"==> TeetimeMonitor {ver} (Linux x86_64, portable)")
    print("==> relocatable CPython", PYTHON_VERSION)
    with tarfile.open(fetch_runtime()) as archive:
        # -> app/python/. share/ (terminfo: file names that differ only in case, which a Mac's
        # filesystem cannot hold) and include/ are of no use to a bundled app.
        wanted = [m for m in archive.getmembers() if not m.name.startswith(("python/share/", "python/include/"))]
        archive.extractall(app, members=wanted, filter="tar")
    python_dir = app / "python"
    site = python_dir / "lib" / f"python{PYTHON_SERIES}" / "site-packages"
    # Console scripts in python/bin have absolute build-machine shebangs and belong to tools we
    # drop (pip, idle); only the interpreter stays.
    for entry in (python_dir / "bin").iterdir():
        if entry.name not in ("python", "python3", f"python{PYTHON_SERIES}"):
            entry.unlink()
    for pip_dir in [site / "pip", *site.glob("pip-*.dist-info")]:
        shutil.rmtree(pip_dir, ignore_errors=True)

    print("==> dependencies (manylinux x86_64 wheels)")
    reqs = requirements()
    target = ["--python-platform", "x86_64-unknown-linux-gnu", "--python-version", PYTHON_SERIES, "--target", site]
    run(["uv", "pip", "install", "--no-cache", "--quiet", "--only-binary", ":all:", *target, "-r", reqs])

    print("==> this project")
    src = WORK / "src"
    src.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(REPO / name, src / name)
    shutil.copytree(REPO / "src", src / "src", ignore=shutil.ignore_patterns("__pycache__"))
    run(["uv", "pip", "install", "--no-cache", "--quiet", "--no-deps", *target, src])
    for dist in site.glob("*.dist-info"):
        (dist / "direct_url.json").unlink(missing_ok=True)
        record = dist / "RECORD"
        if record.exists():  # the install records must not name the build directory
            lines = [
                line
                for line in record.read_text(encoding="utf-8").splitlines()
                if not line.startswith(f"{dist.name}/direct_url.json,")
            ]
            record.write_text("\n".join(lines) + "\n", encoding="utf-8")
        metadata = dist / "METADATA"
        if dist.name.startswith("teetime_monitor-") and metadata.exists():
            metadata.write_text(metadata.read_text(encoding="utf-8").split("\n\n", 1)[0] + "\n", encoding="utf-8")
    shutil.rmtree(site / "bin", ignore_errors=True)  # console scripts with absolute shebangs, unused

    launcher = stage / "TeetimeMonitor.sh"
    launcher.write_text(LAUNCHER, encoding="utf-8", newline="\n")
    launcher.chmod(0o755)
    (stage / "README.txt").write_text(README, encoding="utf-8", newline="\n")

    if sys.platform.startswith("linux"):
        # Bytecode at build time (the launcher runs with -B, so nothing is written later).
        # unchecked-hash: never compared with the source's mtime; -s/-p keep the build directory
        # out of the stored file names. The whole lib/ tree, not just site-packages: the runtime ships no
        # stdlib bytecode, and without -B the compileall run itself would write some with real paths.
        print("==> bytecode")
        run(
            [python_dir / "bin" / "python3", "-I", "-B", "-m", "compileall", "-q", "-f", "-j", "0",
             "--invalidation-mode", "unchecked-hash", "-s", stage, "-p", f"/{TOP}", python_dir / "lib"]
        )  # fmt: skip
    else:
        print("==> bytecode skipped (needs Linux; every start compiles in memory instead)")

    print("==> tarball")

    def normalise(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    with tarfile.open(tar_path, "w:gz", compresslevel=9) as archive:
        archive.add(stage, arcname=TOP, filter=normalise)
    digest = sha256_of(tar_path)
    tar_path.with_name(tar_path.name + ".sha256").write_text(f"{digest}  {tar_path.name}\n", encoding="utf-8")
    print(f"==> {tar_path} ({tar_path.stat().st_size / 1e6:.0f} MB)")
    print(json.dumps({"version": ver, "tarball": tar_path.name, "sha256": digest}))
    return tar_path


if __name__ == "__main__":
    os.chdir(REPO)
    build()
