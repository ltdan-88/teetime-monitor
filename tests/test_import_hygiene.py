"""The GUI's headless entry points must not import the Textual TUI (2026-10-05).

`picks_cli`/`search_cli`/`preview_club_cli` used to `from . import tui` just to reach
a few private helpers, so every GUI subprocess paid for Textual and Rich. Those helpers
now live in `pipeline.py`; this keeps it that way. Each module is imported in a fresh
interpreter (this process has already imported `tui`), so `sys.modules` is clean.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

HEADLESS_MODULES = [
    "picks_cli",
    "search_cli",
    "preview_club_cli",
    "login_cli",
    "ai_login_cli",
    "directory_cli",
    "add_club_cli",
    "pipeline",
    "clock",
]


@pytest.mark.parametrize("module", HEADLESS_MODULES)
def test_headless_module_does_not_import_textual_or_rich(module):
    # On Windows some dependency imports `rich` as a plain text library at import time
    # (seen on the nightly Windows run, 2026-10-06), which says nothing about the TUI, so
    # there only Textual and src.tui are banned.
    code = (
        "import sys\n"
        f"import src.{module}\n"
        f"banned = ('textual',) if {sys.platform == 'win32'!r} else ('textual', 'rich')\n"
        "loaded = sorted(m for m in sys.modules if m.split('.')[0] in banned or m == 'src.tui')\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
