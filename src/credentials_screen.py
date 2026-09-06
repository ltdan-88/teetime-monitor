"""A Textual screen for setting up pc caddie login credentials — direct follow-up to
club_picker.py: "I want to setup credentials from UI. It should be user friendly,"
since hand-editing `.env` in a text editor was the only path before this.

`CredentialsScreen` is a plain `Screen[bool]`, not a standalone `App` — it's meant to
be *pushed* from another app (see club_picker.py, which pushes it automatically the
moment it discovers no credentials are configured yet, letting the user fill them in
without leaving the picker) as well as runnable on its own via `CredentialsApp`
(`python -m src.credentials_screen`). Dismisses with `True` if a save happened during
the screen's lifetime, `False` otherwise — a caller (club_picker.py) uses that to
decide whether to retry whatever needed credentials in the first place.

Only ever writes what the user types into these two Input widgets to `.env` via
env_file.py — Claude never sees, types, or handles the value at any point; this is no
different from the user opening `.env` in a text editor themselves, just friendlier.
The password field uses Textual's own `password=True` masking and is never
pre-filled with an existing value (even though the username field is, since a
username isn't secret) — leaving it blank on save means "keep whatever's already
there," not "clear it," so there's never a need to display or retype a password that
already works.

Also updates `os.environ` directly for the *current* process on save, not just the
file on disk — needed for club_picker.py's own "retry automatically once saved" flow
to see the new credentials without a restart. A fresh process picks them up from
`.env` itself instead, via club_config.py's own `load_dotenv()` call (see that
module's docstring for the related bug this session found and fixed: `.env` was never
actually being loaded into the environment anywhere before now).
"""

import os
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Static

from . import env_file, i18n
from . import theme as theme_module
from .translated_footer import TranslatedFooter


class CredentialsScreen(Screen[bool]):
    """Set PCC_USER/PCC_PASS in .env. See module docstring."""

    CSS = """
    #intro {
        padding: 1 2;
        color: $text-muted;
    }
    .field-row {
        height: 3;
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
    }
    """

    BINDINGS = [("q", "quit_screen", "Quit")]
    _FOOTER_BINDINGS = [("q", "binding.quit")]

    def __init__(self, env_path: Path | None = None, template_path: Path | None = None) -> None:
        super().__init__()
        # Resolved at call time, not bound as a literal default -- see env_file.py's
        # module docstring for the frozen-default gotcha this avoids.
        self.env_path = env_path if env_path is not None else env_file.ENV_FILE
        self.template_path = template_path if template_path is not None else env_file.ENV_EXAMPLE_FILE
        self._saved = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(i18n.t("credentials.intro"), id="intro")
        existing_username = env_file.load_env_value("PCC_USER", self.env_path) or ""
        password_hint_key = (
            "credentials.password_hint_set"
            if env_file.load_env_value("PCC_PASS", self.env_path)
            else "credentials.password_hint_unset"
        )
        with Vertical():
            with Horizontal(classes="field-row"):
                yield Static(i18n.t("credentials.username_label"), classes="field-label")
                yield Input(value=existing_username, id="username", classes="field-input")
            with Horizontal(classes="field-row"):
                yield Static(i18n.t("credentials.password_label"), classes="field-label")
                yield Input(
                    password=True,
                    placeholder=i18n.t(password_hint_key),
                    id="password",
                    classes="field-input",
                )
        yield Static("", id="status")
        with Horizontal(id="buttons"):
            yield Button(i18n.t("button.save"), id="save", variant="success")
            yield Button(i18n.t("button.quit"), id="quit")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.action_quit_screen()
            return
        if event.button.id == "save":
            self._save()

    def _save(self) -> None:
        status = self.query_one("#status", Static)
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value  # not stripped -- a
        # password could legitimately start/end with a space; only strip the username

        if not username:
            status.update(i18n.t("credentials.username_required"))
            return
        has_existing_password = bool(env_file.load_env_value("PCC_PASS", self.env_path))
        if not password and not has_existing_password:
            status.update(i18n.t("credentials.password_required"))
            return

        env_file.set_env_values(
            {"PCC_USER": username, "PCC_PASS": password}, self.env_path, self.template_path
        )
        os.environ["PCC_USER"] = username  # update *this* process too, not just the
        if password:  # file on disk -- see module docstring's "Also updates" note
            os.environ["PCC_PASS"] = password
        self._saved = True
        self.query_one("#password", Input).value = ""  # never linger in the widget
        # once it's written -- re-entering edit mode always starts blank again, same
        # as on first load.
        status.update(i18n.t("credentials.saved"))

    def action_quit_screen(self) -> None:
        self.dismiss(self._saved)


class CredentialsApp(App[None]):
    """Thin standalone wrapper so CredentialsScreen is runnable on its own:
    `python -m src.credentials_screen`. Not used when the screen is pushed from
    another app (club_picker.py) — that app supplies its own theme/language setup and
    push_screen() call directly."""

    TITLE = "teetime-monitor"

    def on_mount(self) -> None:
        theme_module.apply_theme(self)
        i18n.apply_language()
        self.push_screen(CredentialsScreen(), lambda _saved: self.exit())


def main() -> None:
    CredentialsApp().run()


if __name__ == "__main__":
    main()
