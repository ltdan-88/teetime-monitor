"""The web UI's second round (2026-10-10): booking, notices, settings, clubs, login, Add Club,
Search, players and heatmap -- the JSON behind every screen, and the routes in front of it."""

import http.client
import json
import threading
from datetime import date, timedelta

import pytest

from src import club_config, club_directory, env_file, global_preferences, i18n, scrape_once, storage
from src.models import PlayerSighting, Schedule, Slot, SunTimes, WeatherPoint
from src.webui import clubs_api, data, server, settings_api, tools_api

CLUB_ID = "0000001"
COURSE = "18 Loch Tee 1"
SLUG = "golfclub-beispiel"


def _schedule(day: str, rain: float = 5) -> Schedule:
    slots = [
        Slot(time="07:10", booked=1, capacity=4, players=["Max Mustermann"]),
        Slot(time="10:00", booked=0, capacity=4),
        Slot(time="10:10", booked=2, capacity=4, players=["Erika Musterfrau", "Jonas Mustermann"]),
        Slot(time="15:00", booked=0, capacity=4),
        Slot(time="15:10", booked=1, capacity=4),
        Slot(time="19:00", booked=0, capacity=4),
    ]
    weather = [
        WeatherPoint(time=f"{h:02d}:00", precipitation_probability=rain, precipitation_mm=0.0, wind_speed_kph=10, temperature_c=18, weather_code=1)
        for h in range(6, 21)
    ]
    return Schedule(date=day, course=COURSE, slots=slots, weather=weather, sun_times=SunTimes("07:00", "19:00"), events=[])


