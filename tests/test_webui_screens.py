"""The web UI's second round (2026-10-10): booking, notices, settings, clubs, login, Add Club,
Search, players and heatmap -- the JSON behind every screen, and the routes in front of it."""

import http.client
import json
import threading
from datetime import date, timedelta

import pytest

from src import (
    booking,
    club_config,
    club_directory,
    env_file,
    global_preferences,
    i18n,
    pipeline,
    scrape_once,
    storage,
    theme,
    user_config,
)
from src.models import ConfirmedBooking, PlayerSighting, Schedule, Slot, SunTimes, WeatherPoint
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


class _FakeSession:
    def close(self):
        pass


def fake_pccaddie(monkeypatch, *, fail: booking.BookingError | None = None, login: bool = True) -> list:
    """pc caddie itself is replaced: every booking or cancellation that would reach it is recorded in the list."""
    calls: list = []

    def attempt(kind):  # what the button sends; reading ahead reaches nothing
        def run(client, club_id, course, date, time, prepared, progress=None):
            calls.append((kind, club_id, course, date, time))
            if fail is not None:
                raise fail

        return run

    monkeypatch.setattr(booking, "open_session", lambda club_id, user, password: _FakeSession())
    monkeypatch.setattr(booking, "prepare_book", lambda *args: booking.Prepared("book", "", ""))
    monkeypatch.setattr(booking, "prepare_cancel", lambda *args: booking.Prepared("cancel", "", ""))
    monkeypatch.setattr(booking, "commit_book", attempt("book"))
    monkeypatch.setattr(booking, "commit_cancel", attempt("cancel"))
    monkeypatch.setattr(club_config, "resolve_credentials", lambda key: ("me", "secret") if login else ("", ""))
    monkeypatch.setattr(scrape_once, "_sync_my_reservations", lambda *args, **kwargs: "ok")
    return calls


def finished(started: dict) -> dict:
    """A booking runs as a job (the page follows its steps): its outcome, as book_for_club() gives it."""
    import time as clock

    if "job" not in started:
        return started
    deadline = clock.time() + 5
    while (state := booking.job(started["job"]))["state"] == "running" and clock.time() < deadline:
        clock.sleep(0.01)
    if state["state"] == "ok":
        return {"ok": True}
    return {"error": state["error"], **({"message": state["message"]} if state["message"] else {})}


def test_booking_and_cancelling_on_pc_caddie_shows_in_the_overview(world, monkeypatch):
    calls = fake_pccaddie(monkeypatch)
    today = date.today().isoformat()
    assert data.overview(SLUG, COURSE)["days"][0]["booked_time"] is None
    assert finished(data.book(SLUG, None, COURSE, today, "10:00")) == {"ok": True}
    day = data.overview(SLUG, COURSE)["days"][0]
    assert day["booked_time"] == "10:00" and any(s["booked_by_you"] for s in day["slots"])
    assert finished(data.cancel(SLUG, None, COURSE, today, "10:00")) == {"ok": True}
    assert data.overview(SLUG, COURSE)["days"][0]["booked_time"] is None
    assert [c[0] for c in calls] == ["book", "cancel"] and calls[0][2:] == (COURSE, today, "10:00")


def test_reservations_lists_upcoming_bookings_earliest_first_without_cancelled_or_past_ones(world, monkeypatch):
    from src import clock

    monkeypatch.setattr(clock, "now_hhmm", lambda: "12:00")
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    for item in (
        ConfirmedBooking(date=d(2), course=COURSE, time="09:10", source="my_reservations", confirmed_at="t1"),
        ConfirmedBooking(date=d(0), course=COURSE, time="14:00", source="my_reservations", confirmed_at="t1"),  # later today
        ConfirmedBooking(date=d(0), course=COURSE, time="10:00", source="my_reservations", confirmed_at="t1"),  # a time already gone today: not listed (the day has one booking: this one wins)
        ConfirmedBooking(date=d(1), course=COURSE, time="08:00", source="my_reservations", confirmed_at="t1"),
        ConfirmedBooking(date=d(1), course=COURSE, time=None, source="my_reservations", confirmed_at="t2"),  # cancelled since
        ConfirmedBooking(date=d(-3), course=COURSE, time="09:00", source="my_reservations", confirmed_at="t1"),  # played already
    ):
        storage.save_confirmed_booking(item, path=world)
    found = data.reservations()
    assert [(r["date"], r["time"]) for r in found["reservations"]] == [(d(2), "09:10")]
    assert found["reservations"][0]["club"] == "Golfclub Beispiel" and found["reservations"][0]["course"] == COURSE and found["reservations"][0]["slug"] == SLUG
    assert found["refreshed"] is False and found["refresh_problems"] == []


def test_reservations_refresh_reads_pc_caddie_first_and_names_the_clubs_it_could_not_check(world, monkeypatch):
    seen = []
    monkeypatch.setattr(scrape_once, "_sync_my_reservations", lambda club_id, slug, db, courses=None: seen.append(slug) or "login")
    found = data.reservations(refresh=True)
    assert seen == [SLUG] and found["refreshed"] is True
    assert found["refresh_problems"] == [{"club": "Golfclub Beispiel", "reason": "login"}]
    monkeypatch.setattr(scrape_once, "_sync_my_reservations", lambda *args, **kwargs: None)  # skipped: no login saved
    assert data.reservations(refresh=True)["refresh_problems"] == [{"club": "Golfclub Beispiel", "reason": "no_login"}]
    monkeypatch.setattr(scrape_once, "_sync_my_reservations", lambda *args, **kwargs: "ok")
    assert data.reservations(refresh=True)["refresh_problems"] == []


