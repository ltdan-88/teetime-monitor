import sqlite3

from src.models import ConfirmedBooking, Schedule, Slot, SunTimes, WeatherPoint
from src.storage import (
    acknowledge_booking_changes,
    distinct_scraped_dates,
    init_db,
    last_scraped_at,
    load_all_confirmed_bookings,
    load_confirmed_booking,
    load_latest_schedule,
    load_location,
    load_unacknowledged_booking_changes,
    save_booking_change,
    save_confirmed_booking,
    save_location,
    save_schedule,
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
