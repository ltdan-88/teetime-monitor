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
1. Club picker (`ClubPickerScreen`) — skipped automatically if only one club is saved
   under `clubs/*.yaml` (or none: exits with a clear message instead of crashing).
2. Course picker (`CoursePickerScreen`) — skipped if the club's YAML sets a valid
   `default_course`, or if there's only one course to choose from at all.
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
`TeetimeApp.action_switch_club_or_course()` — always shows the club picker (even
with just one club saved) and the course picker (ignoring `default_course`), since
an explicit switch means actively choosing. That club picker now also offers
"🔍 Search for a club…", pushing `club_picker.ClubSearchScreen` right there (using
whichever club is already known to log in — one login works across the whole
platform) so a brand-new club can be found, saved, and switched to in one
continuous flow, no separate `python -m src.club_picker` command or app restart
needed. Every picker screen (`ClubPickerScreen`, `CoursePickerScreen`) also gained
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

from . import club_config, recommend, scrape_once, storage
from . import i18n
from . import theme as theme_module
from .club_picker import ClubSearchScreen
from .search import search as search_slots
from .models import ConfirmedBooking, Schedule
from .scrape_once import _db_path
from .scraper import COURSE_ALIASES, _holes_from_course_label, scrape_schedule
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


# Sentinel id for ClubPickerScreen's "search for a club" entry — added 2026-09-07,
# direct feedback: "I want to be able to switch clubs on the fly," a hassle before
# this since adding a club meant leaving the running TUI to run club_picker.py by
# hand. Distinguishable from a real slug since it can never collide with one --
# club_config.py's slugs are plain filenames, none of which look like this.
_SEARCH_FOR_CLUB_ID = "__search_for_a_club__"


class ClubPickerScreen(Screen[str | None]):
    """Pick a saved club — shown whenever more than one is saved, or (via
    `offer_search`) whenever `TeetimeApp.action_switch_club_or_course()` explicitly
    requests it, so the "search for a club" entry is reachable even with only one
    club currently saved (see `_SEARCH_FOR_CLUB_ID` above). `escape` dismisses with
    `None` (cancel — direct feedback 2026-09-07: "how do I quit from club/course
    picker or return to the schedule?" — there was previously no way to back out of
    this screen at all short of quitting the whole app); `q` quits the whole app,
    matching `DayDetailScreen`'s own convention."""

    BINDINGS = [("escape", "cancel", "Back"), ("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("escape", "binding.cancel"), ("q", "binding.quit")]

    def __init__(self, club_slugs: list[str], offer_search: bool = False) -> None:
        super().__init__()
        self.club_slugs = club_slugs
        self.offer_search = offer_search

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(i18n.t("picker.club_title"))
        options = [Option(slug, id=slug) for slug in self.club_slugs]
        if self.offer_search:
            options.append(Option(i18n.t("picker.search_for_a_club"), id=_SEARCH_FOR_CLUB_ID))
        yield OptionList(*options)
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_quit(self) -> None:
        self.app.exit()


class CoursePickerScreen(Screen[str | None]):
    """Pick a course — only shown when the club has no valid `default_course` set and
    more than one course exists (COURSE_ALIASES is a fixed 3-option picker, not a
    rotating list — see scraper.py's module docstring). Same `escape`/`q` bindings as
    `ClubPickerScreen` — see that class's own docstring."""

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

    def __init__(self, club_id: str, club_slug: str, course: str, date: str) -> None:
        super().__init__()
        self.club_id = club_id
        self.club_slug = club_slug
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
        self.title = f"{self.club_slug} — {self.course} — {self.date}"

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

    async def _pick_club(self, slugs: list[str]) -> str | None:
        """Startup's own picker — skips the screen entirely (returns the one slug
        directly) when there's nothing to choose between, matching the fast,
        mostly-automatic launch this app has always aimed for. Can still return
        `None` if the (only-shown-when-ambiguous) picker itself is cancelled."""
        return slugs[0] if len(slugs) == 1 else await self.push_screen_wait(ClubPickerScreen(slugs))

    async def _pick_club_or_search(self, slugs: list[str]) -> str | None:
        """The switch flow's own club-picking step — always shows the picker, even
        with only one club saved, specifically so its "search for a club" entry is
        reachable (direct feedback 2026-09-07: "I want to be able to switch clubs on
        the fly," a hassle before this since adding one meant leaving the running
        TUI to run club_picker.py separately). Picking that entry pushes
        `ClubSearchScreen` right here, logging in with whichever club is already
        known (any saved club's credentials work platform-wide, confirmed
        2026-09-05) — the newly saved club (or `None`, if backed out without saving)
        becomes the result either way, continuing straight into course-picking for
        it rather than looping back to re-show this list."""
        choice = await self.push_screen_wait(ClubPickerScreen(slugs, offer_search=True))
        if choice != _SEARCH_FOR_CLUB_ID:
            return choice
        return await self.push_screen_wait(ClubSearchScreen(slugs[0]))

    async def _start(self) -> None:
        slugs = club_config.list_clubs()
        if not slugs:
            self.exit(message=i18n.t("app.no_clubs"))
            return

        slug = await self._pick_club(slugs)
        if slug is None:
            self.exit()
            return

        config = club_config.load_club_config(slug)
        club_id = config.get("club_id")
        if not club_id:
            self.exit(message=i18n.t("app.no_club_id", slug=slug))
            return

        courses = list(COURSE_ALIASES)
        default_course = config.get("default_course")
        if default_course in courses:
            course = default_course
        elif len(courses) == 1:
            course = courses[0]
        else:
            course = await self.push_screen_wait(CoursePickerScreen(courses))
            if course is None:
                self.exit()
                return

        await self.push_screen(DayDetailScreen(club_id, slug, course, _initial_date(club_id, course)))

        self._club_slug = slug
        self._club_config = config
        self._periodic_scrape_running = False
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
        """The actual picker flow for `action_switch_club_or_course()` above.
        Deliberately does *not* reuse `_start()`'s own skip-shortcuts: that's the
        right behavior for a fast, mostly-automatic launch, but an explicit request
        to switch means actively choosing is the point — so this always shows the
        club picker (via `_pick_club_or_search()`, which also offers searching for a
        new one) and always shows the course picker (ignoring `default_course`,
        though a club with only one course still skips it — there's nothing to
        choose there either way). Backing out at any step (`escape` on a picker, or
        quitting `ClubSearchScreen` without saving) leaves the current schedule
        exactly as it was — nothing is popped or replaced until a club *and* course
        are both actually chosen."""
        slugs = club_config.list_clubs()
        if not slugs:
            return
        slug = await self._pick_club_or_search(slugs)
        if slug is None:
            return
        config = club_config.load_club_config(slug)
        club_id = config.get("club_id")
        if not club_id:
            return

        courses = list(COURSE_ALIASES)
        if len(courses) == 1:
            course = courses[0]
        else:
            course = await self.push_screen_wait(CoursePickerScreen(courses))
            if course is None:
                return

        self._club_slug = slug
        self._club_config = config
        replacement = DayDetailScreen(club_id, slug, course, _initial_date(club_id, course))
        self.pop_screen()
        await self.push_screen(replacement)
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
