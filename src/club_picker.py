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

Run directly: `python -m src.club_picker <existing-club-slug>` (the clubs/*.yaml
filename slug, not the pc caddie numeric id) — or with no argument if exactly one
club is already saved, matching the "skip the picker" convention used elsewhere in
this project (settings_screen.py, tui.py's own ClubPickerScreen).

Search is a plain case-insensitive substring match against each club's name — not pc
caddie's own exact-substring, umlaut-sensitive behavior confirmed live 2026-09-06 on
their equivalent field (see scraper.py's module docstring). A deliberate, friendlier
deviation, not an unnoticed gap.

Saving writes only `club_config.new_club_stub(club_id)` — see that function's
docstring for why everything besides `club_id` is left for the user to fill in by
hand or via settings_screen.py.

Bilingual like every other screen in this project (i18n.py); shares the same
`TranslatedFooter` approach as settings_screen.py, duplicated rather than imported so
this standalone script doesn't pull in tui.py's much heavier dependency chain.
"""

import re
import sys
from pathlib import Path
from typing import Callable

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Header, Input, Static
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from . import club_config, i18n
from . import theme as theme_module
from .scraper import fetch_club_directory


def search_club_directory(directory: list[tuple[str, str]], query: str) -> list[tuple[str, str]]:
    """Case-insensitive substring match against each club's name. Pure function, no
    Textual/network involved, so it's directly testable against a fixture directory.
    An empty/blank query deliberately returns no results (a "type to search" prompt
    is shown instead) rather than dumping 1300+ entries into the list at once."""
    query = query.strip().lower()
    if not query:
        return []
    return [(club_id, name) for club_id, name in directory if query in name.lower()]


_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")
_UMLAUT_FOLDS = {"ä": "a", "ö": "o", "ü": "u", "ß": "ss"}


def slugify(name: str) -> str:
    """A reasonable starting filename slug from a club's display name — e.g. "Golfclub
    Domäne Musterhausen e.V." -> "golfclub-domane-musterhausen-e-v". Just a default in
    the Input the user can edit before saving, not guaranteed unique or a real
    transliteration — good enough as a starting point, not attempted to be exact."""
    normalized = name.lower()
    for umlaut, plain in _UMLAUT_FOLDS.items():
        normalized = normalized.replace(umlaut, plain)
    slug = _SLUG_INVALID_CHARS.sub("-", normalized).strip("-")
    return slug or "club"


class TranslatedFooter(Static):
    """Duplicated from settings_screen.py/tui.py's own — see either module's docstring
    for why Textual's built-in `Footer` can't be translated at render time.
    `bindings` is `[(key, i18n_key), ...]` in display order."""

    DEFAULT_CSS = """
    TranslatedFooter {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text;
    }
    """

    def __init__(self, bindings: list[tuple[str, str]]) -> None:
        super().__init__()
        self._key_bindings = bindings

    def render(self) -> str:
        parts = [f"[b]{key}[/b] {i18n.t(label_key)}" for key, label_key in self._key_bindings]
        return "  ".join(parts)


class ClubPickerApp(App[None]):
    """Fetch pc caddie's club directory once (via an already-configured club's
    credentials), let the user search/select from it, and save a new club stub."""

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

    BINDINGS = [("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("q", "binding.quit")]

    MAX_RESULTS = 50

    def __init__(
        self,
        existing_slug: str,
        clubs_dir: Path = club_config.CLUBS_DIR,
        on_saved: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.existing_slug = existing_slug
        self.clubs_dir = clubs_dir
        self._on_saved = on_saved
        self.directory: list[tuple[str, str]] = []
        self.selected: tuple[str, str] | None = None
        self._match_names: dict[str, str] = {}

    def on_mount(self) -> None:
        theme_module.apply_theme(self)
        i18n.apply_language()
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
        network calls happen in this project)."""
        status = self.query_one("#status", Static)
        config = club_config.load_club_config(self.existing_slug, self.clubs_dir)
        existing_club_id = config.get("club_id")
        username, password = club_config.resolve_credentials(self.existing_slug)
        if not existing_club_id or not username or not password:
            status.update(i18n.t("club_picker.no_credentials"))
            self.query_one("#search", Input).disabled = True
            return
        status.update(i18n.t("club_picker.fetching"))
        try:
            self.directory = fetch_club_directory(existing_club_id, username, password)
        except Exception as exc:  # noqa: BLE001 — a live fetch can genuinely fail
            # (wrong/expired credentials, no network, site down) and shouldn't crash
            # the screen over it.
            status.update(i18n.t("club_picker.fetch_failed", error=exc))
            self.query_one("#search", Input).disabled = True
            return
        status.update(i18n.t("club_picker.select_prompt"))

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
        club_id, _name = self.selected
        club_config.save_club_config(slug, club_config.new_club_stub(club_id), self.clubs_dir)
        if self._on_saved is not None:
            self._on_saved(slug)
        status.update(i18n.t("club_picker.saved", slug=slug))


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
