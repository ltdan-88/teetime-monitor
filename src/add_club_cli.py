"""Headless add-a-club — the other Tier 2 half of the Swift prototype's add-a-club
(2026-09-18), alongside `directory_cli.py`'s directory refresh.

Wraps `club_config.add_favorite()` directly: derives a slug, skips the write
entirely if this club_id is already saved (idempotent — see that function's own
docstring on the duplicate-file bug this guards against), and does a best-effort
geocoding lookup (`geocode.find_club_location()`, a public Nominatim search, no
login involved, never raises) so a club added from the Swift app gets weather the
same way one added through the TUI does — skipping that lookup here would leave a
Swift-added club silently missing forecasts until someone re-saves it from Python.

No stdin payload — `--club-id` and `--name` are both plain, non-secret values, so
this reads them as flags like `search_cli.py`'s own `--course`, not over stdin like
`login_cli.py`'s real credentials.

Result is one JSON object on stdout:

    {"ok": true, "slug": "golfclub-foo"}
    {"ok": false, "reason": "missing_club_id"}

Exit code 0 whenever a club_id was actually given (this always succeeds from there —
`add_favorite()` itself never raises); 1 only for the one missing-input case.
"""

import json
import sys

from . import club_config


def _flag(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    idx = argv.index(name)
    return argv[idx + 1] if idx + 1 < len(argv) else None


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    club_id = _flag(argv, "--club-id")
    name = _flag(argv, "--name") or ""

    if not club_id:
        print(json.dumps({"ok": False, "reason": "missing_club_id"}))
        sys.exit(1)

    slug = club_config.add_favorite(club_id, name)
    print(json.dumps({"ok": True, "slug": slug}))


if __name__ == "__main__":
    main()
