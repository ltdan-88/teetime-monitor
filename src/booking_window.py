"""Advance-booking-window notices ("4 Tage im Voraus ab 20 Uhr buchbar") as data
(2026-10-05).

A day that isn't bookable yet shows up in pc caddie's tee sheet as a full sheet of
`disable-time` rows whose reason text says when it opens (see `scraper.py`'s
`STATUS_DISABLE_TIME`, stored as `Slot.block_reason`). Until now that text only ever
reached the Events column of the day's own slot rows, while the Pick column said "—"
or "nothing playable" -- though *when* a locked day opens is exactly what a golfer
wants to know, and when a scrape should look again.

Real strings seen in the maintainer's databases (all German, none localised):

    "4 Tage im Voraus ab 20 Uhr buchbar (KP)"                     0497758, Kurzplatz
    "Mitglieder 4 Tage im voraus ab 20 Uhr buchbar"               0497758
    "Mitglieder 4 Tage im voraus ab 20 Uhr buchbarDoppelteestart 11:00 Uhr, ..."
    "Startzeiten 3 Tage vorher ab 21 Uhr"                         0497745
    "Buchung 1 Tag im voraus möglich."                            0497712 (no hour)

Semantics: for a tee-time date D with "N Tage ... ab H Uhr", D becomes bookable at
(D - N calendar days) at H:00 *club-local* time. With no hour, "from the start of day
D - N" (00:00) -- and `hour_known` says so, so a caller never claims a precise time.

Pure: no I/O, no textual import. Anything not recognised is `None` -- never a guess,
since a wrong "opens at" is worse than none (it also decides when a re-scrape runs, see
`scrape_once._should_scrape()`).
"""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from datetime import date as date_cls
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Berlin"  # every club seen so far is on a pc caddie (DE/AT/CH)

# A day counts as locked when at least this share of its "open-looking" slots carry a
# recognised notice. Open-looking = no block reason at all, or a recognised notice; a slot
# blocked by some other text (a tournament or event name, a player, "Belegt") says nothing
# about whether the day is open, so it is left out of the count -- on a locked sheet an
# event reserves its slots under its own name instead of the notice (real: 0497758
# 2026-10-08 had 73 of 84 notices, 0497745 2026-09-14 only 15 of 72 -- the rest the
# "Stadler Trophy"). A slot with no reason still counts *against* the day, so a partly open
# day is never called locked.
LOCKED_SLOT_FRACTION = 0.9
# ...but a few stray notices among event slots aren't a locked day: at least this many
# slots, or this share of the whole day, must carry the notice.
MIN_NOTICE_SLOTS = 5
MIN_NOTICE_DAY_FRACTION = 0.15

# "<N> Tag/Tage/Tagen" directly followed by "im Voraus"/"vorher" -- strict on purpose:
# the words in between are what tell this notice from, say, "3 Tage vor dem Turnier".
_NOTICE_RE = re.compile(r"(?<!\d)(\d{1,3})\s*Tag(?:e|en)?\s+(?:im\s+voraus|vorher)\b", re.IGNORECASE)
# "ab 20 Uhr" / "ab 20:00 Uhr" / "ab 20.30 Uhr", only straight after the notice -- a later
# "Kanonenstart ab 13 Uhr" or "Doppelteestart 11:00 Uhr" is somebody else's hour.
_HOUR_RE = re.compile(r"\s*,?\s*ab\s+(\d{1,2})(?:[:.](\d{2}))?\s*Uhr\b", re.IGNORECASE)
_MAX_DAYS_AHEAD = 365


@dataclass(frozen=True)
class BookingWindow:
    days_ahead: int
    hour: int | None  # None: the notice names no hour
    minute: int = 0  # only ever non-zero with an hour ("ab 20:30 Uhr")


