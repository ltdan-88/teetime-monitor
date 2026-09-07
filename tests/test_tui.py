import asyncio
import threading

import pytest
from textual.app import App
from textual.widgets import DataTable, Input, OptionList, Static

from src import i18n, scrape_once, storage, theme, tui
from src.models import Schedule, Slot


@pytest.fixture(autouse=True)
def _english_ui(monkeypatch, tmp_path):
    """Every test here reads English UI text unless it explicitly switches language
    itself — i18n's "current language" is deliberate module-level global state (see
    i18n.py's docstring), so without this a test that switches to German would leak
    that choice into every test that runs afterward in the same pytest process, and a
    fresh test would otherwise resolve its language from this machine's real locale
    env vars / real ~/.config/teetime-monitor/config, not a hermetic default."""
    monkeypatch.setattr(i18n, "CONFIG_FILE", tmp_path / "not-used-unless-a-test-wants-it")
    i18n.set_language("en")
    yield
    i18n._current_language = None


@pytest.fixture(autouse=True)
def _no_background_scraping(monkeypatch):
    """`TeetimeApp._periodic_scrape()` (added 2026-09-07) fires once automatically as
    soon as `TeetimeApp._start()` finishes — every test here that builds a real
    `TeetimeApp()` would otherwise kick off a real background-thread scrape against
    the live pc caddie site (real club_id "0000001" used throughout this file), since
    none of those tests otherwise mock scraper.py. Caught live: the full test suite's
    runtime jumped from ~15s to over a minute once this shipped, before this fixture
    was added. A no-op by default; a test that specifically wants to exercise the
    real wiring overrides `scrape_once.scrape_due_for_club` itself locally."""
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: [])


class _HostApp(App):
    """Minimal App that just pushes one screen — Textual screens need a running App to
    mount into; this stands in for the real TeetimeApp so each screen can be tested in
    isolation."""

    def __init__(self, screen):
        super().__init__()
        self._screen_to_push = screen
        self.result = "not dismissed yet"

    def on_mount(self):
        self.push_screen(self._screen_to_push, self._capture_result)

    def _capture_result(self, result):
        self.result = result


def _run(coro):
    asyncio.run(coro)


def _day_detail(club_id="0000001", club_slug="musterhausen", course="18 Loch Tee 1", date="2026-09-06"):
    return tui.DayDetailScreen(club_id, club_slug, course, date)


# --- _initial_date -- opens on tomorrow instead of today once today's own cached
# schedule shows every slot has already passed (direct feedback 2026-09-07: showing
# "today" once the course has closed for the day isn't useful) ------------------------


def test_initial_date_returns_today_when_no_cached_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    assert tui._initial_date("0000001", "18 Loch Tee 1") == tui._TODAY()


def test_initial_date_returns_today_when_a_slot_is_still_upcoming(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "14:00")
    schedule = Schedule(date=tui._TODAY(), course="18 Loch Tee 1", slots=[Slot(time="15:00", booked=0, capacity=4)])
    storage.save_schedule(schedule, path=scrape_once._db_path("0000001"))

    assert tui._initial_date("0000001", "18 Loch Tee 1") == tui._TODAY()


def test_initial_date_returns_tomorrow_when_every_slot_has_passed(tmp_path, monkeypatch):
    from datetime import date as date_cls
    from datetime import timedelta

    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "22:00")
    schedule = Schedule(date=tui._TODAY(), course="18 Loch Tee 1", slots=[Slot(time="19:50", booked=0, capacity=4)])
    storage.save_schedule(schedule, path=scrape_once._db_path("0000001"))

    expected = (date_cls.fromisoformat(tui._TODAY()) + timedelta(days=1)).isoformat()
    assert tui._initial_date("0000001", "18 Loch Tee 1") == expected


def test_initial_date_ignores_a_different_course(tmp_path, monkeypatch):
    # Every slot passed, but for a different course -- today's own course has no
    # cached schedule yet, so this should still return today, not tomorrow.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "22:00")
    schedule = Schedule(date=tui._TODAY(), course="9 Loch Tee 1", slots=[Slot(time="19:50", booked=0, capacity=4)])
    storage.save_schedule(schedule, path=scrape_once._db_path("0000001"))

    assert tui._initial_date("0000001", "18 Loch Tee 1") == tui._TODAY()


# --- DayDetailScreen ------------------------------------------------------------------


