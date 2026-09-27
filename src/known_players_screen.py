"""A Textual screen for browsing every real player name this club's own scrapes have
ever seen, and marking some as friends — direct follow-up (2026-09-27) to
authenticated scraping making real names possible at all (`scraper.scrape_schedule()`'s
`client` parameter): a name was already being recorded forever in `slots.players`
(scrape history never gets rewritten), just buried in whichever day happened to record
it. This is a directory over that same data, not new collection — see
`storage.known_players`'s own schema comment.

`is_friend` is the one thing a person actually edits here; everything else
(`first_seen`/`last_seen`) is derived from scraping and read-only. Marking a friend is
what finally gives the long-standing `prioritize_friends` preference (previously a
no-op — there was never a friends list to check against) something real to act on: see
`recommend.ranked_matches()`'s own `friend_names` parameter for the deterministic sort,
and `ai_assist._describe_candidate()`'s own docstring for why only a *count*, never a
name, ever reaches an AI prompt.

`KnownPlayersScreen` is a plain `Screen[None]`, not a standalone `App` — reached from
`SettingsScreen`'s "Player directory" row (an `open_screen` action field, in the same
`"settings.group.priorities"` group as `prioritize_friends` itself), and runnable on
its own via `KnownPlayersApp` (`python -m src.known_players_screen`). Friend toggles
write straight to the database on selection — no separate Save step, same "just do it"
shape a checkbox implies, not a form.
"""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Header, Static
from textual.widgets.data_table import RowDoesNotExist

from . import i18n, storage
from . import theme as theme_module
from .scrape_once import _db_path
from .translated_footer import TranslatedFooter

_FRIEND_MARK = "★"


class KnownPlayersScreen(Screen[None]):
    """Browse known players and toggle who's a friend. See module docstring."""

    CSS = """
    #intro {
        padding: 1 2;
        color: $text-muted;
    }
    #empty {
        padding: 1 2;
        color: $text-muted;
    }
    """

    BINDINGS = [("escape", "close", "Back"), ("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("escape", "binding.cancel"), ("q", "binding.quit")]

    def __init__(self, club_id: str | None, db_path: Path | None = None) -> None:
        super().__init__()
        # `db_path` is resolvable from `club_id` alone (see `_db_path()`) -- accepted
        # as its own optional override only so tests can point this at an isolated
        # database without needing a real club_id/DATA_DIR to line up, same reasoning
        # every other screen's own `*_path` constructor parameters already follow.
        self.club_id = club_id
        self.db_path = db_path if db_path is not None else (_db_path(club_id) if club_id else None)

    def on_mount(self) -> None:
        self.title = i18n.t("players.title")

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(i18n.t("players.intro"), id="intro")
        if self.db_path is None:
            yield Static(i18n.t("players.no_club"), id="empty")
        else:
            yield DataTable(id="players-table", header_height=1, cursor_type="row")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_screen_resume(self) -> None:
        # Also runs once right after compose() on the very first mount (Textual fires
        # this then too, not just on returning to an already-pushed screen) -- the one
        # place this screen's own data actually gets (re)loaded, so a friend toggle
        # made elsewhere (there isn't one yet, but a future second entry point would
        # be) is never stale on return.
        if self.db_path is not None:
            self._reload_table()

    def _reload_table(self) -> None:
        table = self.query_one("#players-table", DataTable)
        table.clear(columns=True)
        table.add_column(i18n.t("players.column.name"))
        table.add_column(i18n.t("players.column.last_seen"))
        table.add_column(i18n.t("players.column.friend"), key="friend")
        for player in storage.load_known_players(path=self.db_path):
            table.add_row(
                player.name,
                player.last_seen[:10],  # ISO timestamp -> just the date, same
                # truncation `overview.updated_relative` style screens elsewhere in
                # this app already prefer over a full timestamp for a glance-read list.
                _FRIEND_MARK if player.is_friend else "",
                key=player.name,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table = self.query_one("#players-table", DataTable)
        name = str(event.row_key.value)
        try:
            row = table.get_row(event.row_key)
        except RowDoesNotExist:
            return
        currently_friend = row[2] == _FRIEND_MARK
        storage.set_player_friend(name, not currently_friend, path=self.db_path)
        table.update_cell(event.row_key, "friend", "" if currently_friend else _FRIEND_MARK)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_quit(self) -> None:
        self.app.exit()


class KnownPlayersApp(App[None]):
    """Thin standalone wrapper so KnownPlayersScreen is runnable on its own:
    `python -m src.known_players_screen`. Not used when the screen is pushed from
    SettingsScreen -- that app supplies its own theme/language setup and
    push_screen() call directly."""

    TITLE = "teetime-monitor"

    def __init__(self, club_id: str | None = None) -> None:
        super().__init__()
        self._club_id = club_id

    def on_mount(self) -> None:
        theme_module.apply_theme(self)
        i18n.apply_language()
        self.push_screen(KnownPlayersScreen(self._club_id), lambda _result: self.exit())


def main() -> None:
    KnownPlayersApp().run()


if __name__ == "__main__":
    main()
