"""Local pattern-recognition, crowd heatmap, and personal stats over accumulated scrape
history (ROADMAP.md Phase 5).

Raw aggregation (`crowd_heatmap`, `best_times_by_weekday`, the fixed personal-stats
numbers) is plain SQL/code, no AI involved — grouping rows by weekday/day-type and
hour is an exact `GROUP BY`, not a judgment call, and it needs to produce real numbers
to color a heatmap grid. Interpreting *sparse or noisy* results (open-ended
personal-stats commentary, "say something interesting about my play history") goes
through `ai_assist.summarize_history()` instead — see ROADMAP.md's "AI placement" note.

`crowd_heatmap()` groups by actual weekday (Sun-Sat) plus a separate "special days"
panel for tournament/public_holiday/vacation — reworked 2026-09-09 to match the
original signed-off mockup after direct feedback flagged a real mismatch ("iirc the
heatmap had to be on a daily basis, remember the mockup?"): the first implementation
grouped by `calendar_context.DAY_TYPES` instead (tournament/public_holiday/vacation/
weekend/workday as five buckets on one axis), which loses weekday granularity within
"workday"/"weekend" entirely — exactly what the mockup's own caption warned against
("Friday afternoon clearly isn't a Tuesday afternoon"). See `crowd_heatmap()`'s own
docstring for the full shape and reasoning. Going forward, a new screen or data shape
gets checked against its own mockup (if one exists) before being called done — not
just built to a written spec and assumed to match.

Needs a few weeks of accumulated history to be useful.

Implemented 2026-09-06. Two things found while implementing, resolved and documented
rather than silently changed — see ROADMAP.md's Phase 5 note for the full detail:
`personal_stats()` uses `storage.load_all_confirmed_bookings()` (your own actual
bookings) as its primary source rather than scanning scraped player names for
`my_name` — that was this module's own original plan, written before
`confirmed_bookings` existed as a reliable automatic source, and scanning for your own
name may not even work (you likely can't be your own pc caddie "friend," so your own
booking may show anonymized like anyone else's). `predict_crowding()` is a plain
deterministic lookup with a minimum-sample-size floor, not an AI call — the original
plan to hand "how much to trust a thin pattern" to `ai_assist.summarize_history()`
doesn't actually fit: that function returns prose commentary, not a number
`predict_crowding()` could use as a machine-checkable confidence score.

Needs a few weeks of accumulated history to be useful — every function here degrades
gracefully (empty dict/list, `None`) rather than erroring on a fresh database with no
scrapes yet.
"""

from datetime import date as date_cls
from pathlib import Path

from . import calendar_context
from .models import DateRange
from .storage import (
    DEFAULT_DB_PATH,
    distinct_scraped_dates,
    load_all_confirmed_bookings,
    load_latest_schedule,
)

# predict_crowding() won't report a number for a day-type/hour bucket with fewer
# samples than this — a single "public_holiday" data point isn't a pattern yet.
MIN_SAMPLES_FOR_PREDICTION = 3


def _occupancy(slot) -> float | None:
    if slot.block_reason is not None:
        return None  # not real occupancy -- excluded, same as recommend.py excludes it
    if slot.capacity <= 0:
        return None
    return slot.booked / slot.capacity


def best_times_by_weekday(course: str, path: Path = DEFAULT_DB_PATH) -> dict[str, list[str]]:
    """Rank each weekday's time slots by historical average occupancy (emptiest first)."""
    buckets: dict[str, dict[str, list[float]]] = {}
    for date in distinct_scraped_dates(course, path):
        schedule = load_latest_schedule(course, date, path)
        if schedule is None:
            continue
        weekday = date_cls.fromisoformat(date).strftime("%A")
        for slot in schedule.slots:
            occupancy = _occupancy(slot)
            if occupancy is None:
                continue
            buckets.setdefault(weekday, {}).setdefault(slot.time, []).append(occupancy)

    result: dict[str, list[str]] = {}
    for weekday, times in buckets.items():
        averaged = {time: sum(values) / len(values) for time, values in times.items()}
        result[weekday] = sorted(averaged, key=averaged.get)
    return result


