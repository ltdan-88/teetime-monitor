import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src import storage
from src.models import ConfirmedBooking, PlayerSighting, Schedule, Slot, SunTimes, WeatherPoint
from src.storage import (
    acknowledge_booking_changes,
    distinct_scraped_dates,
    first_confirmed_at,
    init_db,
    last_scraped_at,
    load_all_confirmed_bookings,
    load_confirmed_booking,
    load_friend_names,
    load_known_handicaps,
    load_known_players,
    load_latest_schedule,
    load_location,
    load_my_handicap,
    load_unacknowledged_booking_changes,
    record_seen_players,
    save_booking_change,
    save_confirmed_booking,
    save_location,
    save_my_handicap,
    save_schedule,
    set_player_friend,
)


def test_init_db_creates_a_missing_parent_directory(tmp_path):
    # Regression test for a real bug found live 2026-09-07: opening the TUI for the
    # very first time, before scrape_once.py had ever run to create data/ itself,
    # crashed with "OperationalError: unable to open database file" -- sqlite3
    # creates the database *file* but not a missing directory in its path.
    db = tmp_path / "data" / "0000001.db"
    assert not db.parent.exists()

    init_db(db)

    assert db.exists()


def test_load_latest_schedule_returns_none_when_never_scraped(tmp_path):
    db = tmp_path / "teetime.db"
    assert load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db) is None


def test_last_scraped_at_returns_none_when_never_scraped(tmp_path):
    db = tmp_path / "teetime.db"
    assert last_scraped_at("18 Loch Tee 1", "2026-09-06", path=db) is None


def test_last_scraped_at_returns_timestamp_of_most_recent_scrape(tmp_path):
    db = tmp_path / "teetime.db"
    schedule = Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[])

    save_schedule(schedule, path=db)
    first = last_scraped_at("18 Loch Tee 1", "2026-09-06", path=db)
    assert first is not None

    save_schedule(schedule, path=db)
    second = last_scraped_at("18 Loch Tee 1", "2026-09-06", path=db)
    assert second is not None
    assert second >= first  # ISO 8601 strings sort chronologically


def test_save_and_load_schedule_round_trips_slots(tmp_path):
    db = tmp_path / "teetime.db"
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="06:00", booked=0, capacity=4, players=[]),
            Slot(time="06:40", booked=2, capacity=4, players=[]),
            Slot(time="15:30", booked=4, capacity=4, block_reason="Golf Beginner Kurs"),
        ],
        # events is its own field, populated by scraper._event_names() before a real
        # Schedule is ever built -- not re-derived from block_reason here any more
        # (see load_latest_schedule()'s own docstring for why that used to be a real
        # bug: a Slot never carries which data-status produced its block_reason, so
        # storage.py itself could never tell a genuine event apart from an
        # advance-booking notice after the fact).
        events=["Golf Beginner Kurs"],
    )

    save_schedule(schedule, path=db)
    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db)

    assert loaded is not None
    assert loaded.date == "2026-09-06"
    assert loaded.course == "18 Loch Tee 1"
    assert [s.time for s in loaded.slots] == ["06:00", "06:40", "15:30"]
    assert loaded.slots[1].booked == 2
    assert loaded.slots[2].block_reason == "Golf Beginner Kurs"
    assert loaded.events == ["Golf Beginner Kurs"]


def test_load_latest_schedule_never_re_derives_events_from_block_reason(tmp_path):
    # The real bug this fixed (2026-09-09, found while splitting the overview's
    # Weather/Events columns): a Slot's block_reason alone can't tell a genuine
    # block-time event apart from a disable-time advance-booking notice -- so
    # events has to be exactly what was actually saved, never reconstructed from
    # whatever block_reason values happen to be sitting on the loaded slots.
    db = tmp_path / "teetime.db"
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="18:00", booked=4, capacity=4, block_reason="4 Tage im Voraus ab 20 Uhr buchbar (KP)")],
        events=[],  # explicitly not an event -- an advance-booking notice
    )

    save_schedule(schedule, path=db)
    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db)

    assert loaded.slots[0].block_reason == "4 Tage im Voraus ab 20 Uhr buchbar (KP)"
    assert loaded.events == []


def test_load_latest_schedule_events_empty_for_a_row_saved_before_the_column_existed(tmp_path):
    db = tmp_path / "old.db"
    save_schedule(Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[]), path=db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE scrapes SET events = NULL")

    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db)

    assert loaded.events == []


def test_save_and_load_schedule_round_trips_players_and_weather(tmp_path):
    db = tmp_path / "teetime.db"
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="08:00", booked=1, capacity=4, players=["Max Mustermann"])],
        weather=[
            WeatherPoint(
                time="08:00",
                precipitation_probability=10.0,
                precipitation_mm=0.0,
                wind_speed_kph=12.5,
                temperature_c=18.5,
                weather_code=61,
            )
        ],
    )

    save_schedule(schedule, path=db)
    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db)

    assert loaded.slots[0].players == ["Max Mustermann"]
    assert len(loaded.weather) == 1
    assert loaded.weather[0].precipitation_probability == 10.0
    assert loaded.weather[0].wind_speed_kph == 12.5
    assert loaded.weather[0].temperature_c == 18.5
    assert loaded.weather[0].weather_code == 61


# --- sun_times persistence (2026-09-08, direct feedback: "don't forget about the
# sunrise and sunset times" -- surfaced that these were fetched at scrape time and
# then silently dropped, never actually persisted at all) --------------------------


def test_save_and_load_schedule_round_trips_sun_times(tmp_path):
    db = tmp_path / "teetime.db"
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[],
        sun_times=SunTimes(sunrise="06:42", sunset="19:58"),
    )

    save_schedule(schedule, path=db)
    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db)

    assert loaded.sun_times == SunTimes(sunrise="06:42", sunset="19:58")


def test_load_latest_schedule_sun_times_is_none_when_never_fetched(tmp_path):
    # A schedule saved before location was configured for weather (or before this
    # feature existed at all) -- must not crash, and must not fabricate a fact
    # nothing actually confirmed.
    db = tmp_path / "teetime.db"
    schedule = Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[])

    save_schedule(schedule, path=db)
    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db)

    assert loaded.sun_times is None


def test_init_db_migrates_a_scrapes_table_from_before_sun_times_existed(tmp_path):
    # Real, non-hypothetical case: this developer's own existing data/*.db files
    # predate the sunrise/sunset columns. CREATE TABLE IF NOT EXISTS is a no-op
    # against an already-existing table, so init_db() has to actively add the
    # missing columns rather than silently leaving old databases behind (which
    # would have meant re-scraping to get sun_times at all, impossible for any
    # date pc caddie has already stopped publishing).
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE scrapes (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "course TEXT NOT NULL, date TEXT NOT NULL, scraped_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO scrapes (course, date, scraped_at) VALUES (?, ?, ?)",
            ("18 Loch Tee 1", "2026-09-01", "2026-09-01T10:00:00+00:00"),
        )

    init_db(db)

    # The pre-existing row survived the migration untouched (just gained NULL
    # sunrise/sunset/events, not lost or duplicated). `events` joined the same
    # migration list a day later (2026-09-09), same reasoning.
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT course, date, sunrise, sunset, events FROM scrapes").fetchall()
    assert rows == [("18 Loch Tee 1", "2026-09-01", None, None, None)]

    # And a schedule saved after the migration round-trips sun_times normally.
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[],
        sun_times=SunTimes(sunrise="06:42", sunset="19:58"),
    )
    save_schedule(schedule, path=db)
    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db)
    assert loaded.sun_times == SunTimes(sunrise="06:42", sunset="19:58")


