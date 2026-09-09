"""Search pc caddie's own full club directory and save a new clubs/*.yaml stub for
one you pick — a searchable "add a club" screen, matching pc caddie's own in-app
"Anlagenauswahl"/"Alle Clubs" feature (confirmed live via real mobile-app screenshots,
2026-09-06) and directly requested: "Can the TUI offer the same dropdown menu that
would list all available courses on PC caddie?"

Needs at least one already-configured club to log in with — its credentials, resolved
the same way as everywhere else (`club_config.resolve_credentials()`). One pc caddie
login works across every club on the platform (confirmed 2026-09-05), so the directory
this fetches isn't limited to that one club. This can't bootstrap your very first
saved club, though — there'd be no club_id yet to log in with. That one still needs
its numeric id found by hand (see clubs/club.example.yaml's own instructions); this
screen is for the ones after that, matching what actually prompted it: a home club
plus a few others visited occasionally.

If PCC_USER/PCC_PASS aren't set yet for that club, this pushes `credentials_screen.py`
automatically (added 2026-09-07, same session — "I want to setup credentials from UI.
It should be user friendly") so they can be filled in right here instead of hand-
editing `.env`, then retries the fetch once saved.

`ClubSearchScreen` is a plain `Screen[str | None]` (added 2026-09-07, direct
follow-up: "I want to be able to switch clubs on the fly" — a hassle otherwise, since
adding a club meant leaving the running TUI, running this as its own program, then
restarting) — meant to be *pushed* from another app. `tui.py`'s own club picker
(reached via `s` on the tee sheet) offers a "search for a club" entry precisely so a
new club can be found, saved, and switched to in one continuous flow, no separate
command needed. Dismisses with the newly saved slug, or `None` if backed out (`q`)
without saving. Still runnable on its own too, via the thin `ClubPickerApp` wrapper:
`python -m src.club_picker <existing-club-slug>` (the clubs/*.yaml filename slug, not
the pc caddie numeric id) — or with no argument if exactly one club is already saved,
matching the "skip the picker" convention used elsewhere in this project
(settings_screen.py, tui.py's own ClubPickerScreen).

Search is a plain case-insensitive substring match against each club's name — not pc
caddie's own exact-substring, umlaut-sensitive behavior confirmed live 2026-09-06 on
their equivalent field (see scraper.py's module docstring). A deliberate, friendlier
deviation, not an unnoticed gap.

Saving writes `club_config.new_club_stub_with_location(club_id, name)` — the same
best-effort weather-`location` lookup (2026-09-08, `geocode.find_club_location()`
against the club's own name — see that module's docstring for what pc caddie
itself doesn't expose, and why this can't be a guaranteed-precise pin) that
`tui.py`'s own `f`-to-favorite goes through too, via `club_config.add_favorite()`
(see that function's docstring for why the lookup had to be factored out to
`new_club_stub_with_location()` rather than living only here). Everything else is
still left for the user to fill in by hand or via settings_screen.py — see
`new_club_stub()`'s own docstring.

Bilingual like every other screen in this project (i18n.py); uses the shared
`TranslatedFooter` from translated_footer.py, same as every other screen.
"""

import sys
from pathlib import Path
from typing import Callable

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Static
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from . import club_config, env_file, i18n
from . import theme as theme_module
from .credentials_screen import CredentialsScreen
from .scraper import fetch_club_directory
from .translated_footer import TranslatedFooter  # noqa: F401 -- re-exported, see that module


def search_club_directory(directory: list[tuple[str, str]], query: str) -> list[tuple[str, str]]:
    """Case-insensitive substring match against each club's name. Pure function, no
    Textual/network involved, so it's directly testable against a fixture directory.
    An empty/blank query deliberately returns no results (a "type to search" prompt
    is shown instead) rather than dumping 1300+ entries into the list at once."""
    query = query.strip().lower()
    if not query:
        return []
    return [(club_id, name) for club_id, name in directory if query in name.lower()]


