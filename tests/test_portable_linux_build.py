"""The portable Linux app's build script (linux/build_portable.py, 2026-10-10).

The build runs in CI on a Linux runner; these pin what can be checked anywhere: the launcher must
keep the app inside its own folder, run the interpreter isolated, and call the entry point
pyproject declares for `teetime-monitor`.
"""

import importlib.util
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("build_portable_linux", ROOT / "linux" / "build_portable.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load()


def test_launcher_calls_the_entry_point_pyproject_declares():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    module, _, function = scripts["teetime-monitor"].partition(":")
    assert f"from {module} import {function}" in build.LAUNCHER
    assert f"sys.exit({function}())" in build.LAUNCHER


def test_launcher_keeps_state_beside_itself_and_runs_isolated():
    text = build.LAUNCHER
    assert text.startswith("#!/bin/sh\n")
    assert "TEETIME_MONITOR_CONFIG_DIR=$here/userdata/config" in text
    assert "TEETIME_MONITOR_DATA_DIR=$here/userdata/data" in text
    assert '"$here/app/python/bin/python3" -I -B -c' in text
    assert '"$@"' in text  # arguments pass through (--doctor)
    assert "umask 077" in text


def test_launcher_is_valid_shell(tmp_path):
    script = tmp_path / "l.sh"
    script.write_text(build.LAUNCHER, encoding="utf-8")
    assert subprocess.run(["sh", "-n", str(script)], capture_output=True).returncode == 0


def test_the_pinned_runtime_is_a_3_12_x86_64_glibc_build():
    assert "cpython-3.12." in build.PBS_NAME and "x86_64-unknown-linux-gnu" in build.PBS_NAME
    assert build.PBS_URL.startswith("https://github.com/astral-sh/python-build-standalone/releases/download/")
    assert len(build.PBS_SHA256) == 64


def test_the_readme_names_the_launcher_and_the_data_folder():
    assert "./TeetimeMonitor.sh" in build.README and "userdata" in build.README


def test_the_browser_launcher_starts_the_web_entry_point_and_is_valid_shell(tmp_path):
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    module, _, function = scripts["teetime-monitor-web"].partition(":")
    text = build.WEB_LAUNCHER
    assert f"from {module} import {function}" in text and "src.tui" not in text
    assert "TEETIME_MONITOR_CONFIG_DIR=$here/userdata/config" in text and "umask 077" in text
    script = tmp_path / "w.sh"
    script.write_text(text, encoding="utf-8")
    assert subprocess.run(["sh", "-n", str(script)], capture_output=True).returncode == 0
    assert "TeetimeMonitor-Web.sh" in build.README
