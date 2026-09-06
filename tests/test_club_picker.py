import asyncio

import pytest

from src import club_picker, i18n
from src.club_config import list_clubs, load_club_config
from src.club_picker import ClubPickerApp, search_club_directory, slugify


@pytest.fixture(autouse=True)
def _english_ui(monkeypatch, tmp_path):
    # Same reasoning as tui.py's/settings_screen.py's identical fixture -- i18n's
    # current language is module-level global state that would otherwise leak
    # between tests.
    monkeypatch.setattr(i18n, "CONFIG_FILE", tmp_path / "not-used-unless-a-test-wants-it")
    i18n.set_language("en")
    yield
    i18n._current_language = None


_DIRECTORY = [
    ("0352001", "Golf Club Grand Ducal de Luxembourg"),
    ("0491605", "1. Golfclub Leipzig e.V."),
    ("0000001", "Golfclub Domäne Musterhausen e.V."),
]


# --- search_club_directory ---------------------------------------------------


def test_search_club_directory_matches_case_insensitively():
    assert search_club_directory(_DIRECTORY, "musterhausen") == [("0000001", "Golfclub Domäne Musterhausen e.V.")]


def test_search_club_directory_matches_substring_anywhere():
    assert search_club_directory(_DIRECTORY, "leipzig") == [("0491605", "1. Golfclub Leipzig e.V.")]


def test_search_club_directory_blank_query_returns_nothing():
    assert search_club_directory(_DIRECTORY, "") == []
    assert search_club_directory(_DIRECTORY, "   ") == []


def test_search_club_directory_no_match_returns_empty():
    assert search_club_directory(_DIRECTORY, "nonexistent club xyz") == []


# --- slugify -------------------------------------------------------------------


def test_slugify_basic_name():
    assert slugify("Golfclub Leipzig") == "golfclub-leipzig"


def test_slugify_folds_umlauts():
    assert slugify("Golfclub Domäne Musterhausen e.V.") == "golfclub-domane-musterhausen-e-v"


def test_slugify_empty_name_falls_back_to_placeholder():
    assert slugify("") == "club"
    assert slugify("---") == "club"


# --- ClubPickerApp (real Textual app, run headlessly) -------------------------


def _fake_fetch_ok(monkeypatch):
    monkeypatch.setattr(club_picker, "fetch_club_directory", lambda club_id, user, password: _DIRECTORY)


def test_club_picker_shows_no_credentials_message(tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")

    async def scenario():
        from textual.widgets import Static

        app = ClubPickerApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "PCC_USER" in str(app.query_one("#status", Static).content)

    asyncio.run(scenario())


def test_club_picker_fetches_directory_and_filters_on_search(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        from textual.widgets import OptionList, Static

        app = ClubPickerApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#search").value = "golf"
            await pilot.pause()
            results = app.query_one("#results", OptionList)
            assert results.option_count == 3
            assert "3" in str(app.query_one("#status", Static).content)

    asyncio.run(scenario())


def test_club_picker_narrows_to_one_match(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        from textual.widgets import OptionList

        app = ClubPickerApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#search").value = "musterhausen"
            await pilot.pause()
            results = app.query_one("#results", OptionList)
            assert results.option_count == 1

    asyncio.run(scenario())


def test_club_picker_selecting_a_result_prefills_slug(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        app = ClubPickerApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#search").value = "leipzig"
            await pilot.pause()
            app.on_option_list_option_selected(_fake_selected_event("0491605"))
            await pilot.pause()
            assert app.query_one("#slug").value == "1-golfclub-leipzig-e-v"

    asyncio.run(scenario())


def _fake_selected_event(option_id: str):
    class _FakeOption:
        id = option_id

    class _FakeEvent:
        option = _FakeOption()

    return _FakeEvent()


def test_club_picker_save_writes_new_club_stub(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)
    seen = []

    async def scenario():
        app = ClubPickerApp("home-club", clubs_dir=tmp_path, on_saved=seen.append)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#search").value = "leipzig"
            await pilot.pause()
            app.on_option_list_option_selected(_fake_selected_event("0491605"))
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    assert seen == ["1-golfclub-leipzig-e-v"]
    saved = load_club_config("1-golfclub-leipzig-e-v", tmp_path)
    assert saved["club_id"] == "0491605"
    assert "1-golfclub-leipzig-e-v" in list_clubs(tmp_path)


def test_club_picker_save_without_selection_shows_message(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        from textual.widgets import Static

        app = ClubPickerApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            assert "Pick a club" in str(app.query_one("#status", Static).content)

    asyncio.run(scenario())


def test_club_picker_save_rejects_a_slug_already_in_use(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    (tmp_path / "1-golfclub-leipzig-e-v.yaml").write_text("club_id: 'already-here'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        from textual.widgets import Static

        app = ClubPickerApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#search").value = "leipzig"
            await pilot.pause()
            app.on_option_list_option_selected(_fake_selected_event("0491605"))
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            assert "already exists" in str(app.query_one("#status", Static).content)

    asyncio.run(scenario())

    # Untouched -- the pre-existing file at that slug wasn't overwritten.
    assert load_club_config("1-golfclub-leipzig-e-v", tmp_path)["club_id"] == "already-here"


def test_club_picker_footer_renders_translated_hint(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    i18n.set_language("de")

    async def scenario():
        from src.club_picker import TranslatedFooter

        app = ClubPickerApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            footer = app.query_one(TranslatedFooter)
            assert "Beenden" in footer.render()

    asyncio.run(scenario())
