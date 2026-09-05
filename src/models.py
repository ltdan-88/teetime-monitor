"""Core dataclasses shared across scraper, storage, weather, analytics, and TUI.

See ROADMAP.md Phase 1 for `Slot`/`Schedule`, Phase 2 for `WeatherPoint`/`SunTimes`.
"""

from dataclasses import dataclass, field


@dataclass
class Slot:
    time: str  # e.g. "09:10"
    booked: int
    capacity: int
    players: list[str] = field(default_factory=list)


@dataclass
class WeatherPoint:
    time: str  # matches a Slot's time
    precipitation_probability: float | None = None  # 0-100
    precipitation_mm: float | None = None
    wind_speed_kph: float | None = None
    temperature_c: float | None = None


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


@dataclass
class ConfirmedBooking:
    """Your own tee time, confirmed by hand via the TUI's `c` keybinding.

    Not booking data pulled from pc caddie — a manual record, because scraped
    player-name matching can't always be trusted to tell us which slot was ours, and
    pc caddie hides past tee sheets so there's no way to reconstruct this later. See
    ROADMAP.md Phase 1.
    """

    date: str  # YYYY-MM-DD
    course: str
    time: str | None  # None means "confirmed not playing that day"
    holes: int | None = None  # 9 or 18, if noted at confirmation time
    confirmed_at: str = ""  # ISO 8601 timestamp


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