@pytest.fixture
def world(tmp_path, monkeypatch):
    clubs_dir, data_dir = tmp_path / "clubs", tmp_path / "data"
    clubs_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setattr(club_config, "CLUBS_DIR", clubs_dir)
    monkeypatch.setattr(scrape_once, "DATA_DIR", data_dir)
    monkeypatch.setattr(club_directory, "DATA_DIR", data_dir)
    monkeypatch.setattr(env_file, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(scrape_once.paths, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.paths, "MANAGED_DIRS", (tmp_path, clubs_dir, data_dir))
    club_config.save_club_config(
        SLUG, {"club_id": CLUB_ID, "name": "Golfclub Beispiel", "default_course": COURSE, "location": {"lat": 49.8, "lon": 9.9}}, clubs_dir
    )
    db = data_dir / f"{CLUB_ID}.db"
    today = date.today()
    for offset in range(3):
        storage.save_schedule(_schedule((today + timedelta(days=offset)).isoformat()), path=db, authenticated=True)
    storage.record_seen_players(
        [
            PlayerSighting(name="Max Mustermann", gender="male", member_status="member", handicap=18.4),
            PlayerSighting(name="Erika Musterfrau", gender="female", member_status="guest"),
        ],
        "2026-10-01T10:00:00+00:00",
        path=db,
    )
    global_preferences.save_preferences(
        {"availability": {"min_open_spots": 2, "weekday_window": {"after": "09:00", "before": "17:00"}, "weekend_window": {"after": "09:00", "before": "17:00"}}}
    )
    data._OVERVIEW_CACHE.clear()
    return db


# ---- bookings, notices, unsaved clubs --------------------------------------------------------


def test_marking_and_cancelling_a_booking_shows_in_the_overview(world):
    today = date.today().isoformat()
    assert data.overview(SLUG, COURSE)["days"][0]["booked_time"] is None
    assert data.confirm_booking(SLUG, None, COURSE, today, "10:00") == {"ok": True}
    day = data.overview(SLUG, COURSE)["days"][0]
    assert day["booked_time"] == "10:00" and any(s["booked_by_you"] for s in day["slots"])
    assert data.cancel_booking(SLUG, None, COURSE, today) == {"ok": True}
    assert data.overview(SLUG, COURSE)["days"][0]["booked_time"] is None
    assert data.confirm_booking(SLUG, None, COURSE, today, "ten") == {"error": "bad_time"}
    assert data.confirm_booking("nope", None, COURSE, today, "10:00") == {"error": "unknown_club"}


def test_a_booking_change_is_a_localized_banner_until_acknowledged(world):
    storage.save_booking_change(
        COURSE, date.today().isoformat(), "10:00", "party_grew", "A player joined", {"count": 1, "time": "10:00"}, path=world
    )
    banners = data.overview(SLUG, COURSE)["banners"]
    assert len(banners) == 1 and "10:00" in banners[0]["text"]
    assert data.acknowledge_banners(SLUG, None, [banners[0]["id"]]) == {"ok": True}
    assert data.overview(SLUG, COURSE)["banners"] == []


def test_a_club_that_is_not_saved_can_still_be_looked_at(world, tmp_path):
    other = tmp_path / "data" / "0000009.db"
    storage.save_schedule(_schedule(date.today().isoformat()), path=other)
    result = data.overview(None, None, club_id="0000009", name="Golfclub Fremd")
    assert result["preview"] is True and result["club"]["slug"] is None and result["club"]["name"] == "Golfclub Fremd"
    assert result["course"] == COURSE and len(result["days"]) == 1
    assert data.overview(None, None, club_id="not-a-number") == {"error": "unknown_club"}
    assert data.overview(SLUG, COURSE)["preview"] is False


# ---- settings and preferences ----------------------------------------------------------------


def test_the_preferences_form_lists_the_groups_and_current_values(world):
    form = settings_api.schema("preferences", CLUB_ID)
    groups = {g["key"]: g for g in form["groups"]}
    assert list(groups) == ["settings.group.availability", "settings.group.weather", "settings.group.pace", "settings.group.priorities"]
    fields = {f["id"]: f for g in form["groups"] for f in g["fields"]}
    assert fields["field-availability-min_open_spots"]["value"] == "2"
    assert fields["field-availability-weekday_window-after"]["value"] == "09:00"
    assert any(c["value"] == "2" for c in fields["field-availability-min_open_spots"]["choices"])
    assert fields["field-preferences-avoid_rain"]["kind"] == "bool"
    assert [c["value"] for c in fields["field-preferences-hcp_preference"]["choices"]] == ["off", "similar", "better"]


def test_saving_preferences_changes_only_what_was_sent_and_refreshes_the_picks(world):
    data.overview(SLUG, COURSE)
    assert data._OVERVIEW_CACHE
    result = settings_api.save(
        "preferences",
        {"field-availability-min_open_spots": "3", "field-preferences-avoid_rain": True, "field-availability-weekday_window-before": ""},
    )
    assert result == {"ok": True}
    saved = global_preferences.load_preferences()
    assert saved["availability"]["min_open_spots"] == 3
    assert saved["availability"]["weekday_window"].get("before") is None  # cleared; "after" stays
    assert saved["availability"]["weekday_window"]["after"] == "09:00"
    assert saved["preferences"]["avoid_rain"] is True
    assert not data._OVERVIEW_CACHE  # the picks depend on them


def test_a_bad_number_is_refused_with_a_message_and_saves_nothing(world):
    before = global_preferences.load_preferences()
    result = settings_api.save("preferences", {"field-preferences-avoid_rain_mm": "lots"})
    assert "error" in result
    assert global_preferences.load_preferences() == before


def test_settings_cover_account_display_scraping_and_ai(world):
    payload = settings_api.settings_payload(CLUB_ID)
    assert [g["key"] for g in payload["groups"]] == [
        "settings.group.display",
        "settings.group.scraping",
        "settings.group.ai",
    ]
    ids = {f["id"] for g in payload["groups"] for f in g["fields"]}
    assert "field-units" in ids and "field-__language__" in ids and "field-__theme__" not in ids
    assert payload["clubs"][0]["slug"] == SLUG and payload["clubs"][0]["courses"] == [COURSE]
    assert payload["account"] == {"username": "", "has_password": False}
    assert payload["ai"]["provider"] == "anthropic" and len(payload["ai"]["providers"]) == 4


def test_the_language_setting_applies_and_persists(world, monkeypatch):
    saved = []
    monkeypatch.setattr(i18n, "save_language", lambda lang, config_file=None: saved.append(lang))
    assert settings_api.save("settings", {"field-__language__": "de"}) == {"ok": True}
    assert saved == ["de"] and i18n.get_language() == "de"


def test_club_settings_default_course_holes_remove_and_add(world):
    assert settings_api.set_default_course(SLUG, "Other Course") == {"ok": True}
    assert club_config.load_club_config(SLUG)["default_course"] == "Other Course"
    assert settings_api.set_course_holes(SLUG, "Kurzplatz", 9) == {"ok": True}
    assert club_config.load_club_config(SLUG)["course_holes"] == {"Kurzplatz": 9}
    assert settings_api.set_course_holes(SLUG, "Kurzplatz", None) == {"ok": True}
    assert "course_holes" not in club_config.load_club_config(SLUG)
    assert settings_api.set_default_course("nope", "x") == {"error": "unknown_club"}

    assert clubs_api.add("0000002", "Golfclub Zwei")["ok"] is True
    assert {c["id"] for c in data.club_entries()} == {CLUB_ID, "0000002"}
    assert clubs_api.add("", "")["ok"] is False
    assert clubs_api.remove("0000002")["ok"] is True
    assert clubs_api.remove("0000002") == {"error": "unknown_club"}
    assert [c["id"] for c in data.club_entries()] == [CLUB_ID]


def test_login_is_saved_verified_and_available_to_this_running_process(world, monkeypatch):
    monkeypatch.delenv("PCC_USER", raising=False)
    monkeypatch.delenv("PCC_PASS", raising=False)
    assert settings_api.login("", "pw", None) == {"saved": False, "reason": "username_required"}
    result = settings_api.login("me@example.com", "hunter2", None)
    assert result == {"saved": True, "verified": None}
    assert settings_api.account() == {"username": "me@example.com", "has_password": True}
    import os

    assert os.environ["PCC_USER"] == "me@example.com" and os.environ["PCC_PASS"] == "hunter2"
    # a blank password later means: keep the saved one
    assert settings_api.login("me@example.com", "", None)["saved"] is True
    assert env_file.load_env_value("PCC_PASS") == "hunter2"


def test_ai_key_validation(world):
    assert settings_api.ai_key("", "k")["reason"] == "provider_required"
    assert settings_api.ai_key("nope", "k")["reason"] == "unknown_provider"
    assert settings_api.ai_key("openai", "")["reason"] == "api_key_required"


# ---- Add Club --------------------------------------------------------------------------------


def test_directory_search_marks_saved_clubs_and_accepts_a_typed_id(world, monkeypatch):
    monkeypatch.setattr(club_directory, "load_cached_directory", lambda path=None: [])
    monkeypatch.setattr(club_directory, "load_seed_directory", lambda path=None: [(CLUB_ID, "Golfclub Beispiel"), ("0000005", "Golfpark Nord")])
    found = clubs_api.search("golf")
    assert found["source"] == "seed" and found["count"] == 2
    assert {(r["id"], r["saved"]) for r in found["results"]} == {(CLUB_ID, True), ("0000005", False)}
    typed = clubs_api.search("1234567")
    assert typed["results"][0] == {"id": "1234567", "name": "", "typed": True, "saved": False}
    assert clubs_api.search("   ")["results"] == []
    monkeypatch.setattr(club_directory, "load_cached_directory", lambda path=None: [("0000007", "Live Club")])
    monkeypatch.setattr(club_directory, "cached_at", lambda path=None: "2026-10-01T00:00:00+00:00")
    assert clubs_api.directory_state() == {"source": "live", "count": 1, "fetched_at": "2026-10-01T00:00:00+00:00"}


# ---- Search, players, heatmap ----------------------------------------------------------------


def test_search_opens_with_your_availability_and_finds_slots_in_your_window(world):
    defaults = tools_api.search_defaults(SLUG, None)
    assert defaults["min_open_spots"] == 2 and defaults["weekday_window"] == {"after": "09:00", "before": "17:00"}
    result = tools_api.run_search(SLUG, None, COURSE, defaults)
    times = {m["time"] for m in result["matches"]}
    assert "10:00" in times and "07:10" not in times  # before the window
    match = next(m for m in result["matches"] if m["time"] == "10:10")
    assert match["players"][0]["name"] == "Erika Musterfrau" and match["players"][0]["gender"] == "female"
    assert match["weather"]["temp"] == 18 and match["flags"] == []
    assert tools_api.run_search("nope", None, COURSE, defaults) == {"error": "unknown_club"}


def test_search_flags_the_weather_limits_you_set(world):
    global_preferences.save_preferences(
        {
            "availability": {"min_open_spots": 1, "weekday_window": {"after": "09:00"}, "weekend_window": {"after": "09:00"}},
            "preferences": {"avoid_wind": True, "avoid_wind_kph": 5},
        }
    )
    flags = {tuple(m["flags"]) for m in tools_api.run_search(SLUG, None, COURSE, tools_api.search_defaults(SLUG, None))["matches"]}
    assert ("wind",) in flags or flags == set()  # (an excluded slot is not listed at all)


def test_search_can_be_limited_to_friends_and_one_player(world):
    storage.set_player_friend("Erika Musterfrau", True, path=world)
    criteria = {**tools_api.search_defaults(SLUG, None), "friends_only": True}
    names = {p["name"] for m in tools_api.run_search(SLUG, None, COURSE, criteria)["matches"] for p in m["players"]}
    assert names == {"Erika Musterfrau", "Jonas Mustermann"}  # only the slot a friend is in
    criteria = {**tools_api.search_defaults(SLUG, None), "player": "Jonas Mustermann"}
    assert {m["time"] for m in tools_api.run_search(SLUG, None, COURSE, criteria)["matches"]} == {"10:10"}


def test_the_player_directory_lists_and_marks_friends(world):
    listed = tools_api.players(SLUG, None)
    by_name = {p["name"]: p for p in listed["players"]}
    assert by_name["Max Mustermann"]["handicap"] == 18.4 and by_name["Max Mustermann"]["gender"] == "male"
    assert by_name["Erika Musterfrau"]["member_status"] == "guest" and by_name["Erika Musterfrau"]["friend"] is False
    assert tools_api.set_friend(SLUG, None, "Erika Musterfrau", True) == {"ok": True}
    assert {p["name"] for p in tools_api.players(SLUG, None)["players"] if p["friend"]} == {"Erika Musterfrau"}
    assert tools_api.players("nope", None) == {"error": "unknown_club"}


def test_the_heatmap_groups_history_by_weekday_and_special_day(world, monkeypatch):
    monkeypatch.setattr(tools_api.pipeline, "_holidays_for_club", lambda config, fetch=True: [])
    # scrape history needs finished days: add a few past ones
    for back in range(1, 4):
        storage.save_schedule(_schedule((date.today() - timedelta(days=back)).isoformat()), path=world)
    result = tools_api.heatmap(SLUG, None, None)
    assert result["course"] == COURSE and result["has_country"] is False
    assert set(result["weekdays"]) >= {"Monday", "Sunday"} and result["special_day_types"] == ["tournament", "public_holiday", "vacation"]
    assert result["hours"] and all(len(h) == 2 for h in result["hours"])
    some_day = next(iter(result["by_weekday"].values()))
    bucket = next(iter(some_day.values()))
    assert set(bucket) == {"average", "samples"} and 0 <= bucket["average"] <= 1
    assert tools_api.heatmap("nope", None, None) == {"error": "unknown_club"}


# ---- the routes ------------------------------------------------------------------------------


@pytest.fixture
def running(world):
    web = server.WebServer(port=0, token="tok")
    thread = threading.Thread(target=lambda: web.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    yield web
    web.shutdown()
    web.server_close()


def _call(web, method, path, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", web.port, timeout=20)
    headers = {"Cookie": f"{server.COOKIE_NAME}={web.token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    response = connection.getresponse()
    payload = json.loads(response.read() or b"null")
    connection.close()
    return response.status, payload


def test_every_screens_route_answers(running, monkeypatch):
    monkeypatch.setattr(tools_api.pipeline, "_holidays_for_club", lambda config, fetch=True: [])
    today = date.today().isoformat()
    status, strings = _call(running, "GET", "/api/strings")
    assert status == 200 and strings["language"] in ("en", "de") and "settings.title" in strings["strings"]
    assert _call(running, "GET", "/api/preferences")[1]["groups"]
    assert _call(running, "GET", "/api/settings")[1]["clubs"][0]["slug"] == SLUG
    assert _call(running, "POST", "/api/preferences", {"values": {"field-availability-min_open_spots": "2"}})[1] == {"ok": True}
    assert _call(running, "POST", "/api/preferences", {"values": {"field-preferences-avoid_rain_mm": "x"}})[0] == 400
    assert _call(running, "POST", "/api/booking", {"slug": SLUG, "course": COURSE, "date": today, "time": "10:00"})[1] == {"ok": True}
    assert _call(running, "GET", f"/api/overview?slug={SLUG}")[1]["days"][0]["booked_time"] == "10:00"
    assert _call(running, "POST", "/api/booking/cancel", {"slug": SLUG, "course": COURSE, "date": today})[1] == {"ok": True}
    assert _call(running, "GET", f"/api/search/defaults?slug={SLUG}")[1]["min_open_spots"] == 2
    status, found = _call(running, "POST", "/api/search", {"slug": SLUG, "course": COURSE, "criteria": {"min_open_spots": 1, "weekday_window": {"after": "09:00"}, "weekend_window": {"after": "09:00"}}})
    assert status == 200 and found["matches"]
    assert _call(running, "GET", f"/api/players?slug={SLUG}")[1]["players"]
    assert _call(running, "POST", "/api/players/friend", {"slug": SLUG, "name": "Max Mustermann", "friend": True})[1] == {"ok": True}
    assert _call(running, "GET", f"/api/heatmap?slug={SLUG}")[0] == 200
    assert _call(running, "GET", "/api/directory?q=zzzz")[1]["results"] == []
    assert _call(running, "POST", "/api/club/default-course", {"slug": SLUG, "course": COURSE})[1] == {"ok": True}
    assert _call(running, "POST", "/api/club/add", {"club_id": "0000003", "name": "Drei"})[1]["ok"] is True
    assert _call(running, "POST", "/api/club/remove", {"club_id": "0000003"})[1]["ok"] is True
    assert _call(running, "POST", "/api/club/remove", {"club_id": "0000003"})[0] == 404
    assert _call(running, "GET", "/api/overview")[0] == 400
    assert _call(running, "GET", "/api/nothing")[0] == 404


def test_refreshing_a_club_that_is_only_open_for_a_look_runs_a_preview(running, monkeypatch):
    calls = []
    monkeypatch.setattr(clubs_api, "preview", lambda club_id, name: calls.append((club_id, name)) or {"ok": True})
    status, state = _call(running, "POST", "/api/refresh", {"club_id": "0000009", "name": "Fremd", "force": True})
    assert status == 200
    for _ in range(100):
        state = _call(running, "GET", "/api/refresh/status?key=club:0000009")[1]
        if not state["running"]:
            break
        threading.Event().wait(0.05)
    assert calls == [("0000009", "Fremd")] and state["error"] is None


def test_a_rejected_preview_is_reported_as_the_error(running, monkeypatch):
    monkeypatch.setattr(clubs_api, "preview", lambda club_id, name: {"ok": False, "reason": "no_tee_sheet"})
    _call(running, "POST", "/api/refresh", {"club_id": "0000009", "name": "Fremd"})
    for _ in range(100):
        state = _call(running, "GET", "/api/refresh/status?key=club:0000009")[1]
        if not state["running"]:
            break
        threading.Event().wait(0.05)
    assert state["error"] == "no_tee_sheet"
