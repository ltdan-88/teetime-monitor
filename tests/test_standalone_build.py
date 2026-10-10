"""The standalone Mac app build (macos/build_standalone.sh, 2026-10-10) derives one launcher per
`[project.scripts]` entry, so the entries have to keep the `module:function` shape it expects. This
is the macOS-free half of its checks (the build and macos/verify_standalone.sh need an Apple
Silicon Mac): the shape of the entries, that each one points at a real function, and that the
shell scripts at least parse."""

import importlib
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]


def test_there_are_console_scripts():
    assert "teetime-monitor" in SCRIPTS and "teetime-monitor-picks" in SCRIPTS


@pytest.mark.parametrize("name,target", sorted(SCRIPTS.items()))
def test_every_console_script_is_module_colon_function(name, target):
    module, separator, function = target.partition(":")
    assert separator == ":" and module and function.isidentifier(), f"{name} = {target!r}"
    # The launcher is `from <module> import <function>; sys.exit(<function>())`: a no-argument callable.
    assert callable(getattr(importlib.import_module(module), function))


@pytest.mark.skipif(shutil.which("bash") is None, reason="no bash")
@pytest.mark.parametrize("script", ["build.sh", "build_standalone.sh", "verify_standalone.sh"])
def test_the_mac_build_scripts_parse(script):
    path = ROOT / "macos" / script
    result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
