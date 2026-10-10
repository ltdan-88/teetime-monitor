"""The local web UI (src/webui/, 2026-10-10): the JSON it builds and the server around it."""

import http.client
import json
import threading
import time
from datetime import date, timedelta

import pytest

from src import clock, club_config, global_preferences, scrape_once, storage
from src.models import ConfirmedBooking, PlayerSighting, Schedule, Slot, SunTimes, WeatherPoint
from src.webui import data, server

CLUB_ID = "0000001"
COURSE = "18 Loch Tee 1"


def _schedule(day: str, hot: bool = False) -> Schedule:
    slots = [
        Slot(time="06:30", booked=0, capacity=4),  # before the sunrise row: not listed
        Slot(time="07:10", booked=2, capacity=4, players=["Max Mustermann", "Erika Musterfrau"]),
        Slot(time="09:00", booked=1, capacity=4, players=["Jonas Mustermann"]),
        Slot(time="09:10", booked=0, capacity=4, block_reason="Turnier"),
        Slot(time="19:00", booked=4, capacity=4),
        Slot(time="19:50", booked=0, capacity=4),  # after the sunset row: not listed
    ]
    weather = [
        WeatherPoint(
            time=f"{hour:02d}:00",
            precipitation_probability=80 if hot else 10,
            precipitation_mm=1.5,
            wind_speed_kph=20 + hour,
            temperature_c=10 + hour / 2,
            weather_code=61 if hot else 1,
        )
        for hour in range(6, 21)
    ]
    return Schedule(date=day, course=COURSE, slots=slots, weather=weather, sun_times=SunTimes("07:12", "19:08"), events=["Clubturnier"])


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """One saved club with two scraped days, and a friend, in throwaway folders."""
    clubs_dir, data_dir = tmp_path / "clubs", tmp_path / "data"
    clubs_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setattr(club_config, "CLUBS_DIR", clubs_dir)
    monkeypatch.setattr(scrape_once, "DATA_DIR", data_dir)
    club_config.save_club_config(
        "golfclub-beispiel",
        {"club_id": CLUB_ID, "name": "Golfclub Beispiel", "default_course": COURSE, "overview_days": 3, "location": {"lat": 49.8, "lon": 9.9}},
        clubs_dir,
    )
    db = data_dir / f"{CLUB_ID}.db"
    today = date.today()
    storage.save_schedule(_schedule(today.isoformat()), path=db, authenticated=True)
    storage.save_schedule(_schedule((today + timedelta(days=1)).isoformat(), hot=True), path=db, authenticated=True)
    storage.record_seen_players(
        [PlayerSighting(name="Max Mustermann", gender="male"), PlayerSighting(name="Erika Musterfrau", gender="female")],
        "2026-10-01T10:00:00+00:00",
        path=db,
    )
    storage.set_player_friend("Max Mustermann", True, path=db)
    storage.save_confirmed_booking(ConfirmedBooking(date=today.isoformat(), course=COURSE, time="09:00", source="manual"), path=db)
    data._OVERVIEW_CACHE.clear()
    return db


# ---- data ---------------------------------------------------------------------------------


def test_heat_strip_has_six_two_hour_buckets_and_ignores_blocked_slots():
    slots = [
        Slot(time="08:10", booked=2, capacity=4),
        Slot(time="09:00", booked=4, capacity=4),
        Slot(time="10:00", booked=0, capacity=4, block_reason="Turnier"),
    ]
    strip = data.heat_strip(slots)
    assert len(strip) == 6
    assert strip[0] == 0.75  # 08:00-10:00: 6 of 8 seats
    assert strip[1] is None  # 10:00-12:00: only a blocked slot, nothing bookable
    assert strip[5] is None


def test_day_weather_summary_uses_the_daytime_window_only():
    points = [
        WeatherPoint(time="06:00", temperature_c=-5, precipitation_probability=100, wind_speed_kph=99, weather_code=95),
        WeatherPoint(time="09:00", temperature_c=12, precipitation_probability=20, precipitation_mm=0.5, wind_speed_kph=10, weather_code=1),
        WeatherPoint(time="15:00", temperature_c=18, precipitation_probability=40, precipitation_mm=1.0, wind_speed_kph=25, weather_code=61),
    ]
    summary = data.day_weather_summary(points)
    assert (summary["temp_high"], summary["temp_low"]) == (18, 12)
    assert summary["rain_avg"] == 30
    assert summary["rain_mm"] == 1.5
    assert summary["wind_peak"] == 25
    assert summary["code"] == 61  # the worst daytime code; the 06:00 storm is outside the window
    assert summary["rain_all_day"] is False
    assert data.day_weather_summary([]) is None


def test_worst_code_follows_the_severity_order_and_ignores_unknown_codes():
    assert data.worst_code([0, 3, 61]) == 61
    assert data.worst_code([None, 1234]) is None
    assert data.worst_code([2, 95]) == 95