def personal_stats(my_name: str, path: Path = DEFAULT_DB_PATH) -> dict:
    """Fun/useful numbers about your own play.

    Fixed numbers (days since you last played, total rounds logged) come from
    `storage.load_all_confirmed_bookings()` — actual confirmed bookings, spanning every
    course at this club, not scraped-player-name matching (see module docstring for
    why). `my_name` is used for one secondary cross-check —
    `rounds_with_visible_name` — for the rarer case a club does show your own real
    name rather than anonymizing it. Anything more open-ended ("say something
    interesting about my play history") goes through `ai_assist.summarize_history()`
    on these same raw rows, rather than growing this into an ever-longer list of
    hand-written queries.
    """
    bookings = [b for b in load_all_confirmed_bookings(path) if b.time is not None]

    if not bookings:
        return {"rounds_logged": 0, "days_since_last_played": None, "last_played": None, "rounds_with_visible_name": 0}

    last_played = max(b.date for b in bookings)
    days_since_last_played = (date_cls.today() - date_cls.fromisoformat(last_played)).days

    visible_name_dates = set()
    for booking in bookings:
        schedule = load_latest_schedule(booking.course, booking.date, path)
        if schedule is None:
            continue
        slot = next((s for s in schedule.slots if s.time == booking.time), None)
        if slot is not None and my_name in slot.players:
            visible_name_dates.add(booking.date)

    return {
        "rounds_logged": len(bookings),
        "days_since_last_played": days_since_last_played,
        "last_played": last_played,
        "rounds_with_visible_name": len(visible_name_dates),
    }


def _crowd_buckets(
    course: str, holidays: list[str], vacation_ranges: list[DateRange], path: Path
) -> tuple[dict[str, dict[str, list[float]]], dict[str, dict[str, list[float]]]]:
    """Raw per-hour occupancy samples, before averaging, split into the same two
    groups crowd_heatmap() returns: (by_weekday, special_days) — shared by
    crowd_heatmap() (which averages them) and predict_crowding()'s minimum-sample-size
    floor (which needs the count, not just the average).

    An ordinary day (calendar_context.classify_day() returning "weekend" or "workday")
    goes into `by_weekday`, keyed by its actual weekday name — a special day
    (calendar_context.SPECIAL_DAY_TYPES: tournament/public_holiday/vacation) goes into
    `special_days` instead, keyed by that type, and is *not* also counted toward its
    weekday — see the module docstring for why."""
    by_weekday: dict[str, dict[str, list[float]]] = {}
    special_days: dict[str, dict[str, list[float]]] = {}
    for date in distinct_scraped_dates(course, path):
        schedule = load_latest_schedule(course, date, path)
        if schedule is None or not schedule.slots:
            continue
        day_type = calendar_context.classify_day(
            date, holidays, vacation_ranges, has_tournament=bool(schedule.events)
        )
        if day_type in calendar_context.SPECIAL_DAY_TYPES:
            target = special_days.setdefault(day_type, {})
        else:
            weekday = date_cls.fromisoformat(date).strftime("%A")
            target = by_weekday.setdefault(weekday, {})
        for slot in schedule.slots:
            occupancy = _occupancy(slot)
            if occupancy is None:
                continue
            hour = slot.time[:2]
            target.setdefault(hour, []).append(occupancy)
    return by_weekday, special_days


def _average_buckets(buckets: dict[str, dict[str, list[float]]]) -> dict[str, dict[str, dict[str, float]]]:
    return {
        key: {
            hour: {"average": sum(values) / len(values), "samples": len(values)}
            for hour, values in hours.items()
        }
        for key, hours in buckets.items()
    }


def crowd_heatmap(
    course: str,
    holidays: list[str],
    vacation_ranges: list[DateRange],
    path: Path = DEFAULT_DB_PATH,
) -> dict[str, dict[str, dict[str, dict[str, float]]]]:
    """Historical average occupancy + sample count, as
    {"by_weekday": {"Monday": {"09": {"average": 0.4, "samples": 6}, ...}, ...,
    "Sunday": {...}}, "special_days": {"public_holiday": {"09": {...}, ...},
    "vacation": {...}, "tournament": {...}}}. Carrying `samples` alongside `average`
    is a shape decision made during implementation, not just bare floats as an
    earlier sketch of this function showed — predict_crowding() needs the count to
    apply its minimum-sample-size floor, and a heatmap display can use it too (e.g.
    dim or hatch a cell backed by only one or two samples, rather than showing it
    with the same visual confidence as a cell backed by dozens).

    Reworked 2026-09-09 to match the original signed-off mockup, per direct feedback
    ("iirc the heatmap had to be on a daily basis, remember the mockup?") that turned
    out to be correct once checked against the actual mockup file: the mockup's grid
    was real days of the week (Sun-Sat, each its own column — "Friday afternoon
    clearly isn't a Tuesday afternoon"), with holiday/vacation/tournament days shown
    in a separate "special days" panel, each compared only against *other* days of
    the same kind (so a vacation-week Monday isn't judged against a typical Monday) —
    not folded into the day-of-week grid as three more buckets alongside a coarse
    workday/weekend split, which is what actually got built the first time around.
    `by_weekday` only ever contains ordinary days (never a holiday/vacation/tournament
    date) so neither group's average is diluted by the other's days.

    This is also what lets a *future* day (with no scrape history of its own) get a
    crowd estimate at all — classify it, then look up its weekday's or its special
    type's pattern. Plain aggregation — no AI here, just exact grouping/averaging.
    `holidays` and `vacation_ranges` are supplied by the caller
    (calendar_context.fetch_public_holidays() output, and the club's YAML
    `calendar.vacation_ranges`) rather than fetched here, so this stays a pure
    function over already-fetched inputs, consistent with how recommend.py takes
    already-fetched `schedules` rather than reaching for the network itself. A date's
    own scraped `events` (from scraper.py's block_reason parsing) is what determines
    `has_tournament` — no second tournament source needed here.
    """
    by_weekday, special_days = _crowd_buckets(course, holidays, vacation_ranges, path)
    return {
        "by_weekday": _average_buckets(by_weekday),
        "special_days": _average_buckets(special_days),
    }


