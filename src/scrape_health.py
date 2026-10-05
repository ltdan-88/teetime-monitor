"""Turns `storage.scrape_health()`'s summary into the one-line warning both front ends
show next to their freshness readout -- or nothing at all while scraping is healthy.

Added 2026-10-05. Found live in ~/Library/Logs/teetime-monitor.log: pc caddie rejected
the login for both real clubs for ~20 hours (every pass silently fell back to anonymous,
so no player names) and one club's course list failed on and off overnight. Both apps
kept saying "Updated N min ago" the whole time; nobody noticed.

Pure (no I/O, `now` passed in) so the TUI's `#status` line and the GUI's footer
(`scrapeHealthWarning()` in macos/Sources/Store.swift) can be cross-checked against
each other -- see scripts/cross_language_reference.py.

Two states, failing first because it's the worse one (no data arriving at all beats
"data without names"):
- `failing`: `consecutive_failed_runs >= FAILING_RUN_THRESHOLD`, or the last successful
  run is older than `STALE_INTERVAL_MULTIPLIER` x the scrape interval (the agent
  stopped). "Since" is when the current failure streak began, else the last success.
- `login_rejected`: an ongoing streak of rejected logins (see `scrape_health()`).
"""

from datetime import datetime, timedelta

from . import i18n

FAILING_RUN_THRESHOLD = 3
STALE_INTERVAL_MULTIPLIER = 3

STATUS_FAILING = "failing"
STATUS_LOGIN_REJECTED = "login_rejected"

# A "since" older than this also shows its date -- a bare weekday is ambiguous then.
_WEEKDAY_ONLY_WITHIN = timedelta(days=6)


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def health_status(health: dict, interval_minutes: int, now: datetime) -> tuple[str, str] | None:
    """(status, since-ISO) when unhealthy, else None. A database with no recorded runs
    is never unhealthy -- nothing is known about it yet."""
    if not health.get("last_run_at"):
        return None
    last_success = _parse(health.get("last_success_at"))
    stale = last_success is not None and (now - last_success) > timedelta(
        minutes=interval_minutes * STALE_INTERVAL_MULTIPLIER
    )
    failed_runs = health.get("consecutive_failed_runs", 0)
    if failed_runs >= FAILING_RUN_THRESHOLD or stale:
        since = health.get("failing_since") if failed_runs > 0 else None
        since = since or health.get("last_success_at")
        if since:
            return STATUS_FAILING, since
    if health.get("login_rejected_since"):
        return STATUS_LOGIN_REJECTED, health["login_rejected_since"]
    return None


def since_text(iso: str, now: datetime) -> str:
    """"Sat 18:45" in local time, or "Sat 09-28 18:45" once it's more than six days
    back -- the same weekday + MM-DD shape the TUI's booking banners already use."""
    moment = _parse(iso)
    if moment is None:
        return iso
    local = moment.astimezone()
    weekday = i18n.t(f"weekday.{local.weekday()}")
    clock = f"{local.hour:02d}:{local.minute:02d}"
    if now - moment > _WEEKDAY_ONLY_WITHIN:
        return f"{weekday} {local.month:02d}-{local.day:02d} {clock}"
    return f"{weekday} {clock}"


def health_warning(health: dict, interval_minutes: int, now: datetime) -> str | None:
    """The localized one-liner for `health_status()`, or None when healthy."""
    status = health_status(health, interval_minutes, now)
    if status is None:
        return None
    kind, since = status
    if kind == STATUS_LOGIN_REJECTED:
        return i18n.t("health.login_rejected", since=since_text(since, now))
    reason_kind = health.get("last_error_kind") or "none"
    return i18n.t("health.failing", since=since_text(since, now), reason=i18n.t(f"health.reason.{reason_kind}"))
