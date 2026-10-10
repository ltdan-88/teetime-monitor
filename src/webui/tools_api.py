"""Search, crowd heatmap and player directory for the web UI (2026-10-10).

Each one reuses what the terminal and Mac apps use: `search_cli.search_matches()` (the ranking
pipeline), `pipeline._cached_crowd_heatmap()` with the club's holidays and vacation ranges, and the
`known_players` table. Nothing here ranks, aggregates or classifies on its own.
"""

from .. import analytics, calendar_context, clock, pipeline, recommend, search_cli, storage
from . import data

SEARCH_DAYS = 7  # "this week", as the terminal app's Search
_WEATHER_DEFAULTS = {
    "avoid_rain_probability_percent": recommend.DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT,
    "avoid_rain_mm": recommend.DEFAULT_AVOID_RAIN_MM,
    "avoid_wind_kph": recommend.DEFAULT_AVOID_WIND_KPH,
}


def _club(slug: str | None, club_id: str | None):
    club = data.resolve_club(slug, club_id)
    if club is None:
        return None, None, None
    config = pipeline._resolved_config(club["slug"], club["id"], club["name"])
    return club, data.db_path_for(club["id"]), config


def _time_window(window) -> dict:
    return {"after": (window.after if window else None) or "", "before": (window.before if window else None) or ""}


# ---- search ------------------------------------------------------------------------------


def search_defaults(slug: str | None, club_id: str | None) -> dict:
    """The criteria the form opens with: your saved availability (Preferences)."""
    club, _, config = _club(slug, club_id)
    if club is None:
        return {"error": "unknown_club"}
    criteria = recommend.default_criteria_from_config(config)
    return {
        "min_open_spots": criteria.min_open_spots,
        "weekday_window": _time_window(criteria.weekday_window),
        "weekend_window": _time_window(criteria.weekend_window),
        "buffer_before_minutes": criteria.buffer_before_minutes,
        "buffer_after_minutes": criteria.buffer_after_minutes,
        "friends_only": False,
        "player": "",
    }


def _weather_flags(config: dict, weather: dict | None) -> list[str]:
    """Which of your weather limits this slot's forecast crosses (what the result's chips show)."""
    if not weather:
        return []
    preferences = config.get("preferences") or {}

    def limit(key: str) -> float:
        value = preferences.get(key)
        return _WEATHER_DEFAULTS[key] if value is None else value

    flags = []
    if preferences.get("avoid_rain") and (
        (weather["rain"] or 0) > limit("avoid_rain_probability_percent") or (weather["rain_mm"] or 0) > limit("avoid_rain_mm")
    ):
        flags.append("rain")
    if preferences.get("avoid_wind") and (weather["wind"] or 0) > limit("avoid_wind_kph"):
        flags.append("wind")
    below, above = preferences.get("avoid_temp_below_c"), preferences.get("avoid_temp_above_c")
    if weather["temp"] is not None and (
        (below is not None and weather["temp"] < below) or (above is not None and weather["temp"] > above)
    ):
        flags.append("temp")
    return flags


def run_search(slug: str | None, club_id: str | None, course: str, criteria: dict) -> dict:
    club, db, config = _club(slug, club_id)
    if club is None:
        return {"error": "unknown_club"}
    payload = {
        "min_open_spots": int(criteria.get("min_open_spots") or 1),
        "weekday_window": _clean_window(criteria.get("weekday_window")),
        "weekend_window": _clean_window(criteria.get("weekend_window")),
        "buffer_before_minutes": int(criteria.get("buffer_before_minutes") or 0),
        "buffer_after_minutes": int(criteria.get("buffer_after_minutes") or 0),
        "friends_only": bool(criteria.get("friends_only")),
        "player": (criteria.get("player") or "").strip() or None,
    }
    matches = search_cli.search_matches(str(db), course, club["slug"], clock.today(), SEARCH_DAYS, payload)
    friends = storage.load_friend_names(db)
    genders = storage.load_player_genders(db)
    schedules: dict[str, object] = {}
    booked = {}
    for match in matches:
        day = match["date"]
        if day not in schedules:
            schedules[day] = storage.load_latest_schedule(course, day, path=db)
            booking = storage.load_confirmed_booking(course, day, path=db)
            booked[day] = booking.time if booking else None
        schedule = schedules[day]
        weather = data._slot_weather(schedule.weather, match["time"]) if schedule else None
        match["weather"] = weather
        match["flags"] = _weather_flags(config, weather)
        match["players"] = [{"name": n, "friend": n in friends, "gender": genders.get(n)} for n in match["players"]]
        match["booked_by_you"] = booked[day] == match["time"]
    return {"matches": matches, "days": SEARCH_DAYS, "units": config.get("units")}


def _clean_window(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    after, before = (raw.get("after") or None), (raw.get("before") or None)
    return {"after": after, "before": before} if (after or before) else None


# ---- players -----------------------------------------------------------------------------


def players(slug: str | None, club_id: str | None) -> dict:
    club, db, _ = _club(slug, club_id)
    if club is None:
        return {"error": "unknown_club"}
    return {
        "players": [
            {
                "name": p.name,
                "gender": p.gender if p.gender in ("male", "female") else None,
                "member_status": p.member_status,
                "handicap": p.handicap,
                "friend": p.is_friend,
                "last_seen": p.last_seen,
            }
            for p in storage.load_known_players(db)
        ],
        "my_handicap": storage.load_my_handicap(db),
    }


def set_friend(slug: str | None, club_id: str | None, name: str, is_friend: bool) -> dict:
    club, db, _ = _club(slug, club_id)
    if club is None:
        return {"error": "unknown_club"}
    storage.set_player_friend(name, bool(is_friend), path=db)
    data._OVERVIEW_CACHE.clear()  # the friend star and the pick both depend on it
    return {"ok": True}


# ---- heatmap -----------------------------------------------------------------------------


def heatmap(slug: str | None, club_id: str | None, course: str | None) -> dict:
    """Average occupancy and sample count per weekday and hour, and per special day type, from the
    club's scrape history (`analytics.crowd_heatmap()`), with the club's public holidays (if its
    country is set) and vacation ranges telling the special days apart."""
    club, db, config = _club(slug, club_id)
    if club is None:
        return {"error": "unknown_club"}
    courses = data.courses_for(club["id"])
    if course not in courses:
        default = config.get("default_course")
        course = default if default in courses else (courses[0] if courses else None)
    if course is None or not db.exists():
        return {"course": course, "by_weekday": {}, "special_days": {}, "has_country": False, "hours": []}
    holidays = pipeline._holidays_for_club(config, fetch=True)
    vacations = pipeline._vacation_ranges_for_club(config)
    result = pipeline._cached_crowd_heatmap(course, holidays, vacations, db)
    hours = sorted(
        {hour for group in ("by_weekday", "special_days") for bucket in result[group].values() for hour in bucket}
    )
    return {
        "course": course,
        "courses": courses,
        "by_weekday": result["by_weekday"],
        "special_days": result["special_days"],
        "weekdays": calendar_context.WEEKDAYS,
        "special_day_types": calendar_context.SPECIAL_DAY_TYPES,
        "hours": hours,
        "min_samples": analytics.MIN_SAMPLES_FOR_PREDICTION,
        "has_country": bool((config.get("calendar") or {}).get("country_code")),
        "history_days": len(storage.distinct_scraped_dates(course, db)),
    }


