"""Headless per-day recommended pick — the GUI's Overview counterpart to
`search_cli.py`'s ad hoc search (2026-09-27).

Direct follow-up: the TUI's Overview has shown a "★ HH:MM" recommended pick per
day (best still-playable slot by `quality.py`'s score, AI-ranked once `ai_assist.enabled`,
with reason keys in `reasons`)
since 2026-09-08 (`tui.py`'s `_day_pick_text()`, `pipeline.py`'s `_availability_pipeline()`), but
the GUI's Overview never had an equivalent — surfaced once AI ranking actually
started working end to end and there was still nothing to see in the Overview
itself (only the ad hoc Search sheet, which already goes through
`recommend.ranked_matches()` via `search_cli.py`).

Reuses `pipeline._availability_pipeline()` directly, the exact function
`_day_pick_text()` itself calls, rather than reimplementing the selection --
this can never drift from what the TUI would show for the same data. (Since
2026-10-05 it imports `pipeline.py`, not the Textual `tui.py`.) `--db-path`/
`--club-slug`/`--course`/`--from`/`--days` are the same flags `search_cli.py`
already takes, same reasoning: `_resolved_config()` builds the identical merged
config either script would use for this club.

Result is one JSON object on stdout keyed by date, not a translated string or an
array -- an O(1) lookup for the GUI, no client-side searching:

    {"2026-09-27": {"time": "09:10", "score": 85.0, "reasons": ["dry", "calm"]},
     "2026-09-28": null}

The pick is the day's *best* playable slot, not the earliest (2026-10-05,
`quality.py`: weather margin, room around the group, predicted crowd, daylight
cushion -- friend/handicap preferences above it, earliest first on a tie), and
`score` is that 0-100 quality score. `reasons` are reason KEYS, at most three, best
contribution first, from this fixed set (the GUI localises them via its own
"quality.reason.<key>" strings, the TUI via `i18n.py`'s; never prose):

    "dry"  "calm"  "mild"  "room_around"  "quiet"  "daylight_spare"

`reasons` is `[]` when nothing about the slot is notably good. With AI ranking on
(`ai_assist.enabled`) the AI chooses among the same candidates, `score` is then its
own 0-100 score, and its free-text sentences arrive as the optional `"ai_reasons"`
(absent when there are none); `reasons` stays the deterministic keys either way.

`null` covers every "nothing to show" case `_day_pick_text()` also collapses to
a plain dash for (no `availability` rules configured yet, no schedule scraped
for that date, or genuinely nothing playable) -- the GUI only needs to know
whether there's a pick to render, not which of those three reasons applies, so
this stays a flat map rather than replicating the TUI's three distinct
"no dry picks"/"too dark to finish"/generic messages.

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

`"locked"` (2026-10-05 -- optional, absent, never null, unless the day is not
bookable yet; older GUI builds ignore it): every slot of that day's latest scrape
carries an advance-booking notice ("4 Tage im Voraus ab 20 Uhr buchbar", see
`booking_window.py`) and its opening time is still ahead. `opens_at` is ISO 8601 with
the club's UTC offset; `hour_known` false means the club names no hour (opens_at is then
00:00 of the opening day and the UI shows the date only). The day then carries no pick:
no pipeline runs for it, and it is not an `alternative` either, even without any
`availability` rules (then `"window"` is null). `window`/`time` stay as above:

    {"2026-10-09": {"time": null, "window": null,
                    "locked": {"opens_at": "2026-10-05T20:00:00+02:00", "hour_known": true}}}

The club's timezone is its YAML's optional `timezone:` (default Europe/Berlin).

`"recommended"` / `"too_late"` (2026-10-05 -- optional, absent, never null or empty, when
there is none; older GUI builds ignore them): the per-slot markers of an expanded day,
as sorted `"HH:MM"` lists -- `"recommended"` the slots the TUI marks "★"
(`pipeline._recommended_times_for()`, read from the very pipeline result the pick above
came from, so no extra ranking or AI call), `"too_late"` the slots it marks "🌙"
(`pipeline._too_late_for_daylight()`, a plain fact about the slot, so it is there
without any `availability` rules too). Exactly what `tui._compute_slot_rows()` shows:
neither marker on a slot already in the past today, and where a slot is in both lists the
TUI's "★" wins (the GUI mirrors that; in practice a recommended slot is playable, so
never too late). A locked day carries "recommended" only for any slots that are actually
open (nearly all, not all, carry the notice; none when fully locked) and its "too_late"
like the TUI's rows do. A day with no availability
rules and no too-late slot stays `null`; with one it is an object with `"time": null`:

    {"2026-10-06": {"time": "16:00", "score": 61.0, "reasons": ["dry"], "window": {...},
                    "recommended": ["16:00", "16:10"], "too_late": ["17:30", "17:40"]}}

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

from . import booking_window, clock, pipeline, recommend, storage


def _flag(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    idx = argv.index(name)
    return argv[idx + 1] if idx + 1 < len(argv) else None


def _slot_markers(schedule, config: dict, recommended: set[str], one_date: str) -> dict:
    """The optional `"recommended"` / `"too_late"` keys for one day (see the module
    docstring) -- `{}` when neither has a slot. Mirrors `tui._compute_slot_rows()`: a
    slot already past today carries no marker, ★ and 🌙 each decided by the same
    pipeline functions the TUI calls, never re-derived."""
    now = clock.now_hhmm() if one_date == clock.today() else None

    def is_past(slot_time: str) -> bool:
        return now is not None and slot_time < now

    markers: dict = {}
    times = sorted(time for time in recommended if not is_past(time))
    if times:
        markers["recommended"] = times
    late = sorted(
        {
            slot.time
            for slot in schedule.slots
            if not is_past(slot.time) and pipeline._too_late_for_daylight(slot.time, schedule, config)
        }
    )
    if late:
        markers["too_late"] = late
    return markers


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
    config = pipeline._resolved_config(club_slug)
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
    tz = booking_window.club_timezone(config)
    now = clock.now_utc()
    for offset in range(days):
        one_date = (start + timedelta(days=offset)).isoformat()
        schedule = storage.load_latest_schedule(course, one_date, path=Path(db_path))
        if schedule is None:
            picks[one_date] = None
            continue
        # A day that isn't bookable yet has no pick to make -- say when it opens instead
        # (2026-10-05), the TUI's "🔒 Wed 21:00". Decided before the availability check:
        # it's worth knowing with no rules configured too.
        status = booking_window.day_booking_status(schedule.slots, one_date, now, tz)
        if status["locked"]:
            window = recommend.window_for_date(one_date, config)
            # No pick, but the TUI still ★-marks any slot of a locked day that is actually
            # open (booking_opening() only needs "nearly all" slots to carry a notice) --
            # _recommended_times_for() is empty when none is, so a fully locked day gets none.
            locked_stars = (
                pipeline._recommended_times_for(schedule, config, club_id, cache) if has_availability else set()
            )
            picks[one_date] = {
                "time": None,
                "window": {"after": window.after, "before": window.before} if window is not None else None,
                "locked": {"opens_at": status["opens_at"].isoformat(), "hour_known": status["hour_known"]},
                **_slot_markers(schedule, config, locked_stars, one_date),
            }
            continue
        if not has_availability:
            # Still worth an object when slots are too late (the TUI's 🌙 needs no rules);
            # otherwise null as ever.
            markers = _slot_markers(schedule, config, set(), one_date)
            if markers:
                window = recommend.window_for_date(one_date, config)
                picks[one_date] = {
                    "time": None,
                    "window": {"after": window.after, "before": window.before} if window is not None else None,
                    **markers,
                }
            else:
                picks[one_date] = None
            continue
        schedules.append(schedule)
        candidates, playable = pipeline._availability_pipeline(schedule, config, club_id, cache)
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
            entry.update({"time": top.slot.time, "score": top.score, "reasons": top.quality_reasons})
            if top.reasons:  # the AI's own sentences, see the module docstring
                entry["ai_reasons"] = top.reasons
        elif candidates:
            entry["unplayable"] = sorted(recommend.unplayable_reasons(candidates, [schedule], config))
            # A shorter round on a sibling course that still finishes before dark
            # (2026-10-05) -- only ever on a day ruled out by daylight alone. Same
            # helper the TUI's Pick column calls, against this --db-path.
            alternative = pipeline._shorter_round_alternative(
                schedule, config, club_id, cache, db_path=Path(db_path)
            )
            if alternative is not None:
                entry["alternative"] = alternative
                alternatives[one_date] = alternative
        # ★/🌙 for the expanded rows, from the same cached pipeline result (2026-10-05).
        entry.update(_slot_markers(schedule, config, pipeline._recommended_times_for(schedule, config, club_id, cache), one_date))
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
