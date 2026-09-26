import asyncio
import os

import pytest
from textual.app import App

from src import ai_assist, global_preferences, i18n
from src import ai_credentials_screen as ai_credentials_screen_module
from src.ai_credentials_screen import AICredentialsScreen
from src.env_file import load_env_value


@pytest.fixture(autouse=True)
def _isolated_preferences(monkeypatch, tmp_path):
    # AICredentialsScreen writes the active provider via global_preferences'
    # module-level PREFERENCES_FILE (resolved at call time) -- point it at a
    # throwaway file, same reasoning credentials_screen.py's own tests isolate
    # os.environ for PCC_USER/PCC_PASS.
    monkeypatch.setattr(global_preferences, "PREFERENCES_FILE", tmp_path / "preferences.yaml")


@pytest.fixture(autouse=True)
def _restore_env():
    originals = {var: os.environ.get(var) for var in ai_assist.PROVIDER_ENV_VARS.values()}
    yield
    for var, original in originals.items():
        if original is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = original


class _HostApp(App[None]):
    def __init__(self, env_path, template_path) -> None:
        super().__init__()
        self.env_path = env_path
        self.template_path = template_path
        self.result: bool | None = "not set"

    def on_mount(self) -> None:
        self.push_screen(AICredentialsScreen(self.env_path, self.template_path), self._on_dismissed)

    def _on_dismissed(self, saved: bool) -> None:
        self.result = saved


def _mock_verify(monkeypatch, result):
    monkeypatch.setattr(ai_credentials_screen_module.ai_assist, "verify_api_key", lambda provider: result)


def test_saves_a_key_for_the_selected_provider_and_makes_it_active(monkeypatch, tmp_path):
    _mock_verify(monkeypatch, (True, None))
    env_path = tmp_path / ".env"

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#provider").value = "openai"
            app.screen.query_one("#api_key").value = "sk-abc"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    assert load_env_value("OPENAI_API_KEY", env_path) == "sk-abc"
    assert global_preferences.load_preferences()["ai_assist"]["provider"] == "openai"


def test_shows_verified_status_on_success(monkeypatch, tmp_path):
    from textual.widgets import Static

    _mock_verify(monkeypatch, (True, None))
    env_path = tmp_path / ".env"

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#api_key").value = "sk-ant"
            await pilot.click("#save")
            await pilot.pause()
            assert str(app.screen.query_one("#status", Static).content) == i18n.t("ai_credentials.verified")

    asyncio.run(scenario())


def test_shows_rejected_status_without_undoing_the_save(monkeypatch, tmp_path):
    from textual.widgets import Static

    _mock_verify(monkeypatch, (False, None))
    env_path = tmp_path / ".env"

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#api_key").value = "bad-key"
            await pilot.click("#save")
            await pilot.pause()
            assert str(app.screen.query_one("#status", Static).content) == i18n.t("ai_credentials.rejected")

    asyncio.run(scenario())
    # Same rule as CredentialsScreen: a rejected verification doesn't mean "don't
    # write what was typed."
    assert load_env_value("ANTHROPIC_API_KEY", env_path) == "bad-key"


def test_shows_unverified_status_on_a_network_hiccup_not_a_bad_key(monkeypatch, tmp_path):
    from textual.widgets import Static

    _mock_verify(monkeypatch, (False, "no network"))
    env_path = tmp_path / ".env"

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#api_key").value = "sk-ant"
            await pilot.click("#save")
            await pilot.pause()
            status = str(app.screen.query_one("#status", Static).content)
            assert status == i18n.t("ai_credentials.unverified", error="no network")

    asyncio.run(scenario())


def test_requires_an_api_key_when_none_is_set_yet(monkeypatch, tmp_path):
    from textual.widgets import Static

    env_path = tmp_path / ".env"

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            assert str(app.screen.query_one("#status", Static).content) == i18n.t("ai_credentials.api_key_required")

    asyncio.run(scenario())
    assert not env_path.exists()


def test_blank_key_with_an_existing_saved_key_switches_provider_without_rewriting_it(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("XAI_API_KEY=already-saved\n")
    global_preferences.save_preferences({"ai_assist": {"enabled": True, "provider": "anthropic"}})
    seen = []
    monkeypatch.setattr(
        ai_credentials_screen_module.ai_assist, "verify_api_key", lambda provider: (seen.append(provider), (True, None))[1]
    )

    async def scenario():
        app = _HostApp(env_path, tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#provider").value = "grok"
            # api_key left blank -- should keep the existing one and just switch to it
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    assert load_env_value("XAI_API_KEY", env_path) == "already-saved"
    assert global_preferences.load_preferences()["ai_assist"]["provider"] == "grok"
    assert global_preferences.load_preferences()["ai_assist"]["enabled"] is True  # not clobbered
    assert seen == ["grok"]


def test_cancel_without_saving_dismisses_false(tmp_path):
    seen = []

    async def scenario():
        app = _HostApp(tmp_path / ".env", tmp_path / ".env.example")
        app._on_dismissed = seen.append
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#cancel")
            await pilot.pause()

    asyncio.run(scenario())
    assert seen == [False]


def test_updates_live_process_environment_so_verification_sees_the_new_key(monkeypatch, tmp_path):
    seen_env_values = []

    def fake_verify(provider):
        seen_env_values.append(os.environ.get("OPENAI_API_KEY"))
        return True, None

    monkeypatch.setattr(ai_credentials_screen_module.ai_assist, "verify_api_key", fake_verify)

    async def scenario():
        app = _HostApp(tmp_path / ".env", tmp_path / ".env.example")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#provider").value = "openai"
            app.screen.query_one("#api_key").value = "sk-fresh"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())
    assert seen_env_values == ["sk-fresh"]
