"""A minimal stand-in for Textual's built-in `Footer` — see tui.py's module docstring
("Revised the same day" note) for why: that widget's key-hint text comes from each
Screen's class-level `BINDINGS` descriptions (fixed at import time, English), and no
public API was found to override a binding's displayed text at render time. Renders
the same key hints from i18n.py instead — `bindings` is `[(key, i18n_key), ...]` in
display order; the actual key dispatch still goes through each Screen/App's own
`BINDINGS`/`action_*` methods, this widget only controls what's shown.

Factored out 2026-09-07 once a 4th screen (credentials_screen.py) needed the exact
same widget — tui.py, settings_screen.py, and club_picker.py each re-export
`TranslatedFooter` from here (`from .translated_footer import TranslatedFooter`)
rather than defining their own copy, so existing imports/tests
(`from src.tui import TranslatedFooter`, etc.) keep working unchanged.
"""

from textual.widgets import Static

from . import i18n


class TranslatedFooter(Static):
    DEFAULT_CSS = """
    TranslatedFooter {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text;
    }
    """

    def __init__(self, bindings: list[tuple[str, str]]) -> None:
        super().__init__()
        self._key_bindings = bindings

    def render(self) -> str:
        parts = [f"[b]{key}[/b] {i18n.t(label_key)}" for key, label_key in self._key_bindings]
        return "  ".join(parts)
