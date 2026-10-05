import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from datetime import date as date_cls

import httpx
import pytest

from src import booking_watch, scrape_once
from src.models import ConfirmedBooking, PlayerSighting, ReservationsSync, Schedule, Slot, SunTimes, WeatherPoint


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
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date, client=None, **_: fake_schedule)

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


def test_run_records_any_players_seen_in_the_scraped_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    fake_schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[
            Slot(
                time="06:00", booked=1, capacity=4, players=["Max Mustermann"],
                player_details=[PlayerSighting(name="Max Mustermann", gender="male", handicap=12.3)],
            ),
            Slot(
                time="07:00", booked=2, capacity=4, players=["Max Mustermann", "Erika Mustermann"],
                player_details=[
                    PlayerSighting(name="Max Mustermann", gender="male", handicap=12.3),
                    PlayerSighting(name="Erika Mustermann", gender="female", member_status="guest"),
                ],
            ),
        ],
    )
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date, client=None, **_: fake_schedule)

    scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={})

    known = {p.name: p for p in scrape_once.storage.load_known_players(path=scrape_once._db_path("0000001"))}
    assert set(known) == {"Max Mustermann", "Erika Mustermann"}
    assert known["Max Mustermann"].gender == "male"
    assert known["Max Mustermann"].handicap == 12.3
    assert known["Erika Mustermann"].member_status == "guest"


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
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date, client=None, **_: next(schedules))

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
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date, client=None, **_: next(schedules))

    scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={"club_id": "0000001"})
    scrape_once.storage.save_confirmed_booking(
        ConfirmedBooking(date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="manual"),
        path=scrape_once._db_path("0000001"),
    )

    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={"club_id": "0000001"})

    assert changes == []


def test_run_works_with_a_bare_empty_config(tmp_path, monkeypatch):
    # Renamed 2026-09-16: this used to be about run() tolerating no
    # credentials for _sync_my_reservations(), but that call moved out of
    # run() entirely (to scrape_due_for_club(), once per pass -- see that
    # function's own docstring) and has its own dedicated tests now. What's
    # left worth checking here is just that run() itself doesn't need
    # anything beyond a bare {} config to work.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        scrape_once,
        "scrape_schedule",
        lambda club_id, course, date, client=None, **_: Schedule(date=date, course=course, slots=[]),
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
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date, client=None, **_: next(schedules))

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
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date, client=None, **_: next(schedules))

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


def test_run_does_not_report_party_grew_on_the_pass_a_booking_is_first_confirmed(tmp_path, monkeypatch):
    # Direct report, 2026-09-20 ("i am the only person booked at 14:20 ... this is not
    # accurate"): the baseline scrape (booked=0) predates the booking; the next scrape
    # (booked=1) is the booking itself landing on the sheet, not another player -- see
    # booking_watch.check_for_changes()'s own docstring for the mechanism this exercises
    # end to end (storage.first_confirmed_at() + baseline_scraped_at, both threaded
    # through by run() itself, not passed by this test).
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    schedules = iter(
        [
            Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=0, capacity=4)]),
            Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=1, capacity=4)]),
        ]
    )
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date, client=None, **_: next(schedules))

    # First call establishes the baseline scrape (booked=0), well before the booking
    # below is ever confirmed.
    scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={})

    scrape_once.storage.save_confirmed_booking(
        ConfirmedBooking(
            date="2026-09-06",
            course="18 Loch Tee 1",
            time="14:00",
            source="my_reservations",
            # Real code (scraper.py) always stamps "now" -- comfortably after the
            # baseline scrape just saved above, same as it would be live.
            confirmed_at=datetime.now(UTC).isoformat(),
        ),
        path=scrape_once._db_path("0000001"),
    )

    changes = scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={})
    assert changes == []