def test_the_read_back_after_a_booking_makes_no_further_request_to_the_site(world, monkeypatch):
    """The courses for the read-back come from the database: a second look at the site made the page wait."""
    fake_pccaddie(monkeypatch)
    seen = []
    monkeypatch.setattr(scrape_once, "_sync_my_reservations", lambda club_id, slug, db, courses=None: seen.append((club_id, slug, courses)) or "ok")

    def forbidden(club_id, client=None, fresh=False):
        raise AssertionError("the read-back must not ask the site for its courses")

    monkeypatch.setattr(booking.scraper, "fetch_course_aliases", forbidden)
    assert finished(data.book(SLUG, None, COURSE, date.today().isoformat(), "10:00")) == {"ok": True}
    assert seen == [(CLUB_ID, SLUG, [COURSE])]


def test_the_page_that_verified_a_booking_is_recorded_without_another_login(world, monkeypatch):
    from src.models import ReservationsSync

    fake_pccaddie(monkeypatch)
    today = date.today().isoformat()
    verified = ReservationsSync(bookings=[ConfirmedBooking(date=today, course=COURSE, time="10:00", source="my_reservations", confirmed_at="t")], my_handicap=18.4)
    monkeypatch.setattr(booking, "commit_book", lambda client, club_id, course, day, time, prepared, progress=None: booking.BookingResult(club_id, course, day, time, verified))

    def forbidden(*args, **kwargs):
        raise AssertionError("the verified page is recorded as it is; no second login")

    monkeypatch.setattr(scrape_once, "_sync_my_reservations", forbidden)
    assert finished(data.book(SLUG, None, COURSE, today, "10:00")) == {"ok": True}
    assert data.overview(SLUG, COURSE)["days"][0]["booked_time"] == "10:00" and storage.load_my_handicap(path=world) == 18.4


def test_a_booking_pc_caddie_refuses_changes_nothing_and_says_why(world, monkeypatch):
    calls = fake_pccaddie(monkeypatch, fail=booking.BookingError("taken", "no free seat"))
    today = date.today().isoformat()
    assert finished(data.book(SLUG, None, COURSE, today, "10:00")) == {"error": "taken", "message": "no free seat"}
    assert data.overview(SLUG, COURSE)["days"][0]["booked_time"] is None and len(calls) == 1


def test_booking_needs_a_valid_time_a_known_club_and_a_pc_caddie_login(world, monkeypatch):
    calls = fake_pccaddie(monkeypatch, login=False)
    today = date.today().isoformat()
    assert finished(data.book(SLUG, None, COURSE, today, "10:00")) == {"error": "no_login"}
    fake_pccaddie(monkeypatch)
    assert data.book(SLUG, None, COURSE, today, "ten") == {"error": "bad_time"}
    assert data.book(SLUG, None, COURSE, "tomorrow", "10:00") == {"error": "bad_time"}
    assert data.book("nope", None, COURSE, today, "10:00") == {"error": "unknown_club"}
    assert data.cancel("nope", None, COURSE, today, "10:00") == {"error": "unknown_club"}
    assert calls == []


def test_history_lists_the_past_days_newest_first_with_what_was_saved_of_them(world, monkeypatch):
    from src import clock

    monkeypatch.setattr(clock, "now_hhmm", lambda: "12:00")  # today is not over: it stays out of the history
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    for n in (-3, -1):
        storage.save_schedule(_schedule(d(n)), path=world)
    storage.save_confirmed_booking(ConfirmedBooking(date=d(-1), course=COURSE, time="10:10", source="my_reservations", confirmed_at="t"), path=world)
    found = data.overview(SLUG, COURSE, history=True)
    assert found["history"] is True and [day["date"] for day in found["days"]] == [d(-3), d(-1)]  # in calendar order, like the coming days
    newest = found["days"][-1]
    assert newest["history"] is True and newest["booked_time"] == "10:10" and newest["pick"] is None
    assert not any(slot["past"] for slot in newest["slots"])  # a whole past day is the record, not dimmed
    assert [p["name"] for p in next(slot for slot in newest["slots"] if slot["time"] == "10:10")["players"]] == ["Erika Musterfrau", "Jonas Mustermann"]
    assert all(day["date"] >= d(0) for day in data.overview(SLUG, COURSE)["days"])  # the ordinary overview is unchanged


def test_history_takes_in_today_once_daylight_is_over(world, monkeypatch):
    from src import clock

    monkeypatch.setattr(clock, "now_hhmm", lambda: "21:30")
    assert [day["date"] for day in data.overview(SLUG, COURSE, history=True)["days"]] == [date.today().isoformat()]


def test_the_mood_of_a_card_follows_the_weather_code_snow_included():
    from src.webui import panel

    assert [panel.mood_for_code(c) for c in (0, 1, 2, 3, 45, 61, 80, 95, 71, 75, 85, None, 999)] == [
        "clear", "clear", "partly", "overcast", "overcast", "rain", "rain", "rain", "snow", "snow", "snow", "overcast", "overcast",
    ]  # fmt: skip


def test_a_drizzle_code_at_a_small_rain_chance_is_not_drawn_as_a_wet_day():
    from src.webui import panel

    assert panel.mood_for_code(51, 11) == "overcast" and panel.mood_for_code(61, 29) == "overcast"  # forecasts send "drizzle" at 11 %
    assert panel.mood_for_code(51, 40) == "rain" and panel.mood_for_code(63, 80) == "rain" and panel.mood_for_code(61, None) == "rain"
    assert panel.mood_for_code(95, 5) == "rain" and panel.mood_for_code(71, 5) == "snow"  # storms and snow follow the code alone


