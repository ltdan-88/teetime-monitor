import asyncio
import threading

import pytest
from textual.app import App
from textual.widgets import DataTable, Input, OptionList, Static

from src import i18n, scrape_once, storage, theme, tui
from src.club_config import list_clubs as _real_list_clubs
from src.club_config import load_club_config as _real_load_club_config
from src.models import ConfirmedBooking, Schedule, Slot, WeatherPoint


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


@pytest.fixture(autouse=True)
def _no_real_club_config_by_default(monkeypatch):
    """`DayDetailScreen._recommended_times()` (added 2026-09-07) calls
    `club_config.load_club_config(self.club_slug)` on every `load_schedule()` --
    every test here built via `_day_detail()` directly (not through a real
    `TeetimeApp`) never mocks that, and `_day_detail()`'s own default slug
    ("musterhausen") happens to match a real file this developer's own machine has
    on disk at `clubs/musterhausen.yaml` — meaning every such test would otherwise
    silently read real personal config off disk instead of running hermetically.
    Defaults to an empty config (no availability rules configured -> nothing gets
    marked recommended, the same as a genuinely blank club); a test that wants to
    exercise the recommendation-marking feature itself overrides this locally,
    same layering as `_no_background_scraping` above."""
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: {})


@pytest.fixture(autouse=True)
def _fake_course_aliases_by_default(monkeypatch):
    """`TeetimeApp._start()`/`_do_switch_club_or_course()` (both updated 2026-09-07,
    see scraper.py's module docstring on why a club's own course list can no longer be
    assumed from a hardcoded constant) call `fetch_course_aliases(club_id)` live --
    every test here that builds a real `TeetimeApp()` would otherwise make a real
    network request against the live pc caddie site (real club_id "0000001" used
    throughout this file, same test-isolation gap as `_no_background_scraping` above)
    for every single course-picking step. Defaults to Musterhausen's own confirmed
    real course set; a test exercising a *different* club's own courses (e.g. the
    switch-flow tests that add a second, distinct club) overrides this locally."""
    monkeypatch.setattr(
        tui, "fetch_course_aliases", lambda club_id: {"18 Loch Tee 1": "COUB", "9 Loch Tee 1": "COU1", "6 Loch Platz": "COU6"}
    )


@pytest.fixture(autouse=True)
def _fake_available_dates_by_default(monkeypatch):
    """`OverviewScreen.load_overview()` (added 2026-09-07) calls
    `fetch_available_dates(club_id)` live to know which of its day-rows are actually
    open for booking -- every test here that reaches a real `OverviewScreen` would
    otherwise make a real network request, same test-isolation gap as
    `_fake_course_aliases_by_default` above. Defaults to "every attempted date is
    open" (an empty real fetch result also means this, per that function's own
    fallback, so this mirrors the common case) rather than a fixed list, since tests
    seed schedules for whatever dates they need regardless."""
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])


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


async def _reach_overview(app, pilot, club_id="0000001"):
    """Drive the club-first startup flow (2026-09-07) up to the multi-day overview --
    the app's actual home screen once a club/course is picked.

    The app now always opens on `ClubBrowserScreen` — a club no longer has to be saved
    to config before it can be looked at, so there's no "only one saved club, skip the
    picker" shortcut at launch any more."""
    await pilot.pause()
    assert isinstance(app.screen, tui.ClubBrowserScreen)
    app.screen.dismiss(club_id)
    await pilot.pause()
    await pilot.pause()
    assert isinstance(app.screen, tui.OverviewScreen)


async def _reach_day_detail(app, pilot, club_id="0000001"):
    """As `_reach_overview()`, then drills into the first day row -- for the many
    existing tests written against `DayDetailScreen` directly, from before
    `OverviewScreen` (added 2026-09-07) became the actual screen a club/course pick
    lands on."""
    await _reach_overview(app, pilot, club_id)
    table = app.screen.query_one(DataTable)
    table.focus()  # cursor already defaults to row 0 -- today's own row
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


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


# --- Recommended-slot marking ("★") -- a lightweight step toward real
# recommendations (ROADMAP.md Phase 3), applied to the single-day view already built
# rather than waiting on the multi-day overview screen's own mockup sign-off ----------

_RECOMMEND_CONFIG = {
    "availability": {
        "min_open_spots": 1,
        "weekday_window": {"after": "10:00"},
        "weekend_window": {"after": "10:00"},
    }
}


