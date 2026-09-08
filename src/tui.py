"""Textual app entry point — the multi-day overview (ROADMAP.md Phase 4) and single-day
detail screen (Phase 1), plus club/course selection (Phase 0). `DayDetailScreen`
implemented 2026-09-06; `OverviewScreen` added 2026-09-07 once the clubhouse-overview
mockup's design questions were resolved (see ROADMAP.md Phase 4 for that history).

Not the full app yet — ad hoc search and the Phase 5 crowd-heatmap screen aren't built
(they depend on a typed-in-criteria form and `analytics.crowd_heatmap()` being wired
into a real screen, not just unit-tested in isolation) — see `OverviewScreen`'s own
docstring for why its footer deliberately doesn't bind `/` or `h` yet.

Startup flow:
1. Club browser (`ClubBrowserScreen`) — the home screen. Search pc caddie's whole club
   directory, pick a favorite, or type a club id straight in; no club has to be saved
   to config first. Reworked 2026-09-07 on direct feedback that requiring a club to be
   saved before you could even look at it was backwards, and that saving one should
   only ever mean "favorite" (`f` toggles that, right on this screen).
2. Course picker (`CoursePickerScreen`) — skipped if the club's saved YAML (if it has
   one) sets a valid `default_course`, or if the club has only one course at all —
   which is 46% of them, per the cross-club sweep in scraper.py's module docstring.
3. `OverviewScreen` — the actual home screen once a club/course is picked: one row per
   attempted day (weekday + exact ISO date, weather or a tournament/rain tag, a
   six-block "heat strip" for 08:00-20:00, and that day's own pick — a confirmed
   booking, a recommended ★ slot, or why neither applies), plus "This week's picks"
   below (only shown once `availability` rules are configured). The cursor starts on
   today's own row, unless `_initial_date()` finds today's cached schedule already
   fully in the past (direct feedback 2026-09-07: showing "today" once the course has
   closed for the day isn't useful — first written for the single-day launch flow
   this screen replaced, then silently stopped applying to anything once it did,
   caught the same evening: "why is the TUI still showing today at this time (11:12
   PM)?"), in which case tomorrow's row is pre-highlighted instead. Enter opens
   whichever row is actually highlighted (or later moved to) either way, drilling into:
4. `DayDetailScreen` — one day's own tee sheet, for that exact date. One row per slot:
   Time | Occupancy | Players (or a block reason
   in place of both, for an event/lesson/advance-booking-window row). `r` re-scrapes
   live (scraper.scrape_schedule() +
   storage.save_schedule()) rather than always hitting the real site on open — opening
   the app should be instant, using whatever was last scraped (by hand or by
   scrape_once.py's schedule). `n`/`p` move a day forward/back within the loaded data.
   `c` opens `ConfirmBookingScreen`, a small form writing `storage.save_confirmed_booking()`
   — the manual fallback for the same-day-booking timing gap described in ROADMAP.md
   Phase 1, not the primary path (scrape_my_reservations() being real is). `x`
   acknowledges any booking_watch.py banners currently shown. `escape` pops back to
   the overview above. `q` quits.

Any unacknowledged `storage.load_unacknowledged_booking_changes()` rows show as banners
at the top of the day-detail screen on open — this is what actually delivers the
"warn me if my booking's situation changes" feature end to end: scrape_once.py detects
and persists a change, this screen is what a person actually sees it in. The overview
surfaces the same fact more compactly, as a "📌 HH:MM booked ⚠" pick for that day.

Color themes (added 2026-09-06, "I'd like color themes like in brew launcher"): see
theme.py for the 10 named themes and how they resolve/persist. Applied once at
startup (`TeetimeApp.on_mount`); switching afterward is Textual's own command palette
(`ctrl+p`, or `t` on the day-detail screen — searchable, live preview, no relaunch
needed, unlike brew-launcher's own version) rather than a hand-built picker screen —
`watch_theme()` persists whatever the command palette picks, including a native
Textual theme with no brew-launcher equivalent.

Language (added 2026-09-06, "need to make sure the TUI is at least bilingual, since
it will be used in Germany"): see i18n.py for the English/German string table and how
it resolves/persists — same shape as theme.py's resolution, sharing the same config
file. Switching is a command-palette entry ("Language: switch to Deutsch"/"...to
English"), which also rebuilds the current `DayDetailScreen` in place so every label,
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

One remaining, disclosed gap: Textual's own built-in command-palette entries (the
default "Theme"/"Quit"/"Keys"/"Screenshot"/"Maximize" system commands, from
`App.get_system_commands()`'s own base implementation) stay in whatever language
Textual itself ships them in — English. Overriding those specifically would mean
re-implementing that base method's own logic to swap in translated strings, not
covered here since the user's own report was specifically about the footer and the
banner text, not the command palette's built-in entries.

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
scraping the whole window doesn't freeze the UI; `r` stays a synchronous, single-day,
always-immediate manual override on `DayDetailScreen` itself, exactly as before —
the two are independent, not one replacing the other.

Switching club/course + searching for a new club on the fly (added 2026-09-07,
direct feedback: "how can i switch to a different course from the time schedule
menu?" followed by "I want to be able to switch clubs on the fly. It is a hassle if
you need to first save clubs into the config"): `s` on `DayDetailScreen` opens
`TeetimeApp.action_switch_club_or_course()` — which opens the very same
`ClubBrowserScreen` the app launches into, so switching mid-session and choosing at
launch behave identically (search the whole directory, jump straight to a club id,
favorite with `f`). The course picker is always shown too, ignoring
`default_course`, since an explicit switch means actively choosing. Every picker
screen (`ClubBrowserScreen`, `CoursePickerScreen`) also gained
`escape` (back out with nothing changed) and `q` (quit the whole app) bindings —
previously there was no way to back out of one short of force-quitting, per direct
feedback: "how do I quit from club/course picker or return to the schedule?"
"""