def test_the_bottom_panel_picks_next_round_best_window_friends_and_best_weather(world, monkeypatch):
    from src import clock
    from src.webui import panel

    monkeypatch.setattr(clock, "now_hhmm", lambda: "08:00")
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    sunny, rainy = _schedule(d(0), rain=5), _schedule(d(1), rain=80)
    for item in (sunny, rainy, _schedule(d(2), rain=10)):
        storage.save_schedule(item, path=world)
    storage.record_seen_players([PlayerSighting(name="Erika Musterfrau", gender="female", member_status="member")], "2026-10-01T10:00:00+00:00", path=world)
    storage.set_player_friend("Erika Musterfrau", True, path=world)
    storage.save_confirmed_booking(ConfirmedBooking(date=d(1), course=COURSE, time="15:00", source="my_reservations", confirmed_at="t"), path=world)
    data._OVERVIEW_CACHE.clear()
    cards = {card["kind"]: card for card in panel.build(SLUG, COURSE)["cards"]}
    assert set(cards) == {"next_round", "best_window", "friends", "best_weather"} or set(cards) == {"next_round", "friends", "best_weather"}
    nxt = cards["next_round"]
    assert (nxt["date"], nxt["time"], nxt["course"]) == (d(1), "15:00", COURSE) and nxt["finish"] > "15:00" and nxt["weather"]["rain"] == 80
    assert nxt["weather"]["mood"] == "clear"  # the fake forecast's code is 1
    friends = cards["friends"]
    assert friends["time"] == "10:10" and [f["name"] for f in friends["friends"]] == ["Erika Musterfrau"] and friends["free"] == 2
    assert cards["best_weather"]["date"] != cards["best_window"]["date"] if "best_window" in cards else cards["best_weather"]["date"] in (d(0), d(2))
    assert cards["best_weather"]["weather"]["rain"] <= 30  # the rainy day loses
    order = [(c["date"], c.get("time", "")) for c in panel.build(SLUG, COURSE)["cards"]]
    assert order == sorted(order)  # the cards run in chronological order


def test_best_weather_is_only_named_when_a_day_is_actually_good(world, monkeypatch):
    from src import clock
    from src.webui import panel

    monkeypatch.setattr(clock, "now_hhmm", lambda: "08:00")
    today = date.today()
    for n, rain in enumerate((45, 80, 35)):  # a wet week: the least bad day is still not good weather
        storage.save_schedule(_schedule((today + timedelta(days=n)).isoformat(), rain=rain), path=world)
    data._OVERVIEW_CACHE.clear()
    assert "best_weather" not in {card["kind"] for card in panel.build(SLUG, COURSE)["cards"]}
    storage.save_schedule(_schedule((today + timedelta(days=3)).isoformat(), rain=12), path=world)  # one dry day brings it back
    data._OVERVIEW_CACHE.clear()
    cards = {card["kind"]: card for card in panel.build(SLUG, COURSE)["cards"]}
    assert cards["best_weather"]["date"] == (today + timedelta(days=3)).isoformat() and cards["best_weather"]["weather"]["rain"] == 12


def test_the_panel_says_when_the_club_lies_south_of_the_equator(world):
    from src.webui import panel

    assert panel.build(SLUG, COURSE)["south"] is False
    club_config.save_club_config(SLUG, {"club_id": CLUB_ID, "name": "Golfclub Beispiel", "default_course": COURSE, "location": {"lat": -33.9, "lon": 18.4}}, club_config.CLUBS_DIR)
    data._OVERVIEW_CACHE.clear()
    assert panel.build(SLUG, COURSE)["south"] is True  # its seasons run the other way


def test_the_bottom_panel_without_anything_to_say_has_no_cards(world):
    from src.webui import panel

    data._OVERVIEW_CACHE.clear()
    assert panel.build(None, None, club_id="0000009", name="Golfclub Fremd")["cards"] == []  # nothing saved for it yet
    assert panel.build("nope", COURSE) == {"error": "unknown_club"}


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
    # a limit names the switch it belongs to (the page shows it only while that is on); no "mark them in the directory" row
    assert fields["field-preferences-avoid_rain_mm"]["depends"] == "field-preferences-avoid_rain"
    assert fields["field-preferences-avoid_wind_kph"]["depends"] == "field-preferences-avoid_wind"
    assert "depends" not in fields["field-preferences-avoid_temp_below_c"] and "field-__friends_hint__" not in fields


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


def test_two_quick_saves_of_different_fields_both_survive(world):
    import threading

    errors = []

    def save(field, value):
        try:
            for _ in range(15):
                assert settings_api.save("settings", {field: value}) == {"ok": True}
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=save, args=("field-units", "imperial")),
        threading.Thread(target=save, args=("field-show_handicaps", False)),
    ]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    saved = global_preferences.load_preferences()
    assert not errors and saved["units"] == "imperial" and saved["show_handicaps"] is False


def test_display_only_changes_keep_the_ranked_picks_but_ranking_changes_drop_them(world):
    data.overview(SLUG, COURSE)
    assert data._OVERVIEW_CACHE
    assert settings_api.save("settings", {"field-units": "imperial"}) == {"ok": True}
    assert settings_api.save("settings", {"field-show_handicaps": False}) == {"ok": True}
    assert data._OVERVIEW_CACHE  # units and handicaps do not change a single pick
    assert settings_api.save("preferences", {"field-availability-min_open_spots": "3"}) == {"ok": True}
    assert not data._OVERVIEW_CACHE


def test_a_bad_number_is_refused_with_a_message_and_saves_nothing(world):
    before = global_preferences.load_preferences()
    result = settings_api.save("preferences", {"field-preferences-avoid_rain_mm": "lots"})
    assert "error" in result
    assert global_preferences.load_preferences() == before


