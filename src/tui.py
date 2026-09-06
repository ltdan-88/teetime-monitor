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
"""

from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

from textual.app import App, ComposeResult, SystemCommand
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from . import club_config, storage
from . import i18n
from . import theme as theme_module
from .models import ConfirmedBooking
from .scrape_once import _db_path
from .scraper import COURSE_ALIASES, scrape_schedule

_TODAY = lambda: date_cls.today().isoformat()  # noqa: E731 — small enough, and patched as a whole in tests


class TranslatedFooter(Static):
    """A minimal stand-in for Textual's built-in `Footer` — see module docstring's
    "Revised the same day" note for why: that widget's key-hint text comes from each
    Screen's class-level `BINDINGS` descriptions (fixed at import time, English), and
    no public API was found to override a binding's displayed text at render time.
    Renders the same key hints from i18n.py instead — `bindings` is `[(key,
    i18n_key), ...]` in display order; the actual key dispatch still goes through the
    Screen's own `BINDINGS`/`action_*` methods, this widget only controls what's shown."""

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
        yield Label(i18n.t("picker.club_title"))
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
        yield Label(i18n.t("picker.course_title"))
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
            yield Label(i18n.t("confirm.title", date=self.date))
            yield Label(i18n.t("confirm.time_label"))
            yield Input(placeholder="14:00", id="time")
            yield Label(i18n.t("confirm.holes_label"))
            yield Input(placeholder="18", id="holes")
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
        ("x", "dismiss_banners", "Dismiss banners"),
        ("t", "command_palette", "Commands"),
        ("q", "quit", "Quit"),
    ]

    _FOOTER_BINDINGS = [
        ("r", "binding.refresh"),
        ("c", "binding.confirm"),
        ("n", "binding.next_day"),
        ("p", "binding.prev_day"),
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
        schedule = storage.load_latest_schedule(self.course, self.date, path=self.db_path)
        if schedule is None or not schedule.slots:
            table.add_row("—", i18n.t("table.no_data"), i18n.t("table.press_refresh"))
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

    async def _start(self) -> None:
        slugs = club_config.list_clubs()
        if not slugs:
            self.exit(message=i18n.t("app.no_clubs"))
            return

        slug = slugs[0] if len(slugs) == 1 else await self.push_screen_wait(ClubPickerScreen(slugs))

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

        await self.push_screen(DayDetailScreen(club_id, slug, course, _TODAY()))


def main() -> None:
    TeetimeApp().run()


if __name__ == "__main__":
    main()
