"""Core dataclasses shared across scraper, storage, weather, analytics, and TUI.

See ROADMAP.md Phase 1 for `Slot`/`Schedule`, Phase 2 for `WeatherPoint`/`SunTimes`/
`DateRange`.
"""

from dataclasses import dataclass, field


@dataclass
class Slot:
    time: str  # e.g. "09:10"
    booked: int
    capacity: int
    players: list[str] = field(default_factory=list)  # real names only (pc caddie
    # friends); anonymized "Occupied" placeholders are counted in `booked`, not stored
    # here as fake player names — see ROADMAP.md "Confirmed pc caddie markup reference"
    block_reason: str | None = None  # None = genuine member occupancy (or fully open).
    # Otherwise the label pc caddie showed: an event/lesson/guest/sponsor name, or an
    # advance-booking-window notice. The latter isn't real occupancy at all — just "not
    # bookable yet" — so callers (recommend.py, analytics.py) should treat a slot with
    # block_reason as unknown/blocked, not automatically as "crowded."


@dataclass
class WeatherPoint:
    time: str  # matches a Slot's time
    precipitation_probability: float | None = None  # 0-100
    precipitation_mm: float | None = None
    wind_speed_kph: float | None = None
    temperature_c: float | None = None


@dataclass
class RoundConditions:
    """Worst-case weather across an entire round's duration, not a single point in
    time — see weather.py's conditions_during_round(). Added 2026-09-05: a slot's
    weather can't be judged from its tee-off hour alone once the round runs 2-4+ hours.

    Precipitation and wind are one-sided (more is always worse), so those collapse to
    a single max. Temperature is two-sided — too cold and too hot are both bad — so it
    stays as a min/max pair rather than forcing it into one "worst" number; a caller
    checks min against `avoid_temp_below_c` and max against `avoid_temp_above_c`
    separately.
    """

    max_precipitation_probability: float | None = None  # 0-100
    max_precipitation_mm: float | None = None
    max_wind_speed_kph: float | None = None
    min_temperature_c: float | None = None
    max_temperature_c: float | None = None


@dataclass
class SunTimes:
    sunrise: str  # "HH:MM", local time
    sunset: str  # "HH:MM", local time


@dataclass
class Schedule:
    date: str  # YYYY-MM-DD
    course: str
    slots: list[Slot] = field(default_factory=list)
    weather: list[WeatherPoint] = field(default_factory=list)
    sun_times: SunTimes | None = None
    events: list[str] = field(default_factory=list)  # tournament/event notes, if any
    available_courses: list[str] = field(default_factory=list)  # this week's options


@dataclass
class ConfirmedBooking:
    """Your own tee time.

    Populated automatically each scrape from pc caddie's own "My Reservations" page
    (source="my_reservations") — revised 2026-09-05 once that page turned out to exist.
    The TUI's `c` keybinding (source="manual") remains as a fallback for the same-day
    booking timing gap: pc caddie hides past tee sheets, so if a same-day booking is
    made and played between two scheduled scrapes, there's no way to reconstruct it
    later without the manual record. See ROADMAP.md Phase 1.
    """

    date: str  # YYYY-MM-DD
    course: str
    time: str | None  # None means "confirmed not playing that day"
    holes: int | None = None  # 9 or 18, if noted at confirmation time
    source: str = "manual"  # "my_reservations" or "manual"
    confirmed_at: str = ""  # ISO 8601 timestamp


@dataclass
class DateRange:
    """A labeled span of dates — used for a club's manually-entered vacation periods
    (ROADMAP.md Phase 2), since there's no universal free API for those."""

    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    label: str = ""


@dataclass
class TimeWindow:
    after: str | None = None  # "HH:MM"
    before: str | None = None  # "HH:MM"


@dataclass
class SlotMatch:
    """One scored candidate slot, returned by recommend.py or search.py.

    `reasons` is a short list of plain-language tags for why it scored the way it did
    (e.g. "dry", "calm", "3 open spots", "20 min clear of other flights") — meant to be
    shown next to the slot in the TUI, not just a bare number.
    """

    date: str  # YYYY-MM-DD
    course: str
    slot: Slot
    score: float
    reasons: list[str] = field(default_factory=list)
