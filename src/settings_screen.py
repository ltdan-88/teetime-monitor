"""A minimal Textual screen for editing your standing availability/weather preferences
and scrape interval — built ahead of the full tee-sheet TUI (ROADMAP.md Phase 4), per
direct feedback (2026-09-06) that these needed to be adjustable from the UI, not just
by hand-editing YAML.

Deliberately narrow — a screen for exactly the settings that came up in that feedback:
`availability` (min open spots, time windows, buffer), `preferences` (rain/wind/
temperature thresholds, friend/crowd weighting), and the scrape interval added the
same day.

**Global, not per-club** (reworked 2026-09-08, direct follow-up: "i also want the
settings/preferences to be global and not tied to a specific club"). These were
originally one block inside each club's own `clubs/*.yaml`, which meant re-entering
the same standing rules into every second club you added — your own availability and
weather comfort don't change depending on which course you're looking at, so that was
never actually a per-club fact, just modeled as one. Now reads/writes
`global_preferences.py`'s one shared file instead. Everything genuinely per-club
(`club_id`, `location`, `calendar`, `overview_days`, `default_course`, `identity`,
`ai_assist`, `round_duration_minutes`) still lives in `clubs/*.yaml`, untouched by
this screen, and hand-edited for now — those are set-once-at-setup values, not
day-to-day dials, and each one really does vary by club.

`SettingsScreen` is a plain `Screen[dict | None]`, not a standalone `App` — pushed
from `tui.py` (bound to `e` on both `OverviewScreen` and `DayDetailScreen`, added
2026-09-08 once a real user asked "i don't even know where to configure from the UI":
until then this really was only reachable as its own separate command, a genuine gap
this whole module's own docstring used to describe as deliberate rather than naming as
the limitation it was). Still runnable on its own too, via the thin `SettingsApp`
wrapper: `python -m src.settings_screen` — no club argument any more, now that there's
only one (global) settings set to open.

Saving writes the whole file back via `global_preferences.save_preferences()` — see
that function's docstring for the one known limitation carried over from
`club_config.save_club_config()` (comments don't survive a save).

Bilingual (added 2026-09-06, alongside tui.py's own i18n.py wiring): every field
label/button/status message goes through i18n.py, same as every other screen in this
project. `SettingsApp` applies the resolved theme/language on startup for the
standalone case; pushed from `tui.py` it inherits whatever's already applied there,
same as every other pushed screen. No in-app language-switch command here, unlike
tui.py itself — switch language from the main TUI (persists to the shared config
file) and this screen picks it up next time it's opened. Its footer's key hint
("q Quit") is rendered by a small `TranslatedFooter` — see
translated_footer.py's docstring for why Textual's built-in `Footer` can't be
translated at render time. Factored into its own tiny module (2026-09-07, once a
fourth screen needed it) specifically so it stays import-light — no need to pull in
tui.py's much heavier dependency chain (scraper, storage, booking_watch) just for one
small widget.
"""

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Label, Static, Switch

from . import global_preferences, i18n
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


class SettingsScreen(Screen[dict | None]):
    """Edit your standing availability/preferences/scrape-interval settings and save
    them back to the one shared file (see module docstring — no longer per-club).
    Dismisses with the final config dict (whether or not a save actually happened
    during the screen's lifetime — a caller that only cares "did a save happen"
    should use `on_saved` instead, which only fires on an actual save)."""

    CSS = """
    #fields {
        padding: 1 2;
        height: 1fr;
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
        /* Textual's own Horizontal container defaults to height: 1fr, same as
           VerticalScroll (#fields above) -- with nothing overriding it, this row of
           two buttons was claiming an equal fractional share of the whole screen's
           remaining height as the entire fields list, leaving most of a tall
           terminal window as dead, empty space below a stub of visible fields.
           Direct feedback (a real screenshot, 2026-09-08): "the settings menu
           doesn't fill out vertical space from my window" -- exactly this: #fields
           needed the space #buttons was silently taking, not more space overall.
           auto lets #buttons take only what its two buttons actually need, so
           #fields' own height: 1fr above can claim everything else. */
        height: auto;
    }
    """

    BINDINGS = [("q", "quit_screen", "Quit")]
    _FOOTER_BINDINGS = [("q", "binding.quit")]

    def __init__(
        self,
        preferences_file: Path | None = None,
        on_saved: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__()
        # Resolved at call time, not bound as a class-definition-time default -- see
        # env_file.py's module docstring for the frozen-default gotcha this avoids
        # (a caller/test monkeypatching global_preferences.PREFERENCES_FILE after
        # this module's own import must still be honored).
        self.preferences_file = (
            preferences_file if preferences_file is not None else global_preferences.PREFERENCES_FILE
        )
        self._on_saved = on_saved
        self.config = global_preferences.load_preferences(self.preferences_file)

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

    def action_quit_screen(self) -> None:
        self.dismiss(self.config)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.action_quit_screen()
            return
        if event.button.id == "save":
            try:
                updated = widget_values_to_config(self.config, self._read_widget_values())
            except ValueError as exc:
                self.query_one("#status", Static).update(i18n.t("settings.not_saved", error=exc))
                return
            global_preferences.save_preferences(updated, self.preferences_file)
            self.config = updated
            if self._on_saved is not None:
                self._on_saved(updated)
            self.query_one("#status", Static).update(i18n.t("settings.saved"))


class SettingsApp(App[None]):
    """Thin standalone wrapper so SettingsScreen is runnable on its own:
    `python -m src.settings_screen`. No club argument any more (2026-09-08, once
    these settings became global) — there's only ever the one shared settings set to
    open. Not used when the screen is pushed from tui.py directly (`e` on
    OverviewScreen/DayDetailScreen) — that app supplies its own theme/language setup
    and push_screen_wait() call directly."""

    TITLE = "teetime-monitor"

    def on_mount(self) -> None:
        theme_module.apply_theme(self)
        i18n.apply_language()
        self.push_screen(SettingsScreen(), lambda _config: self.exit())


def main() -> None:
    SettingsApp().run()


if __name__ == "__main__":
    main()
