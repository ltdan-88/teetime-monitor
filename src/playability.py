"""Is a tee time actually usable before it gets dark? (ROADMAP.md Phase 2)

Pure time arithmetic, no I/O — takes a slot's start time, the day's sunset (from
weather.py's Open-Meteo call), an estimated round duration, and a safety buffer, and
decides whether that round would finish before dark. Round duration is configurable per
round length (9 vs 18 holes) in the active club's YAML, since pace varies by course/player.

Unlike the other src/ modules, this one has no external dependency to wait on, so it's
implemented (and tested) now rather than stubbed.
"""

from datetime import datetime, timedelta

_TIME_FMT = "%H:%M"


def _parse(value: str) -> datetime:
    return datetime.strptime(value, _TIME_FMT)


def latest_playable_start(sunset: str, duration_minutes: int, buffer_minutes: int = 0) -> str:
    """The latest tee time that still finishes `buffer_minutes` before sunset.

    E.g. sunset "19:47", a 4-hour (240 min) round, and a 30-min buffer means the
    latest playable start is "15:17".
    """
    latest = _parse(sunset) - timedelta(minutes=duration_minutes + buffer_minutes)
    return latest.strftime(_TIME_FMT)


def is_playable(slot_time: str, sunset: str, duration_minutes: int, buffer_minutes: int = 0) -> bool:
    """Would a round of `duration_minutes` starting at `slot_time` finish before dark?"""
    return _parse(slot_time) <= _parse(latest_playable_start(sunset, duration_minutes, buffer_minutes))