from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

from textual.app import App, ComposeResult, SystemCommand
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from . import club_config, club_directory, global_preferences, recommend, scrape_once, storage
from . import i18n
from . import theme as theme_module
from .search import SearchCriteria
from .search import resolve_buffer_minutes
from .search import search as search_slots
from .models import ConfirmedBooking, Schedule, TimeWindow, WeatherPoint
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

_TODAY = lambda: date_cls.today().isoformat()  # noqa: E731 — small enough, and patched as a whole in tests
_NOW_HHMM = lambda: datetime.now().strftime("%H:%M")  # noqa: E731 — same reasoning, for _initial_date()


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


def _weather_point_for_time(weather_points: list[WeatherPoint], time: str) -> WeatherPoint | None:
    """The hourly forecast point covering one exact slot time — an hourly point's
    own timestamp is the *start* of the hour it covers (a 14:20 slot falls under the
    14:00 point), the same rule `weather.conditions_during_round()` already uses for
    a whole round's worth of points. `None` if `time` is before the first point, or
    there's no weather at all (an unconfigured `location`, or a forecast that
    doesn't reach this far)."""
    covering = [point for point in weather_points if point.time <= time]
    return max(covering, key=lambda point: point.time) if covering else None


def _slot_weather_cell(weather_points: list[WeatherPoint], time: str) -> str:
    """One row's own weather cell — a rain/wind icon past a plain visual threshold
    plus that hour's temperature, or blank when there's genuinely no forecast to
    show (not a fabricated "0" or icon)."""
    point = _weather_point_for_time(weather_points, time)
    if point is None:
        return ""
    icons = ""
    if (point.precipitation_probability or 0) >= _SLOT_RAIN_ICON_THRESHOLD_PERCENT:
        icons += "🌧"
    if (point.wind_speed_kph or 0) >= _SLOT_WIND_ICON_THRESHOLD_KPH:
        icons += "💨"
    icons = icons or "☀"
    temp = f" {point.temperature_c:.0f}°" if point.temperature_c is not None else ""
    return f"{icons}{temp}"


class ClubBrowserScreen(Screen[str | None]):
    """Pick any club on the platform, by numeric pc caddie id. The app's home screen.

    Replaces the old "pick one of your saved clubs" flow (2026-09-07, direct feedback):
    having to save a club to `clubs/*.yaml` before you could even look at it was
    backwards — launching should just let you choose a club and a course, and saving one
    should only mean "favorite". Three ways in, so a missing directory cache or missing
    credentials is never a dead end (see club_directory.py's module docstring):

    - An empty search box lists your favorites, which need no directory and no login.
    - Typing searches the cached club directory, once it's been fetched.
    - Typing a club id (e.g. "0000001") offers that club directly — no cache, no login,
      because tee sheets are public. This is also what lets a brand-new install reach a
      club before any credentials exist, the bootstrapping gap the old picker couldn't
      close.

    Dismisses with the chosen club's numeric id, or `None` if backed out. `f` toggles
    whether the highlighted club is a favorite; `r` refreshes the directory cache
    (the one action here that does need a login). Opening the highlighted club is
    plain `enter` — Textual's own built-in `OptionList`/`Input` behavior, not a
    binding this screen declares itself (see `on_input_submitted()` and
    `on_option_list_option_selected()` below) — which is exactly why it never showed
    up in the footer on its own; added explicitly to `_FOOTER_BINDINGS` below after
    direct feedback that nothing on screen actually said to press it."""

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
        ("escape", "cancel", "Back"),
        ("q", "quit", "Quit"),
    ]
    _FOOTER_BINDINGS = [
        ("enter", "binding.open"),
        ("f", "binding.favorite"),
        ("r", "binding.refresh_directory"),
        ("escape", "binding.cancel"),
        ("q", "binding.quit"),
    ]

    def __init__(self, allow_cancel: bool = True, initial_status: str = "") -> None:
        super().__init__()
        self.allow_cancel = allow_cancel
        self.initial_status = initial_status
        self._directory: list[tuple[str, str]] = []
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
        self._show_favorites()
        if self.initial_status:
            self.query_one("#club-status", Static).update(self.initial_status)

    # -- listing -----------------------------------------------------------------

    def _favorites(self) -> list[tuple[str, str]]:
        entries = []
        for slug in club_config.list_clubs():
            config = club_config.load_club_config(slug)
            club_id = config.get("club_id")
            if club_id:
                entries.append((str(club_id), slug))
        return entries

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
        login — everything else here works without one (see club_directory.py)."""
        status = self.query_one("#club-status", Static)
        credentials = club_directory.any_credentials()
        if credentials is None:
            status.update(i18n.t("picker.directory_needs_login"))
            return
        status.update(i18n.t("club_picker.fetching"))
        club_id, username, password = credentials
        try:
            self._directory = club_directory.refresh_directory(club_id, username, password)
        except Exception as exc:  # noqa: BLE001 -- a live fetch can genuinely fail
            status.update(i18n.t("club_picker.fetch_failed", error=exc))
            return
        status.update(i18n.t("picker.directory_refreshed", count=len(self._directory)))

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
    not forced — for the rare case either guess is wrong."""

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
        yield Footer()

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


