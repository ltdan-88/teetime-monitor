#!/usr/bin/env python3
"""Checks a linux/build_portable.py tarball the way a stranger's machine would meet it (2026-10-10).

Linux only. The tarball is unpacked into a fresh temp folder and run through its own launcher in a
CLEAN environment: a PATH of /usr/bin:/bin only (no Python of the machine's own, no uv), no PYTHON*
variables, and an empty HOME that must still be empty afterwards -- the portable promise is that
nothing is written outside the unpacked folder. No network is used. Exits non-zero on any failure,
with a PASS/FAIL summary.

  python linux/verify_portable.py [path/to/TeetimeMonitor-<version>-linux-x86_64.tar.gz]

Run inside an old distribution too (the workflow does it in almalinux:8, the glibc 2.28 floor):
  ./TeetimeMonitor.sh --version, --doctor --offline.
Not covered here: the interactive terminal itself (the app is driven headless through Textual's
test pilot instead) and distributions other than the CI runner's and AlmaLinux 8.
"""

import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOP = "TeetimeMonitor"
failures: list[str] = []


def report(ok: bool, what: str, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {what}" + (f" -- {detail}" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(what)


def elf_machine(path: Path) -> int | None:
    """The e_machine field of an ELF file (0x3E = x86-64), or None when it is not ELF."""
    with open(path, "rb") as handle:
        head = handle.read(20)
    if head[:4] != b"\x7fELF" or len(head) < 20:
        return None
    return int.from_bytes(head[18:20], "little")


def main() -> int:
    if not sys.platform.startswith("linux"):
        print("error: this verifies a Linux app and must run on Linux", file=sys.stderr)
        return 2
    with open(REPO / "pyproject.toml", "rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    if len(sys.argv) > 1:
        tar_path = Path(sys.argv[1]).resolve()
    else:
        found = sorted((REPO / "linux" / "dist").glob("TeetimeMonitor-*-linux-x86_64.tar.gz"), key=lambda p: p.stat().st_mtime)
        tar_path = found[-1] if found else Path()
    if not tar_path.is_file():
        print("error: no tarball given and none in linux/dist (run linux/build_portable.py)", file=sys.stderr)
        return 2

    work = Path(tempfile.mkdtemp(prefix="tm-verify-")).resolve()
    home = work / "home"
    home.mkdir()
    unpacked = work / "unpacked"
    unpacked.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(work), "LANG": "C.UTF-8"}

    def run(args: list[str], timeout: int = 180, extra: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(args, env=dict(env, **(extra or {})), cwd=work, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)  # fmt: skip

    # (1) the archive itself
    with tarfile.open(tar_path) as archive:
        names = archive.getnames()
        archive.extractall(unpacked, filter="tar")
    report(all(n == TOP or n.startswith(f"{TOP}/") for n in names), "every entry is inside the single TeetimeMonitor/ folder")
    root = unpacked / TOP
    launcher = root / "TeetimeMonitor.sh"
    for needed in ("TeetimeMonitor.sh", "README.txt", "app/python/bin/python3"):
        report((root / needed).is_file(), f"contains {needed}")
    report(bool(launcher.stat().st_mode & stat.S_IXUSR), "the launcher is executable")
    report(not any((root / "app" / "python" / "bin" / n).is_symlink() and os.readlink(root / "app" / "python" / "bin" / n).startswith("/")
                   for n in os.listdir(root / "app" / "python" / "bin")), "no absolute symlinks in python/bin")  # fmt: skip

    # (2) version and doctor, through the launcher, in the clean environment
    result = run([str(launcher), "--version"])
    report(result.returncode == 0 and result.stdout.strip() == f"teetime-monitor {version}", "launcher --version",
           f"exit {result.returncode}: {result.stdout!r} {result.stderr[-300:]!r}")  # fmt: skip
    result = run([str(launcher), "--doctor", "--offline"])
    report(result.returncode == 0, "--doctor --offline exits 0", f"exit {result.returncode}: {result.stdout[-600:]}")
    config_dir, data_dir = root / "userdata" / "config", root / "userdata" / "data"
    report(str(config_dir) in result.stdout and str(data_dir) in result.stdout, "doctor reports the userdata folders next to the app", result.stdout[-600:])  # fmt: skip

    # (3) what the bundled interpreter sees: itself, its own folders only, every module importable
    probe = r"""
import importlib, json, pkgutil, ssl, sqlite3, sys
from zoneinfo import ZoneInfo
import src
modules = [m.name for m in pkgutil.iter_modules(src.__path__)]
failed = {}
for name in modules:
    try:
        importlib.import_module("src." + name)
    except BaseException as exc:
        failed[name] = repr(exc)
import textual, httpx, truststore, yaml, pydantic, bs4, dotenv, anthropic, openai
from google import genai
print(json.dumps({"exe": sys.executable, "path": sys.path, "modules": len(modules), "failed": failed,
                  "berlin": str(ZoneInfo("Europe/Berlin")), "ssl": ssl.OPENSSL_VERSION,
                  "sqlite": sqlite3.sqlite_version, "version": sys.version.split()[0]}))
"""
    python = root / "app" / "python" / "bin" / "python3"
    result = run([str(python), "-I", "-B", "-c", probe])
    try:
        info = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        info = None
    report(info is not None, "bundled python runs and imports every dependency",
           f"exit {result.returncode}: {result.stdout[-400:]} {result.stderr[-600:]}")  # fmt: skip
    if info:
        inside = str(root)
        report(info["exe"].startswith(inside), "sys.executable is the bundled python", info["exe"])
        outside = [p for p in info["path"] if p and not p.startswith(inside)]
        report(not outside, "sys.path holds only folders inside the app", str(outside))
        report(not info["failed"], f"all {info['modules']} src modules import", str(info["failed"]))
        report(info["berlin"] == "Europe/Berlin", "the bundled time zone database knows Europe/Berlin")
        print(f"      python {info['version']}, {info['ssl']}, sqlite {info['sqlite']}")

    # (4) the TUI starts and stays up (headless, Textual's pilot), without a network
    headless = r"""
import asyncio
from src import paths
paths.ensure_dirs()
from src.tui import TeetimeApp

async def go():
    app = TeetimeApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(1.5)
        print("SCREEN", type(app.screen).__name__)

asyncio.run(go())
"""
    app_env = {"TEETIME_MONITOR_CONFIG_DIR": str(config_dir), "TEETIME_MONITOR_DATA_DIR": str(data_dir), "PYTHONUTF8": "1"}
    result = run([str(python), "-I", "-B", "-c", headless], extra=app_env)
    report(result.returncode == 0 and "SCREEN" in result.stdout, "the app starts headless and shows a screen",
           f"exit {result.returncode}: {result.stdout[-300:]} {result.stderr[-900:]}")  # fmt: skip

    # (5) only the unpacked folder was written to
    stray = [str(p.relative_to(home)) for p in home.rglob("*")]
    report(not stray, "nothing was written to HOME", str(stray[:8]))
    report(config_dir.is_dir() and data_dir.is_dir(), "userdata folders were created next to the app")

    # (6) hygiene: x86-64 only, no build-machine paths in text, nothing links outside the system
    wrong = []
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            machine = elf_machine(path)
            if machine is not None and machine != 0x3E:
                wrong.append(f"{path.relative_to(root)} (e_machine {machine:#x})")
    report(not wrong, "every ELF file is x86-64", str(wrong[:5]))
    leaks = []
    needle = str(REPO).encode()
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in (".py", ".pyc", ".sh", ".txt", ".json", ".pth", "") and not path.is_symlink():
            if path.suffix == "" and elf_machine(path) is not None:
                continue
            if needle in path.read_bytes():
                leaks.append(str(path.relative_to(root)))
    report(not leaks, "no source, bytecode or text file names the build checkout", str(leaks[:5]))

    print()
    print(f"tarball  {tar_path.stat().st_size / 1e6:.0f} MB ({tar_path.name})")
    print(f"---- summary ----\n{'FAIL: ' + str(len(failures)) + ' check(s) failed' if failures else 'PASS: all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