def test_settings_cover_account_display_and_scraping_and_no_ai(world):
    payload = settings_api.settings_payload(CLUB_ID)
    assert [g["key"] for g in payload["groups"]] == ["settings.group.display", "settings.group.scraping"]
    ids = {f["id"] for g in payload["groups"] for f in g["fields"]}
    assert "field-units" in ids and "field-__language__" in ids and "field-__theme__" not in ids
    assert payload["clubs"] == [{"slug": SLUG, "id": CLUB_ID, "name": payload["clubs"][0]["name"]}]  # add and remove only
    assert payload["account"] == {"username": "", "has_password": False}
    assert "ai" not in payload


def test_the_language_setting_applies_and_persists(world, monkeypatch):
    saved = []
    monkeypatch.setattr(i18n, "save_language", lambda lang, config_file=None: saved.append(lang))
    assert settings_api.save("settings", {"field-__language__": "de"}) == {"ok": True}
    assert saved == ["de"] and i18n.get_language() == "de"


def test_club_settings_holes_remove_and_add(world):
    assert settings_api.set_course_holes(SLUG, "Kurzplatz", 9) == {"ok": True}
    assert club_config.load_club_config(SLUG)["course_holes"] == {"Kurzplatz": 9}
    assert settings_api.set_course_holes(SLUG, "Kurzplatz", None) == {"ok": True}
    assert "course_holes" not in club_config.load_club_config(SLUG)
    assert settings_api.set_course_holes("nope", "x", 9) == {"error": "unknown_club"}

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


# ---- themes ------------------------------------------------------------------------------------


def test_the_page_offers_exactly_the_themes_of_the_terminal_and_mac_apps():
    assert sorted(data.theme_names()) == sorted(theme.ALL_THEME_NAMES)


def test_the_theme_is_saved_in_the_shared_setting_and_the_environment_wins(world, tmp_path, monkeypatch):
    monkeypatch.setattr(user_config, "CONFIG_FILE", tmp_path / "config")
    monkeypatch.delenv("TEETIME_MONITOR_THEME", raising=False)
    assert data.saved_theme() is None and data.bootstrap()["theme"] is None  # none saved: the page follows the system
    assert settings_api.set_theme("nord") == {"ok": True}
    assert user_config.load_value("THEME", tmp_path / "config") == "nord"  # the very key theme.py reads
    assert data.bootstrap()["theme"] == "nord" and settings_api.settings_payload(None)["theme"] == "nord"
    monkeypatch.setenv("TEETIME_MONITOR_THEME", "dracula")
    assert data.saved_theme() == "dracula"
    assert settings_api.set_theme("not-a-theme") == {"error": "unknown_theme"}


def test_every_theme_has_the_four_colours_the_page_needs():
    import json

    palettes = json.loads(data.THEMES_FILE.read_text(encoding="utf-8"))
    for name in data.theme_names():
        palette = palettes[name]
        assert set(palette) == {"accent", "background", "surface", "foreground", "dark"}, name
        assert all(palette[key].startswith("#") and len(palette[key]) == 7 for key in ("accent", "background", "surface", "foreground"))


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


def test_search_lists_every_open_time_with_your_rules_for_the_page_to_filter_by(world, monkeypatch):
    from src import clock

    monkeypatch.setattr(clock, "now_hhmm", lambda: "05:00")
    result = tools_api.search_slots(SLUG, None)
    assert result["mine"]["min_open_spots"] == 2 and result["mine"]["weekday_window"] == {"after": "09:00", "before": "17:00"}
    assert len(result["dates"]) == 5  # the days the overview shows (five unless the club says otherwise)
    assert result["dates"][2]["loaded"] and not result["dates"][3]["loaded"]  # three days were scraped
    assert result["dates"][0]["code"] == 1 and result["dates"][3]["code"] is None  # the day's weather for its heading
    assert result["courses"] == [COURSE]
    today = date.today().isoformat()
    times = {s["time"] for s in result["slots"] if s["date"] == today}
    assert {"07:10", "10:00", "15:00"} <= times  # the window is the page's to apply, not the server's
    assert "10:10" in times  # two of four booked: still open
    slot = next(s for s in result["slots"] if s["date"] == today and s["time"] == "10:10")
    assert slot["players"][0]["name"] == "Erika Musterfrau" and slot["players"][0]["gender"] == "female" and slot["open"] == 2
    assert slot["weather"]["temp"] == 18 and slot["flags"] == [] and slot["wet"] is False and slot["gap_ok"] is True
    assert tools_api.search_slots("nope", None) == {"error": "unknown_club"}


def test_search_leaves_out_what_cannot_be_played_and_says_when_the_last_start_is(world, monkeypatch):
    """Tee times that have started are gone, today is once daylight is over, and a start too late to finish before dark
    never counts (sunset 19:00 and a 4 hour round: 15:00 is the last start)."""
    from src import clock

    today, tomorrow = date.today().isoformat(), (date.today() + timedelta(days=1)).isoformat()

    def found():
        return {(s["date"], s["time"]) for s in tools_api.search_slots(SLUG, None)["slots"]}

    monkeypatch.setattr(clock, "now_hhmm", lambda: "05:00")
    assert (today, "15:00") in found() and (today, "15:10") not in found() and (tomorrow, "19:00") not in found()  # too late for a round
    assert tools_api.search_slots(SLUG, None)["last_start"] == "15:00"
    monkeypatch.setattr(clock, "now_hhmm", lambda: "12:00")
    assert (today, "10:10") not in found() and (tomorrow, "07:10") in found()
    monkeypatch.setattr(clock, "now_hhmm", lambda: "19:05")  # past the fixture's sunset (19:00)
    assert not [d for d, _ in found() if d == today] and (tomorrow, "10:00") in found()