def test_should_scrape_true_when_never_scraped(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    assert scrape_once._should_scrape("0000001", "18 Loch Tee 1", "2026-09-06", {}) is True


def test_should_scrape_false_within_normal_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    recent = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    monkeypatch.setattr(scrape_once.storage, "last_scraped_at", lambda course, date, path: recent)
    monkeypatch.setattr(scrape_once.storage, "load_confirmed_booking", lambda course, date, path: None)

    config = {"scrape_interval_minutes": 360}
    assert scrape_once._should_scrape("0000001", "18 Loch Tee 1", "2026-09-06", config) is False


def test_should_scrape_true_once_normal_interval_elapsed(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    old = (datetime.now(UTC) - timedelta(minutes=400)).isoformat()
    monkeypatch.setattr(scrape_once.storage, "last_scraped_at", lambda course, date, path: old)
    monkeypatch.setattr(scrape_once.storage, "load_confirmed_booking", lambda course, date, path: None)

    config = {"scrape_interval_minutes": 360}
    assert scrape_once._should_scrape("0000001", "18 Loch Tee 1", "2026-09-06", config) is True


def test_should_scrape_uses_shorter_interval_once_booked(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    # 90 minutes ago -- past the 60-min "booked" interval, but well within the 360-min
    # normal one, so this only returns True because a confirmed booking exists.
    recent = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
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
    recent = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
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
    monkeypatch.setattr(scrape_once, "run", lambda club_id, course, date, config, slug, client=None, **_: [fake_change])

    result = scrape_once.scrape_due_for_club("musterhausen", {"club_id": "0000001", "overview_days": 1})

    assert result == [fake_change] * (len(_FAKE_COURSES) * len(_FAKE_DATES))


def test_scrape_due_for_club_force_bypasses_should_scrape(tmp_path, monkeypatch):
    # 2026-09-15, OverviewScreen's own manual 'r' override -- "why don't we
    # integrate those missing features into the overview screen" once
    # the since-retired DayDetailScreen's own 'r' was found to unconditionally
    # re-scrape its one day. _should_scrape() itself is never even called here (asserting the
    # bypass, not just a return value it could coincidentally already give).
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: _FAKE_COURSES)
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: _FAKE_DATES)

    def fail_should_scrape(club_id, course, date, config):
        raise AssertionError("_should_scrape() must not be called when force=True")

    monkeypatch.setattr(scrape_once, "_should_scrape", fail_should_scrape)
    fake_booking = ConfirmedBooking(date="2026-09-07", course="18 Loch Tee 1", time="14:00")
    fake_change = booking_watch.BookingChange(booking=fake_booking, kind="party_grew", message="x", params={})
    monkeypatch.setattr(scrape_once, "run", lambda club_id, course, date, config, slug, client=None, **_: [fake_change])

    result = scrape_once.scrape_due_for_club(
        "musterhausen", {"club_id": "0000001", "overview_days": 1}, force=True
    )

    assert result == [fake_change] * (len(_FAKE_COURSES) * len(_FAKE_DATES))


def test_scrape_due_for_club_syncs_my_reservations_exactly_once_per_pass(tmp_path, monkeypatch):
    # The actual bug this whole round is about: _sync_my_reservations() used to
    # be called from inside run(), once per course x date -- 6 courses/dates
    # here would have meant 6 real logins for the exact same "My Reservations"
    # page, each one a separate chance to fail. Direct feedback, 2026-09-16:
    # "I need you to fix it, especially to make it reliably refresh next time I
    # make a reservation." Moved to scrape_due_for_club() itself, called once
    # regardless of how many course/date combinations end up due.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: _FAKE_COURSES)
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: _FAKE_DATES)
    monkeypatch.setattr(scrape_once, "run", lambda club_id, course, date, config, slug, client=None, **_: [])
    calls = []
    monkeypatch.setattr(
        scrape_once,
        "_sync_my_reservations",
        lambda club_id, slug, db_path, known_courses=None: calls.append((club_id, slug)),
    )

    scrape_once.scrape_due_for_club(
        "musterhausen", {"club_id": "0000001", "overview_days": 1}, force=True
    )

    assert len(_FAKE_COURSES) * len(_FAKE_DATES) > 1  # otherwise this test can't tell 1 from N
    assert calls == [("0000001", "musterhausen")]


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

    def fake_run(club_id, course, date, config, slug, client=None, **_):
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
        scrape_once, "run", lambda club_id, course, date, config, slug, client=None, **_: calls.append((course, date))
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
        lambda club_id, course, date, config, slug, client=None, **_: (seen_configs.append(config), seen_slugs.append(slug)),
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

    def broken(club_id, username, password, known_courses=None):
        raise scrape_once.LoginError("bad credentials")

    monkeypatch.setattr(scrape_once, "scrape_my_reservations", broken)

    db_path = scrape_once._db_path("0000001")
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    assert "login failed" in capsys.readouterr().out
    # Not just a print() any more (2026-09-16, "make it reliably refresh" --
    # print() output is invisible while the Textual TUI has the screen, which
    # is exactly why a real, persistent failure once looked identical to
    # "nothing new to sync"): a real, visible OverviewScreen banner too.
    pending = scrape_once.storage.load_unacknowledged_booking_changes(path=db_path)
    assert len(pending) == 1
    assert pending[0]["kind"] == "reservations_sync_failed"
    assert pending[0]["params"] == {"reason": "login"}


def test_sync_my_reservations_catches_not_implemented(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))

    def not_yet(club_id, username, password, known_courses=None):
        raise NotImplementedError("real booking, unseen row markup")

    monkeypatch.setattr(scrape_once, "scrape_my_reservations", not_yet)

    db_path = scrape_once._db_path("0000001")
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)
    # must not raise -- that's the entire point of this test

    pending = scrape_once.storage.load_unacknowledged_booking_changes(path=db_path)
    assert len(pending) == 1
    assert pending[0]["params"] == {"reason": "parsing"}


def test_sync_my_reservations_does_not_duplicate_an_already_pending_failure_banner(tmp_path, monkeypatch):
    # Every scheduled pass would otherwise write a fresh banner every
    # AUTO_REFRESH_INTERVAL_SECONDS for as long as a login problem persists --
    # burying the overview in duplicates of the exact same warning instead of
    # saying it once.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "wrong-password"))

    def broken(club_id, username, password, known_courses=None):
        raise scrape_once.LoginError("bad credentials")

    monkeypatch.setattr(scrape_once, "scrape_my_reservations", broken)

    db_path = scrape_once._db_path("0000001")
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    assert len(scrape_once.storage.load_unacknowledged_booking_changes(path=db_path)) == 1


def test_sync_my_reservations_saves_confirmed_bookings_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))

    booking = ConfirmedBooking(
        date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="my_reservations", confirmed_at="t1"
    )
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password, known_courses=None: ReservationsSync([booking]))

    db_path = scrape_once._db_path("0000001")
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    saved = scrape_once.storage.load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=db_path)
    assert saved == booking


