"""Local pattern-recognition, crowd heatmap, and personal stats over accumulated scrape
history (ROADMAP.md Phase 5).

Raw aggregation (`crowd_heatmap`, `best_times_by_weekday`, the fixed personal-stats
numbers) is plain SQL/code, no AI involved — grouping rows by day-type and hour is an
exact `GROUP BY`, not a judgment call, and it needs to produce real numbers to color a
heatmap grid. Interpreting *sparse or noisy* results (open-ended personal-stats
commentary, "say something interesting about my play history") goes through
`ai_assist.summarize_history()` instead — see ROADMAP.md's "AI placement" note.

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
) -> dict[str, dict[str, list[float]]]:
    """Raw per-day-type/hour occupancy samples, before averaging — shared by
    crowd_heatmap() (which averages them) and predict_crowding()'s minimum-sample-size
    floor (which needs the count, not just the average)."""
    buckets: dict[str, dict[str, list[float]]] = {}
    for date in distinct_scraped_dates(course, path):
        schedule = load_latest_schedule(course, date, path)
        if schedule is None or not schedule.slots:
            continue
        day_type = calendar_context.classify_day(
            date, holidays, vacation_ranges, has_tournament=bool(schedule.events)
        )
        for slot in schedule.slots:
            occupancy = _occupancy(slot)
            if occupancy is None:
                continue
            hour = slot.time[:2]
            buckets.setdefault(day_type, {}).setdefault(hour, []).append(occupancy)
    return buckets


def crowd_heatmap(
    course: str,
    holidays: list[str],
    vacation_ranges: list[DateRange],
    path: Path = DEFAULT_DB_PATH,
) -> dict[str, dict[str, dict[str, float]]]:
    """Historical average occupancy + sample count, grouped by calendar_context.py's
    day-type tag and hour-of-day — e.g. {"public_holiday": {"09": {"average": 0.9,
    "samples": 4}, ...}, "workday": {...}}. Carrying `samples` alongside `average` is a
    shape decision made during implementation, not just bare floats as an earlier
    sketch of this function showed — predict_crowding() needs the count to apply its
    minimum-sample-size floor, and a heatmap display can use it too (e.g. dim or hatch
    a cell backed by only one or two samples, rather than showing it with the same
    visual confidence as a cell backed by dozens).

    Grouping by day-type rather than plain weekday is the point: a Monday during summer
    break isn't "a Monday," it's a vacation-day, and should be compared against other
    vacation-days. This is also what lets a *future* day (with no scrape history of its
    own) get a crowd estimate at all — classify it, then look up its day-type's pattern.
    Plain aggregation — no AI here, just exact grouping/averaging. `holidays` and
    `vacation_ranges` are supplied by the caller (calendar_context.fetch_public_holidays()
    output, and the club's YAML `calendar.vacation_ranges`) rather than fetched here, so
    this stays a pure function over already-fetched inputs, consistent with how
    recommend.py takes already-fetched `schedules` rather than reaching for the network
    itself. A date's own scraped `events` (from scraper.py's block_reason parsing)
    is what determines `has_tournament` — no second tournament source needed here.
    """
    buckets = _crowd_buckets(course, holidays, vacation_ranges, path)
    return {
        day_type: {
            hour: {"average": sum(values) / len(values), "samples": len(values)}
            for hour, values in hours.items()
        }
        for day_type, hours in buckets.items()
    }


def predict_crowding(day_type: str, time: str, heatmap: dict) -> float | None:
    """Estimated occupancy (0-1) for a day-type + time, from a crowd_heatmap() result.

    A plain deterministic lookup with a minimum-sample-size floor
    (MIN_SAMPLES_FOR_PREDICTION), not an AI call — see the module docstring for why
    the original "hand confidence to ai_assist.summarize_history()" plan didn't
    actually fit (that function returns prose, not a number this could use as a
    machine-checkable confidence score). Returns None if the bucket has no data at all,
    or too few samples to call it a pattern yet — a single "public_holiday" data point
    shouldn't drive a recommendation with the same weight as a well-sampled workday.
    """
    hour_buckets = heatmap.get(day_type)
    if not hour_buckets:
        return None
    bucket = hour_buckets.get(time[:2])
    if bucket is None or bucket["samples"] < MIN_SAMPLES_FOR_PREDICTION:
        return None
    return bucket["average"]


def heatmap_readiness(heatmap: dict) -> dict[str, dict]:
    """Per day-type (`calendar_context.DAY_TYPES` order): how close a
    `crowd_heatmap()` result is to actually being usable, not just its raw averages —
    added 2026-09-08, direct request for "a menu to track how much data has been
    collected, and how much is still needed to be functional" ahead of building the
    heatmap screen itself. "Ready" reuses `predict_crowding()`'s own
    `MIN_SAMPLES_FOR_PREDICTION` floor rather than a second, separately-tuned
    threshold — the same bar that decides whether a bucket is trustworthy enough to
    predict from is what decides whether it's trustworthy enough to display as a real
    pattern versus "still collecting."

    Every day type in `DAY_TYPES` is always a key here, even one with zero samples —
    a club with no configured `calendar.country_code`/`vacation_ranges` yet will
    always show 0 for "public_holiday"/"vacation", which is itself useful information
    (that classification simply can't happen yet), not something to hide by omitting
    the row.

    Returns e.g. {"workday": {"hours_seen": 5, "hours_ready": 2, "total_samples": 34},
    "tournament": {"hours_seen": 0, "hours_ready": 0, "total_samples": 0}, ...}."""
    result = {}
    for day_type in calendar_context.DAY_TYPES:
        hours = heatmap.get(day_type, {})
        result[day_type] = {
            "hours_seen": len(hours),
            "hours_ready": sum(1 for bucket in hours.values() if bucket["samples"] >= MIN_SAMPLES_FOR_PREDICTION),
            "total_samples": sum(bucket["samples"] for bucket in hours.values()),
        }
    return result
