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

Since 2026-09-27 a scraped day with no pick is still an object, with `"time":
null`, its `"window"` and, when candidates existed but none was playable,
`"unplayable"` (`["daylight"]`/`["weather"]`/both). A reserved `"_hint"` key
carries `recommend.window_too_late_hint()`'s numbers.

`"alternative"` (2026-10-05, optional -- absent, never null, when there is
none; older GUI builds ignore it): on a day ruled out by daylight alone, a
shorter round on another of the club's courses scraped for that date that
still finishes before dark (`recommend.shorter_round_alternative()`, no AI
call):

    {"2026-10-06": {"time": null, "window": {"after": "16:00", "before": null},
                    "unplayable": ["daylight"],
                    "alternative": {"course": "9 Loch Tee 1", "time": "16:10", "holes": 9}}}

`"_hint"` then also lists those courses as `"alternative_courses"`.

Exit code 0 whenever the script actually ran, even if every date came back
`null` (that's a normal, valid result, not an error) -- exit code 1 only when
`--db-path` or `--course` is missing. A `--club-slug` with no clubs/<slug>.yaml
(e.g. just renamed or removed) is not an error: `_resolved_config()` falls back
to your global settings alone, the same as for a club that was never saved, and
a `--db-path` with nothing scraped yet just yields `null` for every date. Takes
no stdin at all -- unlike `search_cli.py`'s ad hoc criteria,
this always uses your own saved defaults (`recommend.default_criteria_from_config()`),
the same rules `_availability_pipeline()` itself checks against.
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from . import recommend, storage
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
    schedules = []
    alternatives: dict[str, dict] = {}
    # One memo for the whole run, so _shorter_round_alternative() reuses the
    # pipeline result computed just above it instead of ranking the day twice.
    cache: dict = {}
    for offset in range(days):
        one_date = (start + timedelta(days=offset)).isoformat()
        if not has_availability:
            picks[one_date] = None
            continue
        schedule = storage.load_latest_schedule(course, one_date, path=Path(db_path))
        if schedule is None:
            picks[one_date] = None
            continue
        schedules.append(schedule)
        candidates, playable = tui_module._availability_pipeline(schedule, config, club_id, cache)
        # Every day with a schedule gets an object now, pick or not (2026-09-27,
        # bundle C of the TUI/GUI consistency audit): `window` is what the GUI
        # dims out-of-window slots and scrolls to on expand with -- decided here
        # by recommend.window_for_date(), not re-derived in Swift -- and
        # `unplayable` is why there's no pick, so the GUI can say "too dark to
        # finish" where the TUI always has instead of staying silent. `time` is
        # null without a pick; older GUI builds already skip such rows.
        window = recommend.window_for_date(one_date, config)
        entry: dict = {
            "time": None,
            "window": {"after": window.after, "before": window.before} if window is not None else None,
        }
        if playable:
            top = playable[0]
            entry.update({"time": top.slot.time, "score": top.score, "reasons": top.reasons})
        elif candidates:
            entry["unplayable"] = sorted(recommend.unplayable_reasons(candidates, [schedule], config))
            # A shorter round on a sibling course that still finishes before dark
            # (2026-10-05) -- only ever on a day ruled out by daylight alone. Same
            # helper the TUI's Pick column calls, against this --db-path.
            alternative = tui_module._shorter_round_alternative(
                schedule, config, club_id, cache, db_path=Path(db_path)
            )
            if alternative is not None:
                entry["alternative"] = alternative
                alternatives[one_date] = alternative
        picks[one_date] = entry

    # Not a date -- the GUI's own parsing only reads keys whose value has a
    # "time", so a reserved key here can't be mistaken for one. See
    # recommend.window_too_late_hint() for its own shape.
    hint = recommend.window_too_late_hint(schedules, config, alternatives) if has_availability else None
    if hint is not None:
        picks["_hint"] = hint
    print(json.dumps(picks))


if __name__ == "__main__":
    main()
