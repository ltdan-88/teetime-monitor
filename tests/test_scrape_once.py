from datetime import datetime, timedelta, timezone

import pytest

from src import booking_watch, scrape_once
from src.models import ConfirmedBooking, Schedule, Slot


@pytest.fixture(autouse=True)
def _no_real_global_preferences_file(monkeypatch, tmp_path):
    """`run()`/`scrape_due_for_club()` both merge in `global_preferences.py`'s shared
    settings unconditionally now (2026-09-08, once availability/preferences stopped
    being per-club) — defaulting to the real `~/.config/teetime-monitor/preferences.yaml`
    if nothing overrides it. Redirected to a throwaway path for every test here, same
    reasoning/pattern as test_tui.py's identical fixture."""
    monkeypatch.setattr(scrape_once.global_preferences, "PREFERENCES_FILE", tmp_path / "preferences.yaml")


@pytest.fixture(autouse=True)
def _no_real_clubs_dir(monkeypatch, tmp_path):
    """Every `scrape_once.run()` call in this file omits `slug`, so `run()`'s own
    `if config is None or slug is None:` guard fires regardless of what `config` was
    given, reaching `_club_config_and_slug_for_id()` -> `club_config.list_clubs()` ->
    whatever real `clubs/*.yaml` the developer running these tests happens to have on
    disk. Several tests' own comments claimed passing `config={}` alone was enough
    isolation from that — it wasn't, and this genuinely broke live (2026-09-10, same
    bug hunt that fixed club_config.py's frozen-default gotcha): a leftover
    regression-test artifact under the real `clubs/` dir with `club_id: "0000001"` —
    the same fake id used everywhere in this file — made `_club_config_and_slug_for_id`
    match it and `run()` reach the real pc caddie site over the network. Points
    `CLUBS_DIR` at an empty directory instead, for every test here, regardless of
    which of `config`/`slug` a given call happens to pass."""
    monkeypatch.setattr(scrape_once.club_config, "CLUBS_DIR", tmp_path / "clubs")


# scrape_due_for_club() now fetches each club's own course list live (fetch_course_aliases()
# -- see scraper.py's module docstring on why a hardcoded constant isn't safe across clubs)
# rather than assuming a fixed set, so any test exercising that path needs this mocked --
# these are Musterhausen's own confirmed real values, reused as fake test data.
_FAKE_COURSES = {"18 Loch Tee 1": "COUB", "9 Loch Tee 1": "COU1", "6 Loch Platz": "COU6"}

# scrape_due_for_club() also reads the club's own bookable-date window off its tee sheet
# now (fetch_available_dates() -- confirmed 2026-09-07 to range from 1 to 31 days across
# real clubs, against a configured default of 5), so that needs mocking too.
_FAKE_DATES = ["2026-09-07", "2026-09-08"]


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


def test_run_uses_global_preferences_buffer_for_booking_watch(tmp_path, monkeypatch):
    # Direct feedback 2026-09-08: "i also want the settings/preferences to be global
    # and not tied to a specific club" -- run()'s own booking_watch check (buffer
    # minutes, weather preferences) now comes from the one shared file, merged on top
    # of whatever per-club config it's handed, not from that config's own (now
    # unused) availability/preferences keys.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    preferences_file = tmp_path / "preferences.yaml"
    scrape_once.global_preferences.save_preferences(
        {"availability": {"buffer_minutes": 45}}, preferences_file
    )
    monkeypatch.setattr(scrape_once.global_preferences, "PREFERENCES_FILE", preferences_file)

    schedules = iter(
        [
            Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=1, capacity=4)]),
            Schedule(
                date="2026-09-06",
                course="18 Loch Tee 1",
                slots=[
                    Slot(time="14:00", booked=1, capacity=4),
                    Slot(time="14:30", booked=4, capacity=4),  # inside the global 45-min buffer
                ],
            ),
        ]
    )
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date: next(schedules))

    # Per-club config deliberately has no availability block at all -- if run() were
    # still reading buffer_minutes from *this*, the neighbor-crowding check below
    # would never fire.
    scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={"club_id": "0000001"})
    scrape_once.storage.save_confirmed_booking(
        ConfirmedBooking(date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="manual"),
        path=scrape_once._db_path("0000001"),
    )

    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={"club_id": "0000001"})

    # The 14:30 slot is a new, real booking -- inside the global 45-min buffer of the
    # 14:00 confirmed booking, so it counts as "buffer_shrunk" -- only reachable at
    # all if buffer_minutes actually came from the global file. Also doubles as
    # coverage for search.resolve_buffer_minutes()'s back-compat fallback (this
    # config only has the old single buffer_minutes key, not the 2026-09-08
    # before/after split) running all the way through the real scrape_once.run()
    # path, not just in isolation.
    assert any(change.kind == "buffer_shrunk" for change in changes)


