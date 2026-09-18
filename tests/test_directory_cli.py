import json

from src import directory_cli


def _run(capsys, argv):
    exit_code = 0
    try:
        directory_cli.main(argv)
    except SystemExit as exc:
        exit_code = exc.code
    return json.loads(capsys.readouterr().out), exit_code


def test_refreshes_using_any_credentials_when_available(monkeypatch, capsys):
    monkeypatch.setattr(directory_cli.club_directory, "any_credentials",
                         lambda: ("0000001", "someone@example.com", "hunter2"))
    seen_calls = []
    monkeypatch.setattr(directory_cli.club_directory, "refresh_directory",
                         lambda club_id, user, password: seen_calls.append((club_id, user, password))
                         or [("0000001", "Golfclub Foo")])

    result, code = _run(capsys, [])

    assert result == {"ok": True, "count": 1}
    assert code == 0
    assert seen_calls == [("0000001", "someone@example.com", "hunter2")]


def test_falls_back_to_a_typed_club_id_when_no_favorite_has_credentials(monkeypatch, capsys):
    monkeypatch.setattr(directory_cli.club_directory, "any_credentials", lambda: None)
    monkeypatch.setattr(directory_cli.club_directory, "credentials_configured", lambda: True)
    monkeypatch.setattr(directory_cli.club_config, "resolve_credentials",
                         lambda club_id: ("someone@example.com", "hunter2"))
    seen_calls = []
    monkeypatch.setattr(directory_cli.club_directory, "refresh_directory",
                         lambda club_id, user, password: seen_calls.append((club_id, user, password)) or [])

    result, code = _run(capsys, ["--club-id", "0000002"])

    assert result == {"ok": True, "count": 0}
    assert code == 0
    assert seen_calls == [("0000002", "someone@example.com", "hunter2")]


def test_needs_login_when_nothing_is_configured_at_all(monkeypatch, capsys):
    monkeypatch.setattr(directory_cli.club_directory, "any_credentials", lambda: None)
    monkeypatch.setattr(directory_cli.club_directory, "credentials_configured", lambda: False)

    result, code = _run(capsys, [])

    assert result == {"ok": False, "reason": "needs_login"}
    assert code == 1


def test_needs_a_club_when_credentials_exist_but_nothing_to_pair_them_with(monkeypatch, capsys):
    monkeypatch.setattr(directory_cli.club_directory, "any_credentials", lambda: None)
    monkeypatch.setattr(directory_cli.club_directory, "credentials_configured", lambda: True)

    # No --club-id given, so the credentials_configured=True fallback path never
    # gets a club to authenticate against either.
    result, code = _run(capsys, [])

    assert result == {"ok": False, "reason": "needs_a_club"}
    assert code == 1


def test_fetch_failure_is_reported_not_raised(monkeypatch, capsys):
    monkeypatch.setattr(directory_cli.club_directory, "any_credentials",
                         lambda: ("0000001", "someone@example.com", "hunter2"))

    def boom(club_id, user, password):
        raise RuntimeError("pc caddie is down")

    monkeypatch.setattr(directory_cli.club_directory, "refresh_directory", boom)

    result, code = _run(capsys, [])

    assert result == {"ok": False, "reason": "fetch_failed", "error": "pc caddie is down"}
    assert code == 1
