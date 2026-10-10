#!/usr/bin/env python3
"""Checks a windows/build_portable.py zip the way a stranger's PC would meet it (2026-10-10).

Windows only. The zip is unpacked into a fresh temp folder and run through its own launcher in
a CLEAN environment: a PATH of the Windows system folders only (no Python, no Scoop, no uv), no
PYTHON* variables, and a fake user profile (USERPROFILE / APPDATA / LOCALAPPDATA / TEMP) that
must still be empty afterwards -- the portable promise is that nothing is written outside the
unzipped folder. No network is used. Exits non-zero on any failure, with a PASS/FAIL summary.

  python windows/verify_portable.py [path/to/TeetimeMonitor-<version>-windows-x64.zip]

Not covered (needs a real locked-down PC): SmartScreen / the zip's Mark-of-the-Web prompt,
AppLocker or antivirus policy, and the interactive terminal itself (the app is driven headless
through Textual's test pilot instead).
"""

import json
import os
import struct
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOP = "TeetimeMonitor"
failures: list[str] = []


def report(ok: bool, what: str, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {what}" + (f" -- {detail}" if detail and not ok else ""), flush=True)
    if not ok:
        failures.append(what)


def clean_env(profile: Path) -> dict[str, str]:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    env = {
        "SystemRoot": root,
        "SystemDrive": os.environ.get("SystemDrive", "C:"),
        "windir": root,
        "ComSpec": os.environ.get("ComSpec", rf"{root}\System32\cmd.exe"),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "PATH": rf"{root}\System32;{root}",
        "USERPROFILE": str(profile),
        "HOMEDRIVE": os.environ.get("SystemDrive", "C:"),
        "HOMEPATH": str(profile)[2:],
        "APPDATA": str(profile / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(profile / "AppData" / "Local"),
        "TEMP": str(profile / "Temp"),
        "TMP": str(profile / "Temp"),
    }
    return env


def pe_machine(path: Path) -> int | None:
    """The 'Machine' field of a PE file, or None when the file is not a PE image."""
    with open(path, "rb") as handle:
        head = handle.read(64)
        if head[:2] != b"MZ" or len(head) < 64:
            return None
        handle.seek(struct.unpack_from("<I", head, 60)[0])
        sig = handle.read(6)
    if sig[:4] != b"PE\0\0":
        return None
    return struct.unpack_from("<H", sig, 4)[0]


def main() -> int:
    if sys.platform != "win32":
        print("error: this verifies a Windows app and must run on Windows", file=sys.stderr)
        return 2
    with open(REPO / "pyproject.toml", "rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    if len(sys.argv) > 1:
        zip_path = Path(sys.argv[1]).resolve()
    else:
        found = sorted((REPO / "windows" / "dist").glob("TeetimeMonitor-*-windows-x64.zip"), key=lambda p: p.stat().st_mtime)
        zip_path = found[-1] if found else Path()
    if not zip_path.is_file():
        print("error: no zip given and none in windows/dist (run windows/build_portable.py)", file=sys.stderr)
        return 2

    work = Path(tempfile.mkdtemp(prefix="tm-verify-")).resolve()
    profile = work / "profile"
    for sub in ("AppData/Roaming", "AppData/Local", "Temp"):
        (profile / sub).mkdir(parents=True)
    unzipped = work / "unzipped"
    env = clean_env(profile)

    def run(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
        return subprocess.run(args, env=env, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)

    # (1) the zip itself
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        archive.extractall(unzipped)
    report(all(name.startswith(f"{TOP}/") for name in names), "every zip entry is inside the single TeetimeMonitor/ folder")
    root = unzipped / TOP
    for needed in ("TeetimeMonitor.cmd", "README.txt", "app/python.exe", "app/run.py", "app/python312._pth"):
        report((root / needed).is_file(), f"contains {needed}")
    launcher = str(root / "TeetimeMonitor.cmd")

    # (2) version and doctor, through the launcher, in the clean environment
    result = run(["cmd", "/c", launcher, "--version"])
    report(result.returncode == 0 and result.stdout.strip() == f"teetime-monitor {version}", "launcher --version", f"exit {result.returncode}: {result.stdout!r} {result.stderr[-300:]!r}")
    result = run(["cmd", "/c", launcher, "--doctor", "--offline"])
    report(result.returncode == 0, "--doctor --offline exits 0", f"exit {result.returncode}: {result.stdout[-600:]}")
    config_dir, data_dir = root / "userdata" / "config", root / "userdata" / "data"
    report(str(config_dir) in result.stdout and str(data_dir) in result.stdout, "doctor reports the userdata folders next to the app", result.stdout[-600:])

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
print(json.dumps({"exe": sys.executable, "path": sys.path, "prefix": sys.prefix, "flags_isolated": sys.flags.isolated,
                  "modules": len(modules), "failed": failed, "berlin": str(ZoneInfo("Europe/Berlin")),
                  "ssl": ssl.OPENSSL_VERSION, "sqlite": sqlite3.sqlite_version, "version": sys.version.split()[0]}))
"""
    result = run([str(root / "app" / "python.exe"), "-c", probe])
    try:
        info = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        info = None
    report(info is not None, "bundled python runs and imports every dependency", f"exit {result.returncode}: {result.stdout[-400:]} {result.stderr[-600:]}")
    if info:
        inside = str(root).lower()
        report(info["exe"].lower().startswith(inside), "sys.executable is the bundled python.exe", info["exe"])
        outside = [p for p in info["path"] if p and not p.lower().startswith(inside)]
        report(not outside, "sys.path holds only folders inside the app", str(outside))
        report(not info["failed"], f"all {info['modules']} src modules import", str(info["failed"]))
        report(info["berlin"] == "Europe/Berlin", "the bundled time zone database knows Europe/Berlin")
        print(f"      python {info['version']}, {info['ssl']}, sqlite {info['sqlite']}")

    # (4) the TUI starts and stays up (headless, Textual's pilot), without a network
    headless = r"""
import asyncio, os
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
    env_app = dict(env, TEETIME_MONITOR_CONFIG_DIR=str(config_dir), TEETIME_MONITOR_DATA_DIR=str(data_dir), PYTHONUTF8="1")
    result = subprocess.run([str(root / "app" / "python.exe"), "-c", headless], env=env_app, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    report(result.returncode == 0 and "SCREEN" in result.stdout, "the app starts headless and shows a screen", f"exit {result.returncode}: {result.stdout[-300:]} {result.stderr[-900:]}")

    # (5) only the unzipped folder was written to
    stray = [str(p.relative_to(profile)) for p in profile.rglob("*") if p.is_file()]
    report(not stray, "nothing was written to the user profile, AppData or TEMP", str(stray[:8]))
    report(config_dir.is_dir() and data_dir.is_dir(), "userdata folders were created next to the app")

    # (6) hygiene: right architecture, no build-machine paths in text
    wrong = []
    for path in root.rglob("*"):
        if path.suffix.lower() in (".pyd", ".dll", ".exe"):
            machine = pe_machine(path)
            if machine is not None and machine != 0x8664:
                wrong.append(f"{path.relative_to(root)} (machine {machine:#x})")
    report(not wrong, "every .pyd / .dll / .exe is x64", str(wrong[:5]))
    build_roots = {str(REPO).lower(), str(REPO).lower().replace("\\", "/")}
    leaks = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in (".py", ".pyc", ".cmd", ".txt", ".json", ".metadata", ".record", ".pth", ".pth_"):
            blob = path.read_bytes().lower()
            if any(build_root.encode() in blob for build_root in build_roots):
                leaks.append(str(path.relative_to(root)))
    report(not leaks, "no source, bytecode or text file names the build checkout", str(leaks[:5]))

    print()
    print(f"zip   {zip_path.stat().st_size / 1e6:.0f} MB ({zip_path.name})")
    print(f"---- summary ----\n{'FAIL: ' + str(len(failures)) + ' check(s) failed' if failures else 'PASS: all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