def test_day_detail_marks_slots_matching_availability_with_a_star(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: _RECOMMEND_CONFIG)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            slots=[
                Slot(time="09:00", booked=0, capacity=4),  # before the configured window
                Slot(time="14:00", booked=0, capacity=4),  # within the window, open
            ],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            rows = [table.get_row_at(i) for i in range(2)]
            assert rows[0][0] == "09:00"
            assert rows[1][0] == "★ 14:00"

    _run(scenario())


def test_day_detail_does_not_star_a_fully_booked_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: _RECOMMEND_CONFIG)
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=4, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one(DataTable).get_row_at(0)[0] == "14:00"

    _run(scenario())


def test_day_detail_does_not_star_a_past_matching_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: _RECOMMEND_CONFIG)
    monkeypatch.setattr(tui, "_TODAY", lambda: "2026-09-07")
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "15:00")
    storage.save_schedule(
        Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail(date="2026-09-07"))
        async with app.run_test() as pilot:
            await pilot.pause()
            row = app.screen.query_one(DataTable).get_row_at(0)
            # Still dimmed (it's past), but not starred -- recommending something
            # already gone doesn't make sense.
            assert row[0] == "[dim]14:00[/]"

    _run(scenario())


def test_day_detail_does_not_star_a_slot_with_bad_weather(tmp_path, monkeypatch):
    from src.models import WeatherPoint

    config = {
        "availability": _RECOMMEND_CONFIG["availability"],
        "preferences": {"avoid_rain": True},
    }
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: config)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            slots=[Slot(time="14:00", booked=0, capacity=4)],
            weather=[WeatherPoint(time="14:00", precipitation_probability=90, precipitation_mm=5.0)],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one(DataTable).get_row_at(0)[0] == "14:00"  # not starred

    _run(scenario())


def test_day_detail_no_availability_config_means_no_stars(tmp_path, monkeypatch):
    # The autouse _no_real_club_config_by_default fixture already returns {} by
    # default -- this test just makes that behavior explicit and named.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one(DataTable).get_row_at(0)[0] == "14:00"

    _run(scenario())


def test_day_detail_action_confirm_prefills_clean_time_for_a_starred_slot(tmp_path, monkeypatch):
    # Regression test: the confirm form must get the plain "14:00" back, never the
    # decorated "★ 14:00" that's actually rendered in the table.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: _RECOMMEND_CONFIG)
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one(DataTable).get_row_at(0)[0] == "★ 14:00"  # sanity check
            await pilot.press("c")
            await pilot.pause()
            assert app.screen.query_one("#time", Input).value == "14:00"

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


def test_day_detail_escape_pops_back_to_the_overview_and_reloads_it(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        overview = tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1")
        app = _HostApp(overview)
        async with app.run_test() as pilot:
            await pilot.pause()
            reload_calls = []
            monkeypatch.setattr(overview, "load_overview", lambda: reload_calls.append("reload"))
            await app.push_screen(_day_detail())
            await pilot.pause()
            assert isinstance(app.screen, tui.DayDetailScreen)

            await pilot.press("escape")
            await pilot.pause()

            assert app.screen is overview
            assert reload_calls == ["reload"]

    _run(scenario())


def test_day_detail_escape_pops_quietly_with_no_overview_underneath():
    # Reached directly (a test, or any future standalone entry point) rather than
    # via OverviewScreen's own drill-down -- popping back to whatever's actually
    # there (here, the test harness's own blank base screen) must not raise, and
    # load_overview() is simply never called since it isn't an OverviewScreen.
    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, tui.DayDetailScreen)

    _run(scenario())


# --- OverviewScreen (ROADMAP.md Phase 4) -- pure helper functions first --------------


def _weather(time, prob=10, temp=20.0):
    return WeatherPoint(time=time, precipitation_probability=prob, temperature_c=temp)


def test_heat_strip_blocks_colors_by_average_fill_ratio():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="08:10", booked=0, capacity=4),  # 08-10 window: open
            Slot(time="10:10", booked=2, capacity=4),  # 10-12 window: mid
            Slot(time="18:10", booked=4, capacity=4),  # 18-20 window: full
        ],
    )
    blocks = tui._heat_strip_blocks(schedule)
    assert blocks[0] == "open"
    assert blocks[1] == "mid"
    assert blocks[5] == "full"


