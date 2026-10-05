import json
from datetime import UTC, datetime

import pytest

from src import global_preferences, picks_cli
from src.models import Schedule, Slot, SunTimes
from src.storage import save_schedule


@pytest.fixture(autouse=True)
def _isolated_preferences(monkeypatch, tmp_path):
    monkeypatch.setattr(global_preferences, "PREFERENCES_FILE", tmp_path / "preferences.yaml")


def _run(capsys, argv):
    exit_code = 0
    try:
        picks_cli.main(argv)
    except SystemExit as exc:
        exit_code = exc.code
    return json.loads(capsys.readouterr().out), exit_code


def test_missing_db_path_or_course_is_rejected(capsys):
    result, code = _run(capsys, ["--course", "18 Loch Tee 1"])
    assert result == {"error": "missing --db-path or --course"}
    assert code == 1


def test_every_date_is_null_when_no_availability_is_configured(tmp_path, capsys):
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-27", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=0, capacity=4),
    ]), path=db)

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-27", "--days", "2"]
    )

    assert code == 0
    assert result == {"2026-09-27": None, "2026-09-28": None}


def test_picks_the_best_playable_slot_for_each_date(tmp_path, capsys):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    # 2026-09-27 is a Sunday
    save_schedule(Schedule(date="2026-09-27", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=0, capacity=4),
        Slot(time="18:00", booked=4, capacity=4),  # full -- shouldn't be picked
    ]), path=db)

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-27", "--days", "1"]
    )

    assert code == 0
    assert result["2026-09-27"]["time"] == "09:10"
    assert result["2026-09-27"]["reasons"] == []  # ai_assist.enabled defaults to off


def test_null_for_a_date_with_no_schedule_scraped_yet(tmp_path, capsys):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-27", "--days", "1"]
    )

    assert code == 0
    assert result == {"2026-09-27": None}


def test_null_when_nothing_is_playable(tmp_path, capsys):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-27", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=4, capacity=4),  # full
    ]), path=db)

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-27", "--days", "1"]
    )

    assert code == 0
    # A scraped day with no pick is an object now, not null (2026-09-27, bundle C
    # of the TUI/GUI consistency audit) -- the GUI needs its window regardless.
    # Nothing matched at all here (the only slot is full), so no `unplayable`.
    assert result == {"2026-09-27": {"time": None, "window": {"after": None, "before": None}}}


def test_reports_why_a_day_has_no_pick_and_the_window_too_late_hint(tmp_path, capsys):
    """The GUI shows "too dark to finish" and the standing hint from these, the
    same way the TUI does -- decided here, not re-derived in Swift."""
    global_preferences.save_preferences({"availability": {"weekday_window": {"after": "16:00"}}})
    db = tmp_path / "club.db"
    for day in ("2026-09-28", "2026-09-29"):  # Monday, Tuesday
        save_schedule(Schedule(
            date=day, course="18 Loch Tee 1",
            slots=[Slot(time="16:00", booked=0, capacity=4)],
            sun_times=SunTimes(sunrise="07:20", sunset="19:10"),
        ), path=db)

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-28", "--days", "2"]
    )

    assert code == 0
    assert result["2026-09-28"] == {
        "time": None, "window": {"after": "16:00", "before": None}, "unplayable": ["daylight"],
    }
    assert result["_hint"] == {
        "window_after": "16:00", "latest_start": "15:10", "sunset": "19:10", "round_minutes": 240, "days": 2,
    }


