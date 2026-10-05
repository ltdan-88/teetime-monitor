"""A Textual screen for browsing every real player name this club's own scrapes have
ever seen, and marking some as friends — direct follow-up (2026-09-27) to
authenticated scraping making real names possible at all (`scraper.scrape_schedule()`'s
`client` parameter): a name was already being recorded forever in `slots.players`
(scrape history never gets rewritten), just buried in whichever day happened to record
it. This is a directory over that same data, not new collection — see
`storage.known_players`'s own schema comment.

`is_friend` is the one thing a person actually edits here; everything else is derived
from scraping and read-only. Marking a friend is what finally gives the long-standing
`prioritize_friends` preference (previously a no-op — there was never a friends list to
check against) something real to act on: see `recommend.ranked_matches()`'s own
`friend_names` parameter for the deterministic sort, and `ai_assist._describe_candidate()`'s
own docstring for why only a *count*, never a name, ever reaches an AI prompt.

Sortable and searchable (2026-09-27, direct follow-up: "i need the player directory to
be sorted alphabetically by family name. better: make the player directory sortable and
searchable"): default order is alphabetical by family name (`models.family_name()`'s
own last-whitespace-token rule — this club's real directory of 373 names never needs
more, see that function's own docstring), a search box filters by substring on the full
name, and clicking any column header re-sorts by that column, toggling direction on a
second click of the same one. `first_seen`/`last_seen` are still recorded (storage.py)
but never shown here (direct feedback: "i dont need the date when players have been
added") — nothing about sorting or searching needs them.

Gender/member-status/handicap columns (2026-09-27, direct follow-up: "are there any
further scrapable information... worth to display?" — checked live against the real
authenticated tee sheet HTML, see `models.PlayerSighting`'s own docstring) show
whatever pc caddie's own markup carried for that player's most recent sighting; any of
the three can be blank when it was never recorded.

`KnownPlayersScreen` is a plain `Screen[None]`, not a standalone `App` — reached from
`SettingsScreen`'s "Player directory" row (an `open_screen` action field, in the same
`"settings.group.priorities"` group as `prioritize_friends` itself) and from
`OverviewScreen`'s own Actions palette, and runnable on its own via `KnownPlayersApp`
(`python -m src.known_players_screen`). Friend toggles write straight to the database
on selection — no separate Save step, same "just do it" shape a checkbox implies, not
a form.
"""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Header, Input, Label, Static, Switch
from textual.widgets.data_table import RowDoesNotExist

from . import i18n, storage
from . import theme as theme_module
from .models import KnownPlayer, family_name
from .scrape_once import _db_path
from .translated_footer import TranslatedFooter

_FRIEND_MARK = "★"

# One sort key function per column -- keyed by the same string used as that column's
# `DataTable` column key, so `on_data_table_header_selected()` can look a clicked
# header straight up here with no if/elif chain. Each returns a tuple rather than a
# bare value so ties (e.g. two players with the same gender) still break
# deterministically by family name, instead of falling back to whatever order
# Python's stable sort happened to leave them in.
_SORT_KEYS = {
    "name": lambda p: (family_name(p.name).casefold(), p.name.casefold()),
    "gender": lambda p: (p.gender or "", family_name(p.name).casefold()),
    "member_status": lambda p: (p.member_status or "", family_name(p.name).casefold()),
    # `is None` first so a player with no recorded handicap always sorts to the same
    # end regardless of ascending/descending -- reversing the *comparison* itself
    # would otherwise flip which end "no data" lands on, which reads as broken sorting
    # rather than as a real value at the low/high extreme.
    "handicap": lambda p: (p.handicap is None, p.handicap or 0.0, family_name(p.name).casefold()),
    "friend": lambda p: (not p.is_friend, family_name(p.name).casefold()),
}


def _gender_cell(gender: str | None) -> str:
    return i18n.t(f"players.gender.{gender}") if gender else ""


def _member_status_cell(member_status: str | None) -> str:
    return i18n.t(f"players.member_status.{member_status}") if member_status else ""


def _handicap_cell(handicap: float | None) -> str:
    return f"{handicap:.1f}" if handicap is not None else ""


