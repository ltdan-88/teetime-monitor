"""Headless ad hoc search — the Swift prototype's Tier 2 search (2026-09-18).

`SearchScreen` (see its own docstring in tui.py) is the TUI's "just this once"
search: typed-in criteria run against whatever days are already scraped, via the
exact same `recommend.ranked_matches()` pipeline `weekly_picks()` uses for your
saved defaults. This is that same pipeline, exposed as a `teetime-monitor-search`
console script so the Swift app can shell out to it instead of reimplementing
`search()`/`exclude_unplayable()`/`ai_assist.rank_slots()` itself — those are real,
non-trivial business logic (buffer-clearance math, playability/sunset checks,
per-club weather thresholds, an actual Anthropic API call when AI ranking is on),
not the kind of small, stable aggregation formula this prototype has ported
directly elsewhere (see `Day.swift`'s weather cells).

Criteria come in as one JSON object on stdin — the same shape
`SearchScreen._build_criteria()` builds, just from a Swift form instead of a
Textual one:

    {"min_open_spots": 1,
     "weekday_window": {"after": "17:00", "before": null} | null,
     "weekend_window": {"after": "10:00", "before": null} | null,
     "buffer_before_minutes": 0, "buffer_after_minutes": 0}

Schedules aren't sent over the pipe at all — this loads them itself, the same way
`OverviewScreen` builds `self.schedules` in the first place: one
`storage.load_latest_schedule()` call per date in `[--from, --from + --days)`,
skipping any date nothing's been scraped for yet. Keeps the boundary small (typed
criteria in, matches out) rather than round-tripping a whole schedule list through
JSON on every search.

`--club-slug` resolves the exact same merged config `_resolved_config()` builds for
the TUI (club YAML `availability`/`preferences`/`ai_assist`/`round_duration_minutes`
shallow-merged with global preferences) — reused directly, not re-derived, so this
can never drift from what the TUI itself would compute for the same club.

**Known, flagged gap (same "flagged rather than silently assumed" rule
`recommend.py`'s own module docstring uses):** `crowd_estimates` is not computed
here, unlike `SearchScreen._run_search()`'s own call — `analytics.crowd_heatmap()`
needs a live public-holidays fetch this offline-by-design CLI doesn't make. AI
ranking still runs when a club's `ai_assist.enabled` is on; it just can't factor in
`avoid_predicted_crowd` bias yet. `ranked_matches()` already treats no
crowd_estimates as "skip that one signal," not an error, so results are still real,
just missing that one refinement.

Result is a JSON array on stdout, one object per match, not translated text:

    [{"date": "2026-09-20", "course": "18 Loch Tee 1", "time": "09:10",
      "booked": 2, "capacity": 4, "players": [], "block_reason": null,
      "score": 1.0, "reasons": ["dry", "calm"]}, ...]

An empty array is a normal, valid result ("no matches"), not an error. Exit code 0
whenever the search actually ran, even with zero results; exit code 1 only for a
setup problem (bad stdin JSON, `--db-path`/`--club-slug` that doesn't resolve to
anything) — same "saved is what decides success, not the outcome inside it" shape
`login_cli.py` already uses.
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from . import storage
from . import tui as tui_module
from .models import TimeWindow
from .recommend import ranked_matches
from .search import SearchCriteria


def _flag(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    idx = argv.index(name)
    return argv[idx + 1] if idx + 1 < len(argv) else None


def _criteria_from_payload(payload: dict) -> SearchCriteria:
    def _window(key: str) -> TimeWindow | None:
        raw = payload.get(key)
        if not raw:
            return None
        return TimeWindow(after=raw.get("after"), before=raw.get("before"))

    return SearchCriteria(
        min_open_spots=payload.get("min_open_spots", 1),
        weekday_window=_window("weekday_window"),
        weekend_window=_window("weekend_window"),
        buffer_before_minutes=payload.get("buffer_before_minutes", 0),
        buffer_after_minutes=payload.get("buffer_after_minutes", 0),
    )


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

    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(json.dumps({"error": "bad_input"}))
        sys.exit(1)

    criteria = _criteria_from_payload(payload)
    config = tui_module._resolved_config(club_slug)

    start = date.fromisoformat(from_date)
    schedules = []
    for offset in range(days):
        one_date = (start + timedelta(days=offset)).isoformat()
        schedule = storage.load_latest_schedule(course, one_date, path=Path(db_path))
        if schedule is not None:
            schedules.append(schedule)

    matches = ranked_matches(schedules, criteria, config)
    print(json.dumps([
        {
            "date": match.date,
            "course": match.course,
            "time": match.slot.time,
            "booked": match.slot.booked,
            "capacity": match.slot.capacity,
            "players": match.slot.players,
            "block_reason": match.slot.block_reason,
            "score": match.score,
            "reasons": match.reasons,
        }
        for match in matches
    ]))


if __name__ == "__main__":
    main()
