"""`teetime-monitor --doctor` -- environment report; never prints secrets."""

import sys
from datetime import UTC, datetime

import httpx
import pytest

from src import club_config, doctor, paths, scrape_once, storage
from src.models import Schedule, Slot

NOW = datetime(2026, 10, 6, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(doctor, "_scheduler_check", lambda: ("INFO", "Background scraper", "not checked in tests"))


def _statuses(checks):
    return {label: status for status, label, _ in checks}


def test_offline_report_has_the_basics_and_no_network_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no network in --offline")

    monkeypatch.setattr(httpx, "get", boom)
    checks = doctor.collect(offline=True, now=NOW)
    labels = _statuses(checks)
    assert labels["Config folder"] == "OK" and labels["Data folder"] == "OK"
    assert labels["Connectivity"] == "INFO"
    assert labels["Clubs"] == "WARN"  # none saved


def test_connectivity_ok_and_certificate_failure_hint(monkeypatch):
    class Response:
        status_code = 200

    monkeypatch.setattr(httpx, "get", lambda *a, **k: Response())
    assert _statuses(doctor.collect(now=NOW))["Connectivity"] == "OK"

    def cert_error(*a, **k):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in chain")

    monkeypatch.setattr(httpx, "get", cert_error)
    checks = doctor.collect(now=NOW)
    detail = next(d for s, label, d in checks if label == "Connectivity")
    assert _statuses(checks)["Connectivity"] == "FAIL" and "SSL_CERT_FILE" in detail


def test_a_saved_club_reports_database_journal_mode_and_login_without_the_secret(monkeypatch, tmp_path):
    monkeypatch.setattr(club_config, "list_clubs", lambda *a, **k: ["demo"])
    monkeypatch.setattr(club_config, "load_club_config", lambda slug, *a, **k: {"club_id": "0000001"})
    monkeypatch.setattr(club_config, "resolve_credentials", lambda club_id: ("demo-user", "super-secret-password"))
    db = scrape_once._db_path("0000001")
    db.parent.mkdir(parents=True, exist_ok=True)
    storage.save_schedule(Schedule(date="2026-10-06", course="18 Loch Tee 1", slots=[Slot("09:00", 0, 4)]), path=db)

    checks = doctor.collect(offline=True, now=NOW)
    text = doctor.render(checks)
    club = next(d for s, label, d in checks if label.startswith("Club demo"))
    assert "login set" in club and "wal" in club and "last scrape" in club
    assert "super-secret-password" not in text and "demo-user" not in text


def test_a_missing_ai_key_is_a_warning_and_never_printed(monkeypatch):
    monkeypatch.setattr(
        doctor.global_preferences, "load_preferences", lambda *a, **k: {"ai_assist": {"enabled": True, "provider": "gemini"}}
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert _statuses(doctor._ai_checks())["AI ranking"] == "WARN"
    monkeypatch.setenv("GEMINI_API_KEY", "key-value-123")
    status, _, detail = doctor._ai_checks()[0]
    assert status == "OK" and "key-value-123" not in detail


def test_exit_code_is_one_only_when_a_check_failed(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "collect", lambda offline=False, login_check=False: [("OK", "a", "fine"), ("WARN", "b", "meh")])
    assert doctor.main(["--offline"]) == 0
    monkeypatch.setattr(doctor, "collect", lambda offline=False, login_check=False: [("FAIL", "a", "broken")])
    assert doctor.main([]) == 1
    assert "1 failed" in capsys.readouterr().out


def test_tui_main_routes_doctor_flag(monkeypatch):
    from src import tui

    called = []
    monkeypatch.setattr(sys, "argv", ["teetime-monitor", "--doctor", "--offline"])
    monkeypatch.setattr(doctor, "main", lambda argv=None: called.append(argv) or 0)
    with pytest.raises(SystemExit) as exit_info:
        tui.main()
    assert exit_info.value.code == 0 and called == [["--doctor", "--offline"]]


def test_player_name_summary_reports_named_slots_and_login_state(tmp_path):
    from datetime import UTC, date, datetime, timedelta

    db = tmp_path / "club.db"
    storage.save_schedule(
        Schedule(
            date=(date.today() + timedelta(days=2)).isoformat(),
            course="18 Loch Tee 1",
            slots=[
                Slot("09:00", 2, 4, players=["Max Mustermann", "Erika Musterfrau"]),
                Slot("09:10", 1, 4),  # booked but anonymous
                Slot("09:20", 0, 4),  # free, not counted
            ],
        ),
        path=db,
    )
    now = datetime.now(UTC).isoformat()
    storage.record_scrape_run(
        started_at=now, finished_at=now, source="agent", attempted=1, saved=1, failed=0,
        authenticated=False, error_kind="login_rejected", path=db,
    )
    import sqlite3

    with sqlite3.connect(db) as conn:
        text = doctor._player_name_summary(conn)
    assert "1 of 2 booked slots named" in text
    assert "NOT logged in" in text and "login_rejected" in text


class _FakeCookie:
    def __init__(self, name):
        self.name = name


class _FakeResponse:
    status_code = 200
    url = type("U", (), {"path": "/clubs/0000001/app.php"})()

    def __init__(self, text):
        self.text = text


class _FakeClient:
    def __init__(self, text):
        self._text = text
        self.cookies = type("J", (), {"jar": [_FakeCookie("PHPSESSID")]})()
        self.closed = False

    def get(self, url):
        return _FakeResponse(self._text)

    def close(self):
        self.closed = True


def _probe_setup(monkeypatch, page_html, authed_names):
    from src import scraper

    monkeypatch.setattr(club_config, "resolve_credentials", lambda club_id: ("demo-user", "super-secret-password"))
    client = _FakeClient(page_html)
    monkeypatch.setattr(scraper, "login", lambda *a, **k: client)
    monkeypatch.setattr(scraper, "fetch_course_aliases", lambda club_id: {"18 Loch Tee 1": "ALIAS"})
    monkeypatch.setattr(scraper, "fetch_available_dates", lambda club_id: ["2026-10-07"])

    def fake_schedule(club_id, course, day, aliases=None, client=None):
        players = authed_names if client is not None else []
        return Schedule(date=day, course=course, slots=[Slot("09:00", 2, 4, players=list(players))])

    monkeypatch.setattr(scraper, "scrape_schedule", fake_schedule)
    return client


def test_login_check_reports_names_without_leaking_credentials(monkeypatch):
    client = _probe_setup(
        monkeypatch,
        "<html><title>Tee sheet</title><a href='?logout'>Logout</a>"
        "<span class='tt-show-name'>Max Mustermann</span><span class='tt-show-name'>Belegt</span></html>",
        ["Max Mustermann", "Erika Musterfrau"],
    )
    checks = doctor._login_probe("demo", {"club_id": "0000001"})
    text = doctor.render(checks)
    assert "named seats: logged in 2, anonymous 0" in text
    assert "logout link: True" in text and "PHPSESSID" in text
    assert "super-secret-password" not in text and "demo-user" not in text
    assert client.closed and _statuses(checks)["Login check demo"] in {"OK", "INFO"}


def test_login_check_warns_when_logged_in_but_no_names(monkeypatch):
    _probe_setup(monkeypatch, "<html><title>Access denied</title></html>", [])
    checks = doctor._login_probe("demo", {"club_id": "0000001"})
    statuses = [status for status, _, _ in checks]
    assert "WARN" in statuses
    assert any("not really" in detail for _, _, detail in checks)
    assert any("logout link: False" in detail for _, _, detail in checks)


def test_login_check_rejected_login_is_a_failure(monkeypatch):
    from src import scraper

    monkeypatch.setattr(club_config, "resolve_credentials", lambda club_id: ("u", "p"))

    def reject(*a, **k):
        raise scraper.LoginError("no")

    monkeypatch.setattr(scraper, "login", reject)
    assert doctor._login_probe("demo", {"club_id": "0000001"})[0][0] == "FAIL"
    monkeypatch.setattr(club_config, "resolve_credentials", lambda club_id: ("", ""))
    assert doctor._login_probe("demo", {"club_id": "0000001"})[0][0] == "WARN"
