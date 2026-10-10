"""The portable Windows app's build script (windows/build_portable.py, 2026-10-10).

The build itself runs in CI on a Windows runner; these pin what can be checked anywhere: the
launcher must stay a plain-ASCII, CRLF batch file that points the app at its own folder, and the
entry point it runs must be the one pyproject declares for `teetime-monitor`.
"""

import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("build_portable", ROOT / "windows" / "build_portable.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load()


def test_run_py_calls_the_entry_point_pyproject_declares():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    module, _, function = scripts["teetime-monitor"].partition(":")
    assert f"from {module} import {function}" in build.RUN_PY
    assert f"sys.exit({function}())" in build.RUN_PY


def test_launcher_is_ascii_and_keeps_everything_inside_its_folder():
    text = build.LAUNCHER
    text.encode("ascii")  # cmd.exe reads a batch file in the OEM code page
    assert 'set "TEETIME_MONITOR_CONFIG_DIR=%HERE%userdata\\config"' in text
    assert 'set "TEETIME_MONITOR_DATA_DIR=%HERE%userdata\\data"' in text
    assert '"%HERE%app\\python.exe" "%HERE%app\\run.py" %*' in text  # arguments pass through (--doctor)
    assert "pause" in text  # a double-clicked window must not vanish on an error


def test_launcher_and_readme_are_written_with_crlf(tmp_path):
    target = tmp_path / "x.cmd"
    build.write_text(target, build.LAUNCHER, crlf=True)
    data = target.read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")


def test_pth_enables_site_packages_next_to_the_interpreter():
    lines = build.PTH.splitlines()
    assert lines[:3] == ["python312.zip", ".", "Lib\\site-packages"]
    assert "import site" in lines


def test_the_pinned_runtime_is_a_python_org_embeddable_3_12():
    assert build.EMBED_URL.startswith("https://www.python.org/ftp/python/3.12.")
    assert build.EMBED_URL.endswith("-embed-amd64.zip")
    assert len(build.EMBED_SHA256) == 64


def test_the_readme_points_at_the_files_it_names():
    assert "TeetimeMonitor.cmd" in build.README and "userdata" in build.README


def test_the_browser_launcher_starts_the_web_entry_point_in_the_same_isolation():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    module, _, function = scripts["teetime-monitor-web"].partition(":")
    assert f"from {module} import {function}" in build.RUN_WEB_PY
    assert '"%HERE%app\\python.exe" "%HERE%app\\run_web.py" %*' in build.WEB_LAUNCHER
    assert 'set "TEETIME_MONITOR_CONFIG_DIR=%HERE%userdata\\config"' in build.WEB_LAUNCHER
    build.WEB_LAUNCHER.encode("ascii")
    assert "TeetimeMonitor-Web.cmd" in build.README