def test_offers_a_shorter_round_when_daylight_alone_rules_out_the_selected_course(tmp_path, capsys):
    """2026-10-05: `alternative` per date plus `alternative_courses` in the hint
    -- the GUI only displays these, never re-derives them."""
    global_preferences.save_preferences({"availability": {"weekday_window": {"after": "16:00"}}})
    db = tmp_path / "club.db"
    sun = SunTimes(sunrise="07:30", sunset="18:50")
    for day in ("2026-10-05", "2026-10-06"):  # Monday, Tuesday
        save_schedule(Schedule(date=day, course="18 Loch Tee 1",
                               slots=[Slot(time="16:00", booked=0, capacity=4)], sun_times=sun), path=db)
    # A 9-hole course only scraped for Monday, plus a course of unknown length.
    save_schedule(Schedule(date="2026-10-05", course="9 Loch Tee 1",
                           slots=[Slot(time="16:10", booked=0, capacity=4)], sun_times=sun), path=db)
    save_schedule(Schedule(date="2026-10-06", course="Kurzplatz",
                           slots=[Slot(time="16:10", booked=0, capacity=4)], sun_times=sun), path=db)

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-05", "--days", "2"]
    )

    assert code == 0
    assert result["2026-10-05"] == {
        "time": None, "window": {"after": "16:00", "before": None}, "unplayable": ["daylight"],
        "alternative": {"course": "9 Loch Tee 1", "time": "16:10", "holes": 9},
    }
    assert "alternative" not in result["2026-10-06"]  # absent, not null -- older GUIs never see it
    assert result["_hint"]["alternative_courses"] == ["9 Loch Tee 1"]


def test_no_alternative_on_a_day_that_has_a_pick(tmp_path, capsys):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    sun = SunTimes(sunrise="07:30", sunset="18:50")
    save_schedule(Schedule(date="2026-10-04", course="18 Loch Tee 1",
                           slots=[Slot(time="09:00", booked=0, capacity=4)], sun_times=sun), path=db)
    save_schedule(Schedule(date="2026-10-04", course="9 Loch Tee 1",
                           slots=[Slot(time="09:10", booked=0, capacity=4)], sun_times=sun), path=db)

    result, _ = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-04", "--days", "1"]
    )

    assert result["2026-10-04"]["time"] == "09:00"
    assert "alternative" not in result["2026-10-04"]


def test_ai_ranked_pick_includes_real_reasons_when_enabled(tmp_path, monkeypatch, capsys):
    global_preferences.save_preferences({
        "availability": {"weekend_window": {"after": None, "before": None}},
        "ai_assist": {"enabled": True},
    })
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-27", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=0, capacity=4),
    ]), path=db)

    from src import tui as tui_module

    def fake_rank_slots(candidates, context, preferences, provider, model, language):
        for c in candidates:
            c.score = 90.0
            c.reasons = ["dry", "calm"]
        return candidates

    monkeypatch.setattr(tui_module.recommend.ai_assist, "rank_slots", fake_rank_slots)

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-27", "--days", "1"]
    )

    assert code == 0
    assert result["2026-09-27"] == {
        "time": "09:10", "score": 90.0, "reasons": ["dry", "calm"], "window": {"after": None, "before": None},
    }


def test_club_slug_merges_that_clubs_own_yaml(tmp_path, capsys):
    # PicksClient.swift always passes --club-slug when a club is selected; the
    # club's own file (here an older per-club `availability` block) must apply.
    from src import club_config

    club_config.CLUBS_DIR.mkdir(parents=True, exist_ok=True)
    (club_config.CLUBS_DIR / "musterhausen.yaml").write_text(
        "club_id: '0000001'\navailability:\n  weekend_window: {after: '09:00'}\n", encoding="utf-8"
    )
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-27", course="18 Loch Tee 1", slots=[  # a Sunday
        Slot(time="08:30", booked=0, capacity=4),  # before the club's window
        Slot(time="09:10", booked=0, capacity=4),
    ]), path=db)

    result, code = _run(capsys, [
        "--db-path", str(db), "--course", "18 Loch Tee 1", "--club-slug", "musterhausen",
        "--from", "2026-09-27", "--days", "1",
    ])

    assert code == 0
    assert result["2026-09-27"]["time"] == "09:10"
    assert result["2026-09-27"]["window"] == {"after": "09:00", "before": None}


