"""A Textual screen for setting up pc caddie login credentials — direct follow-up to
a request made while building the club picker: "I want to setup credentials from UI.
It should be user friendly," since hand-editing `.env` in a text editor was the only
path before this.

`CredentialsScreen` is a plain `Screen[bool]`, not a standalone `App` — it's meant to
be *pushed* from another app (see tui.py's `ClubBrowserScreen`, which pushes it
automatically the moment it discovers no credentials are configured yet, letting the
user fill them in without leaving the browser, and `TeetimeApp._start()`, which pushes
it before anything else at launch if no credentials exist at all yet) as well as
runnable on its own via `CredentialsApp` (`python -m src.credentials_screen`).
Dismisses with `True` if a save happened during the screen's lifetime, `False`
otherwise — a caller (`ClubBrowserScreen`) uses that to decide whether to retry
whatever needed credentials in the first place.

Only ever writes what the user types into these two Input widgets to `.env` via
env_file.py — Claude never sees, types, or handles the value at any point; this is no
different from the user opening `.env` in a text editor themselves, just friendlier.
The password field uses Textual's own `password=True` masking and is never
pre-filled with an existing value (even though the username field is, since a
username isn't secret) — leaving it blank on save means "keep whatever's already
there," not "clear it," so there's never a need to display or retype a password that
already works.

Field rows and the button row picked up the same layout fixes as settings_screen.py
(2026-09-08, point 6 of that screen's UI/UX feedback: overall consistency) --
compact, one-row Input fields lined up with their labels, and a right-aligned,
Quit-then-Save button row -- since this screen had the identical field-row-height
mismatch and left-hugging buttons, just never called out by name.

Also updates `os.environ` directly for the *current* process on save, not just the
file on disk — needed for `ClubBrowserScreen`'s own "retry automatically once saved"
flow to see the new credentials without a restart. A fresh process picks them up from
`.env` itself instead, via club_config.py's own `load_dotenv()` call (see that
module's docstring for the related bug this session found and fixed: `.env` was never
actually being loaded into the environment anywhere before now).

`verify_against_club_id` (added 2026-09-10, direct report: "how do I know if login
is successful") — a real, live login attempt via `scraper.login()`, shown as a clear
"verified"/"rejected" status rather than just "Saved to .env." (which only ever
confirmed the *file write*, never that pc caddie actually accepted the credentials).
Optional because a login attempt needs a real club_id to authenticate *against*, and
this screen doesn't always have one — a genuinely fresh install (see
`TeetimeApp._start()`, which pushes this screen before any club has ever been
favorited) has no club_id to test with yet, so it falls back to the old plain "Saved"
message in that case rather than skipping the save entirely. Callers that do know a
favorited club_id (`ClubBrowserScreen.action_login()`/`action_refresh_directory()`)
pass one so the common re-entry case gets real verification. This makes a real
network call on save, blocking briefly — same tradeoff `ClubBrowserScreen`'s own `r`
already makes for its "Fetching…" status, not a new pattern.
"""

import os
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Static

from . import env_file, i18n, scraper
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
        /* Same fix as settings_screen.py's own .field-row -- Input's default
           bordered rendering is 3 rows tall against a 1-row Static label, so the two
           never lined up. See that module's CSS for the fuller writeup (direct
           feedback, 2026-09-08, on the sibling settings screen, but the same
           mismatch was here too -- fixed for consistency, point 6 of that
           feedback). compact=True on both Inputs below is the other half of this. */
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
        /* Right-aligned, Cancel-then-Save -- same OS-dialog convention applied to
           settings_screen.py's own #buttons, for consistency across both screens. */
        align: right middle;
    }
    """

    # escape = back (dismiss just this screen), q = quit the whole app -- same fix,
    # same day, same reason as settings_screen.py's own BINDINGS (see that module's
    # docstring for the direct feedback: "Please make key binds consistent"). This
    # screen had the identical outlier pattern (no escape, q = close screen), just
    # not yet reachable from a live user complaint since it isn't currently pushed
    # from the running main app.
    BINDINGS = [("escape", "cancel", "Back"), ("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("escape", "binding.cancel"), ("q", "binding.quit")]

    def __init__(
        self,
        env_path: Path | None = None,
        template_path: Path | None = None,
        verify_against_club_id: str | None = None,
    ) -> None:
        super().__init__()
        # Resolved at call time, not bound as a literal default -- see env_file.py's
        # module docstring for the frozen-default gotcha this avoids.
        self.env_path = env_path if env_path is not None else env_file.ENV_FILE
        self.template_path = template_path if template_path is not None else env_file.ENV_EXAMPLE_FILE
        # See module docstring's "verify_against_club_id" note -- a real club_id to
        # test the saved credentials against with an actual login attempt, or None to
        # fall back to the old "Saved to .env" message with no live verification.
        self.verify_against_club_id = verify_against_club_id
        self._saved = False

    def on_mount(self) -> None:
        # `credentials.title` has existed since this screen was first built but was
        # never actually set anywhere -- found 2026-09-10 auditing for "further
        # cases where it is not wired up" -- so the Header just showed whatever the
        # parent App's own title happened to be (e.g. "teetime-monitor") instead.
        self.title = i18n.t("credentials.title")

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
                yield Input(value=existing_username, id="username", classes="field-input", compact=True)
            with Horizontal(classes="field-row"):
                yield Static(i18n.t("credentials.password_label"), classes="field-label")
                yield Input(
                    password=True,
                    placeholder=i18n.t(password_hint_key),
                    id="password",
                    classes="field-input",
                    compact=True,
                )
        yield Static("", id="status")
        with Horizontal(id="buttons"):
            # "Cancel," not "Quit" -- same rename as settings_screen.py's own button,
            # same reason: this dismisses just the screen, and "Quit" now
            # unambiguously means the q key's "exit the whole app" instead.
            yield Button(i18n.t("button.cancel"), id="cancel")
            yield Button(i18n.t("button.save"), id="save", variant="success")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()
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

        if self.verify_against_club_id is None:
            # No real club_id to test against yet (see module docstring's
            # "verify_against_club_id" note) -- "Saved" only ever confirmed the file
            # write, not that pc caddie actually accepts these credentials.
            status.update(i18n.t("credentials.saved"))
            return

        status.update(i18n.t("credentials.verifying"))
        try:
            client = scraper.login(
                self.verify_against_club_id, os.environ["PCC_USER"], os.environ.get("PCC_PASS", "")
            )
        except scraper.LoginError:
            status.update(i18n.t("credentials.login_failed"))
            return
        except Exception as exc:  # noqa: BLE001 -- a network hiccup isn't the same
            # thing as bad credentials -- don't tell the user their login is wrong
            # over a transient failure that has nothing to do with it.
            status.update(i18n.t("credentials.saved_unverified", error=exc))
            return
        client.close()
        status.update(i18n.t("credentials.login_verified"))

    def action_cancel(self) -> None:
        self.dismiss(self._saved)

    def action_quit(self) -> None:
        self.app.exit()


class CredentialsApp(App[None]):
    """Thin standalone wrapper so CredentialsScreen is runnable on its own:
    `python -m src.credentials_screen`. Not used when the screen is pushed from
    another app (tui.py's TeetimeApp) — that app supplies its own theme/language setup
    and push_screen() call directly."""

    TITLE = "teetime-monitor"

    def on_mount(self) -> None:
        theme_module.apply_theme(self)
        i18n.apply_language()
        self.push_screen(CredentialsScreen(), lambda _saved: self.exit())


def main() -> None:
    CredentialsApp().run()


if __name__ == "__main__":
    main()