# --- weather_code persistence (2026-09-11, direct feedback: "I also would like
# icons for when it is sunny, overcast, foggy, snowing etc.") ---------------------


def test_load_latest_schedule_weather_code_is_none_for_a_row_saved_before_the_column_existed(tmp_path):
    db = tmp_path / "old.db"
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[],
        weather=[WeatherPoint(time="08:00", temperature_c=18.5)],
    )
    save_schedule(schedule, path=db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE weather_points SET weather_code = NULL")

    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db)

    assert loaded.weather[0].weather_code is None


def test_init_db_migrates_a_weather_points_table_from_before_weather_code_existed(tmp_path):
    # Real, non-hypothetical case, same as the scrapes-table migration above: this
    # developer's own existing data/*.db files predate weather_code. CREATE TABLE IF
    # NOT EXISTS is a no-op against an already-existing table, so init_db() has to
    # actively add the missing column.
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE scrapes (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "course TEXT NOT NULL, date TEXT NOT NULL, scraped_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE weather_points (scrape_id INTEGER NOT NULL, time TEXT NOT NULL, "
            "precipitation_probability REAL, precipitation_mm REAL, wind_speed_kph REAL, temperature_c REAL)"
        )
        cursor = conn.execute(
            "INSERT INTO scrapes (course, date, scraped_at) VALUES (?, ?, ?)",
            ("18 Loch Tee 1", "2026-09-01", "2026-09-01T10:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO weather_points (scrape_id, time, temperature_c) VALUES (?, ?, ?)",
            (cursor.lastrowid, "08:00", 18.5),
        )

    init_db(db)

    # The pre-existing row survived the migration untouched (just gained a NULL
    # weather_code, not lost or duplicated).
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT time, temperature_c, weather_code FROM weather_points").fetchall()
    assert rows == [("08:00", 18.5, None)]

    # And a schedule saved after the migration round-trips weather_code normally.
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[],
        weather=[WeatherPoint(time="08:00", temperature_c=18.5, weather_code=0)],
    )
    save_schedule(schedule, path=db)
    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db)
    assert loaded.weather[0].weather_code == 0


def test_save_schedule_never_overwrites_previous_scrape(tmp_path):
    db = tmp_path / "teetime.db"
    first = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="06:00", booked=0, capacity=4)],
    )
    second = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="06:00", booked=2, capacity=4)],
    )

    save_schedule(first, path=db)
    save_schedule(second, path=db)

    # The latest scrape wins for load_latest_schedule...
    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db)
    assert loaded.slots[0].booked == 2

    # ...but the earlier scrape's row is still there, not overwritten (history matters
    # for Phase 5 analytics and booking_watch.py's diffing).
    import sqlite3

    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM scrapes").fetchone()[0]
    assert count == 2


def test_schedules_for_different_courses_or_dates_dont_collide(tmp_path):
    db = tmp_path / "teetime.db"
    save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="06:00", booked=0, capacity=4)]),
        path=db,
    )
    save_schedule(
        Schedule(date="2026-09-06", course="9 Loch Tee 1", slots=[Slot(time="06:00", booked=4, capacity=4)]),
        path=db,
    )
    save_schedule(
        Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="06:00", booked=1, capacity=4)]),
        path=db,
    )

    assert load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=db).slots[0].booked == 0
    assert load_latest_schedule("9 Loch Tee 1", "2026-09-06", path=db).slots[0].booked == 4
    assert load_latest_schedule("18 Loch Tee 1", "2026-09-07", path=db).slots[0].booked == 1


def test_load_confirmed_booking_returns_none_when_never_confirmed(tmp_path):
    db = tmp_path / "teetime.db"
    assert load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=db) is None


def test_save_and_load_confirmed_booking_round_trips(tmp_path):
    db = tmp_path / "teetime.db"
    booking = ConfirmedBooking(
        date="2026-09-06",
        course="18 Loch Tee 1",
        time="14:00",
        holes=18,
        source="my_reservations",
        confirmed_at="2026-09-06T09:00:00+00:00",
    )
    save_confirmed_booking(booking, path=db)

    loaded = load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=db)
    assert loaded == booking


def test_load_confirmed_booking_returns_most_recent_when_reconfirmed(tmp_path):
    db = tmp_path / "teetime.db"
    save_confirmed_booking(
        ConfirmedBooking(
            date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="manual", confirmed_at="t1"
        ),
        path=db,
    )
    save_confirmed_booking(
        ConfirmedBooking(
            date="2026-09-06",
            course="18 Loch Tee 1",
            time="14:00",
            holes=18,
            source="my_reservations",
            confirmed_at="t2",
        ),
        path=db,
    )

    loaded = load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=db)
    assert loaded.source == "my_reservations"
    assert loaded.confirmed_at == "t2"


def test_first_confirmed_at_returns_none_when_never_confirmed(tmp_path):
    db = tmp_path / "teetime.db"
    assert first_confirmed_at("18 Loch Tee 1", "2026-09-06", "14:00", path=db) is None


def test_first_confirmed_at_returns_the_earliest_row_not_the_latest(tmp_path):
    # A re-sync every scrape pass inserts a fresh row with confirmed_at reset to "now"
    # (scraper.py never overwrites -- see the module docstring), so
    # load_confirmed_booking() (latest row) is the wrong thing for booking_watch.py to
    # anchor its "was this already confirmed before the baseline scrape" check on.
    db = tmp_path / "teetime.db"
    save_confirmed_booking(
        ConfirmedBooking(
            date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="my_reservations", confirmed_at="t1"
        ),
        path=db,
    )
    save_confirmed_booking(
        ConfirmedBooking(
            date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="my_reservations", confirmed_at="t2"
        ),
        path=db,
    )

    assert first_confirmed_at("18 Loch Tee 1", "2026-09-06", "14:00", path=db) == "t1"


def test_first_confirmed_at_scoped_to_the_exact_time(tmp_path):
    db = tmp_path / "teetime.db"
    save_confirmed_booking(
        ConfirmedBooking(
            date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="manual", confirmed_at="t1"
        ),
        path=db,
    )

    assert first_confirmed_at("18 Loch Tee 1", "2026-09-06", "14:30", path=db) is None


def test_confirmed_booking_not_playing_has_none_time(tmp_path):
    db = tmp_path / "teetime.db"
    save_confirmed_booking(
        ConfirmedBooking(date="2026-09-06", course="18 Loch Tee 1", time=None, source="manual", confirmed_at="t1"),
        path=db,
    )
    loaded = load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=db)
    assert loaded.time is None


def test_distinct_scraped_dates_empty_when_never_scraped(tmp_path):
    db = tmp_path / "teetime.db"
    assert distinct_scraped_dates("18 Loch Tee 1", path=db) == []


