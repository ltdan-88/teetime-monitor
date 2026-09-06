from src.models import ConfirmedBooking, Schedule, Slot, WeatherPoint
from src.storage import (
    last_scraped_at,
    load_confirmed_booking,
    load_latest_schedule,
    save_confirmed_booking,
    save_schedule,
)


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