def test_sync_my_reservations_saves_my_handicap_when_the_page_carries_it(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    monkeypatch.setattr(
        scrape_once, "scrape_my_reservations",
        lambda club_id, username, password, known_courses=None: ReservationsSync([], my_handicap=43.8),
    )

    db_path = scrape_once._db_path("0000001")
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    assert scrape_once.storage.load_my_handicap(path=db_path) == 43.8


def test_sync_my_reservations_never_clobbers_a_cached_handicap_with_a_transient_miss(tmp_path, monkeypatch):
    # A sighting that happens to come back without it (see ReservationsSync's own
    # docstring) must not erase a real value an earlier pass already cached.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    db_path = scrape_once._db_path("0000001")
    scrape_once.storage.save_my_handicap(43.8, path=db_path)

    monkeypatch.setattr(
        scrape_once, "scrape_my_reservations",
        lambda club_id, username, password, known_courses=None: ReservationsSync([], my_handicap=None),
    )
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    assert scrape_once.storage.load_my_handicap(path=db_path) == 43.8


def test_sync_my_reservations_clears_a_previously_pending_failure_banner_once_it_recovers(tmp_path, monkeypatch):
    # A transient problem that resolves itself on the next pass shouldn't leave
    # a stale "couldn't sync" banner sitting there needing a manual `x`.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    db_path = scrape_once._db_path("0000001")

    def broken(club_id, username, password, known_courses=None):
        raise scrape_once.LoginError("transient")

    monkeypatch.setattr(scrape_once, "scrape_my_reservations", broken)
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)
    assert len(scrape_once.storage.load_unacknowledged_booking_changes(path=db_path)) == 1

    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password, known_courses=None: ReservationsSync([]))
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    assert scrape_once.storage.load_unacknowledged_booking_changes(path=db_path) == []


def test_sync_my_reservations_clearing_a_failure_does_not_touch_unrelated_banners(tmp_path, monkeypatch):
    # _clear_reservations_sync_failure() must only ever acknowledge its own
    # kind -- a genuinely still-pending booking-watch banner (a real detected
    # change to someone's tee time) must survive an unrelated sync recovering.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    db_path = scrape_once._db_path("0000001")
    scrape_once.storage.save_booking_change(
        course="18 Loch Tee 1", date="2026-09-19", time="15:30",
        kind="party_grew", message="x", params={"count": 2, "time": "15:30"}, path=db_path,
    )

    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password, known_courses=None: ReservationsSync([]))
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    pending = scrape_once.storage.load_unacknowledged_booking_changes(path=db_path)
    assert [c["kind"] for c in pending] == ["party_grew"]


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
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password, known_courses=None: ReservationsSync([]))

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
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password, known_courses=None: ReservationsSync([]))

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
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password, known_courses=None: ReservationsSync([]))

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
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda club_id, username, password, known_courses=None: ReservationsSync([rebooked]))

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
                        lambda club_id, course, date, config, slug, client=None, **_: seen.append(date) or [])

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
                        lambda club_id, course, date, config, slug, client=None, **_: seen.append(date) or [])

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
                        lambda club_id, course, date, config, slug, client=None, **_: seen.append(date) or [])

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
                        lambda club_id, course, date, config, slug, client=None, **_: seen.append(date) or [])

    scrape_once.scrape_due_for_club("c", {"club_id": "0000001", "overview_days": 2})

    assert len(seen) == 2


# --- Authenticated schedule scraping (2026-09-27) -- one login shared across the
# whole date/course loop, not one per call (same "up to a dozen logins" bug class
# already fixed once here for _sync_my_reservations() above). ----------------------


def test_scrape_due_for_club_shares_one_login_across_every_run_call(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: _FAKE_COURSES)
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: _FAKE_DATES)
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    # _sync_my_reservations() resolves the same credentials and would otherwise make
    # a real network call here -- not what this test is about, see its own tests above.
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda *a, **k: ReservationsSync([]))

    class _FakeClient:
        def close(self):
            pass

    login_calls = []
    fake_client = _FakeClient()

    def fake_login(club_id, username, password):
        login_calls.append((club_id, username, password))
        return fake_client

    monkeypatch.setattr(scrape_once, "login", fake_login)

    seen_clients = []
    monkeypatch.setattr(
        scrape_once, "run",
        lambda club_id, course, date, config, slug, client=None, **_: seen_clients.append(client) or [],
    )

    scrape_once.scrape_due_for_club("musterhausen", {"club_id": "0000001", "overview_days": 1})

    assert len(login_calls) == 1  # exactly one login for the whole pass
    # Every run() call got the exact same client object -- not a fresh login each time.
    assert seen_clients == [fake_client] * (len(_FAKE_COURSES) * len(_FAKE_DATES))


def test_scrape_due_for_club_closes_the_shared_client_when_done(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: {"A": "a"})
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: ["2026-09-07"])
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda *a, **k: ReservationsSync([]))

    closed = []

    class _FakeClient:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(scrape_once, "login", lambda club_id, username, password: _FakeClient())
    monkeypatch.setattr(scrape_once, "run", lambda club_id, course, date, config, slug, client=None, **_: [])

    scrape_once.scrape_due_for_club("musterhausen", {"club_id": "0000001", "overview_days": 1})

    assert closed == [True]


def test_scrape_due_for_club_falls_back_to_anonymous_when_login_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: {"A": "a"})
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: ["2026-09-07"])
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "wrong-password"))
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda *a, **k: ReservationsSync([]))

    def broken_login(club_id, username, password):
        raise scrape_once.LoginError("bad credentials")

    monkeypatch.setattr(scrape_once, "login", broken_login)
    seen_clients = []
    monkeypatch.setattr(
        scrape_once, "run",
        lambda club_id, course, date, config, slug, client=None, **_: seen_clients.append(client) or [],
    )

    scrape_once.scrape_due_for_club("musterhausen", {"club_id": "0000001", "overview_days": 1})

    assert seen_clients == [None]  # anonymous scrape still happened, not skipped
    assert "falling back to anonymous" in capsys.readouterr().out


def test_scrape_due_for_club_stays_anonymous_without_credentials_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: {"A": "a"})
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: ["2026-09-07"])
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("", ""))

    login_calls = []
    monkeypatch.setattr(scrape_once, "login", lambda club_id, username, password: login_calls.append(1))
    seen_clients = []
    monkeypatch.setattr(
        scrape_once, "run",
        lambda club_id, course, date, config, slug, client=None, **_: seen_clients.append(client) or [],
    )

    scrape_once.scrape_due_for_club("musterhausen", {"club_id": "0000001", "overview_days": 1})

    assert login_calls == []
    assert seen_clients == [None]


