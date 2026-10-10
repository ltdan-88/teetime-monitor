"""The JSON the web UI shows (2026-10-10): clubs, courses and the Overview's day cards.

Everything here is read from the same places the terminal app and the Mac app read --
`clubs/*.yaml`, the per-club SQLite database, the merged config (`pipeline._resolved_config()`)
and `picks_cli.compute_picks()` for the Pick column -- so the three front ends cannot drift
apart on what a day looks like. No Textual, no HTTP: plain functions returning plain dicts,
which `server.py` serialises. Weather stays metric here; the browser converts to the
`units` preference it is told about.

The day assembly mirrors `Day` in macos/Sources/Store.swift (the Swift port of
`tui.py`'s Overview), and keeps its rules: a calendar window of `overview_days` from
today, the daytime window 08:00-20:00 for the day summary, six two-hour occupancy
buckets for the heat strip, and the expanded slot list running from the slot nearest
sunrise to the slot nearest sunset.
"""

import importlib.metadata
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .. import (
    clock,
    club_config,
    global_preferences,
    i18n,
    picks_cli,
    pipeline,
    recommend,
    scrape_health,
    scrape_once,
    storage,
    units,
    weather_icons,
)
from ..models import ConfirmedBooking

DAYTIME_START = "08:00"
DAYTIME_END = "20:00"
HEAT_BUCKET_STARTS = range(8, 20, 2)  # six two-hour buckets across 08:00-20:00
DEFAULT_OVERVIEW_DAYS = 5


def version() -> str:
    """The installed package's version -- read from the metadata, as `tui._version()` does, but
    without importing the whole terminal app (several seconds) just to print a number."""
    try:
        return importlib.metadata.version("teetime-monitor")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def db_path_for(club_id: str) -> Path:
    return scrape_once._db_path(club_id)


def club_entries() -> list[dict]:
    """One entry per saved favorite club, newest-scraped first (the Mac app's order).

    A malformed `clubs/*.yaml` is skipped, as everywhere else. `name` falls back to the
    slug for a favorite saved before its name was known."""
    entries = []
    for slug in club_config.list_clubs():
        config = pipeline._load_club_config_safely(slug)
        club_id = config.get("club_id")
        if not club_id:
            continue
        club_id = str(club_id)
        db = db_path_for(club_id)
        health = storage.scrape_health(db)
        entries.append(
            {
                "slug": slug,
                "id": club_id,
                "name": config.get("name") or slug,
                "default_course": config.get("default_course"),
                "last_success_at": health.get("last_success_at"),
            }
        )
    entries.sort(key=lambda entry: entry["last_success_at"] or "", reverse=True)
    return entries


def club_by_slug(slug: str) -> dict | None:
    return next((entry for entry in club_entries() if entry["slug"] == slug), None)


def club_by_id(club_id: str) -> dict | None:
    return next((entry for entry in club_entries() if entry["id"] == club_id), None)


def resolve_club(slug: str | None = None, club_id: str | None = None, name: str | None = None) -> dict | None:
    """A saved club by `slug` (or by id), else -- for a club opened from Add Club without saving it
    -- a stand-in with `slug: None` (a club's database exists the moment it is scraped, saved or not)."""
    if slug:
        return club_by_slug(slug)
    if club_id:
        saved = club_by_id(club_id)
        if saved is not None:
            return saved
        if club_id.isdigit():
            return {"slug": None, "id": club_id, "name": name or club_id, "default_course": None, "last_success_at": None}
    return None


def courses_for(club_id: str) -> list[str]:
    db = db_path_for(club_id)
    if not db.exists():
        return []
    return storage.upcoming_courses(clock.today(), path=db)


def bootstrap() -> dict:
    """What the page needs before it can draw anything."""
    config = pipeline._resolved_config(None)
    last = global_preferences.load_last_active_club()
    return {
        "version": version(),
        "language": i18n.get_language(),
        "units": config.get("units", units.DEFAULT_UNITS),
        "show_handicaps": bool(config.get("show_handicaps", True)),
        "clubs": club_entries(),
        "last": last,
    }


# ---- one day ---------------------------------------------------------------------------


def worst_code(codes: list[int | None]) -> int | None:
    """The single most severe WMO code among `codes` (`weather_icons._SEVERITY_ORDER`:
    a sunny morning and an afternoon thunderstorm is a thunderstorm day), None if none is
    recognised."""
    known = [code for code in codes if code in weather_icons._SEVERITY_ORDER]
    return min(known, key=weather_icons._SEVERITY_ORDER.index) if known else None


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _closest_slot_time(slots: list, target: str | None) -> str | None:
    """The slot time nearest `target`; the earlier one on a tie (`tui._closest_slot_time()`)."""
    if not target or not slots:
        return None
    goal = _minutes(target)
    return min((slot.time for slot in slots), key=lambda time: abs(_minutes(time) - goal))


