"""Search, crowd heatmap and player directory for the web UI (2026-10-10).

Each one reuses what the terminal app uses: the playability and weather checks of `recommend`, the
gap check of `search`, `pipeline._cached_crowd_heatmap()` with the club's holidays and vacation ranges,
and the `known_players` table. Nothing here ranks, aggregates or classifies on its own.
"""

from datetime import date, datetime, timedelta

from .. import (
    analytics,
    calendar_context,
    clock,
    club_config,
    club_directory,
    pipeline,
    playability,
    recommend,
    search,
    storage,
)
from . import data

SEARCH_DAYS = 14  # how far ahead Search looks: what the club's scrapes keep (scrape_once.MAX_OVERVIEW_DAYS)
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


def _course_of(club: dict, config: dict, course: str | None) -> str | None:
    """`course` if the club has it, else the club's default course, else its first: a search or heatmap for a club
    other than the one open on the page has no course of the page to go by."""
    courses = data.courses_for(club["id"])
    if course in courses:
        return course
    default = config.get("default_course")
    return default if default in courses else (courses[0] if courses else course)


def _time_window(window) -> dict:
    return {"after": (window.after if window else None) or "", "before": (window.before if window else None) or ""}


# ---- search ------------------------------------------------------------------------------


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


def search_slots(slug: str | None, club_id: str | None) -> dict:
    """Every open tee time of the next `SEARCH_DAYS` days on every course of the club that can still be played
    (not started, finished before dark), each with what the page needs to filter by your own rules: whether its
    weather crosses your limits (`wet`) and whether another flight is too close (`gap_ok`). The page narrows these
    down and counts them per day itself, so changing a filter never asks the server again. `mine` carries the
    rules of your Preferences the page offers as chips, `last_start` the latest start that still finishes before
    dark (`None` when no sunset is known)."""
    club, db, config = _club(slug, club_id)
    if club is None:
        return {"error": "unknown_club"}
    criteria = recommend.default_criteria_from_config(config)
    preferences = config.get("preferences") or {}
    weather_rules = [
        rule
        for rule, on in (
            ("rain", preferences.get("avoid_rain")),
            ("wind", preferences.get("avoid_wind")),
            ("temp", preferences.get("avoid_temp_below_c") is not None or preferences.get("avoid_temp_above_c") is not None),
        )
        if on
    ]
    left_out = club_config.excluded_courses(config)
    courses = [course for course in data.courses_for(club["id"]) if course not in left_out]  # the ones you cannot play never show
    friends = storage.load_friend_names(db)
    genders = storage.load_player_genders(db)
    handicaps = storage.load_known_handicaps(db)
    today, now = clock.today(), clock.now_hhmm()
    start = date.fromisoformat(today)
    dates: list[dict] = []
    slots: list[dict] = []
    last_start: str | None = None
    for offset in range(SEARCH_DAYS):
        day = (start + timedelta(days=offset)).isoformat()
        loaded = False
        for course in courses:
            schedule = storage.load_latest_schedule(course, day, path=db)
            if schedule is None:
                continue
            loaded = True
            sunset = schedule.sun_times.sunset if schedule.sun_times else None
            if day == today and pipeline.today_is_over(sunset, now):
                continue
            if sunset and last_start is None:
                duration = recommend._round_duration_minutes(course, config)
                last_start = playability.latest_playable_start(sunset, duration, config.get("daylight_buffer_minutes", 0))
            booking = storage.load_confirmed_booking(course, day, path=db)
            for slot in schedule.slots:
                if slot.block_reason is not None or slot.capacity - slot.booked < 1 or (day == today and slot.time < now):
                    continue
                candidate = search.SlotMatch(date=day, course=course, slot=slot, score=0.0)
                if recommend._fails_playability(candidate, schedule, config):
                    continue
                weather = data._slot_weather(schedule.weather, slot.time) if schedule.weather else None
                slots.append(
                    {
                        "date": day,
                        "course": course,
                        "time": slot.time,
                        "open": slot.capacity - slot.booked,
                        "booked": slot.booked,
                        "capacity": slot.capacity,
                        "players": [
                            {"name": n, "friend": n in friends, "gender": genders.get(n), "hcp": handicaps.get(n)} for n in slot.players
                        ],
                        "weather": weather,
                        "flags": _weather_flags(config, weather),
                        "wet": recommend._fails_weather(candidate, schedule, config),
                        "gap_ok": search._has_buffer_clearance(slot, schedule.slots, criteria.buffer_before_minutes, criteria.buffer_after_minutes),
                        "booked_by_you": bool(booking and booking.time == slot.time),
                    }
                )
        dates.append({"date": day, "loaded": loaded})
    return {
        "today": today,
        "dates": dates,
        "courses": courses,
        "slots": slots,
        "units": config.get("units"),
        "last_start": last_start,
        "mine": {
            "weekday_window": _time_window(criteria.weekday_window),
            "weekend_window": _time_window(criteria.weekend_window),
            "min_open_spots": criteria.min_open_spots,
            "gap_before": criteria.buffer_before_minutes,
            "gap_after": criteria.buffer_after_minutes,
            "weather": weather_rules,
        },
    }


