"""A Textual screen for setting up an AI provider's API key — the AI-side counterpart
to `credentials_screen.py`'s pc caddie login screen, added 2026-09-26 direct follow-up
to shipping AI ranking's own toggle: turning `ai_assist.enabled` on in Settings had no
way at all to enter a key, and if `ANTHROPIC_API_KEY` happened to be missing from
`.env`, the toggle looked on but silently did nothing (`recommend.ranked_matches()`'s
own best-effort fallback swallows the failure with no user-facing sign of it).

Unlike pc caddie (one platform, one pair of fields), there are four supported
providers (see `ai_assist.PROVIDERS`) — this screen is one combined
provider-picker-plus-key-field, not "choose a provider in Settings, then a separate
screen to type the key": saving a key for a provider makes it the active one, the same
"just one action" shape `SettingsSheet`'s login section already has in the GUI. A
blank key when that provider already has one saved means "keep it, just switch to it"
— same blank-means-keep convention `CredentialsScreen`/`login_cli.py` already use for
`PCC_PASS`, applied here to "switch without retyping."

`AICredentialsScreen` is a plain `Screen[bool]`, not a standalone `App` — reached from
`SettingsScreen`'s "AI provider" row (an `open_screen` action field, see
`settings_screen.py`'s `FIELDS`), and runnable on its own via `AICredentialsApp`
(`python -m src.ai_credentials_screen`). Dismisses with `True` if a save happened
during the screen's lifetime, `False` otherwise — same contract as `CredentialsScreen`.

Only ever writes what the user types into the key Input to `.env` via env_file.py —
Claude never sees, types, or handles the value at any point, same as
`CredentialsScreen`'s own rule for the pc caddie password. The key field uses
Textual's own `password=True` masking and is never pre-filled with an existing value,
same reasoning as the pc caddie password field.

Verification (2026-09-26, direct choice: "verify with a live test call") uses
`ai_assist.verify_api_key()` — a `models.list()` call, not a generation call, so
saving a key never itself costs money — shown as a clear verified/rejected/unverified
status line, same three-way split `CredentialsScreen`'s own `verify_against_club_id`
flow already uses for pc caddie login.
"""

import asyncio
import os
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Select, Static

from . import ai_assist, env_file, global_preferences, i18n
from . import theme as theme_module
from .translated_footer import TranslatedFooter

_PROVIDER_LABEL_KEYS = {
    "anthropic": "ai_credentials.provider_anthropic",
    "openai": "ai_credentials.provider_openai",
    "gemini": "ai_credentials.provider_gemini",
    "grok": "ai_credentials.provider_grok",
}


def _active_provider() -> str:
    """The saved provider, or "anthropic" when it's missing or not one this app knows
    (a hand-edited `provider: claude`, or a null `ai_assist:` block) -- compose() feeds
    it straight into `PROVIDER_ENV_VARS[...]` and a blank-less Select, both of which
    raise on an unknown value."""
    prefs = global_preferences.load_preferences()
    ai_config = prefs.get("ai_assist")
    provider = ai_config.get("provider") if isinstance(ai_config, dict) else None
    return provider if provider in ai_assist.PROVIDERS else "anthropic"