def day_weather_summary(points: list) -> dict | None:
    """The collapsed row's numbers: daytime high/low, average rain chance and total
    amount, peak wind, and the worst condition (`tui._temperature_cell()` & co.)."""
    daytime = [p for p in points if DAYTIME_START <= p.time < DAYTIME_END]
    if not daytime:
        return None
    temps = [p.temperature_c for p in daytime if p.temperature_c is not None]
    winds = [p.wind_speed_kph for p in daytime if p.wind_speed_kph is not None]
    probabilities = [(p.precipitation_probability or 0) for p in daytime]
    return {
        "temp_high": max(temps) if temps else None,
        "temp_low": min(temps) if temps else None,
        "rain_avg": sum(probabilities) / len(daytime),
        "rain_mm": sum((p.precipitation_mm or 0) for p in daytime),
        "rain_all_day": all((p.precipitation_probability or 0) >= 70 for p in daytime),
        "wind_peak": max(winds) if winds else None,
        "code": worst_code([p.weather_code for p in daytime]),
    }


def heat_strip(slots: list) -> list[float | None]:
    """Occupancy per two-hour bucket across 08:00-20:00; None where nothing is bookable."""
    strip: list[float | None] = []
    for start in HEAT_BUCKET_STARTS:
        real = [s for s in slots if s.block_reason is None and start <= int(s.time[:2]) < start + 2]
        capacity = sum(s.capacity for s in real)
        strip.append(sum(s.booked for s in real) / capacity if capacity else None)
    return strip


def _slot_weather(points: list, time: str) -> dict | None:
    """The hourly forecast point for a slot (a 09:10 slot uses the 09:00 point)."""
    hour = time[:2]
    point = next((p for p in points if p.time.startswith(hour)), None)
    if point is None:
        return None
    return {
        "temp": point.temperature_c,
        "rain": point.precipitation_probability,
        "rain_mm": point.precipitation_mm,
        "wind": point.wind_speed_kph,
        "code": point.weather_code,
    }


def build_day(
    schedule,
    pick: dict | None,
    friends: set[str],
    genders: dict[str, str],
    handicaps: dict[str, float],
    booked_time: str | None,
    today: str,
) -> dict:
    """One Overview day card (see the module docstring for the shape's source)."""
    sun = schedule.sun_times
    sunrise = sun.sunrise if sun else None
    sunset = sun.sunset if sun else None
    sunrise_row = _closest_slot_time(schedule.slots, sunrise)
    sunset_row = _closest_slot_time(schedule.slots, sunset)
    markers = pick or {}
    recommended = set(markers.get("recommended", []))
    too_late = set(markers.get("too_late", []))
    now = clock.now_hhmm() if schedule.date == today else None

    slots = []
    for slot in schedule.slots:
        # From the sunrise row through the sunset row, both kept (they carry the sun
        # notes); every slot when there are no sun times to measure against.
        if sunrise_row and slot.time < sunrise_row:
            continue
        if sunset_row and slot.time > sunset_row:
            continue
        slots.append(
            {
                "time": slot.time,
                "booked": slot.booked,
                "capacity": slot.capacity,
                "block_reason": slot.block_reason,
                "players": [
                    {"name": name, "friend": name in friends, "gender": genders.get(name), "hcp": handicaps.get(name)}
                    for name in slot.players
                ],
                "weather": _slot_weather(schedule.weather, slot.time),
                "sunrise": slot.time == sunrise_row,
                "sunset": slot.time == sunset_row,
                "recommended": slot.time in recommended,
                "too_late": slot.time in too_late,
                "past": now is not None and slot.time < now,
                "booked_by_you": booked_time is not None and slot.time == booked_time,
            }
        )
    return {
        "date": schedule.date,
        "events": list(schedule.events),
        "booked_time": booked_time,
        "sunrise": sunrise,
        "sunset": sunset,
        "weather": day_weather_summary(schedule.weather),
        "heat": heat_strip(schedule.slots),
        "pick": pick,
        "slots": slots,
    }


# ---- the Overview ----------------------------------------------------------------------

# {(db path, course): (db mtime, date, response)} -- `picks_cli.compute_picks()` ranks every
# day (and may call an AI provider), so an unchanged database is not worth ranking twice.
_OVERVIEW_CACHE: dict[tuple[str, str], tuple[float, str, dict]] = {}


def _overview_window(config: dict) -> int:
    days = config.get("overview_days", DEFAULT_OVERVIEW_DAYS)
    return max(1, min(int(days), scrape_once.MAX_OVERVIEW_DAYS)) if isinstance(days, int | float) else DEFAULT_OVERVIEW_DAYS


def banners_for(db: Path) -> list[dict]:
    """Unacknowledged booking changes, rendered in the current language (as the TUI's banners)."""
    if not db.exists():
        return []
    return [
        {
            "id": change["id"],
            "course": change["course"],
            "date": change["date"],
            "time": change["time"],
            "text": i18n.render_booking_change(change["kind"], change["params"]) or change["message"],
        }
        for change in storage.load_unacknowledged_booking_changes(db)
    ]


