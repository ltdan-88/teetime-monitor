import asyncio

from textual.app import App
from textual.widgets import DataTable, Input, Static, Switch

from src import storage
from src.known_players_screen import KnownPlayersScreen
from src.models import PlayerSighting


class _HostApp(App[None]):
    def __init__(self, club_id, db_path) -> None:
        super().__init__()
        self.club_id = club_id
        self.db_path = db_path
        self.result = "not set"

    def on_mount(self) -> None:
        self.push_screen(KnownPlayersScreen(self.club_id, self.db_path), self._on_dismissed)

    def _on_dismissed(self, result) -> None:
        self.result = result


def _sighting(name: str, **kwargs) -> PlayerSighting:
    return PlayerSighting(name=name, **kwargs)


def test_lists_every_known_player(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players(
        [_sighting("Max Mustermann"), _sighting("Erika Mustermann")], "2026-09-27T10:00:00+00:00", path=db_path
    )

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            names = {str(table.get_row_at(i)[0]) for i in range(table.row_count)}
            assert names == {"Max Mustermann", "Erika Mustermann"}

    asyncio.run(scenario())


def test_default_order_is_alphabetical_by_family_name(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players(
        [_sighting("Bernd Adler"), _sighting("Anna Zeller"), _sighting("Claus Bauer")],
        "2026-09-27T10:00:00+00:00",
        path=db_path,
    )

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            names = [str(table.get_row_at(i)[0]) for i in range(table.row_count)]
            assert names == ["Bernd Adler", "Claus Bauer", "Anna Zeller"]

    asyncio.run(scenario())


def test_shows_gender_member_status_and_handicap_columns(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players(
        [_sighting("Max Mustermann", gender="male", member_status="member", handicap=25.1)],
        "2026-09-27T10:00:00+00:00",
        path=db_path,
    )

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            row = table.get_row_at(0)
            assert row[1] == "Male"
            assert row[2] == "Member"
            assert row[3] == "25.1"

    asyncio.run(scenario())


def test_a_player_with_no_extra_data_shows_blank_cells(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players([_sighting("Max Mustermann")], "2026-09-27T10:00:00+00:00", path=db_path)

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            row = table.get_row_at(0)
            assert row[1] == ""
            assert row[2] == ""
            assert row[3] == ""

    asyncio.run(scenario())


def test_search_filters_by_substring_case_insensitively(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players(
        [_sighting("Max Mustermann"), _sighting("Erika Mustermann"), _sighting("Anna Zeller")],
        "2026-09-27T10:00:00+00:00",
        path=db_path,
    )

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            search = app.screen.query_one("#player-search", Input)
            search.value = "muster"
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            names = {str(table.get_row_at(i)[0]) for i in range(table.row_count)}
            assert names == {"Max Mustermann", "Erika Mustermann"}

    asyncio.run(scenario())


def test_clicking_a_column_header_sorts_by_it_and_toggles_direction(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players(
        [
            _sighting("Bernd Adler", handicap=10.0),
            _sighting("Anna Zeller", handicap=30.0),
            _sighting("Claus Bauer", handicap=20.0),
        ],
        "2026-09-27T10:00:00+00:00",
        path=db_path,
    )

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            from textual.widgets.data_table import ColumnKey

            table.post_message(DataTable.HeaderSelected(table, ColumnKey("handicap"), 3, table.columns[ColumnKey("handicap")].label))
            await pilot.pause()
            names = [str(table.get_row_at(i)[0]) for i in range(table.row_count)]
            assert names == ["Bernd Adler", "Claus Bauer", "Anna Zeller"]  # ascending handicap

            table.post_message(DataTable.HeaderSelected(table, ColumnKey("handicap"), 3, table.columns[ColumnKey("handicap")].label))
            await pilot.pause()
            names = [str(table.get_row_at(i)[0]) for i in range(table.row_count)]
            assert names == ["Anna Zeller", "Claus Bauer", "Bernd Adler"]  # descending handicap

    asyncio.run(scenario())


def test_selecting_a_row_marks_it_as_a_friend(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players([_sighting("Max Mustermann")], "2026-09-27T10:00:00+00:00", path=db_path)

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            table.move_cursor(row=0)
            await pilot.press("enter")
            await pilot.pause()
            assert table.get_row_at(0)[4] == "★"

    asyncio.run(scenario())
    assert storage.load_known_players(path=db_path)[0].is_friend is True


def test_selecting_an_already_friend_row_unmarks_it(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players([_sighting("Max Mustermann")], "2026-09-27T10:00:00+00:00", path=db_path)
    storage.set_player_friend("Max Mustermann", True, path=db_path)

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            assert table.get_row_at(0)[4] == "★"
            table.move_cursor(row=0)
            await pilot.press("enter")
            await pilot.pause()
            assert table.get_row_at(0)[4] == ""

    asyncio.run(scenario())
    assert storage.load_known_players(path=db_path)[0].is_friend is False


def test_shows_a_message_instead_of_a_table_with_no_club(tmp_path):
    async def scenario():
        app = _HostApp(None, None)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.screen.query("#players-table")) == 0
            assert app.screen.query_one("#empty", Static)

    asyncio.run(scenario())


def test_escape_dismisses_the_screen(tmp_path):
    db_path = tmp_path / "club.db"

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        return app.result

    result = asyncio.run(scenario())
    assert result is None


def test_friends_only_switch_hides_everyone_who_is_not_a_friend(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players(
        [_sighting("Max Mustermann"), _sighting("Erika Mustermann"), _sighting("Anna Zeller")],
        "2026-09-27T10:00:00+00:00",
        path=db_path,
    )
    storage.set_player_friend("Anna Zeller", True, path=db_path)

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            assert table.row_count == 3
            app.screen.query_one("#friends-only", Switch).value = True
            await pilot.pause()
            assert [str(table.get_row_at(i)[0]) for i in range(table.row_count)] == ["Anna Zeller"]
            app.screen.query_one("#friends-only", Switch).value = False
            await pilot.pause()
            assert table.row_count == 3

    asyncio.run(scenario())


def test_sorting_by_friend_puts_friends_first_then_last_when_reversed(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players(
        [_sighting("Bernd Adler"), _sighting("Anna Zeller"), _sighting("Claus Bauer")],
        "2026-09-27T10:00:00+00:00",
        path=db_path,
    )
    storage.set_player_friend("Anna Zeller", True, path=db_path)

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            screen._sort_key = "friend"
            screen._sort_reverse = False
            assert screen._visible_players()[0].name == "Anna Zeller"
            screen._sort_reverse = True
            assert screen._visible_players()[-1].name == "Anna Zeller"

    asyncio.run(scenario())