def test_closest_slot_time_prefers_the_earlier_on_a_tie():
    slots = [Slot(time="07:00", booked=0, capacity=4), Slot(time="07:20", booked=0, capacity=4)]
    assert data._closest_slot_time(slots, "07:10") == "07:00"
    assert data._closest_slot_time(slots, None) is None


def test_overview_lists_days_slots_markers_and_the_booking(seeded):
    result = data.overview("golfclub-beispiel", None)
    assert result["course"] == COURSE
    assert result["courses"] == [COURSE]
    assert len(result["days"]) == 2  # only scraped dates of the 3-day window
    today = result["days"][0]
    assert today["booked_time"] == "09:00"
    assert [s["time"] for s in today["slots"]] == ["07:10", "09:00", "09:10", "19:00"]
    first = today["slots"][0]
    assert first["sunrise"] and today["slots"][-1]["sunset"]
    assert first["players"][0] == {"name": "Max Mustermann", "friend": True, "gender": "male", "hcp": None}
    assert first["players"][1]["gender"] == "female" and first["players"][1]["friend"] is False
    assert today["slots"][1]["booked_by_you"] is True
    assert today["slots"][2]["block_reason"] == "Turnier"
    assert today["events"] == ["Clubturnier"]
    assert len(today["heat"]) == 6
    assert result["freshness"]["interval_minutes"] == scrape_once.DEFAULT_SCRAPE_INTERVAL_MINUTES


def test_overview_unknown_club_and_unknown_course(seeded):
    assert data.overview("nope", None) == {"error": "unknown_club"}
    assert data.overview("golfclub-beispiel", "Not A Course")["course"] == COURSE  # falls back to the default


def test_overview_is_cached_until_the_database_changes(seeded, monkeypatch):
    calls = []
    real = data.picks_cli.compute_picks
    monkeypatch.setattr(data.picks_cli, "compute_picks", lambda *a, **k: calls.append(a) or real(*a, **k))
    data.overview("golfclub-beispiel", COURSE)
    data.overview("golfclub-beispiel", COURSE)
    assert len(calls) == 1
    storage.save_schedule(_schedule(date.today().isoformat()), path=seeded)
    data.overview("golfclub-beispiel", COURSE)
    assert len(calls) == 2


def test_the_days_come_at_once_and_the_picks_follow(seeded, monkeypatch):
    calls = []
    real = data.picks_cli.compute_picks
    monkeypatch.setattr(data.picks_cli, "compute_picks", lambda *a, **k: calls.append(a) or real(*a, **k))
    quick = data.overview("golfclub-beispiel", COURSE, picks=False)
    assert calls == [] and quick["picks_pending"] is True and len(quick["days"]) == 2
    assert quick["days"][0]["pick"] is None and not any(s["recommended"] for s in quick["days"][0]["slots"])
    full = data.overview("golfclub-beispiel", COURSE)
    assert len(calls) == 1 and full["picks_pending"] is False
    again = data.overview("golfclub-beispiel", COURSE, picks=False)  # ranked once: nothing is pending any more
    assert len(calls) == 1 and again["picks_pending"] is False and again["days"] == full["days"]


def test_clubs_are_listed_alphabetically(seeded):
    for slug, name in (("zebra", "Zebra Golf"), ("alpha", "alpha golf"), ("mitte", "Mitte GC")):
        club_config.save_club_config(slug, {"club_id": {"zebra": "0000003", "alpha": "0000004", "mitte": "0000005"}[slug], "name": name})
    assert [c["name"] for c in data.club_entries()] == ["alpha golf", "Golfclub Beispiel", "Mitte GC", "Zebra Golf"]


def test_club_entries_skip_a_file_without_a_club_id(seeded, tmp_path):
    (club_config.CLUBS_DIR / "broken.yaml").write_text("name: no id here\n", encoding="utf-8")
    assert [c["slug"] for c in data.club_entries()] == ["golfclub-beispiel"]


# ---- server -------------------------------------------------------------------------------