def test_unknown_club_slug_falls_back_to_global_settings_and_still_exits_0(tmp_path, capsys):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-27", course="18 Loch Tee 1", slots=[
        Slot(time="08:30", booked=0, capacity=4),
    ]), path=db)

    result, code = _run(capsys, [
        "--db-path", str(db), "--course", "18 Loch Tee 1", "--club-slug", "no-such-club",
        "--from", "2026-09-27", "--days", "1",
    ])

    assert code == 0
    assert result["2026-09-27"]["time"] == "08:30"


# --- locked days (2026-10-05): "locked" -------------------------------------------------

_NOTICE = "4 Tage im Voraus ab 20 Uhr buchbar (KP)"


def _locked_schedule(date="2026-10-09", reason=_NOTICE, count=30):
    return Schedule(date=date, course="18 Loch Tee 1", slots=[
        Slot(time=f"{8 + i // 6:02d}:{(i % 6) * 10:02d}", booked=0, capacity=4, block_reason=reason) for i in range(count)
    ])


@pytest.fixture
def _scrape_clock(monkeypatch):
    # 18:28 CEST on 2026-10-05, the observed scrape (16:28 UTC)
    monkeypatch.setattr(picks_cli, "_NOW", lambda: datetime(2026, 10, 5, 16, 28, tzinfo=UTC))


def test_a_locked_day_carries_when_it_opens(tmp_path, capsys, _scrape_clock):
    db = tmp_path / "club.db"
    save_schedule(_locked_schedule(), path=db)

    result, code = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-09", "--days", "1"])

    assert code == 0
    # no availability rules configured: still reported, with no window
    assert result == {
        "2026-10-09": {"time": None, "window": None,
                       "locked": {"opens_at": "2026-10-05T20:00:00+02:00", "hour_known": True}},
    }


def test_a_locked_day_without_a_notice_hour_says_so(tmp_path, capsys, _scrape_clock):
    db = tmp_path / "club.db"
    save_schedule(_locked_schedule("2026-10-08", reason="Buchung 1 Tag im voraus möglich."), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-08", "--days", "1"])

    assert result["2026-10-08"]["locked"] == {"opens_at": "2026-10-07T00:00:00+02:00", "hour_known": False}


def test_the_locked_key_is_absent_for_an_open_day(tmp_path, capsys, _scrape_clock):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-10-11", course="18 Loch Tee 1", slots=[Slot(time="09:10", booked=0, capacity=4)]), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-11", "--days", "1"])

    assert "locked" not in result["2026-10-11"]
    assert result["2026-10-11"]["time"] == "09:10"


def test_the_locked_key_is_absent_once_the_opening_time_has_passed(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(picks_cli, "_NOW", lambda: datetime(2026, 10, 5, 18, 0, tzinfo=UTC))  # 20:00 CEST
    db = tmp_path / "club.db"
    save_schedule(_locked_schedule(), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-09", "--days", "1"])

    assert result == {"2026-10-09": None}


def test_a_locked_day_has_no_pick_even_with_availability_rules(tmp_path, capsys, _scrape_clock):
    global_preferences.save_preferences({"availability": {"weekday_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    save_schedule(_locked_schedule(), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-09", "--days", "1"])

    entry = result["2026-10-09"]
    assert entry["time"] is None
    assert entry["window"] == {"after": None, "before": None}
    assert entry["locked"]["hour_known"] is True
    assert "unplayable" not in entry and "alternative" not in entry
    assert "_hint" not in result


def test_the_club_timezone_decides_when_a_day_opens(tmp_path, capsys, monkeypatch, _scrape_clock):
    from src import tui

    real = tui._resolved_config
    monkeypatch.setattr(tui, "_resolved_config", lambda slug, *a, **k: {**real(slug, *a, **k), "timezone": "Europe/Lisbon"})
    db = tmp_path / "club.db"
    save_schedule(_locked_schedule(), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-09", "--days", "1"])

    assert result["2026-10-09"]["locked"]["opens_at"] == "2026-10-05T20:00:00+01:00"
