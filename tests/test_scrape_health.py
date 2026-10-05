"""scrape_health.py -- the one-line warning both front ends show next to their
freshness readout while scraping is unhealthy (2026-10-05)."""

from datetime import UTC, datetime, timedelta

import pytest

from src import i18n, scrape_health, storage

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
INTERVAL = 360


def _health(**overrides) -> dict:
    """A healthy history: the agent's last run (a no-op) finished 5 minutes ago."""
    health = storage.empty_scrape_health()
    last = (NOW - timedelta(minutes=5)).isoformat()
    health.update(last_run_at=last, last_success_at=last)
    health.update(overrides)
    return health


def _since(moment: datetime) -> str:
    return scrape_health.since_text(moment.isoformat(), NOW)


def test_nothing_recorded_is_not_a_warning():
    assert scrape_health.health_warning(storage.empty_scrape_health(), INTERVAL, NOW) is None


def test_a_healthy_history_shows_nothing():
    assert scrape_health.health_status(_health(), INTERVAL, NOW) is None
    assert scrape_health.health_warning(_health(), INTERVAL, NOW) is None


def test_login_rejected_streak():
    since = datetime(2026, 10, 3, 16, 45, tzinfo=UTC)
    health = _health(login_rejected_since=since.isoformat(), last_error_kind="login_rejected")
    assert scrape_health.health_status(health, INTERVAL, NOW) == ("login_rejected", since.isoformat())
    assert scrape_health.health_warning(health, INTERVAL, NOW) == (
        f"⚠ Login rejected since {_since(since)} — player names unavailable; check Settings → Login"
    )


def test_login_rejected_in_german():
    since = datetime(2026, 10, 3, 16, 45, tzinfo=UTC)
    i18n.set_language("de")
    warning = scrape_health.health_warning(_health(login_rejected_since=since.isoformat()), INTERVAL, NOW)
    assert warning == f"⚠ Login abgelehnt seit {_since(since)} — keine Spielernamen; Einstellungen → pc caddie Anmeldung prüfen"
    assert _since(since).split()[0] in {"Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"}


def test_two_failed_runs_are_not_yet_a_warning():
    health = _health(consecutive_failed_runs=2, failing_since=(NOW - timedelta(minutes=30)).isoformat(),
                     last_error_kind="network")
    assert scrape_health.health_warning(health, INTERVAL, NOW) is None


def test_three_failed_runs_are():
    since = NOW - timedelta(minutes=45)
    health = _health(consecutive_failed_runs=3, failing_since=since.isoformat(), last_error_kind="no_tee_sheet",
                     last_success_at=(NOW - timedelta(minutes=50)).isoformat())
    assert scrape_health.health_status(health, INTERVAL, NOW) == ("failing", since.isoformat())
    assert scrape_health.health_warning(health, INTERVAL, NOW) == (
        f"⚠ Scrapes failing since {_since(since)}: pc caddie showed no tee sheet"
    )


@pytest.mark.parametrize(
    "kind, reason",
    [("network", "network error"), ("other", "unexpected error"), ("login_rejected", "login rejected"),
     (None, "no recent scrape")],
)
def test_every_reason_has_text(kind, reason):
    health = _health(consecutive_failed_runs=3, failing_since=NOW.isoformat(), last_error_kind=kind)
    assert scrape_health.health_warning(health, INTERVAL, NOW).endswith(f": {reason}")


def test_a_stale_last_success_means_failing_since_then():
    # The agent stopped: its last (successful) run is far older than 3x the interval.
    last = NOW - timedelta(minutes=INTERVAL * 3 + 1)
    health = _health(last_run_at=last.isoformat(), last_success_at=last.isoformat())
    assert scrape_health.health_status(health, INTERVAL, NOW) == ("failing", last.isoformat())
    assert scrape_health.health_warning(health, INTERVAL, NOW).endswith(": no recent scrape")


def test_just_inside_the_stale_window_is_fine():
    last = NOW - timedelta(minutes=INTERVAL * 3 - 1)
    assert scrape_health.health_status(_health(last_success_at=last.isoformat()), INTERVAL, NOW) is None


def test_the_stale_window_follows_the_interval():
    last = NOW - timedelta(minutes=200)
    health = _health(last_success_at=last.isoformat())
    assert scrape_health.health_status(health, 60, NOW) == ("failing", last.isoformat())
    assert scrape_health.health_status(health, 360, NOW) is None


def test_failing_wins_over_login_rejected():
    since = NOW - timedelta(hours=2)
    health = _health(consecutive_failed_runs=4, failing_since=since.isoformat(),
                     login_rejected_since=(NOW - timedelta(hours=20)).isoformat(), last_error_kind="login_rejected")
    assert scrape_health.health_status(health, INTERVAL, NOW) == ("failing", since.isoformat())


def test_since_text_is_local_weekday_and_time():
    moment = datetime(2026, 10, 3, 16, 45, tzinfo=UTC)
    local = moment.astimezone()
    assert _since(moment) == f"{i18n.t(f'weekday.{local.weekday()}')} {local:%H:%M}"


def test_since_text_adds_the_date_beyond_six_days():
    moment = NOW - timedelta(days=9)
    local = moment.astimezone()
    assert _since(moment) == f"{i18n.t(f'weekday.{local.weekday()}')} {local:%m-%d} {local:%H:%M}"