def _weather_summary(weather: list) -> str | None:
    """"☀ 24°/14°" for a dry day, "⛅ 21°/13°" once rain becomes plausible but isn't
    the whole day (see _is_rain_all_day for that case, which replaces this line
    entirely rather than combining with it). None with no daytime forecast at all —
    a schedule that was never weather-attached (e.g. `location` not configured yet)."""
    daytime = [w for w in weather if "08:00" <= w.time < "20:00"]
    temps = [w.temperature_c for w in daytime if w.temperature_c is not None]
    if not daytime or not temps:
        return None
    avg_rain_chance = sum((w.precipitation_probability or 0) for w in daytime) / len(daytime)
    icon = "☀" if avg_rain_chance < 20 else "⛅"
    return f"{icon} {max(temps):.0f}°/{min(temps):.0f}°"


def _day_tag_or_weather(schedule: Schedule) -> str:
    """The card's second line: a tournament flag beats a rain-all-day flag beats a
    plain weather summary — a tournament is the single most consequential fact about
    a day (it's not just weather-uncomfortable, whole tee times are blocked), and
    "it's raining all day anyway" is more useful at a glance than exact temperatures.
    `schedule.events` names come straight from the scraped event/lesson label (see
    scraper.py's module docstring) — untranslated, same as every other block_reason
    text in this app, since it's the club's own text, not this app's UI chrome."""
    if schedule.events:
        return f"🏆 {schedule.events[0]}"
    if _is_rain_all_day(schedule.weather):
        return f"🌧 {i18n.t('overview.rain_all_day')}"
    return _weather_summary(schedule.weather) or ""


def _resolved_config(club_slug: str | None) -> dict:
    """This club's own settings (`location`, `overview_days`, `default_course`,
    `identity`, `ai_assist`, `round_duration_minutes` — genuinely per-club facts),
    with your global `availability`/`preferences`/scrape-interval settings shallow-
    merged on top (added 2026-09-08, direct feedback: "i also want the settings/
    preferences to be global and not tied to a specific club" — those aren't
    per-club facts at all, so they overlay every club's own config rather than being
    duplicated into each one). `club_slug is None` (a club being visited without
    saving it) contributes nothing per-club, but still gets your global settings —
    recommendations now work even on a club you haven't favorited, which the old
    per-club-only design couldn't offer since there was nowhere for an unsaved club
    to have availability rules at all."""
    club_settings = {}
    if club_slug is not None:
        try:
            club_settings = club_config.load_club_config(club_slug)
        except FileNotFoundError:
            club_settings = {}
    return {**club_settings, **global_preferences.load_preferences()}


def _availability_pipeline(schedule: Schedule, config: dict) -> tuple[list, list]:
    """(deterministic candidates, still-playable after weather/daylight exclusion)
    for one schedule against your global `availability` rules (see
    `_resolved_config()`) — the exact same pipeline `recommend.weekly_picks()` uses,
    factored out so both the per-day pick column below and `DayDetailScreen`'s own ★
    marker derive from one place. `([], [])` with no `availability` configured at
    all — nothing to check against, not an error."""
    if not config.get("availability"):
        return [], []
    criteria = recommend.default_criteria_from_config(config)
    candidates = search_slots([schedule], criteria)
    playable = recommend.exclude_unplayable(candidates, [schedule], config)
    return candidates, playable


def _day_pick_text(
    schedule: Schedule | None, config: dict, confirmed: ConfirmedBooking | None, has_pending_change: bool
) -> str:
    """The overview's Pick column for one day, in priority order:

    1. A confirmed booking for that date beats everything — it's not a suggestion,
       it's what's actually happening. "⚠" alongside it means `booking_watch.py`
       found an unacknowledged change since it was booked (see DayDetailScreen's own
       banners for the detail).
    2. Otherwise, if availability rules are configured and this day has a schedule to
       check: a recommended "★ HH:MM" (the earliest still-playable match), or "no dry
       picks" specifically when candidates existed before the weather/daylight check
       but none survived it — worth saying explicitly rather than looking identical
       to "nothing matches your rules at all".
    3. A plain dash otherwise — no rules configured, no schedule yet, or genuinely no
       candidates for the day (e.g. outside every configured time window)."""
    if confirmed is not None and confirmed.time:
        text = f"📌 {confirmed.time} {i18n.t('overview.booked')}"
        if has_pending_change:
            text += " [red]⚠[/]"
        return text
    if schedule is None or not config.get("availability"):
        return "[dim]—[/]"
    candidates, playable = _availability_pipeline(schedule, config)
    if not candidates:
        return "[dim]—[/]"
    if playable:
        return f"[yellow]★[/] {min(candidate.slot.time for candidate in playable)}"
    return f"[dim italic]{i18n.t('overview.no_dry_picks')}[/]"


OVERVIEW_MAX_PICKS_SHOWN = 5


