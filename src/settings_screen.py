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
`round_duration_minutes`) still lives in `clubs/*.yaml`, untouched by this screen, and
hand-edited for now — those are set-once-at-setup values, not day-to-day dials, and
each one really does vary by club.

`ai_assist` (whether recommendations get AI-ranked, and which model) joined the
global side the same day, direct request right after discussing turning it on for
the first time: "the ai feature should be an option in the settings menu." It was
originally kept per-club deliberately ("which model to spend on which call is a
cost/quality tradeoff that's yours to set" — see an earlier version of
`global_preferences.py`'s own docstring), but nothing about wanting AI ranking on or
off actually varies by club here, and the ask itself was for one switch, not a
per-club dial — same shape of correction as the availability/weather move above.
`_resolved_config()`'s existing shallow merge (global overrides a club's own YAML)
means a club file that still has its own `ai_assist` block keeps working as a
fallback; it just no longer wins once this screen has actually set one.

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

Reworked again the same day for a 6-point UI/UX critique (direct feedback, quoted
per-point in the CSS/compose() comments closest to each fix rather than here):
fields now render one row tall instead of three and line up with their labels
(`compact=True` on Input/Select, a border-less `Switch`); fields whose real values
only ever come from a small known set (`min_open_spots`, the daylight buffer, both
scrape intervals) are now `Select` dropdowns instead of free text, while genuine
ranges (time windows, weather thresholds) stay free text -- Textual has no
range-slider widget at all, and a discrete dropdown would either be too coarse or
too long a list to beat just typing a number for those; fields are grouped into
four `Collapsible` sections (Availability / Weather / Priorities / Timing &
scraping); and Save/Quit are right-aligned, Quit-then-Save, matching the ordinary
OS-dialog "Cancel ... Save" convention instead of hugging the window's left edge.

**Narrow-window fallback** (same-day follow-up: "I'd like that made more flexible
too" — the side-by-side label/field layout above needs roughly 70 columns and had
nowhere to shrink to below that, clipping the field clean off screen). This Textual
version has no CSS media query, so `on_resize()`/`_update_narrow_class()` measure
the screen's actual width and toggle a `-narrow` class; while set, every field row
switches from side-by-side to label-above-field (both full width) via the
`SettingsScreen.-narrow` CSS rules below — taller, but nothing is ever hidden or
cut off, which matters more at a narrow width than staying compact does.

