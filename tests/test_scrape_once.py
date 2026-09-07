from datetime import datetime, timedelta, timezone

from src import booking_watch, scrape_once
from src.models import ConfirmedBooking, Schedule, Slot

# scrape_due_for_club() now fetches each club's own course list live (fetch_course_aliases()
# -- see scraper.py's module docstring on why a hardcoded constant isn't safe across clubs)
# rather than assuming a fixed set, so any test exercising that path needs this mocked --
# these are Musterhausen's own confirmed real values, reused as fake test data.
_FAKE_COURSES = {"18 Loch Tee 1": "COUB", "9 Loch Tee 1": "COU1", "6 Loch Platz": "COU6"}


def test_run_scrapes_and_saves_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    fake_schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="06:00", booked=1, capacity=4)],
    )
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date: fake_schedule)

    # config={} keeps this isolated from whatever real clubs/*.yaml the developer
    # running these tests happens to have on disk locally (see _attach_weather --
    # a real club config with real coordinates would otherwise make a real network
    # call to Open-Meteo from inside a unit test).
    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={})

    assert changes == []  # nothing to compare against yet — no prior scrape
    loaded = scrape_once.storage.load_latest_schedule(
        "18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001")
    )
    assert loaded.slots[0].booked == 1


def test_run_skips_my_reservations_when_no_credentials_configured(tmp_path, monkeypatch):
    # No slug/credentials resolved for this club (see _sync_my_reservations) --
    # run() must not let that take down the whole scrape.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        scrape_once,
        "scrape_schedule",
        lambda club_id, course, date: Schedule(date=date, course=course, slots=[]),
    )

    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={})

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

    scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={})
    # Second call now has a real baseline in storage — but no confirmed booking exists
    # for this course/date, so booking_watch.check_for_changes() is never even
    # attempted (see test below for that case). Still expect a clean empty list.
    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={})
    assert changes == []


def test_run_reports_booking_watch_changes_when_a_booking_exists(tmp_path, monkeypatch):
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
    scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={})

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
    # which is real now, and should report the party growing from 1 to 2.
    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={})
    assert len(changes) == 1
    assert changes[0].kind == "party_grew"

    # Persisted too -- a separate TUI process reading this club's database later needs
    # to see it, not just whatever run() happened to return in-memory this time.
    saved = scrape_once.storage.load_unacknowledged_booking_changes(path=scrape_once._db_path("0000001"))
    assert len(saved) == 1
    assert saved[0]["kind"] == "party_grew"
    assert saved[0]["date"] == "2026-09-06"


def test_should_scrape_true_when_never_scraped(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    assert scrape_once._should_scrape("0000001", "18 Loch Tee 1", "2026-09-06", {}) is True


def test_should_scrape_false_within_normal_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    monkeypatch.setattr(scrape_once.storage, "last_scraped_at", lambda course, date, path: recent)
    monkeypatch.setattr(scrape_once.storage, "load_confirmed_booking", lambda course, date, path: None)

    config = {"scrape_interval_minutes": 360}
    assert scrape_once._should_scrape("0000001", "18 Loch Tee 1", "2026-09-06", config) is False


def test_should_scrape_true_once_normal_interval_elapsed(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(minutes=400)).isoformat()
    monkeypatch.setattr(scrape_once.storage, "last_scraped_at", lambda course, date, path: old)
    monkeypatch.setattr(scrape_once.storage, "load_confirmed_booking", lambda course, date, path: None)

    config = {"scrape_interval_minutes": 360}
    assert scrape_once._should_scrape("0000001", "18 Loch Tee 1", "2026-09-06", config) is True


def test_should_scrape_uses_shorter_interval_once_booked(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    # 90 minutes ago -- past the 60-min "booked" interval, but well within the 360-min
    # normal one, so this only returns True because a confirmed booking exists.
    recent = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
    monkeypatch.setattr(scrape_once.storage, "last_scraped_at", lambda course, date, path: recent)
    monkeypatch.setattr(
        scrape_once.storage,
        "load_confirmed_booking",
        lambda course, date, path: ConfirmedBooking(
            date=date, course=course, time="14:00", source="manual", confirmed_at="t1"
        ),
    )

    config = {"scrape_interval_minutes": 360, "scrape_interval_minutes_booked": 60}
    assert scrape_once._should_scrape("0000001", "18 Loch Tee 1", "2026-09-06", config) is True


def test_should_scrape_ignores_a_confirmed_not_playing_booking(tmp_path, monkeypatch):
    # A ConfirmedBooking with time=None means "confirmed not playing that day" -- not a
    # real booking to protect, so the normal (longer) interval should still apply.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    recent = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
    monkeypatch.setattr(scrape_once.storage, "last_scraped_at", lambda course, date, path: recent)
    monkeypatch.setattr(
        scrape_once.storage,
        "load_confirmed_booking",
        lambda course, date, path: ConfirmedBooking(
            date=date, course=course, time=None, source="manual", confirmed_at="t1"
        ),
    )

    config = {"scrape_interval_minutes": 360, "scrape_interval_minutes_booked": 60}
    assert scrape_once._should_scrape("0000001", "18 Loch Tee 1", "2026-09-06", config) is False


# --- scrape_due_for_club() (extracted from main() 2026-09-07 so tui.py can call it
# directly for its own auto-refresh -- see that module's docstring) ------------------


def test_scrape_due_for_club_skips_and_returns_empty_when_no_club_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    result = scrape_once.scrape_due_for_club("musterhausen", {})
    assert result == []
    assert "no club_id" in capsys.readouterr().out


def test_scrape_due_for_club_aggregates_changes_across_courses_and_dates(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: _FAKE_COURSES)
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda club_id, course, date, config: True)
    fake_booking = ConfirmedBooking(date="2026-09-07", course="18 Loch Tee 1", time="14:00")
    fake_change = booking_watch.BookingChange(booking=fake_booking, kind="party_grew", message="x", params={})
    monkeypatch.setattr(scrape_once, "run", lambda club_id, course, date, config, slug: [fake_change])

    result = scrape_once.scrape_due_for_club("musterhausen", {"club_id": "0000001", "overview_days": 1})

    assert result == [fake_change] * len(_FAKE_COURSES)


def test_scrape_due_for_club_skips_club_and_returns_empty_when_course_fetch_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    def fake_fetch(club_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(scrape_once, "fetch_course_aliases", fake_fetch)

    result = scrape_once.scrape_due_for_club("musterhausen", {"club_id": "0000001", "overview_days": 1})

    assert result == []
    assert "couldn't load its course list" in capsys.readouterr().out


def test_scrape_due_for_club_catches_one_courses_failure_and_continues(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: _FAKE_COURSES)
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda club_id, course, date, config: True)
    calls = []

    def fake_run(club_id, course, date, config, slug):
        if course == list(_FAKE_COURSES)[0]:
            raise RuntimeError("boom")
        calls.append(course)
        return []

    monkeypatch.setattr(scrape_once, "run", fake_run)

    result = scrape_once.scrape_due_for_club("musterhausen", {"club_id": "0000001", "overview_days": 1})

    assert result == []
    assert len(calls) == len(_FAKE_COURSES) - 1  # every other course still ran
    assert "failed" in capsys.readouterr().out


def test_main_skips_courses_not_yet_due(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: _FAKE_COURSES)
    monkeypatch.setattr(scrape_once.club_config, "list_clubs", lambda: ["musterhausen"])
    monkeypatch.setattr(
        scrape_once.club_config,
        "load_club_config",
        lambda slug: {"club_id": "0000001", "overview_days": 1},
    )
    calls = []
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda club_id, course, date, config: False)
    monkeypatch.setattr(
        scrape_once, "run", lambda club_id, course, date, config, slug: calls.append((course, date))
    )

    scrape_once.main()

    assert calls == []