def test_search_marks_the_slots_that_cross_your_weather_limits_and_the_ones_with_no_room_around(world, monkeypatch):
    from src import clock

    monkeypatch.setattr(clock, "now_hhmm", lambda: "05:00")
    global_preferences.save_preferences(
        {
            "availability": {"min_open_spots": 1, "weekday_window": {"after": "09:00"}, "weekend_window": {"after": "09:00"}, "buffer_after_minutes": 15},
            "preferences": {"avoid_wind": True, "avoid_wind_kph": 5},
        }
    )
    result = tools_api.search_slots(SLUG, None)
    assert result["mine"]["weather"] == ["wind"] and result["mine"]["gap_after"] == 15
    today = date.today().isoformat()
    by_time = {s["time"]: s for s in result["slots"] if s["date"] == today}
    assert all(s["wet"] and s["flags"] == ["wind"] for s in by_time.values())  # 10 km/h against a limit of 5
    assert by_time["10:00"]["gap_ok"] is False and by_time["10:10"]["gap_ok"] is True  # 10:10 is booked, 10:00 sits right before it


def test_courses_are_off_on_or_where_search_starts_and_off_ones_are_left_out(world, monkeypatch):
    """A 9 hole membership: the 18 hole course is off in Preferences and Search never shows its tee times; with two
    playable courses, the usual one can be where Search starts."""
    from src import clock, club_config, scraper  # noqa: F401
    from src.webui import settings_api

    monkeypatch.setattr(clock, "now_hhmm", lambda: "05:00")
    other = _schedule(date.today().isoformat())
    other.course = "9 Loch"
    storage.save_schedule(other, path=world, authenticated=True)
    data._OVERVIEW_CACHE.clear()
    assert {s["course"] for s in tools_api.search_slots(SLUG, None)["slots"]} == {COURSE, "9 Loch"}
    state = lambda: {c["name"]: c["state"] for c in settings_api.club_courses(SLUG, None)["courses"]}  # noqa: E731
    assert settings_api.club_courses(SLUG, None)["slug"] == SLUG and state() == {COURSE: "on", "9 Loch": "on"}
    assert settings_api.set_course_state(SLUG, COURSE, "off") == {"ok": True}
    assert club_config.load_club_config(SLUG)["excluded_courses"] == [COURSE]  # the club's own file keeps the choice
    result = tools_api.search_slots(SLUG, None)
    assert result["courses"] == ["9 Loch"] and {s["course"] for s in result["slots"]} == {"9 Loch"}
    assert state() == {COURSE: "off", "9 Loch": "on"}  # still listed, so it can be switched back on
    assert settings_api.set_course_state(SLUG, COURSE, "on") == {"ok": True}
    assert "excluded_courses" not in club_config.load_club_config(SLUG)  # nothing left over
    # both playable, the 9 hole one the one Search starts with
    assert settings_api.set_course_state(SLUG, "9 Loch", "default") == {"ok": True}
    assert state() == {COURSE: "on", "9 Loch": "default"} and tools_api.search_slots(SLUG, None)["start_course"] == "9 Loch"
    assert {s["course"] for s in tools_api.search_slots(SLUG, None)["slots"]} == {COURSE, "9 Loch"}  # the other is still there to pick
    assert tools_api.heatmap(SLUG, None, None)["course"] == "9 Loch"  # the Heatmap opens on the same tab
    assert data.overview(SLUG, None)["course"] == "9 Loch"  # and so does the overview, when no course is asked for
    assert next(c for c in data.club_entries() if c["slug"] == SLUG)["default_course"] == "9 Loch"
    assert settings_api.set_course_state(SLUG, "9 Loch", "on") == {"ok": True}
    assert "search_courses" not in club_config.load_club_config(SLUG)
    assert settings_api.set_course_state(SLUG, COURSE, "sometimes") == {"error": "bad_request"}
    assert settings_api.set_course_state("nope", COURSE, "off") == {"error": "unknown_club"}
    assert settings_api.club_courses("nope", None) == {"error": "unknown_club"}


def test_a_course_whose_name_hides_its_holes_asks_for_them_in_preferences(world):
    other = _schedule(date.today().isoformat())
    other.course = "Kurzplatz"
    storage.save_schedule(other, path=world, authenticated=True)
    courses = {c["name"]: c for c in settings_api.club_courses(SLUG, None)["courses"]}
    assert "holes" not in courses[COURSE]  # "18 Loch" says it
    assert courses["Kurzplatz"]["holes"] is None  # worked out, until you say
    settings_api.set_course_holes(SLUG, "Kurzplatz", 9)
    assert {c["name"]: c for c in settings_api.club_courses(SLUG, None)["courses"]}["Kurzplatz"]["holes"] == 9


def test_the_overview_opens_a_club_on_your_standard_course_else_the_old_default_else_one_you_play():
    courses = ["18 Loch", "6 Loch", "9 Loch"]
    assert club_config.opening_course({"search_courses": ["9 Loch", "6 Loch"]}, courses) == "6 Loch"  # natural order
    assert club_config.opening_course({"default_course": "9 Loch"}, courses) == "9 Loch"
    assert club_config.opening_course({"default_course": "Gone", "excluded_courses": ["18 Loch"]}, courses) == "6 Loch"
    assert club_config.opening_course({"search_courses": ["Gone"]}, courses) == "18 Loch"
    assert club_config.opening_course({}, []) is None


def test_the_weather_site_is_saved_in_the_shared_setting(world, tmp_path, monkeypatch):
    monkeypatch.setattr(user_config, "CONFIG_FILE", tmp_path / "config")
    assert data.bootstrap()["weather_site"] is None  # opens nothing until chosen
    assert settings_api.set_weather_site("windy") == {"ok": True}
    assert settings_api.set_weather_site("openmeteo") == {"error": "unknown_site"}  # not offered any more
    assert user_config.load_value("WEATHER_LINK", user_config.CONFIG_FILE) == "windy" and data.bootstrap()["weather_site"] == "windy"
    assert settings_api.set_weather_site("elsewhere") == {"error": "unknown_site"}
    assert settings_api.set_weather_site("") == {"ok": True} and data.saved_weather_site() is None