# --- `--force` on the console script (2026-09-17). A GUI Refresh button that usually
# does nothing, because _should_scrape() correctly decided nothing was due, is
# indistinguishable from a broken button -- see main()'s own docstring. -------------


def test_main_passes_force_through_when_asked(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "list_clubs", lambda *a, **k: ["home"])
    monkeypatch.setattr(scrape_once.club_config, "load_club_config", lambda *a, **k: {"club_id": "0000001"})
    seen = []
    monkeypatch.setattr(scrape_once, "scrape_due_for_club",
                        lambda slug, config, force=False, **_: seen.append(force))

    scrape_once.main(["--force"])
    scrape_once.main(["-f"])
    scrape_once.main([])

    assert seen == [True, True, False]


def test_main_defaults_to_the_normal_interval(tmp_path, monkeypatch):
    # The launchd agent passes no arguments, and must keep self-throttling -- forcing
    # every 15 minutes would hammer pc caddie for no benefit.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "list_clubs", lambda *a, **k: ["home"])
    monkeypatch.setattr(scrape_once.club_config, "load_club_config", lambda *a, **k: {"club_id": "0000001"})
    seen = []
    monkeypatch.setattr(scrape_once, "scrape_due_for_club",
                        lambda slug, config, force=False, **_: seen.append(force))

    scrape_once.main([])

    assert seen == [False]


# --- transient network errors must never escape a pass ------------------------------


def test_sync_my_reservations_catches_a_network_error_and_reports_it(tmp_path, monkeypatch, capsys):
    # Offline after wake / a 5xx on the login POST: before this, httpx errors escaped
    # scrape_due_for_club() and exited the TUI's worker (and main()'s club loop).
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))

    def offline(club_id, username, password, known_courses=None):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(scrape_once, "scrape_my_reservations", offline)

    db_path = scrape_once._db_path("0000001")
    scrape_once._sync_my_reservations("0000001", "musterhausen", db_path)

    assert "reservations sync failed" in capsys.readouterr().out
    pending = scrape_once.storage.load_unacknowledged_booking_changes(path=db_path)
    assert [change["params"] for change in pending] == [{"reason": "other"}]


def test_scrape_due_for_club_survives_being_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))

    def offline(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(scrape_once, "fetch_course_aliases", offline)
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", offline)

    assert scrape_once.scrape_due_for_club("musterhausen", {"club_id": "0000001"}) == []


def test_scrape_due_for_club_falls_back_to_anonymous_when_login_hits_a_network_error(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: {"A": "a"})
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: ["2026-09-07"])
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda *a, **k: ReservationsSync([]))

    def bad_gateway(club_id, username, password):
        request = httpx.Request("POST", "https://example.invalid")
        raise httpx.HTTPStatusError("502", request=request, response=httpx.Response(502, request=request))

    monkeypatch.setattr(scrape_once, "login", bad_gateway)
    seen_clients = []
    monkeypatch.setattr(
        scrape_once, "run",
        lambda club_id, course, date, config, slug, client=None, **_: seen_clients.append(client) or [],
    )

    scrape_once.scrape_due_for_club("musterhausen", {"club_id": "0000001", "overview_days": 1})

    assert seen_clients == [None]


def test_scrape_due_for_club_catches_a_should_scrape_failure_per_course(tmp_path, monkeypatch, capsys):
    # e.g. sqlite "database is locked" while another process writes the same DB.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: {"A": "a", "B": "b"})
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: ["2026-09-07"])

    def flaky_should_scrape(club_id, course, date, config):
        if course == "A":
            raise sqlite3.OperationalError("database is locked")
        return True

    monkeypatch.setattr(scrape_once, "_should_scrape", flaky_should_scrape)
    seen = []
    monkeypatch.setattr(
        scrape_once, "run",
        lambda club_id, course, date, config, slug, client=None, **_: seen.append(course) or [],
    )

    scrape_once.scrape_due_for_club(None, {"club_id": "0000001"})

    assert seen == ["B"]
    assert "database is locked" in capsys.readouterr().out


def test_scrape_due_for_club_stops_the_pass_on_a_network_error(tmp_path, monkeypatch, capsys):
    # One connect timeout means the rest would each wait out their own 15 s too.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: _FAKE_COURSES)
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: _FAKE_DATES)
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    calls = []

    def hanging_run(club_id, course, date, config, slug, client=None, **_):
        calls.append((course, date))
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(scrape_once, "run", hanging_run)

    assert scrape_once.scrape_due_for_club(None, {"club_id": "0000001"}) == []
    assert len(calls) == 1
    assert "stopping this pass" in capsys.readouterr().out


# --- one course-alias fetch per pass ------------------------------------------------


def test_scrape_due_for_club_passes_its_course_aliases_through_to_run(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: _FAKE_COURSES)
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: ["2026-09-07"])
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    seen = []
    monkeypatch.setattr(
        scrape_once, "run",
        lambda club_id, course, date, config, slug, client=None, course_aliases=None, **_: seen.append(course_aliases) or [],
    )

    scrape_once.scrape_due_for_club(None, {"club_id": "0000001"})

    assert seen == [_FAKE_COURSES] * len(_FAKE_COURSES)


def test_run_hands_course_aliases_to_scrape_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    seen = []

    def fake_scrape(club_id, course, date, course_aliases=None, client=None):
        seen.append(course_aliases)
        return Schedule(date=date, course=course, slots=[])

    monkeypatch.setattr(scrape_once, "scrape_schedule", fake_scrape)

    scrape_once.run("0000001", "A", "2026-09-07", config={}, course_aliases={"A": "a"})

    assert seen == [{"A": "a"}]  # not None -- which would make scrape_schedule re-fetch it


