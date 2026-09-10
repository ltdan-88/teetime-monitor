"""A locally cached copy of pc caddie's full club directory, so the TUI can open
straight into "pick a club" instead of requiring clubs to be saved to config first.

Direct feedback (2026-09-07): saving a club to `clubs/*.yaml` before you can look at it
is backwards — launching the app should just let you pick a club and a course, and
saving one should mean "favorite", nothing more. That reframing is what this module
exists for.

The awkward constraint it works around: the directory itself is **not public**.
`scraper.fetch_club_directory()` reads it out of one authenticated page's embedded
`<select>` (confirmed 2026-09-07 — a plain GET of that page while logged out returns
HTTP 401), while the tee sheets it points at need no login at all. So a live per-launch
fetch would put a login in front of the one flow that shouldn't need one. Instead the
directory is fetched once, cached here as plain JSON, and reused on every later launch —
1300+ clubs, a list that changes on the order of months, not minutes.

That leaves four ways to reach a club, deliberately, so a missing cache or missing
credentials never becomes a dead end:

1. **Favorites** — any club saved under `clubs/*.yaml`. Always available, no directory
   and no login involved. This is what the old "saved clubs" list becomes.
2. **Search the cached directory** — the full platform, once it's been fetched.
3. **A club id typed directly** — `looks_like_club_id()` below. Needs neither the cache
   nor credentials, because a tee sheet is public: given the id, everything works.
4. **Search a bundled seed directory** — `load_seed_directory()` below, added
   2026-09-10, direct pushback ("a First time User would not know anything about a
   club id"): the login-gated live directory (#2) and a typed/pasted id (#3) both
   still assume you already have *something* — either a login, or a specific club
   already in mind. A genuinely first-time user, with neither, previously had no way
   to search by name at all before this. `club_directory_seed.json` (shipped in
   `src/`, not gitignored the way the live cache under `data/` is) is a one-time,
   real fetch of the whole platform directory (~1300 clubs, names + ids only — the
   same non-sensitive listing any logged-in user already sees via #2) bundled with
   the app itself, so name search works immediately on a brand-new install with zero
   setup. Used only as a fallback when the real cache (#2) has nothing yet — the
   moment a real login exists and `r` is pressed, the live fetch replaces it and
   this bundled data is never consulted again for that install. Necessarily goes
   stale over time (the live directory "changes on the order of months, not
   minutes," same as #2's own note above) but a stale-but-searchable directory beats
   none at all for a first search, the same reasoning behind every other fallback in
   this list.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import club_config
from .scraper import fetch_club_directory

DATA_DIR = Path("data")
CACHE_FILENAME = "club-directory.json"

# Bundled with the app itself (see module docstring's "#4" note) -- not under
# DATA_DIR, deliberately: that whole directory is gitignored (it's per-install
# runtime state), while this ships as part of the source tree, the same way
# clubs/club.example.yaml is a tracked reference file sitting next to the
# gitignored clubs/*.yaml it's a template for.
SEED_FILE = Path(__file__).parent / "club_directory_seed.json"

# pc caddie club ids are a 7-digit zero-padded number — "0" + the country's calling
# code + a per-club number (049… = Germany, 041… = Switzerland, 0352… = Luxembourg),
# confirmed 2026-09-07 across a spread of real clubs. Accepted with or without the
# leading zero, since that's an easy thing to drop when typing one in by hand.
_CLUB_ID_RE = re.compile(r"^\d{6,7}$")

# Direct pushback, 2026-09-10: "a First time User would not know anything about a
# club id" -- correct, and genuinely not solvable by anything in this app's own
# code: pc caddie's platform directory itself isn't publicly searchable (see this
# module's own docstring -- a logged-out GET of it returns HTTP 401), so finding an
# unknown club by name has to start from *some* real, known club id regardless. What
# a first-time user actually has, in practice, is their own club's own pc caddie
# booking link -- bookmarked, emailed as a confirmation, or linked straight from the
# club's own website's "book a tee time" button -- not a bare 7-digit number
# memorized on its own. Recognizing that link directly (rather than requiring it to
# be manually trimmed down to just the digits first) is the actual fix: any
# `/clubs/<id>/...` segment pulled out of a pasted URL, wherever it appears in the
# string, same digit-count rule as a bare id above.
_CLUB_ID_IN_URL_RE = re.compile(r"/clubs/(\d{6,7})(?:/|$|\?)")


def _cache_path(path: Path | None = None) -> Path:
    """Resolved at call time, not bound as a default argument — see env_file.py's
    module docstring for the frozen-default gotcha this avoids (a test monkeypatching
    `DATA_DIR` must actually be honored)."""
    return path if path is not None else DATA_DIR / CACHE_FILENAME


def looks_like_club_id(query: str) -> str | None:
    """The normalized club id if `query` is one, else None.

    Lets the club picker accept "000001" or "0000001" as a direct jump, no directory
    lookup and no login needed — the tee sheet for any id is public. Also accepts a
    pasted pc caddie URL containing a `/clubs/<id>/` segment (2026-09-10 — see
    `_CLUB_ID_IN_URL_RE`'s own comment above for why: a real first-time user's actual
    starting point is a club's own booking link, not a bare number)."""
    candidate = query.strip()
    if _CLUB_ID_RE.match(candidate):
        return candidate.zfill(7)
    url_match = _CLUB_ID_IN_URL_RE.search(candidate)
    if url_match:
        return url_match.group(1).zfill(7)
    return None


def load_cached_directory(path: Path | None = None) -> list[tuple[str, str]]:
    """The cached (club_id, name) pairs, or [] if there's no usable cache yet.

    Deliberately forgiving: a missing, empty, or corrupt cache file is an ordinary
    "you haven't fetched it yet" state that the picker handles by falling back to
    favorites and direct club ids, not an error worth crashing a launch over."""
    cache = _cache_path(path)
    if not cache.exists():
        return []
    try:
        with cache.open() as f:
            payload = json.load(f)
        return [(str(club_id), str(name)) for club_id, name in payload.get("clubs", [])]
    except (json.JSONDecodeError, ValueError, TypeError, OSError):
        return []


def load_seed_directory(path: Path | None = None) -> list[tuple[str, str]]:
    """The bundled reference snapshot (see module docstring's "#4" note), or [] if it's
    somehow missing from this install. `ClubBrowserScreen` only ever calls this when
    `load_cached_directory()` already came back empty — a real live fetch always wins
    once one exists, so this is purely a first-run fallback, never a competing source
    of truth. Same forgiving shape as `load_cached_directory()` for the same reason:
    a missing/corrupt bundled file should degrade to "no seed data" quietly, not crash
    a launch."""
    seed = path if path is not None else SEED_FILE
    if not seed.exists():
        return []
    try:
        with seed.open() as f:
            payload = json.load(f)
        return [(str(club_id), str(name)) for club_id, name in payload.get("clubs", [])]
    except (json.JSONDecodeError, ValueError, TypeError, OSError):
        return []


def cached_at(path: Path | None = None) -> str | None:
    """When the cache was last written (ISO 8601), or None if there's no usable cache.
    Shown in the picker so a stale directory is visible rather than silently assumed
    current."""
    cache = _cache_path(path)
    if not cache.exists():
        return None
    try:
        with cache.open() as f:
            return json.load(f).get("fetched_at")
    except (json.JSONDecodeError, ValueError, TypeError, OSError):
        return None


def save_directory(entries: list[tuple[str, str]], path: Path | None = None) -> None:
    """Write the directory cache, creating `data/` if this is the very first run —
    same reason `storage.init_db()` creates its own parent directory (found the hard
    way 2026-09-07, when a first-ever launch crashed on a missing `data/`)."""
    cache = _cache_path(path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "clubs": [list(entry) for entry in entries],
    }
    with cache.open("w") as f:
        json.dump(payload, f, ensure_ascii=False)


def refresh_directory(
    club_id: str, username: str, password: str, path: Path | None = None
) -> list[tuple[str, str]]:
    """Fetch the live directory and cache it. Needs a login (see module docstring);
    `club_id` only has to be *a* club that account can log into, since one pc caddie
    login works platform-wide."""
    entries = fetch_club_directory(club_id, username, password)
    save_directory(entries, path)
    return entries


def any_credentials() -> tuple[str, str, str] | None:
    """(club_id, username, password) usable for a directory refresh, or None.

    Tries each saved favorite in turn: credentials are normally the plain
    PCC_USER/PCC_PASS pair shared across clubs, but `resolve_credentials()` also
    supports per-club overrides, so the club whose id is used has to be one whose
    credentials actually resolved.

    This needs a real, favorited club_id to pair the credentials with — an
    authenticated request has to be made *against* some specific club's login page
    — so it returns None on a brand-new install with zero favorited clubs even
    once real, working credentials are saved in `.env`. See `credentials_configured()`
    below for the check that doesn't have this dependency."""
    for slug in club_config.list_clubs():
        config = club_config.load_club_config(slug)
        club_id = config.get("club_id")
        if not club_id:
            continue
        username, password = club_config.resolve_credentials(slug)
        if username and password:
            return str(club_id), username, password
    return None


def credentials_configured() -> bool:
    """Whether PCC_USER/PCC_PASS are set at all, independent of any favorited club.

    Found live, 2026-09-10, direct report ("why can't I login... why do I need to
    hit r after login... how do I know if login is successful"): `TeetimeApp`'s own
    "show the credentials screen first at launch" check used `any_credentials()` is
    None for this — but `any_credentials()` also requires an existing favorited club
    to pair the credentials with, which a genuinely fresh install (the exact case
    that check exists for) never has yet. The result: real, correctly-saved,
    already-verified-working credentials in `.env` were never recognized as
    "configured" until a club was separately favorited (a distinct, later step) —
    from the outside this looks exactly like login never actually worked, since
    every screen that checked `any_credentials()` kept reporting "needs a login" no
    matter how many times the credentials screen was filled in. This check only
    looks at whether the plain env vars are set, with no club dependency at all."""
    return bool(os.environ.get("PCC_USER")) and bool(os.environ.get("PCC_PASS"))


def search(directory: list[tuple[str, str]], query: str, limit: int = 50) -> list[tuple[str, str]]:
    """Case-insensitive substring match on the club name — a friendlier choice than
    pc caddie's own exact/umlaut-sensitive matching. A blank query returns nothing
    (`tui.py`'s `ClubBrowserScreen` shows favorites instead in that case)."""
    needle = query.strip().lower()
    if not needle:
        return []
    return [entry for entry in directory if needle in entry[1].lower()][:limit]