def test_the_overview_carries_the_clubs_coordinates_for_the_weather_link(world, monkeypatch):
    monkeypatch.setattr(pipeline, "_resolved_config", lambda *a, **k: {"location": {"lat": 47.6612345, "lon": 9.62}})
    assert data.overview(SLUG, COURSE)["location"] == {"lat": 47.6612, "lon": 9.62}
    monkeypatch.setattr(pipeline, "_resolved_config", lambda *a, **k: {})
    assert data.overview(SLUG, COURSE)["location"] is None


def test_each_day_of_the_overview_counts_the_times_that_pass_your_preferences(world, monkeypatch):
    """What Search shows when it opens: 09:00-17:00, two free seats, and a start that still finishes before dark
    (sunset 19:00, a four hour round): 10:00, 10:10 and 15:00 today."""
    from src import clock

    monkeypatch.setattr(clock, "now_hhmm", lambda: "05:00")
    tools_api._COUNTS_CACHE.clear()
    days = data.overview(SLUG, COURSE)["days"]
    assert days[0]["matches"] == 3 and all(day["matches"] == 3 for day in days)  # the fixture's days are alike
    assert tools_api.default_counts(SLUG, None, "Not A Course") == {}  # nothing to say for a course you cannot play


def test_course_tabs_come_in_a_natural_order():
    names = ["18 Loch Tee 1", "Kurzplatz", "6 Loch Platz", "9 Loch Tee 1", "18-Loch Schleife"]
    assert sorted(names, key=tools_api._natural) == ["6 Loch Platz", "9 Loch Tee 1", "18 Loch Tee 1", "18-Loch Schleife", "Kurzplatz"]
    assert tools_api._start_course(["6 Loch Platz", "9 Loch Tee 1"], {"search_courses": ["9 Loch Tee 1"]}) == "9 Loch Tee 1"
    assert tools_api._start_course(["6 Loch Platz", "9 Loch Tee 1"], {"default_course": "18 Loch Tee 1"}, "9 Loch Tee 1") == "9 Loch Tee 1"  # the page's
    assert tools_api._start_course(["6 Loch Platz", "9 Loch Tee 1"], {}) == "6 Loch Platz"
    assert tools_api._start_course([], {}) is None


def test_the_player_directory_lists_and_marks_friends(world):
    listed = tools_api.players(SLUG, None)
    by_name = {p["name"]: p for p in listed["players"]}
    assert by_name["Max Mustermann"]["handicap"] == 18.4 and by_name["Max Mustermann"]["gender"] == "male"
    assert by_name["Erika Musterfrau"]["member_status"] == "guest" and by_name["Erika Musterfrau"]["friend"] is False
    assert tools_api.set_friend(SLUG, None, "Erika Musterfrau", True) == {"ok": True}
    assert {p["name"] for p in tools_api.players(SLUG, None)["players"] if p["friend"]} == {"Erika Musterfrau"}
    assert tools_api.players("nope", None) == {"error": "unknown_club"}


def test_the_player_directory_says_where_each_player_is_booked_on_every_course(world, monkeypatch):
    """What "jump to their tee time" needs: upcoming bookings across all the club's courses, in date order,
    leaving out today's slots that have already started."""
    from src import clock

    monkeypatch.setattr(clock, "now_hhmm", lambda: "12:00")
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    other = _schedule(tomorrow)
    other.course = "9 Loch"
    other.slots = [Slot(time="08:00", booked=1, capacity=4, players=["Max Mustermann"])]
    storage.save_schedule(other, path=world, authenticated=True)
    data._OVERVIEW_CACHE.clear()
    by_name = {p["name"]: p["upcoming"] for p in tools_api.players(SLUG, None)["players"]}
    assert [(h["date"], h["time"], h["course"]) for h in by_name["Max Mustermann"]] == [
        (tomorrow, "07:10", COURSE),  # today's 07:10 has started; tomorrow's has not
        (tomorrow, "08:00", "9 Loch"),
        ((date.today() + timedelta(days=2)).isoformat(), "07:10", COURSE),
    ]
    first = by_name["Erika Musterfrau"][0]
    assert (first["date"], first["time"], first["course"], first["here"]) == (tomorrow, "10:10", COURSE, True)


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


