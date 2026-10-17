"""Search, crowd heatmap and player directory for the web UI (2026-10-10).

Each one reuses what the terminal app uses: the playability and weather checks of `recommend`, the
gap check of `search`, `pipeline._cached_crowd_heatmap()` with the club's holidays and vacation ranges,
and the `known_players` table. Nothing here ranks, aggregates or classifies on its own.
"""

import re
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


def _natural(name: str) -> list:
    """A course name's sort key with its numbers as numbers: 6 holes, 9 holes, 18 holes (not 18, 6, 9)."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", name)]


def _playable_courses(club: dict, config: dict) -> list[str]:
    """The club's courses you can play (Preferences > Courses), in a natural order: the tabs of Search and the Heatmap."""
    left_out = club_config.excluded_courses(config)
    return sorted((course for course in data.courses_for(club["id"]) if course not in left_out), key=_natural)


def _start_course(courses: list[str], config: dict, page_course: str | None = None) -> str | None:
    """The tab Search and the Heatmap open on: the course you set as where Search starts, else the course open on the
    page, else the club's default course, else the first."""
    for candidate in [*sorted(club_config.search_courses(config), key=_natural), page_course, config.get("default_course")]:
        if candidate in courses:
            return candidate
    return courses[0] if courses else None


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


def search_slots(slug: str | None, club_id: str | None, page_course: str | None = None) -> dict:
    """Every open tee time of the days the overview shows (`overview_days`, five unless set) on every course of the club that can still be played
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
    courses = _playable_courses(club, config)  # the ones you cannot play never show
    friends = storage.load_friend_names(db)
    genders = storage.load_player_genders(db)
    handicaps = storage.load_known_handicaps(db)
    today, now = clock.today(), clock.now_hhmm()
    start = date.fromisoformat(today)
    dates: list[dict] = []
    slots: list[dict] = []
    last_start: str | None = None
    for offset in range(data._overview_window(config)):  # the days the overview shows: later ones have no tee sheet yet
        day = (start + timedelta(days=offset)).isoformat()
        loaded = False
        code = None  # the day's weather, for the icon beside its heading
        for course in courses:
            schedule = storage.load_latest_schedule(course, day, path=db)
            if schedule is None:
                continue
            loaded = True
            if code is None and schedule.weather:
                summary = data.day_weather_summary(schedule.weather)
                code = summary["code"] if summary else None
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
        dates.append({"date": day, "loaded": loaded, "code": code})
    return {
        "today": today,
        "dates": dates,
        "courses": courses,
        "start_course": _start_course(courses, config, page_course),
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


_COUNTS_CACHE: dict[tuple, tuple] = {}


def default_counts(slug: str | None, club_id: str | None, course: str | None) -> dict[str, int]:
    """How many open times of each day pass your Preferences on `course`: what Search shows when it opens on that course,
    and the count in the overview's day headers (a tap opens Search on that day). The same rules as the page's own
    filter when Search opens: your times, your weather limits, your gap and your free seats. Nothing for a course you
    cannot play. Kept until the club's data, the clock's minute or your settings change."""
    club, db, config = _club(slug, club_id)
    if club is None or not course or not db.exists():
        return {}
    stamp = (db.stat().st_mtime, clock.today(), clock.now_hhmm(), repr(config))
    hit = _COUNTS_CACHE.get((str(db), course))
    if hit and hit[0] == stamp:
        return hit[1]
    result = search_slots(slug, club_id, page_course=course)
    if course not in result["courses"]:
        return {}
    mine = result["mine"]
    windows = (mine["weekday_window"], mine["weekend_window"])
    timed = any(window["after"] or window["before"] for window in windows)
    spots = min(4, max(1, mine["min_open_spots"] or 1))
    counts = {day["date"]: 0 for day in result["dates"] if day["loaded"]}
    for slot in result["slots"]:
        if slot["course"] != course or slot["open"] < spots:
            continue
        if (mine["weather"] and slot["wet"]) or ((mine["gap_before"] or mine["gap_after"]) and not slot["gap_ok"]):
            continue
        window = windows[1] if date.fromisoformat(slot["date"]).weekday() >= 5 else windows[0]
        if timed and ((window["after"] and slot["time"] < window["after"]) or (window["before"] and slot["time"] > window["before"])):
            continue
        counts[slot["date"]] = counts.get(slot["date"], 0) + 1
    _COUNTS_CACHE[(str(db), course)] = (stamp, counts)
    return counts


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


def heatmap(slug: str | None, club_id: str | None, course: str | None, page_course: str | None = None) -> dict:
    """Average occupancy and sample count per weekday and hour, and per special day type, from the
    club's scrape history (`analytics.crowd_heatmap()`), with the club's public holidays (if its
    country is set) and vacation ranges telling the special days apart."""
    club, db, config = _club(slug, club_id)
    if club is None:
        return {"error": "unknown_club"}
    courses = _playable_courses(club, config)
    course = course if course in courses else _start_course(courses, config, page_course)
    if course is None or not db.exists():
        return {"course": course, "courses": courses, "by_weekday": {}, "special_days": {}, "has_country": False, "hours": []}
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


