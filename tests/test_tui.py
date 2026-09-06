import asyncio

from textual.app import App
from textual.widgets import DataTable, Input, OptionList, Static

from src import scrape_once, storage, tui
from src.models import Schedule, Slot


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


def test_app_exits_cleanly_with_no_clubs_saved(monkeypatch):
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()

    _run(scenario())