def test_heat_strip_blocks_is_blocked_with_no_real_slot_in_the_window():
    # Nothing at all in 12-14, and an event fills every slot in 14-16 -- both read as
    # "blocked", not a fill ratio that would be meaningless (0 slots) or misleading
    # (an event isn't real occupancy, see scraper.py's module docstring).
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="14:10", booked=4, capacity=4, block_reason="Golf Beginner Kurs")],
    )
    blocks = tui._heat_strip_blocks(schedule)
    assert blocks[2] == "blocked"  # 12-14, no slot at all
    assert blocks[3] == "blocked"  # 14-16, only an event


def test_is_rain_all_day_true_when_every_daytime_point_is_wet():
    weather = [_weather("09:00", prob=80), _weather("15:00", prob=90)]
    assert tui._is_rain_all_day(weather) is True


def test_is_rain_all_day_false_when_only_part_of_the_day_is_wet():
    weather = [_weather("09:00", prob=90), _weather("15:00", prob=5)]
    assert tui._is_rain_all_day(weather) is False


def test_is_rain_all_day_false_with_no_weather_at_all():
    assert tui._is_rain_all_day([]) is False


def test_weather_summary_shows_sun_icon_and_temp_range():
    weather = [_weather("09:00", prob=5, temp=22.0), _weather("15:00", prob=10, temp=14.0)]
    assert tui._weather_summary(weather) == "☀ 22°/14°"


def test_weather_summary_shows_partial_cloud_icon_once_rain_is_plausible():
    weather = [_weather("09:00", prob=40, temp=18.0)]
    assert tui._weather_summary(weather).startswith("⛅")


def test_weather_summary_none_without_daytime_forecast():
    assert tui._weather_summary([]) is None


def test_day_tag_prefers_a_tournament_over_rain_or_weather():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[],
        weather=[_weather("09:00", prob=95)],
        events=["Herbstturnier"],
    )
    assert tui._day_tag_or_weather(schedule) == "🏆 Herbstturnier"


def test_day_tag_shows_rain_all_day_over_a_plain_weather_line():
    schedule = Schedule(
        date="2026-09-07", course="18 Loch Tee 1", slots=[], weather=[_weather("09:00", prob=95)]
    )
    assert "rain all day" in tui._day_tag_or_weather(schedule)


def test_day_tag_falls_back_to_the_weather_summary():
    schedule = Schedule(
        date="2026-09-07", course="18 Loch Tee 1", slots=[], weather=[_weather("09:00", prob=5, temp=20.0)]
    )
    assert tui._day_tag_or_weather(schedule) == "☀ 20°/20°"


def test_availability_pipeline_empty_without_availability_configured():
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)])
    assert tui._availability_pipeline(schedule, {}) == ([], [])


def test_day_pick_text_shows_a_confirmed_booking_first():
    booking = ConfirmedBooking(date="2026-09-07", course="18 Loch Tee 1", time="14:00", source="manual")
    text = tui._day_pick_text(None, {}, booking, has_pending_change=False)
    assert "14:00" in text
    assert "📌" in text
    assert "⚠" not in text


def test_day_pick_text_flags_a_pending_booking_watch_change():
    booking = ConfirmedBooking(date="2026-09-07", course="18 Loch Tee 1", time="14:00", source="manual")
    text = tui._day_pick_text(None, {}, booking, has_pending_change=True)
    assert "⚠" in text


def test_day_pick_text_dash_without_availability_configured():
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)])
    assert tui._day_pick_text(schedule, {}, None, False) == "[dim]—[/]"


def test_day_pick_text_stars_the_earliest_playable_match():
    config = {"availability": {"weekday_window": {"after": "08:00"}}}
    schedule = Schedule(
        date="2026-09-07",  # a Monday
        course="18 Loch Tee 1",
        slots=[Slot(time="10:00", booked=0, capacity=4), Slot(time="09:00", booked=0, capacity=4)],
    )
    assert tui._day_pick_text(schedule, config, None, False) == "[yellow]★[/] 09:00"


def test_day_pick_text_no_dry_picks_when_weather_excludes_everything():
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "preferences": {"avoid_rain": True},
    }
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=0, capacity=4)],
        weather=[_weather("09:00", prob=90)],
    )
    assert "no dry picks" in tui._day_pick_text(schedule, config, None, False)