# Moved into club_config.py 2026-09-07 so the favorites helpers there share one
# implementation with this screen; re-exported under its original name because this
# module's own callers and tests already import it from here.
slugify = club_config.slugify


class ClubSearchScreen(Screen[str | None]):
    """Fetch pc caddie's club directory once (via an already-configured club's
    credentials), let the user search/select from it, and save a new club stub. See
    module docstring."""

    CSS = """
    #status {
        padding: 0 2;
        color: $text-muted;
    }
    #search {
        margin: 0 2;
    }
    #results {
        height: 12;
        margin: 0 2 1 2;
    }
    #save-row {
        padding: 0 2;
        align: left middle;
        height: 3;
    }
    #slug {
        width: 40;
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

    MAX_RESULTS = 50

    def __init__(
        self,
        existing_slug: str,
        clubs_dir: Path | None = None,
        on_saved: Callable[[str], None] | None = None,
        env_path: Path | None = None,
        template_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.existing_slug = existing_slug
        # Resolved at call time, not bound as a literal default -- see env_file.py's
        # module docstring for the frozen-default gotcha this avoids (this screen is
        # now pushed straight from tui.py's own switch flow, not just constructed
        # directly by tests/club_picker.py's own CLI wrapper, so a caller that never
        # touches `clubs_dir` at all must still see any monkeypatched
        # club_config.CLUBS_DIR — a class-definition-time default wouldn't).
        self.clubs_dir = clubs_dir if clubs_dir is not None else club_config.CLUBS_DIR
        self._on_saved = on_saved
        self.env_path = env_path if env_path is not None else env_file.ENV_FILE
        self.template_path = template_path if template_path is not None else env_file.ENV_EXAMPLE_FILE
        self.directory: list[tuple[str, str]] = []
        self.selected: tuple[str, str] | None = None
        self._match_names: dict[str, str] = {}
        self._saved_slug: str | None = None

    def on_mount(self) -> None:
        # `club_picker.title` has existed since this screen was first built but was
        # never actually set anywhere -- found 2026-09-10 auditing for "further
        # cases where it is not wired up."
        self.title = i18n.t("club_picker.title")
        self._load_directory()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="status")
        yield Input(placeholder=i18n.t("club_picker.search_placeholder"), id="search")
        yield OptionList(id="results")
        with Horizontal(id="save-row"):
            yield Input(placeholder=i18n.t("club_picker.slug_placeholder"), id="slug")
            yield Button(i18n.t("button.save"), id="save", variant="success")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def _load_directory(self) -> None:
        """Best-effort, not fatal to the whole screen — a missing/wrong credential or
        a live fetch failure just disables search with a clear status message, rather
        than crashing (same "fail visibly, not loudly" stance used everywhere else
        network calls happen in this project). Specifically missing PCC_USER/PCC_PASS
        (as opposed to a broken/missing club_id, which a credentials screen can't
        fix) pushes CredentialsScreen right here — added 2026-09-07, direct follow-up
        to the picker itself: "I want to setup credentials from UI. It should be
        user friendly" — so a first-time user hits this and can fill them in on the
        spot, without leaving to hand-edit .env, before retrying automatically."""
        status = self.query_one("#status", Static)
        search = self.query_one("#search", Input)
        config = club_config.load_club_config(self.existing_slug, self.clubs_dir)
        existing_club_id = config.get("club_id")
        username, password = club_config.resolve_credentials(self.existing_slug)
        if not existing_club_id:
            status.update(i18n.t("club_picker.no_credentials"))
            search.disabled = True
            return
        if not username or not password:
            status.update(i18n.t("club_picker.no_credentials"))
            search.disabled = True
            self.app.push_screen(
                CredentialsScreen(self.env_path, self.template_path), self._on_credentials_screen_dismissed
            )
            return
        status.update(i18n.t("club_picker.fetching"))
        try:
            self.directory = fetch_club_directory(existing_club_id, username, password)
        except Exception as exc:  # noqa: BLE001 — a live fetch can genuinely fail
            # (wrong/expired credentials, no network, site down) and shouldn't crash
            # the screen over it.
            status.update(i18n.t("club_picker.fetch_failed", error=exc))
            search.disabled = True
            return
        search.disabled = False
        status.update(i18n.t("club_picker.select_prompt"))

    def _on_credentials_screen_dismissed(self, saved: bool) -> None:
        if saved:
            self._load_directory()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self._update_results(event.value)

    def _update_results(self, query: str) -> None:
        results = self.query_one("#results", OptionList)
        results.clear_options()
        status = self.query_one("#status", Static)
        if not query.strip():
            status.update(i18n.t("club_picker.select_prompt"))
            return
        matches = search_club_directory(self.directory, query)
        if not matches:
            status.update(i18n.t("club_picker.no_matches"))
            return
        status.update(i18n.t("club_picker.match_count", count=len(matches)))
        shown = matches[: self.MAX_RESULTS]
        self._match_names = dict(shown)
        for club_id, name in shown:
            results.add_option(Option(f"[{club_id}] {name}", id=club_id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        club_id = event.option.id
        name = self._match_names.get(club_id, "")
        self.selected = (club_id, name)
        self.query_one("#slug", Input).value = slugify(name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            return
        status = self.query_one("#status", Static)
        if self.selected is None:
            status.update(i18n.t("club_picker.pick_first"))
            return
        slug = self.query_one("#slug", Input).value.strip()
        if not slug:
            status.update(i18n.t("club_picker.slug_required"))
            return
        if slug in club_config.list_clubs(self.clubs_dir):
            status.update(i18n.t("club_picker.slug_taken", slug=slug))
            return
        club_id, name = self.selected
        # Best-effort automatic weather location, shared with tui.py's own
        # `f`-to-favorite path via club_config.add_favorite() -- see
        # new_club_stub_with_location()'s own docstring for why this needed to be
        # factored out rather than living only here (2026-09-08 direct follow-up:
        # "can the scraper find out location data and fill it in automatically on
        # the fly?" -- pc caddie itself has nothing usable, so this is a one-off
        # OpenStreetMap lookup on the club's own name instead; see geocode.py's
        # module docstring for what was checked before landing on that approach,
        # and why it's a best-effort location, not a guaranteed-precise one).
        stub = club_config.new_club_stub_with_location(club_id, name)
        club_config.save_club_config(slug, stub, self.clubs_dir)
        self._saved_slug = slug
        if self._on_saved is not None:
            self._on_saved(slug)
        saved_key = "club_picker.saved_with_location" if "location" in stub else "club_picker.saved_no_location"
        status.update(i18n.t(saved_key, slug=slug))

    def action_cancel(self) -> None:
        self.dismiss(self._saved_slug)

    def action_quit(self) -> None:
        self.app.exit()


class ClubPickerApp(App[None]):
    """Thin standalone wrapper so ClubSearchScreen is runnable on its own:
    `python -m src.club_picker`. Not used when the screen is pushed from another app
    (tui.py's switch-club flow) — that app supplies its own theme/language setup and
    push_screen()/push_screen_wait() call directly."""

    TITLE = "teetime-monitor"

    def __init__(self, existing_slug: str) -> None:
        super().__init__()
        self.existing_slug = existing_slug

    def on_mount(self) -> None:
        theme_module.apply_theme(self)
        i18n.apply_language()
        self.push_screen(ClubSearchScreen(self.existing_slug), lambda _slug: self.exit())


def main() -> None:
    if len(sys.argv) > 1:
        existing_slug = sys.argv[1]
    else:
        clubs = club_config.list_clubs()
        if len(clubs) == 1:
            existing_slug = clubs[0]
        elif not clubs:
            print(i18n.t("app.no_clubs"))
            return
        else:
            print("More than one club saved — pass one: " + ", ".join(clubs))
            return

    ClubPickerApp(existing_slug).run()


if __name__ == "__main__":
    main()