class OverviewScreen(Screen[None]):
    """The multi-day at-a-glance home screen — one row per attempted day: weekday +
    exact ISO date, weather (or a tournament/rain tag in its place), a six-block "heat
    strip" showing how full 08:00-20:00 is in 2-hour windows, and that day's own pick.
    "This week's picks" below lists the same recommendation across every loaded day —
    shown only once `availability` rules are actually configured (direct feedback on
    the mockup: an unconfigured club showing "no picks" on every single day would
    read as broken, not just empty).

    Data comes from whatever's already been scraped (`storage.load_latest_schedule()`
    per day), same as `DayDetailScreen` — opening this screen never blocks on a live
    fetch; `TeetimeApp._periodic_scrape()` (on open, and on a timer) is what keeps it
    current, exactly as it already did for the single-day view.

    How many days to attempt, and which of those are actually open for booking, are
    two separate questions — see `_display_dates()` and `scraper.fetch_available_dates()`'s
    own docstring for why a club's real booking window can be shorter (or longer)
    than the configured `overview_days`; a day beyond it renders as "not open for
    booking yet" rather than a misleadingly empty schedule.

    Enter drills into `DayDetailScreen` for the highlighted day's exact date; escape
    there pops back here (see that screen's `action_back_to_overview()`). `enter`
    itself is Textual's own built-in `DataTable` behavior, not a `BINDINGS` entry this
    screen declares — the same reason it never showed up in the footer on its own,
    fixed by listing it explicitly in `_FOOTER_BINDINGS` (see `ClubBrowserScreen`'s own
    docstring for the direct feedback this responds to). `/` opens `SearchScreen`
    (Phase 4's ad hoc search, wired in 2026-09-08 once its own backend --
    `search.py`'s hard filters, `recommend.exclude_unplayable()`,
    `ai_assist.rank_slots()` -- already existed fully tested; `recommend.ranked_matches()`
    is the same three-step pipeline `weekly_picks()` uses, just taking an explicit
    typed-in `SearchCriteria` instead of deriving one from your saved defaults),
    searching across whatever days are already loaded here (`self._schedules`), not
    a fresh scrape. `h` (Phase 5's crowd heatmap) still isn't bound — that one's
    backend (`analytics.crowd_heatmap()`) is real and tested too, but needs a few
    weeks of accumulated scrapes to actually say anything useful, so it's a
    separate, still-unbuilt screen for now.

    `e` opens `SettingsScreen` (added 2026-09-08, direct feedback: "i don't even know
    where to configure from the UI" — until then `settings_screen.py` really was only
    reachable as its own separate command, with nothing in the running app pointing
    at it). Your availability/preferences are global, not per-club (same-day
    follow-up: "i also want the settings/preferences to be global and not tied to a
    specific club") — `e` opens the same one shared settings set regardless of which
    club is active, or even whether one is favorited at all."""

    BINDINGS = [
        ("/", "search", "Search"),
        ("s", "switch", "Switch club/course"),
        ("e", "edit_settings", "Settings"),
        ("t", "command_palette", "Commands"),
        ("q", "quit", "Quit"),
    ]
    _FOOTER_BINDINGS = [
        ("enter", "binding.open"),
        ("/", "binding.search"),
        ("s", "binding.switch"),
        ("e", "binding.settings"),
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
        self._row_dates: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="status")
        yield DataTable(id="overview-table")
        yield Static("", id="picks")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(i18n.t("table.day"), i18n.t("table.weather"), i18n.t("table.heat"), i18n.t("table.pick"))
        table.cursor_type = "row"
        self._set_title()
        self.load_overview()

    @property
    def db_path(self):
        return _db_path(self.club_id)

    def _set_title(self) -> None:
        label = self.club_name or self.club_slug or self.club_id
        star = "★ " if self.club_slug else ""
        self.title = f"{star}{label} — {self.course}"

    def _config(self) -> dict:
        return _resolved_config(self.club_slug)

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

    def load_overview(self) -> None:
        self._set_title()  # picks up club_slug if this club was just favorited
        config = self._config()
        dates, open_dates = self._display_dates(config)
        table = self.query_one(DataTable)
        table.clear()
        self._row_dates = []

        confirmed_by_date = {
            booking.date: booking
            for booking in storage.load_all_confirmed_bookings(path=self.db_path)
            if booking.course == self.course
        }
        pending_change_dates = {
            change["date"] for change in storage.load_unacknowledged_booking_changes(path=self.db_path)
        }

        schedules: list[Schedule] = []
        for one_date in dates:
            self._row_dates.append(one_date)
            weekday = i18n.t(f"weekday.{date_cls.fromisoformat(one_date).weekday()}")
            suffix = f" {i18n.t('overview.today_suffix')}" if one_date == _TODAY() else ""
            day_cell = f"{weekday} {one_date}{suffix}"

            if one_date not in open_dates:
                table.add_row(
                    f"[dim]{day_cell}[/]", "[dim]—[/]", "[dim]—[/]", f"[dim]{i18n.t('overview.not_open_yet')}[/]"
                )
                continue

            schedule = storage.load_latest_schedule(self.course, one_date, path=self.db_path)
            if schedule is not None and schedule.slots:
                schedules.append(schedule)
                weather_cell = _day_tag_or_weather(schedule) or "[dim]—[/]"
                heat_cell = _heat_strip_markup(schedule)
            else:
                weather_cell = "[dim]…[/]"
                heat_cell = "[dim]……[/]"
            pick_cell = _day_pick_text(schedule, config, confirmed_by_date.get(one_date), one_date in pending_change_dates)
            table.add_row(day_cell, weather_cell, heat_cell, pick_cell)

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
        self._update_picks(schedules, config)

    def _update_picks(self, schedules: list[Schedule], config: dict) -> None:
        picks_widget = self.query_one("#picks", Static)
        if not config.get("availability"):
            picks_widget.update("")  # resolved design question: only show once configured
            return
        picks = recommend.weekly_picks(schedules, config)
        if not picks:
            picks_widget.update(f"\n[dim]{i18n.t('overview.no_matches')}[/]")
            return
        lines = [f"\n[bold]{i18n.t('overview.picks_title')}[/]"]
        for pick in picks[:OVERVIEW_MAX_PICKS_SHOWN]:
            weekday = i18n.t(f"weekday.{date_cls.fromisoformat(pick.date).weekday()}")
            line = f"[yellow]★[/] {weekday} {pick.date} · {pick.slot.time}"
            if pick.reasons:
                line += f"  [dim]{', '.join(pick.reasons)}[/]"
            lines.append(line)
        picks_widget.update("\n".join(lines))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if not (0 <= event.cursor_row < len(self._row_dates)):
            return
        date = self._row_dates[event.cursor_row]
        self.app.push_screen(
            DayDetailScreen(self.club_id, self.club_slug, self.course, date, club_name=self.club_name)
        )

    def action_search(self) -> None:
        self.app.push_screen(SearchScreen(self._schedules, self._config()))

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

    BINDINGS = [("escape", "cancel", "Back"), ("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("escape", "binding.cancel"), ("q", "binding.quit")]

    def __init__(self, schedules: list[Schedule], config: dict) -> None:
        super().__init__()
        self.schedules = schedules
        self.config = config

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
        yield DataTable(id="search-results")
        yield Static("", id="search-status")
        with Horizontal(id="buttons"):
            yield Button(i18n.t("button.cancel"), id="cancel")
            yield Button(i18n.t("search.button"), id="run", variant="success")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_mount(self) -> None:
        table = self.query_one("#search-results", DataTable)
        table.add_columns(
            i18n.t("search.table.date"),
            i18n.t("table.time"),
            i18n.t("search.table.course"),
            i18n.t("search.table.notes"),
        )

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
        matches = recommend.ranked_matches(self.schedules, criteria, self.config)
        table = self.query_one("#search-results", DataTable)
        table.clear()
        status = self.query_one("#search-status", Static)
        if not matches:
            status.update(i18n.t("search.no_matches"))
            return
        status.update("")
        for match in matches:
            weekday = i18n.t(f"weekday.{date_cls.fromisoformat(match.date).weekday()}")
            table.add_row(f"{weekday} {match.date}", match.slot.time, match.course, ", ".join(match.reasons))

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


class DayDetailScreen(Screen[None]):
    """The single-day tee sheet: Time | Occupancy | Players | Weather, colored by
    fill ratio. The Weather column (added 2026-09-08, direct feedback: "Yes per tee
    time indicator, also don't forget about the sunrise and sunset times") was
    actually part of the original Phase 2 plan — "shown per slot in the day-detail
    table" — but only the invisible half of that (`conditions_during_round()`,
    feeding recommendation filtering) had ever been built; the visible column
    itself never was, quietly, until now (`_slot_weather_cell()`). A `#daylight`
    line above the table shows the day's own sunrise/sunset, sourced from the same
    `Schedule.sun_times` this feature also had to start actually persisting (see
    `storage.init_db()`'s own docstring) — it had been fetched at scrape time and
    silently dropped ever since, so the daylight half of `exclude_unplayable()`
    could never actually exclude a too-late tee time either, not just an invisible
    display gap."""

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("c", "confirm", "Confirm tee time"),
        ("n", "next_day", "Next day"),
        ("p", "prev_day", "Previous day"),
        ("s", "switch", "Switch club/course"),
        ("e", "edit_settings", "Settings"),
        ("x", "dismiss_banners", "Dismiss banners"),
        ("escape", "back_to_overview", "Overview"),
        ("t", "command_palette", "Commands"),
        ("q", "quit", "Quit"),
    ]

    _FOOTER_BINDINGS = [
        ("r", "binding.refresh"),
        ("c", "binding.confirm"),
        ("n", "binding.next_day"),
        ("p", "binding.prev_day"),
        ("s", "binding.switch"),
        ("e", "binding.settings"),
        ("x", "binding.dismiss_banners"),
        ("escape", "binding.overview"),
        ("t", "binding.commands"),
        ("q", "binding.quit"),
    ]

    def __init__(self, club_id: str, club_slug: str | None, course: str, date: str,
                 club_name: str = "") -> None:
        super().__init__()
        self.club_id = club_id
        # None for a club being visited without saving it — an ordinary state since
        # the 2026-09-07 favorites rework, not an error (see ClubBrowserScreen).
        self.club_slug = club_slug
        self.club_name = club_name
        self.course = course
        self.date = date
        # Each real row's own plain slot.time, in table order -- kept separate from
        # what's actually rendered in the Time column (which can carry "[dim]"/"★"
        # decoration) so _selected_slot_time() reads the real value back, not
        # whatever markup happens to be on screen. Found live 2026-09-07 while adding
        # the "★" recommended-slot marker: an existing test caught it picking up the
        # literal "★ 14:00" text instead of "14:00" -- a latent fragility in reading
        # display text back out of the table that the dimming feature had already
        # introduced without anyone noticing (a past slot's confirm pre-fill would
        # have picked up "[dim]11:10[/]" verbatim).
        self._row_times: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="banners")
        yield Static("", id="daylight")
        yield Static("", id="status")
        yield DataTable(id="table")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(
            i18n.t("table.time"), i18n.t("table.occupancy"), i18n.t("table.players"), i18n.t("table.weather")
        )
        table.cursor_type = "row"
        self.refresh_banners()
        self.load_schedule()

    @property
    def db_path(self):
        return _db_path(self.club_id)

    def _set_title(self) -> None:
        # Prefer the club's own name/slug, but a club reached straight by id has
        # neither — fall back to the id rather than showing "None".
        label = self.club_name or self.club_slug or self.club_id
        star = "★ " if self.club_slug else ""
        self.title = f"{star}{label} — {self.course} — {self.date}"

    def load_schedule(self) -> None:
        self._set_title()
        table = self.query_one(DataTable)
        table.clear()
        self._row_times = []
        schedule = storage.load_latest_schedule(self.course, self.date, path=self.db_path)
        daylight = self.query_one("#daylight", Static)
        if schedule is not None and schedule.sun_times is not None:
            daylight.update(
                i18n.t(
                    "daylight.summary",
                    sunrise=schedule.sun_times.sunrise,
                    sunset=schedule.sun_times.sunset,
                )
            )
        else:
            # No forecast fetched yet (an unconfigured `location`, or nothing
            # scraped yet) -- blank, not a fabricated or stale time.
            daylight.update("")
        if schedule is None or not schedule.slots:
            table.add_row("—", i18n.t("table.no_data"), i18n.t("table.press_refresh"), "")
            return
        # Only today's own slots can already be in the past -- direct feedback
        # 2026-09-07: "can you hide or make timeslots less visible that are in the
        # past? ... I won't be able to make reservations for 11:10 or earlier
        # today." Dimmed rather than hidden entirely, matching the existing
        # block_reason rows' own style — a past slot is still real information (who
        # played it), just not something you can act on anymore. `None` on any other
        # date, so a future/past *day* never dims itself against today's clock.
        now = _NOW_HHMM() if self.date == _TODAY() else None
        recommended_times = self._recommended_times(schedule)
        for slot in schedule.slots:
            self._row_times.append(slot.time)
            is_past = now is not None and slot.time < now
            time_cell = _dim_if(slot.time, is_past)
            if slot.time in recommended_times and not is_past:
                time_cell = f"★ {time_cell}"
            weather_cell = _dim_if(_slot_weather_cell(schedule.weather, slot.time), is_past)
            if slot.block_reason is not None:
                # A real, confirmed case (Sonnenberg, 2026-09-08): pc caddie's own
                # merged free-seat cell for a block-time/disable-time row can be
                # genuinely *empty* — blocked, but with no label at all shown on the
                # site itself. `slot.block_reason` faithfully stores that as `""`
                # (not `None` — the row still isn't real occupancy), but rendering
                # `""` directly produced a blank, confusing-looking row here — direct
                # feedback: "why am I seeing timeslots without any occupancies?".
                # Substituted with a plain translated placeholder at display time
                # only; the underlying `""` is left alone everywhere else (already
                # handled correctly: `Schedule.events`/the overview's heat-strip both
                # already test block_reason by truthiness/`is None`, not by display
                # text).
                reason_text = slot.block_reason or i18n.t("table.not_bookable")
                table.add_row(time_cell, f"[dim]{reason_text}[/]", "", weather_cell)
                continue
            style = f"dim {_fill_style(slot.booked, slot.capacity)}" if is_past else _fill_style(
                slot.booked, slot.capacity
            )
            occupancy = f"[{style}]{slot.booked}/{slot.capacity}[/]"
            players = ", ".join(slot.players) if slot.players else ""
            table.add_row(
                time_cell, occupancy, _dim_if(players, is_past and bool(players)), weather_cell
            )

    def _recommended_times(self, schedule: Schedule) -> set[str]:
        """Which of this schedule's own slot times pass your global availability
        rules right now — marked with a leading "★" in the Time column.

        Thin wrapper around the module-level `_availability_pipeline()` (factored out
        2026-09-07 when `OverviewScreen`'s own per-day pick column needed the exact
        same computation) — this method's only job is resolving `config` via
        `_resolved_config()`. Best-effort: no `availability` configured at all, or a
        schedule with no weather/sun-times attached yet (e.g. `location` still isn't
        configured for this club), just means nothing gets marked — never an error
        shown to the user. `sun_times` genuinely round-trips through `storage.py` now
        (2026-09-08 — see that module's `init_db()` docstring for the real gap this
        closed: it used to be fetched at scrape time and silently dropped, so the
        daylight half of `exclude_unplayable()` could never actually exclude
        anything reached through this method)."""
        _, playable = _availability_pipeline(schedule, _resolved_config(self.club_slug))
        return {candidate.slot.time for candidate in playable}

    def refresh_banners(self) -> None:
        changes = storage.load_unacknowledged_booking_changes(path=self.db_path)
        banner = self.query_one("#banners", Static)
        if not changes:
            banner.update("")
            return
        # render_booking_change() re-renders kind+params in the current language;
        # falls back to the stored (English) message for a row saved before that
        # existed, or an unrecognized kind, rather than showing nothing.
        lines = [
            f"⚠ {i18n.render_booking_change(change['kind'], change['params']) or change['message']}"
            for change in changes
        ]
        banner.update("\n".join(lines))

    def action_refresh(self) -> None:
        status = self.query_one("#status", Static)
        try:
            schedule = scrape_schedule(self.club_id, self.course, self.date)
        except Exception as exc:  # noqa: BLE001 — a live scrape can genuinely fail
            # (no network, site down); pressing 'r' shouldn't crash the whole TUI over
            # it, and this uses a separate widget from #banners so a transient error
            # here doesn't clobber a pending booking_watch message.
            status.update(i18n.t("status.refresh_failed", error=exc))
            return
        # Real regression caught live, 2026-09-08, while verifying the new per-slot
        # weather column: this manual 'r' path never called _attach_weather() at
        # all, unlike the background scheduled scrape (scrape_once.run()) — so a
        # schedule that already had real weather/sun_times attached would get
        # silently overwritten with a weather-less one (storage.py's "latest
        # scrape wins" rule) the moment someone pressed 'r', undoing the whole
        # point of persisting sun_times at all. Resolved fresh here (not the
        # session-cached TeetimeApp._club_config) for the same reason
        # _periodic_scrape() was fixed to do the same the same day.
        _attach_weather(schedule, _resolved_config(self.club_slug), self.club_id, self.course, self.date)
        storage.save_schedule(schedule, path=self.db_path)
        status.update(i18n.t("status.refreshed"))
        self.load_schedule()

    def action_confirm(self) -> None:
        def on_result(confirmed: bool | None) -> None:
            if confirmed:
                self.load_schedule()

        default_time = self._selected_slot_time()
        default_holes = _holes_from_course_label(self.course)
        self.app.push_screen(
            ConfirmBookingScreen(self.club_id, self.course, self.date, default_time, default_holes),
            on_result,
        )

    def _selected_slot_time(self) -> str | None:
        """The currently highlighted row's own time, if a real slot is selected —
        direct feedback 2026-09-07: confirming a tee time shouldn't require
        re-typing what you already picked by moving the cursor there. Reads
        `self._row_times` (each row's plain, undecorated slot.time, tracked
        separately in `load_schedule()`) rather than parsing the Time column's own
        rendered text — that text can carry "[dim]"/"★" markup once a slot is past
        or recommended, which very nearly leaked into this exact field verbatim
        before an existing test caught it. `None` for the "no data yet" placeholder
        row (nothing in `_row_times` at all) or an empty table."""
        table = self.query_one(DataTable)
        if not (0 <= table.cursor_row < len(self._row_times)):
            return None
        return self._row_times[table.cursor_row]

    def action_next_day(self) -> None:
        self.date = (date_cls.fromisoformat(self.date) + timedelta(days=1)).isoformat()
        self.query_one("#status", Static).update("")
        self.load_schedule()

    def action_prev_day(self) -> None:
        self.date = (date_cls.fromisoformat(self.date) - timedelta(days=1)).isoformat()
        self.query_one("#status", Static).update("")
        self.load_schedule()

    def action_dismiss_banners(self) -> None:
        changes = storage.load_unacknowledged_booking_changes(path=self.db_path)
        storage.acknowledge_booking_changes([change["id"] for change in changes], path=self.db_path)
        self.refresh_banners()

    def action_quit(self) -> None:
        self.app.exit()

    def action_back_to_overview(self) -> None:
        """Pop back to whatever this day was pushed on top of — the `OverviewScreen`
        it was drilled into from (added 2026-09-07 alongside that screen), which then
        gets reloaded in case a scrape landed while drilled into this day. Guarded
        against popping the very last screen in the stack (Textual disallows that),
        which never happens via the real drill-down flow — `OverviewScreen` is always
        underneath — but keeps `escape` harmless if this screen is ever reached some
        other way (a test, or a future standalone entry point) with nothing real
        below it."""
        if len(self.app.screen_stack) <= 1:
            return
        self.app.pop_screen()
        screen = self.app.screen
        if isinstance(screen, OverviewScreen):
            screen.load_overview()

    def action_switch(self) -> None:
        # Delegates to the App (same shape as action_command_palette below) since
        # re-opening the club/course pickers needs push_screen_wait(), which lives on
        # TeetimeApp already — see TeetimeApp.action_switch_club_or_course()'s own
        # docstring.
        self.app.action_switch_club_or_course()

    def action_edit_settings(self) -> None:
        # Same delegation reasoning as action_switch() above — see
        # TeetimeApp._do_edit_settings().
        self.app.action_edit_settings()

    def action_command_palette(self) -> None:
        # The command palette's own ctrl+p binding isn't a normal bubbling action
        # (found empirically — it's not even in App.BINDINGS), so `t` needs its own
        # action here that calls App.action_command_palette() directly rather than
        # relying on the binding name alone reaching the App.
        self.app.action_command_palette()


