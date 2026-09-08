import asyncio
import os

import pytest
from textual.app import App

from src import club_config, club_picker, i18n
from src.club_config import list_clubs, load_club_config
from src.club_picker import ClubSearchScreen, search_club_directory, slugify


@pytest.fixture(autouse=True)
def _english_ui(monkeypatch, tmp_path):
    # Same reasoning as tui.py's/settings_screen.py's identical fixture -- i18n's
    # current language is module-level global state that would otherwise leak
    # between tests.
    monkeypatch.setattr(i18n, "CONFIG_FILE", tmp_path / "not-used-unless-a-test-wants-it")
    i18n.set_language("en")
    yield
    i18n._current_language = None


@pytest.fixture(autouse=True)
def _no_real_geocoding_by_default(monkeypatch):
    """`on_button_pressed()`'s save handler calls
    `club_config.new_club_stub_with_location()` -> `geocode.find_club_location()`
    (added 2026-09-08) on every save -- every test here that reaches the save
    button would otherwise make a real network request to the live Nominatim
    service, same test-isolation gap this project has caught before (e.g.
    `_fake_course_aliases_by_default` in test_tui.py). Confirmed live once, then
    fixed: a spy on `httpx.get` showed a real request actually leaving before this
    fixture existed. Defaults to "nothing found" (`None`) -- a test exercising the
    "location found" path overrides this locally. Patched on `club_config` (where
    the lookup actually lives, shared with `tui.py`'s own `f`-to-favorite path via
    `add_favorite()`), not `club_picker` itself."""
    monkeypatch.setattr(club_config.geocode, "find_club_location", lambda name: None)


@pytest.fixture(autouse=True)
def _restore_pcc_env():
    # CredentialsScreen (pushed automatically when credentials are missing) writes
    # directly to os.environ on save -- bypassing monkeypatch's own undo tracking.
    # Same reasoning/precedent as test_credentials_screen.py's identical fixture.
    original_user = os.environ.get("PCC_USER")
    original_pass = os.environ.get("PCC_PASS")
    yield
    for key, original in (("PCC_USER", original_user), ("PCC_PASS", original_pass)):
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original


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


# --- ClubSearchScreen (real Textual screen, run headlessly via a throwaway host app) --