# --- an empty scrape never replaces a populated one ----------------------------------


def test_run_refuses_to_save_an_empty_scrape_over_a_populated_one(tmp_path, monkeypatch):
    # pc caddie's intermittent table-less page parsed as 0 slots: saving it blanked the
    # day and made every occupied neighbour a false BUFFER_SHRUNK on the next pass.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    populated = Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=1, capacity=4)])
    schedules = iter([populated, Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[])])
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date, client=None, **_: next(schedules))

    scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={})
    with pytest.raises(scrape_once.EmptyScheduleError):
        scrape_once.run("0000001", "18 Loch Tee 1", "2026-09-06", config={})

    latest = scrape_once.storage.load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001"))
    assert [slot.time for slot in latest.slots] == ["14:00"]


# --- one weather fetch per date per pass, and none after a failure -------------------


def _patch_pass_with_location(monkeypatch, tmp_path, courses, dates):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.global_preferences, "PREFERENCES_FILE", tmp_path / "preferences.yaml")
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: courses)
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: dates)
    monkeypatch.setattr(
        scrape_once, "scrape_schedule",
        lambda club_id, course, date, client=None, **_: Schedule(date=date, course=course, slots=[]),
    )


def test_scrape_due_for_club_fetches_weather_once_per_date_not_per_course(tmp_path, monkeypatch):
    _patch_pass_with_location(monkeypatch, tmp_path, _FAKE_COURSES, _FAKE_DATES)
    hourly_calls = []
    monkeypatch.setattr(
        scrape_once.weather_module, "fetch_hourly_weather",
        lambda lat, lon, date: hourly_calls.append(date) or [WeatherPoint(time="10:00", precipitation_probability=5)],
    )
    monkeypatch.setattr(scrape_once.weather_module, "fetch_sun_times", lambda lat, lon, date: SunTimes("07:00", "19:00"))

    scrape_once.scrape_due_for_club(None, {"club_id": "0000001", "location": {"lat": 50.0, "lon": 8.0}}, force=True)

    assert hourly_calls == _FAKE_DATES
    db_path = scrape_once._db_path("0000001")
    for course in _FAKE_COURSES:  # every course still got the day's forecast attached
        saved = scrape_once.storage.load_latest_schedule(course, _FAKE_DATES[0], path=db_path)
        assert [point.time for point in saved.weather] == ["10:00"]


def test_scrape_due_for_club_stops_fetching_weather_after_the_first_failure(tmp_path, monkeypatch):
    _patch_pass_with_location(monkeypatch, tmp_path, _FAKE_COURSES, _FAKE_DATES)
    hourly_calls = []

    def weather_down(lat, lon, date):
        hourly_calls.append(date)
        raise httpx.ConnectTimeout("open-meteo unreachable")

    monkeypatch.setattr(scrape_once.weather_module, "fetch_hourly_weather", weather_down)

    scrape_once.scrape_due_for_club(None, {"club_id": "0000001", "location": {"lat": 50.0, "lon": 8.0}}, force=True)

    assert len(hourly_calls) == 1
    # The schedules themselves were still saved -- weather is best-effort.
    saved = scrape_once.storage.load_latest_schedule("6 Loch Platz", _FAKE_DATES[-1], path=scrape_once._db_path("0000001"))
    assert saved is not None


# --- one pass per club at a time, across processes ----------------------------------


def test_scrape_due_for_club_skips_while_another_pass_holds_the_club_lock(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "CLUB_LOCK_WAIT_SECONDS", 0)

    def must_not_run(*a, **k):
        raise AssertionError("must not scrape while another pass holds the lock")

    monkeypatch.setattr(scrape_once, "fetch_course_aliases", must_not_run)

    # A separate open() of the lock file conflicts just like another process would.
    with scrape_once._club_lock("0000001") as held:
        assert held
        assert scrape_once.scrape_due_for_club(None, {"club_id": "0000001"}) == []

    assert "another pass still running" in capsys.readouterr().out


def test_scrape_due_for_club_releases_the_club_lock_when_done(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: {"A": "a"})
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: ["2026-09-07"])
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: True)
    monkeypatch.setattr(scrape_once, "run", lambda club_id, course, date, config, slug, client=None, **_: [])

    scrape_once.scrape_due_for_club(None, {"club_id": "0000001"})

    with scrape_once._club_lock("0000001", wait_seconds=0) as acquired:
        assert acquired


def test_club_lock_waits_for_the_other_holder_to_finish(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "_CLUB_LOCK_POLL_SECONDS", 0.01)
    released = threading.Event()

    def hold_briefly():
        with scrape_once._club_lock("0000001") as held:
            assert held
            released.wait(5)

    holder = threading.Thread(target=hold_briefly)
    holder.start()
    try:
        time.sleep(0.05)  # let the holder take the lock first
        threading.Timer(0.1, released.set).start()
        with scrape_once._club_lock("0000001", wait_seconds=5) as acquired:
            assert acquired
            assert released.is_set()  # only got it after the holder let go, not alongside it
    finally:
        released.set()
        holder.join()


# --- booking-watch round length matches recommend.py --------------------------------