# --- OverviewScreen itself ------------------------------------------------------------


def test_overview_screen_shows_a_row_per_attempted_day(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.row_count == 5  # club.example.yaml's overview_days default

    _run(scenario())


def test_overview_screen_greys_out_a_date_the_club_has_not_opened_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [tui._TODAY()])  # only today

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            row = table.get_row_at(1)  # tomorrow -- not in the real open-dates set
            assert "not open" in row[3]

    _run(scenario())


def test_overview_screen_shows_no_data_placeholder_for_an_unscraped_open_day(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            row = app.screen.query_one(DataTable).get_row_at(0)
            assert "…" in row[1]

    _run(scenario())


def test_overview_screen_hides_picks_section_without_availability_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: {})
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert str(app.screen.query_one("#picks", Static).content) == ""

    _run(scenario())


def test_overview_screen_shows_picks_once_availability_is_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        tui.club_config, "load_club_config",
        lambda slug, *a, **k: {"availability": {"weekday_window": {"after": "08:00"}}},
    )
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])
    storage.save_schedule(
        Schedule(date=tui._TODAY(), course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            content = str(app.screen.query_one("#picks", Static).content)
            assert "This week's picks" in content
            assert "09:00" in content

    _run(scenario())


def test_overview_screen_row_selected_opens_that_dates_day_detail_screen(tmp_path, monkeypatch):
    from datetime import date as date_cls
    from datetime import timedelta

    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])
    tomorrow = (date_cls.fromisoformat(tui._TODAY()) + timedelta(days=1)).isoformat()

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            table.focus()
            await pilot.press("down")  # tomorrow's row
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.date == tomorrow

    _run(scenario())


def test_overview_screen_footer_says_enter_opens_a_day(tmp_path, monkeypatch):
    # Direct feedback 2026-09-07: "the club selector also doesn't say that you need
    # to hit enter" -- true of every screen here that opens something via Textual's
    # own built-in Enter behavior (OptionList/DataTable), not a real BINDINGS entry
    # this app declares, which is exactly why it never showed up in the footer on its
    # own anywhere. Checked here for OverviewScreen; see the matching ClubBrowserScreen
    # and CoursePickerScreen tests below for the other two.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            text = app.screen.query_one(tui.TranslatedFooter).render()
            assert "enter" in text and "Open" in text

    _run(scenario())


def test_overview_screen_club_visited_not_saved_has_no_availability_computed(tmp_path, monkeypatch):
    # club_slug=None (a club reached by id, never favorited) must not try to load a
    # config file that doesn't exist -- same handling as DayDetailScreen's own.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", None, "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert str(app.screen.query_one("#picks", Static).content) == ""

    _run(scenario())


# --- ClubBrowserScreen / CoursePickerScreen --------------------------------------------


def test_club_browser_footer_says_enter_opens_a_club(monkeypatch):
    # Direct feedback 2026-09-07: "the club selector also doesn't say that you need
    # to hit enter" -- see OverviewScreen's matching test above for the fuller note.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            text = app.screen.query_one(tui.TranslatedFooter).render()
            assert "enter" in text and "Open" in text

    _run(scenario())


def test_club_browser_status_mentions_enter_once_matches_are_shown(monkeypatch):
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(
        tui.club_directory, "load_cached_directory", lambda *a, **k: [("0491605", "1. Golfclub Leipzig e.V.")]
    )

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "leipzig"
            await pilot.pause()
            status = str(app.screen.query_one("#club-status", Static).content)
            assert "enter" in status

    _run(scenario())


def test_club_browser_lists_favorites_and_dismisses_with_the_club_id(tmp_path, monkeypatch):
    # An empty search box lists your favorites -- no directory and no login involved.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club", "guest-club"])
    configs = {"home-club": {"club_id": "0000001"}, "guest-club": {"club_id": "0352001"}}
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: configs[slug])
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda *a, **k: True)
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            option_list = app.screen.query_one(OptionList)
            assert option_list.option_count == 2
            option_list.focus()  # focus starts in the search box, not the list
            option_list.highlighted = 1
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            # Dismisses with the club's numeric pc caddie id, not a local slug --
            # the id is what every scraper call actually needs, and a club reached
            # from the directory has no slug at all.
            assert app.result == "0352001"

    _run(scenario())


