"""A minimal Textual screen for editing a club's availability/weather preferences and
scrape interval — built ahead of the full tee-sheet TUI (ROADMAP.md Phase 4), per
direct feedback (2026-09-06) that these needed to be adjustable from the UI, not just
by hand-editing a club's YAML.

Deliberately narrow: this is *not* tui.py's home screen (still unbuilt — Phase 0/1/4
have to land first, see tui.py's own docstring). It's a standalone screen for exactly
the settings that came up in that feedback: `availability` (min open spots, time
windows, buffer), `preferences` (rain/wind/temperature thresholds, friend/crowd
weighting), and the scrape interval added the same day. Everything else in a club's
YAML (club_id, location, calendar, identity, ai_assist) stays hand-edited for now —
those are set-once-at-setup values, not day-to-day dials.

Run directly: `python -m src.settings_screen <club-id>` (the clubs/*.yaml filename
slug, not the pc caddie numeric id) — or with no argument if exactly one club is
saved, matching the "skip the picker" convention used elsewhere in this project.

Saving writes the whole config back via club_config.save_club_config() — see that
function's docstring for the one known limitation (comments in the YAML file don't
survive a save).

Bilingual (added 2026-09-06, alongside tui.py's own i18n.py wiring): applies the same
resolved theme/language as the main TUI on startup, and every field label/button/
status message goes through i18n.py — this is a separate standalone App (run directly
as `python -m src.settings_screen`, not a Screen pushed into TeetimeApp), so it needs
its own `apply_theme()`/`apply_language()` calls rather than inheriting TeetimeApp's.
No in-app language-switch command here, unlike tui.py — switch language from the main
TUI (persists to the shared config file) and this screen picks it up next time it's
run. Its footer's key hint ("q Quit") is rendered by a small `TranslatedFooter` — see
translated_footer.py's docstring for why Textual's built-in `Footer` can't be
translated at render time. Factored into its own tiny module (2026-09-07, once a
fourth screen needed it) specifically so it stays import-light — no need to pull in
tui.py's much heavier dependency chain (scraper, storage, booking_watch) just for one
small widget.
"""

import copy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Header, Input, Label, Static, Switch

from . import club_config, i18n
from . import theme as theme_module
from .recommend import (
    DEFAULT_AVOID_RAIN_MM,
    DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT,
    DEFAULT_AVOID_WIND_KPH,
)
from .scrape_once import (
    DEFAULT_SCRAPE_INTERVAL_MINUTES,
    DEFAULT_SCRAPE_INTERVAL_MINUTES_BOOKED,
)
from .translated_footer import TranslatedFooter  # noqa: F401 -- re-exported, see that module


def _get_path(config: dict, path: tuple[str, ...], default: Any = None) -> Any:
    node = config
    for key in path[:-1]:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    return node.get(path[-1], default) if isinstance(node, dict) else default


def _set_path(config: dict, path: tuple[str, ...], value: Any) -> None:
    node = config
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = value


@dataclass
class Field:
    """One editable setting. `kind` picks the widget and how its value round-trips:
    "int" -> Input parsed as an int (never blank -- always has a real default);
    "optional_float" -> Input parsed as a float, blank means "not set" (None), for
    thresholds that are legitimately optional (e.g. no temperature floor at all);
    "optional_time" -> Input held as a raw "HH:MM" string or blank -> None;
    "bool" -> Switch.

    `label_key` is an i18n.py key, not literal text — looked up at compose() time so
    the label reflects whatever language is current then, not whatever it was when
    FIELDS (a module-level list, built once at import time) was first defined.
    """

    label_key: str
    path: tuple[str, ...]
    kind: str
    default: Any = None


FIELDS: list[Field] = [
    Field("settings.field.min_open_spots", ("availability", "min_open_spots"), "int", 1),
    Field("settings.field.weekday_after", ("availability", "weekday_window", "after"), "optional_time"),
    Field("settings.field.weekday_before", ("availability", "weekday_window", "before"), "optional_time"),
    Field("settings.field.weekend_after", ("availability", "weekend_window", "after"), "optional_time"),
    Field("settings.field.weekend_before", ("availability", "weekend_window", "before"), "optional_time"),
    Field("settings.field.buffer_minutes", ("availability", "buffer_minutes"), "int", 0),
    Field("settings.field.avoid_rain", ("preferences", "avoid_rain"), "bool", False),
    Field(
        "settings.field.avoid_rain_probability",
        ("preferences", "avoid_rain_probability_percent"),
        "optional_float",
        DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT,
    ),
    Field(
        "settings.field.avoid_rain_mm",
        ("preferences", "avoid_rain_mm"),
        "optional_float",
        DEFAULT_AVOID_RAIN_MM,
    ),
    Field("settings.field.avoid_wind", ("preferences", "avoid_wind"), "bool", False),
    Field(
        "settings.field.avoid_wind_kph",
        ("preferences", "avoid_wind_kph"),
        "optional_float",
        DEFAULT_AVOID_WIND_KPH,
    ),
    Field("settings.field.avoid_temp_below", ("preferences", "avoid_temp_below_c"), "optional_float"),
    Field("settings.field.avoid_temp_above", ("preferences", "avoid_temp_above_c"), "optional_float"),
    Field("settings.field.prioritize_friends", ("preferences", "prioritize_friends"), "bool", False),
    Field("settings.field.avoid_predicted_crowd", ("preferences", "avoid_predicted_crowd"), "bool", False),
    Field("settings.field.daylight_buffer", ("daylight_buffer_minutes",), "int", 30),
    Field(
        "settings.field.scrape_interval_normal",
        ("scrape_interval_minutes",),
        "int",
        DEFAULT_SCRAPE_INTERVAL_MINUTES,
    ),
    Field(
        "settings.field.scrape_interval_booked",
        ("scrape_interval_minutes_booked",),
        "int",
        DEFAULT_SCRAPE_INTERVAL_MINUTES_BOOKED,
    ),
]


