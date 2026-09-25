import json

from src import preview_club_cli
from src.scraper import NoTeeSheetError


def _run(capsys, argv):
    exit_code = 0
    try:
        preview_club_cli.main(argv)
    except SystemExit as exc:
        exit_code = exc.code
    return json.loads(capsys.readouterr().out), exit_code


def test_missing_club_id_is_rejected(capsys):
    result, code = _run(capsys, ["--club-name", "Golfclub Foo"])
    assert result == {"ok": False, "reason": "missing_club_id"}
    assert code == 1


def test_no_tee_sheet_is_reported_not_swallowed(monkeypatch, capsys):
    def fail(club_id):
        raise NoTeeSheetError

    monkeypatch.setattr(preview_club_cli, "fetch_course_aliases", fail)

    result, code = _run(capsys, ["--club-id", "0000001"])

    assert result == {"ok": False, "reason": "no_tee_sheet"}
    assert code == 1


def test_a_genuine_course_fetch_failure_is_reported_not_swallowed(monkeypatch, capsys):
    def fail(club_id):
        raise ConnectionError("no network")

    monkeypatch.setattr(preview_club_cli, "fetch_course_aliases", fail)

    result, code = _run(capsys, ["--club-id", "0000001"])

    assert result == {"ok": False, "reason": "course_fetch_failed", "error": "no network"}
    assert code == 1


def test_scrapes_the_unsaved_club_with_no_slug_and_force_true(monkeypatch, capsys):
    # club_id is unsaved -- no clubs/*.yaml, so no real slug exists for it. Mirrors
    # _open_club()'s own "a club reached from the directory usually has no saved
    # file at all" state exactly.
    monkeypatch.setattr(preview_club_cli, "fetch_course_aliases", lambda club_id: {"18 Loch Tee 1": ""})

    captured = {}

    def spy_scrape_due_for_club(slug, config, force=False):
        captured["slug"] = slug
        captured["config"] = config
        captured["force"] = force
        return []

    monkeypatch.setattr(preview_club_cli.scrape_once, "scrape_due_for_club", spy_scrape_due_for_club)

    result, code = _run(capsys, ["--club-id", "0000001", "--club-name", "Golfclub Foo"])

    assert result == {"ok": True}
    assert code == 0
    assert captured["slug"] is None
    assert captured["force"] is True
    assert captured["config"]["club_id"] == "0000001"


def test_works_without_a_club_name(monkeypatch, capsys):
    monkeypatch.setattr(preview_club_cli, "fetch_course_aliases", lambda club_id: {"18 Loch Tee 1": ""})
    monkeypatch.setattr(preview_club_cli.scrape_once, "scrape_due_for_club", lambda slug, config, force=False: [])

    result, code = _run(capsys, ["--club-id", "0000001"])

    assert result == {"ok": True}
    assert code == 0