def test_club_browser_offers_a_typed_club_id_directly(tmp_path, monkeypatch):
    # The path that needs neither the directory cache nor credentials -- and the only
    # way to reach a club on a brand-new install, before any login exists.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda *a, **k: False)
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "000001"
            await pilot.pause()
            option_list = app.screen.query_one(OptionList)
            assert option_list.option_count == 1
            option_list.focus()  # focus starts in the search box, not the list
            option_list.highlighted = 0
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.result == "0000001"  # normalized to 7 digits

    _run(scenario())


def test_club_browser_enter_in_the_search_box_opens_the_result(tmp_path, monkeypatch):
    # Caught in a live run, not by the other tests here (which drive the OptionList
    # directly): focus stays in the Input, so without an Input.Submitted handler
    # typing a club id showed the right result and then Enter did nothing at all.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda *a, **k: False)
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).focus()
            await pilot.press(*"0352002")
            await pilot.pause()
            await pilot.press("enter")  # never leaves the search box
            await pilot.pause()
            assert app.result == "0352002"

    _run(scenario())


def test_club_browser_does_not_use_the_open_by_id_prompt_as_a_club_name(tmp_path, monkeypatch):
    # "open this club" is a prompt, not a name -- it was ending up as the tee sheet's
    # own window title for any club reached by id (caught live).
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda *a, **k: False)
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "0352002"
            await pilot.pause()
            assert app.screen._names == {}

    _run(scenario())


def test_club_browser_searches_the_cached_directory_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda *a, **k: False)
    monkeypatch.setattr(
        tui.club_directory, "load_cached_directory",
        lambda *a, **k: [("0491605", "1. Golfclub Leipzig e.V."), ("0000001", "Golfclub Musterhausen")],
    )

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "leipzig"
            await pilot.pause()
            option_list = app.screen.query_one(OptionList)
            assert option_list.option_count == 1
            option_list.focus()  # focus starts in the search box, not the list
            option_list.highlighted = 0
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.result == "0491605"

    _run(scenario())


def test_club_browser_f_toggles_favorite(tmp_path, monkeypatch):
    monkeypatch.setattr(tui.club_config, "CLUBS_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory",
                        lambda *a, **k: [("0000001", "Golfclub Musterhausen")])
    added = []
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda club_id, *a, **k: club_id in added)
    monkeypatch.setattr(tui.club_config, "add_favorite",
                        lambda club_id, name="", *a, **k: added.append(club_id) or "slug")

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "musterhausen"
            await pilot.pause()
            # Deliberately does NOT set `highlighted` -- with focus still in the
            # search box Textual highlights nothing, and `f` silently did nothing at
            # exactly the moment the one obvious target was on screen (caught live).
            app.screen.action_toggle_favorite()
            await pilot.pause()
            assert added == ["0000001"]

    _run(scenario())


def test_course_picker_footer_says_enter_opens_a_course():
    # Same gap, same fix as ClubBrowserScreen/OverviewScreen -- see their tests above.
    async def scenario():
        app = _HostApp(tui.CoursePickerScreen(["18 Loch Tee 1", "9 Loch Tee 1"]))
        async with app.run_test() as pilot:
            await pilot.pause()
            text = app.screen.query_one(tui.TranslatedFooter).render()
            assert "enter" in text and "Open" in text

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


