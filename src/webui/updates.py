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
"""

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

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
    """Background thread: the first look a minute after start-up, then every few hours."""
    global _last_attempt
    time.sleep(FIRST_CHECK_AFTER_SECONDS)
    while True:
        with _lock:
            _last_attempt = time.time()
        check_now()
        time.sleep(CHECK_EVERY_SECONDS)


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
    }


# ---- installing it (a Pi server) -------------------------------------------------------------------------


def apply(serving: bool, on_installed) -> dict:
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
    threading.Thread(target=_run_install, args=(latest["tag"], on_installed), daemon=True, name="update").start()
    return {"state": "running", "error": None}


def _run_install(tag: str, on_installed) -> None:
    source = f"https://github.com/{REPO}/archive/refs/tags/{tag}.tar.gz"
    command = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade", source]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800)  # noqa: S603
        failure = None if result.returncode == 0 else (result.stderr or result.stdout or "pip failed").strip().splitlines()[-1][:300]
    except (OSError, subprocess.SubprocessError) as error:
        failure = str(error)[:300]
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
