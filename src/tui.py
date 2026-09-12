"""Textual app entry point — the multi-day overview (ROADMAP.md Phase 4), plus
club/course selection (Phase 0), ad hoc search (Phase 4) and the crowd-heatmap
readiness view (Phase 5). `OverviewScreen` added 2026-09-07 once the clubhouse-overview
mockup's design questions were resolved (see ROADMAP.md Phase 4 for that history);
`SearchScreen`/`HeatmapScreen` followed 2026-09-08, once their own backends
(`search.py`, `analytics.crowd_heatmap()`) already existed fully tested and just
needed a screen wired up to each — see `OverviewScreen`'s own docstring for how
they're reached (the Actions menu, `t` — no dedicated key of their own any more).

A separate single-day `DayDetailScreen` (implemented 2026-09-06, one row per slot:
Time | Occupancy | Players) was the original home screen every day-level action lived
on — expanding a day, confirming/cancelling a tee time, booking-watch banners, a
manual force-refresh. Retired entirely 2026-09-15 (direct follow-up, once
"expand-in-place" rows already put slot detail and confirm/cancel straight into
`OverviewScreen`: "why don't we integrate those missing features into the overview
screen. Would make this open full day view screen redundant, right?") once its last
two genuinely unique things — `x` (dismiss a booking-watch banner) and `r` (force a
re-scrape right now, bypassing the interval) — were ported onto `OverviewScreen`
itself (see that screen's own `refresh_banners()`/`action_refresh()`). See
ROADMAP.md for the full history of what that screen used to do and why each piece
moved where it did.

Startup flow:
0. `CredentialsScreen`, only if no login is configured at all yet (2026-09-10, direct
   request: "I want the login screen to appear first, whenever you don't have a
   login") — entirely skippable (`escape`/Cancel, same as anywhere else it's pushed),
   since real functionality below never actually required a login to begin with. See
   `TeetimeApp._start()`'s own docstring.
1. Club browser (`ClubBrowserScreen`) — the home screen. Search pc caddie's whole club
   directory, pick a favorite, or type a club id straight in; no club has to be saved
   to config first. Reworked 2026-09-07 on direct feedback that requiring a club to be
   saved before you could even look at it was backwards, and that saving one should
   only ever mean "favorite" (`f` toggles that, right on this screen).
2. Course picker (`CoursePickerScreen`) — skipped if the club's saved YAML (if it has
   one) sets a valid `default_course`, or if the club has only one course at all —
   which is 46% of them, per the cross-club sweep in scraper.py's module docstring.
3. `OverviewScreen` — the actual home screen, and (2026-09-15 on) the only one: one row
   per attempted day (weekday + exact ISO date, actual weather, that day's own event/
   closure note in a separate column, a six-block "heat strip" for 08:00-20:00, and
   that day's own pick — a confirmed booking, a recommended ★ slot, or why neither
   applies). A separate "This week's picks" summary used to repeat this same column
   one more time below the table; dropped 2026-09-14 once it turned out to be a
   strict, smaller subset of what the Pick column already showed (see that column's
   own `_day_pick_text()` docstring) — one source of truth now, not two. The cursor
   starts on today's own row, unless `_initial_date()` finds today's cached schedule
   already fully in the past (direct feedback 2026-09-07: showing "today" once the
   course has closed for the day isn't useful), in which case tomorrow's row is
   pre-highlighted instead. Enter expands whichever row is actually highlighted in
   place, showing that day's own slots directly beneath it — see this screen's own
   `on_data_table_row_selected()` docstring for the full expand/confirm/cancel
   interaction.

Any unacknowledged `storage.load_unacknowledged_booking_changes()` rows show as
banners at the top of `OverviewScreen` on open — this is what actually delivers the
"warn me if my booking's situation changes" feature end to end: scrape_once.py
detects and persists a change, this is what a person actually sees it in. The Pick
column surfaces the same fact more compactly too, as a "📌 HH:MM booked ⚠" pick for
that day.

Color themes (added 2026-09-06, "I'd like color themes like in brew launcher"): see
theme.py for the 10 named themes and how they resolve/persist. Applied once at
startup (`TeetimeApp.on_mount`); switching afterward is Textual's own command palette
(`ctrl+p`, or `t`/Actions on `OverviewScreen` — searchable, live preview, no relaunch
needed, unlike brew-launcher's own version) rather than a hand-built picker screen —
`watch_theme()` persists whatever the command palette picks, including a native
Textual theme with no brew-launcher equivalent.

Language (added 2026-09-06, "need to make sure the TUI is at least bilingual, since
it will be used in Germany"): see i18n.py for the English/German string table and how
it resolves/persists — same shape as theme.py's resolution, sharing the same config
file. Switching is a command-palette entry ("Language: switch to Deutsch"/"...to
English"), which also rebuilds the current `OverviewScreen` in place so every label,
table header, and status message updates immediately, not just on next launch.

Revised the same day, after the user spotted two things still in English in a
screenshot: the Footer's key-hint text does translate now too, via `TranslatedFooter`
below — Textual's built-in `Footer` derives its text from each Screen's `BINDINGS`
(a class-level attribute fixed at import time) with no public API found to override a
binding's displayed description at render time (confirmed empirically: `bind()` isn't
exposed on `Screen` in this Textual version, and the only paths that worked touched
private internals), so this renders its own translated hints from i18n.py instead,
independent of `BINDINGS`'s own (English, dispatch-only) description strings — the key
bindings themselves are unaffected, only what's displayed at the bottom of the screen.
`booking_watch.py`'s banner messages are now bilingual too — see that module and
storage.py's `booking_changes` table for the structured (kind + params) redesign that
replaced storing pre-rendered English prose.

Textual's own built-in command-palette entries (the default "Theme"/"Quit"/"Keys"/
"Screenshot"/"Maximize" system commands, from `App.get_system_commands()`'s own
base implementation) used to stay in whatever language Textual itself ships them
in — English — left alone since the original footer/banner report wasn't about
them specifically. Closed 2026-09-16, direct follow-up once the Actions menu (`t`)
became the only way to reach several of this app's own actions too: "can you
please translate everything in actions screen?" `TeetimeApp.get_system_commands()`
now maps each one to a translated title/description via
`_BASE_COMMAND_TRANSLATIONS` — see that dict's own docstring, including the
"logical arrangement" grouping added the same day.

Auto-refresh (added 2026-09-07, direct feedback: "can we make autorefresh for the
maximum timeframe, whenever you run the TUI and at the defined time intervals? I
think hitting 'r' makes only sense as a manual override"): `TeetimeApp` now calls
`scrape_once.scrape_due_for_club()` for the active club once right after opening, and
again every `AUTO_REFRESH_INTERVAL_SECONDS` while it keeps running — covering that
club's *whole* `overview_days` window, not just whatever single day happens to be on
screen, matching "maximum timeframe" from the request. `scrape_once._should_scrape()`
still throttles what's actually fetched each pass exactly as it already did for the
standalone scheduled job, so this doesn't scrape more often than each course/date's
own configured interval — it just means a cron job is no longer the only thing that
can trigger it. Runs in a background thread (`run_worker(..., thread=True)`) so
scraping the whole window doesn't freeze the UI; `r` (2026-09-15 on: `OverviewScreen`
itself, see `action_refresh()`) stays an always-immediate manual override, bypassing
`_should_scrape()`'s own throttle for the whole loaded window at once — the two are
independent, not one replacing the other.

Switching club/course + searching for a new club on the fly (added 2026-09-07,
direct feedback: "how can i switch to a different course from the time schedule
menu?" followed by "I want to be able to switch clubs on the fly. It is a hassle if
you need to first save clubs into the config"): Actions ("Find a club", reached via
`t` — no dedicated key of its own since 2026-09-16, see `OverviewScreen`'s own
docstring) opens `TeetimeApp.action_switch_club_or_course()` — which opens the very
same `ClubBrowserScreen` the app launches into, so switching mid-session and
choosing at launch behave identically (search the whole directory, jump straight to
a club id, favorite with `f`). Never shows a course picker at all any more
(2026-09-16, direct follow-up: "if a course picker is not necessary, then remove it
from the 'find a club' screen. Course picker is anyway implemented in overview
screen" — falls back to the club's own first course instead, same as the inline
course dropdown already did). Every picker screen (`ClubBrowserScreen`,
`CoursePickerScreen`) also gained `escape` (back out with nothing changed) and `q`
(quit the whole app) bindings — previously there was no way to back out of one
short of force-quitting, per direct feedback: "how do I quit from club/course
picker or return to the schedule?"
"""

import importlib.metadata
import sys
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult, SystemCommand
from textual.command import DiscoveryHit
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.system_commands import SystemCommandsProvider
from textual.widgets import Button, DataTable, Header, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from . import analytics, calendar_context, club_config, club_directory, geocode, global_preferences, playability
from . import recommend, scrape_once, storage
from . import i18n
from . import units as units_module
from . import weather_icons
from . import theme as theme_module
from .credentials_screen import CredentialsScreen
from .search import SearchCriteria
from .search import resolve_buffer_minutes
from .search import search as search_slots
from .models import ConfirmedBooking, DateRange, Schedule, Slot, SlotMatch, TimeWindow, WeatherPoint
from .scrape_once import _attach_weather, _db_path
from .settings_screen import (
    BUFFER_CHOICES,
    HOUR_CHOICES,
    MIN_OPEN_SPOTS_CHOICES,
    MINUTE_CHOICES,
    SettingsScreen,
)
from .scraper import (
    NoTeeSheetError,
    _holes_from_course_label,
    fetch_available_dates,
    fetch_course_aliases,
    scrape_schedule,
)
from .translated_footer import TranslatedFooter  # noqa: F401 -- re-exported, see that module

# How often the running app rechecks whether anything's due for a background
# re-scrape — matches the cadence scrape_once.py's own docstring recommends for an
# external cron job (every 15-30 min); scrape_once._should_scrape() still decides
# what's actually due each pass, so firing this often doesn't mean hammering the site
# every time. See TeetimeApp._periodic_scrape()'s own docstring.
AUTO_REFRESH_INTERVAL_SECONDS = 15 * 60

# When today's own row drops off the overview entirely -- direct feedback,
# 2026-09-11, refining the very same day's earlier "after sunset" version: "I would
# prefer that the current day disappears from the overview whenever it is after
# 9 pm." A plain fixed clock time now, deliberately, not sunset -- simpler and more
# predictable than a value that shifts with the season and needs a real cached
# schedule with sun_times to even exist yet. See OverviewScreen.load_overview()'s
# own comment for where this is used.
TODAY_HIDDEN_AFTER_HHMM = "21:00"

_TODAY = lambda: date_cls.today().isoformat()  # noqa: E731 — small enough, and patched as a whole in tests
_NOW_HHMM = lambda: datetime.now().strftime("%H:%M")  # noqa: E731 — same reasoning, for _initial_date()


def _version() -> str:
    """The installed package's own version, read from package metadata rather than
    duplicating pyproject.toml's version string a second time here — added
    2026-09-10, direct request: "implement a version display like with
    brew-launcher" (that project shows its own version both via `--version` and
    directly in its running UI's border, at all times, not gated behind a flag; see
    `main()` for the former and `TeetimeApp.__init__`'s `sub_title` for the latter
    here). Falls back to "dev" for a checkout that was never actually
    `pip install`-ed (e.g. running `src/tui.py` directly against a bare clone)
    rather than raising — a missing version shouldn't crash the app over a display
    nicety."""
    try:
        return importlib.metadata.version("teetime-monitor")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def _initial_date(club_id: str, course: str) -> str:
    """Pick today, unless today's own cached schedule shows every slot's time has
    already passed — direct user feedback (2026-09-07, first real end-to-end test):
    opening the app late in the evening and landing on "today," where the course has
    closed and every remaining slot is already history, isn't useful; tomorrow is
    what you'd actually want to look at then. Falls back to today if there's no
    cached schedule to check against yet (a genuinely first-ever open, or one that
    hasn't been scraped since) — nothing lost, since there'd be no data to show for
    either date until 'r' is pressed regardless.

    Originally the date `DayDetailScreen` opened on directly at launch. Now backs
    `OverviewScreen.load_overview()`'s own choice of which row to pre-highlight
    instead, since `OverviewScreen` (added the same day) became what launch actually
    lands on — this function stopped being called at all for a while in between,
    silently regressing the whole feature until a live report the same evening ("why
    is the TUI still showing today at this time (11:12 PM)?") caught it.

    Deliberately reads whatever's already cached (storage.load_latest_schedule())
    rather than triggering a live scrape here — opening the app should stay instant,
    per this module's own docstring, and course hours vary by club/season anyway, so
    the schedule's own last real slot is a better signal than any fixed clock cutoff
    would be."""
    today = _TODAY()
    schedule = storage.load_latest_schedule(course, today, path=_db_path(club_id))
    if schedule is None or not schedule.slots:
        return today
    now = _NOW_HHMM()
    if all(slot.time < now for slot in schedule.slots):
        return (date_cls.fromisoformat(today) + timedelta(days=1)).isoformat()
    return today


def _fill_style(booked: int, capacity: int) -> str:
    """Rich markup style name for a slot's occupancy — colored by fill ratio, per the
    already-agreed mockup design (see the clubhouse-terminal artifact from the design
    session)."""
    if capacity <= 0:
        return "white"
    ratio = booked / capacity
    if ratio >= 1.0:
        return "bold red"
    if ratio >= 0.5:
        return "yellow"
    return "green"


def _dim_if(text: str, condition: bool) -> str:
    """Wrap `text` in Rich's "dim" style when `condition` is true, otherwise leave it
    plain — the shared building block behind `load_schedule()`'s past-slot dimming."""
    return f"[dim]{text}[/]" if condition else text


# Per-tee-time weather column on DayDetailScreen (added 2026-09-08, direct
# feedback: "Yes per tee time indicator" — this was actually part of the original
# Phase 2 plan, "shown per slot in the day-detail table," but only the invisible
# half (conditions_during_round(), used to filter recommendations) ever got built;
# the visible column itself never did, and nothing since had flagged that gap).
# Deliberately plain visual thresholds, independent of the user's own configurable
# avoid_rain_probability_percent/avoid_wind_kph (recommend.py) — "worth noticing at
# a glance," the same spirit as _fill_style() above, not a personal-comfort filter.
_SLOT_RAIN_ICON_THRESHOLD_PERCENT = 50
_SLOT_WIND_ICON_THRESHOLD_KPH = 30


def _column_header(label_key: str, unit_kind: str, units: str) -> str:
    """A table column header with its unit spelled out (2026-09-13, direct
    feedback: "can we integrate units into header" — shipped first as fixed
    "(°C)"/"(km/h)"/"(%/mm)" text; this is what makes the label itself track the
    metric/imperial setting once that became adjustable too, same day, second
    remark: "Can we adjust format (metric/imperial) in settings?"). `unit_kind`
    is one of `units_module.SYMBOLS`'s own keys ("temperature"/"wind"/
    "precipitation").

    The unit sits on its own line below the label (2026-09-15, direct
    feedback: "some of the table headers can wrap up, e.g. units could be in
    a second row" — fitting the whole app on an iPad portrait terminal, ~50
    columns), not appended after a space -- a real column-width win, since a
    column's own width is driven by its *longest single line*, not the sum
    of both (see `_cell_visible_width()`'s own docstring), and the unit
    symbol is always shorter than the label word it sits under. Needs
    `header_height=2` on whichever `DataTable` uses this -- both screens'
    tables set it."""
    symbol = units_module.SYMBOLS.get(units, units_module.SYMBOLS[units_module.METRIC])[unit_kind]
    return f"{i18n.t(label_key)}\n({symbol})"


def _weather_point_for_time(weather_points: list[WeatherPoint], time: str) -> WeatherPoint | None:
    """The hourly forecast point covering one exact slot time — an hourly point's
    own timestamp is the *start* of the hour it covers (a 14:20 slot falls under the
    14:00 point), the same rule `weather.conditions_during_round()` already uses for
    a whole round's worth of points. `None` if `time` is before the first point, or
    there's no weather at all (an unconfigured `location`, or a forecast that
    doesn't reach this far)."""
    covering = [point for point in weather_points if point.time <= time]
    return max(covering, key=lambda point: point.time) if covering else None


def _slot_temperature_cell(weather_points: list[WeatherPoint], time: str, units: str = units_module.DEFAULT_UNITS) -> str:
    """One row's own Temperature column — that hour's forecast temperature, or
    blank with no forecast to show. Split out of the old combined
    `_slot_weather_cell()` 2026-09-09, direct feedback: "can you please split
    weather into Temperature, Precipitation, and wind columns (both in the overview
    and detailed view)?" — see `_slot_precipitation_cell()`'s own docstring for why
    each split column now shows its real number unconditionally, not just when a
    threshold fires. `units` (2026-09-13, "Can we adjust format (metric/imperial)
    in settings?") converts for display only — the stored value, and every other
    caller of this same weather data, stays in °C regardless.

    No "°" suffix here any more (2026-09-13, direct follow-up once the column
    header started spelling out the unit: "since the units are now in the
    headers, we don't need the units in the rows, right?") — the header already
    says "(°C)"/"(°F)", so a bare number reads the same without repeating it on
    every single row."""
    point = _weather_point_for_time(weather_points, time)
    if point is None or point.temperature_c is None:
        return ""
    return f"{units_module.display_temperature(point.temperature_c, units):.0f}"


def _precipitation_amount_text(mm: float, units: str) -> str:
    """A precipitation amount, converted and labelled for display — 1 decimal in
    mm (the existing convention), 2 in inches (a metric mm value under 1 rounds to
    "0.0in" at 1 decimal, losing the number entirely for exactly the light-rain
    case this column exists to show). Shared by the day-level and per-slot
    Precipitation columns so the two can't drift on formatting."""
    amount = units_module.display_precipitation_mm(mm, units)
    decimals = 2 if units == units_module.IMPERIAL else 1
    return f"{amount:.{decimals}f}{units_module.precipitation_amount_label(units)}"


def _slot_precipitation_cell(weather_points: list[WeatherPoint], time: str, units: str = units_module.DEFAULT_UNITS) -> str:
    """One row's own Precipitation column — the real rain probability (and amount,
    once measurable), always shown now that it has its own dedicated column, not
    just once a threshold fires (that threshold — `_SLOT_RAIN_ICON_THRESHOLD_PERCENT`
    — still decides whether the 🌧 icon itself shows, a "worth noticing at a
    glance" flag layered on top of the real number, not a gate on the number
    itself). Blank with no forecast to show. `units` only ever affects the amount
    (mm/in) — the probability is already a unit-agnostic percentage.

    Deliberately keeps its own "%"/"mm"/"in" suffixes even though the column
    header now states the unit too (2026-09-13, unlike `_slot_temperature_cell()`/
    `_slot_wind_cell()`, which dropped theirs the same day) — this is the one
    column packing two different numbers into a single cell ("70%/1.5mm"), so
    the suffixes are doing real, per-cell work distinguishing which number is
    the probability and which is the amount, not just repeating the header."""
    point = _weather_point_for_time(weather_points, time)
    if point is None:
        return ""
    probability = point.precipitation_probability or 0
    mm = f"/{_precipitation_amount_text(point.precipitation_mm, units)}" if point.precipitation_mm else ""
    icon = "🌧 " if probability >= _SLOT_RAIN_ICON_THRESHOLD_PERCENT else ""
    return f"{icon}{probability:.0f}%{mm}"


def _slot_wind_cell(weather_points: list[WeatherPoint], time: str, units: str = units_module.DEFAULT_UNITS) -> str:
    """One row's own Wind column — same "real number always, icon only above the
    threshold" treatment as `_slot_precipitation_cell()`. Blank with no forecast to
    show. The 💨 icon's own threshold (`_SLOT_WIND_ICON_THRESHOLD_KPH`) is always
    checked against the real km/h value, never the display-converted one — it's an
    internal "worth noticing" cutoff, not something a user sets in either unit.

    No "km/h"/"mph" suffix here any more (2026-09-13, same follow-up as
    `_slot_temperature_cell()`'s own docstring) — the column header already
    states it."""
    point = _weather_point_for_time(weather_points, time)
    if point is None or point.wind_speed_kph is None:
        return ""
    icon = "💨 " if point.wind_speed_kph >= _SLOT_WIND_ICON_THRESHOLD_KPH else ""
    speed = units_module.display_wind_speed(point.wind_speed_kph, units)
    return f"{icon}{speed:.0f}"


def _slot_condition_cell(weather_points: list[WeatherPoint], time: str) -> str:
    """One row's own Condition column — that hour's own weather icon (sunny,
    overcast, foggy, snowing, etc.), or blank with no forecast to show. Added
    2026-09-11, direct feedback: "I also would like icons for when it is sunny,
    overcast, foggy, snowing etc." A dedicated column rather than folding the icon
    into an existing one — same "split rather than combine" reasoning
    `_slot_temperature_cell()`'s own docstring documents for Temperature/
    Precipitation/Wind, and it also carries information none of those three do at
    all (clear vs. cloudy vs. foggy vs. snow are never otherwise distinguished).
    No unit conversion involved — a weather code means the same thing regardless
    of the metric/imperial setting."""
    point = _weather_point_for_time(weather_points, time)
    if point is None:
        return ""
    return weather_icons.icon_for_code(point.weather_code)


def _slot_event_cell(slot: Slot) -> str:
    """The day-detail table's own Events column for one slot — `slot.block_reason`
    if this slot is blocked (event, lesson, guest reservation, or an advance-booking
    notice — see scraper.py's module docstring for why `block_reason` doesn't
    distinguish which kind at the per-slot level; unlike the overview's own day-level
    Events column, this one intentionally doesn't filter those out, since "why can't
    I book this specific time" is exactly the question a per-slot column should
    answer), a translated placeholder for a genuinely blank reason (a real, confirmed
    case — see `load_schedule()`'s own note), or blank for a normal open/occupied
    slot. Split out of the old Occupancy-column overload 2026-09-09, direct
    feedback: "I would prefer if detailed view had a separate events column." The
    📋 icon (added the same day, alongside the overview's own legend) matches the
    overview's own Events column exactly — same meaning, same symbol, on both
    screens."""
    if slot.block_reason is None:
        return ""
    return f"📋 {slot.block_reason or i18n.t('table.not_bookable')}"


