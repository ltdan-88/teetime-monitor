"""The web server's password (2026-10-11), for `teetime-monitor-web --serve`.

Running on your own computer, the web UI trusts whoever holds the random link it prints (see
server.py). Running as a server on the home network (a Raspberry Pi), anyone on the Wi-Fi can reach it,
and what sits behind it -- your pc caddie login, the AI key, your bookings -- needs a real password.

- One password for the whole server, set with `teetime-monitor-web --set-password` and stored as a
  salted PBKDF2-SHA256 hash (600 000 rounds) in `web_auth.json` next to your other settings, readable
  by you only. The password itself is never stored.
- A login hands out a signed cookie (HMAC-SHA256 over an expiry date, with a random secret kept in the
  same file). Nothing about sessions is kept in memory, so a restart does not log anyone out, and
  setting a new password replaces the secret and logs everyone out at once.
- Wrong passwords are slowed down per address: five misses lock that address out for 30 s, doubling
  with every further miss up to 15 minutes.

This is plain HTTP on your own network. Anyone who can watch the Wi-Fi traffic could read the password;
for use away from home put the server behind a VPN (Tailscale, WireGuard) rather than opening a port.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

from .. import paths

AUTH_FILE = paths.CONFIG_DIR / "web_auth.json"
PBKDF2_ROUNDS = 600_000
MIN_PASSWORD_LENGTH = 8
SESSION_SECONDS = 30 * 24 * 3600
FREE_MISSES = 5
LOCK_BASE_SECONDS = 30
LOCK_MAX_SECONDS = 15 * 60


def _file(path: Path | None) -> Path:
    return path if path is not None else AUTH_FILE


def _load(path: Path | None) -> dict | None:
    try:
        loaded = json.loads(_file(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    needed = ("salt", "hash", "rounds", "secret")
    return loaded if isinstance(loaded, dict) and all(key in loaded for key in needed) else None


def _hash(password: str, salt: bytes, rounds: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)


def is_configured(path: Path | None = None) -> bool:
    return _load(path) is not None


def set_password(password: str, path: Path | None = None) -> None:
    """Store `password` (replacing any earlier one, and every session with it). ValueError if it is too short."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"The password needs at least {MIN_PASSWORD_LENGTH} characters.")
    salt = secrets.token_bytes(16)
    record = {
        "salt": base64.b64encode(salt).decode(),
        "hash": base64.b64encode(_hash(password, salt, PBKDF2_ROUNDS)).decode(),
        "rounds": PBKDF2_ROUNDS,
        "secret": base64.b64encode(secrets.token_bytes(32)).decode(),
    }
    target = _file(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    # Created owner-only from the start, so the hash is never readable by anyone else, not even briefly.
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(record, handle)
    os.replace(temporary, target)


def check_password(password: str, path: Path | None = None) -> bool:
    record = _load(path)
    if record is None or not isinstance(password, str) or len(password) > 1024:
        return False
    try:
        salt = base64.b64decode(record["salt"])
        expected = base64.b64decode(record["hash"])
        rounds = int(record["rounds"])
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(_hash(password, salt, rounds), expected)


def _sign(secret: bytes, text: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(secret, text.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def make_session(path: Path | None = None, now: float | None = None) -> str | None:
    """A signed cookie value valid for 30 days; None when no password is set."""
    record = _load(path)
    if record is None:
        return None
    expires = int((time.time() if now is None else now) + SESSION_SECONDS)
    text = f"v1.{expires}"
    return f"{text}.{_sign(base64.b64decode(record['secret']), text)}"


def valid_session(value: str, path: Path | None = None, now: float | None = None) -> bool:
    record = _load(path)
    parts = value.split(".") if isinstance(value, str) else []
    if record is None or len(parts) != 3 or parts[0] != "v1" or not parts[1].isdigit():
        return False
    text = f"v1.{parts[1]}"
    if not hmac.compare_digest(_sign(base64.b64decode(record["secret"]), text), parts[2]):
        return False
    return int(parts[1]) > (time.time() if now is None else now)


class LoginThrottle:
    """Slows down password guessing, per client address (kept in memory; a restart clears it)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, tuple[int, float]] = {}  # address -> (misses, locked until)

    def retry_after(self, address: str, now: float | None = None) -> int:
        """Seconds until `address` may try again; 0 when it may try now."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            _, locked_until = self._state.get(address, (0, 0.0))
        return max(0, int(locked_until - moment + 0.999))

    def miss(self, address: str, now: float | None = None) -> None:
        moment = time.monotonic() if now is None else now
        with self._lock:
            misses, _ = self._state.get(address, (0, 0.0))
            misses += 1
            lock = 0
            if misses >= FREE_MISSES:
                lock = min(LOCK_BASE_SECONDS * 2 ** (misses - FREE_MISSES), LOCK_MAX_SECONDS)
            self._state[address] = (misses, moment + lock)

    def success(self, address: str) -> None:
        with self._lock:
            self._state.pop(address, None)