def test_distinct_scraped_dates_returns_sorted_unique_dates(tmp_path):
    db = tmp_path / "teetime.db"
    for date in ["2026-09-08", "2026-09-06", "2026-09-06", "2026-09-07"]:
        save_schedule(Schedule(date=date, course="18 Loch Tee 1", slots=[]), path=db)

    assert distinct_scraped_dates("18 Loch Tee 1", path=db) == ["2026-09-06", "2026-09-07", "2026-09-08"]


def test_distinct_scraped_dates_only_returns_matching_course(tmp_path):
    db = tmp_path / "teetime.db"
    save_schedule(Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[]), path=db)
    save_schedule(Schedule(date="2026-09-06", course="9 Loch Tee 1", slots=[]), path=db)

    assert distinct_scraped_dates("9 Loch Tee 1", path=db) == ["2026-09-06"]


def test_load_all_confirmed_bookings_empty_when_none_confirmed(tmp_path):
    db = tmp_path / "teetime.db"
    assert load_all_confirmed_bookings(path=db) == []


def test_load_all_confirmed_bookings_spans_every_course(tmp_path):
    db = tmp_path / "teetime.db"
    save_confirmed_booking(
        ConfirmedBooking(date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="manual", confirmed_at="t1"),
        path=db,
    )
    save_confirmed_booking(
        ConfirmedBooking(date="2026-09-08", course="9 Loch Tee 1", time="09:00", source="manual", confirmed_at="t2"),
        path=db,
    )

    bookings = load_all_confirmed_bookings(path=db)
    assert [(b.date, b.course) for b in bookings] == [("2026-09-06", "18 Loch Tee 1"), ("2026-09-08", "9 Loch Tee 1")]


def test_load_all_confirmed_bookings_uses_latest_confirmation_per_course_date(tmp_path):
    db = tmp_path / "teetime.db"
    save_confirmed_booking(
        ConfirmedBooking(date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="manual", confirmed_at="t1"),
        path=db,
    )
    save_confirmed_booking(
        ConfirmedBooking(
            date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="my_reservations", confirmed_at="t2"
        ),
        path=db,
    )

    bookings = load_all_confirmed_bookings(path=db)
    assert len(bookings) == 1
    assert bookings[0].source == "my_reservations"


def test_load_unacknowledged_booking_changes_empty_when_none_saved(tmp_path):
    db = tmp_path / "teetime.db"
    assert load_unacknowledged_booking_changes(path=db) == []


def test_save_and_load_booking_change_round_trips(tmp_path):
    db = tmp_path / "teetime.db"
    save_booking_change(
        course="18 Loch Tee 1",
        date="2026-09-06",
        time="14:00",
        kind="party_grew",
        message="1 more player joined your 14:00 tee time since you booked",
        path=db,
    )

    changes = load_unacknowledged_booking_changes(path=db)
    assert len(changes) == 1
    assert changes[0]["course"] == "18 Loch Tee 1"
    assert changes[0]["kind"] == "party_grew"
    assert "1 more player" in changes[0]["message"]
    assert changes[0]["params"] == {}  # not passed -- defaults to empty, not an error


def test_save_booking_change_round_trips_params(tmp_path):
    db = tmp_path / "teetime.db"
    save_booking_change(
        course="18 Loch Tee 1",
        date="2026-09-06",
        time="14:00",
        kind="party_grew",
        message="2 more players joined your 14:00 tee time since you booked",
        params={"count": 2, "time": "14:00"},
        path=db,
    )

    changes = load_unacknowledged_booking_changes(path=db)
    assert changes[0]["params"] == {"count": 2, "time": "14:00"}


def test_acknowledge_booking_changes_hides_them(tmp_path):
    db = tmp_path / "teetime.db"
    save_booking_change(
        course="18 Loch Tee 1", date="2026-09-06", time="14:00", kind="party_grew", message="msg", path=db
    )
    changes = load_unacknowledged_booking_changes(path=db)

    acknowledge_booking_changes([c["id"] for c in changes], path=db)

    assert load_unacknowledged_booking_changes(path=db) == []


def test_acknowledge_booking_changes_handles_empty_list(tmp_path):
    db = tmp_path / "teetime.db"
    acknowledge_booking_changes([], path=db)  # must not raise, e.g. on an empty db
    assert load_unacknowledged_booking_changes(path=db) == []


# save_location/load_location -- added 2026-09-08, direct feedback: "I don't want to
# first save a club in order to see weather forecast." A club's location now lives in
# its own per-club db rather than clubs/*.yaml, so it works whether or not the club
# was ever favorited.


def test_load_location_is_none_for_a_club_never_geocoded(tmp_path):
    db = tmp_path / "teetime.db"
    save_schedule(Schedule(course="18 Loch Tee 1", date="2026-09-08", slots=[]), path=db)

    assert load_location(path=db) is None


def test_load_location_is_none_when_the_db_file_does_not_exist_yet(tmp_path):
    db = tmp_path / "never-scraped.db"

    assert load_location(path=db) is None


def test_save_and_load_location_round_trips(tmp_path):
    db = tmp_path / "teetime.db"

    save_location({"lat": 50.1234567, "lon": 8.1234567}, path=db)

    assert load_location(path=db) == {"lat": 50.1234567, "lon": 8.1234567}


def test_save_location_overwrites_a_previous_value(tmp_path):
    db = tmp_path / "teetime.db"
    save_location({"lat": 1.0, "lon": 2.0}, path=db)

    save_location({"lat": 3.0, "lon": 4.0}, path=db)

    assert load_location(path=db) == {"lat": 3.0, "lon": 4.0}


# --- my_handicap (2026-09-27, direct follow-up: "would it make sense to have the
# option to choose to play with similar HCP or with better HCP") --------------------


def test_load_my_handicap_is_none_when_never_synced(tmp_path):
    db = tmp_path / "teetime.db"
    save_schedule(Schedule(course="18 Loch Tee 1", date="2026-09-08", slots=[]), path=db)

    assert load_my_handicap(path=db) is None


def test_load_my_handicap_is_none_when_the_db_file_does_not_exist_yet(tmp_path):
    assert load_my_handicap(path=tmp_path / "never-scraped.db") is None


def test_save_and_load_my_handicap_round_trips(tmp_path):
    db = tmp_path / "teetime.db"

    save_my_handicap(43.8, path=db)

    assert load_my_handicap(path=db) == 43.8


def test_save_my_handicap_overwrites_a_previous_value(tmp_path):
    db = tmp_path / "teetime.db"
    save_my_handicap(43.8, path=db)

    save_my_handicap(41.2, path=db)

    assert load_my_handicap(path=db) == 41.2


# --- Weather falls back to an earlier scrape when the latest has none (2026-09-17).
# Direct report: "sometimes I noticed that weather data wasn't pulled for every day in
# the overview." Open-Meteo was unreachable for ~7 hours; every scrape in that window
# saved a schedule with zero weather points, and each became "the latest", blanking the
# column even though good weather sat one row above. ------------------------------


def _schedule(date, weather=None, sun=None):
    return Schedule(
        date=date,
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=1, capacity=4)],
        weather=weather or [],
        sun_times=sun,
    )


_WX = [WeatherPoint(time="09:00", precipitation_probability=10.0, precipitation_mm=0.0,
                    wind_speed_kph=5.0, temperature_c=18.0, weather_code=1)]


