"""Core dataclasses shared across scraper, storage, weather, analytics, and TUI.

See ROADMAP.md Phase 1 for `Slot`/`Schedule`, Phase 2 for `WeatherPoint`.
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


@dataclass
class Schedule:
    date: str  # YYYY-MM-DD
    course: str
    slots: list[Slot] = field(default_factory=list)
    weather: list[WeatherPoint] = field(default_factory=list)