@pytest.fixture
def running(seeded):
    web = server.WebServer(port=0, token="secret-token")
    thread = threading.Thread(target=lambda: web.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    yield web
    web.shutdown()
    web.server_close()


def _request(web, method, path, *, cookie=True, headers=None, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", web.port, timeout=10)
    all_headers = dict(headers or {})
    if cookie:
        all_headers["Cookie"] = f"{server.COOKIE_NAME}={web.token}"
    if body is not None:
        all_headers["Content-Type"] = "application/json"
    connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=all_headers)
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response, payload


def test_nothing_is_served_without_the_session_cookie(running):
    for path in ("/", "/api/bootstrap", "/app.js", "/api/overview?slug=golfclub-beispiel"):
        response, _ = _request(running, "GET", path, cookie=False)
        assert response.status == 403, path


def test_the_token_url_sets_a_strict_http_only_cookie_and_redirects(running):
    response, _ = _request(running, "GET", "/?t=secret-token", cookie=False)
    assert response.status == 302
    assert response.getheader("Location") == "/"
    cookie = response.getheader("Set-Cookie")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "secret-token" in cookie


def test_a_wrong_token_is_refused(running):
    response, _ = _request(running, "GET", "/?t=wrong", cookie=False)
    assert response.status == 403
    assert "Set-Cookie" not in dict(response.getheaders())


def test_a_foreign_host_header_is_refused_even_with_the_cookie(running):
    response, _ = _request(running, "GET", "/api/bootstrap", headers={"Host": "evil.example:80"})
    assert response.status == 403


def test_a_cross_origin_post_is_refused(running):
    response, _ = _request(running, "POST", "/api/ping", headers={"Origin": "http://evil.example"}, body={})
    assert response.status == 403
    assert running.last_ping is None
    response, _ = _request(running, "POST", "/api/ping", headers={"Origin": f"http://127.0.0.1:{running.port}"}, body={})
    assert response.status == 200
    assert running.last_ping is not None


def test_static_files_are_served_with_a_strict_csp_and_no_traversal(running):
    response, body = _request(running, "GET", "/")
    assert response.status == 200 and b"Teetime Monitor" in body
    assert "script-src 'self'" in response.getheader("Content-Security-Policy")
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    response, body = _request(running, "GET", "/app.js")
    assert response.status == 200 and response.getheader("Content-Type").startswith("text/javascript")
    response, _ = _request(running, "GET", "/vendor/htm-preact.js")
    assert response.status == 200
    for bad in ("/../server.py", "/%2e%2e/server.py", "/nothing.txt", "/vendor/"):
        response, _ = _request(running, "GET", bad)
        assert response.status == 404, bad


def test_bootstrap_and_overview_json(running):
    response, body = _request(running, "GET", "/api/bootstrap")
    boot = json.loads(body)
    assert response.status == 200
    assert boot["language"] in ("en", "de") and boot["units"] == "metric"
    assert [c["slug"] for c in boot["clubs"]] == ["golfclub-beispiel"]
    assert response.getheader("Cache-Control") == "no-store"

    response, body = _request(running, "GET", "/api/overview?slug=golfclub-beispiel")
    overview = json.loads(body)
    assert response.status == 200 and len(overview["days"]) == 2
    assert _request(running, "GET", "/api/overview?slug=nope")[0].status == 404
    assert _request(running, "GET", "/api/overview")[0].status == 400


def test_last_club_is_remembered_through_the_existing_preference(running, monkeypatch):
    saved = []
    monkeypatch.setattr(global_preferences, "save_last_active_club", lambda *args: saved.append(args))
    response, _ = _request(running, "POST", "/api/last", body={"slug": "golfclub-beispiel", "course": COURSE})
    assert response.status == 200
    assert saved == [(CLUB_ID, "golfclub-beispiel", COURSE)]
    assert _request(running, "POST", "/api/last", body={"slug": "nope", "course": COURSE})[0].status == 400


def test_refresh_runs_a_forced_scrape_in_the_background_and_reports_when_done(running, monkeypatch):
    calls = []

    def fake_scrape(slug, config, force=False, source="agent"):
        calls.append((slug, force, source))
        return []

    monkeypatch.setattr(scrape_once, "scrape_due_for_club", fake_scrape)
    response, body = _request(running, "POST", "/api/refresh", body={"slug": "golfclub-beispiel", "force": True})
    assert response.status == 200
    for _ in range(100):
        status = json.loads(_request(running, "GET", "/api/refresh/status?key=golfclub-beispiel")[1])
        if not status["running"]:
            break
        time.sleep(0.05)
    assert status["running"] is False and status["error"] is None
    assert calls == [("golfclub-beispiel", True, "gui")]
    assert _request(running, "POST", "/api/refresh", body={"slug": "nope"})[0].status == 404


def test_a_failing_scrape_is_reported_not_fatal(running, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(scrape_once, "scrape_due_for_club", boom)
    _request(running, "POST", "/api/refresh", body={"slug": "golfclub-beispiel", "force": False})
    for _ in range(100):
        status = json.loads(_request(running, "GET", "/api/refresh/status?key=golfclub-beispiel")[1])
        if not status["running"]:
            break
        time.sleep(0.05)
    assert "network down" in status["error"]
    assert _request(running, "GET", "/api/bootstrap")[0].status == 200  # still serving


def test_the_server_stops_itself_once_the_window_has_gone_quiet(running, monkeypatch):
    assert running.should_exit() is False
    now = time.monotonic()
    running.last_ping = now - server.IDLE_EXIT_AFTER_FIRST_PING_SECONDS - 1
    assert running.should_exit() is True
    running.keep_running = True
    assert running.should_exit() is False
    running.keep_running = False
    running.last_ping = None
    running.started = now - server.IDLE_EXIT_WITHOUT_ANY_PING_SECONDS - 1
    assert running.should_exit() is True


def test_it_only_ever_binds_to_the_loopback_address(running):
    assert running.server_address[0] == "127.0.0.1"
    assert clock.today()  # (keeps the clock import honest: the suite freezes it for every test)
