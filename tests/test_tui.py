import asyncio

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

