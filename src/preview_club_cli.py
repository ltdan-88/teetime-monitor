"""Headless "browse before saving" preview -- closes the one Tier 2 gap the Swift
prototype's own README explicitly flagged as still open after its 2026-09-19/20
feedback round ("the third gap found -- browsing a club's schedule before saving
it, the way `ClubBrowserScreen` can -- is still open; adding a club still means
favoriting it first").

`ClubBrowserScreen`/`TeetimeApp._open_club()` in tui.py can take *any* club id
straight to a real, live-scraped multi-day overview with no `clubs/*.yaml` ever
written -- picking a club there is a completed action with something to look at,
not a prerequisite gate behind favoriting first (see that function's own
docstring: "a club reached from the directory usually has no saved file at all,
and that's a normal state"). This wraps that same unsaved-club path as a console
script, reusing it directly rather than re-deriving it:

- `tui._resolved_config(club_slug=None, club_id, club_name)` -- the exact call
  `_open_club()` itself makes for a club with no saved YAML, which still merges
  in your global availability/preferences and best-effort geocodes a location
  for weather (see that function's own docstring on why `club_id`/`club_name`
  exist at all).
- `scrape_once.scrape_due_for_club(slug=None, config, force=True)` -- the exact
  call `TeetimeApp._periodic_scrape()` makes for the session's active club
  regardless of favorite status. `slug=None` is already a handled, ordinary
  case throughout that function's own callees (`_sync_my_reservations()`'s
  first line is `if not slug: return` -- "My Reservations" needs credentials
  keyed by slug, and an unsaved club living only in-session never has any),
  not a special case invented here.

Scrapes straight into `<club_id>.db` -- the same fixed-name database
`Store.days()`/`Store.courses()` (the Swift app's own generic, club-agnostic
readers) already read for *any* club file that exists on disk, favorited or
not. That's the whole reason this script's contract is this thin: it has no
course/date/results shape of its own to return at all, unlike `search_cli.py` --
its only job is making sure something real ends up in that database, so the
Swift app can then just point its existing day-list view at it, exactly as it
already does for a saved club.

Course discovery (`fetch_course_aliases()`) is called once here, before the
scrape, purely to distinguish a real "this club has no tee sheet" fact (a
message worth showing) from a genuine scrape failure -- `scrape_due_for_club()`
would otherwise swallow that same exception into a one-line console `print()`
nothing sees while shelled out from a GUI, and report `{"ok": True}` regardless
(it doesn't raise). That means this club's course list gets fetched live twice
per preview (again inside `scrape_due_for_club()` itself) -- the same double
fetch `_open_club()` + `_periodic_scrape()` already do in the TUI for the exact
same reason, not a new inefficiency introduced here.

Result is one JSON object on stdout:

    {"ok": true}
    {"ok": false, "reason": "missing_club_id"}
    {"ok": false, "reason": "no_tee_sheet"}
    {"ok": false, "reason": "course_fetch_failed", "error": "..."}

Exit code 0 only for `{"ok": true}`; 1 for every rejection above -- same
"saved/scraped is what decides success" shape `add_club_cli.py`/`search_cli.py`
already use. `{"ok": true}` doesn't promise any *slots* were found (a course
fully booked, or a window pc caddie itself rejects, is still a successful
scrape of zero open spots) -- same "a script's job is running cleanly, not
guaranteeing a particular result" distinction those two make.
"""

import json
import sys

from . import scrape_once
from . import tui as tui_module
from .scraper import NoTeeSheetError, fetch_course_aliases


def _flag(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    idx = argv.index(name)
    return argv[idx + 1] if idx + 1 < len(argv) else None


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    club_id = _flag(argv, "--club-id")
    club_name = _flag(argv, "--club-name") or ""

    if not club_id:
        print(json.dumps({"ok": False, "reason": "missing_club_id"}))
        sys.exit(1)

    try:
        fetch_course_aliases(club_id)
    except NoTeeSheetError:
        print(json.dumps({"ok": False, "reason": "no_tee_sheet"}))
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 -- a live fetch can genuinely fail
        print(json.dumps({"ok": False, "reason": "course_fetch_failed", "error": str(exc)}))
        sys.exit(1)

    config = {**tui_module._resolved_config(None, club_id, club_name), "club_id": club_id}
    scrape_once.scrape_due_for_club(None, config, force=True)
    print(json.dumps({"ok": True}))


if __name__ == "__main__":
    main()
