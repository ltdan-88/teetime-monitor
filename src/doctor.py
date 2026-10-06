"""`teetime-monitor --doctor`: a one-shot environment report for new installs and bug
reports (2026-10-06). Plain English on purpose -- it's meant to be pasted into an issue
or a chat. It never prints secrets: credentials and API keys show only as set / not set.

Makes at most one network request by default (HTTPS to www.pccaddie.net, to test connectivity and
certificate trust, the usual failure behind a proxy); `--offline` skips it. `--login-check` also logs
in with the stored credentials and compares logged-in and anonymous tee sheets (never printing
credentials), for "login works but no player names". Exit code
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

from . import ai_assist, club_config, global_preferences, net, paths, scrape_health, scrape_once, scraper, storage

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


def _player_name_summary(conn: sqlite3.Connection) -> str:
    """Whether the latest scrapes carry real player names, and whether the last scrape pass
    was logged in. Names come only from a logged-in scrape (and only if the club shares them),
    so "0 of N booked slots named" with a set login points at the login step of the scrape,
    not at parsing (2026-10-06, a Windows install showed tee times but no names)."""
    try:
        booked, named = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(s.players IS NOT NULL AND s.players NOT IN ('', '[]')), 0) "
            "FROM slots s JOIN (SELECT MAX(id) AS id FROM scrapes WHERE date >= date('now', '-1 day') GROUP BY course, date) latest "
            "ON s.scrape_id = latest.id WHERE s.booked > 0"
        ).fetchone()
        run = conn.execute(
            "SELECT authenticated, error_kind FROM scrape_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return "player names: unknown"
    text = f"player names: {named} of {booked} booked slots named on upcoming days"
    if run is not None:
        authenticated, error_kind = run
        state = {1: "logged in", 0: "NOT logged in (anonymous)"}.get(authenticated, "login not attempted")
        text += f"; last pass {state}" + (f", {error_kind}" if error_kind else "")
    return text


def _login_probe(slug: str, config: dict) -> list[Check]:
    """`--doctor --login-check`: log in with the stored credentials (the report never contains
    them) and compare what the tee sheet shows to a logged-in session against an anonymous
    one. Meant for "login works but there are no player names" (2026-10-06, a Windows install):
    scraper.login() counts any answer without a password field as success, so a block page or
    consent wall would pass; this shows what the session really sees."""
    club_id = str(config.get("club_id") or "")
    label = f"Login check {slug}"
    user, password = club_config.resolve_credentials(club_id)
    if not (user and password):
        return [("WARN", label, "no login stored for this club")]
    try:
        client = scraper.login(club_id, user, password)
    except scraper.LoginError:
        return [("FAIL", label, "pc caddie rejected the stored login")]
    except Exception as exc:  # noqa: BLE001
        return [("FAIL", label, f"login request failed: {type(exc).__name__}: {exc}")]
    checks: list[Check] = []
    try:
        cookie_names = sorted({cookie.name for cookie in client.cookies.jar})
        checks.append(("INFO", label, f"login answered; session cookies: {', '.join(cookie_names) or 'none'}"))
        aliases = scraper.fetch_course_aliases(club_id)
        course = config.get("default_course") if config.get("default_course") in aliases else next(iter(aliases))
        dates = scraper.fetch_available_dates(club_id)
        day = dates[0] if dates else (datetime.now(UTC).date().isoformat())
        page = client.get(scraper.club_url(club_id, scraper.TEE_SHEET_CATEGORY, day, aliases[course]))
        soup = scraper.BeautifulSoup(page.text, "html.parser")
        title = (soup.title.get_text(strip=True) if soup.title else "")[:80]
        spans = [span.get_text(strip=True) for span in soup.select(".tt-show-name")]
        placeholders = {text for text in spans if text in scraper.KNOWN_ANONYMIZED_LABELS}
        other = [text for text in spans if text and text not in scraper.KNOWN_ANONYMIZED_LABELS]
        logout = any(marker in page.text.lower() for marker in ("logout", "abmelden", "se déconnecter"))
        checks.append((
            "INFO", label,
            f"{course} {day}: HTTP {page.status_code}, title {title!r}, final URL path {page.url.path}, "
            f"login form present: {scraper._PASSWORD_FIELD in page.text}, logout link: {logout}",
        ))
        authed = scraper.scrape_schedule(club_id, course, day, aliases, client=client)
        anon = scraper.scrape_schedule(club_id, course, day, aliases)

        def named(schedule) -> int:
            return sum(len(slot.players) for slot in schedule.slots)

        verdict = "OK" if named(authed) > 0 else "WARN"
        checks.append((
            verdict, label,
            f"named seats: logged in {named(authed)}, anonymous {named(anon)}; seat labels on the page: "
            f"{len(other)} name-like, {len(spans) - len(other)} placeholder/empty"
            + (f" (placeholders: {'; '.join(sorted(placeholders))})" if placeholders else ""),
        ))
        if verdict == "WARN":
            checks.append((
                "INFO", label,
                "0 names while logged in: either this pc caddie account has not enabled name sharing at "
                "this club (placeholders such as 'Belegt'/'Occupied' stay), or the session is not really "
                "logged in (no logout link, a different title, or a login form on the page).",
            ))
    except Exception as exc:  # noqa: BLE001
        checks.append(("FAIL", label, f"probe failed: {type(exc).__name__}: {exc}"))
    finally:
        client.close()
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
                names = _player_name_summary(conn)
            size_mb = db_path.stat().st_size / 1_000_000
            health = storage.scrape_health(db_path)
            warning = scrape_health.health_warning(health, interval, now)
            detail = f"{login}; database {size_mb:.1f} MB ({journal}); last scrape {last or 'never'}; {names}"
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


def collect(offline: bool = False, now: datetime | None = None, login_check: bool = False) -> list[Check]:
    now = now or datetime.now(UTC)
    checks = _system_checks() + _folder_checks() + _network_checks(offline) + _club_checks(now) + _ai_checks()
    if login_check and not offline:
        for slug in club_config.list_clubs():
            try:
                config = club_config.load_club_config(slug)
            except Exception:  # noqa: BLE001 -- already reported by _club_checks
                continue
            if config.get("club_id"):
                checks += _login_probe(slug, config)
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
    checks = collect(offline="--offline" in argv, login_check="--login-check" in argv)
    print(render(checks))
    return 1 if any(status == "FAIL" for status, _, _ in checks) else 0
