"""Headless platform-directory refresh — Tier 2 for the Swift prototype's
add-a-club (2026-09-18).

`ClubBrowserScreen.action_refresh_directory()` (see its own docstring in tui.py) is
the TUI's `r`-to-refresh: re-fetch pc caddie's full club list and cache it, the one
directory action that genuinely needs a login (an authenticated page, see
`club_directory.py`'s own module docstring on why the directory itself isn't
public). This is that same fetch-and-cache call, exposed as
`teetime-monitor-directory-refresh` so the Swift app can shell out to it instead of
reimplementing an authenticated pc caddie request itself.

**Everything else about the directory stays Tier 1, not here.** Searching it
(`club_directory.search()`, a plain case-insensitive substring match) and reading
the cache/seed files it produces (`club-directory.json` under
`~/.local/share/teetime-monitor/`, and the bundled `club_directory_seed.json`
snapshot) are simple enough, and simple enough to verify byte-for-byte, that the
Swift app reads/matches them directly — see `ClubDirectoryStore.swift`. Only the
*live, authenticated fetch* is real enough (network, credential resolution, HTML
parsing) to stay a Python-owned action.

Credentials are never passed in directly — resolved the exact same way
`action_refresh_directory()` does, via `club_directory.any_credentials()` first
(whichever saved favorite has working credentials paired with it), falling back to
`--club-id` (a specific id to authenticate against, e.g. one just typed into the
Swift app's own search box) plus whatever `.env` already has, only if
`any_credentials()` finds nothing to pair with. No stdin payload at all — there's
nothing here a user types that needs to stay off argv/env (contrast
`login_cli.py`, which handles a real password).

Result is one JSON object on stdout:

    {"ok": true, "count": 1300}
    {"ok": false, "reason": "needs_login"}
    {"ok": false, "reason": "needs_a_club"}
    {"ok": false, "reason": "fetch_failed", "error": "..."}

Exit code 0 only when the fetch actually succeeded; 1 for every `ok: false` case —
unlike `login_cli.py`/`search_cli.py`, there's no "ran but found nothing" middle
ground here, a refresh either updated the cache or it didn't.
"""

import json
import sys

from . import club_config, club_directory


def _flag(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    idx = argv.index(name)
    return argv[idx + 1] if idx + 1 < len(argv) else None


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    fallback_club_id = _flag(argv, "--club-id")

    credentials = club_directory.any_credentials()
    if credentials is not None:
        club_id, username, password = credentials
    elif fallback_club_id and club_directory.credentials_configured():
        club_id = fallback_club_id
        username, password = club_config.resolve_credentials(fallback_club_id)
    else:
        club_id = username = password = None

    if not club_id or not username or not password:
        reason = "needs_a_club" if club_directory.credentials_configured() else "needs_login"
        print(json.dumps({"ok": False, "reason": reason}))
        sys.exit(1)

    try:
        entries = club_directory.refresh_directory(club_id, username, password)
    except Exception as exc:  # noqa: BLE001 -- a live fetch can genuinely fail
        # (network, pc caddie down, an unexpected page shape) -- same broad catch
        # action_refresh_directory() itself uses, for the same reason.
        print(json.dumps({"ok": False, "reason": "fetch_failed", "error": str(exc)}))
        sys.exit(1)

    print(json.dumps({"ok": True, "count": len(entries)}))


if __name__ == "__main__":
    main()