def test_every_screens_route_answers(running, monkeypatch, tmp_path):
    monkeypatch.setattr(user_config, "CONFIG_FILE", tmp_path / "config")
    monkeypatch.setattr(tools_api.pipeline, "_holidays_for_club", lambda config, fetch=True: [])
    today = date.today().isoformat()
    status, strings = _call(running, "GET", "/api/strings")
    assert status == 200 and strings["language"] in ("en", "de") and "settings.title" in strings["strings"]
    assert _call(running, "GET", "/api/preferences")[1]["groups"]
    assert _call(running, "GET", "/api/settings")[1]["clubs"][0]["slug"] == SLUG
    assert _call(running, "POST", "/api/preferences", {"values": {"field-availability-min_open_spots": "2"}})[1] == {"ok": True}
    assert _call(running, "POST", "/api/preferences", {"values": {"field-preferences-avoid_rain_mm": "x"}})[0] == 400
    calls = fake_pccaddie(monkeypatch)
    assert _call(running, "POST", "/api/booking/prepare", {"slug": SLUG, "kind": "book", "course": COURSE, "date": today, "time": "10:00"})[1] == {"ok": True}
    started = _call(running, "POST", "/api/booking", {"slug": SLUG, "course": COURSE, "date": today, "time": "10:00"})[1]
    assert finished(started) == {"ok": True} and _call(running, "GET", f"/api/booking/job?id={started['job']}")[1]["state"] == "ok"
    assert _call(running, "GET", "/api/booking/job?id=nope")[0] == 404
    assert _call(running, "GET", f"/api/overview?slug={SLUG}")[1]["days"][0]["booked_time"] == "10:00"
    assert finished(_call(running, "POST", "/api/booking/cancel", {"slug": SLUG, "course": COURSE, "date": today, "time": "10:00"})[1]) == {"ok": True}
    assert len(calls) == 2
    assert _call(running, "GET", "/api/reservations")[1]["reservations"] == []  # nothing is booked any more
    fake_pccaddie(monkeypatch, fail=booking.BookingError("taken", "gone"))
    started = _call(running, "POST", "/api/booking", {"slug": SLUG, "course": COURSE, "date": today, "time": "10:10"})[1]
    assert finished(started) == {"error": "taken", "message": "gone"}
    status, refused = _call(running, "GET", f"/api/booking/job?id={started['job']}")
    assert status == 200 and refused["state"] == "failed" and refused["error"] == "taken"  # the page can tell it from a crash
    status, found = _call(running, "GET", f"/api/search/slots?slug={SLUG}")
    assert status == 200 and found["slots"] and found["mine"]["min_open_spots"] == 2
    assert _call(running, "GET", f"/api/players?slug={SLUG}")[1]["players"]
    assert _call(running, "POST", "/api/players/friend", {"slug": SLUG, "name": "Max Mustermann", "friend": True})[1] == {"ok": True}
    assert _call(running, "GET", f"/api/heatmap?slug={SLUG}")[0] == 200
    assert _call(running, "GET", f"/api/heatmap?slug={SLUG}&course=Not+A+Course")[1]["course"] == COURSE  # another club's course: its own default
    assert _call(running, "GET", "/api/directory?q=zzzz")[1]["results"] == []
    assert _call(running, "POST", "/api/weather-site", {"name": "meteoblue"})[1] == {"ok": True}
    assert _call(running, "POST", "/api/weather-site", {"name": "nope"})[0] == 400
    assert _call(running, "POST", "/api/club/default-course", {"slug": SLUG, "course": COURSE})[0] == 404  # gone: Preferences decides
    assert _call(running, "POST", "/api/club/add", {"club_id": "0000003", "name": "Drei"})[1]["ok"] is True
    assert _call(running, "POST", "/api/club/remove", {"club_id": "0000003"})[1]["ok"] is True
    assert _call(running, "POST", "/api/club/remove", {"club_id": "0000003"})[0] == 404
    assert _call(running, "GET", "/api/overview")[0] == 400
    assert _call(running, "POST", "/api/theme", {"name": "nord"})[1] == {"ok": True}
    assert _call(running, "POST", "/api/theme", {"name": "nope"})[0] == 400
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


def test_the_tournament_calendar_is_read_with_the_saved_login_and_kept_for_a_while(running, monkeypatch):
    from src import scraper
    from src.models import Tournament

    monkeypatch.setattr(club_config, "resolve_credentials", lambda key: ("me", "secret"))
    data._TOURNAMENT_CACHE.clear()
    reads = []

    def fake(club_id, user, password):
        reads.append(club_id)
        return [Tournament(id="5", date="2026-11-02", time="17:00", name="Autumn Cup", holes=18, guests=True, deadline="2026-11-02 10:00", register_open=True)]

    monkeypatch.setattr(scraper, "scrape_tournaments", fake)
    status, first = _call(running, "GET", f"/api/tournaments?slug={SLUG}")
    [item] = first["tournaments"]
    assert status == 200 and first["problem"] is None and (item["date"], item["name"], item["register_open"]) == ("2026-11-02", "Autumn Cup", True)
    assert item["url"] == f"https://www.pccaddie.net/clubs/{CLUB_ID}/app.php?cat=ts_calendar&sub=detail&id=5"  # no entry list link
    _call(running, "GET", f"/api/tournaments?slug={SLUG}")
    assert len(reads) == 1  # the second look comes from the half hour cache
    _call(running, "GET", f"/api/tournaments?slug={SLUG}&refresh=1")
    assert len(reads) == 2
    assert _call(running, "GET", "/api/tournaments?slug=nope")[0] == 404


def test_a_tournament_calendar_that_cannot_be_read_says_why_and_keeps_the_last_list(world, monkeypatch):
    import httpx

    from src import scraper
    from src.models import Tournament

    data._TOURNAMENT_CACHE.clear()
    monkeypatch.setattr(club_config, "resolve_credentials", lambda key: ("", ""))
    assert data.tournaments(SLUG, None) == {"tournaments": [], "problem": "no_login"}
    monkeypatch.setattr(club_config, "resolve_credentials", lambda key: ("me", "secret"))
    for failure, problem in ((scraper.LoginError("no"), "login"), (httpx.ConnectError("down"), "network"), (NotImplementedError("markup"), "parsing")):
        monkeypatch.setattr(scraper, "scrape_tournaments", lambda *args, failure=failure: (_ for _ in ()).throw(failure))
        assert data.tournaments(SLUG, None, refresh=True) == {"tournaments": [], "problem": problem}
    monkeypatch.setattr(scraper, "scrape_tournaments", lambda *args: [Tournament(id="1", date="2026-11-02", time=None, name="Cup")])
    assert len(data.tournaments(SLUG, None, refresh=True)["tournaments"]) == 1
    monkeypatch.setattr(scraper, "scrape_tournaments", lambda *args: (_ for _ in ()).throw(httpx.ConnectError("down")))
    again = data.tournaments(SLUG, None, refresh=True)
    assert again["problem"] == "network" and len(again["tournaments"]) == 1  # the old list stays on screen


