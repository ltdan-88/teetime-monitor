"""Is there a newer release? And, on a Raspberry Pi server, installing it (2026-10-11).

- **The notice (every install).** Every few hours the server asks GitHub for the newest release (one plain
  GET of the public releases page, nothing about you is sent) and remembers the answer; the page shows
  "Version X is available" with a link to the release notes, and, where it can tell how the program was
  installed, the command that updates it (`brew upgrade teetime-monitor`, `scoop update ...`).
  `TEETIME_MONITOR_NO_UPDATE_CHECK=1` switches the check off.
- **The update button (a Pi server only).** When the program runs as `--serve` under systemd out of the
  installer's own Python environment, a logged-in page can install the newest release into that
  environment and let the service restart (exit code 75, which the unit restarts). The server installs
  only the release it found itself, from github.com/<repo> at that tag -- never anything the page sends.
  Portable downloads and the Mac app are not touched: replacing files that are running is not safe, so
  they stay a manual download.
- **Automatic updates (a Pi server, opt-in, 2026-10-18).** With `AUTO_UPDATE=1` in the config file (the switch in
  Settings > About), the same install runs by itself at night (`NIGHT`), when nothing was done on the page for a
  while and no club is being fetched. What it did is kept in `MARKER_FILE` for the page to tell the next morning;
  a release that failed is not tried again by itself.
- **Every install checks itself first.** After pip, the new version starts once on a spare local port
  (`--self-test`); if that fails, the previous version is installed back and nothing restarts.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from .. import clock, paths, user_config
from . import data

REPO = "ltdan-88/teetime-monitor"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY_SECONDS = 6 * 3600
STALE_AFTER_SECONDS = 900  # a page that asks while the last look is older than this makes the server look again
FIRST_CHECK_AFTER_SECONDS = 60
RESTART_EXIT_CODE = 75  # EX_TEMPFAIL: a "failure" to systemd's Restart=on-failure, so it starts the new version
TAG = re.compile(r"^v\d{1,4}\.\d{1,4}\.\d{1,4}$")
SERVER_DIR_NAME = "teetime-monitor-server"  # install.sh puts the environment in ~/.local/share/<this>/venv

_lock = threading.Lock()
_latest: dict | None = None  # {tag, url, checked_at}
_last_attempt = 0.0  # when the last look started, whether or not it worked
_looking = False
_install = {"state": "idle", "error": None}  # idle | running | restarting | failed

AUTO_KEY = "AUTO_UPDATE"  # in the config file: "1" installs updates at night by itself
NIGHT = ("03:00", "05:00")  # the local hours an automatic update may run in
QUIET_SECONDS = 10 * 60  # nothing done on the page (a booking, a save) for this long
WAKE_SECONDS = 10 * 60  # how often the watcher wakes to see whether it is time
MARKER_FILE = "auto_update.json"  # in the data folder: {"from", "to", "ok", "at"} of the last automatic update
MARKER_DAYS = 3  # the page tells about it for this long, unless it is dismissed
SELF_TEST_SECONDS = 120


def _numbers(version: str) -> tuple[int, ...] | None:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", version or "")
    return tuple(int(part) for part in match.groups()) if match else None


def is_newer(latest: str, current: str) -> bool:
    a, b = _numbers(latest), _numbers(current)
    return a is not None and b is not None and a > b


def disabled() -> bool:
    return bool(os.environ.get("TEETIME_MONITOR_NO_UPDATE_CHECK"))


def check_now() -> dict | None:
    """Ask GitHub for the newest release and remember it; None (and the old answer kept) if it cannot be reached."""
    global _latest
    if disabled():
        return None
    try:
        response = httpx.get(
            LATEST_URL,
            timeout=8,
            follow_redirects=True,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "teetime-monitor"},
        )
        response.raise_for_status()
        release = response.json()
        tag = str(release["tag_name"])
        url = str(release.get("html_url") or f"https://github.com/{REPO}/releases/tag/{tag}")
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    if not TAG.match(tag):
        return None
    with _lock:
        _latest = {"tag": tag, "url": url, "checked_at": time.time()}
        return dict(_latest)


def refresh_if_stale(now: float | None = None) -> bool:
    """Called when a page asks for the status: if the last look is more than 15 minutes old (the server may have
    been running for days since it last looked), look again in the background -- the page gets the newer
    answer on its next visit. True if a look was started."""
    global _last_attempt, _looking
    moment = time.time() if now is None else now
    if disabled():
        return False
    with _lock:
        if _looking or moment - _last_attempt < STALE_AFTER_SECONDS:
            return False
        _looking, _last_attempt = True, moment

    def look():
        global _looking
        try:
            check_now()
        finally:
            with _lock:
                _looking = False

    threading.Thread(target=look, daemon=True, name="update-check-now").start()
    return True


def watch(server=None) -> None:
    """Background thread: the first look a minute after start-up, then every few hours; in between it wakes
    now and then to see whether an automatic update is due."""
    global _last_attempt
    time.sleep(FIRST_CHECK_AFTER_SECONDS)
    while True:
        with _lock:
            due = time.time() - _last_attempt >= CHECK_EVERY_SECONDS
            if due:
                _last_attempt = time.time()
        if due:
            check_now()
        if server is not None and auto_due(server):
            apply(True, server.restart, auto=True)
        time.sleep(WAKE_SECONDS)


# ---- automatic updates (a Pi server) ----------------------------------------------------------------------


def auto_enabled() -> bool:
    return user_config.load_value(AUTO_KEY, user_config.CONFIG_FILE) == "1"


def set_auto(on: bool) -> dict:
    user_config.save_value(AUTO_KEY, "1" if on else "0", user_config.CONFIG_FILE)
    return {"ok": True, "auto": on}


def _marker_path() -> Path:
    return paths.DATA_DIR / MARKER_FILE


def _read_marker() -> dict | None:
    try:
        marker = json.loads(_marker_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return marker if isinstance(marker, dict) else None


def _write_marker(marker: dict) -> None:
    try:
        _marker_path().parent.mkdir(parents=True, exist_ok=True)
        _marker_path().write_text(json.dumps(marker), encoding="utf-8")
    except OSError:
        pass  # only the morning note is lost


def auto_result() -> dict | None:
    """The last automatic update, for the page to tell about: {"from", "to", "ok"}; None once it is old or seen."""
    marker = _read_marker()
    if not marker or marker.get("seen") or time.time() - float(marker.get("at") or 0) > MARKER_DAYS * 86400:
        return None
    return {"from": marker.get("from"), "to": marker.get("to"), "ok": bool(marker.get("ok"))}


def auto_seen() -> dict:
    marker = _read_marker()
    if marker:
        _write_marker({**marker, "seen": True})  # kept, so a failed release is still not tried again
    return {"ok": True}


def auto_due(server, now_hhmm: str | None = None) -> bool:
    """Time for an automatic update: switched on, a Pi server, at night, a newer release that has not failed
    here before, nothing installing, nothing fetching, and nothing done on the page for a while."""
    if not auto_enabled() or not getattr(server, "serve", False) or install_kind() != "pi":
        return False
    moment = now_hhmm or clock.now_hhmm()
    if not (NIGHT[0] <= moment < NIGHT[1]):
        return False
    if server.quiet_for() < QUIET_SECONDS or server.refresher.busy():
        return False
    with _lock:
        latest = dict(_latest) if _latest else None
        state = _install["state"]
    if not latest or state in ("running", "restarting") or not is_newer(latest["tag"], data.version()):
        return False
    marker = _read_marker() or {}
    return not (marker.get("ok") is False and marker.get("to") == latest["tag"].lstrip("v"))


# ---- how this copy was installed -------------------------------------------------------------------------


def install_kind() -> str:
    """'pi' (the installer's environment, running under systemd), 'brew', 'scoop' or 'other'."""
    prefix = Path(sys.prefix)
    text = str(prefix).lower().replace("\\", "/")
    if prefix.parent.name == SERVER_DIR_NAME and "INVOCATION_ID" in os.environ:
        return "pi"
    if "/cellar/" in text or "/homebrew/" in text:
        return "brew"
    if "/scoop/" in text:
        return "scoop"
    return "other"


COMMANDS = {"brew": "brew upgrade teetime-monitor", "scoop": "scoop update teetime-monitor"}


def status(serving: bool = False) -> dict:
    """What the page shows: the installed version, the newest known one, and what can be done about it."""
    current = data.version()
    with _lock:
        latest = dict(_latest) if _latest else None
        running = dict(_install)
    kind = install_kind()
    newer = bool(latest) and is_newer(latest["tag"], current)
    return {
        "current": current,
        "latest": latest["tag"].lstrip("v") if latest else None,
        "newer": newer,
        "url": latest["url"] if latest else None,
        "checked_at": latest["checked_at"] if latest else None,
        "command": COMMANDS.get(kind),
        "can_update": newer and kind == "pi" and serving,
        "check_disabled": disabled(),
        "install": running,
        "auto_available": kind == "pi" and serving,
        "auto": auto_enabled(),
        "auto_result": auto_result() if kind == "pi" and serving else None,
    }


# ---- installing it (a Pi server) -------------------------------------------------------------------------


def apply(serving: bool, on_installed, auto: bool = False) -> dict:
    """Install the newest known release into this environment, then call `on_installed()` (which restarts
    the server). Returns the install state at once; the work runs in a thread. `{"error": ...}` when it
    must not be done."""
    with _lock:
        if _install["state"] in ("running", "restarting"):
            return {"state": _install["state"], "error": None}
        latest = dict(_latest) if _latest else None
    info = status(serving)
    if not (latest and TAG.match(latest["tag"])) or not info["newer"]:
        return {"error": "nothing_to_install"}
    if not info["can_update"]:
        return {"error": "not_supported"}
    with _lock:
        _install.update(state="running", error=None)
    threading.Thread(target=_run_install, args=(latest["tag"], on_installed, auto), daemon=True, name="update").start()
    return {"state": "running", "error": None}


def source_for(tag: str) -> str:
    """Where pip gets a release: GitHub's archive of that tag (a test points this at a local build)."""
    return f"https://github.com/{REPO}/archive/refs/tags/{tag}.tar.gz"


def _last_line(text: str, fallback: str) -> str:
    lines = (text or "").strip().splitlines()
    return (lines[-1] if lines else fallback)[:300]


def _pip_install(tag: str) -> str | None:
    """Install `tag` into this environment; None when it worked, else what went wrong."""
    command = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade", source_for(tag)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)[:300]
    return None if result.returncode == 0 else _last_line(result.stderr or result.stdout, "pip failed")


def _self_test(tag: str) -> str | None:
    """Start the version just installed once (`--self-test`, a fresh process, `-I` so no folder can shadow the
    installed one); None when it came up as that version, else what went wrong."""
    command = [sys.executable, "-I", "-m", "src.webui.server", "--self-test"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=SELF_TEST_SECONDS)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as error:
        return f"self-test: {str(error)[:280]}"
    expected = f"ok {tag.lstrip('v')}"
    if result.returncode != 0 or expected not in result.stdout:
        return "self-test: " + _last_line(result.stderr or result.stdout, f"exit code {result.returncode}")
    return None


def _run_install(tag: str, on_installed, auto: bool = False) -> None:
    previous = data.version()
    failure = _pip_install(tag)
    if failure is None:
        failure = _self_test(tag)
        if failure is not None:  # the new version does not start: put the one that ran back
            back = _pip_install(f"v{previous}")
            failure += f" (v{previous} restored)" if back is None else f" (restoring v{previous} failed too: {back})"
    if auto:  # first, so whoever sees the outcome below also finds the note about it
        _write_marker({"from": previous, "to": tag.lstrip("v"), "ok": failure is None, "at": time.time()})
    with _lock:
        _install.update(state="failed" if failure else "restarting", error=failure)
    if not failure:
        time.sleep(2)  # let the page see "restarting" first
        on_installed()


def reset_for_tests() -> None:
    global _latest, _last_attempt, _looking
    with _lock:
        _latest = None
        _last_attempt = 0.0
        _looking = False
        _install.update(state="idle", error=None)
