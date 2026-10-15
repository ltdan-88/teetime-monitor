"""The bottom panel's cards (2026-10-15): what is worth a look right now, picked from the days the Overview already shows.

Four cards, each only when there is something to say: your next round (from your confirmed bookings), the best
window this week (the best recommended pick, weather decides between days), the best time with friends (a free spot in
a slot where a friend is already booked) and the best weather (the nicest day that still has a free time). Each card
carries the forecast it is about, with a `mood` the page draws as its little scene (clear, partly, overcast, rain or
snow, from the WMO weather code). No new requests to the site: everything comes from the databases and from
`data.overview()` (cached after the page's own call).
"""

from .. import booking, pipeline, recommend, storage
from . import data

WEEK = 7  # days looked at

# WMO weather codes (see weather_icons.py) -> the scene drawn behind a card
_SNOW = {71, 73, 75, 77, 85, 86}
_RAIN = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
_OVERCAST = {3, 45, 48}


def mood_for_code(code: int | None) -> str:
    """"snow" | "rain" | "overcast" | "partly" | "clear" for a WMO code; an unknown or missing code reads as overcast."""
    if code in _SNOW:
        return "snow"
    if code in _RAIN:
        return "rain"
    if code in _OVERCAST:
        return "overcast"
    if code == 2:
        return "partly"
    if code in (0, 1):
        return "clear"
    return "overcast"


def _score(temp: float | None, rain: float | None, wind: float | None) -> float:
    """Higher is nicer: little rain, little wind, close to a pleasant 21 degrees."""
    score = 0.0
    if rain is not None:
        score -= rain
    if wind is not None:
        score -= max(0.0, wind - 15)
    if temp is not None:
        score -= abs(temp - 21) * 1.5
    return score


def _weather(temp, rain, wind, code, temp_low=None) -> dict:
    return {"temp": temp, "temp_low": temp_low, "rain": rain, "wind": wind, "code": code, "mood": mood_for_code(code)}


def _slot_card(kind: str, day: dict, slot: dict, **extra) -> dict:
    w = slot.get("weather") or {}
    return {
        "kind": kind,
        "date": day["date"],
        "time": slot["time"],
        "free": max(0, slot["capacity"] - slot["booked"]),
        "weather": _weather(w.get("temp"), w.get("rain"), w.get("wind"), w.get("code")),
        **extra,
    }


def _slot_score(slot: dict) -> float:
    w = slot.get("weather") or {}
    return _score(w.get("temp"), w.get("rain"), w.get("wind"))


def _free_slots(day: dict) -> list[dict]:
    return [s for s in day["slots"] if not s["block_reason"] and not s["past"] and s["capacity"] - s["booked"] > 0]


def _next_round(club: dict, db, config: dict) -> dict | None:
    upcoming = booking.upcoming_reservations([club])["reservations"]
    if not upcoming:
        return None
    item = upcoming[0]
    schedule = storage.load_latest_schedule(item["course"], item["date"], path=db)
    weather = sunset = None
    if schedule is not None:
        weather = data._slot_weather(schedule.weather, item["time"])
        sunset = schedule.sun_times.sunset if schedule.sun_times else None
    start = int(item["time"][:2]) * 60 + int(item["time"][3:5]) + recommend._round_duration_minutes(item["course"], config)
    w = weather or {}
    return {
        "kind": "next_round",
        "date": item["date"],
        "time": item["time"],
        "course": item["course"],
        "finish": f"{start // 60 % 24:02d}:{start % 60:02d}",
        "sunset": sunset,
        "weather": _weather(w.get("temp"), w.get("rain"), w.get("wind"), w.get("code")),
    }


def _best_window(days: list[dict]) -> dict | None:
    best = None
    for day in days:
        pick = (day.get("pick") or {}).get("time")
        slot = next((s for s in day["slots"] if s["time"] == pick), None) if pick else None
        if slot is None:
            continue
        score = _slot_score(slot)
        if best is None or score > best[0]:
            best = (score, day, slot)
    return _slot_card("best_window", best[1], best[2]) if best else None


def _with_friends(days: list[dict]) -> dict | None:
    best = None
    for day in days:
        for slot in _free_slots(day):
            friends = [p for p in slot["players"] if p["friend"]]
            if not friends:
                continue
            key = (len(friends), _slot_score(slot))
            if best is None or key > best[0]:
                best = (key, day, slot, friends)
    if best is None:
        return None
    _, day, slot, friends = best
    return _slot_card("friends", day, slot, friends=[{"name": p["name"], "gender": p["gender"]} for p in friends])


def _best_weather(days: list[dict], not_date: str | None) -> dict | None:
    candidates = [d for d in days if d["weather"] and _free_slots(d)]
    others = [d for d in candidates if d["date"] != not_date]
    pool = others or candidates
    if not pool:
        return None
    day = max(pool, key=lambda d: _score(d["weather"]["temp_high"], d["weather"]["rain_avg"], d["weather"]["wind_peak"]))
    w = day["weather"]
    return {
        "kind": "best_weather",
        "date": day["date"],
        "weather": _weather(w["temp_high"], w["rain_avg"], w["wind_peak"], w["code"], w["temp_low"]),
    }


def build(slug: str | None, course: str | None, club_id: str | None = None, name: str | None = None) -> dict:
    """`{"cards": [...]}` for the club and course shown, or `{"error": ...}`."""
    shown = data.overview(slug, course, club_id, name)
    if "error" in shown:
        return shown
    club = shown["club"]
    cards: list[dict] = []
    if club["slug"] is not None:
        config = pipeline._resolved_config(club["slug"], club["id"], club["name"])
        nxt = _next_round(club, data.db_path_for(club["id"]), config)
        if nxt:
            cards.append(nxt)
    days = shown["days"][:WEEK]
    window = _best_window(days)
    for card in (window, _with_friends(days), _best_weather(days, window["date"] if window else None)):
        if card:
            cards.append(card)
    return {"cards": cards}
