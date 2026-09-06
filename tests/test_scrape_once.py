from src import scrape_once
from src.models import Schedule, Slot


def test_run_scrapes_and_saves_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    fake_schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="06:00", booked=1, capacity=4)],
    )
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date: fake_schedule)

    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06")

    assert changes == []  # nothing to compare against yet — no prior scrape
    loaded = scrape_once.storage.load_latest_schedule(
        "18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001")
    )
    assert loaded.slots[0].booked == 1


def test_run_skips_my_reservations_when_not_implemented(tmp_path, monkeypatch):
    # scrape_my_reservations() is a genuine NotImplementedError stub (login form not
    # yet built) — run() must not let that take down the whole scrape.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        scrape_once,
        "scrape_schedule",
        lambda club_id, course, date: Schedule(date=date, course=course, slots=[]),
    )

    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06")

    assert changes == []


def test_run_uses_previous_scrape_as_baseline_on_second_call(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    schedules = iter(
        [
            Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="06:00", booked=1, capacity=4)]),
            Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="06:00", booked=2, capacity=4)]),
        ]
    )
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date: next(schedules))

    scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06")
    # Second call now has a real baseline in storage — but no confirmed booking exists
    # for this course/date, so booking_watch.check_for_changes() is never even
    # attempted (see test below for that case). Still expect a clean empty list.
    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06")
    assert changes == []


def test_run_skips_booking_watch_when_check_for_changes_not_implemented(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    schedules = iter(
        [
            Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=1, capacity=4)]),
            Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=2, capacity=4)]),
        ]
    )
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date: next(schedules))

    # First call establishes a baseline scrape (schedules[0]) with nothing to compare
    # against yet.
    scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06")

    from src.models import ConfirmedBooking

    scrape_once.storage.save_confirmed_booking(
        ConfirmedBooking(
            date="2026-09-06",
            course="18 Loch Tee 1",
            time="14:00",
            source="manual",
            confirmed_at="2026-09-06T09:00:00+00:00",
        ),
        path=scrape_once._db_path("0000001"),
    )

    # Second call: a real baseline (schedules[0], now in storage) and a real confirmed
    # booking both exist, so run() actually reaches booking_watch.check_for_changes() —
    # which itself still raises NotImplementedError. run() must catch that, not
    # propagate it.
    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06")
    assert changes == []
