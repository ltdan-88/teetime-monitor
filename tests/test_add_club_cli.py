import json

from src import add_club_cli, club_config


def _run(capsys, argv):
    exit_code = 0
    try:
        add_club_cli.main(argv)
    except SystemExit as exc:
        exit_code = exc.code
    return json.loads(capsys.readouterr().out), exit_code


def test_missing_club_id_is_rejected(capsys):
    result, code = _run(capsys, ["--name", "Golfclub Foo"])
    assert result == {"ok": False, "reason": "missing_club_id"}
    assert code == 1


def test_adds_a_club_and_returns_its_slug(capsys):
    # club_config.CLUBS_DIR is already patched to a throwaway tmp_path by
    # conftest.py's autouse _no_real_state_directories fixture -- same isolation
    # every other CLI/screen test in this suite already relies on.
    result, code = _run(capsys, ["--club-id", "0000001", "--name", "Golfclub Domäne Musterhausen e.V."])

    assert code == 0
    assert result["ok"] is True
    assert result["slug"] == "golfclub-domane-musterhausen-e-v"
    assert club_config.load_club_config(result["slug"])["club_id"] == "0000001"


def test_is_idempotent_like_add_favorite_itself(capsys):
    first, _ = _run(capsys, ["--club-id", "0000001", "--name", "Musterhausen"])
    second, _ = _run(capsys, ["--club-id", "0000001", "--name", "Musterhausen"])
    assert first["slug"] == second["slug"]
    assert club_config.list_clubs() == [first["slug"]]


def test_falls_back_to_club_id_without_a_name(capsys):
    result, _ = _run(capsys, ["--club-id", "0000001"])
    assert result["slug"] == "club-0000001"


def test_geocodes_the_clubs_name_best_effort(monkeypatch, capsys):
    monkeypatch.setattr(club_config.geocode, "find_club_location", lambda name: (50.1234567, 8.1234567))
    result, _ = _run(capsys, ["--club-id", "0000002", "--name", "Golf Club Sonnenberg e.V."])
    assert club_config.load_club_config(result["slug"])["location"] == {"lat": 50.1234567, "lon": 8.1234567}