def test_load_latest_schedule_falls_back_to_earlier_weather(tmp_path):
    path = tmp_path / "club.db"
    save_schedule(_schedule("2026-09-19", weather=_WX, sun=SunTimes(sunrise="07:00", sunset="19:30")), path=path)
    save_schedule(_schedule("2026-09-19"), path=path)  # weather fetch failed this pass

    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-19", path=path)

    assert [point.temperature_c for point in loaded.weather] == [18.0]
    # Sun times come along with it -- they're fetched in the same step.
    assert loaded.sun_times == SunTimes(sunrise="07:00", sunset="19:30")


def test_load_latest_schedule_still_takes_slots_from_the_newest_scrape(tmp_path):
    """Only weather falls back. Occupancy must always be the freshest -- that's the
    whole point of re-scraping."""
    path = tmp_path / "club.db"
    save_schedule(_schedule("2026-09-19", weather=_WX), path=path)
    newest = Schedule(
        date="2026-09-19",
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=4, capacity=4)],  # filled up since
        weather=[],
    )
    save_schedule(newest, path=path)

    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-19", path=path)

    assert loaded.slots[0].booked == 4  # newest occupancy, not the older scrape's 1
    assert loaded.weather  # but weather recovered from the older one


def test_load_latest_schedule_prefers_the_latest_weather_when_it_has_some(tmp_path):
    path = tmp_path / "club.db"
    save_schedule(_schedule("2026-09-19", weather=_WX), path=path)
    fresher = [WeatherPoint(time="09:00", precipitation_probability=90.0, precipitation_mm=4.0,
                            wind_speed_kph=30.0, temperature_c=9.0, weather_code=61)]
    save_schedule(_schedule("2026-09-19", weather=fresher), path=path)

    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-19", path=path)

    assert [point.temperature_c for point in loaded.weather] == [9.0]  # no stale fallback


def test_load_latest_schedule_weather_fallback_is_scoped_to_the_same_course_and_date(tmp_path):
    path = tmp_path / "club.db"
    save_schedule(_schedule("2026-09-18", weather=_WX), path=path)  # a different day
    save_schedule(
        Schedule(date="2026-09-19", course="9 Loch Tee 1",
                 slots=[Slot(time="09:00", booked=0, capacity=4)], weather=_WX),
        path=path,
    )  # a different course
    save_schedule(_schedule("2026-09-19"), path=path)  # no weather, and nothing to inherit

    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-19", path=path)

    assert loaded.weather == []  # must not borrow another day's or another course's


def test_load_latest_schedule_without_any_weather_ever_is_still_fine(tmp_path):
    path = tmp_path / "club.db"
    save_schedule(_schedule("2026-09-19"), path=path)

    loaded = load_latest_schedule("18 Loch Tee 1", "2026-09-19", path=path)

    assert loaded.weather == []
    assert loaded.slots[0].time == "09:00"


# --- known_players (2026-09-27) -------------------------------------------------------


def _sighting(name: str, gender: str | None = None, member_status: str | None = None,
              handicap: float | None = None) -> PlayerSighting:
    return PlayerSighting(name=name, gender=gender, member_status=member_status, handicap=handicap)


def test_record_seen_players_creates_new_rows(tmp_path):
    path = tmp_path / "club.db"
    record_seen_players(
        [_sighting("Max Mustermann"), _sighting("Erika Mustermann")], "2026-09-27T10:00:00+00:00", path=path
    )

    players = {p.name: p for p in load_known_players(path=path)}
    assert set(players) == {"Max Mustermann", "Erika Mustermann"}
    assert players["Max Mustermann"].first_seen == "2026-09-27T10:00:00+00:00"
    assert players["Max Mustermann"].last_seen == "2026-09-27T10:00:00+00:00"
    assert players["Max Mustermann"].is_friend is False


def test_record_seen_players_with_no_names_is_a_no_op(tmp_path):
    path = tmp_path / "club.db"
    record_seen_players([], "2026-09-27T10:00:00+00:00", path=path)

    assert load_known_players(path=path) == []


def test_record_seen_players_bumps_last_seen_without_touching_first_seen(tmp_path):
    path = tmp_path / "club.db"
    record_seen_players([_sighting("Max Mustermann")], "2026-09-27T10:00:00+00:00", path=path)
    record_seen_players([_sighting("Max Mustermann")], "2026-09-28T10:00:00+00:00", path=path)

    players = load_known_players(path=path)
    assert len(players) == 1
    assert players[0].first_seen == "2026-09-27T10:00:00+00:00"
    assert players[0].last_seen == "2026-09-28T10:00:00+00:00"


def test_record_seen_players_never_resets_an_existing_friend_flag(tmp_path):
    path = tmp_path / "club.db"
    record_seen_players([_sighting("Max Mustermann")], "2026-09-27T10:00:00+00:00", path=path)
    set_player_friend("Max Mustermann", True, path=path)

    record_seen_players([_sighting("Max Mustermann")], "2026-09-28T10:00:00+00:00", path=path)

    players = load_known_players(path=path)
    assert players[0].is_friend is True


def test_record_seen_players_stores_gender_member_status_and_handicap(tmp_path):
    path = tmp_path / "club.db"
    record_seen_players(
        [_sighting("Max Mustermann", gender="male", member_status="member", handicap=25.1)],
        "2026-09-27T10:00:00+00:00",
        path=path,
    )

    player = load_known_players(path=path)[0]
    assert player.gender == "male"
    assert player.member_status == "member"
    assert player.handicap == 25.1


def test_record_seen_players_keeps_a_prior_value_when_a_later_sighting_omits_it(tmp_path):
    """A guest's cell sometimes has no handicap span at all -- see
    scraper._parse_hcp_span()'s own docstring. A later sighting with None shouldn't
    erase a real value an earlier one already recorded."""
    path = tmp_path / "club.db"
    record_seen_players(
        [_sighting("Max Mustermann", gender="male", member_status="member", handicap=25.1)],
        "2026-09-27T10:00:00+00:00",
        path=path,
    )
    record_seen_players([_sighting("Max Mustermann")], "2026-09-28T10:00:00+00:00", path=path)

    player = load_known_players(path=path)[0]
    assert player.gender == "male"
    assert player.member_status == "member"
    assert player.handicap == 25.1


def test_set_player_friend_toggles_on_and_off(tmp_path):
    path = tmp_path / "club.db"
    record_seen_players([_sighting("Max Mustermann")], "2026-09-27T10:00:00+00:00", path=path)

    set_player_friend("Max Mustermann", True, path=path)
    assert load_known_players(path=path)[0].is_friend is True

    set_player_friend("Max Mustermann", False, path=path)
    assert load_known_players(path=path)[0].is_friend is False


def test_set_player_friend_is_a_no_op_for_a_name_never_seen(tmp_path):
    path = tmp_path / "club.db"
    set_player_friend("Nobody Real", True, path=path)

    assert load_known_players(path=path) == []


def test_load_known_players_sorts_alphabetically_by_family_name(tmp_path):
    path = tmp_path / "club.db"
    # Inserted out of both first-seen and first-name order -- only the family name
    # (last token) should determine the result.
    record_seen_players([_sighting("Bernd Adler")], "2026-09-25T10:00:00+00:00", path=path)
    record_seen_players([_sighting("Anna Zeller")], "2026-09-27T10:00:00+00:00", path=path)
    record_seen_players([_sighting("Claus Bauer")], "2026-09-26T10:00:00+00:00", path=path)
    set_player_friend("Anna Zeller", True, path=path)  # friend status no longer affects order

    names = [p.name for p in load_known_players(path=path)]
    assert names == ["Bernd Adler", "Claus Bauer", "Anna Zeller"]