class TeetimeApp(App[None]):
    """Club/course selection, then the day-detail screen. See module docstring."""

    TITLE = "teetime-monitor"

    def __init__(self) -> None:
        super().__init__()
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
        yield from super().get_system_commands(screen)
        current = i18n.get_language()
        other = i18n.other_language(current)
        yield SystemCommand(
            i18n.t("command.language_title", other=i18n.LANGUAGE_LABELS[other]),
            i18n.t("command.language_description", current=i18n.LANGUAGE_LABELS[current]),
            self.action_switch_language,
        )

    def action_switch_language(self) -> None:
        new_lang = i18n.other_language(i18n.get_language())
        i18n.set_language(new_lang)
        i18n.save_language(new_lang)
        self._rebuild_current_screen()

    def _rebuild_current_screen(self) -> None:
        """Replace the current screen with a fresh instance of itself so every label,
        table header, and status message re-renders in the new language immediately —
        simpler and more reliable than a partial recompose that would also need to
        manually re-run load_schedule()/refresh_banners() (or load_overview()) by
        hand. Handles both DayDetailScreen and OverviewScreen (renamed from
        `_rebuild_day_detail_screen` 2026-09-07 once a second screen needed the same
        treatment) — a no-op for anything else (e.g. mid-picker when switching
        language), since those screens are transient enough that the next one shown
        will already use the new language, and this app deliberately doesn't chase
        every transient screen's live re-render (see module docstring)."""
        screen = self.screen
        if isinstance(screen, DayDetailScreen):
            replacement = DayDetailScreen(
                screen.club_id, screen.club_slug, screen.course, screen.date, club_name=screen.club_name
            )
        elif isinstance(screen, OverviewScreen):
            replacement = OverviewScreen(screen.club_id, screen.club_slug, screen.course, club_name=screen.club_name)
        else:
            return
        self.pop_screen()
        self.push_screen(replacement)

    async def _pick_course(self, club_id: str, config: dict, always_ask: bool) -> str | None:
        """This club's own course list, fetched live (see scraper.fetch_course_aliases),
        reduced to a single choice. Returns `""` to mean "the club has no tee sheet"
        and `None` to mean "backed out / couldn't fetch", so callers can tell those two
        genuinely different outcomes apart — one is a fact about the club, the other is
        a transient failure or a deliberate cancel.

        `always_ask` is what separates the two callers: launching should be fast and
        mostly automatic (honor `default_course`), while explicitly asking to switch
        means actively choosing is the whole point."""
        status = None
        if isinstance(self.screen, (DayDetailScreen, OverviewScreen)):
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
        if len(courses) == 1:
            return courses[0]  # nothing to choose between
        return await self.push_screen_wait(CoursePickerScreen(courses))

    async def _open_club(self, club_id: str, always_ask_course: bool) -> bool:
        """Take a chosen club id all the way to its multi-day overview. True if an
        `OverviewScreen` was actually opened.

        The club's saved config is looked up *from* its id rather than the other way
        round (`club_config.slug_for_club_id()`) — since the 2026-09-07 favorites
        rework a club reached from the directory usually has no saved file at all, and
        that's a normal state: it just means empty config and all the existing
        per-setting fallbacks.

        Pops back to the app's own base screen first, however deep the current stack
        is (e.g. drilled into a `DayDetailScreen` from the overview when `s` was
        pressed) — so switching clubs never leaves a stale screen buried underneath
        the new one."""
        slug = club_config.slug_for_club_id(club_id)
        config = club_config.load_club_config(slug) if slug else {}
        course = await self._pick_course(club_id, config, always_ask=always_ask_course)
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
        return True

    async def _start(self) -> None:
        """Open straight into "pick a club" — no saved club required (2026-09-07,
        direct feedback that having to save a club before looking at it was backwards;
        see `ClubBrowserScreen`). `allow_cancel=False` because this is the home screen
        at launch: there's nothing behind it to go back to, so `escape` shouldn't drop
        the user onto a blank app."""
        self._periodic_scrape_running = False
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

        Deliberately does *not* reuse `_start()`'s `default_course` shortcut: an
        explicit request to switch means actively choosing is the point. A club with
        only one course still skips the course picker — there's nothing to choose.
        Backing out at any step leaves the current schedule exactly as it was; nothing
        is popped or replaced until a club *and* a course are both actually chosen."""
        club_id = await self.push_screen_wait(ClubBrowserScreen(allow_cancel=True))
        if club_id is None:
            return
        await self._open_club(club_id, always_ask_course=True)
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
        # not just on the next scheduled reload -- since it can change the ★ marker,
        # the overview's per-day pick column, and "This week's picks" all at once.
        if isinstance(self.screen, DayDetailScreen):
            self.screen.load_schedule()
        elif isinstance(self.screen, OverviewScreen):
            self.screen.load_overview()

    def _periodic_scrape(self) -> None:
        """Best-effort background scrape of this club's whole overview window — direct
        feedback 2026-09-07: "I think hitting 'r' makes only sense as a manual
        override" — 'r' still forces an immediate re-scrape of just the currently
        viewed day (DayDetailScreen.action_refresh()), but data should also update on
        its own, both right when the app opens and periodically while it keeps
        running, without waiting for a keypress or a separately-scheduled cron job.

        Runs `scrape_once.scrape_due_for_club()` in a real thread (`run_worker(...,
        thread=True)`) rather than as a plain coroutine, since scraping the whole
        window (every course x every day in `overview_days`) can be several requests
        and would otherwise block the UI's single event loop for that whole time —
        `action_refresh()`'s single-day scrape stays synchronous since it's already a
        deliberate, one-off user action. `_should_scrape()` still throttles what's
        actually fetched each pass, same as the standalone scheduled job. Skips
        starting a new pass if a previous one is still running, so a slow network
        can't pile up overlapping scrapes.

        Shows "Refreshing…" in the status line while a pass is running, and
        "Refreshed." once it lands (added 2026-09-07, direct feedback: "I noticed a
        slight delay between the auto-refresh and seeing the updated schedule.
        Wouldn't it be better if the tool had a loading screen?") — a full loading
        *screen* would defeat the point of running this in a thread in the first
        place (staying usable while it scrapes), so a status-line message explains
        the delay without blocking anything. The delay itself was never partial data
        either: each course/date is saved as one complete `Schedule` per scrape (see
        storage.py's module docstring), so `DayDetailScreen` only ever shows either
        the previous complete scrape or the new one, never a mix."""
        if self._periodic_scrape_running:
            return
        self._periodic_scrape_running = True
        if isinstance(self.screen, (DayDetailScreen, OverviewScreen)):
            self.screen.query_one("#status", Static).update(i18n.t("status.refreshing"))

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
                # it's still read from the snapshot rather than re-derived.
                config = {**_resolved_config(self._club_slug), "club_id": self._club_config.get("club_id")}
                self._club_config = config
                scrape_once.scrape_due_for_club(self._club_slug, config)
            finally:
                self.call_from_thread(self._finish_periodic_scrape)

        self.run_worker(scrape_then_reload, thread=True)

    def _finish_periodic_scrape(self) -> None:
        self._periodic_scrape_running = False
        screen = self.screen
        if isinstance(screen, DayDetailScreen):
            screen.load_schedule()
            screen.refresh_banners()
            screen.query_one("#status", Static).update(i18n.t("status.refreshed"))
        elif isinstance(screen, OverviewScreen):
            screen.load_overview()
            screen.query_one("#status", Static).update(i18n.t("status.refreshed"))


def main() -> None:
    TeetimeApp().run()


if __name__ == "__main__":
    main()