**Time fields split into hour/minute** (same-day follow-up: "can you at least
split the input boxes for the time ranges into something like hh:mm?"). The four
weekday/weekend window fields were a single free-text "17:00"-or-blank `Input` --
now two small `Select` dropdowns (hour, minute) joined by a `:` separator, matching
the same "small known set of values -> dropdown" treatment `min_open_spots` and the
scrape intervals already got. `_time_widget_ids()` and the "optional_time" branches
of `compose()`/`_read_widget_values()` are the only places that know a time field
is really two widgets -- `widget_values_to_config()` still receives one plain
"HH:MM" string per field, same as before this change, since `_read_widget_values()`
recombines the two dropdowns' values before handing them off.

**Buffer split into before/after** (same-day follow-up, after being asked whether a
symmetric buffer actually made sense: "split it like in your recommendation, and
make it a dropdown in 10 minute increments"). The one `buffer_minutes` field became
two -- `buffer_before_minutes`/`buffer_after_minutes` in `search.py`'s
`SearchCriteria` and everywhere that reads `availability` -- since the group ahead
of you slowing your pace and the group behind you crowding in aren't the same
concern. Both render here as `Select` dropdowns in 10-minute steps (`BUFFER_CHOICES`
below), the same treatment as `min_open_spots`/the scrape intervals. See
`search.resolve_buffer_minutes()`'s own docstring for how a config saved before
this split (still just `buffer_minutes`) keeps working unchanged.

**Hour dropdown trimmed to plausible tee times** (same-day follow-up: "can you
please remove hours that don't make sense from the dropdown menus?"). The
weekday/weekend window hour `Select` used to offer the full 00-23 -- including
hours no golf club is ever open at. `HOUR_CHOICES` now only spans
`EARLIEST_TEE_HOUR`-`LATEST_TEE_HOUR` (05:00-21:00), comfortably covering real
confirmed tee times (as early as 06:40, see docs/pccaddie-markup-notes.md) with
room on both ends. A saved value outside that range still loads and stays
selectable -- the same generic "keep the actual current value selectable"
mechanism every other dropdown here already relies on, not new migration logic.

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

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Header, Input, Label, Select, Static, Switch

from . import global_preferences, i18n
from . import theme as theme_module
from .ai_assist import DEFAULT_MODEL
from .recommend import (
    DEFAULT_AVOID_RAIN_MM,
    DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT,
    DEFAULT_AVOID_WIND_KPH,
)
from .scrape_once import (
    DEFAULT_SCRAPE_INTERVAL_MINUTES,
    DEFAULT_SCRAPE_INTERVAL_MINUTES_BOOKED,
)
from .search import resolve_buffer_minutes
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


def _int_choices(*values: int) -> list[tuple[str, str]]:
    """A fixed preset list for a field whose real-world values only ever come from a
    small, known set (a scrape interval, a buffer count) -- direct feedback
    (2026-09-08): "many of the entry fields could be dropdowns since the selection
    options are mostly limited." A dropdown can't hold an invalid string the way a
    free-text Input could, so it also closes off a whole class of "not a number"
    mistakes for exactly the fields where that's true."""
    return [(f"{v} min" if v else "0", str(v)) for v in values]


# Presets deliberately stop short of every remotely-plausible value -- these are
# "the values someone actually picks in practice," not an exhaustive range. A value
# saved from outside this list (hand-edited YAML, or a preset list that later
# changes) still round-trips correctly -- see compose()'s "keep the actual current
# value selectable" handling below, which adds it to the list rather than silently
# discarding it.
DAYLIGHT_BUFFER_CHOICES = _int_choices(0, 15, 30, 45, 60, 90)
# Includes scrape_once.py's own DEFAULT_SCRAPE_INTERVAL_MINUTES (360) -- an earlier
# version of this list left it out, so a freshly-created settings file (nothing
# saved yet, everything on its default) showed a plain unlabeled "360" instead of
# "360 min" like every other preset, since a value outside the list is added back in
# under its own raw string rather than through _int_choices' " min" formatting (see
# compose()'s "keep the actual current value selectable" handling).
SCRAPE_INTERVAL_NORMAL_CHOICES = _int_choices(5, 10, 15, 30, 60, 120, 360)
SCRAPE_INTERVAL_BOOKED_CHOICES = _int_choices(15, 30, 60, 120, 240)
MIN_OPEN_SPOTS_CHOICES = [(str(n), str(n)) for n in (1, 2, 3, 4)]
# Direct follow-up (2026-09-08, after the before/after buffer split): "split it
# like in your recommendation, and make it a dropdown in 10 minute increments."
BUFFER_CHOICES = _int_choices(0, 10, 20, 30, 40, 50, 60)
# Added 2026-09-08 alongside settings.field.ai_assist_model -- the real Claude model
# family names available at the time this was wired in (see ai_assist.DEFAULT_MODEL),
# not an exhaustive list of every model Anthropic has ever shipped. Displayed as their
# own raw names rather than through _int_choices()'s " min" formatting -- there's no
# unit to append here, the id itself is the whole label.
AI_MODEL_CHOICES = [(model, model) for model in ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001")]

# Direct follow-up (2026-09-08): "can you at least split the input boxes for the
# time ranges into something like hh:mm?" -- each "optional_time" field below (a
# free-text "17:00"-or-blank Input until now) renders as two small Select
# dropdowns instead, hour and minute, joined by a ":" separator -- see compose()'s
# "optional_time" branch and _time_widget_ids() below. "--" (an empty string
# value) means "not set" for the hour; a blank minute with an hour chosen collapses
# to :00 (see _read_widget_values()'s combining logic) rather than being a second,
# redundant way to mean "not set."
# Direct follow-up (2026-09-08): "can you please remove hours that don't make
# sense from the dropdown menus?" -- the full 00-23 range included plenty of hours
# no golf club is ever open at (a "workdays after 02:00" window makes no sense).
# 05:00-21:00 comfortably covers real confirmed tee times seen live (as early as
# 06:40, see docs/pccaddie-markup-notes.md) with room on both ends for an
# early-summer sunrise round or a last-light evening one, without offering the
# entire clock. An existing config with an hour outside this range (hand-edited,
# or saved before this change) still loads and stays selectable -- see compose()'s
# "keep the actual current value selectable" handling, the same generic mechanism
# every other dropdown on this screen already relies on, not something added for
# this specifically.
EARLIEST_TEE_HOUR = 5
LATEST_TEE_HOUR = 21
HOUR_CHOICES = [("--", "")] + [
    (f"{h:02d}", f"{h:02d}") for h in range(EARLIEST_TEE_HOUR, LATEST_TEE_HOUR + 1)
]
MINUTE_CHOICES = [("--", "")] + [(f"{m:02d}", f"{m:02d}") for m in (0, 15, 30, 45)]


@dataclass
class Field:
    """One editable setting. `kind` picks how its value round-trips regardless of
    which widget renders it:
    "int" -> parsed as an int (never blank -- always has a real default);
    "optional_float" -> parsed as a float, blank means "not set" (None), for
    thresholds that are legitimately optional (e.g. no temperature floor at all);
    "optional_time" -> held as a raw "HH:MM" string or blank -> None;
    "bool" -> Switch;
    "str" -> a plain string, unparsed, blank falls back to `default` -- added
    2026-09-08 for `ai_assist.model` (a Claude model id), the first field here that
    isn't a number/flag/time. Always paired with `choices` in practice (a free-text
    model name would invite typos a fixed-choice quality/cost dropdown avoids), but
    nothing about "str" itself requires that.

    `choices`, when set, renders this field as a `Select` dropdown instead of a
    free-text `Input` -- see FIELDS below for which fields qualify (a small, known
    set of values) versus which stay free text (a genuine range, or a value where a
    dropdown would be either too coarse or too long to beat just typing a number --
    see the module docstring's "range values" note). Either way `widget.value` comes
    back as the same plain string, so the "int"/"optional_float"/"optional_time"
    parsing above needs no knowledge of which widget produced it.

    `group_key` is an i18n.py key naming the `Collapsible` section this field
    appears under (2026-09-08 direct feedback: "entries in settings could be grouped
    into categories, to make it more user friendly") -- see GROUP_ORDER below for
    the section order.

    `label_key` is an i18n.py key, not literal text — looked up at compose() time so
    the label reflects whatever language is current then, not whatever it was when
    FIELDS (a module-level list, built once at import time) was first defined.
    """

    label_key: str
    path: tuple[str, ...]
    kind: str
    group_key: str
    default: Any = None
    choices: list[tuple[str, str]] | None = None


GROUP_ORDER = [
    "settings.group.availability",
    "settings.group.weather",
    "settings.group.priorities",
    "settings.group.ai",
    "settings.group.timing",
]

FIELDS: list[Field] = [
    Field(
        "settings.field.min_open_spots",
        ("availability", "min_open_spots"),
        "int",
        "settings.group.availability",
        1,
        choices=MIN_OPEN_SPOTS_CHOICES,
    ),
    Field(
        "settings.field.weekday_after",
        ("availability", "weekday_window", "after"),
        "optional_time",
        "settings.group.availability",
    ),
    Field(
        "settings.field.weekday_before",
        ("availability", "weekday_window", "before"),
        "optional_time",
        "settings.group.availability",
    ),
    Field(
        "settings.field.weekend_after",
        ("availability", "weekend_window", "after"),
        "optional_time",
        "settings.group.availability",
    ),
    Field(
        "settings.field.weekend_before",
        ("availability", "weekend_window", "before"),
        "optional_time",
        "settings.group.availability",
    ),
    Field(
        "settings.field.buffer_before_minutes",
        ("availability", "buffer_before_minutes"),
        "int",
        "settings.group.availability",
        0,
        choices=BUFFER_CHOICES,
    ),
    Field(
        "settings.field.buffer_after_minutes",
        ("availability", "buffer_after_minutes"),
        "int",
        "settings.group.availability",
        0,
        choices=BUFFER_CHOICES,
    ),
    Field("settings.field.avoid_rain", ("preferences", "avoid_rain"), "bool", "settings.group.weather", False),
    Field(
        "settings.field.avoid_rain_probability",
        ("preferences", "avoid_rain_probability_percent"),
        "optional_float",
        "settings.group.weather",
        DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT,
    ),
    Field(
        "settings.field.avoid_rain_mm",
        ("preferences", "avoid_rain_mm"),
        "optional_float",
        "settings.group.weather",
        DEFAULT_AVOID_RAIN_MM,
    ),
    Field("settings.field.avoid_wind", ("preferences", "avoid_wind"), "bool", "settings.group.weather", False),
    Field(
        "settings.field.avoid_wind_kph",
        ("preferences", "avoid_wind_kph"),
        "optional_float",
        "settings.group.weather",
        DEFAULT_AVOID_WIND_KPH,
    ),
    Field(
        "settings.field.avoid_temp_below",
        ("preferences", "avoid_temp_below_c"),
        "optional_float",
        "settings.group.weather",
    ),
    Field(
        "settings.field.avoid_temp_above",
        ("preferences", "avoid_temp_above_c"),
        "optional_float",
        "settings.group.weather",
    ),
    Field(
        "settings.field.prioritize_friends",
        ("preferences", "prioritize_friends"),
        "bool",
        "settings.group.priorities",
        False,
    ),
    Field(
        "settings.field.avoid_predicted_crowd",
        ("preferences", "avoid_predicted_crowd"),
        "bool",
        "settings.group.priorities",
        False,
    ),
    # Moved here from clubs/*.yaml, 2026-09-08 direct request: "the ai feature should
    # be an option in the settings menu" -- ai_assist was originally kept per-club
    # ("which model to spend on which call is a cost/quality tradeoff that's yours to
    # set" -- see global_preferences.py's own docstring), but nothing about wanting AI
    # ranking on or off actually varies by club for this developer, and the explicit
    # ask was for one on/off switch, not a per-club dial. `_resolved_config()`'s
    # existing shallow merge (global preferences override a club's own YAML) means a
    # club file that still has its own `ai_assist` block keeps working as a fallback
    # -- this only takes priority once actually set here.
    Field(
        "settings.field.ai_assist_enabled",
        ("ai_assist", "enabled"),
        "bool",
        "settings.group.ai",
        False,
    ),
    Field(
        "settings.field.ai_assist_model",
        ("ai_assist", "model"),
        "str",
        "settings.group.ai",
        DEFAULT_MODEL,
        choices=AI_MODEL_CHOICES,
    ),
    Field(
        "settings.field.daylight_buffer",
        ("daylight_buffer_minutes",),
        "int",
        "settings.group.timing",
        30,
        choices=DAYLIGHT_BUFFER_CHOICES,
    ),
    Field(
        "settings.field.scrape_interval_normal",
        ("scrape_interval_minutes",),
        "int",
        "settings.group.timing",
        DEFAULT_SCRAPE_INTERVAL_MINUTES,
        choices=SCRAPE_INTERVAL_NORMAL_CHOICES,
    ),
    Field(
        "settings.field.scrape_interval_booked",
        ("scrape_interval_minutes_booked",),
        "int",
        "settings.group.timing",
        DEFAULT_SCRAPE_INTERVAL_MINUTES_BOOKED,
        choices=SCRAPE_INTERVAL_BOOKED_CHOICES,
    ),
]


def _field_id(field: Field) -> str:
    return "field-" + "-".join(field.path)


def _time_widget_ids(field: Field) -> tuple[str, str]:
    """The hour/minute Select ids for an "optional_time" field -- see FIELDS'
    weekday/weekend window entries. Kept separate from `_field_id()` itself since
    every other kind still renders as exactly one widget under that one id;
    `_read_widget_values()` recombines these two back into that same base id's
    "HH:MM" string, so `widget_values_to_config()` never needs to know a time field
    was ever split into two widgets at all."""
    base = _field_id(field)
    return f"{base}-hh", f"{base}-mm"


_BUFFER_PATHS = {
    ("availability", "buffer_before_minutes"): "before",
    ("availability", "buffer_after_minutes"): "after",
}


def config_to_widget_values(config: dict) -> dict[str, Any]:
    """What each field's widget should show, given a loaded club config. Pure
    function — kept separate from the widgets themselves so it's testable without a
    running Textual app."""
    values: dict[str, Any] = {}
    for field in FIELDS:
        if field.path in _BUFFER_PATHS:
            # A config saved before the 2026-09-08 before/after split only has the
            # old single buffer_minutes key -- plain _get_path() below would show
            # "0" for both new dropdowns even though the buffer is actually still
            # in effect (search.py/scrape_once.py both fall back to it too, via
            # resolve_buffer_minutes() -- see that function's own docstring). Using
            # the same fallback here means what this screen displays always
            # matches what the app is actually doing, not just what's literally
            # under the new key yet.
            raw = resolve_buffer_minutes(config.get("availability", {}), _BUFFER_PATHS[field.path], field.default)
        else:
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
        elif field.kind == "str":
            text = str(raw).strip()
            _set_path(updated, field.path, text if text else field.default)

    # A time window with neither "after" nor "before" set means "no window at all"
    # (see search.py's SearchCriteria docstring: a day type with no window configured
    # is skipped entirely) -- an empty {"after": None, "before": None} dict would mean
    # something different (any time is fine), so collapse it back to nothing.
    for window_key in ("weekday_window", "weekend_window"):
        window = updated.get("availability", {}).get(window_key)
        if window is not None and window.get("after") is None and window.get("before") is None:
            del updated["availability"][window_key]

    # Both new buffer_before_minutes/buffer_after_minutes keys are always written
    # above (they're ordinary "int" fields, same as any other) -- once that's
    # happened, an old single buffer_minutes key left over from before the split
    # would just be dead, unread weight in the saved file, confusing to find later
    # ("why doesn't editing this do anything?"). Dropped here rather than left to
    # linger.
    availability = updated.get("availability")
    if availability is not None:
        availability.pop("buffer_minutes", None)

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
    .field-group {
        margin-bottom: 1;
    }
    .field-row {
        /* Was height: 3, matching Input's own default bordered rendering (a top
           border row + a content row + a bottom border row) -- three display rows
           for one setting, and visibly taller than the one-row Label next to it, so
           the two never looked vertically aligned. Direct feedback (2026-09-08):
           "the settings entries take too much vertical space... the labels are not
           aligned vertically with the entry fields." Input/Select below now render
           `compact=True` (border-less, one row -- see Textual's own DEFAULT_CSS for
           both, gated behind the `-textual-compact` class), and Switch gets the
           same one-row treatment via the `Switch.field-input` rule below (it has no
           compact flag of its own), so every field genuinely is one row now,
           matching .field-label's own height and finally lining up with it. */
        height: 1;
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
    Switch.field-input {
        /* Switch has no `compact` flag the way Input/Select do -- its own
           DEFAULT_CSS always draws a `border: tall`, which alone makes it 3 rows
           tall (height: auto around a 1-row slider plus its own top/bottom border).
           Dropping the border directly is the only way to bring it down to the same
           one row as everything else in .field-row. */
        border: none;
        height: 1;
    }
    /* Narrow-window fallback (direct follow-up, 2026-09-08, to the row-height fix
       above): a 42-column label next to a 20-column field needs roughly 65+ columns
       total once #fields' own padding and Collapsible's left padding are counted --
       below that the two-column layout above had nowhere to shrink to and started
       clipping the field clean off screen. Textual has no CSS media query in this
       version, so `_update_narrow_class()` below measures the real width itself and
       toggles this `-narrow` class; while set, every field row switches from
       side-by-side to label-above-field, each spanning the full row -- more rows
       per field again, but nothing is ever hidden or cut off, which matters more at
       a narrow width than staying compact does. */
    SettingsScreen.-narrow .field-row {
        layout: vertical;
        height: auto;
        align: left top;
    }
    SettingsScreen.-narrow .field-label {
        width: 100%;
        content-align: left middle;
        padding: 0;
    }
    SettingsScreen.-narrow .field-input {
        width: 100%;
    }
    /* Direct follow-up (2026-09-08): "can you at least split the input boxes for
       the time ranges into something like hh:mm?" -- .field-time-group holds the
       hour/minute pair together as its own small unit rather than each spanning
       the whole row's width like a single .field-input would; not `.field-input`
       itself, so it's unaffected by `SettingsScreen.-narrow .field-input`'s
       width: 100% above -- a 2-character dropdown never needs to stretch that far,
       narrow window or not. */
    .field-time-group {
        width: auto;
        height: 1;
    }
    .time-part {
        width: 8;
    }
    .field-time-sep {
        width: 1;
        content-align: center middle;
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
        /* Common dialog convention (direct feedback, 2026-09-08: "buttons ... need
           to follow common layout conventions regarding placement (iirc usually
           those buttons are aligned to the right)") -- the secondary/dismissive
           action (Quit) sits to the left of the primary one (Save), which is
           rightmost, matching the OS-dialog "Cancel ... Save" convention rather
           than the button row hugging the window's left edge. */
        align: right middle;
    }
    """

    BINDINGS = [("q", "quit_screen", "Quit")]
    _FOOTER_BINDINGS = [("q", "binding.quit")]

    # Below this width the side-by-side label/field layout has nowhere left to
    # shrink to (see the CSS comment above `.-narrow` for the arithmetic) -- picked
    # empirically by resizing a live terminal down column by column until a
    # `Select` field's own dropdown arrow started getting clipped off (at 70-71
    # columns, one to two columns before the row overflowed outright), not derived
    # from a formula, since Collapsible's own padding and Textual's own
    # text-measurement aren't exposed cheaply enough to compute this ahead of time.
    NARROW_WIDTH_THRESHOLD = 72

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

    def on_mount(self) -> None:
        self._update_narrow_class(self.size.width)

    def on_resize(self, event: events.Resize) -> None:
        # `events.Resize` doesn't bubble (see Textual's own docstring for it), so
        # this has to live directly on the Screen -- it's the widget that's
        # actually resized when the terminal window is, not something a child
        # widget further down would ever receive on its own.
        self._update_narrow_class(event.size.width)

    def _update_narrow_class(self, width: int) -> None:
        self.set_class(width < self.NARROW_WIDTH_THRESHOLD, "-narrow")

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="fields"):
            values = config_to_widget_values(self.config)
            fields_by_group: dict[str, list[Field]] = {}
            for field in FIELDS:
                fields_by_group.setdefault(field.group_key, []).append(field)
            # Grouped into labeled, expanded-by-default sections (2026-09-08 direct
            # feedback: "entries in settings could be grouped into categories, to
            # make it more user friendly") -- expanded by default since these are
            # settings you're here to look at, not a wall of text worth hiding.
            for group_key in GROUP_ORDER:
                with Collapsible(title=i18n.t(group_key), collapsed=False, classes="field-group"):
                    for field in fields_by_group.get(group_key, []):
                        widget_id = _field_id(field)
                        current = values[widget_id]
                        with Horizontal(classes="field-row"):
                            yield Label(i18n.t(field.label_key), classes="field-label")
                            if field.kind == "bool":
                                yield Switch(value=current, id=widget_id, classes="field-input")
                            elif field.kind == "optional_time":
                                hh, _, mm = current.partition(":")
                                hh_id, mm_id = _time_widget_ids(field)
                                hour_options = HOUR_CHOICES
                                if hh not in {value for _, value in hour_options}:
                                    hour_options = [(hh, hh), *hour_options]
                                minute_options = MINUTE_CHOICES
                                if mm not in {value for _, value in minute_options}:
                                    minute_options = [(mm, mm), *minute_options]
                                with Horizontal(classes="field-time-group"):
                                    yield Select(
                                        hour_options,
                                        value=hh,
                                        allow_blank=False,
                                        compact=True,
                                        id=hh_id,
                                        classes="time-part",
                                    )
                                    yield Static(":", classes="field-time-sep")
                                    yield Select(
                                        minute_options,
                                        value=mm,
                                        allow_blank=False,
                                        compact=True,
                                        id=mm_id,
                                        classes="time-part",
                                    )
                            elif field.choices is not None:
                                options = field.choices
                                # A value saved outside the preset list (hand-edited
                                # YAML, or a preset list that changed since) must
                                # still be selectable -- Select raises rather than
                                # silently dropping a value that isn't among its
                                # options, so it's added in rather than lost.
                                if current not in {value for _, value in options}:
                                    options = [(current, current), *options]
                                yield Select(
                                    options,
                                    value=current,
                                    allow_blank=False,
                                    compact=True,
                                    id=widget_id,
                                    classes="field-input",
                                )
                            else:
                                yield Input(value=current, id=widget_id, classes="field-input", compact=True)
        yield Static("", id="status")
        with Horizontal(id="buttons"):
            yield Button(i18n.t("button.quit"), id="quit")
            yield Button(i18n.t("button.save"), id="save", variant="success")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def _read_widget_values(self) -> dict[str, Any]:
        widget_values: dict[str, Any] = {}
        for field in FIELDS:
            widget_id = _field_id(field)
            if field.kind == "optional_time":
                hh_id, mm_id = _time_widget_ids(field)
                hh = self.query_one(f"#{hh_id}").value
                mm = self.query_one(f"#{mm_id}").value
                # No hour chosen -- "not set," regardless of what the minute
                # dropdown happens to show. An hour with no minute chosen isn't a
                # second way to mean that -- it just means "on the hour."
                widget_values[widget_id] = f"{hh}:{mm or '00'}" if hh else ""
            else:
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