def test_load_known_players_with_no_club_db_yet_returns_empty(tmp_path):
    assert load_known_players(path=tmp_path / "never-created.db") == []


def test_load_friend_names_returns_only_the_marked_ones(tmp_path):
    path = tmp_path / "club.db"
    record_seen_players([_sighting("Friend One"), _sighting("Not A Friend")], "2026-09-27T10:00:00+00:00", path=path)
    set_player_friend("Friend One", True, path=path)

    assert load_friend_names(path=path) == {"Friend One"}


def test_load_friend_names_with_no_club_db_yet_returns_empty_set(tmp_path):
    assert load_friend_names(path=tmp_path / "never-created.db") == set()


def test_load_known_handicaps_returns_only_names_with_a_recorded_handicap(tmp_path):
    path = tmp_path / "club.db"
    record_seen_players(
        [_sighting("Has Handicap", handicap=24.0), _sighting("No Handicap")],
        "2026-09-27T10:00:00+00:00",
        path=path,
    )

    assert load_known_handicaps(path=path) == {"Has Handicap": 24.0}


def test_load_known_handicaps_with_no_club_db_yet_returns_empty_dict(tmp_path):
    assert load_known_handicaps(path=tmp_path / "never-created.db") == {}


def test_looks_like_player_name_rejects_events_and_accepts_real_names():
    from src.models import looks_like_player_name

    assert not looks_like_player_name("Doppelteestart 11:00 Uhr, Ihre Startzeit gilt nur für 9-Loch!")
    assert not looks_like_player_name("")
    for name in ("Max Mustermann", "Hans-Jürgen Rosshau", "didier waechter", "Dr. Jan-Simon Schmidt"):
        assert looks_like_player_name(name)


def test_purge_non_player_names_removes_event_rows_but_keeps_players(tmp_path):
    import sqlite3

    from src import storage
    from src.models import PlayerSighting

    db = tmp_path / "x.db"
    storage.record_seen_players([PlayerSighting(name="Max Mustermann")], "2026-10-02T00:00:00", path=db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO known_players (name, first_seen, last_seen) VALUES (?, ?, ?)",
            ("Doppelteestart 11:00 Uhr!", "x", "x"),
        )
    assert storage.purge_non_player_names(db) == 1
    assert [p.name for p in storage.load_known_players(path=db)] == ["Max Mustermann"]


def test_looks_like_player_name_keeps_parenthesised_and_long_names():
    from src.models import looks_like_player_name

    assert looks_like_player_name("Müller (Gast)")
    assert looks_like_player_name("Hans-Joachim Freiherr von und zu Altenstein")


def test_purge_never_deletes_a_friend_row(tmp_path):
    import sqlite3

    from src import storage

    db = tmp_path / "y.db"
    storage.init_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO known_players (name, first_seen, last_seen, is_friend) VALUES (?, 'x', 'x', 1)",
            ("Odd Name 2",),
        )
    assert storage.purge_non_player_names(db) == 0


def test_init_db_migrates_a_known_players_table_from_before_gender_existed(tmp_path):
    # Same shape as the scrapes/weather_points migration tests above: a real directory
    # (373 names) predates gender/member_status/handicap, and init_db() has to ALTER
    # the table in place without losing a friend flag.
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE known_players (name TEXT PRIMARY KEY, first_seen TEXT NOT NULL, "
            "last_seen TEXT NOT NULL, is_friend INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO known_players VALUES (?, ?, ?, 1)",
            ("Max Mustermann", "2026-09-01T10:00:00+00:00", "2026-09-01T10:00:00+00:00"),
        )
    conn.close()

    record_seen_players(
        [_sighting("Max Mustermann", gender="male", member_status="member", handicap=25.1)],
        "2026-09-28T10:00:00+00:00",
        path=db,
    )

    player = load_known_players(path=db)[0]
    assert player.is_friend is True
    assert player.first_seen == "2026-09-01T10:00:00+00:00"
    assert (player.gender, player.member_status, player.handicap) == ("male", "member", 25.1)


def test_load_player_genders_returns_only_male_and_female(tmp_path):
    from src.storage import load_player_genders

    db = tmp_path / "club.db"
    record_seen_players(
        [
            _sighting("Max Mustermann", gender="male"),
            _sighting("Erika Mustermann", gender="female"),
            _sighting("Kim Muster", gender="unknown"),
            _sighting("Alex Muster"),
        ],
        "2026-09-27T10:00:00+00:00",
        path=db,
    )

    assert load_player_genders(path=db) == {"Max Mustermann": "male", "Erika Mustermann": "female"}
    assert load_player_genders(path=tmp_path / "missing.db") == {}


