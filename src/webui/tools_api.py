"""Search, crowd heatmap and player directory for the web UI (2026-10-10).

Each one reuses what the terminal and Mac apps use: `search_cli.search_matches()` (the ranking
pipeline), `pipeline._cached_crowd_heatmap()` with the club's holidays and vacation ranges, and the
`known_players` table. Nothing here ranks, aggregates or classifies on its own.
"""

from datetime import datetime, timedelta

from .. import analytics, calendar_context, clock, club_directory, pipeline, recommend, search_cli, storage
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


def run_search(slug: str | None, club_id: str | None, course: str, criteria: dict, ai: bool = True) -> dict:
    """The ranked matches. With `ai=False` the AI step is skipped and `ai_pending` says whether a second
    request with `ai=True` would reorder them (AI ranking is on) -- the page shows the quick answer and
    then asks again, so a search never waits seconds for an AI provider."""
    club, db, config = _club(slug, club_id)
    if club is None:
        return {"error": "unknown_club"}
    course = _course_of(club, config, course)
    payload = {
        "min_open_spots": int(criteria.get("min_open_spots") or 1),
        "weekday_window": _clean_window(criteria.get("weekday_window")),
        "weekend_window": _clean_window(criteria.get("weekend_window")),
        "buffer_before_minutes": int(criteria.get("buffer_before_minutes") or 0),
        "buffer_after_minutes": int(criteria.get("buffer_after_minutes") or 0),
        "friends_only": bool(criteria.get("friends_only")),
        "player": (criteria.get("player") or "").strip() or None,
    }
    matches = search_cli.search_matches(str(db), course, club["slug"], clock.today(), SEARCH_DAYS, payload, use_ai=ai)
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
    ai_pending = (not ai) and bool((config.get("ai_assist") or {}).get("enabled")) and bool(matches)
    return {"matches": matches, "days": SEARCH_DAYS, "units": config.get("units"), "ai_pending": ai_pending}


def _clean_window(raw) -> dict:
    """A time window as the search takes it. A blank one is not "skip this kind of day" but "any
    time" (`{"after": None, "before": None}`): what the Mac app sends too, and what "Reset filters"
    leaves behind."""
    raw = raw if isinstance(raw, dict) else {}
    return {"after": raw.get("after") or None, "before": raw.get("before") or None}


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