def predict_crowding(key: str, time: str, heatmap: dict) -> float | None:
    """Estimated occupancy (0-1) for a time on a given weekday or special day type,
    from a crowd_heatmap() result. `key` is either a weekday name
    (calendar_context.WEEKDAYS, e.g. "Monday") or a special day type
    (calendar_context.SPECIAL_DAY_TYPES, e.g. "tournament") — whichever of
    crowd_heatmap()'s two groups actually holds it; the caller already knows which
    one applies (it classified the date to get here), so this just looks in both
    rather than asking the caller to also say which group.

    A plain deterministic lookup with a minimum-sample-size floor
    (MIN_SAMPLES_FOR_PREDICTION), not an AI call — see the module docstring for why
    the original "hand confidence to ai_assist.summarize_history()" plan didn't
    actually fit (that function returns prose, not a number this could use as a
    machine-checkable confidence score). Returns None if the bucket has no data at all,
    or too few samples to call it a pattern yet — a single "public_holiday" data point
    shouldn't drive a recommendation with the same weight as a well-sampled Monday.
    """
    bucket_group = heatmap.get("by_weekday", {}).get(key) or heatmap.get("special_days", {}).get(key)
    if not bucket_group:
        return None
    bucket = bucket_group.get(time[:2])
    if bucket is None or bucket["samples"] < MIN_SAMPLES_FOR_PREDICTION:
        return None
    return bucket["average"]


def _readiness_for(keys: list[str], group: dict) -> dict[str, dict]:
    result = {}
    for key in keys:
        hours = group.get(key, {})
        result[key] = {
            "hours_seen": len(hours),
            "hours_ready": sum(1 for bucket in hours.values() if bucket["samples"] >= MIN_SAMPLES_FOR_PREDICTION),
            "total_samples": sum(bucket["samples"] for bucket in hours.values()),
        }
    return result


def heatmap_readiness(heatmap: dict) -> dict[str, dict[str, dict]]:
    """How close a `crowd_heatmap()` result is to actually being usable, not just its
    raw averages — added 2026-09-08, direct request for "a menu to track how much
    data has been collected, and how much is still needed to be functional" ahead of
    building the heatmap screen itself. Reworked 2026-09-09 alongside crowd_heatmap()
    itself to report readiness per weekday and per special day type separately,
    rather than one flat list of `calendar_context.DAY_TYPES` — see that function's
    docstring for why. "Ready" reuses `predict_crowding()`'s own
    `MIN_SAMPLES_FOR_PREDICTION` floor rather than a second, separately-tuned
    threshold — the same bar that decides whether a bucket is trustworthy enough to
    predict from is what decides whether it's trustworthy enough to display as a real
    pattern versus "still collecting."

    Every weekday and every special day type is always a key here, even one with zero
    samples — a club with no configured `calendar.country_code`/`vacation_ranges` yet
    will always show 0 for "public_holiday"/"vacation", which is itself useful
    information (that classification simply can't happen yet), not something to hide
    by omitting the row.

    Returns e.g. {"by_weekday": {"Monday": {"hours_seen": 5, "hours_ready": 2,
    "total_samples": 34}, ..., "Sunday": {...}}, "special_days": {"tournament":
    {"hours_seen": 0, "hours_ready": 0, "total_samples": 0}, ...}}."""
    return {
        "by_weekday": _readiness_for(calendar_context.WEEKDAYS, heatmap.get("by_weekday", {})),
        "special_days": _readiness_for(calendar_context.SPECIAL_DAY_TYPES, heatmap.get("special_days", {})),
    }
