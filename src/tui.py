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
3. `DayDetailScreen` — the actual tee sheet for today, one row per slot: Time |
   Occupancy | Players (or a block reason in place of both, for an event/lesson/
   advance-booking-window row). `r` re-scrapes live (scraper.scrape_schedule() +
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
"""

from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from . import club_config, storage
from .models import ConfirmedBooking
from .scrape_once import _db_path
from .scraper import COURSE_ALIASES, scrape_schedule

_TODAY = lambda: date_cls.today().isoformat()  # noqa: E731 — small enough, and patched as a whole in tests


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


class ClubPickerScreen(Screen[str]):
    """Pick a saved club — only shown when more than one is saved."""

    def __init__(self, club_slugs: list[str]) -> None:
        super().__init__()
        self.club_slugs = club_slugs

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Which club?")
        yield OptionList(*[Option(slug, id=slug) for slug in self.club_slugs])
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)


class CoursePickerScreen(Screen[str]):
    """Pick a course — only shown when the club has no valid `default_course` set and
    more than one course exists (COURSE_ALIASES is a fixed 3-option picker, not a
    rotating list — see scraper.py's module docstring)."""

    def __init__(self, courses: list[str]) -> None:
        super().__init__()
        self.courses = courses

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Which course?")
        yield OptionList(*[Option(course, id=course) for course in self.courses])
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)


class ConfirmBookingScreen(Screen[bool]):
    """Manual confirm-your-tee-time form — the fallback for the same-day-booking timing
    gap (ROADMAP.md Phase 1), not the primary source (scrape_my_reservations() is,
    once the login form exists)."""

    def __init__(self, club_id: str, course: str, date: str) -> None:
        super().__init__()
        self.club_id = club_id
        self.course = course
        self.date = date

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="confirm-form"):
            yield Label(f"Confirm your tee time for {self.date}")
            yield Label("Time (HH:MM):")
            yield Input(placeholder="14:00", id="time")
            yield Label("Holes (9 or 18, optional):")
            yield Input(placeholder="18", id="holes")
            yield Static("", id="confirm-status")
            with Horizontal():
                yield Button("Save", id="save", variant="success")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
            return

        time = self.query_one("#time", Input).value.strip()
        holes_text = self.query_one("#holes", Input).value.strip()
        if not time:
            self.query_one("#confirm-status", Static).update("Enter a time first.")
            return
        try:
            holes = int(holes_text) if holes_text else None
        except ValueError:
            self.query_one("#confirm-status", Static).update("Holes must be a number.")
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
        ("x", "dismiss_banners", "Dismiss banners"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, club_id: str, club_slug: str, course: str, date: str) -> None:
        super().__init__()
        self.club_id = club_id
        self.club_slug = club_slug
        self.course = course
        self.date = date

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="banners")
        yield Static("", id="status")
        yield DataTable(id="table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Time", "Occupancy", "Players")
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
        schedule = storage.load_latest_schedule(self.course, self.date, path=self.db_path)
        if schedule is None or not schedule.slots:
            table.add_row("—", "no data yet", "press 'r' to scrape")
            return
        for slot in schedule.slots:
            if slot.block_reason is not None:
                table.add_row(slot.time, f"[dim]{slot.block_reason}[/]", "")
                continue
            style = _fill_style(slot.booked, slot.capacity)
            occupancy = f"[{style}]{slot.booked}/{slot.capacity}[/]"
            players = ", ".join(slot.players) if slot.players else ""
            table.add_row(slot.time, occupancy, players)

    def refresh_banners(self) -> None:
        changes = storage.load_unacknowledged_booking_changes(path=self.db_path)
        banner = self.query_one("#banners", Static)
        if not changes:
            banner.update("")
            return
        lines = [f"⚠ {change['message']}" for change in changes]
        banner.update("\n".join(lines))

    def action_refresh(self) -> None:
        status = self.query_one("#status", Static)
        try:
            schedule = scrape_schedule(self.club_id, self.course, self.date)
        except Exception as exc:  # noqa: BLE001 — a live scrape can genuinely fail
            # (no network, site down); pressing 'r' shouldn't crash the whole TUI over
            # it, and this uses a separate widget from #banners so a transient error
            # here doesn't clobber a pending booking_watch message.
            status.update(f"Refresh failed: {exc}")
            return
        storage.save_schedule(schedule, path=self.db_path)
        status.update("Refreshed.")
        self.load_schedule()

    def action_confirm(self) -> None:
        def on_result(confirmed: bool | None) -> None:
            if confirmed:
                self.load_schedule()

        self.app.push_screen(ConfirmBookingScreen(self.club_id, self.course, self.date), on_result)

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


class TeetimeApp(App[None]):
    """Club/course selection, then the day-detail screen. See module docstring."""

    TITLE = "teetime-monitor"

    def on_mount(self) -> None:
        self.run_worker(self._start(), exclusive=True)

    async def _start(self) -> None:
        slugs = club_config.list_clubs()
        if not slugs:
            self.exit(message="No clubs saved yet — copy clubs/club.example.yaml first.")
            return

        slug = slugs[0] if len(slugs) == 1 else await self.push_screen_wait(ClubPickerScreen(slugs))

        config = club_config.load_club_config(slug)
        club_id = config.get("club_id")
        if not club_id:
            self.exit(message=f"clubs/{slug}.yaml has no club_id set.")
            return

        courses = list(COURSE_ALIASES)
        default_course = config.get("default_course")
        if default_course in courses:
            course = default_course
        elif len(courses) == 1:
            course = courses[0]
        else:
            course = await self.push_screen_wait(CoursePickerScreen(courses))

        await self.push_screen(DayDetailScreen(club_id, slug, course, _TODAY()))


def main() -> None:
    TeetimeApp().run()


if __name__ == "__main__":
    main()
