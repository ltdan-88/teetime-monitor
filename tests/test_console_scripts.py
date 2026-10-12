"""The console scripts in pyproject.toml: each must be `module:function` and point at a real, callable function
(a typo there only shows after `pip install`, on somebody's machine)."""

import importlib
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]


def test_there_are_console_scripts():
    assert {"teetime-monitor", "teetime-monitor-scrape", "teetime-monitor-web"} <= set(SCRIPTS)


@pytest.mark.parametrize("name,target", sorted(SCRIPTS.items()))
def test_every_console_script_is_module_colon_function(name, target):
    module, separator, function = target.partition(":")
    assert separator == ":" and module and function.isidentifier(), f"{name} = {target!r}"
    assert callable(getattr(importlib.import_module(module), function))