def test_day_detail_shows_placeholder_when_never_scraped(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert "no data yet" in row[1]

    _run(scenario())


def test_day_detail_shows_occupancy_and_players(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            slots=[
                Slot(time="06:00", booked=0, capacity=4),
                Slot(time="08:00", booked=1, capacity=4, players=["Max Mustermann"]),
                Slot(time="15:30", booked=4, capacity=4, block_reason="Golf Beginner Kurs"),
            ],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.row_count == 3
            rows = [table.get_row_at(i) for i in range(3)]
            assert rows[0][0] == "06:00" and "0/4" in rows[0][1]
            assert rows[1][0] == "08:00" and "1/4" in rows[1][1] and rows[1][2] == "Max Mustermann"
            assert rows[2][0] == "15:30" and "Golf Beginner Kurs" in rows[2][1]

    _run(scenario())


# --- Past-slot dimming (2026-09-07, direct feedback: "can you hide or make
# timeslots less visible that are in the past? ... now is 11:18, so I need a visible
# feedback that I won't be able to make reservations for 11:10 or earlier today") ----


def test_day_detail_dims_past_slots_on_todays_date(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "_TODAY", lambda: "2026-09-07")
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "11:18")
    storage.save_schedule(
        Schedule(
            date="2026-09-07",
            course="18 Loch Tee 1",
            slots=[
                Slot(time="09:00", booked=0, capacity=4),
                Slot(time="11:10", booked=1, capacity=4, players=["Max Mustermann"]),
                Slot(time="14:00", booked=2, capacity=4),
            ],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail(date="2026-09-07"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            rows = [table.get_row_at(i) for i in range(3)]
            assert rows[0][0] == "[dim]09:00[/]"
            assert rows[1][0] == "[dim]11:10[/]"
            assert rows[1][2] == "[dim]Max Mustermann[/]"
            assert rows[2][0] == "14:00"  # still upcoming -- not dimmed

    _run(scenario())


def test_day_detail_does_not_dim_slots_on_a_different_date(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    # "Today" is tomorrow relative to this screen's own date -- late in the day, so
    # every slot on this schedule would be "in the past" if the check didn't first
    # confirm this screen is even showing today at all.
    monkeypatch.setattr(tui, "_TODAY", lambda: "2026-09-08")
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "23:59")
    storage.save_schedule(
        Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="06:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail(date="2026-09-07"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.get_row_at(0)[0] == "06:00"

    _run(scenario())


def test_day_detail_dims_a_blocked_past_slot_too(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "_TODAY", lambda: "2026-09-07")
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "16:00")
    storage.save_schedule(
        Schedule(
            date="2026-09-07",
            course="18 Loch Tee 1",
            slots=[Slot(time="15:30", booked=4, capacity=4, block_reason="Golf Beginner Kurs")],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail(date="2026-09-07"))
        async with app.run_test() as pilot:
            await pilot.pause()
            row = app.screen.query_one(DataTable).get_row_at(0)
            assert row[0] == "[dim]15:30[/]"
            assert "Golf Beginner Kurs" in row[1]

    _run(scenario())


def test_day_detail_shows_and_dismisses_booking_watch_banner(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_booking_change(
        course="18 Loch Tee 1",
        date="2026-09-06",
        time="14:00",
        kind="party_grew",
        message="1 more player joined your 14:00 tee time since you booked",
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            banner = app.screen.query_one("#banners", Static)
            assert "1 more player" in str(banner.content)

            await pilot.press("x")
            await pilot.pause()
            banner = app.screen.query_one("#banners", Static)
            assert str(banner.content) == ""

    _run(scenario())

    remaining = storage.load_unacknowledged_booking_changes(path=scrape_once._db_path("0000001"))
    assert remaining == []


def test_day_detail_next_and_prev_day_reload_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    # Neither fixture date is "today" -- avoids load_schedule()'s past-slot dimming
    # (see the dedicated tests for that below), which would otherwise collide with
    # this test's own exact-text assertions once "today" catches up to 2026-09-07.
    monkeypatch.setattr(tui, "_TODAY", lambda: "2099-01-01")
    db = scrape_once._db_path("0000001")
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="06:00", booked=0, capacity=4)]),
        path=db,
    )
    storage.save_schedule(
        Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="07:00", booked=1, capacity=4)]),
        path=db,
    )

    async def scenario():
        app = _HostApp(_day_detail(date="2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.get_row_at(0)[0] == "07:00"

            await pilot.press("p")
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.get_row_at(0)[0] == "06:00"

    _run(scenario())


def test_day_detail_refresh_scrapes_and_saves(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    fake_schedule = Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=2, capacity=4)])
    monkeypatch.setattr(tui, "scrape_schedule", lambda club_id, course, date: fake_schedule)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.get_row_at(0)[0] == "09:00"
            assert app.screen.query_one("#status", Static).content == "Refreshed."

    _run(scenario())

    loaded = storage.load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001"))
    assert loaded.slots[0].booked == 2