def test_history_lookups_use_indexes_not_full_scans(tmp_path):
    # Every scrape appends a day of slots forever; without an index each
    # load_latest_schedule() scanned the whole table.
    db = tmp_path / "club.db"
    init_db(db)
    with sqlite3.connect(db) as conn:
        plans = {
            sql: " ".join(row[-1] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", params))
            for sql, params in (
                ("SELECT time FROM slots WHERE scrape_id = ? ORDER BY time", (1,)),
                ("SELECT time FROM weather_points WHERE scrape_id = ? ORDER BY time", (1,)),
                ("SELECT id FROM scrapes WHERE course = ? AND date = ? ORDER BY id DESC LIMIT 1", ("c", "d")),
            )
        }
    conn.close()
    for sql, plan in plans.items():
        assert "USING INDEX" in plan or "USING COVERING INDEX" in plan, (sql, plan)
        assert "TEMP B-TREE" not in plan, (sql, plan)


def test_storage_calls_close_their_connections(tmp_path):
    # `with sqlite3.connect(...)` only commits; the connection stayed open until GC
    # and Python warned "unclosed database" on every call.
    import gc
    import warnings

    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-06", course="c", slots=[Slot(time="08:00", booked=0, capacity=4)]), path=db)
    gc.collect()  # other tests' own unclosed connections must not be counted here
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        load_latest_schedule("c", "2026-09-06", path=db)
        gc.collect()
    assert not [w for w in caught if issubclass(w.category, ResourceWarning)]


# --- scrape_runs / scrape_health() (2026-10-05) -- see storage.py's module docstring:
# a 20-hour silent login failure nobody noticed ------------------------------------

_T0 = datetime(2026, 10, 3, 16, 45, tzinfo=UTC)


def _run(path, minutes, *, saved=1, attempted=None, failed=0, authenticated=None, error_kind=None,
         error_message=None, source="agent"):
    """One run `minutes` after _T0 (a pass of about a minute)."""
    started = _T0 + timedelta(minutes=minutes)
    storage.record_scrape_run(
        started_at=started.isoformat(),
        finished_at=(started + timedelta(minutes=1)).isoformat(),
        source=source,
        attempted=saved + failed if attempted is None else attempted,
        saved=saved,
        failed=failed,
        authenticated=authenticated,
        error_kind=error_kind,
        error_message=error_message,
        path=path,
    )


def _iso(minutes, finished=False):
    return (_T0 + timedelta(minutes=minutes + (1 if finished else 0))).isoformat()


def test_init_db_creates_scrape_runs_and_its_index(tmp_path):
    path = tmp_path / "club.db"
    init_db(path)
    with sqlite3.connect(path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(scrape_runs)")]
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(scrape_runs)")}
    assert columns == ["id", "started_at", "finished_at", "source", "attempted", "saved", "failed",
                       "authenticated", "error_kind", "error_message"]
    assert "idx_scrape_runs_started" in indexes


def test_init_db_adds_scrape_runs_to_a_database_that_predates_it(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE scrapes (id INTEGER PRIMARY KEY, course TEXT, date TEXT, scraped_at TEXT)")
    assert storage.scrape_health(path) == storage.empty_scrape_health()
    _run(path, 0)
    assert storage.scrape_health(path)["last_run_at"] == _iso(0, finished=True)


def test_record_scrape_run_stores_every_field(tmp_path):
    path = tmp_path / "club.db"
    _run(path, 0, saved=3, failed=1, authenticated=False, error_kind="login_rejected",
         error_message="  Login failed for club 0000001  ", source="tui")
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT started_at, finished_at, source, attempted, saved, failed, authenticated, error_kind, "
            "error_message FROM scrape_runs"
        ).fetchone()
    assert row == (_iso(0), _iso(0, finished=True), "tui", 4, 3, 1, 0, "login_rejected",
                   "Login failed for club 0000001")


def test_record_scrape_run_keeps_null_for_no_credentials(tmp_path):
    path = tmp_path / "club.db"
    _run(path, 0, authenticated=None)
    _run(path, 1, authenticated=True)
    with sqlite3.connect(path) as conn:
        assert [r[0] for r in conn.execute("SELECT authenticated FROM scrape_runs ORDER BY id")] == [None, 1]


def test_record_scrape_run_truncates_a_long_error_message(tmp_path):
    path = tmp_path / "club.db"
    _run(path, 0, saved=0, failed=1, error_kind="other", error_message="x" * 5000)
    with sqlite3.connect(path) as conn:
        (message,) = conn.execute("SELECT error_message FROM scrape_runs").fetchone()
    assert len(message) == storage.SCRAPE_ERROR_MESSAGE_MAX_CHARS


@pytest.mark.parametrize("field, value", [("source", "cron"), ("error_kind", "timeout")])
def test_record_scrape_run_rejects_unknown_values(tmp_path, field, value):
    kwargs = {"started_at": _iso(0), "finished_at": _iso(1), "source": "agent", "attempted": 0, "saved": 0,
              "failed": 0, "authenticated": None, "path": tmp_path / "club.db"}
    kwargs[field] = value
    with pytest.raises(ValueError):
        storage.record_scrape_run(**kwargs)


def test_record_scrape_run_prunes_rows_older_than_the_retention_window(tmp_path):
    path = tmp_path / "club.db"
    now = datetime.now(UTC)
    for days_old in (45, 31, 29, 1):
        started = now - timedelta(days=days_old)
        storage.record_scrape_run(started_at=started.isoformat(), finished_at=started.isoformat(), source="agent",
                                  attempted=0, saved=0, failed=0, authenticated=None, path=path)
    with sqlite3.connect(path) as conn:
        kept = [row[0] for row in conn.execute("SELECT started_at FROM scrape_runs ORDER BY started_at")]
    assert kept == [(now - timedelta(days=d)).isoformat() for d in (29, 1)]


def test_scrape_health_is_empty_for_a_missing_database(tmp_path):
    path = tmp_path / "never-scraped.db"
    assert storage.scrape_health(path) == storage.empty_scrape_health()
    assert not path.exists()  # a read must not create the club's database


def test_scrape_health_for_a_healthy_history(tmp_path):
    path = tmp_path / "club.db"
    _run(path, 0, saved=6)
    _run(path, 15, saved=0, attempted=0)  # nothing due -- still a success
    health = storage.scrape_health(path)
    assert health == {
        "last_run_at": _iso(15, finished=True),
        "last_success_at": _iso(15, finished=True),
        "last_error_kind": None,
        "last_error_message": None,
        "consecutive_failed_runs": 0,
        "failing_since": None,
        "login_rejected_since": None,
    }


def test_scrape_health_counts_the_current_failure_streak(tmp_path):
    path = tmp_path / "club.db"
    _run(path, 0, saved=6)
    _run(path, 15, saved=0, failed=1, error_kind="network", error_message="offline")
    _run(path, 30, saved=6)  # recovered: the streak before this doesn't count
    _run(path, 45, saved=0, attempted=0, error_kind="no_tee_sheet", error_message="no table")
    _run(path, 60, saved=0, attempted=0, error_kind="no_tee_sheet", error_message="no table")
    _run(path, 75, saved=0, failed=2, error_kind="network", error_message="timed out")
    health = storage.scrape_health(path)
    assert health["consecutive_failed_runs"] == 3
    assert health["failing_since"] == _iso(45)
    assert health["last_success_at"] == _iso(30, finished=True)
    assert health["last_error_kind"] == "network"
    assert health["last_error_message"] == "timed out"


def test_scrape_health_with_no_success_ever(tmp_path):
    path = tmp_path / "club.db"
    _run(path, 0, saved=0, attempted=0, error_kind="no_tee_sheet")
    _run(path, 15, saved=0, attempted=0, error_kind="no_tee_sheet")
    health = storage.scrape_health(path)
    assert health["last_success_at"] is None
    assert health["consecutive_failed_runs"] == 2
    assert health["failing_since"] == _iso(0)


def test_a_login_rejected_run_that_still_saved_anonymously_is_a_success(tmp_path):
    # The real 2026-10-03 incident: data kept arriving, only the names were missing.
    path = tmp_path / "club.db"
    _run(path, 0, saved=6, authenticated=True)
    _run(path, 15, saved=6, authenticated=False, error_kind="login_rejected")
    _run(path, 30, saved=0, attempted=0, authenticated=False, error_kind="login_rejected")
    health = storage.scrape_health(path)
    # Nothing was due and only the login failed: the agent is alive, so still a success
    # (2026-10-05, review -- see scrape_run_succeeded()).
    assert health["consecutive_failed_runs"] == 0
    assert health["last_success_at"] == _iso(30, finished=True)
    assert health["login_rejected_since"] == _iso(15)


def test_idle_passes_during_a_login_outage_never_become_a_failure_streak(tmp_path):
    # The agent runs every 15 min against a 6 h interval: most passes have nothing due.
    # Before the 2026-10-05 review fix, four of them in a row read as "scrapes failing".
    path = tmp_path / "club.db"
    _run(path, 0, saved=6, authenticated=False, error_kind="login_rejected")
    for minutes in (15, 30, 45, 60):
        _run(path, minutes, saved=0, attempted=0, authenticated=False, error_kind="login_rejected")
    health = storage.scrape_health(path)
    assert health["consecutive_failed_runs"] == 0 and health["failing_since"] is None
    assert health["last_success_at"] == _iso(60, finished=True)
    assert health["login_rejected_since"] == _iso(0)


def test_a_course_list_failure_during_a_login_outage_is_a_failure_and_keeps_the_streak(tmp_path):
    # scrape_once records it as no_tee_sheet with authenticated=0 (the real cause wins).
    path = tmp_path / "club.db"
    _run(path, 0, saved=6, authenticated=False, error_kind="login_rejected")
    _run(path, 15, saved=0, attempted=0, authenticated=False, error_kind="no_tee_sheet")
    health = storage.scrape_health(path)
    assert health["consecutive_failed_runs"] == 1
    assert health["last_error_kind"] == "no_tee_sheet"
    assert health["login_rejected_since"] == _iso(0)


def test_login_rejected_streak_survives_a_run_whose_login_outcome_is_unknown(tmp_path):
    path = tmp_path / "club.db"
    _run(path, 0, saved=6, authenticated=True)
    _run(path, 15, saved=6, authenticated=False, error_kind="login_rejected")
    _run(path, 30, saved=0, failed=1, authenticated=False, error_kind="network")  # offline blip
    _run(path, 45, saved=6, authenticated=False, error_kind="login_rejected")
    assert storage.scrape_health(path)["login_rejected_since"] == _iso(15)


def test_login_rejected_streak_holds_while_the_newest_run_could_not_tell(tmp_path):
    path = tmp_path / "club.db"
    _run(path, 0, saved=6, authenticated=False, error_kind="login_rejected")
    _run(path, 15, saved=0, failed=1, authenticated=False, error_kind="network")
    assert storage.scrape_health(path)["login_rejected_since"] == _iso(0)


@pytest.mark.parametrize("authenticated", [True, None])
def test_login_rejected_streak_ends_at_a_good_login_or_removed_credentials(tmp_path, authenticated):
    path = tmp_path / "club.db"
    _run(path, 0, saved=6, authenticated=False, error_kind="login_rejected")
    _run(path, 15, saved=6, authenticated=authenticated)
    assert storage.scrape_health(path)["login_rejected_since"] is None
    _run(path, 30, saved=6, authenticated=False, error_kind="login_rejected")
    assert storage.scrape_health(path)["login_rejected_since"] == _iso(30)


def test_backup_db_writes_a_consistent_copy(tmp_path):
    source = tmp_path / "club.db"
    save_location({"lat": 48.5, "lon": 8.8}, source)
    target = tmp_path / "backups" / "club-2026-10-05.db"
    storage.backup_db(source, target)
    assert load_location(target) == {"lat": 48.5, "lon": 8.8}
    assert not (tmp_path / "backups" / "club-2026-10-05.db.partial").exists()


def test_courses_scraped_on_lists_every_course_with_a_scrape_for_that_date(tmp_path):
    db = tmp_path / "club.db"
    for course, day in (("9 Loch Tee 1", "2026-10-05"), ("18 Loch Tee 1", "2026-10-05"),
                        ("18 Loch Tee 1", "2026-10-05"), ("6 Loch Platz", "2026-10-06")):
        storage.save_schedule(Schedule(date=day, course=course, slots=[]), path=db)
    assert storage.courses_scraped_on("2026-10-05", path=db) == ["18 Loch Tee 1", "9 Loch Tee 1"]
    assert storage.courses_scraped_on("2026-10-07", path=db) == []


def test_upcoming_courses_hides_retired_names_and_falls_back_to_everything(tmp_path):
    db = tmp_path / "club.db"
    for course, day in (("Alt", "2026-09-01"), ("Kurzplatz", "2026-10-06"), ("18 Loch Tee 1", "2026-10-05")):
        storage.save_schedule(Schedule(date=day, course=course, slots=[]), path=db)
    assert storage.upcoming_courses("2026-10-05", path=db) == ["18 Loch Tee 1", "Kurzplatz"]  # "Alt" is history
    assert storage.upcoming_courses("2027-01-01", path=db) == ["18 Loch Tee 1", "Alt", "Kurzplatz"]  # none upcoming
    assert storage.upcoming_courses("2026-10-05", path=tmp_path / "empty.db") == []


def test_load_player_handicaps_skips_players_without_one(tmp_path):
    from src.storage import load_player_handicaps

    db = tmp_path / "club.db"
    record_seen_players(
        [
            _sighting("Max Mustermann", handicap=18.4),
            _sighting("Erika Mustermann", handicap=0.0),
            _sighting("Gast Eins"),
        ],
        "2026-10-05T10:00:00+00:00",
        path=db,
    )
    # A later sighting without a handicap keeps the recorded one (COALESCE).
    record_seen_players([_sighting("Max Mustermann")], "2026-10-06T10:00:00+00:00", path=db)

    assert load_player_handicaps(path=db) == {"Max Mustermann": 18.4, "Erika Mustermann": 0.0}
    assert load_player_handicaps(path=tmp_path / "missing.db") == {}


# --- WAL, busy timeout, user_version (2026-10-05): the launchd agent, the TUI worker and
# the GUI all open the same file ---------------------------------------------------


def _one_slot_schedule(course="c", date="2026-09-06"):
    return Schedule(date=date, course=course, slots=[Slot(time="08:00", booked=1, capacity=4)])


def _pragma(db, name):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(f"PRAGMA {name}").fetchone()[0]
    finally:
        conn.close()


def test_connections_set_a_busy_timeout(monkeypatch, tmp_path):
    # A bare sqlite3.connect() already reports 5000 ms, so a test of the default can't
    # fail. Change the constant and check the pragma follows it: that proves _open()
    # issues the PRAGMA / passes timeout= rather than inheriting Python's default.
    assert storage.BUSY_TIMEOUT_MS == 5000
    monkeypatch.setattr(storage, "BUSY_TIMEOUT_MS", 1234)
    with storage._connect(tmp_path / "x.db") as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 1234


def test_init_db_switches_to_wal_and_it_persists(tmp_path):
    db = tmp_path / "club.db"
    init_db(db)
    assert _pragma(db, "journal_mode") == "wal"  # a brand-new connection: persisted in the file
    init_db(db)  # idempotent
    assert _pragma(db, "journal_mode") == "wal"


def test_every_storage_call_leaves_wal_on(tmp_path):
    db = tmp_path / "club.db"
    save_schedule(_one_slot_schedule(), path=db)
    assert _pragma(db, "journal_mode") == "wal"


def test_init_db_migrates_an_old_rollback_journal_database(tmp_path):
    db = tmp_path / "club.db"
    # An old install: rollback journal, no user_version, an older `scrapes` shape.
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE scrapes (id INTEGER PRIMARY KEY AUTOINCREMENT, course TEXT NOT NULL,"
        " date TEXT NOT NULL, scraped_at TEXT NOT NULL);"
        "INSERT INTO scrapes (course, date, scraped_at) VALUES ('c', '2026-09-06', '2026-09-05T08:00:00');"
    )
    conn.commit()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()

    init_db(db)
    init_db(db)  # twice: idempotent

    assert _pragma(db, "journal_mode") == "wal"
    assert _pragma(db, "user_version") == storage.SCHEMA_VERSION
    assert last_scraped_at("c", "2026-09-06", path=db) == "2026-09-05T08:00:00"  # history intact
    columns = {row[1] for row in sqlite3.connect(db).execute("PRAGMA table_info(scrapes)")}
    assert {"sunrise", "sunset", "events"} <= columns


def test_init_db_stamps_user_version_and_never_lowers_a_newer_one(tmp_path):
    db = tmp_path / "club.db"
    init_db(db)
    assert storage.schema_version(db) == storage.SCHEMA_VERSION >= 1
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION + 41}")
    conn.close()
    init_db(db)  # a newer app already touched this file: leave its version alone
    save_schedule(_one_slot_schedule(), path=db)
    assert storage.schema_version(db) == storage.SCHEMA_VERSION + 41


def test_a_reader_is_not_blocked_by_an_open_write_transaction(tmp_path, monkeypatch):
    import threading
    import time

    db = tmp_path / "club.db"
    save_schedule(_one_slot_schedule(), path=db)
    # The discriminating part: a rollback-journal writer that has only a few dirty pages
    # holds RESERVED and readers still pass, so the test would be green without WAL.
    # Spilling dirty pages (tiny cache, a few MB) makes a delete-mode writer take
    # EXCLUSIVE and the reader fail with "database is locked"; in WAL it returns at once.
    assert _pragma(db, "journal_mode") == "wal"
    writer_open = threading.Event()
    release = threading.Event()

    def hold_write_lock():
        conn = sqlite3.connect(db)
        try:
            conn.execute("PRAGMA cache_size = 1")
            conn.execute("BEGIN IMMEDIATE")
            for _ in range(2000):
                conn.execute(
                    "INSERT INTO scrapes (course, date, scraped_at) VALUES ('c', '2026-09-07', hex(randomblob(2000)))"
                )
            writer_open.set()
            release.wait(10)
            conn.rollback()
        finally:
            conn.close()

    thread = threading.Thread(target=hold_write_lock)
    thread.start()
    try:
        assert writer_open.wait(30)
        monkeypatch.setattr(storage, "BUSY_TIMEOUT_MS", 300)  # fail fast if it would block
        started = time.monotonic()
        schedule = load_latest_schedule("c", "2026-09-06", path=db)
        dates = distinct_scraped_dates("c", path=db)
        elapsed = time.monotonic() - started
        assert schedule is not None and len(schedule.slots) == 1
        assert dates == ["2026-09-06"]  # the uncommitted row is not visible
        assert elapsed < 0.25, f"reader waited {elapsed:.1f}s on a writer"
    finally:
        release.set()
        thread.join()


def test_concurrent_writers_all_land(tmp_path):
    import threading

    db = tmp_path / "club.db"
    init_db(db)
    errors = []

    def writer(n):
        try:
            for i in range(5):
                save_schedule(_one_slot_schedule(course=f"c{n}", date=f"2026-09-{10 + i}"), path=db)
                load_latest_schedule(f"c{n}", f"2026-09-{10 + i}", path=db)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM scrapes").fetchone()[0] == 20
    finally:
        conn.close()


def test_backup_under_wal_is_a_consistent_self_contained_snapshot(tmp_path):
    db = tmp_path / "club.db"
    save_schedule(_one_slot_schedule(date="2026-09-06"), path=db)
    # A second connection stays open, so the commit below still sits in the -wal file
    # (no checkpoint has folded it into the main file) and a plain file copy would miss it.
    holder = sqlite3.connect(db)
    holder.execute("SELECT 1 FROM scrapes").fetchall()
    try:
        save_schedule(_one_slot_schedule(date="2026-09-07"), path=db)
        assert (tmp_path / "club.db-wal").exists()
        # ...and an in-flight transaction that must NOT appear in the snapshot.
        writer = sqlite3.connect(db, isolation_level=None)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO scrapes (course, date, scraped_at) VALUES ('c', '2026-09-08', 'x')")
        try:
            destination = tmp_path / "out" / "backup.db"
            storage.backup_db(db, destination)
        finally:
            writer.execute("ROLLBACK")
            writer.close()
    finally:
        holder.close()

    # Self-contained: move it alone, with no sidecars, somewhere else and read it.
    lone = tmp_path / "elsewhere.db"
    destination.rename(lone)
    assert not list((tmp_path / "out").glob("*"))  # no .partial left behind
    conn = sqlite3.connect(lone)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        dates = [row[0] for row in conn.execute("SELECT date FROM scrapes ORDER BY date")]
    finally:
        conn.close()
    assert dates == ["2026-09-06", "2026-09-07"]
    assert distinct_scraped_dates("c", path=lone) == ["2026-09-06", "2026-09-07"]


def test_backup_does_not_change_the_sources_journal_mode(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE scrapes (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    storage.backup_db(db, tmp_path / "b.db")
    assert _pragma(db, "journal_mode") == "delete"


def test_legacy_migration_copies_wal_pending_commits(tmp_path, monkeypatch):
    # paths.migrate_from() used to shutil.copy2() the bare .db; with WAL a recent commit
    # may live only in the -wal file, so it goes through the backup API instead.
    from src import paths

    legacy = tmp_path / "old"
    (legacy / "data").mkdir(parents=True)
    old_db = legacy / "data" / "0000001.db"
    save_schedule(_one_slot_schedule(), path=old_db)
    holder = sqlite3.connect(old_db)  # keeps the commit in the -wal file
    holder.execute("SELECT 1 FROM scrapes").fetchall()
    try:
        data = tmp_path / "new-data"
        monkeypatch.setattr(paths, "DATA_DIR", data)
        monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "cfg")
        monkeypatch.setattr(paths, "CLUBS_DIR", tmp_path / "cfg" / "clubs")
        monkeypatch.setattr(paths, "ENV_FILE", tmp_path / "cfg" / ".env")
        monkeypatch.setattr(paths, "MANAGED_DIRS", (tmp_path / "cfg", tmp_path / "cfg" / "clubs", data))
        monkeypatch.setattr(paths, "_write_migration_marker", lambda: None)
        paths.migrate_from(legacy)
    finally:
        holder.close()
    assert distinct_scraped_dates("c", path=data / "0000001.db") == ["2026-09-06"]


def test_scrapes_record_whether_they_were_logged_in_and_old_databases_gain_the_column(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:  # a database from before the column existed
        conn.executescript(
            "CREATE TABLE scrapes (id INTEGER PRIMARY KEY AUTOINCREMENT, course TEXT NOT NULL, date TEXT NOT NULL,"
            " scraped_at TEXT NOT NULL, sunrise TEXT, sunset TEXT, events TEXT);"
        )
    storage.init_db(db)
    with sqlite3.connect(db) as conn:
        assert "authenticated" in {row[1] for row in conn.execute("PRAGMA table_info(scrapes)")}

    schedule = Schedule(date="2026-10-07", course="18 Loch Tee 1", slots=[Slot("09:00", 1, 4)])
    assert storage.last_scrape_authenticated("18 Loch Tee 1", "2026-10-07", path=db) is None  # never scraped
    storage.save_schedule(schedule, path=db)
    assert storage.last_scrape_authenticated("18 Loch Tee 1", "2026-10-07", path=db) is None  # unknown
    storage.save_schedule(schedule, path=db, authenticated=False)
    assert storage.last_scrape_authenticated("18 Loch Tee 1", "2026-10-07", path=db) is False
    storage.save_schedule(schedule, path=db, authenticated=True)
    assert storage.last_scrape_authenticated("18 Loch Tee 1", "2026-10-07", path=db) is True