def test_app_opens_the_club_browser_then_honors_default_course(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    # TeetimeApp.on_mount() applies a theme, which persists to disk -- redirect it
    # away from the real ~/.config/teetime-monitor/config for the duration of the test.
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            # The club browser is the home screen now, always -- but once a club is
            # picked, a favorite's own default_course still skips the course picker.
            await _reach_day_detail(app, pilot)
            screen = app.screen
            assert isinstance(screen, tui.DayDetailScreen)
            assert screen.course == "9 Loch Tee 1"
            assert screen.club_id == "0000001"
            assert screen.club_slug == "home-club"  # resolved from the club id

    _run(scenario())


# --- Auto-refresh (2026-09-07, direct feedback: "can we make autorefresh for the
# maximum timeframe, whenever you run the TUI and at the defined time intervals? I
# think hitting 'r' makes only sense as a manual override") ------------------------


def test_periodic_scrape_runs_once_on_open_with_the_active_slug_and_config(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    club_cfg = {"club_id": "0000001", "default_course": "9 Loch Tee 1"}
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: club_cfg)

    calls = []

    def fake_scrape(slug, config):
        calls.append((slug, config))
        return []

    monkeypatch.setattr(scrape_once, "scrape_due_for_club", fake_scrape)

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            for _ in range(20):
                if calls:
                    break
                await pilot.pause(0.05)
            assert calls == [("home-club", club_cfg)]

    _run(scenario())


def test_periodic_scrape_still_runs_for_a_club_visited_without_saving_it(tmp_path, monkeypatch):
    # Direct feedback 2026-09-07: "I selected a random club... the tee times don't
    # automatically refresh, I had to hit 'r'". Root cause: an unsaved club's config
    # is {} (nothing to load club_id back out of), and scrape_due_for_club() silently
    # does nothing at all without a club_id in the config it's handed -- auto-refresh
    # was never running for any club that wasn't a saved favorite, the exact case the
    # same-day favorites rework was supposed to make first-class.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])  # no favorites at all
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    calls = []
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: calls.append(config) or [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            app.screen.dismiss("0352002")  # a club reached by id, never saved
            await pilot.pause()
            assert isinstance(app.screen, tui.CoursePickerScreen)
            app.screen.dismiss("18 Loch Tee 1")
            for _ in range(20):
                if calls:
                    break
                await pilot.pause(0.05)
            assert calls and calls[0].get("club_id") == "0352002"

    _run(scenario())


def test_periodic_scrape_reloads_the_day_detail_screen_when_done(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
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
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )
    calls = []
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: calls.append(1) or [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
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
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )
    proceed = threading.Event()
    started = threading.Event()

    def fake_scrape(slug, config):
        started.set()
        proceed.wait(timeout=2)
        return []

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            # Reach day detail first, on the fast no-op scrape the autouse fixture
            # already installs -- only then swap in the slow one and trigger it
            # directly (same pattern as the sibling periodic_scrape tests above).
            # Racing the slow scrape against _reach_day_detail's own navigation
            # (through OverviewScreen, added 2026-09-07) would show "Refreshing…" on
            # whichever screen was current when the scrape *started*, not the one
            # navigated to afterward -- a real but narrow inconsistency, not what
            # this test is actually about.
            await _reach_day_detail(app, pilot)
            monkeypatch.setattr(scrape_once, "scrape_due_for_club", fake_scrape)
            app._periodic_scrape_running = False
            app._periodic_scrape()

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
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.course == "9 Loch Tee 1"  # default_course, honored at launch

            await pilot.press("s")
            await pilot.pause()
            # Switching opens the very same club browser the app launches into.
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            app.screen.dismiss("0000001")
            await pilot.pause()
            # ...and always shows the course picker, even though default_course
            # would otherwise skip it.
            assert isinstance(app.screen, tui.CoursePickerScreen)

            app.screen.dismiss("18 Loch Tee 1")
            await pilot.pause()
            await pilot.pause()
            # Switching lands back on the overview (its own home screen), not
            # directly on a DayDetailScreen -- pops back to the app's base first,
            # so the old DayDetailScreen this switch started from isn't left buried
            # underneath.
            assert isinstance(app.screen, tui.OverviewScreen)
            assert app.screen.course == "18 Loch Tee 1"
            assert app.screen.club_id == "0000001"
            assert len(app.screen_stack) == 2  # base + the one fresh OverviewScreen

    _run(scenario())


def test_switch_action_shows_club_picker_when_multiple_clubs_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club", "guest-club"])
    configs = {
        "home-club": {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
        "guest-club": {"club_id": "0352001", "default_course": "18 Loch Tee 1"},
    }
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: configs[slug])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.club_id == "0000001"

            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)

            app.screen.dismiss("0352001")
            await pilot.pause()
            assert isinstance(app.screen, tui.CoursePickerScreen)  # ignores default_course too

            app.screen.dismiss("6 Loch Platz")
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, tui.OverviewScreen)
            assert app.screen.club_id == "0352001"
            assert app.screen.club_slug == "guest-club"
            assert app.screen.course == "6 Loch Platz"

    _run(scenario())


# --- ClubPickerScreen / CoursePickerScreen: escape backs out, q quits (2026-09-07,
# direct feedback: "how do I quit from club/course picker or return to the
# schedule?" -- there was previously no way to back out short of force-quitting) ----


