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
    monkeypatch.setattr(doctor, "collect", lambda offline=False: [("OK", "a", "fine"), ("WARN", "b", "meh")])
    assert doctor.main(["--offline"]) == 0
    monkeypatch.setattr(doctor, "collect", lambda offline=False: [("FAIL", "a", "broken")])
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