def parse_booking_window(label: str | None) -> BookingWindow | None:
    """The `BookingWindow` a block-reason label states, or None for anything else
    (including a recognisable notice whose numbers make no sense, e.g. "ab 25 Uhr")."""
    if not label:
        return None
    match = _NOTICE_RE.search(label)
    if match is None:
        return None
    days_ahead = int(match.group(1))
    if not 1 <= days_ahead <= _MAX_DAYS_AHEAD:
        return None
    hour: int | None = None
    minute = 0
    hour_match = _HOUR_RE.match(label, match.end())
    if hour_match is not None:
        hour = int(hour_match.group(1))
        minute = int(hour_match.group(2) or 0)
        if hour > 23 or minute > 59:
            return None
    return BookingWindow(days_ahead=days_ahead, hour=hour, minute=minute)


def club_timezone(config: dict | None) -> tzinfo:
    """The club's own timezone: the YAML's optional `timezone:` (an IANA name), else
    Europe/Berlin. An unknown name falls back to the default too -- a typo in a club
    file must not take the Overview down. Where the tz database isn't available the
    machine's own zone stands in (a fixed offset, so approximate) -- not expected: `tzdata`
    is a Windows dependency in pyproject.toml, and macOS/Linux ship the database."""
    names = []
    configured = (config or {}).get("timezone")
    if isinstance(configured, str) and configured.strip():
        names.append(configured.strip())
    names.append(DEFAULT_TIMEZONE)
    for name in names:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            continue
    return datetime.now().astimezone().tzinfo or UTC


def opens_at_for(window: BookingWindow, date: str, tz: tzinfo) -> datetime:
    """When `date` (YYYY-MM-DD) opens under `window`, as an aware datetime in `tz`.
    Calendar-day arithmetic on the *local* date, then the wall-clock time -- not N x 24
    hours, which would be an hour off across a DST change. A wall time that doesn't exist
    (the spring-forward gap) is pushed to the real instant it maps to, and an ambiguous
    one (autumn) takes the first occurrence."""
    opening_day = date_cls.fromisoformat(date) - timedelta(days=window.days_ahead)
    naive = datetime(opening_day.year, opening_day.month, opening_day.day, window.hour or 0, window.minute)
    return naive.replace(tzinfo=tz).astimezone(UTC).astimezone(tz)


def booking_opening(slots, date: str, tz: tzinfo) -> tuple[datetime, bool] | None:
    """(opens_at, hour_known) for a day whose slots (nearly) all carry a recognised
    booking-window notice -- whether or not that moment has passed -- else None.

    "Nearly all": of the slots that look open (no block reason, or a notice) at least
    `LOCKED_SLOT_FRACTION` carry a notice -- slots blocked by other text are ignored, see
    that constant -- and the notices number `MIN_NOTICE_SLOTS` or `MIN_NOTICE_DAY_FRACTION`
    of the whole day. Of the notices seen, the most common one is the day's (an odd slot
    with a different count of days can't move it); on a tie the earliest opening wins."""
    slots = list(slots)
    if not slots:
        return None
    windows = [parse_booking_window(slot.block_reason) for slot in slots]
    recognised = [window for window in windows if window is not None]
    unblocked = sum(1 for slot in slots if not slot.block_reason)
    if not recognised or len(recognised) < LOCKED_SLOT_FRACTION * (len(recognised) + unblocked):
        return None
    if len(recognised) < MIN_NOTICE_SLOTS and len(recognised) < MIN_NOTICE_DAY_FRACTION * len(slots):
        return None
    counts = Counter(recognised)
    top = max(counts.values())
    best = min(
        (window for window, count in counts.items() if count == top),
        key=lambda window: opens_at_for(window, date, tz),
    )
    return opens_at_for(best, date, tz), best.hour is not None


def day_booking_status(slots, date: str, now: datetime, tz: tzinfo) -> dict:
    """{"locked": bool, "opens_at": aware datetime | None, "hour_known": bool} for one
    day's slots. Locked = (nearly) every slot carries a recognised notice AND `now` is
    before it opens. `opens_at` is None whenever the day isn't locked (not a booking-
    window day, or already open). A naive `now` is read as club-local time."""
    opening = booking_opening(slots, date, tz)
    if opening is None:
        return {"locked": False, "opens_at": None, "hour_known": False}
    opens_at, hour_known = opening
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    if now >= opens_at:
        return {"locked": False, "opens_at": None, "hour_known": False}
    return {"locked": True, "opens_at": opens_at, "hour_known": hour_known}