def _favorite_clubs() -> list[tuple[str, str]]:
    """(club_id, display_name) for every saved favorite -- shared by
    `ClubBrowserScreen._favorites()` and `OverviewScreen`'s own inline club selector
    (added 2026-09-09, direct feedback: "would it be possible to integrate club and
    course selectors into the overview screen... this would make navigation much
    quicker") -- pulled out here so both can read it without one instantiating the
    other's screen.

    `config.get("name")` -- the club's real display name, if it was ever actually
    known (via a directory search) and so persisted by
    club_config.new_club_stub() (2026-09-08). Real bug found live: this used to hand
    back `slug` here unconditionally -- close enough to read at a glance, but a
    confirmed dead end for geocode.find_club_location() (which this same value feeds
    into on an un/re-favorite from ClubBrowserScreen's own list), and this project's
    own no-op geocoding tests for a "typed-in id, no known name" club would have
    caught it immediately had the slug not looked so plausibly name-shaped. Falls
    back to `slug` only for a favorite saved before this fix existed."""
    entries = []
    for slug in club_config.list_clubs():
        config = club_config.load_club_config(slug)
        club_id = config.get("club_id")
        if club_id:
            entries.append((str(club_id), config.get("name") or slug))
    return entries


def _any_favorite_club_id() -> str | None:
    """A real club_id to test a login attempt against, if any favorite exists --
    added 2026-09-10 alongside CredentialsScreen's own live-verification feature
    (see that module's docstring). Any favorited club works: one pc caddie login is
    platform-wide, so this doesn't need to be the *same* club the credentials will
    later be used for."""
    favorites = _favorite_clubs()
    return favorites[0][0] if favorites else None