def test_a_tournament_carries_the_stored_forecast_for_its_start_time_when_the_day_was_loaded(world, monkeypatch):
    from src import scraper
    from src.models import Tournament

    today = date.today()
    soon, later = (today + timedelta(days=1)).isoformat(), (today + timedelta(days=40)).isoformat()
    storage.save_schedule(_schedule(soon, rain=60), path=world)  # one loaded day; nothing is fetched for the other
    data._TOURNAMENT_CACHE.clear()
    monkeypatch.setattr(club_config, "resolve_credentials", lambda key: ("me", "secret"))
    monkeypatch.setattr(
        scraper, "scrape_tournaments",
        lambda *args: [Tournament(id="1", date=soon, time="09:30", name="Near Cup"), Tournament(id="2", date=later, time="09:30", name="Far Cup"), Tournament(id="3", date=soon, time=None, name="No Time")],
    )
    near, far, no_time = data.tournaments(SLUG, None, refresh=True)["tournaments"]
    assert near["weather"]["temp"] == 18 and near["weather"]["rain"] == 60 and near["weather"]["code"] == 1  # the 09:00 point
    assert far["weather"] is None  # beyond the days that were loaded: no guess
    assert no_time["weather"] is not None  # ten o'clock


def test_a_day_with_a_tournament_block_says_so_and_a_routine_event_does_not(world):
    today = date.today()
    championship, group = _schedule(today.isoformat()), _schedule((today + timedelta(days=1)).isoformat())
    championship.events = ["Club Championship"]
    championship.slots[1].block_reason = "Club Championship"
    group.events = ["Ladies Afternoon"]  # a weekly group: it blocks one time and its name does not read like a competition
    group.slots[1].block_reason = "Ladies Afternoon"
    for item in (championship, group):
        storage.save_schedule(item, path=world)
    data._OVERVIEW_CACHE.clear()
    days = {day["date"]: day for day in data.overview(SLUG, COURSE)["days"]}
    assert days[today.isoformat()]["tournament_day"] is True  # its blocked times link to the calendar
    assert days[(today + timedelta(days=1)).isoformat()]["tournament_day"] is False


def test_the_page_addresses_its_stylesheet_and_script_by_content(running):
    """A new version is a new address, so a browser cannot pair a fresh script with a stylesheet it kept (2026-10-16)."""
    import re

    def get(path):
        connection = http.client.HTTPConnection("127.0.0.1", running.port, timeout=20)
        connection.request("GET", path, headers={"Cookie": f"{server.COOKIE_NAME}={running.token}"})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body

    status, page = get("/")
    assert status == 200
    css = re.search(rb'href="/style\.css\?v=([0-9a-f]{12})"', page)
    js = re.search(rb'src="/app\.js\?v=([0-9a-f]{12})"', page)
    assert css and js
    assert css.group(1) == js.group(1) == server._release()  # one version for every file of the page
    status, sheet = get("/style.css?v=" + css.group(1).decode())
    assert status == 200 and sheet == (server.STATIC_DIR / "style.css").read_bytes()  # the query does not change which file comes back
    status, script = get("/app.js?v=" + js.group(1).decode())
    imports = re.findall(rb"from '(/[\w./-]+\.js[^']*)'", script)
    assert imports and all(path.endswith(b"?v=" + js.group(1)) for path in imports), imports  # and so are the modules it imports
    status, lib = get("/search.js?v=" + js.group(1).decode())
    assert b"from '/lib.js?v=" + js.group(1) + b"'" in lib


def test_the_player_list_is_one_for_every_club_and_names_the_home_club(world):
    from src.webui import tools_api

    other = world.parent / "0000002.db"  # a second club in the same data folder
    storage.record_seen_players([PlayerSighting(name="Lena Beispiel", gender="female", member_status="guest", handicap=12.0)], "2026-10-02T10:00:00+00:00", path=other)
    storage.set_player_friend("Lena Beispiel", True, path=other)  # marked while looking at the other club
    players = {p["name"]: p for p in tools_api.players(SLUG, None)["players"]}
    assert players["Lena Beispiel"]["friend"] is True and players["Lena Beispiel"]["home_clubs"] == []  # a guest: club unknown
    assert players["Max Mustermann"]["home_clubs"] == ["Golfclub Beispiel"]  # a member here, by the saved club's name
    assert "Lena Beispiel" in storage.load_friend_names(world)  # and a friend at this club too


def test_a_players_next_tee_times_come_from_every_saved_club_each_with_its_club(world):
    from src.webui import tools_api

    club_config.save_club_config("golfclub-nachbar", {"club_id": "0000002", "name": "Golfclub Nachbar", "default_course": "9 Loch Platz"}, club_config.CLUBS_DIR)
    other = world.parent / "0000002.db"
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    slots = [Slot(time="10:00", booked=1, capacity=4, players=["Erika Musterfrau"])]
    storage.save_schedule(Schedule(date=tomorrow, course="9 Loch Platz", slots=slots, weather=[], sun_times=SunTimes("07:00", "19:00"), events=[]), path=other, authenticated=True)
    hits = {p["name"]: p["upcoming"] for p in tools_api.players(SLUG, None)["players"]}
    away = [hit for hit in hits["Erika Musterfrau"] if not hit["here"]]
    assert away == [{"date": tomorrow, "time": "10:00", "course": "9 Loch Platz", "club": "Golfclub Nachbar", "slug": "golfclub-nachbar", "club_id": "0000002", "here": False}]
    assert all(hit["here"] for hit in hits["Max Mustermann"])  # this club's own times stay "here"
    seen_from_there = {p["name"]: p["upcoming"] for p in tools_api.players("golfclub-nachbar", None)["players"]}
    assert any(hit["here"] and hit["club"] == "Golfclub Nachbar" for hit in seen_from_there["Erika Musterfrau"])
