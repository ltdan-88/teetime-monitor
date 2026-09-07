"""Textual app entry point — the single-day detail screen (ROADMAP.md Phase 1), plus
club/course selection (Phase 0). Implemented 2026-09-06, once every module it depends
on (storage.py, scraper.py, booking_watch.py, club_config.py) was real.

Not the full app yet — the Phase 4 multi-day overview, ad hoc search, and Phase 5
heatmap screens aren't built (they depend on `scraper.scrape_overview_areas()` and
`search.py`/`ai_assist.rank_slots()`/`analytics.crowd_heatmap()` being wired together
for real use, not just unit-tested in isolation — a deliberate stopping point to check
this screen against the already-agreed mockups before building further, rather than
guessing blind at three more screens' worth of layout).

Startup flow:
1. Club browser (`ClubBrowserScreen`) — the home screen. Search pc caddie's whole club
   directory, pick a favorite, or type a club id straight in; no club has to be saved
   to config first. Reworked 2026-09-07 on direct feedback that requiring a club to be
   saved before you could even look at it was backwards, and that saving one should
   only ever mean "favorite" (`f` toggles that, right on this screen).
2. Course picker (`CoursePickerScreen`) — skipped if the club's saved YAML (if it has
   one) sets a valid `default_course`, or if the club has only one course at all —
   which is 46% of them, per the cross-club sweep in scraper.py's module docstring.
3. `DayDetailScreen` — the actual tee sheet, opening on today's date unless
   `_initial_date()` finds today's own cached schedule already fully in the past
   (see that function's docstring — direct feedback 2026-09-07: showing "today" once
   the course has closed for the day isn't useful), in which case it opens on
   tomorrow instead. One row per slot: Time | Occupancy | Players (or a block reason
   in place of both, for an event/lesson/advance-booking-window row). `r` re-scrapes
   live (scraper.scrape_schedule() +
   storage.save_schedule()) rather than always hitting the real site on open — opening
   the app should be instant, using whatever was last scraped (by hand or by
   scrape_once.py's schedule). `n`/`p` move a day forward/back within the loaded data.
   `c` opens `ConfirmBookingScreen`, a small form writing `storage.save_confirmed_booking()`
   — the manual fallback for the same-day-booking timing gap described in ROADMAP.md
   Phase 1, not the primary path (scrape_my_reservations() being real is). `x`
   acknowledges any booking_watch.py banners currently shown. `q` quits.

Any unacknowledged `storage.load_unacknowledged_booking_changes()` rows show as banners
at the top of the day-detail screen on open — this is what actually delivers the
"warn me if my booking's situation changes" feature end to end: scrape_once.py detects
and persists a change, this screen is what a person actually sees it in.

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
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from . import club_config, club_directory, recommend, scrape_once, storage
from . import i18n
from . import theme as theme_module
from .search import search as search_slots
from .models import ConfirmedBooking, Schedule
from .scrape_once import _db_path
from .scraper import (
    NoTeeSheetError,
    _holes_from_course_label,
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
    (the one action here that does need a login)."""

    CSS = """
    #club-search { margin: 0 2; }
    #club-results { height: 1fr; margin: 0 2; }
    #club-status { padding: 0 2; color: $text-muted; }
    """

    BINDINGS = [
        ("escape", "cancel", "Back"),
        ("f", "toggle_favorite", "Favorite"),
        ("r", "refresh_directory", "Refresh list"),
        ("q", "quit", "Quit"),
    ]
    _FOOTER_BINDINGS = [
        ("escape", "binding.cancel"),
        ("f", "binding.favorite"),
        ("r", "binding.refresh_directory"),
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
            self._show_entries(matches, i18n.t("club_picker.match_count", count=len(matches)))
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
    `ClubBrowserScreen` — see that class's own docstring."""

    BINDINGS = [("escape", "cancel", "Back"), ("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("escape", "binding.cancel"), ("q", "binding.quit")]

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


class DayDetailScreen(Screen[None]):
    """The single-day tee sheet: Time | Occupancy | Players, colored by fill ratio."""

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("c", "confirm", "Confirm tee time"),
        ("n", "next_day", "Next day"),
        ("p", "prev_day", "Previous day"),
        ("s", "switch", "Switch club/course"),
        ("x", "dismiss_banners", "Dismiss banners"),
        ("t", "command_palette", "Commands"),
        ("q", "quit", "Quit"),
    ]

    _FOOTER_BINDINGS = [
        ("r", "binding.refresh"),
        ("c", "binding.confirm"),
        ("n", "binding.next_day"),
        ("p", "binding.prev_day"),
        ("s", "binding.switch"),
        ("x", "binding.dismiss_banners"),
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
        yield Static("", id="status")
        yield DataTable(id="table")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(i18n.t("table.time"), i18n.t("table.occupancy"), i18n.t("table.players"))
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
        if schedule is None or not schedule.slots:
            table.add_row("—", i18n.t("table.no_data"), i18n.t("table.press_refresh"))
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
            if slot.block_reason is not None:
                table.add_row(time_cell, f"[dim]{slot.block_reason}[/]", "")
                continue
            style = f"dim {_fill_style(slot.booked, slot.capacity)}" if is_past else _fill_style(
                slot.booked, slot.capacity
            )
            occupancy = f"[{style}]{slot.booked}/{slot.capacity}[/]"
            players = ", ".join(slot.players) if slot.players else ""
            table.add_row(time_cell, occupancy, _dim_if(players, is_past and bool(players)))

    def _recommended_times(self, schedule: Schedule) -> set[str]:
        """Which of this schedule's own slot times pass your saved availability rules
        right now — marked with a leading "★" in the Time column. A lightweight step
        toward real recommendations (ROADMAP.md Phase 3's search.py/recommend.py)
        without needing the full multi-day overview screen first, which still needs a
        mockup sign-off before it's built.

        Reuses the exact same deterministic pipeline `recommend.weekly_picks()` uses
        for the (still-unbuilt) multi-day screen — `search.search()` for party
        size/time-window/buffer, then `recommend.exclude_unplayable()` for
        weather/daylight — just applied to this one already-loaded `Schedule` instead
        of the whole overview window. Best-effort: a club with no `availability` block
        configured, or a schedule with no weather attached yet, just means nothing
        gets marked — never an error shown to the user. `sun_times` specifically is
        never set on a schedule loaded this way (storage.py doesn't persist it — see
        its own module docstring), so the daylight half of `exclude_unplayable()`
        can't actually exclude anything here; only the weather half can. A known,
        accepted gap, not a silent one."""
        if self.club_slug is None:
            return set()  # a club being visited, not saved — no availability rules
        try:
            config = club_config.load_club_config(self.club_slug)
        except FileNotFoundError:
            return set()
        criteria = recommend.default_criteria_from_config(config)
        candidates = search_slots([schedule], criteria)
        playable = recommend.exclude_unplayable(candidates, [schedule], config)
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

    def action_switch(self) -> None:
        # Delegates to the App (same shape as action_command_palette below) since
        # re-opening the club/course pickers needs push_screen_wait(), which lives on
        # TeetimeApp already — see TeetimeApp.action_switch_club_or_course()'s own
        # docstring.
        self.app.action_switch_club_or_course()

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
        self._rebuild_day_detail_screen()

    def _rebuild_day_detail_screen(self) -> None:
        """Replace the current screen with a fresh instance of itself so every label,
        table header, and status message re-renders in the new language immediately —
        simpler and more reliable than a partial recompose that would also need to
        manually re-run load_schedule()/refresh_banners() by hand. A no-op if the
        current screen isn't DayDetailScreen (e.g. mid-picker when switching
        language) — that screen is transient enough that the next one shown will
        already use the new language, and this app deliberately doesn't chase every
        transient screen's live re-render (see module docstring)."""
        screen = self.screen
        if isinstance(screen, DayDetailScreen):
            replacement = DayDetailScreen(screen.club_id, screen.club_slug, screen.course, screen.date)
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
        if isinstance(self.screen, DayDetailScreen):
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
        """Take a chosen club id all the way to its tee sheet. True if a
        `DayDetailScreen` was actually opened.

        The club's saved config is looked up *from* its id rather than the other way
        round (`club_config.slug_for_club_id()`) — since the 2026-09-07 favorites
        rework a club reached from the directory usually has no saved file at all, and
        that's a normal state: it just means empty config and all the existing
        per-setting fallbacks."""
        slug = club_config.slug_for_club_id(club_id)
        config = club_config.load_club_config(slug) if slug else {}
        course = await self._pick_course(club_id, config, always_ask=always_ask_course)
        if not course:
            return False

        replacement = DayDetailScreen(
            club_id, slug, course, _initial_date(club_id, course), club_name=self._club_names.get(club_id, "")
        )
        if isinstance(self.screen, DayDetailScreen):
            self.pop_screen()
        await self.push_screen(replacement)
        self._club_slug = slug
        self._club_config = config
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
        if isinstance(self.screen, DayDetailScreen):
            self.screen.query_one("#status", Static).update(i18n.t("status.refreshing"))

        def scrape_then_reload() -> None:
            try:
                scrape_once.scrape_due_for_club(self._club_slug, self._club_config)
            finally:
                self.call_from_thread(self._finish_periodic_scrape)

        self.run_worker(scrape_then_reload, thread=True)

    def _finish_periodic_scrape(self) -> None:
        self._periodic_scrape_running = False
        if isinstance(self.screen, DayDetailScreen):
            self.screen.load_schedule()
            self.screen.refresh_banners()
            self.screen.query_one("#status", Static).update(i18n.t("status.refreshed"))


def main() -> None:
    TeetimeApp().run()


if __name__ == "__main__":
    main()