class AICredentialsScreen(Screen[bool]):
    """Set an AI provider's API key in .env and make it the active provider. See
    module docstring."""

    CSS = """
    #intro {
        padding: 1 2;
        color: $text-muted;
    }
    .field-row {
        /* Same fix as credentials_screen.py's own .field-row -- see that module's
           CSS for the fuller writeup. */
        height: 1;
        align: left middle;
        padding: 0 2;
    }
    .field-label {
        width: 20;
    }
    .field-input {
        width: 40;
    }
    #status {
        padding: 0 2;
        color: $text-muted;
    }
    #buttons {
        padding: 1 2;
        align: right middle;
    }
    """

    BINDINGS = [("escape", "cancel", "Back"), ("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("escape", "binding.cancel"), ("q", "binding.quit")]

    def __init__(self, env_path: Path | None = None, template_path: Path | None = None) -> None:
        super().__init__()
        # Resolved at call time, not bound as a literal default -- see env_file.py's
        # module docstring for the frozen-default gotcha this avoids.
        self.env_path = env_path if env_path is not None else env_file.ENV_FILE
        self.template_path = template_path if template_path is not None else env_file.ENV_EXAMPLE_FILE
        self._saved = False

    def on_mount(self) -> None:
        self.title = i18n.t("ai_credentials.title")

    def _provider_options(self) -> list[tuple[str, str]]:
        return [(i18n.t(_PROVIDER_LABEL_KEYS[p]), p) for p in ai_assist.PROVIDERS]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(i18n.t("ai_credentials.intro"), id="intro")
        current_provider = _active_provider()
        with Vertical():
            with Horizontal(classes="field-row"):
                yield Static(i18n.t("ai_credentials.provider_label"), classes="field-label")
                yield Select(
                    self._provider_options(),
                    value=current_provider,
                    allow_blank=False,
                    id="provider",
                    classes="field-input",
                    compact=True,
                )
            with Horizontal(classes="field-row"):
                yield Static(i18n.t("ai_credentials.api_key_label"), classes="field-label")
                yield Input(
                    password=True,
                    placeholder=self._key_hint(current_provider),
                    id="api_key",
                    classes="field-input",
                    compact=True,
                )
        yield Static("", id="status")
        with Horizontal(id="buttons"):
            yield Button(i18n.t("button.cancel"), id="cancel")
            yield Button(i18n.t("button.save"), id="save", variant="success")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def _key_hint(self, provider: str) -> str:
        env_var = ai_assist.PROVIDER_ENV_VARS[provider]
        has_existing = bool(env_file.load_env_value(env_var, self.env_path))
        return i18n.t("ai_credentials.api_key_hint_set" if has_existing else "ai_credentials.api_key_hint_unset")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "provider":
            self.query_one("#api_key", Input).placeholder = self._key_hint(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()
            return
        if event.button.id == "save":
            self._save()

    def _save(self) -> None:
        status = self.query_one("#status", Static)
        provider = self.query_one("#provider", Select).value
        api_key = self.query_one("#api_key", Input).value  # not stripped -- a key
        # could legitimately contain leading/trailing characters that matter

        env_var = ai_assist.PROVIDER_ENV_VARS[provider]
        has_existing_key = bool(env_file.load_env_value(env_var, self.env_path))
        if not api_key and not has_existing_key:
            status.update(i18n.t("ai_credentials.api_key_required"))
            return

        if api_key:
            env_file.set_env_values({env_var: api_key}, self.env_path, self.template_path)
        # verify_api_key() builds its SDK client from os.environ -- see
        # ai_login_cli.py's own comment on this same gotcha (a fresh write only ever
        # reaches the file on disk, not this process's own environment).
        os.environ[env_var] = api_key or (env_file.load_env_value(env_var, self.env_path) or "")

        prefs = global_preferences.load_preferences()
        existing = prefs.get("ai_assist")
        ai_config = dict(existing) if isinstance(existing, dict) else {}
        ai_config["provider"] = provider
        prefs["ai_assist"] = ai_config
        global_preferences.save_preferences(prefs)

        self._saved = True
        self.query_one("#api_key", Input).value = ""  # never linger in the widget
        # once it's written -- re-entering edit mode always starts blank again, same
        # as CredentialsScreen's own password field.

        status.update(i18n.t("ai_credentials.verifying"))
        self.query_one("#save", Button).disabled = True
        self.run_worker(self._verify(provider), exclusive=True, group="verify")

    async def _verify(self, provider: str) -> None:
        """The live check runs in a thread, not on the event loop: `models.list()` can
        stall for minutes on a bad network (SDK timeouts plus retries), which used to
        freeze the whole TUI and meant "Verifying..." was never even painted. Leaving
        the screen cancels this worker (Textual cancels a node's workers on unmount),
        so a late result never touches widgets that are gone."""
        ok, error = await asyncio.to_thread(ai_assist.verify_api_key, provider)
        self.query_one("#save", Button).disabled = False
        status = self.query_one("#status", Static)
        if ok:
            status.update(i18n.t("ai_credentials.verified"))
        elif error is None:
            status.update(i18n.t("ai_credentials.rejected"))
        else:
            status.update(i18n.t("ai_credentials.unverified", error=error))

    def action_cancel(self) -> None:
        self.dismiss(self._saved)

    def action_quit(self) -> None:
        self.app.exit()


class AICredentialsApp(App[None]):
    """Thin standalone wrapper so AICredentialsScreen is runnable on its own:
    `python -m src.ai_credentials_screen`. Not used when the screen is pushed from
    SettingsScreen -- that app supplies its own theme/language setup and
    push_screen() call directly."""

    TITLE = "teetime-monitor"

    def on_mount(self) -> None:
        theme_module.apply_theme(self)
        i18n.apply_language()
        self.push_screen(AICredentialsScreen(), lambda _saved: self.exit())


def main() -> None:
    AICredentialsApp().run()


if __name__ == "__main__":
    main()