def test_run_uses_the_split_buffer_keys_directionally(tmp_path, monkeypatch):
    # Direct follow-up, same day: "does a symmetric buffer make sense or should it
    # be adjustable asymmetrically?" -> "split it like in your recommendation."
    # buffer_after_minutes=0 here means a new booking *behind* the confirmed one
    # shouldn't be flagged at all, even though it's well inside what a generous
    # buffer_before would have caught the other way around.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    preferences_file = tmp_path / "preferences.yaml"
    scrape_once.global_preferences.save_preferences(
        {"availability": {"buffer_before_minutes": 45, "buffer_after_minutes": 0}}, preferences_file
    )
    monkeypatch.setattr(scrape_once.global_preferences, "PREFERENCES_FILE", preferences_file)

    schedules = iter(
        [
            Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=1, capacity=4)]),
            Schedule(
                date="2026-09-06",
                course="18 Loch Tee 1",
                slots=[
                    Slot(time="14:00", booked=1, capacity=4),
                    Slot(time="14:30", booked=4, capacity=4),  # after the booking -- buffer_after=0
                ],
            ),
        ]
    )
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date: next(schedules))

    scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={"club_id": "0000001"})
    scrape_once.storage.save_confirmed_booking(
        ConfirmedBooking(date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="manual"),
        path=scrape_once._db_path("0000001"),
    )

    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={"club_id": "0000001"})

    assert changes == []


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
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: _FAKE_DATES)
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda club_id, course, date, config: True)
    fake_booking = ConfirmedBooking(date="2026-09-07", course="18 Loch Tee 1", time="14:00")
    fake_change = booking_watch.BookingChange(booking=fake_booking, kind="party_grew", message="x", params={})
    monkeypatch.setattr(scrape_once, "run", lambda club_id, course, date, config, slug: [fake_change])

    result = scrape_once.scrape_due_for_club("musterhausen", {"club_id": "0000001", "overview_days": 1})

    assert result == [fake_change] * (len(_FAKE_COURSES) * len(_FAKE_DATES))


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
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: _FAKE_DATES)
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
    assert len(calls) == (len(_FAKE_COURSES) - 1) * len(_FAKE_DATES)  # every other course still ran
    assert "failed" in capsys.readouterr().out


def test_main_skips_courses_not_yet_due(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: _FAKE_COURSES)
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: _FAKE_DATES)
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
    # pass that same config's content straight to run() rather than making run()
    # re-read it. Not the exact same object any more (2026-09-08, once global
    # preferences started getting merged in along the way -- see
    # scrape_due_for_club()'s own docstring), so this checks content, not identity.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: _FAKE_COURSES)
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: _FAKE_DATES)
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
    assert all(config.get("club_id") == "0000001" for config in seen_configs)
    assert all(config.get("overview_days") == 1 for config in seen_configs)
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


# --- Cancellation reconciliation -- direct question, 2026-09-13: "how do i
# cancel/modify confirmed tee times?" A previously-known *future* my_reservations
# booking that's disappeared from the live list has been cancelled on pc caddie's
# own real site directly; _sync_my_reservations() used to only ever add rows, so
# this never actually got noticed locally. -----------------------------------------


def test_sync_my_reservations_marks_a_disappeared_future_booking_as_not_playing(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    db_path = scrape_once._db_path("0000001")
    future = (scrape_once.date_cls.today() + timedelta(days=5)).isoformat()
    scrape_once.storage.save_confirmed_booking(
        ConfirmedBooking(date=future, course="18 Loch Tee 1", time="14:00", source="my_reservations", confirmed_at="t1"),
        path=db_path,
    )
    # The live list no longer has it -- cancelled on the real site.
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password: [])

    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    saved = scrape_once.storage.load_confirmed_booking("18 Loch Tee 1", future, path=db_path)
    assert saved.time is None  # "confirmed not playing" -- the existing sentinel
    assert saved.source == "my_reservations"


def test_sync_my_reservations_does_not_cancel_a_past_booking_that_naturally_dropped_off(tmp_path, monkeypatch):
    # "My Reservations" isn't a history view -- it drops a booking once its own
    # date has passed, regardless of whether it was played or cancelled. Must
    # never be mistaken for a cancellation, or every played round would get
    # flagged "cancelled" the moment its own date passed.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    db_path = scrape_once._db_path("0000001")
    past = (scrape_once.date_cls.today() - timedelta(days=5)).isoformat()
    scrape_once.storage.save_confirmed_booking(
        ConfirmedBooking(date=past, course="18 Loch Tee 1", time="14:00", source="my_reservations", confirmed_at="t1"),
        path=db_path,
    )
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password: [])

    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    saved = scrape_once.storage.load_confirmed_booking("18 Loch Tee 1", past, path=db_path)
    assert saved.time == "14:00"  # untouched