def test_day_detail_refresh_failure_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    def broken_scrape(club_id, course, date):
        raise RuntimeError("no network")

    monkeypatch.setattr(tui, "scrape_schedule", broken_scrape)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            assert "Refresh failed" in str(app.screen.query_one("#status", Static).content)

    _run(scenario())


def test_day_detail_confirm_booking_persists_and_reloads(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()

            app.screen.query_one("#time", Input).value = "14:00"
            app.screen.query_one("#holes", Input).value = "18"
            await pilot.click("#save")
            await pilot.pause()

    _run(scenario())

    booking = storage.load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001"))
    assert booking is not None
    assert booking.time == "14:00"
    assert booking.holes == 18
    assert booking.source == "manual"


def test_confirm_booking_requires_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            assert "Enter a time" in str(app.screen.query_one("#confirm-status", Static).content)
            assert app.result == "not dismissed yet"

    _run(scenario())


def test_confirm_booking_rejects_non_numeric_holes(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#time", Input).value = "14:00"
            app.screen.query_one("#holes", Input).value = "nine"
            await pilot.click("#save")
            await pilot.pause()

            assert "must be a number" in str(app.screen.query_one("#confirm-status", Static).content)

    _run(scenario())


def test_confirm_booking_cancel_dismisses_without_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#cancel")
            await pilot.pause()
            assert app.result is False

    _run(scenario())

    booking = storage.load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001"))
    assert booking is None


# --- Pre-filled confirm form (2026-09-07, direct feedback: "I already selected a
# specific time, and the TUI should know on which course I'm currently focused") -----


def test_confirm_booking_screen_prefills_time_and_holes_when_given():
    async def scenario():
        app = _HostApp(
            tui.ConfirmBookingScreen(
                "0000001", "18 Loch Tee 1", "2026-09-06", default_time="14:00", default_holes=18
            )
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one("#time", Input).value == "14:00"
            assert app.screen.query_one("#holes", Input).value == "18"

    _run(scenario())


def test_confirm_booking_screen_leaves_fields_blank_with_no_defaults():
    async def scenario():
        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one("#time", Input).value == ""
            assert app.screen.query_one("#holes", Input).value == ""

    _run(scenario())


def test_day_detail_action_confirm_prefills_time_from_the_selected_row(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=0, capacity=4), Slot(time="14:00", booked=1, capacity=4)],
    )
    storage.save_schedule(schedule, path=scrape_once._db_path("0000001"))

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one(DataTable).move_cursor(row=1)  # the "14:00" row
            await pilot.press("c")
            await pilot.pause()
            assert app.screen.query_one("#time", Input).value == "14:00"
            # "18 Loch Tee 1" -> 18 holes, derived from the course itself.
            assert app.screen.query_one("#holes", Input).value == "18"

    _run(scenario())


def test_day_detail_action_confirm_leaves_time_blank_with_no_data_scraped_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()  # only the "no data yet" placeholder row exists
            await pilot.press("c")
            await pilot.pause()
            assert app.screen.query_one("#time", Input).value == ""

    _run(scenario())


def test_day_detail_action_confirm_derives_holes_from_a_nine_hole_course(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail(course="9 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert app.screen.query_one("#holes", Input).value == "9"

    _run(scenario())


# --- ClubPickerScreen / CoursePickerScreen ---------------------------------------------


def test_club_picker_dismisses_with_selected_slug():
    async def scenario():
        app = _HostApp(tui.ClubPickerScreen(["home-club", "guest-club"]))
        async with app.run_test() as pilot:
            await pilot.pause()
            option_list = app.screen.query_one(OptionList)
            option_list.highlighted = 1
            await pilot.press("enter")
            await pilot.pause()
            assert app.result == "guest-club"

    _run(scenario())


def test_course_picker_dismisses_with_selected_course():
    async def scenario():
        app = _HostApp(tui.CoursePickerScreen(["18 Loch Tee 1", "9 Loch Tee 1"]))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.result == "18 Loch Tee 1"

    _run(scenario())


# --- TeetimeApp startup flow ------------------------------------------------------------


def test_app_skips_pickers_with_one_club_and_default_course(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    # TeetimeApp.on_mount() applies a theme, which persists to disk -- redirect it
    # away from the real ~/.config/teetime-monitor/config for the duration of the test.
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, tui.DayDetailScreen)
            assert screen.course == "9 Loch Tee 1"
            assert screen.club_id == "0000001"

    _run(scenario())


# --- Auto-refresh (2026-09-07, direct feedback: "can we make autorefresh for the
# maximum timeframe, whenever you run the TUI and at the defined time intervals? I
# think hitting 'r' makes only sense as a manual override") ------------------------


def test_periodic_scrape_runs_once_on_open_with_the_active_slug_and_config(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: ["home-club"])
    club_cfg = {"club_id": "0000001", "default_course": "9 Loch Tee 1"}
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug: club_cfg)

    calls = []

    def fake_scrape(slug, config):
        calls.append((slug, config))
        return []

    monkeypatch.setattr(scrape_once, "scrape_due_for_club", fake_scrape)

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            for _ in range(20):
                if calls:
                    break
                await pilot.pause(0.05)
            assert calls == [("home-club", club_cfg)]

    _run(scenario())


def test_periodic_scrape_reloads_the_day_detail_screen_when_done(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            reload_calls = []
            monkeypatch.setattr(screen, "load_schedule", lambda: reload_calls.append("load"))
            monkeypatch.setattr(screen, "refresh_banners", lambda: reload_calls.append("banners"))

            # Trigger another pass directly rather than waiting on the real interval
            # timer (15 minutes) -- exercises the same _finish_periodic_scrape() path
            # that the timer would eventually reach on its own.
            app._periodic_scrape_running = False
            app._periodic_scrape()

            for _ in range(20):
                if reload_calls:
                    break
                await pilot.pause(0.05)
            assert "load" in reload_calls
            assert "banners" in reload_calls

    _run(scenario())


def test_periodic_scrape_skips_a_new_pass_while_one_is_already_running(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )
    calls = []
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: calls.append(1) or [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            for _ in range(20):  # wait for the automatic on-open pass to finish
                if calls:
                    break
                await pilot.pause(0.05)
            assert calls == [1]

            # Force the flag on to simulate a pass still in flight, and confirm a
            # second call is a genuine no-op -- no additional scrape gets started.
            app._periodic_scrape_running = True
            app._periodic_scrape()
            await pilot.pause(0.1)
            assert calls == [1]

    _run(scenario())


def test_periodic_scrape_shows_refreshing_then_refreshed_status(tmp_path, monkeypatch):
    # Direct feedback 2026-09-07: "I noticed a slight delay between the auto-refresh
    # and seeing the updated schedule. Wouldn't it be better if the tool had a
    # loading screen?" -- a status-line message instead, so the delay is explained
    # without blocking the UI (the whole point of running this in a thread).
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )
    proceed = threading.Event()
    started = threading.Event()

    def fake_scrape(slug, config):
        started.set()
        proceed.wait(timeout=2)
        return []

    monkeypatch.setattr(scrape_once, "scrape_due_for_club", fake_scrape)

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await asyncio.get_event_loop().run_in_executor(None, started.wait, 2)
            await pilot.pause()
            assert "Refreshing" in str(app.screen.query_one("#status", Static).content)

            proceed.set()
            for _ in range(20):
                if "Refreshed" in str(app.screen.query_one("#status", Static).content):
                    break
                await pilot.pause(0.05)
            assert "Refreshed" in str(app.screen.query_one("#status", Static).content)

    _run(scenario())


# --- Switching club/course from the day-detail screen (2026-09-07, direct feedback:
# "how can i switch to a different course from the time schedule menu? It is somehow
# not possible to return to the previous menus like choosing the course or login") --


def test_switch_action_shows_course_picker_ignoring_default_course(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.course == "9 Loch Tee 1"  # the usual startup shortcut

            await pilot.press("s")
            await pilot.pause()
            # Explicitly switching always shows the picker, even though
            # default_course would otherwise skip it.
            assert isinstance(app.screen, tui.CoursePickerScreen)

            app.screen.dismiss("18 Loch Tee 1")
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.course == "18 Loch Tee 1"
            assert app.screen.club_id == "0000001"

    _run(scenario())


def test_switch_action_shows_club_picker_when_multiple_clubs_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: ["home-club", "guest-club"])
    configs = {
        "home-club": {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
        "guest-club": {"club_id": "0352001", "default_course": "18 Loch Tee 1"},
    }
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug: configs[slug])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubPickerScreen)  # more than one saved
            app.screen.dismiss("home-club")
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.club_id == "0000001"

            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubPickerScreen)

            app.screen.dismiss("guest-club")
            await pilot.pause()
            assert isinstance(app.screen, tui.CoursePickerScreen)  # ignores default_course too

            app.screen.dismiss("6 Loch Platz")
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.club_id == "0352001"
            assert app.screen.club_slug == "guest-club"
            assert app.screen.course == "6 Loch Platz"

    _run(scenario())


def test_app_exits_cleanly_with_no_clubs_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()

    _run(scenario())


# --- Themes -------------------------------------------------------------------------


def test_app_applies_resolved_theme_on_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    theme.save_theme("nord", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "nord"

    _run(scenario())


def test_app_persists_theme_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.theme = "green"
            await pilot.pause()

    _run(scenario())

    assert theme.load_saved_theme(tmp_path / "theme-config") == "green"


def test_app_persists_a_native_textual_theme_with_no_brew_launcher_equivalent(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.theme = "monokai"  # a real Textual theme, not one of the 10 named here
            await pilot.pause()

    _run(scenario())

    assert theme.load_saved_theme(tmp_path / "theme-config") == "monokai"


def test_day_detail_t_binding_opens_command_palette(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            from textual.command import CommandPalette

            assert any(isinstance(screen, CommandPalette) for screen in app.screen_stack)

    _run(scenario())


# --- Language (bilingual UI) ----------------------------------------------------------


def test_day_detail_renders_german_table_headers_and_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    i18n.set_language("de")

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert [str(col.label) for col in table.columns.values()] == ["Zeit", "Belegung", "Spieler"]
            row = table.get_row_at(0)
            assert row[1] == "noch keine Daten"

    _run(scenario())


def test_confirm_booking_renders_german_labels_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    i18n.set_language("de")

    async def scenario():
        from textual.widgets import Button

        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert str(app.screen.query_one("#save", Button).label) == "Speichern"
            await pilot.click("#save")
            await pilot.pause()
            assert "Uhrzeit" in str(app.screen.query_one("#confirm-status", Static).content)

    _run(scenario())


def test_app_switch_language_command_rebuilds_day_detail_screen_in_german(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert i18n.get_language() == "en"  # default, per the autouse fixture

            app.action_switch_language()
            await pilot.pause()

            table = app.screen.query_one(DataTable)
            assert [str(col.label) for col in table.columns.values()] == ["Zeit", "Belegung", "Spieler"]

    _run(scenario())

    # The autouse fixture points i18n.CONFIG_FILE at this same tmp_path -- confirms
    # action_switch_language() actually persisted the change, not just applied it live.
    assert i18n.load_saved_language(tmp_path / "not-used-unless-a-test-wants-it") == "de"


def test_day_detail_footer_renders_translated_hints_in_english(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            footer = app.screen.query_one(tui.TranslatedFooter)
            text = footer.render()
            assert "Refresh" in text
            assert "Confirm tee time" in text
            assert "Quit" in text

    _run(scenario())


def test_day_detail_footer_renders_translated_hints_in_german(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    i18n.set_language("de")

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            footer = app.screen.query_one(tui.TranslatedFooter)
            text = footer.render()
            assert "Aktualisieren" in text
            assert "Tee-Zeit bestätigen" in text
            assert "Beenden" in text

    _run(scenario())


def test_day_detail_banner_renders_localized_from_params(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_booking_change(
        course="18 Loch Tee 1",
        date="2026-09-06",
        time="14:00",
        kind="party_grew",
        message="2 more players joined your 14:00 tee time since you booked",
        params={"count": 2, "time": "14:00"},
        path=scrape_once._db_path("0000001"),
    )
    i18n.set_language("de")

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            banner = app.screen.query_one("#banners", Static)
            assert "weitere Spieler sind" in str(banner.content)
            assert "14:00" in str(banner.content)

    _run(scenario())

