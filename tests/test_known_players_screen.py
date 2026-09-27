import asyncio

from textual.app import App
from textual.widgets import DataTable, Static

from src import storage
from src.known_players_screen import KnownPlayersScreen


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


def test_lists_every_known_player(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players(["Max Mustermann", "Erika Mustermann"], "2026-09-27T10:00:00+00:00", path=db_path)

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            names = {str(table.get_row_at(i)[0]) for i in range(table.row_count)}
            assert names == {"Max Mustermann", "Erika Mustermann"}

    asyncio.run(scenario())


def test_selecting_a_row_marks_it_as_a_friend(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players(["Max Mustermann"], "2026-09-27T10:00:00+00:00", path=db_path)

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            table.move_cursor(row=0)
            await pilot.press("enter")
            await pilot.pause()
            assert table.get_row_at(0)[2] == "★"

    asyncio.run(scenario())
    assert storage.load_known_players(path=db_path)[0].is_friend is True


def test_selecting_an_already_friend_row_unmarks_it(tmp_path):
    db_path = tmp_path / "club.db"
    storage.record_seen_players(["Max Mustermann"], "2026-09-27T10:00:00+00:00", path=db_path)
    storage.set_player_friend("Max Mustermann", True, path=db_path)

    async def scenario():
        app = _HostApp("0000001", db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#players-table", DataTable)
            assert table.get_row_at(0)[2] == "★"
            table.move_cursor(row=0)
            await pilot.press("enter")
            await pilot.pause()
            assert table.get_row_at(0)[2] == ""

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
