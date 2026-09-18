import io
import json

import pytest

from src import env_file, login_cli
from src.scraper import LoginError


@pytest.fixture(autouse=True)
def _isolated_env_file(monkeypatch, tmp_path):
    # login_cli reads/writes via env_file's module-level ENV_FILE (resolved at call
    # time, per env_file.py's own docstring on that gotcha) -- point it at a throwaway
    # file so this never touches the real ~/.config/teetime-monitor/.env.
    monkeypatch.setattr(env_file, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(login_cli.paths, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(login_cli.paths, "MANAGED_DIRS", (tmp_path,))


def _run(monkeypatch, capsys, payload, argv=None):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    exit_code = 0
    try:
        login_cli.main(argv or [])
    except SystemExit as exc:
        exit_code = exc.code
    return json.loads(capsys.readouterr().out), exit_code


def test_saves_without_club_id_and_skips_verification(monkeypatch, capsys):
    result, code = _run(monkeypatch, capsys, {"username": "someone@example.com", "password": "hunter2"})
    assert result == {"saved": True, "verified": None}
    assert code == 0
    assert env_file.load_env_value("PCC_USER") == "someone@example.com"
    assert env_file.load_env_value("PCC_PASS") == "hunter2"


def test_missing_username_is_rejected_and_nothing_is_saved(monkeypatch, capsys):
    result, code = _run(monkeypatch, capsys, {"username": "", "password": "hunter2"})
    assert result == {"saved": False, "reason": "username_required"}
    assert code == 1
    assert env_file.load_env_value("PCC_USER") is None


def test_blank_password_with_no_existing_password_is_rejected(monkeypatch, capsys):
    result, code = _run(monkeypatch, capsys, {"username": "someone@example.com", "password": ""})
    assert result == {"saved": False, "reason": "password_required"}
    assert code == 1


def test_blank_password_keeps_existing_saved_password(monkeypatch, capsys):
    env_file.set_env_values({"PCC_USER": "old@example.com", "PCC_PASS": "existingpass"})
    result, code = _run(monkeypatch, capsys, {"username": "someone@example.com", "password": ""})
    assert result == {"saved": True, "verified": None}
    assert code == 0
    assert env_file.load_env_value("PCC_USER") == "someone@example.com"
    assert env_file.load_env_value("PCC_PASS") == "existingpass"


def test_bad_stdin_json_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    with pytest.raises(SystemExit) as excinfo:
        login_cli.main([])
    assert excinfo.value.code == 1
    assert json.loads(capsys.readouterr().out) == {"saved": False, "reason": "bad_input"}


def test_verifies_login_and_reports_success(monkeypatch, capsys):
    fake_client = type("FakeClient", (), {"close": lambda self: None})()
    seen_calls = []
    monkeypatch.setattr(
        login_cli.scraper,
        "login",
        lambda club_id, user, password: (seen_calls.append((club_id, user, password)), fake_client)[1],
    )
    result, code = _run(
        monkeypatch, capsys,
        {"username": "someone@example.com", "password": "hunter2"},
        argv=["--club-id", "0000001"],
    )
    assert result == {"saved": True, "verified": True}
    assert code == 0
    assert seen_calls == [("0000001", "someone@example.com", "hunter2")]


def test_verifies_login_and_reports_rejection_without_undoing_the_save(monkeypatch, capsys):
    def fake_login(club_id, user, password):
        raise LoginError("nope")

    monkeypatch.setattr(login_cli.scraper, "login", fake_login)
    result, code = _run(
        monkeypatch, capsys,
        {"username": "someone@example.com", "password": "wrongpass"},
        argv=["--club-id", "0000001"],
    )
    assert result == {"saved": True, "verified": False, "reason": "login_failed"}
    assert code == 0
    # Same rule as CredentialsScreen: a rejected verification doesn't mean "don't
    # write what was typed."
    assert env_file.load_env_value("PCC_USER") == "someone@example.com"


def test_reports_unverified_on_a_network_hiccup_not_bad_credentials(monkeypatch, capsys):
    def fake_login(club_id, user, password):
        raise RuntimeError("no network")

    monkeypatch.setattr(login_cli.scraper, "login", fake_login)
    result, code = _run(
        monkeypatch, capsys,
        {"username": "someone@example.com", "password": "hunter2"},
        argv=["--club-id", "0000001"],
    )
    assert result == {"saved": True, "verified": None, "reason": "network_error", "error": "no network"}
    assert code == 0


def test_verification_uses_existing_saved_password_when_none_is_given(monkeypatch, capsys):
    env_file.set_env_values({"PCC_USER": "old@example.com", "PCC_PASS": "existingpass"})
    seen_calls = []
    fake_client = type("FakeClient", (), {"close": lambda self: None})()
    monkeypatch.setattr(
        login_cli.scraper,
        "login",
        lambda club_id, user, password: (seen_calls.append((club_id, user, password)), fake_client)[1],
    )
    result, code = _run(
        monkeypatch, capsys,
        {"username": "someone@example.com", "password": ""},
        argv=["--club-id", "0000001"],
    )
    assert result == {"saved": True, "verified": True}
    assert seen_calls == [("0000001", "someone@example.com", "existingpass")]