def test_sync_my_reservations_does_not_cancel_a_manual_confirmation(tmp_path, monkeypatch):
    # "My Reservations" was never going to confirm or deny a manual (`c` in the
    # TUI) record in the first place -- see ConfirmedBooking's own docstring on
    # why that fallback exists at all.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    db_path = scrape_once._db_path("0000001")
    future = (scrape_once.date_cls.today() + timedelta(days=5)).isoformat()
    scrape_once.storage.save_confirmed_booking(
        ConfirmedBooking(date=future, course="18 Loch Tee 1", time="14:00", source="manual", confirmed_at="t1"),
        path=db_path,
    )
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password: [])

    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    saved = scrape_once.storage.load_confirmed_booking("18 Loch Tee 1", future, path=db_path)
    assert saved.time == "14:00"  # untouched


def test_sync_my_reservations_reinstates_a_booking_that_reappears_live(tmp_path, monkeypatch):
    # Cancel, then rebook the exact same course/date -- the fresh live row
    # should win again ("latest wins"), undoing the earlier cancellation.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    db_path = scrape_once._db_path("0000001")
    future = (scrape_once.date_cls.today() + timedelta(days=5)).isoformat()
    scrape_once.storage.save_confirmed_booking(
        ConfirmedBooking(date=future, course="18 Loch Tee 1", time=None, source="my_reservations", confirmed_at="t1"),
        path=db_path,
    )
    rebooked = ConfirmedBooking(
        date=future, course="18 Loch Tee 1", time="15:00", source="my_reservations", confirmed_at="t2"
    )
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password: [rebooked])

    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    saved = scrape_once.storage.load_confirmed_booking("18 Loch Tee 1", future, path=db_path)
    assert saved.time == "15:00"


def test_scrape_due_for_club_uses_the_clubs_own_booking_window(tmp_path, monkeypatch):
    # The club's real bookable dates win over the configured overview_days -- a fixed 5
    # was both asking some clubs for dates their site rejects and ignoring most of the
    # window others offer (1 to 31 days observed across 79 real clubs, 2026-09-07).
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: {"A": "a"})
    monkeypatch.setattr(scrape_once, "fetch_available_dates",
                        lambda club_id: ["2026-09-07", "2026-09-08", "2026-09-09"])
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    seen = []
    monkeypatch.setattr(scrape_once, "run",
                        lambda club_id, course, date, config, slug: seen.append(date) or [])

    scrape_once.scrape_due_for_club("c", {"club_id": "0000001", "overview_days": 1})

    assert seen == ["2026-09-07", "2026-09-08", "2026-09-09"]


def test_scrape_due_for_club_caps_an_absurdly_long_booking_window(tmp_path, monkeypatch):
    # One real club advertises 366 days of tee sheets; scraping a year every pass is
    # not what "the overview window" means.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: {"A": "a"})
    monkeypatch.setattr(scrape_once, "fetch_available_dates",
                        lambda club_id: [f"2026-10-{d:02d}" for d in range(1, 31)])
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    seen = []
    monkeypatch.setattr(scrape_once, "run",
                        lambda club_id, course, date, config, slug: seen.append(date) or [])

    scrape_once.scrape_due_for_club("c", {"club_id": "0000001"})

    assert len(seen) == scrape_once.MAX_OVERVIEW_DAYS


def test_scrape_due_for_club_falls_back_to_overview_days_without_a_date_selector(tmp_path, monkeypatch):
    # 5 of 45 clubs swept have no date selector on the page at all.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: {"A": "a"})
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: [])
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    seen = []
    monkeypatch.setattr(scrape_once, "run",
                        lambda club_id, course, date, config, slug: seen.append(date) or [])

    scrape_once.scrape_due_for_club("c", {"club_id": "0000001", "overview_days": 3})

    assert len(seen) == 3


def test_scrape_due_for_club_still_scrapes_when_the_date_window_fetch_fails(tmp_path, monkeypatch):
    # A failed window lookup falls back to overview_days rather than skipping the club.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: {"A": "a"})

    def boom(club_id):
        raise RuntimeError("no network")

    monkeypatch.setattr(scrape_once, "fetch_available_dates", boom)
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    seen = []
    monkeypatch.setattr(scrape_once, "run",
                        lambda club_id, course, date, config, slug: seen.append(date) or [])

    scrape_once.scrape_due_for_club("c", {"club_id": "0000001", "overview_days": 2})

    assert len(seen) == 2
