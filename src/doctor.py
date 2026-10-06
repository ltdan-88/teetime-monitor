"""`teetime-monitor --doctor`: a one-shot environment report for new installs and bug
reports (2026-10-06). Plain English on purpose -- it's meant to be pasted into an issue
or a chat. It never prints secrets: credentials and API keys show only as set / not set.

Makes at most one network request (HTTPS to www.pccaddie.net, to test connectivity and
certificate trust, the usual failure on a corporate PC); `--offline` skips it. Exit code
1 when a check failed, 0 otherwise (warnings don't fail).
"""

import importlib.metadata
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import ai_assist, club_config, global_preferences, net, paths, scrape_health, scrape_once, storage

CONNECTIVITY_URL = "https://www.pccaddie.net/"

# (status, label, detail) -- status is one of OK / WARN / FAIL / INFO.
Check = tuple[str, str, str]


def _version() -> str:
    try:
        return importlib.metadata.version("teetime-monitor")
    except importlib.metadata.PackageNotFoundError:
        return "dev (not installed)"


def _writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".doctor-probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _system_checks() -> list[Check]:
    checks: list[Check] = [
        ("INFO", "teetime-monitor", _version()),
        ("INFO", "Python", f"{platform.python_version()} ({sys.executable})"),
        ("INFO", "Platform", f"{platform.system()} {platform.release()} {platform.machine()}"),
        ("INFO", "Encoding", f"stdout={getattr(sys.stdout, 'encoding', '?')} filesystem={sys.getfilesystemencoding()}"),
    ]
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo("Europe/Berlin")
        checks.append(("OK", "Time zone data", "Europe/Berlin loads"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("FAIL", "Time zone data", f"Europe/Berlin missing ({exc}) -- install the tzdata package"))
    return checks


def _folder_checks() -> list[Check]:
    checks: list[Check] = []
    for label, directory in (("Config folder", paths.CONFIG_DIR), ("Data folder", paths.DATA_DIR)):
        ok = _writable(directory)
        checks.append(("OK" if ok else "FAIL", label, f"{directory}" + ("" if ok else " -- not writable")))
    for variable in ("TEETIME_MONITOR_CONFIG_DIR", "TEETIME_MONITOR_DATA_DIR"):
        if os.environ.get(variable):
            checks.append(("INFO", variable, os.environ[variable]))
    return checks


def _network_checks(offline: bool) -> list[Check]:
    checks: list[Check] = [("INFO", "Certificate trust", net.trust_description())]
    if offline:
        checks.append(("INFO", "Connectivity", "skipped (--offline)"))
        return checks
    import httpx

    try:
        response = httpx.get(CONNECTIVITY_URL, timeout=10, follow_redirects=True)
        checks.append(("OK", "Connectivity", f"{CONNECTIVITY_URL} answered HTTP {response.status_code}"))
    except httpx.ConnectError as exc:
        text = str(exc)
        if "CERTIFICATE" in text.upper() or "SSL" in text.upper():
            hint = (
                "certificate not trusted -- if your company inspects HTTPS traffic, point SSL_CERT_FILE at its CA bundle "
                "(see the README)"
            )
            checks.append(("FAIL", "Connectivity", f"{text} -- {hint}"))
        else:
            checks.append(("FAIL", "Connectivity", f"cannot connect: {text}"))
    except httpx.HTTPError as exc:
        checks.append(("FAIL", "Connectivity", f"{type(exc).__name__}: {exc}"))
    return checks


def _club_checks(now: datetime) -> list[Check]:
    checks: list[Check] = []
    slugs = club_config.list_clubs()
    if not slugs:
        return [("WARN", "Clubs", "none saved yet -- open the club browser and press f on a club")]
    preferences = global_preferences.load_preferences()
    interval = int(preferences.get("scrape_interval_minutes") or 360)
    for slug in slugs:
        try:
            config = club_config.load_club_config(slug)
        except Exception as exc:  # noqa: BLE001
            checks.append(("FAIL", f"Club {slug}", f"config unreadable: {exc}"))
            continue
        club_id = str(config.get("club_id") or "")
        if not club_id:
            checks.append(("FAIL", f"Club {slug}", "no club_id in its YAML"))
            continue
        user, password = club_config.resolve_credentials(club_id)
        login = "login set" if user and password else "no login (anonymous scraping)"
        db_path = scrape_once._db_path(club_id)
        if not db_path.exists():
            checks.append(("WARN", f"Club {slug} ({club_id})", f"{login}; no scrape history yet"))
            continue
        try:
            with sqlite3.connect(db_path) as conn:
                journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
                last = conn.execute("SELECT MAX(scraped_at) FROM scrapes").fetchone()[0]
            size_mb = db_path.stat().st_size / 1_000_000
            health = storage.scrape_health(db_path)
            warning = scrape_health.health_warning(health, interval, now)
            detail = f"{login}; database {size_mb:.1f} MB ({journal}); last scrape {last or 'never'}"
            if warning:
                checks.append(("WARN", f"Club {slug} ({club_id})", f"{detail}; {warning}"))
            else:
                checks.append(("OK", f"Club {slug} ({club_id})", detail))
        except sqlite3.Error as exc:
            checks.append(("FAIL", f"Club {slug} ({club_id})", f"database problem: {exc}"))
    return checks


def _ai_checks() -> list[Check]:
    ai = global_preferences.load_preferences().get("ai_assist")
    if not isinstance(ai, dict) or not ai.get("enabled"):
        return [("INFO", "AI ranking", "off")]
    provider = ai.get("provider") or "anthropic"
    variable = ai_assist.PROVIDER_ENV_VARS.get(provider)
    key_set = bool(variable and os.environ.get(variable))
    status = "OK" if key_set else "WARN"
    return [(status, "AI ranking", f"on ({provider}); API key {'set' if key_set else 'NOT set'}")]


def _scheduler_check() -> Check:
    system = platform.system()
    try:
        if system == "Darwin":
            plist = Path.home() / "Library" / "LaunchAgents" / "com.teetimemonitor.scrape.plist"
            if not plist.exists():
                return ("WARN", "Background scraper", f"launchd agent not installed ({plist.name}) -- see the README")
            listed = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10).stdout
            loaded = "com.teetimemonitor.scrape" in listed
            return ("OK" if loaded else "WARN", "Background scraper", "launchd agent loaded" if loaded else "plist exists but agent not loaded")
        if system == "Windows":
            if shutil.which("schtasks") is None:
                return ("INFO", "Background scraper", "schtasks not found")
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", "teetime-monitor-scrape"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return ("OK", "Background scraper", "scheduled task 'teetime-monitor-scrape' exists")
            return ("WARN", "Background scraper", "scheduled task not found -- see the README")
    except (OSError, subprocess.SubprocessError) as exc:
        return ("INFO", "Background scraper", f"could not check ({exc})")
    return ("INFO", "Background scraper", f"no built-in check for {system}; use cron or a systemd timer")


def collect(offline: bool = False, now: datetime | None = None) -> list[Check]:
    now = now or datetime.now(UTC)
    checks = _system_checks() + _folder_checks() + _network_checks(offline) + _club_checks(now) + _ai_checks()
    checks.append(_scheduler_check())
    return checks


def render(checks: list[Check]) -> str:
    width = max(len(label) for _, label, _ in checks)
    lines = ["teetime-monitor --doctor", ""]
    lines += [f"[{status:4}] {label:<{width}}  {detail}" for status, label, detail in checks]
    failed = sum(1 for status, _, _ in checks if status == "FAIL")
    warned = sum(1 for status, _, _ in checks if status == "WARN")
    lines += ["", f"{failed} failed, {warned} warnings"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    checks = collect(offline="--offline" in argv)
    print(render(checks))
    return 1 if any(status == "FAIL" for status, _, _ in checks) else 0