def _field_id(field: Field) -> str:
    return "field-" + "-".join(field.path)


def config_to_widget_values(config: dict) -> dict[str, Any]:
    """What each field's widget should show, given a loaded club config. Pure
    function — kept separate from the widgets themselves so it's testable without a
    running Textual app."""
    values: dict[str, Any] = {}
    for field in FIELDS:
        raw = _get_path(config, field.path, field.default)
        if field.kind == "bool":
            values[_field_id(field)] = bool(raw)
        elif raw is None:
            values[_field_id(field)] = ""
        else:
            values[_field_id(field)] = str(raw)
    return values


def widget_values_to_config(config: dict, widget_values: dict[str, Any]) -> dict:
    """Apply edited widget values back onto a copy of `config`. Pure function, no
    Textual involved — the app just supplies what's currently in each widget."""
    updated = copy.deepcopy(config)
    for field in FIELDS:
        raw = widget_values[_field_id(field)]
        if field.kind == "bool":
            _set_path(updated, field.path, bool(raw))
        elif field.kind == "int":
            text = str(raw).strip()
            _set_path(updated, field.path, int(text) if text else field.default)
        elif field.kind == "optional_float":
            text = str(raw).strip()
            _set_path(updated, field.path, float(text) if text else None)
        elif field.kind == "optional_time":
            text = str(raw).strip()
            _set_path(updated, field.path, text if text else None)

    # A time window with neither "after" nor "before" set means "no window at all"
    # (see search.py's SearchCriteria docstring: a day type with no window configured
    # is skipped entirely) -- an empty {"after": None, "before": None} dict would mean
    # something different (any time is fine), so collapse it back to nothing.
    for window_key in ("weekday_window", "weekend_window"):
        window = updated.get("availability", {}).get(window_key)
        if window is not None and window.get("after") is None and window.get("before") is None:
            del updated["availability"][window_key]

    return updated


class SettingsScreen(App[None]):
    """Edit one club's availability/preferences/scrape-interval settings and save them
    back to its YAML file."""

    CSS = """
    #fields {
        padding: 1 2;
    }
    .field-row {
        height: 3;
        align: left middle;
    }
    .field-label {
        width: 42;
        content-align: right middle;
        padding-right: 2;
    }
    .field-input {
        width: 20;
    }
    #status {
        padding: 0 2;
        color: $text-muted;
    }
    #buttons {
        padding: 1 2;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("q", "binding.quit")]

    def __init__(
        self,
        club_id: str,
        clubs_dir: Path = club_config.CLUBS_DIR,
        on_saved: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__()
        self.club_id = club_id
        self.clubs_dir = clubs_dir
        self._on_saved = on_saved
        self.config = club_config.load_club_config(club_id, clubs_dir)

    def on_mount(self) -> None:
        theme_module.apply_theme(self)
        i18n.apply_language()

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="fields"):
            values = config_to_widget_values(self.config)
            for field in FIELDS:
                widget_id = _field_id(field)
                with Horizontal(classes="field-row"):
                    yield Label(i18n.t(field.label_key), classes="field-label")
                    if field.kind == "bool":
                        yield Switch(value=values[widget_id], id=widget_id, classes="field-input")
                    else:
                        yield Input(value=values[widget_id], id=widget_id, classes="field-input")
        yield Static("", id="status")
        with Horizontal(id="buttons"):
            yield Button(i18n.t("button.save"), id="save", variant="success")
            yield Button(i18n.t("button.quit"), id="quit")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def _read_widget_values(self) -> dict[str, Any]:
        widget_values: dict[str, Any] = {}
        for field in FIELDS:
            widget_id = _field_id(field)
            widget = self.query_one(f"#{widget_id}")
            widget_values[widget_id] = widget.value
        return widget_values

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.exit()
            return
        if event.button.id == "save":
            try:
                updated = widget_values_to_config(self.config, self._read_widget_values())
            except ValueError as exc:
                self.query_one("#status", Static).update(i18n.t("settings.not_saved", error=exc))
                return
            club_config.save_club_config(self.club_id, updated, self.clubs_dir)
            self.config = updated
            if self._on_saved is not None:
                self._on_saved(updated)
            self.query_one("#status", Static).update(i18n.t("settings.saved"))


def main() -> None:
    if len(sys.argv) > 1:
        club_id = sys.argv[1]
    else:
        clubs = club_config.list_clubs()
        if len(clubs) == 1:
            club_id = clubs[0]
        elif not clubs:
            print("No clubs saved yet — copy clubs/club.example.yaml first.")
            return
        else:
            print("More than one club saved — pass one: " + ", ".join(clubs))
            return

    SettingsScreen(club_id).run()


if __name__ == "__main__":
    main()