class KnownPlayersScreen(Screen[str | None]):
    """Browse known players, filter, sort, and toggle who's a friend. See module
    docstring.

    `pick=True` (2026-09-28, direct follow-up: the Search screen's own player dropdown
    "is a bit too long to use") turns this same browser into a chooser: Enter on a row
    dismisses with that player's name instead of toggling a friend, Escape dismisses
    with None. Reusing the screen keeps its sort/search/family-name ordering rather than
    duplicating them in a second list."""

    CSS = """
    #intro {
        padding: 1 2;
        color: $text-muted;
    }
    #empty {
        padding: 1 2;
        color: $text-muted;
    }
    #search-row {
        height: 3;
        margin: 0 2 1 2;
    }
    #player-search {
        width: 1fr;
    }
    #friends-only-label {
        padding: 1 1 0 2;
        width: auto;
    }
    """

    BINDINGS = [("escape", "close", "Back"), ("q", "quit", "Quit")]
    _FOOTER_BINDINGS = [("escape", "binding.cancel"), ("q", "binding.quit")]

    def __init__(self, club_id: str | None, db_path: Path | None = None, pick: bool = False) -> None:
        super().__init__()
        self.pick = pick
        # `db_path` is resolvable from `club_id` alone (see `_db_path()`) -- accepted
        # as its own optional override only so tests can point this at an isolated
        # database without needing a real club_id/DATA_DIR to line up, same reasoning
        # every other screen's own `*_path` constructor parameters already follow.
        self.club_id = club_id
        self.db_path = db_path if db_path is not None else (_db_path(club_id) if club_id else None)
        self._players: list[KnownPlayer] = []
        self._sort_key = "name"
        self._sort_reverse = False
        self._query = ""
        self._friends_only = False

    def on_mount(self) -> None:
        self.title = i18n.t("players.picker_title" if self.pick else "players.title")

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(i18n.t("players.picker_intro" if self.pick else "players.intro"), id="intro")
        if self.db_path is None:
            yield Static(i18n.t("players.no_club"), id="empty")
        else:
            with Horizontal(id="search-row"):
                yield Input(placeholder=i18n.t("players.search_placeholder"), id="player-search")
                yield Label(i18n.t("players.friends_only"), id="friends-only-label")
                yield Switch(value=False, id="friends-only")
            yield DataTable(id="players-table", header_height=1, cursor_type="row")
        yield TranslatedFooter(self._FOOTER_BINDINGS)

    def on_screen_resume(self) -> None:
        # Also runs once right after compose() on the very first mount (Textual fires
        # this then too, not just on returning to an already-pushed screen) -- the one
        # place this screen's own data actually gets (re)loaded, so a friend toggle
        # made elsewhere is never stale on return.
        if self.db_path is not None:
            self._players = storage.load_known_players(path=self.db_path)
            self._render_table()
            # The table, not the new search box, keeps the arrow-keys/Enter
            # interaction this screen already had working the moment it opens --
            # without this, Textual's own default-focus-the-first-widget behavior
            # would hand focus to the search Input instead (it's now first in the
            # compose() order), and Enter would submit an empty search instead of
            # toggling a friend.
            self.query_one("#players-table", DataTable).focus()

    def _visible_players(self) -> list[KnownPlayer]:
        players = self._players
        if self._friends_only:
            players = [p for p in players if p.is_friend]
        if self._query:
            query = self._query.casefold()
            players = [p for p in players if query in p.name.casefold()]
        return sorted(players, key=_SORT_KEYS[self._sort_key], reverse=self._sort_reverse)

    def _column_label(self, key: str, translation_key: str) -> str:
        # An arrow on whichever column is currently driving the sort, so the table's
        # own header doubles as its sort indicator -- no separate status line needed.
        if key != self._sort_key:
            return i18n.t(translation_key)
        return i18n.t(translation_key) + (" ▼" if self._sort_reverse else " ▲")

    def _render_table(self) -> None:
        table = self.query_one("#players-table", DataTable)
        table.clear(columns=True)
        table.add_column(self._column_label("name", "players.column.name"), key="name")
        table.add_column(self._column_label("gender", "players.column.gender"), key="gender")
        table.add_column(self._column_label("member_status", "players.column.member_status"), key="member_status")
        table.add_column(self._column_label("handicap", "players.column.handicap"), key="handicap")
        table.add_column(self._column_label("friend", "players.column.friend"), key="friend")
        for player in self._visible_players():
            table.add_row(
                player.name,
                _gender_cell(player.gender),
                _member_status_cell(player.member_status),
                _handicap_cell(player.handicap),
                _FRIEND_MARK if player.is_friend else "",
                key=player.name,
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "player-search":
            return
        self._query = event.value.strip()
        self._render_table()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id != "friends-only":
            return
        self._friends_only = event.value
        self._render_table()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        key = str(event.column_key.value)
        if key not in _SORT_KEYS:
            return
        if key == self._sort_key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_key = key
            self._sort_reverse = False
        self._render_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table = self.query_one("#players-table", DataTable)
        name = str(event.row_key.value)
        if self.pick:
            self.dismiss(name)
            return
        try:
            currently_friend = table.get_cell(event.row_key, "friend") == _FRIEND_MARK
        except RowDoesNotExist:
            return
        storage.set_player_friend(name, not currently_friend, path=self.db_path)
        for player in self._players:
            if player.name == name:
                player.is_friend = not currently_friend
                break
        table.update_cell(event.row_key, "friend", "" if currently_friend else _FRIEND_MARK)
        if self._sort_key == "friend" or self._friends_only:
            # Toggling a friend can change this row's position when friend status is
            # what's actually being sorted on, and drops it from the list entirely
            # under "Friends only" -- a single cell update above isn't enough in
            # either case. The cursor stays on the same row index rather than jumping
            # back to the top.
            cursor_row = table.cursor_row
            self._render_table()
            if table.row_count:
                table.move_cursor(row=min(cursor_row, table.row_count - 1))

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
