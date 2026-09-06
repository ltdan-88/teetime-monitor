"""Structured search across multiple already-scraped days (ROADMAP.md Phase 4),
used two ways:

- **Ad hoc**, via the TUI's search form: criteria typed in on the spot for a one-off
  need, e.g. "3 players, weekdays only, after 15:00, at least 20 minutes clear of any
  other flight."
- **Default**, via recommend.py: the same SearchCriteria shape, but saved in the active
  club's `availability` block and run automatically against every day in the overview,
  so the week's recommended slots show up without typing anything. This is what
  replaced the older, flatter idea of a single "preferences" block — same engine, just
  two entry points (typed-in vs saved-as-default).

This module does the *hard* filtering only — party size and time windows are exact
checks, not judgment calls, so plain code (not AI) is both simpler and more reliable
here. Ranking the results (dry, calm, safely-before-sunset first, with plain-language
reasons) is a separate step via `ai_assist.rank_slots()`, called by recommend.py for the
saved-default path and by the TUI's ad hoc search handler for the typed-in path — see
ROADMAP.md's "AI placement" note for why that split exists.

Implemented and tested 2026-09-06, as the first of the two deterministic steps behind
`recommend.py`'s `weekly_picks()` (the other being `exclude_unplayable()`) — together
these are the actual MVP per the "Build priority" note in ROADMAP.md: a short, sane
list of bookable slots, with no AI call required to get that far.
"""

from dataclasses import dataclass
from datetime import datetime

from .models import Schedule, Slot, SlotMatch, TimeWindow

_DATE_FMT = "%Y-%m-%d"
_TIME_FMT = "%H:%M"


@dataclass
class SearchCriteria:
    min_open_spots: int = 1  # e.g. 1 for "always play alone", 3 for a 3-player group

    # A day with no window set for its type is skipped entirely. Setting only
    # weekday_window (leaving weekend_window as None) means "weekdays only" — same
    # effect as the old ad hoc "weekdays_only" flag, just expressed as an omission.
    weekday_window: TimeWindow | None = None  # Mon-Fri, e.g. after "17:00"
    weekend_window: TimeWindow | None = None  # Sat-Sun, e.g. after "10:00"

    buffer_minutes: int = 0  # min gap to the nearest other booked flight, either side


def _window_for_date(date: str, criteria: SearchCriteria) -> TimeWindow | None:
    is_weekend = datetime.strptime(date, _DATE_FMT).weekday() >= 5  # Sat=5, Sun=6
    return criteria.weekend_window if is_weekend else criteria.weekday_window


def _within_window(time: str, window: TimeWindow) -> bool:
    if window.after is not None and time < window.after:
        return False
    if window.before is not None and time > window.before:
        return False
    return True


def _is_another_flight(slot: Slot) -> bool:
    """Whether a slot represents something happening nearby that a buffer check should
    care about — real players booked, or a block (event/lesson/guest/advance-booking
    notice all count, same as booking_watch.py's neighbor-crowding logic treats them).
    A fully open slot isn't "another flight" and doesn't count against the buffer."""
    return slot.booked > 0 or slot.block_reason is not None


def _has_buffer_clearance(slot: Slot, other_slots: list[Slot], buffer_minutes: int) -> bool:
    if buffer_minutes <= 0:
        return True
    slot_time = datetime.strptime(slot.time, _TIME_FMT)
    for other in other_slots:
        if other is slot or not _is_another_flight(other):
            continue
        other_time = datetime.strptime(other.time, _TIME_FMT)
        gap_minutes = abs((other_time - slot_time).total_seconds()) / 60
        if gap_minutes < buffer_minutes:
            return False
    return True


def search(schedules: list[Schedule], criteria: SearchCriteria) -> list[SlotMatch]:
    """Return matching slots across all given days — filtered, not yet ranked
    (`score`/`reasons` unset). Pass the result to `ai_assist.rank_slots()` for that."""
    matches: list[SlotMatch] = []
    for schedule in schedules:
        window = _window_for_date(schedule.date, criteria)
        if window is None:
            continue  # this day type (weekday/weekend) has no configured window at all

        for slot in schedule.slots:
            if slot.block_reason is not None:
                continue  # can't book a blocked slot
            if slot.capacity - slot.booked < criteria.min_open_spots:
                continue
            if not _within_window(slot.time, window):
                continue
            if not _has_buffer_clearance(slot, schedule.slots, criteria.buffer_minutes):
                continue
            matches.append(SlotMatch(date=schedule.date, course=schedule.course, slot=slot, score=0.0))
    return matches