@pytest.mark.parametrize(
    ("course", "holes", "round_config", "expected"),
    [
        ("9 Loch Tee 1", 9, {}, 120),  # 9 holes default to 120, not 240
        ("18 Loch Tee 1", 18, {}, 240),
        ("6 Loch Platz", 6, {"nine": 90}, 90),
        ("18 Loch Tee 1", 9, {}, 120),  # the booking's own hole count wins
        ("Kurzplatz", None, {"nine": 100, "eighteen": 200}, 200),  # unknown -> 18, like recommend
        ("9 Loch Tee 1", None, {}, 120),  # unknown on the booking -> the course label
    ],
)
def test_booking_round_minutes(course, holes, round_config, expected):
    booking = ConfirmedBooking(date="2026-09-06", course=course, time="10:00", holes=holes, source="manual")
    config = {"round_duration_minutes": round_config} if round_config else {}

    assert scrape_once._booking_round_minutes(booking, config) == expected


def test_run_watches_a_nine_hole_booking_over_a_nine_hole_window(tmp_path, monkeypatch):
    # Rain only in hours 3-4 after a 9-hole tee-off falls after the round -- no banner.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    preferences_file = tmp_path / "preferences.yaml"
    scrape_once.global_preferences.save_preferences({"preferences": {"avoid_rain": True}}, preferences_file)
    monkeypatch.setattr(scrape_once.global_preferences, "PREFERENCES_FILE", preferences_file)

    def day(late_rain):
        weather = [WeatherPoint(time=f"{hour:02d}:00", precipitation_probability=0) for hour in range(9, 15)]
        weather[4] = WeatherPoint(time="13:00", precipitation_probability=late_rain)
        return Schedule(
            date="2026-09-06", course="9 Loch Tee 1", slots=[Slot(time="10:00", booked=1, capacity=4)], weather=weather
        )

    schedules = iter([day(0), day(90)])
    monkeypatch.setattr(scrape_once, "scrape_schedule", lambda club_id, course, date, client=None, **_: next(schedules))

    scrape_once.run("0000001", "9 Loch Tee 1", "2026-09-06", config={})
    scrape_once.storage.save_confirmed_booking(
        ConfirmedBooking(date="2026-09-06", course="9 Loch Tee 1", time="10:00", holes=9, source="manual"),
        path=scrape_once._db_path("0000001"),
    )

    assert scrape_once.run("0000001", "9 Loch Tee 1", "2026-09-06", config={}) == []


# --- scrape health: one scrape_runs row per scrape_due_for_club() call (2026-10-05) --
# pc caddie rejected the login for ~20 hours and every pass silently went anonymous;
# see storage.py's module docstring. ------------------------------------------------


def _runs(tmp_path, club_id="0000001"):
    with sqlite3.connect(tmp_path / f"{club_id}.db") as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM scrape_runs ORDER BY id")]


def _one_course_pass(monkeypatch, tmp_path, run=None, due=True):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once, "fetch_course_aliases", lambda club_id: {"A": "a", "B": "b"})
    monkeypatch.setattr(scrape_once, "fetch_available_dates", lambda club_id: ["2026-10-05"])
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: due)
    monkeypatch.setattr(
        scrape_once, "run", run or (lambda club_id, course, date, config, slug, client=None, **_: [])
    )


def _with_credentials(monkeypatch, login):
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("max@example.org", "s3cret!"))
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", lambda *a, **k: ReservationsSync([]))
    monkeypatch.setattr(scrape_once, "login", login)


class _FakeClient:
    def close(self):
        pass