class _HostApp(App[None]):
    """Minimal App that just pushes ClubSearchScreen -- Screens need a running App to
    mount into; this stands in for tui.py's real TeetimeApp so the screen can be
    tested in isolation, same shape as test_credentials_screen.py's own _HostApp."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__()
        self._args = args
        self._kwargs = kwargs
        self.result: str | None = "not set"

    def on_mount(self) -> None:
        self.push_screen(ClubSearchScreen(*self._args, **self._kwargs), self._on_dismissed)

    def _on_dismissed(self, slug: str | None) -> None:
        self.result = slug


def _fake_fetch_ok(monkeypatch):
    monkeypatch.setattr(club_picker, "fetch_club_directory", lambda club_id, user, password: _DIRECTORY)


def _fake_selected_event(option_id: str):
    class _FakeOption:
        id = option_id

    class _FakeEvent:
        option = _FakeOption()

    return _FakeEvent()


def test_club_picker_pushes_credentials_screen_when_none_configured(tmp_path, monkeypatch):
    # Added 2026-09-07: missing credentials now open CredentialsScreen right there
    # instead of just printing a message and leaving the user to go hand-edit .env --
    # see club_picker.py's own module docstring.
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.delenv("PCC_USER", raising=False)
    monkeypatch.delenv("PCC_PASS", raising=False)

    async def scenario():
        from src.credentials_screen import CredentialsScreen

        app = _HostApp(
            "home-club",
            clubs_dir=tmp_path,
            env_path=tmp_path / ".env",
            template_path=tmp_path / ".env.example",
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, CredentialsScreen)

    asyncio.run(scenario())


def test_club_picker_retries_directory_fetch_after_credentials_saved(monkeypatch, tmp_path):
    # The full happy path: no credentials yet -> CredentialsScreen pops up
    # automatically -> user fills it in -> dismissing with a save retries the fetch
    # that originally failed, without the user having to do anything else.
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.delenv("PCC_USER", raising=False)
    monkeypatch.delenv("PCC_PASS", raising=False)
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        from textual.widgets import OptionList

        app = _HostApp(
            "home-club",
            clubs_dir=tmp_path,
            env_path=tmp_path / ".env",
            template_path=tmp_path / ".env.example",
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#username").value = "someone@example.com"
            app.screen.query_one("#password").value = "hunter2"
            await pilot.click("#save")
            await pilot.pause()
            await pilot.click("#quit")
            await pilot.pause()
            # Back on ClubSearchScreen now, with a real directory loaded.
            app.screen.query_one("#search").value = "leipzig"
            await pilot.pause()
            assert app.screen.query_one("#results", OptionList).option_count == 1

    asyncio.run(scenario())


def test_club_picker_fetches_directory_and_filters_on_search(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        from textual.widgets import OptionList, Static

        app = _HostApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search").value = "golf"
            await pilot.pause()
            results = app.screen.query_one("#results", OptionList)
            assert results.option_count == 3
            assert "3" in str(app.screen.query_one("#status", Static).content)

    asyncio.run(scenario())


def test_club_picker_narrows_to_one_match(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        from textual.widgets import OptionList

        app = _HostApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search").value = "musterhausen"
            await pilot.pause()
            results = app.screen.query_one("#results", OptionList)
            assert results.option_count == 1

    asyncio.run(scenario())


def test_club_picker_selecting_a_result_prefills_slug(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        app = _HostApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search").value = "leipzig"
            await pilot.pause()
            app.screen.on_option_list_option_selected(_fake_selected_event("0491605"))
            await pilot.pause()
            assert app.screen.query_one("#slug").value == "1-golfclub-leipzig-e-v"

    asyncio.run(scenario())


def test_club_picker_save_writes_new_club_stub(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)
    seen = []

    async def scenario():
        app = _HostApp("home-club", clubs_dir=tmp_path, on_saved=seen.append)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search").value = "leipzig"
            await pilot.pause()
            app.screen.on_option_list_option_selected(_fake_selected_event("0491605"))
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    assert seen == ["1-golfclub-leipzig-e-v"]
    saved = load_club_config("1-golfclub-leipzig-e-v", tmp_path)
    assert saved["club_id"] == "0491605"
    assert "1-golfclub-leipzig-e-v" in list_clubs(tmp_path)


# --- Automatic weather location (2026-09-08, direct follow-up: "can the scraper find
# out location data and fill it in automatically on the fly?" -> "yes please build it
# in, it should be automatic for any future club i add") --------------------------


def test_club_picker_save_fills_in_a_location_when_found(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)
    monkeypatch.setattr(club_config.geocode, "find_club_location", lambda name: (50.1234567, 8.1234567))

    async def scenario():
        from textual.widgets import Static

        app = _HostApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search").value = "leipzig"
            await pilot.pause()
            app.screen.on_option_list_option_selected(_fake_selected_event("0491605"))
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            assert "automatically" in str(app.screen.query_one("#status", Static).content)

    asyncio.run(scenario())

    saved = load_club_config("1-golfclub-leipzig-e-v", tmp_path)
    assert saved["location"] == {"lat": 50.1234567, "lon": 8.1234567}


def test_club_picker_save_status_message_when_location_not_found(monkeypatch, tmp_path):
    # The autouse `_no_real_geocoding_by_default` fixture already makes every save
    # in this file behave this way -- this test just confirms the actual status
    # text and that no `location` key gets written when nothing was found.
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        from textual.widgets import Static

        app = _HostApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search").value = "leipzig"
            await pilot.pause()
            app.screen.on_option_list_option_selected(_fake_selected_event("0491605"))
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            assert "couldn't find" in str(app.screen.query_one("#status", Static).content)

    asyncio.run(scenario())

    saved = load_club_config("1-golfclub-leipzig-e-v", tmp_path)
    assert "location" not in saved


def test_club_picker_save_passes_the_clubs_own_name_to_the_geocoder(monkeypatch, tmp_path):
    # A real, if easy-to-make, mistake: passing the club_id or the search query
    # instead of the actual selected club's own name.
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)
    seen_names = []
    monkeypatch.setattr(
        club_config.geocode, "find_club_location", lambda name: seen_names.append(name) or None
    )

    async def scenario():
        app = _HostApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search").value = "leipzig"
            await pilot.pause()
            app.screen.on_option_list_option_selected(_fake_selected_event("0491605"))
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    assert seen_names == ["1. Golfclub Leipzig e.V."]


def test_club_picker_dismisses_with_the_saved_slug_on_quit(monkeypatch, tmp_path):
    # Direct feedback 2026-09-07: this screen is meant to be pushed inline from
    # tui.py's own switch-club flow -- it must report back what was saved (or None)
    # rather than exiting the whole app the way the old standalone-only App did.
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        app = _HostApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search").value = "leipzig"
            await pilot.pause()
            app.screen.on_option_list_option_selected(_fake_selected_event("0491605"))
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            # "q" is a keybinding, not a button here -- call the action directly
            # rather than pilot.press("q"), which would just type into whichever
            # Input has focus instead of triggering it.
            app.screen.action_quit_screen()
            await pilot.pause()
            assert app.result == "1-golfclub-leipzig-e-v"

    asyncio.run(scenario())


def test_club_picker_dismisses_with_none_when_quit_without_saving(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        app = _HostApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_quit_screen()
            await pilot.pause()
            assert app.result is None

    asyncio.run(scenario())


def test_club_picker_save_without_selection_shows_message(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        from textual.widgets import Static

        app = _HostApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            assert "Pick a club" in str(app.screen.query_one("#status", Static).content)

    asyncio.run(scenario())


def test_club_picker_save_rejects_a_slug_already_in_use(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    (tmp_path / "1-golfclub-leipzig-e-v.yaml").write_text("club_id: 'already-here'\n")
    monkeypatch.setenv("PCC_USER", "user@example.com")
    monkeypatch.setenv("PCC_PASS", "hunter2")
    _fake_fetch_ok(monkeypatch)

    async def scenario():
        from textual.widgets import Static

        app = _HostApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search").value = "leipzig"
            await pilot.pause()
            app.screen.on_option_list_option_selected(_fake_selected_event("0491605"))
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            assert "already exists" in str(app.screen.query_one("#status", Static).content)

    asyncio.run(scenario())

    # Untouched -- the pre-existing file at that slug wasn't overwritten.
    assert load_club_config("1-golfclub-leipzig-e-v", tmp_path)["club_id"] == "already-here"


def test_club_picker_footer_renders_translated_hint(monkeypatch, tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    i18n.set_language("de")

    async def scenario():
        from src.club_picker import TranslatedFooter

        app = _HostApp("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            footer = app.screen.query_one(TranslatedFooter)
            assert "Beenden" in footer.render()

    asyncio.run(scenario())