class ClubBrowserScreen(Screen[str | None]):
    """Pick any club on the platform, by numeric pc caddie id. The app's home screen.

    Replaces the old "pick one of your saved clubs" flow (2026-09-07, direct feedback):
    having to save a club to `clubs/*.yaml` before you could even look at it was
    backwards — launching should just let you choose a club and a course, and saving one
    should only mean "favorite". Four ways in, so a missing directory cache or missing
    credentials is never a dead end (see club_directory.py's module docstring):

    - An empty search box lists your favorites, which need no directory and no login.
    - Typing searches the cached club directory, once it's been fetched — or, before
      that's ever happened, the bundled reference snapshot instead (2026-09-10, see
      club_directory.py's own "#4" note: a first search shouldn't require a login
      just to exist at all).
    - Typing a club id (e.g. "0000001"), or pasting a club's own pc caddie booking
      link (2026-09-10), offers that club directly — no cache, no login, because tee
      sheets are public. This is also what lets a brand-new install reach a club
      before any credentials exist, the bootstrapping gap the old picker couldn't
      close.

    Dismisses with the chosen club's numeric id, or `None` if backed out. `f` toggles
    whether the highlighted club is a favorite; `r` refreshes the directory cache
    (the one action here that does need a login). Opening the highlighted club is
    plain `enter` — Textual's own built-in `OptionList`/`Input` behavior, not a
    binding this screen declares itself (see `on_input_submitted()` and
    `on_option_list_option_selected()` below) — which is exactly why it never showed
    up in the footer on its own; added explicitly to `_FOOTER_BINDINGS` below after
    direct feedback that nothing on screen actually said to press it.

    `l` opens `CredentialsScreen` right here, in this same running session — added
    2026-09-09, direct feedback: "I want login setup within the tui directly when
    you run it." Before this, `r` without credentials configured just printed a
    status line telling you to go run `python -m src.credentials_screen` as a
    separate program — `CredentialsScreen` itself has existed since 2026-09-07 (its
    own docstring even flagged "not yet reachable from a live user complaint since
    it isn't currently pushed from the running main app"), just never actually
    wired into this screen, the one every fresh install actually lands on. `r` now
    pushes it automatically the same moment it discovers no credentials exist,
    instead of only describing the fix; `l` is the same screen reached proactively,
    for a first run before ever trying `r` at all. Either way, a save retries the
    directory fetch automatically (`_on_credentials_screen_dismissed()`)."""

    CSS = """
    #club-search { margin: 0 2; }
    #club-results { height: 1fr; margin: 0 2; }
    #club-status { padding: 0 2; color: $text-muted; }
    """

    # Ordered enter (the primary action) first, this screen's own actions next, then
    # escape/quit last -- matching every other screen's convention (see
    # OverviewScreen/DayDetailScreen) rather than putting "Back" ahead of actions
    # that are used far more often. Direct feedback (2026-09-08): "please check
    # whether the order of menu elements or keybinds displayed at the bottom of the
    # window is logical" -- escape used to sit right after enter, ahead of Favorite
    # and Refresh, even though this screen is usually the app's home screen (opened
    # with allow_cancel=False, so escape often does nothing at all here).
    BINDINGS = [
        ("f", "toggle_favorite", "Favorite"),
        ("r", "refresh_directory", "Refresh list"),
        ("l", "login", "Login"),
        ("escape", "cancel", "Back"),
        ("q", "quit", "Quit"),
    ]
    _FOOTER_BINDINGS = [
        ("enter", "binding.open"),
        ("f", "binding.favorite"),
        ("r", "binding.refresh_directory"),
        ("l", "binding.login"),
        ("escape", "binding.cancel"),
        ("q", "binding.quit"),
    ]

    def __init__(self, allow_cancel: bool = True, initial_status: str = "") -> None:
        super().__init__()
        self.allow_cancel = allow_cancel
        self.initial_status = initial_status
        self._directory: list[tuple[str, str]] = []
        # Whether `self._directory` is currently the bundled reference snapshot
        # (club_directory.load_seed_directory()) rather than a real, live-fetched
        # cache -- see that function's own docstring. Only ever used to pick which
        # status hint to show; search/open/favorite all treat both sources
        # identically.
        self._directory_is_seed = False
        self._names: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(i18n.t("picker.club_title"))
        yield Input(placeholder=i18n.t("picker.club_search_placeholder"), id="club-search")
        yield OptionList(id="club-results")
        yield Static("", id="club-status")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_mount(self) -> None:
        self._directory = club_directory.load_cached_directory()
        if not self._directory:
            # No real fetch has ever happened on this install -- fall back to the
            # bundled reference snapshot (2026-09-10, see club_directory.py's own
            # module docstring "#4" note) so name search works immediately, with no
            # login or known club id needed at all. A real `r` refresh always
            # replaces this the moment one succeeds (see action_refresh_directory()).
            self._directory = club_directory.load_seed_directory()
            self._directory_is_seed = bool(self._directory)
        self._show_favorites()
        if self.initial_status:
            self.query_one("#club-status", Static).update(self.initial_status)

    # -- listing -----------------------------------------------------------------

    def _favorites(self) -> list[tuple[str, str]]:
        return _favorite_clubs()

    def _show_entries(
        self, entries: list[tuple[str, str]], status: str, store_names: bool = True
    ) -> None:
        # Not named `_render`: that's an existing method on Textual's own Widget,
        # and overriding it with a different signature breaks rendering outright --
        # the third such collision in this file (see `_auto_refresh` and
        # `_pending_message` above). Prefix private helpers distinctively here.
        results = self.query_one("#club-results", OptionList)
        results.clear_options()
        self._names = dict(entries) if store_names else {}
        for club_id, name in entries:
            star = "★ " if club_config.is_favorite(club_id) else "  "
            results.add_option(Option(f"{star}[{club_id}] {name}", id=club_id))
        self.query_one("#club-status", Static).update(status)

    def _show_favorites(self) -> None:
        favorites = self._favorites()
        if favorites:
            self._show_entries(favorites, i18n.t("picker.favorites_hint", count=len(self._directory)))
        elif self._directory_is_seed:
            # Distinct from the plain no_favorites_hint below -- there genuinely is
            # a directory to search already (the bundled snapshot), so this says so
            # instead of implying nothing exists to search yet.
            self._show_entries([], i18n.t("picker.no_favorites_hint_with_seed", count=len(self._directory)))
        else:
            self._show_entries([], i18n.t("picker.no_favorites_hint"))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "club-search":
            return
        query = event.value.strip()
        if not query:
            self._show_favorites()
            return
        # A typed club id wins over a name search -- it's unambiguous, and it's the one
        # path that works with no directory cache at all.
        club_id = club_directory.looks_like_club_id(query)
        if club_id is not None:
            # store_names=False: "open this club" is a prompt, not the club's name —
            # without this it ended up as the tee sheet's own title (caught live).
            self._show_entries(
                [(club_id, i18n.t("picker.open_by_id"))],
                i18n.t("picker.enter_to_open"),
                store_names=False,
            )
            return
        matches = club_directory.search(self._directory, query)
        if matches:
            self._show_entries(matches, i18n.t("picker.match_count", count=len(matches)))
        elif self._directory:
            self._show_entries([], i18n.t("club_picker.no_matches"))
        else:
            self._show_entries([], i18n.t("picker.no_directory_yet"))

    # -- actions -----------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the search box opens the first (or highlighted) result.

        Without this, typing a club id showed the right single result but Enter did
        nothing: focus stays in the Input, so neither Enter nor the arrow keys reach
        the OptionList, and the screen looked broken at exactly the moment it was
        working. Caught in a live run, not by the tests — which drive the list
        directly and so never exercised the keyboard path a person actually uses."""
        if event.input.id != "club-search":
            return
        results = self.query_one("#club-results", OptionList)
        if results.option_count == 0:
            return
        index = results.highlighted if results.highlighted is not None else 0
        self._choose(results.get_option_at_index(index).id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._choose(event.option.id)

    def _choose(self, club_id: str) -> None:
        # Hand the club's display name up to the app, so the tee sheet can show it —
        # a club reached from the directory has no saved slug to title itself with.
        name = self._names.get(club_id, "")
        if name and hasattr(self.app, "_club_names"):
            self.app._club_names[club_id] = name
        self.dismiss(club_id)

    def _highlighted_club_id(self) -> str | None:
        """The club `f` should act on. Falls back to the first result when nothing is
        explicitly highlighted — with focus still in the search box (the normal case
        right after typing) Textual highlights nothing, and without this fallback `f`
        silently did nothing at exactly the moment the one obvious target was on
        screen. Same reasoning as `on_input_submitted()`."""
        results = self.query_one("#club-results", OptionList)
        if results.option_count == 0:
            return None
        index = results.highlighted if results.highlighted is not None else 0
        try:
            return results.get_option_at_index(index).id
        except Exception:  # noqa: BLE001 -- a stale index just means "nothing picked"
            return None

    def action_toggle_favorite(self) -> None:
        club_id = self._highlighted_club_id()
        if club_id is None:
            return
        status = self.query_one("#club-status", Static)
        if club_config.is_favorite(club_id):
            club_config.remove_favorite(club_id)
            status.update(i18n.t("picker.unfavorited", club_id=club_id))
        else:
            club_config.add_favorite(club_id, self._names.get(club_id, ""))
            status.update(i18n.t("picker.favorited", club_id=club_id))
        # Re-render so the ★ updates, keeping whatever list is currently shown.
        query = self.query_one("#club-search", Input).value.strip()
        if query:
            self.on_input_changed(Input.Changed(self.query_one("#club-search", Input), query))
        else:
            self._show_favorites()

    def action_refresh_directory(self) -> None:
        """Re-fetch the platform club list. The only action on this screen that needs a
        login — everything else here works without one (see club_directory.py).

        Pushes `CredentialsScreen` right here the moment it discovers none are
        configured, rather than just describing the fix in a status line — see this
        class's own docstring for the direct feedback this responds to.

        `any_credentials() is None` has two genuinely different causes, told apart
        here since 2026-09-10 (direct report: "why can't I login... why do I need to
        hit r after login") -- no credentials saved at all (push CredentialsScreen,
        same as before), versus credentials that are already saved and working but
        have no favorited club yet to pair with for an authenticated request
        (`club_directory.credentials_configured()` is True either way it's checked
        directly, not inferred from `any_credentials()`'s own None). Pushing
        CredentialsScreen again for the second case would be actively misleading --
        implying the login itself is missing or wrong when it isn't.

        Real follow-up gap, same day, direct pushback ("it is a chicken-and-egg
        problem"): the "needs a club" message originally said to *favorite* a club
        first -- but favoriting was never actually required, just knowing a real
        club_id to authenticate against, which the search box above already has the
        moment a club id is typed into it, whether or not it's ever favorited (one
        pc caddie login is platform-wide -- it doesn't have to be *your* club, or a
        saved one, just a real id). Now tries whatever's currently typed in
        `#club-search` before falling back to a favorite, so typing your own club's
        id and pressing 'r' works immediately, no separate favorite-first step."""
        status = self.query_one("#club-status", Static)
        credentials = club_directory.any_credentials()
        if credentials is not None:
            club_id, username, password = credentials
        else:
            typed_club_id = club_directory.looks_like_club_id(
                self.query_one("#club-search", Input).value.strip()
            )
            if typed_club_id is not None and club_directory.credentials_configured():
                club_id = typed_club_id
                username, password = club_config.resolve_credentials(typed_club_id)
            else:
                club_id = username = password = None
        if not club_id or not username or not password:
            if club_directory.credentials_configured():
                status.update(i18n.t("picker.directory_needs_a_club"))
                return
            status.update(i18n.t("picker.directory_needs_login"))
            self.app.push_screen(
                CredentialsScreen(verify_against_club_id=self._verification_club_id()),
                self._on_credentials_screen_dismissed,
            )
            return
        status.update(i18n.t("club_picker.fetching"))
        try:
            self._directory = club_directory.refresh_directory(club_id, username, password)
        except Exception as exc:  # noqa: BLE001 -- a live fetch can genuinely fail
            status.update(i18n.t("club_picker.fetch_failed", error=exc))
            return
        self._directory_is_seed = False  # a real fetch always wins over the bundled seed
        status.update(i18n.t("picker.directory_refreshed", count=len(self._directory)))

    def _verification_club_id(self) -> str | None:
        """A real club_id to test a saved login against -- whatever's currently typed
        in `#club-search` if it looks like one (no favorite needed, see
        `action_refresh_directory()`'s own docstring for why that was never actually
        a requirement), else any favorited club's id, else None."""
        typed = club_directory.looks_like_club_id(self.query_one("#club-search", Input).value.strip())
        return typed if typed is not None else _any_favorite_club_id()

    def action_login(self) -> None:
        """`CredentialsScreen`, reached proactively -- e.g. right after a fresh
        install, before ever trying `r` and hitting the reactive push in
        `action_refresh_directory()` above. Same screen, same dismiss handling.
        `verify_against_club_id` (2026-09-10) lets a save show real "login
        verified"/"login rejected" feedback instead of just "Saved" whenever a real
        club_id is already known to test against -- see credentials_screen.py's own
        docstring for why it's optional."""
        self.app.push_screen(
            CredentialsScreen(verify_against_club_id=self._verification_club_id()),
            self._on_credentials_screen_dismissed,
        )

    def _on_credentials_screen_dismissed(self, saved: bool) -> None:
        # "Retry automatically" convention -- a save is exactly the signal that
        # whatever needed a login (here, always the directory fetch) is worth
        # attempting again right away, not making the user press 'r' a second time
        # themselves.
        if saved:
            self.action_refresh_directory()

    def action_cancel(self) -> None:
        if self.allow_cancel:
            self.dismiss(None)

    def action_quit(self) -> None:
        self.app.exit()


class CoursePickerScreen(Screen[str | None]):
    """Pick a course — only shown when the club has no valid `default_course` set and
    more than one course exists. The options themselves come from this specific
    club's own `fetch_course_aliases()` (not a rotating list, but not universal
    across clubs either — see scraper.py's module docstring for why a second real
    club needed this fixed 2026-09-07). Same `escape`/`q` bindings as
    `ClubBrowserScreen` — see that class's own docstring, including why `enter` is
    listed in `_FOOTER_BINDINGS` despite not being a real `BINDINGS` entry here
    either."""

    BINDINGS = [("escape", "cancel", "Back"), ("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("enter", "binding.open"), ("escape", "binding.cancel"), ("q", "binding.quit")]

    def __init__(self, courses: list[str]) -> None:
        super().__init__()
        self.courses = courses

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(i18n.t("picker.course_title"))
        yield OptionList(*[Option(course, id=course) for course in self.courses])
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_quit(self) -> None:
        self.app.exit()


class ConfirmBookingScreen(Screen[bool]):
    """Manual confirm-your-tee-time form — the fallback for the same-day-booking timing
    gap (ROADMAP.md Phase 1), not the primary source (scrape_my_reservations() is,
    once the login form exists).

    `default_time`/`default_holes` (added 2026-09-07, direct feedback: "I already
    selected a specific time, and the TUI should know on which course I'm currently
    focused" — why was this ever re-typed by hand?) pre-fill both fields as real
    values, not just placeholder hints: `DayDetailScreen.action_confirm()` reads the
    currently highlighted row's own time off the table, and holes come from the
    course itself (`_holes_from_course_label()` — the same derivation
    scraper.py's own reservation parsing already uses, since a course category like
    "18 Loch Tee 1" only ever means one hole count). Both stay editable — pre-filled,
    not forced — for the rare case either guess is wrong.

    Found genuinely missed, dedicated bug hunt (2026-09-10): every other screen in
    this app was carefully audited for `escape` back / `q` quit consistency and a
    translated footer — this one never was. Had no `BINDINGS` at all (`escape` did
    nothing, `q` either typed into a focused `Input` or did nothing) and yielded a
    plain `Footer()` instead of `TranslatedFooter`, silently English-only regardless
    of the app's own language setting. `escape` now dismisses the same as clicking
    Cancel (`dismiss(False)`, no save)."""

    BINDINGS = [("escape", "cancel", "Back"), ("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("escape", "binding.cancel"), ("q", "binding.quit")]

    def __init__(
        self,
        club_id: str,
        course: str,
        date: str,
        default_time: str | None = None,
        default_holes: int | None = None,
    ) -> None:
        super().__init__()
        self.club_id = club_id
        self.course = course
        self.date = date
        self.default_time = default_time
        self.default_holes = default_holes

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="confirm-form"):
            yield Label(i18n.t("confirm.title", date=self.date))
            yield Label(i18n.t("confirm.time_label"))
            yield Input(value=self.default_time or "", placeholder="14:00", id="time")
            yield Label(i18n.t("confirm.holes_label"))
            yield Input(
                value=str(self.default_holes) if self.default_holes else "",
                placeholder="18",
                id="holes",
            )
            yield Static("", id="confirm-status")
            with Horizontal():
                yield Button(i18n.t("button.save"), id="save", variant="success")
                yield Button(i18n.t("button.cancel"), id="cancel")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_quit(self) -> None:
        self.app.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
            return

        time = self.query_one("#time", Input).value.strip()
        holes_text = self.query_one("#holes", Input).value.strip()
        if not time:
            self.query_one("#confirm-status", Static).update(i18n.t("confirm.enter_time"))
            return
        try:
            holes = int(holes_text) if holes_text else None
        except ValueError:
            self.query_one("#confirm-status", Static).update(i18n.t("confirm.holes_number"))
            return

        booking = ConfirmedBooking(
            date=self.date,
            course=self.course,
            time=time,
            holes=holes,
            source="manual",
            confirmed_at=datetime.now(timezone.utc).isoformat(),
        )
        storage.save_confirmed_booking(booking, path=_db_path(self.club_id))
        self.dismiss(True)


class CancelBookingScreen(Screen[bool]):
    """A small yes/no confirmation for cancelling your confirmed tee time
    (2026-09-13, direct question: "why can you confirm tee time within the TUI,
    but cannot cancel or modify?"). `DayDetailScreen.action_confirm()` opens this
    instead of a fresh `ConfirmBookingScreen` when `c` is pressed on the row
    that's already your confirmed booking — re-confirming the exact same
    date/course/time again wouldn't do anything useful, but offering to cancel
    it does.

    Same "we only track what already happened, we never book or cancel
    anything ourselves" boundary `ConfirmBookingScreen`'s own docstring already
    draws — this never touches pc caddie, only teetime-monitor's own local
    record. Writes a `time=None` row (`source="manual"`, mirroring the existing
    "manual" `c`-confirm) — the same "confirmed not playing that day" sentinel
    `_reconcile_cancelled_reservations()` introduced for the automatic case one
    version ago; already fully handled everywhere a confirmed booking gets read
    back (see that function's own docstring).

    Deliberately does NOT reuse `button.cancel`'s own text for either button —
    "Cancel" already means "back out, don't do this" everywhere else in this
    app, which here would sit right next to a screen whose entire subject is
    itself "cancel the booking." Using that same word for "keep the booking"
    risks exactly the wrong click on a genuinely consequential action, so both
    buttons spell out what they actually do instead."""

    BINDINGS = [("escape", "cancel", "Back"), ("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("escape", "binding.cancel"), ("q", "binding.quit")]

    def __init__(self, club_id: str, course: str, date: str, time: str) -> None:
        super().__init__()
        self.club_id = club_id
        self.course = course
        self.date = date
        self.time = time

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="confirm-form"):
            yield Label(i18n.t("cancel_booking.title", date=self.date, time=self.time))
            yield Static("", id="confirm-status")
            with Horizontal():
                yield Button(i18n.t("cancel_booking.confirm"), id="confirm-cancel", variant="error")
                yield Button(i18n.t("cancel_booking.keep"), id="keep")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_quit(self) -> None:
        self.app.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "keep":
            self.dismiss(False)
            return
        booking = ConfirmedBooking(
            date=self.date,
            course=self.course,
            time=None,
            holes=None,
            source="manual",
            confirmed_at=datetime.now(timezone.utc).isoformat(),
        )
        storage.save_confirmed_booking(booking, path=_db_path(self.club_id))
        self.dismiss(True)


# --- OverviewScreen (ROADMAP.md Phase 4) -- the multi-day home screen, added
# 2026-09-07 once the clubhouse-overview mockup's design questions were resolved.
# Pure helper functions first (heat-strip coloring, weather/tag text, the shared
# availability pipeline), then the screen itself. -------------------------------------

_HEAT_STRIP_WINDOWS = [
    ("08:00", "10:00"),
    ("10:00", "12:00"),
    ("12:00", "14:00"),
    ("14:00", "16:00"),
    ("16:00", "18:00"),
    ("18:00", "20:00"),
]

# Same three fill-ratio thresholds as _fill_style() above, just averaged across
# however many real (non-block_reason) slots fall in each 2-hour window instead of
# judging one slot at a time.
_HEAT_BLOCK_STYLES = {"open": "green", "mid": "yellow", "full": "bold red", "blocked": "dim"}

# A day counts as "rain all day" for the overview's tag line when every daytime
# forecast point is at least this likely to rain — a display heuristic, deliberately
# separate from a club's own configured avoid_rain_probability_percent (recommend.py),
# which governs the hard exclude_unplayable() filter, not this summary line.
_RAIN_ALL_DAY_THRESHOLD_PERCENT = 70


def _heat_strip_blocks(schedule: Schedule) -> list[str]:
    """One "open"/"mid"/"full"/"blocked" class per 2-hour window across the day
    (08:00-20:00). A window with no real slot in it at all (before opening, after
    closing, or every slot in it is block_reason'd — an event/lesson/advance-booking
    notice, not real occupancy) reports "blocked" rather than an average that would
    be meaningless or misleading."""
    blocks = []
    for start, end in _HEAT_STRIP_WINDOWS:
        real = [s for s in schedule.slots if start <= s.time < end and s.block_reason is None]
        capacity = sum(s.capacity for s in real)
        if not real or capacity <= 0:
            blocks.append("blocked")
            continue
        ratio = sum(s.booked for s in real) / capacity
        if ratio >= 1.0:
            blocks.append("full")
        elif ratio >= 0.5:
            blocks.append("mid")
        else:
            blocks.append("open")
    return blocks


def _heat_strip_markup(schedule: Schedule) -> str:
    return "".join(f"[{_HEAT_BLOCK_STYLES[block]}]■[/]" for block in _heat_strip_blocks(schedule))


def _is_rain_all_day(weather: list) -> bool:
    daytime = [w for w in weather if "08:00" <= w.time < "20:00"]
    if not daytime:
        return False
    return all((w.precipitation_probability or 0) >= _RAIN_ALL_DAY_THRESHOLD_PERCENT for w in daytime)


def _temperature_cell(weather: list[WeatherPoint], units: str = units_module.DEFAULT_UNITS) -> str:
    """The overview's own Temperature column for one day — daytime (08:00-20:00)
    high/low, e.g. "24/14", or blank with no forecast to show (a schedule that
    was never weather-attached — e.g. `location` not configured yet). Split out of
    the old combined Weather column 2026-09-09, direct feedback: "can you please
    split weather into Temperature, Precipitation, and wind columns (both in the
    overview and detailed view)?" — see `_precipitation_cell()`'s own docstring for
    the rest of that split. `units` (2026-09-13) converts for display only, same as
    `_slot_temperature_cell()`'s own. No "°" suffix any more (2026-09-13, same
    follow-up as that function's own docstring) — the column header already
    states the unit."""
    daytime = [w for w in weather if "08:00" <= w.time < "20:00"]
    temps = [w.temperature_c for w in daytime if w.temperature_c is not None]
    if not temps:
        return ""
    high = units_module.display_temperature(max(temps), units)
    low = units_module.display_temperature(min(temps), units)
    return f"{high:.0f}/{low:.0f}"


def _precipitation_cell(weather: list[WeatherPoint], units: str = units_module.DEFAULT_UNITS) -> str:
    """The overview's own Precipitation column for one day — "rain all day" when
    every daytime point crosses `_RAIN_ALL_DAY_THRESHOLD_PERCENT` (still worth its
    own phrase rather than an average, the same reasoning `_is_rain_all_day()`
    already had), otherwise the average rain chance across daytime (and total mm,
    once measurable) — always shown now that this has its own column, not gated
    behind a threshold the way the combined cell used to be. The 🌧 icon itself is
    still gated on `_SLOT_RAIN_ICON_THRESHOLD_PERCENT` — a "worth noticing at a
    glance" flag layered on top of the real number, not a replacement for it. Blank
    with no daytime forecast at all.

    Deliberately keeps its own "%"/"mm"/"in" suffixes despite the column header
    also stating the unit now (2026-09-13) — same reasoning as
    `_slot_precipitation_cell()`'s own docstring: this cell packs two different
    numbers together, so the suffixes distinguish which one is which, not just
    repeat the header."""
    daytime = [w for w in weather if "08:00" <= w.time < "20:00"]
    if not daytime:
        return ""
    if _is_rain_all_day(weather):
        return f"🌧 {i18n.t('overview.rain_all_day')}"
    avg_chance = sum((w.precipitation_probability or 0) for w in daytime) / len(daytime)
    total_mm = sum((w.precipitation_mm or 0) for w in daytime)
    mm_part = f"/{_precipitation_amount_text(total_mm, units)}" if total_mm else ""
    icon = "🌧 " if avg_chance >= _SLOT_RAIN_ICON_THRESHOLD_PERCENT else ""
    return f"{icon}{avg_chance:.0f}%{mm_part}"


def _wind_cell(weather: list[WeatherPoint], units: str = units_module.DEFAULT_UNITS) -> str:
    """The overview's own Wind column for one day — the day's peak daytime wind
    speed (max, not average — the same "worst case across the window" reasoning
    `weather.conditions_during_round()` already applies to a single round), shown
    unconditionally now that this has its own column; the 💨 icon is still gated on
    `_SLOT_WIND_ICON_THRESHOLD_KPH` (the real km/h value, not the display-converted
    one — same reasoning as `_slot_wind_cell()`'s own). Blank with no daytime
    forecast at all. No "km/h"/"mph" suffix any more (2026-09-13, same follow-up
    as `_slot_wind_cell()`'s own docstring) — the column header already states
    the unit."""
    daytime = [w for w in weather if "08:00" <= w.time < "20:00"]
    winds = [w.wind_speed_kph for w in daytime if w.wind_speed_kph is not None]
    if not winds:
        return ""
    peak = max(winds)
    icon = "💨 " if peak >= _SLOT_WIND_ICON_THRESHOLD_KPH else ""
    speed = units_module.display_wind_speed(peak, units)
    return f"{icon}{speed:.0f}"


def _condition_cell(weather: list[WeatherPoint]) -> str:
    """The overview's own Condition column for one day — the single most severe
    condition among the daytime (08:00-20:00) forecast (see
    `weather_icons.worst_icon()`), the same "worst across the window, not an
    average" reasoning `_wind_cell()`'s own daily peak already uses: a day that's
    sunny all morning and thunderstorms in the afternoon is a thunderstorm day, not
    a "mostly sunny" one. Blank with no daytime forecast at all. Added 2026-09-11,
    direct feedback: "I also would like icons for when it is sunny, overcast,
    foggy, snowing etc." — see `_slot_condition_cell()`'s own docstring for why
    this is its own column."""
    daytime = [w for w in weather if "08:00" <= w.time < "20:00"]
    if not daytime:
        return ""
    return weather_icons.worst_icon([w.weather_code for w in daytime])


def _event_cell(schedule: Schedule) -> str:
    """The overview's own Events column for one day — split out of the old combined
    Weather column (2026-09-09, direct feedback: "It shouldn't mix up events with
    weather data"). `schedule.events` names come straight from the scraped
    block-reason label (see `scraper._event_names()`) — untranslated, same as every
    other block_reason text in this app, since it's the club's own text, not this
    app's UI chrome. Empty string with nothing to show, same as
    `_temperature_cell()`/`_precipitation_cell()`/`_wind_cell()`.

    The icon (📋, not 🏆) is deliberately generic: `events` is genuinely just "the
    club published a reason a slot isn't normally bookable today," which is very
    often a real tournament ("AK 50 Herren") but just as often a routine ladies'/
    members' day or a maintenance closure — nothing in the scraped data actually
    distinguishes a competitive event from a routine one (see ROADMAP.md's "Known
    risks" — no separate tournament-calendar source is implemented), so a trophy
    specifically claiming "competition" would overclaim what this app can actually
    tell. Changed from 📌 to 📋 2026-09-09 (see `LEGEND_*` below) — 📌 was already
    doing double duty for confirmed bookings in the Pick column (`_day_pick_text()`),
    which a legend listing icon meanings would have had to show twice with two
    different meanings."""
    if schedule.events:
        return f"📋 {schedule.events[0]}"
    return ""


def _location_for_club(club_id: str, club_name: str) -> dict | None:
    """A club's {"lat", "lon"}, independent of whether it's ever been favorited
    (2026-09-08, direct feedback: "I don't want to first save a club in order to see
    weather forecast" — location used to only ever get looked up when a club was
    saved, via club_config.new_club_stub_with_location(), so a club visited without
    saving it (an ordinary state since the 2026-09-07 favorites rework — see
    _open_club()) never got one at all, no matter how long you kept it open. Cached
    in the club's own per-club db (storage.save_location/load_location) instead of
    clubs/*.yaml, since that db already exists the moment a club is scraped,
    regardless of favorite status — geocoded at most once per club, same one-time-
    lookup rule new_club_stub_with_location() already follows, just keyed by the
    club's db file instead of a saved config file."""
    path = _db_path(club_id)
    cached = storage.load_location(path=path)
    if cached is not None:
        return cached
    if not club_name:
        return None
    location = geocode.find_club_location(club_name)
    if location is None:
        return None
    lat, lon = location
    found = {"lat": lat, "lon": lon}
    storage.save_location(found, path=path)
    return found


def _resolved_config(club_slug: str | None, club_id: str | None = None, club_name: str = "") -> dict:
    """This club's own settings (`location`, `overview_days`, `default_course`,
    `identity` — genuinely per-club facts), with your global `availability`/
    `preferences`/`ai_assist`/`round_duration_minutes`/scrape-interval settings
    shallow-merged on top (added 2026-09-08, direct feedback: "i also want the
    settings/preferences to be global and not tied to a specific club" — those aren't
    per-club facts at all, so they overlay every club's own config rather than being
    duplicated into each one). `club_slug is None` (a club being visited without
    saving it) contributes nothing per-club from clubs/*.yaml, but still gets your
    global settings — recommendations now work even on a club you haven't favorited,
    which the old per-club-only design couldn't offer since there was nowhere for an
    unsaved club to have availability rules at all.

    `club_id`/`club_name` (added 2026-09-08, same feedback as `_location_for_club()`)
    fill in `location` from that club's own per-club db when clubs/*.yaml has none —
    whether because the club was never saved at all, or because it was saved before a
    location could be found. Both default to falsy so every existing caller that
    doesn't pass them keeps behaving exactly as before."""
    club_settings = {}
    if club_slug is not None:
        try:
            club_settings = club_config.load_club_config(club_slug)
        except FileNotFoundError:
            club_settings = {}
    if "location" not in club_settings and club_id is not None:
        location = _location_for_club(club_id, club_name)
        if location is not None:
            club_settings = {**club_settings, "location": location}
    return {**club_settings, **global_preferences.load_preferences()}


def _crowd_estimates(schedules: list[Schedule], config: dict, club_id: str) -> dict[tuple[str, str, str], float]:
    """{(date, course, time): predicted occupancy 0-1} for every slot across
    `schedules` — entirely skipped (empty dict, no analytics/DB work at all) unless
    `ai_assist.avoid_predicted_crowd` is actually on, since nothing downstream does
    anything with it otherwise. Added 2026-09-10, direct follow-up to finding
    `avoid_predicted_crowd` had zero real effect despite reaching Claude's own
    prompt verbatim: "make avoid crowds a child of AI option" — moving where it
    lives in Settings only fixes the framing, not the underlying gap, so this is
    the actual data behind it.

    One `analytics.crowd_heatmap()` per distinct course across `schedules` (a real,
    if modest, SQLite scan — cheap enough at this app's actual scale not to bother
    caching across calls; every caller here only reaches this at all once
    `ai_assist.enabled` is already on too, meaning a per-day paid API call is
    already happening regardless). `calendar_context.classify_day()` picks the same
    weekday-or-special-type key `HeatmapScreen`'s own table uses — see that
    screen's docstring, and `analytics.crowd_heatmap()`'s, for why day-of-week
    (not a coarse workday/weekend split) is what the underlying data is actually
    keyed by."""
    ai_config = config.get("ai_assist", {})
    if not ai_config.get("avoid_predicted_crowd", False):
        return {}
    holidays = _holidays_for_club(config)
    vacation_ranges = _vacation_ranges_for_club(config)
    heatmaps: dict[str, dict] = {}
    estimates: dict[tuple[str, str, str], float] = {}
    for schedule in schedules:
        if schedule.course not in heatmaps:
            heatmaps[schedule.course] = analytics.crowd_heatmap(
                schedule.course, holidays, vacation_ranges, path=_db_path(club_id)
            )
        heatmap = heatmaps[schedule.course]
        day_type = calendar_context.classify_day(
            schedule.date, holidays, vacation_ranges, has_tournament=bool(schedule.events)
        )
        key = (
            day_type
            if day_type in calendar_context.SPECIAL_DAY_TYPES
            else date_cls.fromisoformat(schedule.date).strftime("%A")
        )
        for slot in schedule.slots:
            estimate = analytics.predict_crowding(key, slot.time, heatmap)
            if estimate is not None:
                estimates[(schedule.date, schedule.course, slot.time)] = estimate
    return estimates


def _availability_pipeline(schedule: Schedule, config: dict, club_id: str) -> tuple[list, list]:
    """(deterministic candidates, still-playable matches) for one schedule against
    your global `availability` rules (see `_resolved_config()`) — factored out so both
    the per-day pick column below and `DayDetailScreen`'s own ★ marker derive from one
    place. `([], [])` with no `availability` configured at all — nothing to check
    against, not an error.

    `playable` goes through `recommend.ranked_matches()` (not a bare
    `exclude_unplayable()`, as this used to call directly) — the exact same pipeline
    `weekly_picks()` uses, so "the best slot for one day" can never disagree with "the
    best slots for the week" about what counts as best. With `ai_assist.enabled`
    false (the default), `ranked_matches()` returns exactly what `exclude_unplayable()`
    alone would have — same items, same order — so this is a behavior-preserving
    change until AI ranking is actually turned on; only then does `playable`'s order
    start reflecting genuine judgment instead of plain chronological order. Direct
    feedback this responds to (2026-09-08): "why does it always recommend 16:00 on
    any other day?" — `_day_pick_text()` used to take the literal earliest playable
    time, which is exactly 16:00 every day once a saved window starts at 16:00 and
    that slot happens to be open, regardless of how good the rest of the window is."""
    if not config.get("availability"):
        return [], []
    criteria = recommend.default_criteria_from_config(config)
    candidates = search_slots([schedule], criteria)
    crowd_estimates = _crowd_estimates([schedule], config, club_id)
    playable = recommend.ranked_matches([schedule], criteria, config, crowd_estimates)
    return candidates, playable


def _too_late_for_daylight(slot_time: str, schedule: Schedule, config: dict) -> bool:
    """Would a round starting at `slot_time`, at this club's own estimated pace for
    the active course (`recommend._round_duration_minutes()`) plus your configured
    `daylight_buffer_minutes`, finish before sunset? Added 2026-09-09, direct
    request: "It would also be great if you could immediately see in the detailed
    view, which of the timeslots are already too late until sunset."

    Deliberately independent of whether `availability` is configured at all —
    unlike the ★ recommendation (`_availability_pipeline()`), this is a plain
    physics fact about the slot, not a judgment against your own standing rules, so
    it has to work identically on a club you haven't set any preferences for yet.
    Reuses `recommend._round_duration_minutes()`/`playability.is_playable()`
    directly rather than a second, hand-rolled duration/buffer calculation — so this
    marker can never disagree with what `exclude_unplayable()` already uses to
    decide the same question for the ★ system. `False` (not "too late") with no
    `sun_times` at all — unknown, not assumed bad, same stance
    `recommend._fails_playability()` already takes."""
    if schedule.sun_times is None:
        return False
    duration = recommend._round_duration_minutes(schedule.course, config)
    buffer_minutes = config.get("daylight_buffer_minutes", 0)
    return not playability.is_playable(slot_time, schedule.sun_times.sunset, duration, buffer_minutes)


def _closest_slot_time(times: list[str], target: str) -> str | None:
    """Whichever "HH:MM" in `times` is numerically nearest `target` -- used by
    `DayDetailScreen.load_schedule()` to note sunrise/sunset on the row nearest
    each one (2026-09-13, direct feedback: "make sunrise and sunset to
    corresponding rows" — replacing the old standalone `#daylight` summary line,
    which duplicated the same information one line up instead of showing it where
    it's actually relevant). `None` for an empty `times` (no slots at all, or no
    `sun_times` — see the one call site). Ties break toward the earlier time,
    since `times` is already in chronological order and `min()` keeps the
    first-seen minimum on a tie -- an arbitrary but stable choice, not something
    this app's own 10-minute slot grid should ever actually need to break in
    practice."""
    if not times:
        return None
    target_dt = datetime.strptime(target, "%H:%M")
    return min(times, key=lambda t: abs((datetime.strptime(t, "%H:%M") - target_dt).total_seconds()))


def _recommended_times_for(schedule: Schedule, config: dict, club_id: str) -> set[str]:
    """Thin wrapper around `_availability_pipeline()` returning just the still-
    playable slot times — factored out 2026-09-14 (ROADMAP.md's queued "nested/
    collapsed overview" item) once `OverviewScreen`'s own expanded slot rows
    needed the exact same ★ computation `DayDetailScreen._recommended_times()`
    already did, without a `Screen` instance to hang it off of. That method is now
    a one-line delegate to this."""
    _, playable = _availability_pipeline(schedule, config, club_id)
    return {candidate.slot.time for candidate in playable}


class SlotRowCells(NamedTuple):
    """One tee-time slot's row, already rendered into display-ready cells — the
    output of `_compute_slot_rows()` below. `DayDetailScreen`'s own eight columns
    (Time/Condition/Occupancy/Players/Temperature/Precipitation/Wind/Events) map
    onto these fields directly; `OverviewScreen`'s expanded child rows re-map the
    same fields onto its own differently-ordered columns instead — see
    `OverviewScreen._render_table()`'s own docstring for that mapping."""

    time: str
    time_cell: str
    condition_cell: str
    occupancy_cell: str
    players_cell: str
    temperature_cell: str
    precipitation_cell: str
    wind_cell: str
    events_cell: str


def _compute_slot_rows(
    schedule: Schedule,
    config: dict,
    units: str,
    date: str,
    recommended_times: set[str],
    confirmed: ConfirmedBooking | None,
) -> list[SlotRowCells]:
    """One `SlotRowCells` per slot in `schedule`, in order — the exact per-slot
    rendering `DayDetailScreen.load_schedule()` used to do inline, factored out
    2026-09-14 so `OverviewScreen`'s expand-in-place rows (ROADMAP.md's queued
    "nested/collapsed overview" item) can build the identical cells without
    duplicating the ★/🌙 markers, sunrise/sunset notes, and past-slot dimming
    logic a second time. `DayDetailScreen.load_schedule()` now calls this too —
    behavior-preserving, not a change to what either screen shows."""
    now = _NOW_HHMM() if date == _TODAY() else None
    slot_times = [slot.time for slot in schedule.slots]
    sunrise_row = _closest_slot_time(slot_times, schedule.sun_times.sunrise) if schedule.sun_times else None
    sunset_row = _closest_slot_time(slot_times, schedule.sun_times.sunset) if schedule.sun_times else None
    rows: list[SlotRowCells] = []
    for slot in schedule.slots:
        is_past = now is not None and slot.time < now
        markers = []
        if slot.time in recommended_times and not is_past:
            markers.append("★")
        elif not is_past and _too_late_for_daylight(slot.time, schedule, config):
            markers.append("🌙")
        time_cell = _dim_if(slot.time, is_past)
        if markers:
            time_cell = f"{' '.join(markers)} {time_cell}"
        extra_events = []
        if slot.time == sunrise_row:
            extra_events.append(i18n.t("events.sunrise", time=schedule.sun_times.sunrise))
        if slot.time == sunset_row:
            extra_events.append(i18n.t("events.sunset", time=schedule.sun_times.sunset))
        if confirmed is not None and slot.time == confirmed.time:
            extra_events.append(f"📌 {i18n.t('overview.booked')}")
        condition_cell = _dim_if(_slot_condition_cell(schedule.weather, slot.time), is_past)
        temperature_cell = _dim_if(_slot_temperature_cell(schedule.weather, slot.time, units), is_past)
        precipitation_cell = _dim_if(_slot_precipitation_cell(schedule.weather, slot.time, units), is_past)
        wind_cell = _dim_if(_slot_wind_cell(schedule.weather, slot.time, units), is_past)
        if slot.block_reason is not None:
            event_text = ", ".join([_slot_event_cell(slot), *extra_events])
            rows.append(
                SlotRowCells(
                    slot.time,
                    time_cell,
                    condition_cell,
                    "[dim]—[/]",
                    "",
                    temperature_cell,
                    precipitation_cell,
                    wind_cell,
                    f"[dim]{event_text}[/]",
                )
            )
            continue
        style = f"dim {_fill_style(slot.booked, slot.capacity)}" if is_past else _fill_style(slot.booked, slot.capacity)
        occupancy = f"[{style}]{slot.booked}/{slot.capacity}[/]"
        players = ", ".join(slot.players) if slot.players else ""
        rows.append(
            SlotRowCells(
                slot.time,
                time_cell,
                condition_cell,
                occupancy,
                _dim_if(players, is_past and bool(players)),
                temperature_cell,
                precipitation_cell,
                wind_cell,
                ", ".join(extra_events),
            )
        )
    return rows


def _day_pick_text(
    schedule: Schedule | None,
    config: dict,
    confirmed: ConfirmedBooking | None,
    has_pending_change: bool,
    club_id: str,
) -> str:
    """The overview's Pick column for one day, in priority order:

    1. A confirmed booking for that date beats everything — it's not a suggestion,
       it's what's actually happening. "⚠" alongside it means `booking_watch.py`
       found an unacknowledged change since it was booked (see DayDetailScreen's own
       banners for the detail).
    2. Otherwise, if availability rules are configured and this day has a schedule to
       check: a recommended "★ HH:MM" (the best still-playable match — AI-ranked once
       `ai_assist.enabled`, otherwise the earliest, see `_availability_pipeline()`'s
       own docstring), or a specific "no dry picks"/"too dark to finish"/"nothing
       playable" message when
       candidates existed before the weather/daylight check but none survived it —
       worth saying explicitly (and *accurately* — see `recommend.unplayable_reasons()`'s
       own docstring for a real mix-up this avoids) rather than looking identical to
       "nothing matches your rules at all".
    3. A plain dash otherwise — no rules configured, no schedule yet, or genuinely no
       candidates for the day (e.g. outside every configured time window)."""
    if confirmed is not None and confirmed.time:
        text = f"📌 {confirmed.time} {i18n.t('overview.booked')}"
        if has_pending_change:
            text += " [red]⚠[/]"
        return text
    if schedule is None or not config.get("availability"):
        return "[dim]—[/]"
    candidates, playable = _availability_pipeline(schedule, config, club_id)
    if not candidates:
        return "[dim]—[/]"
    if playable:
        text = f"[yellow]★[/] {playable[0].slot.time}"
        # Folded straight into this cell, not a separate "This week's picks"
        # section any more (2026-09-14, direct feedback + the redundancy it
        # surfaced: that section only ever repeated this exact same ★ HH:MM per
        # day, one column over — a strict, smaller subset of what this cell
        # already covers, since it dropped confirmed bookings and unplayable
        # days entirely). `reasons` stays empty until `ai_assist.enabled` is
        # actually turned on (see `_availability_pipeline()`'s own docstring) —
        # nothing shows here until then, same as the removed section's own
        # behavior.
        if playable[0].reasons:
            text += f"  [dim]{', '.join(playable[0].reasons)}[/]"
        return text
    reasons = recommend.unplayable_reasons(candidates, [schedule], config)
    if reasons == {"daylight"}:
        message_key = "overview.no_daylight_picks"
    elif reasons == {"weather"}:
        message_key = "overview.no_dry_picks"
    else:
        # Both reasons, or neither pinned down (e.g. the schedule that produced
        # `playable`'s emptiness isn't the same one passed in here) -- a generic,
        # still-honest message beats guessing at a specific one that might be wrong.
        message_key = "overview.no_playable_picks"
    return f"[dim italic]{i18n.t(message_key)}[/]"


# Shared cap for every genuinely open-ended text column across both results
# tables (OverviewScreen's Events/Pick, SearchScreen's Players/Notes) --
# direct feedback 2026-09-15, fitting the whole app on an iPad portrait
# terminal (~50 columns): "Events and picks can for sure wrap up." One shared
# constant rather than a per-column value so all these columns read
# consistently at a glance, regardless of screen.
_WRAP_CAP_WIDTH = 18


def _table_overhead(num_columns: int) -> int:
    """How many extra columns of width `DataTable` itself consumes for
    per-column gutter/padding, on top of every column's own declared
    `width=` -- confirmed empirically (two differently-sized tables: 8
    columns needed 15 reserved, 3 columns needed 5), not documented anywhere
    in Textual itself. `_render_table()` uses this to decide whether Events/
    Pick's own natural width will actually fit a given screen width before
    falling back to `_WRAP_CAP_WIDTH`."""
    return 1 + (num_columns - 1) * 2


def _cell_visible_width(markup_text: str) -> int:
    """The real on-screen width of a `DataTable` cell string once its own
    Rich markup (`[dim]...[/]`, `[yellow]★[/]`, etc.) is stripped and its wide
    characters (emoji, CJK) are counted properly -- `Text.from_markup(...).cell_len`
    does exactly this in one call. Added 2026-09-14 for `OverviewScreen`'s own
    column-width computation (`_render_table()`'s own docstring) once reading
    `DataTable`'s own `Column.width`/`content_width` after the fact turned out
    unreliable: computing it ourselves, straight from the same cell strings
    this app is about to display, needed no dependency on that at all.

    Multi-line text (a `"Temperature\\n(°C)"`-style wrapped header — see
    `_column_header()`) needs its own widest *line*, not the whole string's
    `cell_len` including the newline itself as a character (confirmed
    empirically: the naive single-call version overcounted a two-line header
    by exactly one, and would have quietly forced every such column a touch
    wider than its own rendered content ever actually needs)."""
    text = Text.from_markup(markup_text)
    return max(line.cell_len for line in text.split("\n"))


def _legend_pairs(entries: list[tuple[str, str]]) -> list[str]:
    """Each entry rendered as one "icon meaning" unit, e.g. "★ recommended" --
    takes a plain list (`OVERVIEW_LEGEND` below, the only one left since
    `DayDetailScreen`'s own separate `DAY_DETAIL_LEGEND` was retired alongside
    that screen 2026-09-15) rather than assuming one specific constant, so a
    narrower subset (e.g. `CONDITION_LEGEND` alone) can reuse it too."""
    return [f"{icon} {i18n.t(key)}" for icon, key in entries]


def _wrap_legend(pairs: list[str], width: int) -> str:
    """Pack legend pairs onto as few lines as fit in `width` cells, greedily,
    never splitting one pair's icon from its own meaning across two lines --
    added 2026-09-09, direct follow-up: "legend needs to wrap up, since some
    words might be cut off." A first attempt joined icon and meaning with a
    non-breaking space, expecting that to block a wrap between them; confirmed
    live it doesn't fix anything -- Rich's own word-wrapper
    (rich._wrap.divide_line) splits on Python's regular \\s regex, which treats
    U+00A0 as just another whitespace character, not specially "unbreakable" the
    way a browser's CSS renderer would. So this wraps the legend itself line by
    line, rather than handing Rich one long string and hoping its own wrap
    behaves -- the exact failure mode confirmed live (a narrow terminal wrapping
    right between an icon and its own meaning, stranding the icon at the end of
    one line and the meaning alone at the start of the next) can't happen here,
    since a break only ever falls between whole pairs. rich.cells.cell_len (the
    same width measure Rich's own wrapper uses, not len()) accounts for wide
    glyphs like emoji correctly. A single pair wider than width still gets its
    own line rather than being cropped or dropped -- the same "never lose real
    information to a layout constraint" stance every other narrow-terminal
    fallback in this app already takes."""
    lines: list[str] = []
    current = ""
    for pair in pairs:
        candidate = f"{current}  {pair}" if current else pair
        if current and cell_len(candidate) > width:
            lines.append(current)
            current = pair
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


# One (icon, i18n key) pair per icon that screen's own table can actually show —
# kept as the single source of truth both the legend line and this comment can
# point back to, rather than the icons living only inside each cell-building
# function with nothing tying their meanings together in one place.
# The Condition column's own weather-condition icons (weather_icons.py, WMO
# code -> icon), spelled out since several aren't self-explanatory at a glance
# (direct feedback 2026-09-15: "Conditions needs some legend, as some icons
# might not be self explanatory"). Shared by both screens' legends below --
# every icon `weather_icons.icon_for_code()`/`worst_icon()` can actually
# return, distinct codes collapsed onto one entry each (e.g. every drizzle
# severity is the same 🌦️ icon, so one "drizzle" line covers all of them).
#
# Real duplicate caught live the same day, direct follow-up ("I noticed that
# rain icon is shown twice in the legend"): this list's own 🌧️ (with VS16,
# "it's raining right now") and the Precipitation/Wind columns' own plain 🌧/💨
# threshold markers (`_SLOT_RAIN_ICON_THRESHOLD_PERCENT`/`_SLOT_WIND_ICON_
# THRESHOLD_KPH` -- "worth noticing at a glance," a fixed visual cutoff,
# independent of the user's own configurable avoid_rain/avoid_wind
# preference) both used the identical "legend.rain"/"legend.wind" text below
# -- two visually near-identical glyphs both just saying "rain"/"wind," read
# as one accidentally-repeated line. Different concepts (current condition
# vs. a specific column crossing a notice threshold), so they keep their own
# icons but now say something different too: `legend.rain_threshold`/
# `legend.wind_threshold` ("rain likely"/"windy") for the threshold markers,
# leaving plain "rain" solely to this list's own condition icon.
#
# Ordering, direct question 2026-09-15 ("how are the weather icons arranged/
# ordered?"): calm-first, straight from `weather_icons.ordered_icons()` --
# the exact reverse of that module's own `_SEVERITY_ORDER` (worst-first,
# already the source of truth `worst_icon()` uses to collapse a day's hourly
# codes down to one icon), rather than a second, separately hand-typed
# ordering that could silently drift out of sync with it. Each icon's own
# label still lives here, in `_CONDITION_LEGEND_LABELS` below, since the
# severity list only knows about WMO codes/icons, not this app's own i18n
# keys for them.
_CONDITION_LEGEND_LABELS = {
    "☀️": "legend.clear",
    "🌤️": "legend.mostly_clear",
    "⛅": "legend.partly_cloudy",
    "☁️": "legend.overcast",
    "🌫️": "legend.fog",
    "🌦️": "legend.drizzle",
    "🌧️": "legend.rain",
    "❄️": "legend.snow",
    "🌨️": "legend.snow_showers",
    "⛈️": "legend.thunderstorm",
}
CONDITION_LEGEND = [(icon, _CONDITION_LEGEND_LABELS[icon]) for icon in weather_icons.ordered_icons()]
# The only legend left as of 2026-09-15 (`DayDetailScreen`, and its own
# separate `DAY_DETAIL_LEGEND`, retired the same day) -- so it now has to
# cover every marker either a day-summary row *or* one of its own expanded
# slot rows can show. `🌙` (too late to finish before dark) moved in from the
# old `DAY_DETAIL_LEGEND`: a real gap caught while removing that list, not
# just a copy-paste -- `_compute_slot_rows()` (shared by both, see its own
# docstring) has always been able to mark an expanded slot row with `🌙`, but
# this legend never explained it, since only the now-retired screen's own
# legend used to.
#
# Split into labeled categories for rendering (2026-09-15, direct question:
# "would it make sense to separate legend into categories?", asked right
# alongside the icon-ordering one above) -- Markers (table-row indicators),
# Weather (the Condition column's own icons, `CONDITION_LEGEND`), and Notices
# (the Precipitation/Wind threshold flags) are different *kinds* of thing, not
# just one long undifferentiated list. `OVERVIEW_LEGEND` itself stays a flat
# concatenation of the three -- existing membership checks (`icon in
# OVERVIEW_LEGEND`) and the general-purpose `_legend_pairs()`/`_wrap_legend()`
# machinery don't need to know or care that it's actually three groups;
# `_render_legend()` is the only thing that reads `OVERVIEW_LEGEND_CATEGORIES`
# instead, to render each group under its own heading.
_MARKER_LEGEND = [
    ("▶/▼", "legend.expand"),
    ("•", "legend.today"),
    ("★", "legend.recommended"),
    ("🌙", "legend.too_late"),
    ("📋", "legend.event"),
    ("📌", "overview.booked"),
    ("⚠", "legend.changed"),
]
_NOTICE_LEGEND = [
    ("🌧", "legend.rain_threshold"),
    ("💨", "legend.wind_threshold"),
]
OVERVIEW_LEGEND = [*_MARKER_LEGEND, *CONDITION_LEGEND, *_NOTICE_LEGEND]
OVERVIEW_LEGEND_CATEGORIES = [
    ("legend.category_markers", _MARKER_LEGEND),
    ("legend.category_weather", CONDITION_LEGEND),
    ("legend.category_notices", _NOTICE_LEGEND),
]


class _AutoHideStatic(Static):
    """A `Static` that collapses out of layout entirely (`display: none`)
    whenever its own content is empty, instead of always reserving its own
    blank line -- used for `#banners`/`#status` on `OverviewScreen` and
    `DayDetailScreen`, both blank most of the time.

    Found live, 2026-09-13, "check for spacing consistency": a plain `Static`
    still occupies its own line even with nothing to show, so the visible gap
    before/after it silently changes size depending on whether there happens
    to be a banner or status message at that exact moment -- exactly what made
    the day-detail screen's own top area look inconsistent (compare the single
    blank line between the switcher's two dropdown rows against the two- or
    three-line gap that used to sit above the table once an empty `#banners`/
    `#status`/the now-removed `#daylight` line were stacked on top of each
    other).

    Overriding `update()` here, rather than hunting down and touching every
    individual call site that writes to `#banners`/`#status` across
    `OverviewScreen`, `DayDetailScreen`, `_ClubCourseSwitcher`, and `TeetimeApp`
    itself, means the fix applies uniformly and automatically wherever these
    widgets are updated -- a find-and-replace across that many call sites would
    only need to miss one to silently reintroduce the exact inconsistency this
    exists to fix. `_SWITCHER_CSS` (shared by both screens already) starts both
    ids hidden via a plain `display: none`, matching the empty text both are
    constructed with in `compose()` -- the first real `update()` call is what
    ever makes either one visible."""

    def update(self, renderable: object = "") -> None:
        super().update(renderable)
        self.styles.display = "block" if str(renderable) else "none"


def _render_banner_lines(changes: list[dict], include_date: bool) -> str:
    """One "⚠ ..." line per unacknowledged `booking_watch.py` change --
    shared by `DayDetailScreen.refresh_banners()` and (added 2026-09-15,
    "why don't we integrate those missing features into the overview
    screen") `OverviewScreen.refresh_banners()`, rather than two copies of
    the same rendering logic. `render_booking_change()` re-renders kind+params
    in the current language; falls back to the stored (English) message for a
    row saved before that existed, or an unrecognized kind, rather than
    showing nothing. `include_date` prefixes each line with its own weekday +
    short date — `DayDetailScreen` never needs this (you're already looking
    at that one specific day), but `OverviewScreen` spans several, so a bare
    message alone wouldn't say which day it's about."""
    lines = []
    for change in changes:
        message = i18n.render_booking_change(change["kind"], change["params"]) or change["message"]
        if include_date:
            weekday = i18n.t(f"weekday.{date_cls.fromisoformat(change['date']).weekday()}")
            message = f"{weekday} {change['date'][5:]}: {message}"
        lines.append(f"⚠ {message}")
    return "\n".join(lines)


_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _format_ago(seconds: float) -> str:
    """"just now" / "{n}m" / "{n}h" for `_RefreshStatus`'s idle readout --
    plain, unit-suffixed like this app's own km/h or mm already are, not
    translated word-by-word (see `status.updated_ago`'s own docstring)."""
    if seconds < 60:
        return i18n.t("status.just_now")
    if seconds < 3600:
        return i18n.t("status.updated_ago", time=f"{int(seconds // 60)}m")
    return i18n.t("status.updated_ago", time=f"{int(seconds // 3600)}h")


class _RefreshStatus(Static):
    """Compact refresh-freshness readout living beside the Club dropdown row
    (2026-09-15, direct feedback: "I see a nice space to the right of both
    dropdown menus. Can we use that for the 'refreshing' notification, and
    maybe combine that with a status bar, timer or wheel"). Two states: an
    animated braille spinner + "Refreshing…" while a scrape is actually
    running (`start_refreshing()`), or a plain "Updated Xm ago" readout once
    idle (`finish_refreshing()`) that keeps re-rendering itself every 30s
    while mounted so it never goes stale-looking during a long session --
    genuine ongoing freshness awareness, not just the one-off transient blip
    the old standalone `#status` line gave for this. `#status` itself is
    untouched and still used for actual error messages ("no tee sheet
    found", a failed fetch) — this widget's own narrow space next to a
    dropdown is no place for arbitrary-length error text, only this one
    short, predictable readout.

    Shared by `OverviewScreen` and `DayDetailScreen` via `_compose_switcher()`
    below, same as everything else in `_ClubCourseSwitcher` — one widget, not
    two independently-maintained copies."""

    DEFAULT_CSS = """
    _RefreshStatus {
        width: 1fr;
        height: 1;
        color: $text-muted;
        content-align: right middle;
        padding-right: 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._last_refreshed_at: datetime | None = None
        self._spinner_frame = 0
        self._spinner_timer = None

    def on_unmount(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()

    def start_refreshing(self) -> None:
        self._spinner_frame = 0
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
        self._spinner_timer = self.set_interval(0.1, self._tick_spinner)
        self._tick_spinner()

    def _tick_spinner(self) -> None:
        frame = _SPINNER_FRAMES[self._spinner_frame % len(_SPINNER_FRAMES)]
        self._spinner_frame += 1
        self.update(f"{frame} {i18n.t('status.refreshing')}")

    def finish_refreshing(self) -> None:
        """Called on success *and* failure -- a failed scrape still means
        "we just checked," even though `#status` separately explains it
        didn't land; this readout answers "how current is what's on screen,"
        not "did the last attempt succeed."""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self._last_refreshed_at = datetime.now(timezone.utc)
        self._render_idle()

    def on_mount(self) -> None:
        # Re-renders "Updated Xm ago" on its own timer, independent of
        # whatever triggers an actual refresh -- otherwise it would silently
        # go stale (still reading "Updated 1m ago" an hour into a long
        # session) until the next real scrape happened to land.
        self.set_interval(30, self._render_idle)

    def _render_idle(self) -> None:
        if self._last_refreshed_at is None:
            self.update("")
            return
        elapsed = (datetime.now(timezone.utc) - self._last_refreshed_at).total_seconds()
        self.update(_format_ago(elapsed))


# Shared by both OverviewScreen and DayDetailScreen's own #switcher (2026-09-11,
# "I want the club and course selector drop downs also implemented in the
# detailed view") -- one constant rather than two copies drifting apart, same
# reasoning as factoring _ClubCourseSwitcher out below in the first place.
_SWITCHER_CSS = """
#switcher {
    height: auto;
    padding: 0 2;
}
.switcher-row {
    height: 1;
    margin-bottom: 1;
    align: left middle;
}
.switcher-label {
    width: 10;
    content-align: right middle;
    padding-right: 2;
}
#club-select, #course-select {
    width: auto;
    max-width: 60;
}
#club-row-fields {
    width: auto;
    height: 1;
}
/* _apply_switcher_layout()'s own "stacked" class -- the club label/dropdown
   (#club-row-fields) and the refresh-status readout share `#club-row` (a
   Horizontal) whenever there's room; toggling its own `layout` to vertical
   is what actually drops the status readout onto its own line below instead
   of squeezing it into whatever's left of a fixed `1fr`. #club-row-fields
   deliberately keeps its own plain `width: auto` even here (not stretched to
   100%) -- purely cosmetic (a left-aligned label+dropdown reads fine above a
   right-aligned status line), *not* load-bearing for the decision itself any
   more, since _apply_switcher_layout() computes that from `self.club_name`
   directly rather than this widget's own rendered size (see that method's
   own docstring for why). */
#club-row.stacked {
    layout: vertical;
    height: auto;
}
#club-row.stacked _RefreshStatus {
    width: 100%;
}
"""

# Also shared by both screens (2026-09-13, "check for spacing consistency") --
# #banners/#status start hidden, matching the empty text both are constructed
# with in compose(); see _AutoHideStatic's own docstring for why this lives in
# CSS rather than a per-widget default and why update() is what flips it back.
_AUTO_HIDE_CSS = """
#banners, #status {
    display: none;
}
"""


class _ClubCourseSwitcher:
    """Shared inline club/course dropdown behavior for `OverviewScreen` and
    `DayDetailScreen` (2026-09-11, direct feedback: "I want the club and course
    selector drop downs also implemented in the detailed view") -- factored out
    here rather than copy-pasted a second time, since the switching logic below
    carries real, hard-won behavior (see `_refresh_course_options()`'s own
    docstring for the `Select.Changed` transient-value bug this shape avoids)
    that a second, independently-maintained copy would risk quietly drifting out
    of sync with.

    A subclass needs its own `club_id`/`club_slug`/`club_name`/`course`
    attributes (both screens already have these for other reasons) and a
    `_reload()` method that re-renders whatever this screen shows for the
    *current* club_id/course (`load_overview()` / `load_schedule()`
    respectively) -- that renders-what-exactly difference is the only thing
    that actually varies between the two screens' switchers. Neither screen
    sets its own Header title any more (2026-09-11, direct feedback: "I want
    the header to include the name of the TUI 'teetime-monitor' and remove the
    club/course names since they will be redundant" -- redundant precisely
    because the labelled dropdowns right below the header already show both),
    so switching doesn't need to touch it either.

    Labelled rows, not bare dropdowns (2026-09-11, same feedback: "I want
    labels to the left of club and course selector drop downs") -- reuses the
    same `.field-row`/`.field-label`-style left-label convention
    `settings_screen.py`/`SearchScreen` already established elsewhere in this
    app (`.switcher-row`/`.switcher-label` here, since these rows sit directly
    in a screen's own `#switcher` rather than a settings form), rather than
    inventing a second visual pattern for the same idea."""

    def _club_select_options(self) -> list[tuple[str, str]]:
        """(label, club_id) pairs for the inline club selector -- every saved
        favorite, plus the currently active club if it isn't one (visited via a
        directory search without saving, or a bare typed-in id), so the dropdown
        always has a valid value to show -- same "inject the current value if
        it's missing from the presets" convention every dropdown in this app
        already follows (see settings_screen.py)."""
        favorites = _favorite_clubs()
        if self.club_id not in {club_id for club_id, _ in favorites}:
            favorites = [(self.club_id, self.club_name or self.club_slug or self.club_id), *favorites]
        return [(name, club_id) for club_id, name in favorites]

    def _compose_switcher(self) -> ComposeResult:
        with Vertical(id="switcher"):
            # club-row-fields nests the label+dropdown separately from
            # _RefreshStatus so _apply_switcher_layout() can toggle *this*
            # row's own layout (horizontal/vertical) without needing to move
            # any widget between containers -- see that method's own
            # docstring and `#club-row.stacked`'s CSS above.
            with Horizontal(classes="switcher-row", id="club-row"):
                with Horizontal(id="club-row-fields"):
                    yield Label(i18n.t("switcher.club_label"), classes="switcher-label")
                    yield Select(
                        self._club_select_options(), value=self.club_id, allow_blank=False,
                        compact=True, id="club-select",
                    )
                yield _RefreshStatus()
            with Horizontal(classes="switcher-row"):
                yield Label(i18n.t("switcher.course_label"), classes="switcher-label")
                # Just the current course at first -- the club's full list needs a
                # live fetch (fetch_course_aliases()), kicked off from on_mount()
                # instead so compose() itself never blocks on the network, same
                # rule every other screen here already follows.
                yield Select(
                    [(self.course, self.course)], value=self.course, allow_blank=False,
                    compact=True, id="course-select",
                )

    # How much room the refresh-status readout itself needs to read
    # comfortably ("Updated 59m ago" plus a little slack) -- below this,
    # _apply_switcher_layout() drops it onto its own line instead.
    _STATUS_MIN_WIDTH = 18
    # .switcher-label's own fixed CSS width (10) plus its padding-right (2).
    _SWITCHER_LABEL_WIDTH = 12
    # #club-select's own CSS cap (`max-width: 60`), plus a little slack for
    # Select's own chrome (the dropdown arrow and its surrounding padding) --
    # not pinned down to an exact measured value (see this method's own
    # docstring for why live-measuring the widget itself was dropped).
    _SELECT_CHROME_WIDTH = 4
    _SELECT_MAX_WIDTH = 60

    def _apply_switcher_layout(self, width: int | None = None) -> None:
        """Moves the refresh-status readout onto its own line once the club
        label+dropdown don't leave it enough room to read comfortably on the
        same line -- direct feedback 2026-09-16: "can you make status area
        wrap up when window is too narrow?" Previously it just got squeezed
        into whatever was left of a fixed `1fr` next to `#club-select`, which
        on a narrow terminal (or a long club name) meant real clipping, not a
        wrap -- `Horizontal` containers in Textual don't reflow their own
        children onto a new line by themselves the way CSS flex-wrap would.

        Computes the label+dropdown's own width straight from `self.club_name`
        (the same "measure the string, not the rendered widget" approach
        `_render_table()`'s own docstring already documents at length for the
        exact same reason) rather than querying `#club-select`'s live
        `.size.width` -- confirmed empirically that reads back `max-width`
        (60) even for a short club name immediately after mount/resize,
        Select's own real auto-content-width apparently no more
        synchronously available than `DataTable.Column`'s was.

        Also *sets* `#club-row-fields`'s own width to that same computed
        value, not just `#club-row`'s "stacked" class -- confirmed
        empirically that `width: auto` on a `Horizontal` (unlike a plain
        `Label`/`Static`) doesn't shrink-wrap to its children's real content
        at all, it fills the *entire* row regardless, which in the
        not-stacked case squeezed `_RefreshStatus`'s own `1fr` down to
        nothing beside it even with plenty of real room -- an explicit width
        here is what actually leaves `_RefreshStatus` its fair share."""
        w = width if width is not None else self.size.width
        club_label_text = self.club_name or self.club_slug or self.club_id
        select_width = min(_cell_visible_width(club_label_text) + self._SELECT_CHROME_WIDTH, self._SELECT_MAX_WIDTH)
        fields_width = self._SWITCHER_LABEL_WIDTH + select_width
        stacked = (w - fields_width) < self._STATUS_MIN_WIDTH
        self.query_one("#club-row").set_class(stacked, "stacked")
        self.query_one("#club-row-fields").styles.width = fields_width

    async def _refresh_course_options(self) -> None:
        """Fills the course selector in with the active club's *real* course list,
        once fetched -- `_compose_switcher()` seeds it with just the current course
        so mounting never blocks on the network. Silently keeps the single-entry
        fallback on a failed fetch, same graceful-degradation every other live
        lookup here already follows, rather than surfacing a fetch error for a
        dropdown that still works fine with just the one course it already knows
        about.

        `self.course` is always kept first in the list handed to `set_options()`,
        not just included somewhere — real bug found live, 2026-09-10, while
        adding last-active-club persistence: `set_options()` briefly resets the
        Select's own value to its new *first* option before the very next line
        explicitly corrects it back to `self.course`, firing a real (non-blank)
        `Select.Changed` for that transient wrong value in between. A guard-flag
        approach can't catch this reliably either: `Select.Changed` is delivered
        as a queued message, processed on a later turn of the event loop than the
        one this coroutine's own body (guard included) already finished on.
        Keeping `self.course` first removes the transient wrong value altogether
        — the momentary state during the rebuild is already correct, so there's
        nothing spurious left to guard against."""
        try:
            courses = list(fetch_course_aliases(self.club_id))
        except Exception:  # noqa: BLE001 — see docstring
            return
        courses = [self.course, *(c for c in courses if c != self.course)]
        select = self.query_one("#course-select", Select)
        select.set_options((course, course) for course in courses)
        select.value = self.course

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return  # a transient state while set_options() rebuilds the list
        if event.select.id == "club-select" and event.value != self.club_id:
            self.run_worker(self._switch_club(event.value), exclusive=True, group="switch")
        elif event.select.id == "course-select" and event.value != self.course:
            self._switch_course(event.value)

    async def _switch_club(self, club_id: str) -> None:
        """The inline club selector's own version of `TeetimeApp._open_club()` --
        same bookkeeping (resolve slug/config, pick a course, update the App's own
        `_club_slug`/`_club_config` so the periodic background scrape follows the
        switch too — see that method's own docstring for the real bug this exact
        step fixed once before), but updates this same screen's state and reloads
        in place instead of pushing a new one."""
        slug = club_config.slug_for_club_id(club_id)
        config = club_config.load_club_config(slug) if slug else {}
        name = dict(_favorite_clubs()).get(club_id, "")
        try:
            courses = list(fetch_course_aliases(club_id))
        except NoTeeSheetError:
            self.query_one("#status", Static).update(i18n.t("app.no_tee_sheet", club_id=club_id))
            self.query_one("#club-select", Select).value = self.club_id  # revert the dropdown
            return
        except Exception as exc:  # noqa: BLE001 — a live fetch can genuinely fail
            self.query_one("#status", Static).update(i18n.t("app.course_fetch_failed", error=exc))
            self.query_one("#club-select", Select).value = self.club_id
            return
        default_course = config.get("default_course")
        course = default_course if default_course in courses else courses[0]

        self.club_id = club_id
        self.club_slug = slug
        self.club_name = name
        self.course = course
        course_select = self.query_one("#course-select", Select)
        course_select.set_options((c, c) for c in courses)
        course_select.value = course
        self._reload()
        # A switch to a club whose name is a very different length can flip
        # whether the refresh-status readout still fits beside it.
        # self.club_name is already updated above by the time this runs.
        self._apply_switcher_layout()

        app = self.app
        app._club_slug = slug
        app._club_config = {**config, "club_id": club_id}
        app._periodic_scrape()
        # So the *next* launch resumes here too, not back at the club/course
        # pickers -- see global_preferences.load_last_active_club()'s own docstring.
        global_preferences.save_last_active_club(club_id, slug, course)

    def _switch_course(self, course: str) -> None:
        """No network, no App-level bookkeeping needed -- `scrape_due_for_club()`
        already scrapes every one of a club's courses regardless of which one is
        showing here, so only this screen's own state needs to change."""
        self.course = course
        self._reload()
        global_preferences.save_last_active_club(self.club_id, self.club_slug, course)


class OverviewScreen(_ClubCourseSwitcher, Screen[None]):
    """The multi-day at-a-glance home screen — one row per attempted day: weekday +
    exact ISO date, weather split into its own Temperature/Precipitation/Wind
    columns (2026-09-09, direct feedback: "can you please split weather into
    Temperature, Precipitation, and wind columns" — see `_temperature_cell()`'s own
    docstring), that day's own event/closure note in a separate Events column
    (split out one exchange earlier the same day, same reasoning: a Weather column
    mixing the two was a real problem, not just a labeling nitpick), a six-block
    "heat strip" showing how full 08:00-20:00 is in 2-hour windows, and that day's
    own pick (`_day_pick_text()`) — the one and only place a recommendation shows.
    A separate "This week's picks" section used to repeat the exact same ★ HH:MM
    one column over, below the table; dropped 2026-09-14, direct feedback ("check
    whether the recommendation area and recommendation column are redundant") that
    turned up a real answer: the section was a strict, smaller subset of the
    column (it silently dropped confirmed bookings and unplayable days that the
    column always shows), never the other way around. `_day_pick_text()`'s own ★
    cell now folds in AI-ranked `reasons` text directly (empty until `ai_assist.
    enabled` is turned on) — the one genuine thing the removed section could show
    that the column couldn't, now with nowhere else for it to live.

    A dim `#legend` line below the table (2026-09-09, direct question: "Would it
    make sense to implement a legend, since we already have so many icons?") spells
    out what every icon this screen can show actually means (`OVERVIEW_LEGEND`) —
    added alongside a real fix, not just documentation: `_event_cell()`'s own 📌 was
    quietly reused for two different meanings (a day's event/closure note here, a
    confirmed booking in the Pick column) until this same change gave the Events
    column its own icon (📋) instead, so a legend would never have to list one icon
    twice for two different things.

    Data comes from whatever's already been scraped (`storage.load_latest_schedule()`
    per day), same as `DayDetailScreen` — opening this screen never blocks on a live
    fetch; `TeetimeApp._periodic_scrape()` (on open, and on a timer) is what keeps it
    current, exactly as it already did for the single-day view.

    How many days to attempt, and which of those are actually open for booking, are
    two separate questions — see `_display_dates()` and `scraper.fetch_available_dates()`'s
    own docstring for why a club's real booking window can be shorter (or longer)
    than the configured `overview_days`; a day beyond it renders as "not open for
    booking yet" rather than a misleadingly empty schedule.

    Enter expands a day row in place (▶/▼ caret, indented slot rows inserted directly
    beneath it — `_render_table()`'s own docstring has the column-remapping detail),
    rather than drilling into a separate day-detail screen (the "nested/collapsed
    overview" item, queued 2026-09-13, scoped and built 2026-09-14 once "expand-in-
    place rows" was picked over a split pane or a full accordion rewrite; the
    screen it replaced, `DayDetailScreen`, was retired outright once expansion
    covered its viewing role too — see the module docstring's own note on where its
    last two unique features, banners and a manual refresh, moved). Enter on one of
    those expanded slot rows confirms or cancels that exact tee time instead.
    `enter` itself is Textual's own built-in `DataTable` behavior, not a `BINDINGS`
    entry this screen declares — the same reason it never showed up in the footer on
    its own, fixed by listing it explicitly in `_FOOTER_BINDINGS` (see
    `ClubBrowserScreen`'s own docstring for the direct feedback this responds to).

    `action_search()` opens `SearchScreen` (Phase 4's ad hoc search, wired in
    2026-09-08 once its own backend -- `search.py`'s hard filters,
    `recommend.exclude_unplayable()`, `ai_assist.rank_slots()` -- already existed
    fully tested; `recommend.ranked_matches()` is the same three-step pipeline
    `weekly_picks()` uses, just taking an explicit typed-in `SearchCriteria` instead
    of deriving one from your saved defaults), searching across whatever days are
    already loaded here (`self._schedules`), not a fresh scrape. `action_heatmap()`
    opens `HeatmapScreen` (Phase 5's crowd heatmap, wired in 2026-09-08: "Can we
    still start building the UI for the heat map? We need a menu to track how much
    data has been collected, and how much is still needed to be functional" — a real
    data-readiness view, not a heatmap grid built ahead of having any real data to
    show in it; see that screen's own docstring). `action_edit_settings()` opens
    `SettingsScreen` (added 2026-09-08, direct feedback: "i don't even know where to
    configure from the UI"); your availability/preferences are global, not per-club
    (same-day follow-up: "i also want the settings/preferences to be global and not
    tied to a specific club") — it opens the same one shared settings set regardless
    of which club is active, or even whether one is favorited at all. `action_switch()`
    opens `ClubBrowserScreen` to find/switch clubs (see `TeetimeApp
    ._do_switch_club_or_course()`'s own docstring).

    None of those four have their own direct key any more (2026-09-16, direct
    follow-up on the 2026-09-15 command-palette work below: "I thought settings and
    commands were now integrated into one menu. Why do we still have a key bind for
    commands?" — having both a direct key *and* a palette entry for the exact same
    action wasn't integration, it was the same four things reachable two different
    ways). `t` — renamed Actions, since it's no longer just a searchable list of
    Textual's own commands now that these are the *only* way to reach it — opens
    the command palette; each still calls the exact same `action_*` method above
    (see `TeetimeApp.get_system_commands()`). `r` (Refresh) and `x` (Dismiss
    banners) keep their own direct keys regardless — both are reached for often
    enough, and right after something changes on screen, that a searchable menu
    would only slow down the exact moment they're needed.

    Two inline `Select` dropdowns at the top — club and course — let you switch
    between clubs/courses you already have saved without leaving this screen at all
    (added 2026-09-09, direct feedback: "would it be possible to integrate club and
    course selectors into the overview screen... this would make navigation much
    quicker"). Changing either one reloads in place (`_switch_club()`/
    `_switch_course()`, both actually defined on the shared `_ClubCourseSwitcher`
    mixin — see its own docstring) rather than pushing a new screen. The club
    dropdown only lists favorites (`_favorite_clubs()`) plus the currently active
    club if it isn't one — finding a club you haven't saved yet still needs Actions
    → Find a club's full searchable `ClubBrowserScreen`, which stays exactly as it
    was; the inline selectors are an additional fast path for clubs you're already
    switching between regularly, not a replacement for discovering a new one.

    Stacked (course under club) rather than side by side, both widened to fit a
    real course name without truncating, and now with a label to the left of each
    (2026-09-11, direct feedback in two parts: "make course dropdown in overview
    wider and position it under the club selection dropdown," then "I want labels
    to the left of club and course selector drop downs") — the original
    single-row layout is what forced `#course-select`'s own narrower fixed width
    in the first place. `DayDetailScreen` now has the identical switcher too
    (same feedback, part three: "I want the club and course selector drop downs
    also implemented in the detailed view") — see `_ClubCourseSwitcher` for what's
    actually shared between the two.

    `#overview-table { height: 1fr }` (2026-09-14, direct feedback once expand-
    in-place rows could actually make the table tall: "fixate everything from
    the recommendation area to the bottom") — the exact same fix
    `DayDetailScreen`'s own `#table` already got in v0.9.1 ("fix day-detail
    scrolling the whole screen instead of just the table"), just never applied
    here since this table was a fixed 5 rows until expansion existed. Without
    it, `DataTable`'s default `height: auto` sizes to however many rows are
    currently showing — a `Screen`'s own default vertical layout then has no
    fixed remaining region to cap it against, so expanding a day pushed the
    legend/the footer further down the *document* (scrolling the whole screen
    to reach them) instead of just growing the table's own internal
    scrollbar. `1fr` gives the table exactly the leftover
    space after its fixed-height siblings, so those siblings stay put
    regardless of how many rows are expanded."""

    CSS = _SWITCHER_CSS + _AUTO_HIDE_CSS + """
    #overview-table {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("x", "dismiss_banners", "Dismiss banners"),
        ("t", "command_palette", "Actions"),
        ("q", "quit", "Quit"),
    ]
    _FOOTER_BINDINGS = [
        ("enter", "binding.expand_or_confirm"),
        ("r", "binding.refresh"),
        ("x", "binding.dismiss_banners"),
        ("t", "binding.commands"),
        ("q", "binding.quit"),
    ]

    def __init__(self, club_id: str, club_slug: str | None, course: str, club_name: str = "") -> None:
        super().__init__()
        self.club_id = club_id
        # Whatever load_overview() last actually loaded -- SearchScreen (`/`) reuses
        # this rather than re-hitting storage itself, same "opening a screen should
        # be instant" rule every other screen in this app already follows.
        self._schedules: list[Schedule] = []
        # None for a club being visited without saving it (see ClubBrowserScreen) —
        # an ordinary state, same as DayDetailScreen's own club_slug.
        self.club_slug = club_slug
        self.club_name = club_name
        self.course = course
        # One entry per day-summary row, in display order -- unaffected by
        # expansion (see _row_index below), kept purely for _initial_date()'s own
        # cursor-placement lookup, which only ever runs right after a fresh,
        # all-collapsed load.
        self._row_dates: list[str] = []
        # One entry per *physical* table row -- (date, None) for a day-summary
        # row, (date, slot_time) for one of that day's expanded child rows.
        # Added 2026-09-14 for the "nested/collapsed overview" redesign
        # (ROADMAP.md, queued 2026-09-13): on_data_table_row_selected() reads
        # this to tell which kind of row `enter` landed on.
        self._row_index: list[tuple[str, str | None]] = []
        # Which dates currently show their own slot rows inline. Deliberately
        # not reset by every load_overview() call (a periodic auto-refresh
        # shouldn't collapse whatever you're currently looking at) -- only
        # _reload() (a real club/course switch, a genuinely different dataset)
        # clears it.
        self._expanded_dates: set[str] = set()
        # `_display_dates()`'s own result, cached from the last load_overview()
        # -- real, noticeable lag caught live 2026-09-14 ("i notice a bit of
        # lag when uncollapsing the menus"): _display_dates() calls
        # scraper.fetch_available_dates(), a real synchronous HTTP GET against
        # the club's own site (up to a 15s timeout), and every single expand/
        # collapse/confirm/cancel used to re-run it just to redraw the table --
        # the booking window doesn't change between one keypress and the next,
        # so there was never a reason to. _rerender_preserving_cursor() now
        # reuses this instead of re-fetching; only a fresh load_overview() (a
        # real open, club/course switch, or the periodic auto-refresh) re-hits
        # the network.
        self._cached_dates: list[str] = []
        self._cached_open_dates: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield from self._compose_switcher()
        yield _AutoHideStatic("", id="banners")
        yield _AutoHideStatic("", id="status")
        yield DataTable(id="overview-table", header_height=2)
        yield Static("", id="legend")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    # Indices into _render_table()'s own fixed 8-column order (Day/Time,
    # Condition, Temperature, Precipitation, Wind, Occupancy, Events, Pick --
    # see that method's own docstring for the Events/Occupancy ordering).
    # Events and Pick are both capped at the module-level _WRAP_CAP_WIDTH and
    # wrap (`height=None`) rather than force a wide column, since both carry
    # genuinely open-ended text (event/tournament names and unplayable-
    # reason sentences/AI reasons, respectively).
    _EVENTS_COLUMN_INDEX = 6
    _PICK_COLUMN_INDEX = 7

    def on_mount(self) -> None:
        self._render_legend()
        self.refresh_banners()
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        # Columns are declared inside _render_table() itself, not here --
        # see that method's own docstring for why (their widths depend on
        # the real cell content load_overview() is about to compute).
        self.load_overview()
        self.run_worker(self._refresh_course_options(), exclusive=True, group="course-options")
        # Computed straight from self.club_name/self.size, both already known
        # here -- no deferral needed (see _apply_switcher_layout()'s own
        # docstring for why it doesn't measure any live-rendered widget).
        self._apply_switcher_layout()

    def on_resize(self, event: events.Resize) -> None:
        # events.Resize doesn't bubble (same reasoning as SettingsScreen's own
        # identical on_resize() -- see that screen's docstring), so this has to
        # live directly on the Screen. Re-wraps the legend for the new width;
        # _rerender_preserving_cursor() re-declares the table's columns too
        # (only actually capping Events/Pick once the *new* width doesn't fit
        # their natural content -- see that method's own docstring);
        # _apply_switcher_layout() decides whether the refresh-status readout
        # still fits beside the club dropdown at the new width. All three
        # reuse whatever's already cached/mounted rather than a fresh fetch.
        self._render_legend(event.size.width)
        self._rerender_preserving_cursor(self.query_one(DataTable).cursor_row, event.size.width)
        self._apply_switcher_layout(event.size.width)

    def _render_legend(self, width: int | None = None) -> None:
        """A bold category heading, on its own line, then that category's own
        wrapped pairs below it -- real bug caught live, 2026-09-16, direct
        question ("why are snow showers and thunderstorm a separate row in
        the screenshot?"): an earlier version put the heading on the *same*
        line as the first wrapped chunk, but `_wrap_legend()` packed that
        chunk against the full available width with no idea a heading would
        also share the line -- the combined line then ran wider than the
        `#legend` widget's own real width, so Rich's own rendering silently
        wrapped it a *second* time at an arbitrary point, splitting a pair
        (❄️ from its own "snow" label) across two visual lines despite
        `_wrap_legend()`'s entire job being to never let that happen. Putting
        the heading on its own line means `_wrap_legend()` always gets the
        real full width for the pairs alone, so nothing it packs can ever
        overflow the widget a second time."""
        w = width if width is not None else self.size.width
        blocks = [
            f"[bold]{i18n.t(label_key)}[/]\n[dim]{_wrap_legend(_legend_pairs(entries), w)}[/]"
            for label_key, entries in OVERVIEW_LEGEND_CATEGORIES
        ]
        self.query_one("#legend", Static).update("\n".join(blocks))

    def refresh_banners(self) -> None:
        """Ported from `DayDetailScreen` 2026-09-15 (direct follow-up: "why
        don't we integrate those missing features into the overview screen" --
        this and `action_refresh()` below were the only two things that still
        genuinely needed that separate screen). `load_unacknowledged_booking_
        changes()` already returns every change across the whole club, not
        scoped to one date — DayDetailScreen just happened to be viewing one
        date already, so its own banner never needed to say which day a
        change was about; here it does (`include_date=True`)."""
        changes = storage.load_unacknowledged_booking_changes(path=self.db_path)
        self.query_one("#banners", Static).update(_render_banner_lines(changes, include_date=True))

    def action_dismiss_banners(self) -> None:
        changes = storage.load_unacknowledged_booking_changes(path=self.db_path)
        storage.acknowledge_booking_changes([change["id"] for change in changes], path=self.db_path)
        self.refresh_banners()

    def action_refresh(self) -> None:
        """`r` -- the same manual "scrape this right now, don't wait for the
        interval" override `DayDetailScreen.action_refresh()` already gives
        for one day, for the whole loaded window instead. Delegates to the
        App (`TeetimeApp.action_force_refresh()`) since the actual scrape
        runs via `_periodic_scrape(force=True)`'s own threaded worker — same
        reason `action_switch()`/`action_edit_settings()` below already
        delegate for their own App-level machinery."""
        self.app.action_force_refresh()

    def _reload(self) -> None:
        """The `_ClubCourseSwitcher` mixin's own hook -- what "reload after a
        club/course switch" means on this particular screen. A genuinely
        different dataset, so any expanded day rows collapse too -- nothing
        expanded from the old club/course would mean anything against the new
        one's dates."""
        self._expanded_dates = set()
        self.load_overview()

    @property
    def db_path(self):
        return _db_path(self.club_id)

    def _config(self) -> dict:
        return _resolved_config(self.club_slug, self.club_id, self.club_name)

    def _display_dates(self, config: dict) -> tuple[list[str], set[str]]:
        """(every date to attempt a row for, the subset of those actually open for
        booking). `overview_days` (config, default 5) is how many day-rows to
        attempt, not a promise that all of them are bookable — a real fetch failure,
        or a club whose page has no date selector at all, means "assume every
        attempted date is open" (the old, pre-2026-09-07 behavior) rather than
        greying out a window this call simply couldn't determine."""
        display_days = config.get("overview_days", 5)
        today = date_cls.fromisoformat(_TODAY())
        dates = [(today + timedelta(days=offset)).isoformat() for offset in range(display_days)]
        try:
            open_dates = set(fetch_available_dates(self.club_id))
        except Exception:  # noqa: BLE001 — see docstring: assume everything attempted is open
            return dates, set(dates)
        return (dates, open_dates) if open_dates else (dates, set(dates))

    def _render_table(
        self, config: dict, dates: list[str], open_dates: set[str], width: int | None = None
    ) -> list[Schedule]:
        """Clear and rebuild `#overview-table` for `dates`/`open_dates`, populating
        `self._row_dates`/`self._row_index` and returning the schedules with real
        slots encountered along the way. Factored out of `load_overview()`
        2026-09-14 (ROADMAP.md's queued "nested/collapsed overview" item) so a
        toggle/confirm/cancel action can rebuild the table in place without also
        re-running `load_overview()`'s own `_initial_date()` cursor placement,
        which would otherwise yank the cursor away from the row just acted on.

        A day whose own schedule has real slots gets an expand/collapse caret
        (▶/▼) prepended to its own first cell; picking it in
        `on_data_table_row_selected()` toggles `self._expanded_dates` and
        inserts that day's own per-slot rows (via `_compute_slot_rows()` — the
        same rendering `DayDetailScreen` uses) directly beneath it, indented.
        That first column reads as "Date/Time" (2026-09-15, direct feedback:
        "the 'day' column should preferably say 'time/date'", corrected the
        same day to "Date/Time" — the right order once it's a date first,
        drilling down to a time only once expanded), not just "Day"
        — it shows the date for a day-summary row but the exact slot time for
        one of its own expanded children, and the header never caught up to
        that dual meaning until now. The other seven columns don't have their
        own header row either (`DataTable` only ever has one header for the
        whole table), so an expanded slot row re-purposes the day row's own
        columns: Occupancy (how full 08:00-20:00 is, in aggregate) becomes
        that one slot's own booked/capacity count; Pick (today's recommended/
        confirmed slot) becomes that slot's own Players. Both are already
        "how full / who's here" columns at the day level, so the slot-level
        meaning underneath reads as a zoom-in on the same idea rather than a
        mismatched relabeling. Occupancy sits right after Wind and before
        Events (2026-09-15, direct feedback: "I would swap arrangement of
        events and occupancy") -- the four weather-ish columns (Condition/
        Temperature/Precipitation/Wind/Occupancy) now read as one contiguous
        group, with Events (which isn't weather at all) and Pick (the actual
        verdict) following after.

        Rows are buffered in `pending_rows` and only actually added to `table`
        at the end, alongside freshly-declared columns (2026-09-14, direct
        feedback: "make better use of the width of the window") -- every
        column gets an explicit width computed from the real cell text this
        call is about to display (`_cell_visible_width()`). This is a full
        rebuild every call rather than a cheaper column-reuse, but it
        sidesteps a real dead end found first: `DataTable.Column.width`/
        `.content_width` are both computed lazily by the table's *own* next
        render pass, not synchronously by add_row()/add_column() -- confirmed
        by two failed attempts to read them (immediately, and even via
        `call_after_refresh()`) that each produced a stretch wildly
        disagreeing with what actually got painted. Computing widths
        ourselves, straight from the cell strings we already hold before they
        ever reach the table, sidesteps that entirely.

        Events/Pick get their own full natural content width, same as every
        other column, *unless* that would overflow `width` (defaults to
        `self.size.width`, but `on_resize()` passes the new size explicitly
        rather than trusting a stale `self.size` mid-resize) -- only then are
        they capped at `_WRAP_CAP_WIDTH` and left to wrap (`height=None`
        below), since both can carry genuinely open-ended text (event/
        tournament names, unplayable-reason sentences, AI reasons) that would
        otherwise force a wide single-line column no matter how long one
        day's content happens to be. Two direct follow-ups got here in turn:
        an earlier version handed any *leftover* width beyond the cap to
        Events unconditionally, to avoid unused blank space on a wide desktop
        terminal -- dropped 2026-09-15 once seen live ("why is the event
        column so wide?"); the fix for that then capped both columns
        unconditionally at *every* width, including ones plenty wide enough
        to show the full content on one line -- narrowed to just the narrow
        case 2026-09-16 ("can you make events/picks columns only wrap up,
        when window is too narrow?")."""
        units = config.get("units", units_module.DEFAULT_UNITS)
        table = self.query_one(DataTable)
        self._row_dates = []
        self._row_index = []

        confirmed_by_date = {
            booking.date: booking
            for booking in storage.load_all_confirmed_bookings(path=self.db_path)
            if booking.course == self.course
        }
        pending_change_dates = {
            change["date"] for change in storage.load_unacknowledged_booking_changes(path=self.db_path)
        }

        schedules: list[Schedule] = []
        pending_rows: list[tuple[str, str, str, str, str, str, str, str]] = []
        for one_date in dates:
            weekday = i18n.t(f"weekday.{date_cls.fromisoformat(one_date).weekday()}")
            # No year (2026-09-15, fitting the whole app on an iPad portrait
            # terminal, ~50 columns): "2026-09-12" was the single biggest
            # contributor to this column's own width, and the exact date is
            # never actually needed at a glance here -- the weekday already
            # disambiguates within the loaded window, and `d` (open full day
            # view) shows the complete ISO date in its own title for anyone
            # who needs it. `one_date` is always `YYYY-MM-DD`, so slicing off
            # its first 5 characters is exactly "MM-DD" -- no reformatting.
            short_date = one_date[5:]
            suffix = f" {i18n.t('overview.today_suffix')}" if one_date == _TODAY() else ""
            day_cell = f"{weekday} {short_date}{suffix}"

            if one_date not in open_dates:
                self._row_dates.append(one_date)
                self._row_index.append((one_date, None))
                pending_rows.append((
                    f"[dim]  {day_cell}[/]",
                    "[dim]—[/]",
                    "[dim]—[/]",
                    "[dim]—[/]",
                    "[dim]—[/]",
                    "[dim]—[/]",
                    "[dim]—[/]",
                    f"[dim]{i18n.t('overview.not_open_yet')}[/]",
                ))
                continue

            schedule = storage.load_latest_schedule(self.course, one_date, path=self.db_path)
            # Drop today's own row entirely once it's past TODAY_HIDDEN_AFTER_HHMM
            # -- direct follow-up, 2026-09-11, refining the very same day's earlier
            # "after sunset" version to a plain fixed clock time instead ("I would
            # prefer that the current day disappears ... whenever it is after
            # 9 pm"). Genuinely different from _initial_date()'s own "every slot's
            # own time has passed" heuristic below (the club's booking hours, not a
            # fixed cutoff), and no longer needs a cached schedule/sun_times to
            # exist at all -- a plain clock comparison, simpler and predictable
            # year-round.
            if one_date == _TODAY() and _NOW_HHMM() > TODAY_HIDDEN_AFTER_HHMM:
                continue
            self._row_dates.append(one_date)
            self._row_index.append((one_date, None))
            can_expand = schedule is not None and bool(schedule.slots)
            if can_expand:
                schedules.append(schedule)
                caret = "▼" if one_date in self._expanded_dates else "▶"
                day_cell = f"{caret} {day_cell}"
                condition_cell = _condition_cell(schedule.weather) or "[dim]—[/]"
                temperature_cell = _temperature_cell(schedule.weather, units) or "[dim]—[/]"
                precipitation_cell = _precipitation_cell(schedule.weather, units) or "[dim]—[/]"
                wind_cell = _wind_cell(schedule.weather, units) or "[dim]—[/]"
                event_cell = _event_cell(schedule) or "[dim]—[/]"
                heat_cell = _heat_strip_markup(schedule)
            else:
                day_cell = f"  {day_cell}"
                condition_cell = "[dim]…[/]"
                temperature_cell = "[dim]…[/]"
                precipitation_cell = "[dim]…[/]"
                wind_cell = "[dim]…[/]"
                event_cell = "[dim]…[/]"
                heat_cell = "[dim]……[/]"
            pick_cell = _day_pick_text(
                schedule, config, confirmed_by_date.get(one_date), one_date in pending_change_dates, self.club_id
            )
            pending_rows.append(
                (day_cell, condition_cell, temperature_cell, precipitation_cell, wind_cell, heat_cell, event_cell, pick_cell)
            )

            if can_expand and one_date in self._expanded_dates:
                recommended_times = _recommended_times_for(schedule, config, self.club_id)
                confirmed = confirmed_by_date.get(one_date)
                for slot_row in _compute_slot_rows(schedule, config, units, one_date, recommended_times, confirmed):
                    self._row_index.append((one_date, slot_row.time))
                    pending_rows.append((
                        f"  {slot_row.time_cell}",
                        slot_row.condition_cell,
                        slot_row.temperature_cell,
                        slot_row.precipitation_cell,
                        slot_row.wind_cell,
                        slot_row.occupancy_cell,
                        slot_row.events_cell,
                        slot_row.players_cell,
                    ))

        headers = [
            i18n.t("table.day"),
            i18n.t("table.condition"),
            _column_header("table.temperature", "temperature", units),
            _column_header("table.precipitation", "precipitation", units),
            _column_header("table.wind", "wind", units),
            i18n.t("table.heat"),
            i18n.t("table.events"),
            i18n.t("table.pick"),
        ]
        column_widths = [_cell_visible_width(header) for header in headers]
        for row in pending_rows:
            for index, cell in enumerate(row):
                column_widths[index] = max(column_widths[index], _cell_visible_width(cell))

        # Events/Pick content is genuinely open-ended (event/tournament names,
        # unplayable-reason sentences, AI reasons) -- only capped (wrapping
        # onto more lines via `height=None` below) once the table's own
        # *natural*, uncapped width wouldn't actually fit. Direct follow-up
        # 2026-09-16 on the original "wrap up" fix: "can you make events/
        # picks columns only wrap up, when window is too narrow?" -- the
        # original fix (2026-09-15, "Events and picks can for sure wrap up")
        # capped both unconditionally, at any width, which then itself drew a
        # complaint once seen on a wide desktop terminal ("why is the event
        # column so wide?" -- answered by *not* stretching it, not by capping
        # it either). Reserves `_TABLE_OVERHEAD` columns of `DataTable`'s own
        # per-column gutter/padding, empirically confirmed elsewhere in this
        # file not to be reflected in any column's own declared width.
        natural_total = sum(column_widths) + _table_overhead(len(headers))
        available = width if width is not None else self.size.width
        if natural_total > available:
            for index in (self._EVENTS_COLUMN_INDEX, self._PICK_COLUMN_INDEX):
                column_widths[index] = min(column_widths[index], _WRAP_CAP_WIDTH)

        table.clear(columns=True)
        for header, width in zip(headers, column_widths):
            table.add_column(header, width=width)
        for row in pending_rows:
            # height=None -- auto-detect the wrapped height instead of a
            # fixed single line, so a capped Events/Pick cell (or a narrow
            # terminal squeezing every column) wraps onto more lines rather
            # than clipping (same feedback as the cap above).
            table.add_row(*row, height=None)

        return schedules

    def load_overview(self) -> None:
        config = self._config()
        dates, open_dates = self._display_dates(config)
        self._cached_dates, self._cached_open_dates = dates, open_dates
        schedules = self._render_table(config, dates, open_dates)
        table = self.query_one(DataTable)

        # Pre-highlight today, unless today's own cached schedule shows every slot
        # already passed -- see _initial_date()'s own docstring (direct feedback,
        # first written for the old "land straight on a day" launch flow, and
        # silently stopped applying to anything once that flow became this overview
        # instead; re-caught live 2026-09-07 the same evening: "why is the TUI still
        # showing today at this time (11:12 PM)?"). Enter still opens whatever row is
        # actually highlighted, same as always -- this only moves where the cursor
        # starts, so a quick glance-and-enter lands somewhere useful late at night
        # without requiring an extra press of `n`/arrow-down first.
        target_date = _initial_date(self.club_id, self.course)
        if target_date in self._row_dates:
            table.move_cursor(row=self._row_dates.index(target_date))

        self._schedules = schedules

    def _rerender_preserving_cursor(self, row: int, width: int | None = None) -> None:
        """Rebuild the table exactly as `load_overview()` does, but keep the
        cursor on physical row `row` (clamped to whatever the new row count
        allows) instead of recomputing `_initial_date()`'s own placement --
        used after a user-initiated expand/collapse or confirm/cancel, where
        yanking the cursor back to "today" would undo the very navigation the
        user just did. See `load_overview()`'s own docstring for the other
        (fresh-open) case, which still wants `_initial_date()`'s placement.

        Reuses `self._cached_dates`/`self._cached_open_dates` instead of
        calling `_display_dates()` again -- see `self._cached_dates`'s own
        docstring for the real lag this avoids; the booking window can't have
        changed between the keypress that triggered this and now, so there's
        nothing to gain from re-fetching it.

        `width` passes `on_resize()`'s own new size through to `_render_table()`
        (which otherwise falls back to `self.size.width` -- stale mid-resize
        by the time that read happens, same reasoning `_render_legend()`
        already documents for its own `width` parameter)."""
        config = self._config()
        schedules = self._render_table(config, self._cached_dates, self._cached_open_dates, width)
        self._schedules = schedules
        table = self.query_one(DataTable)
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """`enter` on a day-summary row expands/collapses it in place; `enter` on
        one of its own expanded slot rows confirms or cancels that exact tee time
        -- the "nested/collapsed overview" redesign (ROADMAP.md, queued
        2026-09-13, scoped 2026-09-14: expand-in-place rows, not a split pane or
        a full accordion rewrite). Replaces the old "always drill into a
        separate day-detail screen" behavior -- that screen was retired
        entirely 2026-09-15 once `x` (banner dismiss) and `r` (force refresh)
        were ported here too (direct follow-up: "why don't we integrate those
        missing features into the overview screen"), the last two things
        expansion alone didn't already cover."""
        if not (0 <= event.cursor_row < len(self._row_index)):
            return
        date, slot_time = self._row_index[event.cursor_row]
        if slot_time is None:
            # Real bug caught live, 2026-09-14: without this guard, `enter` on a
            # day row with no caret at all (no cached schedule yet, or "not open
            # yet") still silently added it to `_expanded_dates` -- invisible at
            # the time (nothing to render), but a real scrape landing for that
            # date later would then render it pre-expanded, never actually asked
            # for. `self._schedules` is exactly the set of dates `_render_table()`
            # judged expandable (`can_expand`), so this mirrors the same caret
            # the user actually saw before pressing enter.
            if any(schedule.date == date for schedule in self._schedules):
                self._toggle_expanded(date, event.cursor_row)
        else:
            self._confirm_or_cancel_slot(date, slot_time, event.cursor_row)

    def _toggle_expanded(self, date: str, row: int) -> None:
        if date in self._expanded_dates:
            self._expanded_dates.discard(date)
        else:
            self._expanded_dates.add(date)
        self._rerender_preserving_cursor(row)

    def _confirm_or_cancel_slot(self, date: str, slot_time: str, row: int) -> None:
        """`enter` on an expanded slot row -- the exact same confirm-or-cancel
        choice `DayDetailScreen.action_confirm()` makes for its own highlighted
        row (see that method's own docstring), just resolving `date`/`slot_time`
        from this row's own `_row_index` entry instead of the single day it's
        scoped to."""
        existing = storage.load_confirmed_booking(self.course, date, path=self.db_path)
        if existing is not None and existing.time is not None and existing.time == slot_time:

            def on_cancel_result(cancelled: bool | None) -> None:
                if cancelled:
                    self._rerender_preserving_cursor(row)

            self.app.push_screen(
                CancelBookingScreen(self.club_id, self.course, date, existing.time), on_cancel_result
            )
            return

        def on_result(confirmed: bool | None) -> None:
            if confirmed:
                self._rerender_preserving_cursor(row)

        default_holes = _holes_from_course_label(self.course)
        self.app.push_screen(
            ConfirmBookingScreen(self.club_id, self.course, date, slot_time, default_holes), on_result
        )

    def action_search(self) -> None:
        # Callback (not push_screen_wait()) since this itself isn't a worker
        # context -- see action_switch()'s own comment on that requirement.
        # Reopens the Actions menu once SearchScreen backs out, since it's
        # only ever reached via that menu now -- see
        # TeetimeApp._reopen_actions_menu()'s own docstring.
        self.app.push_screen(
            SearchScreen(self._schedules, self._config(), self.club_id),
            lambda _result: self.app._reopen_actions_menu(),
        )

    def action_heatmap(self) -> None:
        self.app.push_screen(
            HeatmapScreen(self.club_id, self.course, self._config()),
            lambda _result: self.app._reopen_actions_menu(),
        )

    def action_switch(self) -> None:
        # Same delegation as DayDetailScreen.action_switch() — push_screen_wait()
        # needs to run on the App, see TeetimeApp.action_switch_club_or_course().
        self.app.action_switch_club_or_course()

    def action_edit_settings(self) -> None:
        # Delegates to the App for the same reason action_switch does above —
        # opening SettingsScreen needs push_screen_wait(). See
        # TeetimeApp.action_edit_settings()'s own docstring.
        self.app.action_edit_settings()

    def action_command_palette(self) -> None:
        self.app.action_command_palette()

    def action_quit(self) -> None:
        self.app.exit()


def _time_window_row(label_key: str, base_id: str, current_value: str | None) -> ComposeResult:
    """One label + hour/minute-dropdown-pair row, shared by every time-window field
    on `SearchScreen` below -- the exact same hour/minute `Select` pattern
    settings_screen.py's own `optional_time` fields use (including the
    05:00-21:00 hour range trim, via the shared `HOUR_CHOICES`/`MINUTE_CHOICES`
    imported from there), just built here directly since this screen has a fixed,
    small set of time fields rather than a generic `FIELDS` list to iterate.
    `current_value` is a plain "HH:MM" string or `None` ("not set"), same
    convention as everywhere else in this app that stores a time window."""
    hh, _, mm = (current_value or "").partition(":")
    hour_options = HOUR_CHOICES if hh in {value for _, value in HOUR_CHOICES} else [(hh, hh), *HOUR_CHOICES]
    minute_options = (
        MINUTE_CHOICES if mm in {value for _, value in MINUTE_CHOICES} else [(mm, mm), *MINUTE_CHOICES]
    )
    with Horizontal(classes="field-row"):
        yield Label(i18n.t(label_key), classes="field-label")
        with Horizontal(classes="field-time-group"):
            yield Select(
                hour_options, value=hh, allow_blank=False, compact=True, id=f"{base_id}-hh", classes="time-part"
            )
            yield Static(":", classes="field-time-sep")
            yield Select(
                minute_options, value=mm, allow_blank=False, compact=True, id=f"{base_id}-mm", classes="time-part"
            )


class SearchScreen(Screen[None]):
    """Ad hoc search (ROADMAP.md Phase 4) — "just this once" criteria that don't
    match your saved defaults, added 2026-09-08 once its own backend (`search.py`'s
    hard filters, `recommend.exclude_unplayable()`, `ai_assist.rank_slots()` — all
    already real and fully tested) just needed a screen wired up to it. Pushed
    from `OverviewScreen` via `/`.

    Pre-filled from your saved global availability defaults (edit from there for
    this one case, not type everything from scratch) — same fields, same dropdowns
    (hour range trimmed to 05:00-21:00, buffer in 10-minute steps) as
    `settings_screen.py`'s own, reusing its `HOUR_CHOICES`/`MINUTE_CHOICES`/
    `MIN_OPEN_SPOTS_CHOICES`/`BUFFER_CHOICES` directly for a consistent look and
    the same "can't hold an invalid value" guarantee a dropdown gives over free
    text. A saved value outside a dropdown's presets still loads and stays
    selectable, same generic handling as every dropdown in this app.

    Runs against whatever days `OverviewScreen` already has loaded
    (`self.schedules`, handed in at construction), not a fresh scrape — opening
    this screen, and running a search from it, should both stay instant, same as
    everything else in this app. `recommend.ranked_matches()` is the exact
    three-step pipeline `weekly_picks()` already uses for your saved defaults,
    just handed this screen's own typed-in `SearchCriteria` instead.

    `escape`/`q` both dismiss back to the overview and quit the whole app
    respectively — same convention as `ClubBrowserScreen`/`CoursePickerScreen`
    (screens pushed as part of the main flow, not a standalone-capable task screen
    like `SettingsScreen`), since this screen is reached from, and returns to,
    `OverviewScreen` the same way those are.

    The results table has no per-row Course column (2026-09-13, direct question:
    "why does adhoc search need to mention course, couldn't it be mentioned once
    in the header?") — `self.schedules` is always `OverviewScreen._schedules`,
    itself already filtered to one active course, so every result here shares
    the same one; it joins the Header's own title instead of repeating on every
    row.

    Occupancy/Players/Temperature/Precipitation/Wind columns (2026-09-13, direct
    question: "why does adhoc search not show occupancy, player, or weather
    data?") — a `SlotMatch.slot` already carries `booked`/`capacity`/`players`,
    and the matching `Schedule.weather` is already in `self.schedules`; reuses
    `DayDetailScreen`'s own `_slot_temperature_cell()`/`_slot_precipitation_cell()`/
    `_slot_wind_cell()` directly rather than a second, parallel set of weather
    formatters, so the two screens can't drift on how a number gets displayed.

    `c` confirms the highlighted result (2026-09-13, direct question: "can we
    confirm tee times from adhoc search?") — same `ConfirmBookingScreen` as
    `DayDetailScreen`'s own `c`, pre-filled from the highlighted row's own
    date/course/time (`self._row_matches`, the search equivalent of that
    screen's `_row_times`) rather than whatever date/course happened to be
    active when this screen was opened, since a single search's results can
    span several different days.
    """

    CSS = """
    #search-fields {
        padding: 1 2;
        height: auto;
    }
    .field-row {
        height: 1;
        align: left middle;
    }
    .field-label {
        width: 32;
        content-align: right middle;
        padding-right: 2;
    }
    .field-input {
        width: 20;
    }
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
    #search-results {
        height: 1fr;
        margin: 0 2;
    }
    #search-status {
        padding: 0 2;
        color: $text-muted;
    }
    #buttons {
        padding: 1 2;
        align: right middle;
    }
    """

    BINDINGS = [("c", "confirm", "Confirm tee time"), ("escape", "cancel", "Back"), ("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("c", "binding.confirm"), ("escape", "binding.cancel"), ("q", "binding.quit")]

    def __init__(self, schedules: list[Schedule], config: dict, club_id: str) -> None:
        super().__init__()
        self.schedules = schedules
        self.config = config
        self.club_id = club_id
        # This result's own SlotMatch, in table row order -- lets `c` confirm the
        # highlighted row's exact date/course/time without re-deriving it from
        # display text, same reasoning DayDetailScreen's own `_row_times` already
        # follows for the identical purpose.
        self._row_matches: list[SlotMatch] = []

    def compose(self) -> ComposeResult:
        yield Header()
        availability = self.config.get("availability", {})
        weekday_window = availability.get("weekday_window") or {}
        weekend_window = availability.get("weekend_window") or {}
        with VerticalScroll(id="search-fields"):
            with Horizontal(classes="field-row"):
                yield Label(i18n.t("settings.field.min_open_spots"), classes="field-label")
                min_open_spots = str(availability.get("min_open_spots", 1))
                spots_options = MIN_OPEN_SPOTS_CHOICES
                if min_open_spots not in {value for _, value in spots_options}:
                    spots_options = [(min_open_spots, min_open_spots), *spots_options]
                yield Select(
                    spots_options,
                    value=min_open_spots,
                    allow_blank=False,
                    compact=True,
                    id="search-min-open-spots",
                    classes="field-input",
                )
            yield from _time_window_row("settings.field.weekday_after", "search-weekday-after", weekday_window.get("after"))
            yield from _time_window_row(
                "settings.field.weekday_before", "search-weekday-before", weekday_window.get("before")
            )
            yield from _time_window_row("settings.field.weekend_after", "search-weekend-after", weekend_window.get("after"))
            yield from _time_window_row(
                "settings.field.weekend_before", "search-weekend-before", weekend_window.get("before")
            )
            for label_key, widget_id, direction in (
                ("settings.field.buffer_before_minutes", "search-buffer-before", "before"),
                ("settings.field.buffer_after_minutes", "search-buffer-after", "after"),
            ):
                with Horizontal(classes="field-row"):
                    yield Label(i18n.t(label_key), classes="field-label")
                    current = str(resolve_buffer_minutes(availability, direction, 0))
                    buffer_options = BUFFER_CHOICES
                    if current not in {value for _, value in buffer_options}:
                        buffer_options = [(current, current), *buffer_options]
                    yield Select(
                        buffer_options,
                        value=current,
                        allow_blank=False,
                        compact=True,
                        id=widget_id,
                        classes="field-input",
                    )
        yield DataTable(id="search-results", header_height=2)
        yield Static("", id="search-status")
        with Horizontal(id="buttons"):
            yield Button(i18n.t("button.cancel"), id="cancel")
            yield Button(i18n.t("search.button"), id="run", variant="success")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_mount(self) -> None:
        # Never actually set before this -- found live, dedicated bug hunt
        # (2026-09-10): the mockup's own "Search" screen shows "Search this week"
        # right in the Header, but the real screen just showed the bare app title.
        # The course, once known, joins it here instead of repeating on every
        # result row (2026-09-13, direct question: "why does adhoc search need
        # to mention course, couldn't it be mentioned once in the header?" --
        # `self.schedules` is always OverviewScreen._schedules, itself already
        # filtered to one active course, so a per-row Course column never
        # actually varied within a single search anyway).
        title = i18n.t("search.title")
        if self.schedules:
            title = f"{title} — {self.schedules[0].course}"
        self.title = title
        units = self.config.get("units", units_module.DEFAULT_UNITS)
        table = self.query_one("#search-results", DataTable)
        table.add_column(i18n.t("search.table.date"))
        table.add_column(i18n.t("table.time"))
        table.add_column(i18n.t("table.condition"))
        table.add_column(i18n.t("table.occupancy"))
        # Capped and left to wrap (`height=None` in _run_search()'s own
        # add_row()) rather than sized to full natural content -- same
        # reasoning and same shared cap as OverviewScreen's Events/Pick and
        # DayDetailScreen's Players/Events (direct feedback 2026-09-15,
        # fitting the whole app on an iPad portrait terminal, ~50 columns).
        table.add_column(i18n.t("table.players"), width=_WRAP_CAP_WIDTH)
        table.add_column(_column_header("table.temperature", "temperature", units))
        table.add_column(_column_header("table.precipitation", "precipitation", units))
        table.add_column(_column_header("table.wind", "wind", units))
        table.add_column(i18n.t("search.table.notes"), width=_WRAP_CAP_WIDTH)

    def _time_value(self, base_id: str) -> str | None:
        hh = self.query_one(f"#{base_id}-hh").value
        mm = self.query_one(f"#{base_id}-mm").value
        return f"{hh}:{mm or '00'}" if hh else None

    def _build_criteria(self) -> SearchCriteria:
        weekday_after = self._time_value("search-weekday-after")
        weekday_before = self._time_value("search-weekday-before")
        weekend_after = self._time_value("search-weekend-after")
        weekend_before = self._time_value("search-weekend-before")
        return SearchCriteria(
            min_open_spots=int(self.query_one("#search-min-open-spots").value),
            weekday_window=TimeWindow(after=weekday_after, before=weekday_before)
            if (weekday_after or weekday_before)
            else None,
            weekend_window=TimeWindow(after=weekend_after, before=weekend_before)
            if (weekend_after or weekend_before)
            else None,
            buffer_before_minutes=int(self.query_one("#search-buffer-before").value),
            buffer_after_minutes=int(self.query_one("#search-buffer-after").value),
        )

    def _run_search(self) -> None:
        criteria = self._build_criteria()
        crowd_estimates = _crowd_estimates(self.schedules, self.config, self.club_id)
        matches = recommend.ranked_matches(self.schedules, criteria, self.config, crowd_estimates)
        table = self.query_one("#search-results", DataTable)
        table.clear()
        self._row_matches = []
        status = self.query_one("#search-status", Static)
        if not matches:
            status.update(i18n.t("search.no_matches"))
            return
        status.update("")
        units = self.config.get("units", units_module.DEFAULT_UNITS)
        # Same (date, course) -> Schedule lookup DayDetailScreen's own
        # load_schedule() already does implicitly via storage -- here it's an
        # in-memory match against self.schedules instead, since this screen never
        # re-fetches anything.
        schedule_by_key = {(schedule.date, schedule.course): schedule for schedule in self.schedules}
        for match in matches:
            self._row_matches.append(match)
            weekday = i18n.t(f"weekday.{date_cls.fromisoformat(match.date).weekday()}")
            schedule = schedule_by_key.get((match.date, match.course))
            weather = schedule.weather if schedule is not None else []
            occupancy = f"{match.slot.booked}/{match.slot.capacity}"
            players = ", ".join(match.slot.players) if match.slot.players else ""
            table.add_row(
                f"{weekday} {match.date}",
                match.slot.time,
                _slot_condition_cell(weather, match.slot.time),
                occupancy,
                players,
                _slot_temperature_cell(weather, match.slot.time, units),
                _slot_precipitation_cell(weather, match.slot.time, units),
                _slot_wind_cell(weather, match.slot.time, units),
                ", ".join(match.reasons),
                height=None,  # wrap Players/Notes instead of clipping -- see their capped width above
            )

    def action_confirm(self) -> None:
        table = self.query_one("#search-results", DataTable)
        if not (0 <= table.cursor_row < len(self._row_matches)):
            return  # no results yet, or the "no matches" placeholder state
        match = self._row_matches[table.cursor_row]

        def on_result(confirmed: bool | None) -> None:
            if confirmed:
                self.query_one("#search-status", Static).update(i18n.t("confirm.confirmed"))

        default_holes = _holes_from_course_label(match.course)
        self.app.push_screen(
            ConfirmBookingScreen(self.club_id, match.course, match.date, match.slot.time, default_holes),
            on_result,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()
            return
        if event.button.id == "run":
            self._run_search()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_quit(self) -> None:
        self.app.exit()


# --- HeatmapScreen (ROADMAP.md Phase 5) -- crowd-heatmap readiness, added 2026-09-08.
# analytics.crowd_heatmap()/heatmap_readiness() are pure and already tested; the two
# helpers below are the first thing in the running app to actually read a club's own
# `calendar.country_code`/`calendar.vacation_ranges` and call
# calendar_context.fetch_public_holidays() -- calendar_context.py has existed, fully
# implemented and tested, since Phase 2, but nothing ever wired it in until this
# screen needed it. ------------------------------------------------------------------


def _holidays_for_club(config: dict) -> list[str]:
    """This year's public holidays for a club's configured `calendar.country_code`,
    via the free Nager.Date API (calendar_context.fetch_public_holidays()). Empty
    list — not an error — with no country_code configured, or if the fetch fails;
    day-type classification still works with just tournament/weekend/workday in that
    case, the same graceful-degradation every other optional-config feature here
    already follows (e.g. `_location_for_club()`'s own None-on-failure)."""
    country_code = config.get("calendar", {}).get("country_code")
    if not country_code:
        return []
    try:
        return calendar_context.fetch_public_holidays(country_code, date_cls.fromisoformat(_TODAY()).year)
    except Exception:
        return []


def _vacation_ranges_for_club(config: dict) -> list[DateRange]:
    """A club's hand-entered `calendar.vacation_ranges` (see clubs/club.example.yaml)
    as real DateRange objects, ready for calendar_context.classify_day(). Empty list
    with nothing configured, same as _holidays_for_club()."""
    ranges = config.get("calendar", {}).get("vacation_ranges") or []
    return [DateRange(start=r["start"], end=r["end"], label=r.get("label", "")) for r in ranges]


def _readiness_status_text(stats: dict) -> str:
    """One of "no data yet" / "collecting" / "N/M hours ready" / "ready", from one
    day-type's own heatmap_readiness() entry."""
    seen, ready = stats["hours_seen"], stats["hours_ready"]
    if seen == 0:
        return i18n.t("heatmap.status.no_data")
    if ready == 0:
        return i18n.t("heatmap.status.collecting", seen=seen)
    if ready < seen:
        return i18n.t("heatmap.status.partial", ready=ready, seen=seen)
    return i18n.t("heatmap.status.ready", ready=ready, seen=seen)


def _heatmap_cell_style(average: float) -> str:
    """Same three fill-ratio thresholds as _heat_strip_blocks() -- one shared visual
    language for "how full" across both screens."""
    if average >= 1.0:
        return "full"
    if average >= 0.5:
        return "mid"
    return "open"


def _heatmap_preview_lines(keys: list[str], label_of, group: dict, readiness_group: dict) -> list[str]:
    """One line per key (a weekday or a special day type) with at least one ready
    hour: its label, then a colored block per ready hour
    (samples >= analytics.MIN_SAMPLES_FOR_PREDICTION), sorted by hour -- an hour
    that's merely *seen* but not yet ready is left out entirely rather than shown
    with a misleadingly thin sample. Shared helper so _heatmap_preview_markup() can
    run the same logic over both the by_weekday and special_days groups."""
    lines = []
    for key in keys:
        if readiness_group[key]["hours_ready"] == 0:
            continue
        hours = group.get(key, {})
        ready_hours = sorted(
            hour for hour, bucket in hours.items() if bucket["samples"] >= analytics.MIN_SAMPLES_FOR_PREDICTION
        )
        blocks = " ".join(
            f"{hour} [{_HEAT_BLOCK_STYLES[_heatmap_cell_style(hours[hour]['average'])]}]■[/]"
            for hour in ready_hours
        )
        lines.append(f"{label_of(key)}: {blocks}")
    return lines


def _heatmap_preview_markup(heatmap: dict, readiness: dict) -> str:
    """Weekdays first (in calendar_context.WEEKDAYS order), then special day types --
    i18n.t("heatmap.no_preview") once nothing anywhere is ready yet, the ordinary
    state for a brand-new install, not an error to work around."""
    lines = _heatmap_preview_lines(
        calendar_context.WEEKDAYS,
        lambda weekday: i18n.t(f"heatmap.weekday.{weekday.lower()}"),
        heatmap.get("by_weekday", {}),
        readiness["by_weekday"],
    )
    lines += _heatmap_preview_lines(
        calendar_context.SPECIAL_DAY_TYPES,
        lambda day_type: i18n.t(f"heatmap.day_type.{day_type}"),
        heatmap.get("special_days", {}),
        readiness["special_days"],
    )
    return "\n".join(lines) if lines else i18n.t("heatmap.no_preview")


class HeatmapScreen(Screen[None]):
    """Phase 5's crowd heatmap — currently a data-readiness view, not the colored grid
    a "heatmap" name might suggest, per direct request (2026-09-08): "Can we still
    start building the UI for the heat map? We need a menu to track how much data has
    been collected, and how much is still needed to be functional." Building the full
    grid first would have meant showing an almost-empty one — every real club here is
    at most a couple of days into accumulating history — so this screen leads with the
    actually-useful question right now: how close each weekday/day type is to usable.

    Two tables, mirroring `analytics.crowd_heatmap()`'s own split (reworked
    2026-09-09 to match the original signed-off mockup — see that function's
    docstring for the mismatch this fixes): "By weekday" (one row per
    `calendar_context.WEEKDAYS`, Sun-Sat) and "Special days" (one row per
    `calendar_context.SPECIAL_DAY_TYPES`: tournament/public_holiday/vacation,
    compared only against other days of their own kind). Every row is always shown
    even at zero samples — a club with no `calendar.country_code`/
    `calendar.vacation_ranges` configured correctly shows 0 forever for
    "public_holiday"/"vacation", which is itself useful information (that
    classification simply can't happen yet), not a row to hide. "Ready" reuses
    `analytics.MIN_SAMPLES_FOR_PREDICTION` — the same bar `predict_crowding()`
    already uses to trust a bucket, not a second, separately-tuned threshold invented
    just for this display.

    Below both tables: a compact colored preview (reusing the overview's own
    heat-strip green/yellow/bold-red thresholds — see `_HEAT_BLOCK_STYLES`) for any
    weekday or special day type that already has at least one ready hour. Empty on
    every real club here today (see above), but the rendering path itself is real and
    tested against synthetic data, not a placeholder left for later — it simply has
    nothing to show yet."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("q", "quit", "Quit"),
    ]
    _FOOTER_BINDINGS = [
        ("escape", "binding.cancel"),
        ("q", "binding.quit"),
    ]

    def __init__(self, club_id: str, course: str, config: dict) -> None:
        super().__init__()
        self.club_id = club_id
        self.course = course
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="weekday-title")
        yield DataTable(id="weekday-table")
        yield Static("", id="special-title")
        yield DataTable(id="special-table")
        yield Static("", id="threshold-note")
        yield Static("", id="preview-title")
        yield Static("", id="preview")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_mount(self) -> None:
        self.title = i18n.t("heatmap.title", course=self.course)

        self.query_one("#weekday-title", Static).update(i18n.t("heatmap.section.by_weekday"))
        weekday_table = self.query_one("#weekday-table", DataTable)
        weekday_table.add_columns(
            i18n.t("heatmap.column.weekday"),
            i18n.t("heatmap.column.hours_seen"),
            i18n.t("heatmap.column.hours_ready"),
            i18n.t("heatmap.column.samples"),
            i18n.t("heatmap.column.status"),
        )

        self.query_one("#special-title", Static).update(i18n.t("heatmap.section.special_days"))
        special_table = self.query_one("#special-table", DataTable)
        special_table.add_columns(
            i18n.t("heatmap.column.day_type"),
            i18n.t("heatmap.column.hours_seen"),
            i18n.t("heatmap.column.hours_ready"),
            i18n.t("heatmap.column.samples"),
            i18n.t("heatmap.column.status"),
        )

        self.query_one("#threshold-note", Static).update(
            i18n.t("heatmap.threshold_note", min=analytics.MIN_SAMPLES_FOR_PREDICTION)
        )
        self.load_readiness()

    def load_readiness(self) -> None:
        holidays = _holidays_for_club(self.config)
        vacation_ranges = _vacation_ranges_for_club(self.config)
        heatmap = analytics.crowd_heatmap(self.course, holidays, vacation_ranges, path=_db_path(self.club_id))
        readiness = analytics.heatmap_readiness(heatmap)

        weekday_table = self.query_one("#weekday-table", DataTable)
        weekday_table.clear()
        for weekday in calendar_context.WEEKDAYS:
            stats = readiness["by_weekday"][weekday]
            weekday_table.add_row(
                i18n.t(f"heatmap.weekday.{weekday.lower()}"),
                str(stats["hours_seen"]),
                str(stats["hours_ready"]),
                str(stats["total_samples"]),
                _readiness_status_text(stats),
            )

        special_table = self.query_one("#special-table", DataTable)
        special_table.clear()
        for day_type in calendar_context.SPECIAL_DAY_TYPES:
            stats = readiness["special_days"][day_type]
            special_table.add_row(
                i18n.t(f"heatmap.day_type.{day_type}"),
                str(stats["hours_seen"]),
                str(stats["hours_ready"]),
                str(stats["total_samples"]),
                _readiness_status_text(stats),
            )

        self.query_one("#preview-title", Static).update(i18n.t("heatmap.preview_title"))
        self.query_one("#preview", Static).update(_heatmap_preview_markup(heatmap, readiness))

    def action_back(self) -> None:
        # self.dismiss(), not self.app.pop_screen() directly (the only screen
        # in this app that used to take that shortcut) -- push_screen()'s own
        # result callback only fires via dismiss(); pop_screen() called
        # straight from here discards it unfired (confirmed straight from
        # Textual's own source: Screen.dismiss() invokes the callback itself
        # before calling pop_screen(), which on its own just drops it). Direct
        # feedback needed this fixed 2026-09-16 once action_heatmap() started
        # relying on that callback to reopen the Actions menu on the way out.
        self.dismiss()

    def action_quit(self) -> None:
        self.app.exit()


class _OrderedSystemCommandsProvider(SystemCommandsProvider):
    """`Provider.discover()`'s own default (Textual's `SystemCommandsProvider`,
    the base class here) re-sorts every command *alphabetically by title*
    whenever the palette's search box is empty -- confirmed straight from its
    own source (`sorted(..., key=lambda command: command[0])`), which is also
    why re-ordering `get_system_commands()`'s own `yield` sequence alone
    never actually changed what a first-time `t` press showed: direct
    feedback 2026-09-16, "can you make logical arrangement of entries in
    actions screen?" -- the empty-search view was always A-Z regardless.
    Overriding just `discover()` to preserve `get_system_commands()`'s own
    yield order instead is the only way to actually control that; `search()`
    (typing a query) is untouched, since Textual's own fuzzy-match ranking
    there already orders by match quality, not alphabetically, and reordering
    an active search's own results was never the ask."""

    async def discover(self):
        for name, help_text, callback, discover in self.app.get_system_commands(self.screen):
            if discover:
                yield DiscoveryHit(name, callback, help=help_text)


# Maps each of Textual's own built-in system commands -- fixed English
# (title, help) pairs hardcoded in `App.get_system_commands()`'s own base
# implementation -- to this app's translated equivalent, plus the fixed sort
# key `TeetimeApp.get_system_commands()` uses to place it within the
# "logical" grouping direct feedback 2026-09-16 asked for: this app's own
# screen actions first (yielded ahead of this dict entirely -- most likely
# what `t` was actually pressed for), Language next (how the UI itself
# reads), then these -- Theme/Keys/Minimize-or-Maximize/Screenshot, Quit
# last, a common app convention rather than one specific to this app.
# Translating these closes a gap the module docstring used to call out as
# deliberately left alone ("Textual's own built-in command-palette entries
# ... stay in whatever language Textual itself ships them in") -- direct
# same-day follow-up: "can you please translate everything in actions
# screen?"
_BASE_COMMAND_TRANSLATIONS: dict[tuple[str, str], tuple[int, str, str]] = {
    ("Theme", "Change the current theme"): (10, "binding.theme", "command.theme_description"),
    ("Keys", "Show help for the focused widget and a summary of available keys"): (
        11,
        "binding.keys",
        "command.show_help_description",
    ),
    ("Keys", "Hide the keys and widget help panel"): (11, "binding.keys", "command.hide_help_description"),
    ("Minimize", "Minimize the widget and restore to normal size"): (
        12,
        "binding.minimize",
        "command.minimize_description",
    ),
    ("Maximize", "Maximize the focused widget"): (12, "binding.maximize", "command.maximize_description"),
    ("Screenshot", "Save an SVG 'screenshot' of the current screen"): (
        13,
        "binding.screenshot",
        "command.screenshot_description",
    ),
    ("Quit", "Quit the application as soon as possible"): (99, "binding.quit", "command.quit_description"),
}


class TeetimeApp(App[None]):
    """Club/course selection, then the day-detail screen. See module docstring."""

    TITLE = "teetime-monitor"
    # Swaps in _OrderedSystemCommandsProvider above instead of Textual's own
    # default SystemCommandsProvider -- see that class's own docstring for why.
    COMMANDS = {_OrderedSystemCommandsProvider}

    def __init__(self) -> None:
        super().__init__()
        # Shows in the Header's subtitle on every screen, always, not gated behind
        # a flag or a separate "about" screen -- see _version()'s own docstring for
        # the brew-launcher precedent this matches. Set here rather than as a
        # `SUB_TITLE` class attribute so it's read fresh per instance (mockable in
        # tests) instead of frozen once at import time.
        self.sub_title = f"v{_version()}"
        # Display names for clubs picked from the directory, so the tee sheet's title
        # can say "Golfclub Domäne Musterhausen e.V." rather than a bare numeric id for
        # a club that isn't saved and therefore has no slug to show instead.
        self._club_names: dict[str, str] = {}
        # A message from a failed/empty club pick, shown on the club list it sends the
        # user back to (there's no other screen to put it on at that point). NOT named
        # `_pending_message`: that's an existing attribute on Textual's own MessagePump
        # (the one-message peek buffer), and shadowing it with a plain string breaks
        # every screen's message loop with a bare AttributeError deep inside Textual --
        # the same collision class as the `_auto_refresh` one documented above.
        self._club_list_message: str = ""

    def on_mount(self) -> None:
        theme_module.apply_theme(self)
        i18n.apply_language()
        self.run_worker(self._start(), exclusive=True)

    def watch_theme(self, theme_name: str) -> None:
        """Persist whenever the theme changes — via the command palette, or the `t`
        binding that opens it — so the choice survives to the next launch. Reactive
        watch method, called by Textual itself on every `self.theme` change,
        including the initial one from `apply_theme()` above; harmless to
        re-persist the same value on startup."""
        theme_module.save_theme(theme_module.to_logical_name(theme_name))

    def get_system_commands(self, screen: Screen):
        """Textual's own command palette, extended with this app's screen-
        specific actions -- direct question 2026-09-15: "Can commands and
        settings be combined in one menu?" Until then this only ever knew
        about Theme/Quit/Keys (Textual's own base commands) plus the
        language-switch entry below; every other action (Settings, Switch
        club/course, Search, Heatmap) lived solely on its own dedicated key
        binding, invisible to `t`. First added alongside those still-live key
        bindings, deliberately kept as a faster route for whoever already
        knew them — until direct follow-up 2026-09-16 pointed out that
        wasn't actually "integrated" at all: "I thought settings and commands
        were now integrated into one menu. Why do we still have a key bind
        for commands?" `OverviewScreen.BINDINGS` no longer binds `/`/`h`/`s`/
        `e` at all; this (renamed Actions — see `binding.commands`) is now
        the *only* way to reach any of the four. Each entry still just calls
        the exact same `action_*` method its key binding used to call
        directly.

        Yields this app's own screen actions first, Language next, then
        Textual's own base commands (translated + regrouped via
        `_BASE_COMMAND_TRANSLATIONS` — see that dict's own docstring for the
        full ordering rationale and the "translate everything" follow-up this
        closes) — same-day direct follow-up: "can you make logical
        arrangement of entries in actions screen?" Yield order alone doesn't
        actually control the empty-search palette view though —
        `SystemCommandsProvider.discover()` (Textual's default) re-sorts
        every command alphabetically by title regardless of yield order,
        confirmed straight from its own source; `TeetimeApp.COMMANDS` swaps
        in `_OrderedSystemCommandsProvider` instead, which doesn't."""
        if isinstance(screen, OverviewScreen):
            yield SystemCommand(
                i18n.t("binding.switch"), i18n.t("command.switch_description"), screen.action_switch
            )
            yield SystemCommand(
                i18n.t("binding.search"), i18n.t("command.search_description"), screen.action_search
            )
            yield SystemCommand(
                i18n.t("binding.heatmap"), i18n.t("command.heatmap_description"), screen.action_heatmap
            )
            yield SystemCommand(
                i18n.t("binding.settings"), i18n.t("command.settings_description"), screen.action_edit_settings
            )

        current = i18n.get_language()
        other = i18n.other_language(current)
        yield SystemCommand(
            i18n.t("command.language_title", other=i18n.LANGUAGE_LABELS[other]),
            i18n.t("command.language_description", current=i18n.LANGUAGE_LABELS[current]),
            self.action_switch_language,
        )

        base_commands: list[tuple[int, SystemCommand]] = []
        for command in super().get_system_commands(screen):
            mapped = _BASE_COMMAND_TRANSLATIONS.get((command.title, command.help))
            if mapped is None:
                # A future Textual base command this app doesn't know to
                # translate/reorder yet -- passed through untouched rather
                # than silently dropped.
                yield command
                continue
            order, title_key, help_key = mapped
            base_commands.append((
                order,
                SystemCommand(i18n.t(title_key), i18n.t(help_key), command.callback, command.discover),
            ))
        for _, command in sorted(base_commands, key=lambda pair: pair[0]):
            yield command

    def action_switch_language(self) -> None:
        new_lang = i18n.other_language(i18n.get_language())
        i18n.set_language(new_lang)
        i18n.save_language(new_lang)
        self._rebuild_current_screen()

    def _reopen_actions_menu(self) -> None:
        """Reopens the Actions menu (`t`) once a screen it opened (Settings,
        Search, Heatmap, or Find a club's `ClubBrowserScreen`) backs out --
        direct feedback 2026-09-16: "can you make ESC return to actions
        screen when accessing entries from actions screen?" Those four are
        the *only* way any of them are reached at all now (their own direct
        keys came out the same day, see `get_system_commands()`'s own
        docstring), so backing all the way out used to always land bare on
        `OverviewScreen`, skipping straight past the very menu that opened
        them — one extra `escape` now gets from there back to `OverviewScreen`
        itself, same as it always did.

        Deferred via `call_after_refresh()`, not called directly, since each
        caller's own screen-pop (`dismiss()`, or `_rebuild_current_screen()`'s
        own pop+push pair for Settings specifically) hasn't necessarily
        finished landing back on `OverviewScreen` yet at the exact moment its
        own callback/continuation runs — opening the palette only once that
        settles avoids racing it."""
        self.call_after_refresh(self.action_command_palette)

    def _rebuild_current_screen(self) -> None:
        """Replace the current screen with a fresh instance of itself so every label,
        table header, and status message re-renders immediately — simpler and more
        reliable than a partial recompose that would also need to manually re-run
        load_overview() by hand. A no-op for anything else (e.g. mid-picker when
        switching language), since those screens are transient enough that the next
        one shown will already reflect the change, and this app deliberately doesn't
        chase every transient screen's live re-render (see module docstring).

        Originally handled both `DayDetailScreen` and `OverviewScreen` (renamed from
        `_rebuild_day_detail_screen` 2026-09-07 once a second screen needed the same
        treatment); back down to just `OverviewScreen` 2026-09-15 once
        `DayDetailScreen` itself was retired (see that class's own removal note in
        ROADMAP.md).

        Originally just the language-switch helper; reused as-is by
        `_do_edit_settings()` too (2026-09-13, once a units change also needed a full
        header rebuild, not just a row-content reload) — a table's own column
        headers, unlike its rows, are only ever set once in `on_mount()`, so nothing
        short of a fresh instance actually picks up a changed unit label."""
        screen = self.screen
        if not isinstance(screen, OverviewScreen):
            return
        replacement = OverviewScreen(screen.club_id, screen.club_slug, screen.course, club_name=screen.club_name)
        self.pop_screen()
        self.push_screen(replacement)

    async def _pick_course(
        self, club_id: str, config: dict, always_ask: bool, allow_picker: bool = True
    ) -> str | None:
        """This club's own course list, fetched live (see scraper.fetch_course_aliases),
        reduced to a single choice. Returns `""` to mean "the club has no tee sheet"
        and `None` to mean "backed out / couldn't fetch", so callers can tell those two
        genuinely different outcomes apart — one is a fact about the club, the other is
        a transient failure or a deliberate cancel.

        `always_ask` is what separates the two launch-flow callers: launching should
        be fast and mostly automatic (honor `default_course`), while explicitly
        asking to switch (from the old, now-retired `DayDetailScreen`'s own picker
        flow) meant actively choosing was the whole point.

        `allow_picker=False` (added 2026-09-16, direct follow-up: "if a course
        picker is not necessary, then remove it from the 'find a club' screen.
        Course picker is anyway implemented in overview screen") goes one step
        further than `always_ask` ever did on its own: never push
        `CoursePickerScreen` at all, even for a club with several courses and no
        saved default, falling back to the first one exactly the way the inline
        club-select dropdown's own `_switch_club()` already does. Only
        `_do_switch_club_or_course()` (`s`, "Find a club") passes this -- the
        initial launch flow still shows the picker for a genuinely ambiguous
        club, since a first-time pick deserves an active choice the same way
        `always_ask` already covers for that flow specifically."""
        status = None
        if isinstance(self.screen, OverviewScreen):
            status = self.screen.query_one("#status", Static)
        try:
            courses = list(fetch_course_aliases(club_id))
        except NoTeeSheetError:
            message = i18n.t("app.no_tee_sheet", club_id=club_id)
            if status is not None:
                status.update(message)
            else:
                self._club_list_message = message
            return ""
        except Exception as exc:  # noqa: BLE001 — a live fetch can genuinely fail
            # (no network, site down, a wrong club id) and shouldn't crash the app.
            message = i18n.t("app.course_fetch_failed", error=exc)
            if status is not None:
                status.update(message)
            else:
                self._club_list_message = message
            return None

        default_course = config.get("default_course")
        if not always_ask and default_course in courses:
            return default_course
        if len(courses) == 1 or not allow_picker:
            return courses[0]  # nothing to choose between, or told not to ask at all
        return await self.push_screen_wait(CoursePickerScreen(courses))

    async def _open_club(self, club_id: str, always_ask_course: bool, allow_course_picker: bool = True) -> bool:
        """Take a chosen club id all the way to its multi-day overview. True if an
        `OverviewScreen` was actually opened.

        The club's saved config is looked up *from* its id rather than the other way
        round (`club_config.slug_for_club_id()`) — since the 2026-09-07 favorites
        rework a club reached from the directory usually has no saved file at all, and
        that's a normal state: it just means empty config and all the existing
        per-setting fallbacks.

        Pops back to the app's own base screen first, however deep the current stack
        is -- so switching clubs never leaves a stale screen buried underneath the
        new one. `allow_course_picker` just threads through to `_pick_course()`'s
        own identically-named parameter -- see its docstring."""
        slug = club_config.slug_for_club_id(club_id)
        config = club_config.load_club_config(slug) if slug else {}
        course = await self._pick_course(
            club_id, config, always_ask=always_ask_course, allow_picker=allow_course_picker
        )
        if not course:
            return False

        replacement = OverviewScreen(club_id, slug, course, club_name=self._club_names.get(club_id, ""))
        while len(self.screen_stack) > 1:
            self.pop_screen()
        await self.push_screen(replacement)
        self._club_slug = slug
        # `config` alone is {} for a club visited without saving it (no clubs/*.yaml
        # to read `club_id` back out of), and `scrape_due_for_club()` needs `club_id`
        # in the config it's handed — without it, it silently prints "no club_id set,
        # skipping" and does nothing at all, on open and on every timer tick, for as
        # long as this club stays active. Caught live 2026-09-07 ("I selected a
        # random club... the tee times don't automatically refresh, I had to hit
        # 'r'"): auto-refresh was never running for any unsaved club, the whole point
        # of the same-day favorites rework. `club_id` is always known here directly
        # (the function's own argument), so it's merged in regardless of whether the
        # rest of `config` came from a real file or not.
        self._club_config = {**config, "club_id": club_id}
        # Remembered so the *next* launch can skip both pickers entirely -- see
        # global_preferences.load_last_active_club()'s own docstring. Covers both
        # the initial launch flow and the explicit `s`-to-switch flow, since both
        # funnel through this same function.
        global_preferences.save_last_active_club(club_id, slug, course)
        return True

    async def _start(self) -> None:
        """Open straight into "pick a club" — no saved club required (2026-09-07,
        direct feedback that having to save a club before looking at it was backwards;
        see `ClubBrowserScreen`). `allow_cancel=False` because this is the home screen
        at launch: there's nothing behind it to go back to, so `escape` shouldn't drop
        the user onto a blank app.

        `CredentialsScreen` shows first, before any of that, whenever no login is
        configured at all — added 2026-09-10, direct follow-up to wiring it into
        `ClubBrowserScreen`'s own `r`/`l`: "I want the login screen to appear first,
        whenever you don't have a login." Checked once here, not on every loop
        iteration below (a club with no tee sheet or a cancelled course picker sends
        this loop back to `ClubBrowserScreen` again, and re-showing credentials on
        every one of those retries would be its own new annoyance). Still entirely
        skippable — `escape`/Cancel dismiss it same as anywhere else it's pushed —
        since real functionality here (typing a club id directly, favorites, the tee
        sheet itself) never needed a login to begin with; this is a faster path to
        set one up before ever hitting the point where you'd actually need it
        (searching the full directory, or reading "My Reservations"), not a new
        requirement to use the app at all.

        Deliberately `club_directory.credentials_configured()` here, not
        `any_credentials()` — real bug found live, 2026-09-10, direct report ("why
        can't I login... why do I need to hit r after login"): `any_credentials()`
        also requires an existing favorited club to pair the credentials with, which
        a genuinely fresh install (exactly this check's own case) never has. That
        made this screen reappear (or `ClubBrowserScreen`'s own directory refresh
        keep saying "needs a login") every single time, regardless of how many times
        real, correct credentials were saved — see `credentials_configured()`'s own
        docstring for the full detail.

        Tries to resume straight into the last-used club/course first (2026-09-10,
        see `_resume_last_active()`'s own docstring) — both pickers below are a
        fallback for when that's missing or turns out stale, not the default path
        for a returning user any more."""
        self._periodic_scrape_running = False
        if not club_directory.credentials_configured():
            # verify_against_club_id: usually None here (this exact check only ever
            # fires when there's no login configured yet, but a club could already be
            # favorited without one -- e.g. browsed and favorited before ever setting
            # up credentials -- so still worth trying for real verification feedback
            # rather than assuming it's always the true-first-launch case).
            await self.push_screen_wait(CredentialsScreen(verify_against_club_id=_any_favorite_club_id()))

        last_active = global_preferences.load_last_active_club()
        if last_active is not None and await self._resume_last_active(last_active):
            self._periodic_scrape()
            self.set_interval(AUTO_REFRESH_INTERVAL_SECONDS, self._periodic_scrape)
            return

        while True:
            club_id = await self.push_screen_wait(
                ClubBrowserScreen(allow_cancel=False, initial_status=self._club_list_message)
            )
            self._club_list_message = ""
            if club_id is None:
                self.exit()
                return
            if await self._open_club(club_id, always_ask_course=False):
                break
            # A club with no tee sheet, a cancelled course picker, or a failed fetch —
            # go back to the club list with the reason shown, rather than exiting the
            # whole app over one bad pick.
        self._periodic_scrape()
        self.set_interval(AUTO_REFRESH_INTERVAL_SECONDS, self._periodic_scrape)

    async def _resume_last_active(self, last_active: dict) -> bool:
        """Jump straight into the remembered club/course from a previous session,
        skipping both pickers entirely — added 2026-09-10, direct feedback: "when
        you launch teetime-monitor you are greeted with which club to select, then
        which course. I think this is redundant since you can now select club and
        courses from the overview." Once `OverviewScreen`'s own inline switcher
        (2026-09-09) already covers "change club/course without leaving the
        overview," asking again at every single launch — even a returning user
        opening the exact same club as always — stopped serving a purpose; `s`
        still opens the full picker flow for genuinely finding something new (see
        `_do_switch_club_or_course()`'s own docstring).

        Returns `False` (falls back to the normal picker flow in `_start()`) if the
        remembered course no longer exists on this club's real, live course list —
        renamed, or the club's own lineup changed — or the live fetch itself fails
        outright. A stale remembered choice should degrade to asking again, the
        same way any other live-fetch failure elsewhere in this app does, not
        silently open onto a course that doesn't exist any more."""
        club_id = last_active["club_id"]
        slug = last_active.get("slug")
        course = last_active["course"]
        # A missing file here is a real, reachable case, not just theoretical --
        # found live 2026-09-11: the remembered slug in ~/.config/teetime-monitor/config
        # survives across whatever directory teetime-monitor happens to be launched
        # from (see user_config.py), but clubs/*.yaml itself is deliberately
        # cwd-relative (see this module's own docstring, "reads its own state... from
        # whatever directory you run it in"), so a remembered club whose file lives in
        # a different launch directory's clubs/ folder reads as plain "missing" here.
        # Degrades to an empty config rather than aborting the resume entirely --
        # same fallback `_resolved_config()` already uses for a load_club_config()
        # miss -- since the live fetch_course_aliases() check just below is what
        # actually decides whether this remembered club/course is still good.
        try:
            config = club_config.load_club_config(slug) if slug else {}
        except FileNotFoundError:
            config = {}
        try:
            courses = list(fetch_course_aliases(club_id))
        except Exception:  # noqa: BLE001 — any live-fetch failure just means "ask instead"
            return False
        if course not in courses:
            return False
        replacement = OverviewScreen(club_id, slug, course, club_name=self._club_names.get(club_id, ""))
        await self.push_screen(replacement)
        self._club_slug = slug
        self._club_config = {**config, "club_id": club_id}
        return True

    def action_switch_club_or_course(self) -> None:
        """Re-open the club/course pickers on demand — direct feedback 2026-09-07:
        "how can i switch to a different course from the time schedule menu? It is
        somehow not possible to return to the previous menus like choosing the
        course or login." Bound to `s` on `DayDetailScreen` (see that class's own
        `action_switch()`, which delegates here since the actual work needs
        `push_screen_wait()`, which lives on the App).

        Runs the real work in its own worker (`run_worker(..., exclusive=True)`,
        same as `_start()`) rather than directly here — `push_screen_wait()` requires
        an active Textual worker context to await from (confirmed empirically: a
        plain `async def` action method dispatched straight from a keybinding isn't
        one, and raises `NoActiveWorker` the moment it's awaited)."""
        self.run_worker(self._do_switch_club_or_course(), exclusive=True, group="switch")

    async def _do_switch_club_or_course(self) -> None:
        """The actual picker flow for `action_switch_club_or_course()` above — the same
        club browser the app launches into, so switching mid-session and choosing at
        launch behave identically (including favoriting, searching, and jumping to a
        club by id).

        Never shows a course picker at all any more (2026-09-11, direct follow-up:
        "when you go to the club selector by hitting s, it still asks you to select
        a course. This seems redundant" — first fixed only for the has-a-saved-
        default case; 2026-09-16, direct follow-up on the still-remaining
        genuinely-ambiguous case: "if a course picker is not necessary, then remove
        it from the 'find a club' screen. Course picker is anyway implemented in
        overview screen"): `OverviewScreen`'s own inline course selector already
        makes changing course trivial without any picker, so forcing one here,
        even onto a club with several courses and no saved default, stopped
        serving a purpose either way -- `_open_club(..., allow_course_picker=False)`
        falls back to the club's first course instead (see `_pick_course()`'s own
        docstring), the exact same fallback the inline club-select dropdown's own
        `_switch_club()` already used. Backing out of the club browser itself still
        leaves the current schedule exactly as it was; nothing is popped or
        replaced until a club is actually settled. Backing out (escape/`q`)
        reopens the Actions menu rather than dropping straight back to
        `OverviewScreen` -- direct feedback 2026-09-16: "can you make ESC
        return to actions screen when accessing entries from actions
        screen?" (see `_reopen_actions_menu()`'s own docstring). Picking a
        club instead is a completed action with a real result to look at, not
        a "never mind" -- that path is unaffected, landing straight on the
        freshly switched `OverviewScreen` same as always."""
        club_id = await self.push_screen_wait(ClubBrowserScreen(allow_cancel=True))
        if club_id is None:
            self._reopen_actions_menu()
            return
        await self._open_club(club_id, always_ask_course=False, allow_course_picker=False)
        self._periodic_scrape()

    def action_edit_settings(self) -> None:
        """Open `SettingsScreen` — direct feedback 2026-09-08: "i don't even know
        where to configure from the UI." Bound to `e` on both `OverviewScreen` and
        `DayDetailScreen` (see their own `action_edit_settings()`, which delegate here
        since `push_screen_wait()` lives on the App). Same worker requirement/
        reasoning as `action_switch_club_or_course()` above.

        No club to resolve or favorite first any more (2026-09-08, same-day follow-up:
        "i also want the settings/preferences to be global and not tied to a specific
        club") — `SettingsScreen()` now always opens the one shared settings file
        regardless of which club is active, or even whether one is favorited at all."""
        self.run_worker(self._do_edit_settings(), exclusive=True, group="settings")

    async def _do_edit_settings(self) -> None:
        await self.push_screen_wait(SettingsScreen())
        # A saved availability/preferences change should be reflected immediately --
        # not just on the next scheduled reload -- since it can change the ★ marker
        # and the overview's per-day Pick column all at once.
        # Uses the same full-rebuild helper _rebuild_current_screen() already uses
        # for a language switch (2026-09-13, once a units change also needed a
        # rebuild, not just a reload -- the old direct load_schedule()/
        # load_overview() calls refresh row content but never touch a table's own
        # column headers, which are only ever set once in on_mount()) -- a plain
        # reload would leave a stale "(°C)" header showing next to freshly
        # converted °F numbers.
        self._rebuild_current_screen()
        # SettingsScreen only ever closes via escape/Cancel (Save persists in
        # place without closing the screen -- see its own on_button_pressed())
        # so this always means "done here," never "just saved, show me the
        # result immediately" -- reopening the Actions menu doesn't interrupt
        # anything. See _reopen_actions_menu()'s own docstring.
        self._reopen_actions_menu()

    def _periodic_scrape(self, force: bool = False) -> None:
        """Best-effort background scrape of this club's whole overview window — direct
        feedback 2026-09-07: "I think hitting 'r' makes only sense as a manual
        override" — data should update on its own, both right when the app opens and
        periodically while it keeps running, without waiting for a keypress or a
        separately-scheduled cron job.

        `force=True` (added 2026-09-15, `OverviewScreen.action_refresh()` — "why
        don't we integrate those missing features into the overview screen" once
        `DayDetailScreen.action_refresh()` was found to unconditionally re-scrape
        its one day, no throttle at all) gives the whole window that same manual-
        override contract: every course/date in it, not just whatever's actually
        due per `_should_scrape()`. A pass already running still wins either way —
        this doesn't queue a second, forced pass on top of one already in flight,
        it's simply a no-op then, same as any other repeated trigger.

        Runs `scrape_once.scrape_due_for_club()` in a real thread (`run_worker(...,
        thread=True)`) rather than as a plain coroutine, since scraping the whole
        window (every course x every day in `overview_days`) can be several requests
        and would otherwise block the UI's single event loop for that whole time.
        Skips starting a new pass if a previous one is still running, so a slow
        network can't pile up overlapping scrapes.

        Shows an animated spinner + "Refreshing…" beside the Club dropdown while a
        pass is running, and "Updated just now" once it lands (added 2026-09-07,
        direct feedback: "I noticed a slight delay between the auto-refresh and
        seeing the updated schedule. Wouldn't it be better if the tool had a
        loading screen?") — a full loading *screen* would defeat the point of
        running this in a thread in the first place (staying usable while it
        scrapes), so this status readout explains the delay without blocking
        anything. Moved from the standalone `#status` line to `_RefreshStatus`
        2026-09-15 (direct feedback: "I see a nice space to the right of both
        dropdown menus... combine that with a status bar, timer or wheel") — see
        that widget's own docstring; `#status` stays reserved for actual error
        text. The delay itself was never partial data either: each course/date is
        saved as one complete `Schedule` per scrape (see storage.py's module
        docstring), so `OverviewScreen` only ever shows either the previous
        complete scrape or the new one, never a mix."""
        if self._periodic_scrape_running:
            return
        self._periodic_scrape_running = True
        if isinstance(self.screen, OverviewScreen):
            self.screen.query_one(_RefreshStatus).start_refreshing()

        def scrape_then_reload() -> None:
            try:
                # Re-resolved fresh on every pass, not the dict snapshotted once in
                # _open_club() -- a location (or any other per-club YAML fact) added
                # or changed mid-session must take effect on the very next scheduled
                # scrape, not only after switching clubs or restarting. Direct
                # feedback (2026-09-08, a real screenshot): the overview's weather
                # column stayed blank even after a location was added to the club's
                # own file, because this exact call was still handing
                # scrape_due_for_club() the config captured before that edit.
                # club_id itself doesn't change for the session's active club, so
                # it's still read from the snapshot rather than re-derived. club_name
                # (2026-09-08, same-day follow-up: "I don't want to first save a
                # club in order to see weather forecast") lets an unsaved club's
                # background scrape geocode+cache its own location too, not just a
                # favorited one's.
                club_id = self._club_config.get("club_id")
                config = {
                    **_resolved_config(self._club_slug, club_id, self._club_names.get(club_id, "")),
                    "club_id": club_id,
                }
                self._club_config = config
                scrape_once.scrape_due_for_club(self._club_slug, config, force=force)
            finally:
                self.call_from_thread(self._finish_periodic_scrape)

        self.run_worker(scrape_then_reload, thread=True)

    def _finish_periodic_scrape(self) -> None:
        self._periodic_scrape_running = False
        screen = self.screen
        if isinstance(screen, OverviewScreen):
            screen.load_overview()
            screen.refresh_banners()
            screen.query_one(_RefreshStatus).finish_refreshing()

    def action_force_refresh(self) -> None:
        """`r` on `OverviewScreen` -- the same manual override
        `DayDetailScreen.action_refresh()` already gives for one day, ported to
        the whole loaded window (2026-09-15, direct follow-up: "why don't we
        integrate those missing features into the overview screen"). Just
        `_periodic_scrape(force=True)` -- a no-op if a pass is already running,
        same as the plain periodic trigger; there's no separate "cancel and
        restart" path, since a pass already in flight will itself finish and
        reflect current data within moments regardless."""
        self._periodic_scrape(force=True)


def main() -> None:
    if "--version" in sys.argv or "-v" in sys.argv:
        print(f"teetime-monitor {_version()}")
        return
    TeetimeApp().run()


if __name__ == "__main__":
    main()