def test_a_successful_pass_records_one_run(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"}, source="tui")
    (run,) = _runs(tmp_path)
    assert (run["source"], run["attempted"], run["saved"], run["failed"]) == ("tui", 2, 2, 0)
    assert run["authenticated"] is None  # no credentials configured
    assert run["error_kind"] is None and run["error_message"] is None
    assert run["started_at"] <= run["finished_at"]


def test_a_pass_with_nothing_due_still_records_a_successful_run(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path, due=False)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    (run,) = _runs(tmp_path)
    assert (run["source"], run["attempted"], run["saved"], run["error_kind"]) == ("agent", 0, 0, None)
    assert scrape_once.storage.scrape_health(tmp_path / "0000001.db")["last_success_at"] == run["finished_at"]


def test_a_logged_in_pass_records_authenticated(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)
    _with_credentials(monkeypatch, lambda club_id, username, password: _FakeClient())
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    (run,) = _runs(tmp_path)
    assert run["authenticated"] == 1 and run["error_kind"] is None


def test_a_rejected_login_is_recorded_even_though_the_pass_continues_anonymously(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)

    def rejected(club_id, username, password):
        raise scrape_once.LoginError("Login failed for club 0000001 — check PCC_USER/PCC_PASS in .env.")

    _with_credentials(monkeypatch, rejected)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    (run,) = _runs(tmp_path)
    assert (run["saved"], run["authenticated"], run["error_kind"]) == (2, 0, "login_rejected")
    assert "Login failed for club 0000001" in run["error_message"]
    health = scrape_once.storage.scrape_health(tmp_path / "0000001.db")
    assert health["login_rejected_since"] == run["started_at"]
    assert health["consecutive_failed_runs"] == 0  # data still arrived


def test_a_login_rejected_by_the_reservations_sync_counts_when_the_course_list_fails(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)

    def no_table(club_id):
        raise scrape_once.NoTeeSheetError("Club 0000001 doesn't publish an online tee sheet")

    def rejected(*a, **k):
        raise scrape_once.LoginError("Login failed")

    monkeypatch.setattr(scrape_once, "fetch_course_aliases", no_table)
    monkeypatch.setattr(scrape_once.club_config, "resolve_credentials", lambda slug: ("user", "pass"))
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", rejected)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    (run,) = _runs(tmp_path)
    # Both went wrong, but the pass got nothing because of the course list -- that's the
    # cause the "failing" line must name (2026-10-05, review). authenticated=0 still
    # keeps an ongoing login-rejected streak open (see storage.scrape_health()).
    assert (run["authenticated"], run["error_kind"], run["attempted"]) == (0, "no_tee_sheet", 0)
    health = scrape_once.storage.scrape_health(tmp_path / "0000001.db")
    assert health["consecutive_failed_runs"] == 1


def test_a_course_list_failure_keeps_an_ongoing_login_streak_open(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)

    def rejected(*a, **k):
        raise scrape_once.LoginError("Login failed")

    _with_credentials(monkeypatch, rejected)
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", rejected)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})  # saved anonymously

    def no_table(club_id):
        raise scrape_once.NoTeeSheetError("Club 0000001 doesn't publish an online tee sheet")

    monkeypatch.setattr(scrape_once, "fetch_course_aliases", no_table)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    first, second = _runs(tmp_path)
    assert (second["error_kind"], second["authenticated"]) == ("no_tee_sheet", 0)
    health = scrape_once.storage.scrape_health(tmp_path / "0000001.db")
    assert health["login_rejected_since"] == first["started_at"]


def test_a_pass_that_saved_still_reports_the_rejected_login_over_a_flaky_course(tmp_path, monkeypatch):
    # A success either way -- so the login, the one the user can fix, is what it records
    # (otherwise one flaky course per pass would hide a day-long rejection).
    def flaky(club_id, course, date, config, slug, client=None, **_):
        if course == "B":
            raise scrape_once.EmptyScheduleError("B/2026-10-05 came back with no tee times")
        return []

    _one_course_pass(monkeypatch, tmp_path, run=flaky)

    def rejected(club_id, username, password):
        raise scrape_once.LoginError("Login failed")

    _with_credentials(monkeypatch, rejected)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    (run,) = _runs(tmp_path)
    assert (run["saved"], run["failed"], run["error_kind"]) == (1, 1, "login_rejected")


def test_idle_passes_with_a_rejected_login_warn_about_the_login_not_failing_scrapes(tmp_path, monkeypatch):
    # The 2026-10-03 incident's shape: launchd every 15 min, most passes with nothing due,
    # every one of them rejected at login. Before the 2026-10-05 review fix, three such
    # passes turned the amber login line into a red "Scrapes failing".
    from src import scrape_health

    _one_course_pass(monkeypatch, tmp_path)

    def rejected(*a, **k):
        raise scrape_once.LoginError("Login failed for club 0000001")

    _with_credentials(monkeypatch, rejected)
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", rejected)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})  # one pass that saved
    monkeypatch.setattr(scrape_once, "_should_scrape", lambda *a: False)
    for _ in range(4):
        scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    runs = _runs(tmp_path)
    assert [(r["attempted"], r["authenticated"], r["error_kind"]) for r in runs[1:]] == [(0, 0, "login_rejected")] * 4
    health = scrape_once.storage.scrape_health(tmp_path / "0000001.db")
    assert health["consecutive_failed_runs"] == 0
    assert health["login_rejected_since"] == runs[0]["started_at"]
    now = datetime.fromisoformat(runs[-1]["finished_at"])
    assert scrape_health.health_status(health, 360, now) == ("login_rejected", runs[0]["started_at"])


def test_a_network_error_is_recorded_as_network(tmp_path, monkeypatch):
    def offline(*a, **k):
        raise httpx.ConnectError("[Errno 8] nodename nor servname provided")

    _one_course_pass(monkeypatch, tmp_path, run=offline)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    (run,) = _runs(tmp_path)
    # The pass stops at the first transport error -- only that one pair was attempted.
    assert (run["attempted"], run["saved"], run["failed"], run["error_kind"]) == (1, 0, 1, "network")
    assert "nodename" in run["error_message"]


def test_a_course_list_timeout_is_recorded_as_network(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)

    def timeout(club_id):
        raise httpx.ReadTimeout("The read operation timed out")

    monkeypatch.setattr(scrape_once, "fetch_course_aliases", timeout)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    (run,) = _runs(tmp_path)
    assert (run["attempted"], run["error_kind"]) == (0, "network")


def test_no_tee_sheet_is_recorded_as_no_tee_sheet(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)

    def no_table(club_id):
        raise scrape_once.NoTeeSheetError("Club 0000001 doesn't publish an online tee sheet on pc caddie")

    monkeypatch.setattr(scrape_once, "fetch_course_aliases", no_table)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    (run,) = _runs(tmp_path)
    assert (run["attempted"], run["saved"], run["error_kind"]) == (0, 0, "no_tee_sheet")
    assert scrape_once.storage.scrape_health(tmp_path / "0000001.db")["consecutive_failed_runs"] == 1


def test_one_failing_course_is_recorded_as_other_while_the_rest_save(tmp_path, monkeypatch):
    def flaky(club_id, course, date, config, slug, client=None, **_):
        if course == "B":
            raise scrape_once.EmptyScheduleError("B/2026-10-05 came back with no tee times")
        return []

    _one_course_pass(monkeypatch, tmp_path, run=flaky)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    (run,) = _runs(tmp_path)
    assert (run["attempted"], run["saved"], run["failed"], run["error_kind"]) == (2, 1, 1, "other")


def test_an_error_message_never_carries_the_credentials(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)

    def leaky(club_id, username, password):
        raise scrape_once.LoginError(f"rejected {username} / {password}")

    _with_credentials(monkeypatch, leaky)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    (run,) = _runs(tmp_path)
    assert "max@example.org" not in run["error_message"] and "s3cret!" not in run["error_message"]
    assert run["error_message"] == "rejected *** / ***"


def test_a_pass_that_gave_up_on_the_lock_records_nothing(tmp_path, monkeypatch, capsys):
    # The pass holding the lock records its own row (2026-10-05, review).
    _one_course_pass(monkeypatch, tmp_path)
    monkeypatch.setattr(scrape_once, "CLUB_LOCK_WAIT_SECONDS", 0)
    scrape_once.storage.init_db(tmp_path / "0000001.db")
    with scrape_once._club_lock("0000001"):
        scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    assert _runs(tmp_path) == []
    assert "still running" in capsys.readouterr().out


def test_a_lock_timeout_mid_outage_leaves_the_login_streak_alone(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)

    def rejected(*a, **k):
        raise scrape_once.LoginError("Login failed")

    _with_credentials(monkeypatch, rejected)
    monkeypatch.setattr(scrape_once, "scrape_my_reservations", rejected)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    monkeypatch.setattr(scrape_once, "CLUB_LOCK_WAIT_SECONDS", 0)
    with scrape_once._club_lock("0000001"):
        scrape_once.scrape_due_for_club("home", {"club_id": "0000001"}, source="gui")
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    first, _second = _runs(tmp_path)
    health = scrape_once.storage.scrape_health(tmp_path / "0000001.db")
    assert health["login_rejected_since"] == first["started_at"]
    assert health["consecutive_failed_runs"] == 0


def test_every_call_records_exactly_one_run(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)
    for _ in range(3):
        scrape_once.scrape_due_for_club("home", {"club_id": "0000001"}, source="gui")
    assert [run["source"] for run in _runs(tmp_path)] == ["gui"] * 3


def test_an_unknown_source_is_refused(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        scrape_once.scrape_due_for_club("home", {"club_id": "0000001"}, source="cron")


def test_a_failure_to_record_never_fails_the_pass(tmp_path, monkeypatch, capsys):
    _one_course_pass(monkeypatch, tmp_path)

    def locked(**kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(scrape_once.storage, "record_scrape_run", locked)
    assert scrape_once.scrape_due_for_club("home", {"club_id": "0000001"}) == []
    assert "couldn't record this scrape run" in capsys.readouterr().out


# --- daily backups (2026-10-05) ---------------------------------------------------


def _backups(tmp_path):
    return sorted(path.name for path in (tmp_path / "backups").glob("*.db"))


def test_a_successful_agent_pass_backs_up_the_database_once_a_day(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)
    today = date_cls.today().isoformat()
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    assert _backups(tmp_path) == [f"0000001-{today}.db"]
    backup = tmp_path / "backups" / f"0000001-{today}.db"
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT COUNT(*) FROM scrape_runs").fetchone() == (1,)
    stamp = backup.stat().st_mtime_ns
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    assert backup.stat().st_mtime_ns == stamp  # today's already exists -- left alone


@pytest.mark.parametrize("source", ["tui", "gui"])
def test_interactive_passes_never_back_up(tmp_path, monkeypatch, source):
    _one_course_pass(monkeypatch, tmp_path)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"}, source=source)
    assert not (tmp_path / "backups").exists()


def test_a_failed_agent_pass_does_not_back_up(tmp_path, monkeypatch):
    _one_course_pass(monkeypatch, tmp_path)

    def no_table(club_id):
        raise scrape_once.NoTeeSheetError("no tee sheet")

    monkeypatch.setattr(scrape_once, "fetch_course_aliases", no_table)
    scrape_once.scrape_due_for_club("home", {"club_id": "0000001"})
    assert not (tmp_path / "backups").exists()


def test_backups_keep_only_the_newest_seven_per_club(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    scrape_once.storage.init_db(tmp_path / "0000001.db")
    backups = tmp_path / "backups"
    backups.mkdir()
    for day in range(1, 10):
        (backups / f"0000001-2026-09-{day:02d}.db").write_bytes(b"old")
    (backups / "0352002-2026-09-01.db").write_bytes(b"another club")

    written = scrape_once._daily_backup("0000001", today="2026-10-05")

    assert written == backups / "0000001-2026-10-05.db"
    assert _backups(tmp_path) == [
        "0000001-2026-09-04.db", "0000001-2026-09-05.db", "0000001-2026-09-06.db", "0000001-2026-09-07.db",
        "0000001-2026-09-08.db", "0000001-2026-09-09.db", "0000001-2026-10-05.db", "0352002-2026-09-01.db",
    ]


def test_a_backup_error_is_logged_and_never_fails_the_pass(tmp_path, monkeypatch, capsys):
    _one_course_pass(monkeypatch, tmp_path)

    def disk_full(source, destination):
        raise OSError("No space left on device")

    monkeypatch.setattr(scrape_once.storage, "backup_db", disk_full)
    assert scrape_once.scrape_due_for_club("home", {"club_id": "0000001"}) == []
    assert "daily backup failed: No space left on device" in capsys.readouterr().out
    assert len(_runs(tmp_path)) == 1


# --- `--source` on the console script ---------------------------------------------


def _capture_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scrape_once.club_config, "list_clubs", lambda *a, **k: ["home"])
    monkeypatch.setattr(scrape_once.club_config, "load_club_config", lambda *a, **k: {"club_id": "0000001"})
    seen = []
    monkeypatch.setattr(
        scrape_once, "scrape_due_for_club",
        lambda slug, config, force=False, source="agent": seen.append((force, source)),
    )
    return seen


def test_main_tags_runs_with_the_source_it_was_given(tmp_path, monkeypatch):
    seen = _capture_sources(monkeypatch, tmp_path)
    scrape_once.main(["--force", "--source", "gui"])
    scrape_once.main(["--source=tui"])
    scrape_once.main([])  # launchd passes nothing
    assert seen == [(True, "gui"), (False, "tui"), (False, "agent")]


def test_main_refuses_an_unknown_source(tmp_path, monkeypatch, capsys):
    seen = _capture_sources(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exit_info:
        scrape_once.main(["--source", "cron"])
    assert exit_info.value.code == 2
    assert seen == []
    assert "invalid choice" in capsys.readouterr().err