def test_club_browser_escape_dismisses_with_none(monkeypatch):
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen(allow_cancel=True))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_cancel()
            await pilot.pause()
            assert app.result is None

    _run(scenario())


def test_club_browser_escape_does_nothing_when_cancel_is_disallowed(monkeypatch):
    # At launch there's nothing behind the club list to go back to, so escape must
    # not drop the user onto a blank app.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen(allow_cancel=False))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_cancel()
            await pilot.pause()
            assert app.result == "not dismissed yet"

    _run(scenario())


def test_course_picker_screen_escape_dismisses_with_none():
    async def scenario():
        app = _HostApp(tui.CoursePickerScreen(["18 Loch Tee 1", "9 Loch Tee 1"]))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_cancel()
            await pilot.pause()
            assert app.result is None

    _run(scenario())


# --- Switching club/course: backing out at any step leaves the schedule unchanged,
# and searching for a new club integrates directly into the same flow (2026-09-07,
# direct feedback: "I want to be able to switch clubs on the fly. It is a hassle if
# you need to first save clubs into the config") --------------------------------------


def test_switch_action_cancelling_club_picker_leaves_schedule_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            original_screen = app.screen
            assert isinstance(original_screen, tui.DayDetailScreen)

            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            app.screen.action_cancel()
            await pilot.pause()

            assert app.screen is original_screen
            assert app.screen.course == "9 Loch Tee 1"

    _run(scenario())


def test_switch_action_cancelling_course_picker_leaves_schedule_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            original_screen = app.screen

            await pilot.press("s")
            await pilot.pause()
            app.screen.dismiss("0000001")  # the only real club
            await pilot.pause()
            assert isinstance(app.screen, tui.CoursePickerScreen)
            app.screen.action_cancel()
            await pilot.pause()

            assert app.screen is original_screen
            assert app.screen.course == "9 Loch Tee 1"

    _run(scenario())


def test_switch_action_reaches_an_unsaved_club_from_the_directory(tmp_path, monkeypatch):
    """Switching to a club that was never saved to config -- the whole point of the
    2026-09-07 rework. The old flow needed a club saved to clubs/*.yaml before it could
    be opened at all; now a directory hit is enough, and saving is purely optional
    (the `f` favorite toggle, tested separately)."""
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    (tmp_path / "clubs").mkdir()
    (tmp_path / "clubs" / "home-club.yaml").write_text("club_id: '0000001'\ndefault_course: '18 Loch Tee 1'\n")
    monkeypatch.setattr(tui.club_config, "CLUBS_DIR", tmp_path / "clubs")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: _real_list_clubs(tmp_path / "clubs"))
    monkeypatch.setattr(
        tui.club_config, "load_club_config", lambda slug, *a, **k: _real_load_club_config(slug, tmp_path / "clubs")
    )
    monkeypatch.setattr(
        tui.club_directory, "load_cached_directory",
        lambda *a, **k: [("0491605", "1. Golfclub Leipzig e.V.")],
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.club_slug == "home-club"

            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            app.screen.query_one("#club-search", Input).value = "leipzig"
            await pilot.pause()
            options = app.screen.query_one(OptionList)
            assert options.option_count == 1
            options.focus()
            options.highlighted = 0
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # Straight into course-picking for a club that has no clubs/*.yaml at all.
            assert isinstance(app.screen, tui.CoursePickerScreen)
            app.screen.dismiss("9 Loch Tee 1")
            await pilot.pause()
            await pilot.pause()

            assert isinstance(app.screen, tui.OverviewScreen)
            assert app.screen.club_id == "0491605"
            assert app.screen.club_slug is None  # visited, not saved
            assert app.screen.course == "9 Loch Tee 1"

    _run(scenario())

    # Nothing was written to config -- visiting a club must not save it.
    assert tui.club_config.list_clubs(tmp_path / "clubs") == ["home-club"]


def _fake_option_selected(option_id: str):
    class _FakeOption:
        id = option_id

    class _FakeEvent:
        option = _FakeOption()

    return _FakeEvent()


def test_app_exits_cleanly_with_no_clubs_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])

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
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "nord"

    _run(scenario())


def test_app_persists_theme_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])

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
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])

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
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
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

