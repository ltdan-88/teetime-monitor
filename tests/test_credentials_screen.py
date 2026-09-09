import asyncio
import os

import pytest

from src import i18n
from src.credentials_screen import CredentialsScreen
from src.env_file import load_env_value


@pytest.fixture(autouse=True)
def _english_ui(monkeypatch, tmp_path):
    # Same reasoning as every other screen's identical fixture -- i18n's current
    # language is module-level global state that would otherwise leak between tests.
    monkeypatch.setattr(i18n, "CONFIG_FILE", tmp_path / "not-used-unless-a-test-wants-it")
    i18n.set_language("en")
    yield
    i18n._current_language = None


@pytest.fixture(autouse=True)
def _restore_pcc_env():
    # CredentialsScreen writes directly to os.environ on save (see its own docstring
    # for why) -- bypassing monkeypatch's undo tracking, since that only covers
    # changes made through monkeypatch.setenv/delenv themselves, not ones application
    # code makes afterward. Every test in this file that exercises a real save needs
    # this restored regardless: skipping it once already leaked a fake PCC_USER/
    # PCC_PASS into later tests in the same pytest process, which let
    # scrape_once.py's tests skip their "no credentials" guard and fire real (if
    # rejected) login requests at the live pc caddie site.
    original_user = os.environ.get("PCC_USER")
    original_pass = os.environ.get("PCC_PASS")
    yield
    for key, original in (("PCC_USER", original_user), ("PCC_PASS", original_pass)):
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original


# CredentialsScreen is a Screen, not a standalone App -- test it pushed into a
# throwaway App, same shape club_picker.py actually uses it in.
from textual.app import App, ComposeResult  # noqa: E402


class _HostApp(App[None]):
    def __init__(self, env_path, template_path) -> None:
        super().__init__()
        self.env_path = env_path
        self.template_path = template_path
        self.result: bool | None = "not set"

    def on_mount(self) -> None:
        self.push_screen(CredentialsScreen(self.env_path, self.template_path), self._on_dismissed)

    def _on_dismissed(self, saved: bool) -> None:
        self.result = saved


def test_credentials_screen_saves_username_and_password(tmp_path):
    env_path = tmp_path / ".env"

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#username").value = "someone@example.com"
            app.screen.query_one("#password").value = "hunter2"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    assert load_env_value("PCC_USER", env_path) == "someone@example.com"
    assert load_env_value("PCC_PASS", env_path) == "hunter2"


def test_credentials_screen_cancel_without_saving_dismisses_false(tmp_path):
    # Clicking the Cancel button rather than pressing "q" -- an Input has focus on
    # mount, and Textual gives a focused Input first refusal on printable keys
    # (including "q") before any Screen-level binding sees them. Also, "q" now quits
    # the whole app rather than dismissing this screen (2026-09-09 fix, see this
    # module's own BINDINGS comment) -- Cancel-the-button is the only way left to
    # dismiss without saving, so this scenario needs it regardless of that focus
    # detail.
    env_path = tmp_path / ".env"
    seen = []

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        app._on_dismissed = seen.append
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#cancel")
            await pilot.pause()

    asyncio.run(scenario())
    assert seen == [False]


def test_credentials_screen_save_then_close_dismisses_true(tmp_path):
    # "escape," not "q" any more -- q now quits the whole app rather than dismissing
    # this screen (2026-09-09 fix, see this module's own BINDINGS comment).
    env_path = tmp_path / ".env"
    seen = []

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        app._on_dismissed = seen.append
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#username").value = "someone@example.com"
            app.screen.query_one("#password").value = "hunter2"
            await pilot.click("#save")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(scenario())
    assert seen == [True]


def test_credentials_screen_requires_a_username(tmp_path):
    env_path = tmp_path / ".env"

    async def scenario():
        from textual.widgets import Static

        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#password").value = "hunter2"
            await pilot.click("#save")
            await pilot.pause()
            assert "username" in str(app.screen.query_one("#status", Static).content).lower()

    asyncio.run(scenario())
    assert not env_path.exists()


def test_credentials_screen_requires_a_password_when_none_set_yet(tmp_path):
    env_path = tmp_path / ".env"

    async def scenario():
        from textual.widgets import Static

        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#username").value = "someone@example.com"
            await pilot.click("#save")
            await pilot.pause()
            assert "password" in str(app.screen.query_one("#status", Static).content).lower()

    asyncio.run(scenario())
    assert not env_path.exists()


def test_credentials_screen_blank_password_keeps_existing_one(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("PCC_USER=old@example.com\nPCC_PASS=originalpass\n")

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#username").value = "new@example.com"
            # password left blank -- should keep the existing one
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    assert load_env_value("PCC_USER", env_path) == "new@example.com"
    assert load_env_value("PCC_PASS", env_path) == "originalpass"


def test_credentials_screen_prefills_existing_username_not_password(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("PCC_USER=existing@example.com\nPCC_PASS=secretvalue\n")

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one("#username").value == "existing@example.com"
            assert app.screen.query_one("#password").value == ""

    asyncio.run(scenario())


def test_credentials_screen_updates_live_process_environment(monkeypatch, tmp_path):
    # Cleanup is handled by the module's autouse _restore_pcc_env fixture above.
    monkeypatch.delenv("PCC_USER", raising=False)
    monkeypatch.delenv("PCC_PASS", raising=False)
    env_path = tmp_path / ".env"

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#username").value = "someone@example.com"
            app.screen.query_one("#password").value = "hunter2"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    assert os.environ["PCC_USER"] == "someone@example.com"
    assert os.environ["PCC_PASS"] == "hunter2"


def test_credentials_screen_footer_renders_translated_hint(tmp_path):
    i18n.set_language("de")

    async def scenario():
        from src.translated_footer import TranslatedFooter

        app = _HostApp(tmp_path / ".env", tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            footer = app.screen.query_one(TranslatedFooter)
            assert "Beenden" in footer.render()

    asyncio.run(scenario())