# ---- players -----------------------------------------------------------------------------


def _upcoming_by_player(club: dict, db, config: dict) -> dict[str, list[dict]]:
    """Where each known player is booked from now on, on every course of the club, as
    `{name: [{date, time, course}, ...]}` in date order -- what "jump to their tee time" needs."""
    today = clock.today()
    now = clock.now_hhmm()
    start = datetime.fromisoformat(today).date()
    found: dict[str, list[dict]] = {}
    for course in data.courses_for(club["id"]):
        for offset in range(data._overview_window(config)):
            date = (start + timedelta(days=offset)).isoformat()
            schedule = storage.load_latest_schedule(course, date, path=db)
            if schedule is None:
                continue
            for slot in schedule.slots:
                if date == today and slot.time < now:
                    continue
                for name in slot.players:
                    found.setdefault(name, []).append({"date": date, "time": slot.time, "course": course})
    for hits in found.values():
        hits.sort(key=lambda hit: (hit["date"], hit["time"], hit["course"]))
    return found


def _upcoming_everywhere(open_club: dict, open_db, open_config: dict) -> dict[str, list[dict]]:
    """`_upcoming_by_player()` for every saved club (and the one open, if it is only being looked at), each hit
    with its club -- the directory is shared, so a friend booked at another of your clubs shows too. Only reads
    what the clubs' own background refreshes stored: nothing is fetched from pc caddie for this."""
    clubs = [(open_club, open_db, open_config)]
    for entry in data.club_entries():
        if entry["id"] != open_club["id"]:
            other, db, config = _club(entry["slug"], None)
            if other is not None:
                clubs.append((other, db, config))
    found: dict[str, list[dict]] = {}
    for club, db, config in clubs:
        here = club["id"] == open_club["id"]
        for name, hits in _upcoming_by_player(club, db, config).items():
            found.setdefault(name, []).extend(
                {**hit, "club": club["name"], "slug": club["slug"], "club_id": club["id"], "here": here} for hit in hits
            )
    for hits in found.values():
        hits.sort(key=lambda hit: (hit["date"], hit["time"], not hit["here"], hit["club"], hit["course"]))
    return found


def players(slug: str | None, club_id: str | None) -> dict:
    club, db, config = _club(slug, club_id)
    if club is None:
        return {"error": "unknown_club"}
    upcoming = _upcoming_everywhere(club, db, config)
    names = club_directory.names_by_id()  # the directory is shared by every club: say which one is home
    return {
        "players": [
            {
                "upcoming": upcoming.get(p.name, []),
                "name": p.name,
                "gender": p.gender,
                "member_status": p.member_status,
                "home_clubs": [names.get(club, club) for club in p.home_clubs],
                "handicap": p.handicap,
                "friend": p.is_friend,
                "last_seen": p.last_seen,
            }
            for p in storage.load_known_players(db)
        ],
        "my_handicap": storage.load_my_handicap(db),
        "today": clock.today(),  # what the "tee time today" filter compares with
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
    course = _course_of(club, config, course) if courses else None
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


