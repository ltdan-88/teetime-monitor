"""Headless per-day recommended pick — the GUI's Overview counterpart to
`search_cli.py`'s ad hoc search (2026-09-27).

Direct follow-up: the TUI's Overview has shown a "★ HH:MM" recommended pick per
day (best still-playable slot, AI-ranked with `reasons` once `ai_assist.enabled`)
since 2026-09-08 (`tui.py`'s `_day_pick_text()`/`_availability_pipeline()`), but
the GUI's Overview never had an equivalent — surfaced once AI ranking actually
started working end to end and there was still nothing to see in the Overview
itself (only the ad hoc Search sheet, which already goes through
`recommend.ranked_matches()` via `search_cli.py`).

Reuses `tui._availability_pipeline()` directly, the exact function
`_day_pick_text()` itself calls, rather than reimplementing the selection --
this can never drift from what the TUI would show for the same data. `--db-path`/
`--club-slug`/`--course`/`--from`/`--days` are the same flags `search_cli.py`
already takes, same reasoning: `_resolved_config()` builds the identical merged
config either script would use for this club.

Result is one JSON object on stdout keyed by date, not a translated string or an
array -- an O(1) lookup for the GUI, no client-side searching:

    {"2026-09-27": {"time": "09:10", "score": 85.0, "reasons": ["dry", "calm"]},
     "2026-09-28": null}

`null` covers every "nothing to show" case `_day_pick_text()` also collapses to
a plain dash for (no `availability` rules configured yet, no schedule scraped
for that date, or genuinely nothing playable) -- the GUI only needs to know
whether there's a pick to render, not which of those three reasons applies, so
this stays a flat map rather than replicating the TUI's three distinct
"no dry picks"/"too dark to finish"/generic messages. `reasons` is `[]`
whenever `ai_assist.enabled` is off, same as the TUI's own Pick column.

Exit code 0 whenever the script actually ran, even if every date came back
`null` (that's a normal, valid result, not an error) -- exit code 1 only for a
setup problem (bad stdin, or `--db-path`/`--club-slug` that doesn't resolve),
same "saved/ran is what decides success" shape `login_cli.py`/`search_cli.py`
already use. Takes no stdin at all -- unlike `search_cli.py`'s ad hoc criteria,
this always uses your own saved defaults (`recommend.default_criteria_from_config()`),
the same rules `_availability_pipeline()` itself checks against.
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from . import storage
from . import tui as tui_module


def _flag(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    idx = argv.index(name)
    return argv[idx + 1] if idx + 1 < len(argv) else None


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    db_path = _flag(argv, "--db-path")
    course = _flag(argv, "--course")
    club_slug = _flag(argv, "--club-slug")
    from_date = _flag(argv, "--from") or date.today().isoformat()
    days = int(_flag(argv, "--days") or "6")

    if not db_path or not course:
        print(json.dumps({"error": "missing --db-path or --course"}))
        sys.exit(1)

    club_id = Path(db_path).stem
    config = tui_module._resolved_config(club_slug)
    # Checked once, up front, rather than per date: a config with no `availability`
    # block at all short-circuits every date to `None` immediately, same as
    # _day_pick_text()'s own early return, without loading a single schedule first.
    has_availability = bool(config.get("availability"))

    start = date.fromisoformat(from_date)
    picks: dict[str, dict | None] = {}
    for offset in range(days):
        one_date = (start + timedelta(days=offset)).isoformat()
        if not has_availability:
            picks[one_date] = None
            continue
        schedule = storage.load_latest_schedule(course, one_date, path=Path(db_path))
        if schedule is None:
            picks[one_date] = None
            continue
        _candidates, playable = tui_module._availability_pipeline(schedule, config, club_id)
        if not playable:
            picks[one_date] = None
            continue
        top = playable[0]
        picks[one_date] = {"time": top.slot.time, "score": top.score, "reasons": top.reasons}

    print(json.dumps(picks))


if __name__ == "__main__":
    main()