def overview(slug: str | None, course: str | None, club_id: str | None = None, name: str | None = None) -> dict:
    """The Overview for one club (saved, by `slug`; or just opened, by `club_id`) and course;
    `{"error": ...}` for an unknown club."""
    club = resolve_club(slug, club_id, name)
    if club is None:
        return {"error": "unknown_club"}
    db = db_path_for(club["id"])
    slug = club["slug"]
    config = pipeline._resolved_config(slug, club["id"], club["name"])
    courses = courses_for(club["id"])
    if course not in courses:
        default = config.get("default_course")
        course = default if default in courses else (courses[0] if courses else None)
    interval = int(config.get("scrape_interval_minutes", scrape_once.DEFAULT_SCRAPE_INTERVAL_MINUTES))
    health = storage.scrape_health(db)
    warning = scrape_health.health_warning(health, interval, datetime.now(UTC))
    response = {
        "club": club,
        "courses": courses,
        "course": course,
        "units": config.get("units", units.DEFAULT_UNITS),
        "show_handicaps": bool(config.get("show_handicaps", True)),
        "preview": slug is None,
        "banners": banners_for(db),
        "freshness": {
            "last_success_at": health.get("last_success_at"),
            "last_run_at": health.get("last_run_at"),
            "interval_minutes": interval,
            "warning": warning,
        },
        "days": [],
    }
    if course is None or not db.exists():
        return response

    today = clock.today()
    window = _overview_window(config)
    mtime = db.stat().st_mtime
    key = (str(db), course)
    cached = _OVERVIEW_CACHE.get(key)
    if cached and cached[0] == mtime and cached[1] == today:
        response["days"] = cached[2]["days"]
        response["hint"] = cached[2]["hint"]
        return response

    picks = picks_cli.compute_picks(str(db), course, slug, today, window)
    friends = storage.load_friend_names(db)
    genders = storage.load_player_genders(db)
    handicaps = storage.load_player_handicaps(db)
    start = datetime.fromisoformat(today).date()
    days = []
    for offset in range(window):
        date = (start + timedelta(days=offset)).isoformat()
        schedule = storage.load_latest_schedule(course, date, path=db)
        if schedule is None:
            continue
        booking = storage.load_confirmed_booking(course, date, path=db)
        booked_time = booking.time if booking is not None else None
        days.append(build_day(schedule, picks.get(date), friends, genders, handicaps, booked_time, today))
    response["days"] = days
    response["hint"] = picks.get("_hint")
    _OVERVIEW_CACHE[key] = (mtime, today, {"days": days, "hint": response["hint"]})
    return response


# ---- bookings and notices ----------------------------------------------------------------


def _club_db(slug: str | None, club_id: str | None) -> tuple[dict, Path] | None:
    club = resolve_club(slug, club_id)
    return (club, db_path_for(club["id"])) if club is not None else None


def confirm_booking(slug: str | None, club_id: str | None, course: str, date: str, time: str) -> dict:
    """Mark `time` on `date` as your booking: the manual fallback the TUI's `c` key and the Mac
    app's slot menu write (append-only: the newest row wins). Holes come from the course (name
    heuristic or the club's `course_holes` override)."""
    found = _club_db(slug, club_id)
    if found is None:
        return {"error": "unknown_club"}
    club, db = found
    if not (isinstance(time, str) and len(time) == 5 and time[2] == ":" and time.replace(":", "").isdigit()):
        return {"error": "bad_time"}
    config = pipeline._resolved_config(club["slug"], club["id"], club["name"])
    storage.save_confirmed_booking(
        ConfirmedBooking(
            date=date,
            course=course,
            time=time,
            holes=recommend.holes_for_course(course, config),
            source="manual",
            confirmed_at=datetime.now(UTC).isoformat(),
        ),
        path=db,
    )
    _OVERVIEW_CACHE.clear()
    return {"ok": True}


def cancel_booking(slug: str | None, club_id: str | None, course: str, date: str) -> dict:
    """Record 'not playing that day' (a new row with no time, as the TUI's cancel does)."""
    found = _club_db(slug, club_id)
    if found is None:
        return {"error": "unknown_club"}
    _, db = found
    storage.save_confirmed_booking(
        ConfirmedBooking(date=date, course=course, time=None, holes=None, source="manual", confirmed_at=datetime.now(UTC).isoformat()),
        path=db,
    )
    _OVERVIEW_CACHE.clear()
    return {"ok": True}


def acknowledge_banners(slug: str | None, club_id: str | None, ids: list) -> dict:
    found = _club_db(slug, club_id)
    if found is None:
        return {"error": "unknown_club"}
    storage.acknowledge_booking_changes([int(i) for i in ids if isinstance(i, int)], path=found[1])
    return {"ok": True}