def test_main_passes_its_loaded_config_through_to_run(tmp_path, monkeypatch):
    # main() already loads each club's config to check _should_scrape() -- it should
    # pass that same config straight to run() rather than making run() re-read it.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: _FAKE_COURSES)
    monkeypatch.setattr(scrape_once.club_config, "list_clubs", lambda: ["musterhausen"])
    club_config_dict = {"club_id": "0000001", "overview_days": 1}
    monkeypatch.setattr(scrape_once.club_config, "load_club_config", lambda slug: club_config_dict)
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda club_id, course, date, config: True)

    seen_configs = []
    seen_slugs = []
    monkeypatch.setattr(
        scrape_once,
        "run",
        lambda club_id, course, date, config, slug: (seen_configs.append(config), seen_slugs.append(slug)),
    )

    scrape_once.main()

    assert seen_configs
    assert all(config is club_config_dict for config in seen_configs)
    assert all(slug == "musterhausen" for slug in seen_slugs)


# --- _sync_my_reservations() (real login, added 2026-09-06) --------------------------


def test_sync_my_reservations_skips_without_a_slug(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    called = []
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda *a, **k: called.append(True))

    scrape_once._sync_my_reservations("0000001", None, scrape_once._db_path("0000001"))

    assert called == []


def test_sync_my_reservations_skips_without_credentials_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("", ""))
    called = []
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda *a, **k: called.append(True))

    scrape_once._sync_my_reservations("0000001", "musterhausen", scrape_once._db_path("0000001"))

    assert called == []


def test_sync_my_reservations_catches_login_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "wrong-password"))

    def broken(club_id, username, password):
        raise scrape_once.LoginError("bad credentials")

    monkeypatch.setattr(scrape_once, "scrape_my_reservations", broken)

    scrape_once._sync_my_reservations("0000001", "musterhausen", scrape_once._db_path("0000001"))

    assert "login failed" in capsys.readouterr().out


def test_sync_my_reservations_catches_not_implemented(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))

    def not_yet(club_id, username, password):
        raise NotImplementedError("real booking, unseen row markup")

    monkeypatch.setattr(scrape_once, "scrape_my_reservations", not_yet)

    scrape_once._sync_my_reservations("0000001", "musterhausen", scrape_once._db_path("0000001"))
    # must not raise -- that's the entire point of this test


def test_sync_my_reservations_saves_confirmed_bookings_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))

    booking = ConfirmedBooking(
        date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="my_reservations", confirmed_at="t1"
    )
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password: [booking])

    db_path = scrape_once._db_path("0000001")
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    saved = scrape_once.storage.load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=db_path)
    assert saved == booking
