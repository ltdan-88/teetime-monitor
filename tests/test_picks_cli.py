import json
from datetime import UTC, datetime

import pytest

from src import clock, global_preferences, picks_cli, pipeline
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
        "too_late": ["16:00"],
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
        "too_late": ["16:00"],
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
        "recommended": ["09:10"],
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
    monkeypatch.setattr(clock, "now_utc", lambda: datetime(2026, 10, 5, 16, 28, tzinfo=UTC))


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
    monkeypatch.setattr(clock, "now_utc", lambda: datetime(2026, 10, 5, 18, 0, tzinfo=UTC))  # 20:00 CEST
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
    real = pipeline._resolved_config
    monkeypatch.setattr(pipeline, "_resolved_config", lambda slug, *a, **k: {**real(slug, *a, **k), "timezone": "Europe/Lisbon"})
    db = tmp_path / "club.db"
    save_schedule(_locked_schedule(), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-09", "--days", "1"])

    assert result["2026-10-09"]["locked"]["opens_at"] == "2026-10-05T20:00:00+01:00"


# --- per-slot markers (2026-10-05): "recommended" / "too_late" ---------------------------

_SUN = SunTimes(sunrise="07:30", sunset="18:50")


def _marker_day(date="2026-10-04", times=("09:00", "09:10", "15:00", "15:10", "17:30"), booked=None, **kwargs):
    booked = booked or {}
    return Schedule(date=date, course="18 Loch Tee 1", sun_times=_SUN, **kwargs,
                    slots=[Slot(time=t, booked=booked.get(t, 0), capacity=4) for t in times])


def test_recommended_and_too_late_slots_are_listed_per_day(tmp_path, capsys):
    # 2026-10-04 is a Sunday; a 240 min round from 15:00 would end 19:00, past the 18:50 sunset.
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": "12:00"}}})
    db = tmp_path / "club.db"
    save_schedule(_marker_day(booked={"09:10": 4}), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-04", "--days", "1"])

    entry = result["2026-10-04"]
    assert entry["recommended"] == ["09:00"]  # 09:10 is full; the afternoon is outside the window
    assert entry["too_late"] == ["15:00", "15:10", "17:30"]
    assert entry["time"] == "09:00"


def test_marker_lists_equal_the_pipeline_functions_slot_by_slot(tmp_path, capsys):
    """Parity: the very functions the TUI's `_compute_slot_rows()` is fed with."""
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": "09:00", "before": "16:00"}}})
    db = tmp_path / "club.db"
    schedule = _marker_day(times=[f"{h:02d}:{m:02d}" for h in range(7, 19) for m in (0, 20, 40)],
                           booked={"10:00": 4, "11:20": 4})
    save_schedule(schedule, path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-04", "--days", "1"])

    config = pipeline._resolved_config(None)
    expected_recommended = sorted(pipeline._recommended_times_for(schedule, config, "club"))
    expected_late = sorted(s.time for s in schedule.slots if pipeline._too_late_for_daylight(s.time, schedule, config))
    assert expected_recommended and expected_late  # the fixture really exercises both
    assert result["2026-10-04"]["recommended"] == expected_recommended
    assert result["2026-10-04"]["too_late"] == expected_late
    assert not set(expected_recommended) & set(expected_late)


def test_marker_keys_are_absent_when_there_is_none(tmp_path, capsys):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    save_schedule(_marker_day(times=("09:00",)), path=db)  # open but early: nothing too late
    save_schedule(_marker_day(date="2026-10-05", times=("09:00",), booked={"09:00": 4}), path=db)  # full: nothing to recommend

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-04", "--days", "2"])

    assert "too_late" not in result["2026-10-04"]
    assert result["2026-10-04"]["recommended"] == ["09:00"]
    assert "recommended" not in result["2026-10-05"] and "too_late" not in result["2026-10-05"]


def test_no_markers_without_sun_times(tmp_path, capsys):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-10-04", course="18 Loch Tee 1", slots=[Slot(time="17:30", booked=0, capacity=4)]), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-04", "--days", "1"])

    assert "too_late" not in result["2026-10-04"]  # unknown, not assumed bad (as the TUI)


def test_too_late_needs_no_availability_rules_but_a_day_without_any_stays_null(tmp_path, capsys):
    db = tmp_path / "club.db"  # no preferences saved at all
    save_schedule(_marker_day(), path=db)
    save_schedule(_marker_day(date="2026-10-05", times=("09:00",)), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-04", "--days", "2"])

    assert result["2026-10-04"] == {"time": None, "window": None, "too_late": ["15:00", "15:10", "17:30"]}
    assert result["2026-10-05"] is None  # unchanged from before markers existed


def test_unplayable_day_has_no_star_but_keeps_its_moons(tmp_path, capsys):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": "15:00", "before": None}}})
    db = tmp_path / "club.db"
    save_schedule(_marker_day(times=("15:00", "15:10")), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-04", "--days", "1"])

    entry = result["2026-10-04"]
    assert entry["unplayable"] == ["daylight"]
    assert "recommended" not in entry
    assert entry["too_late"] == ["15:00", "15:10"]


def test_locked_day_has_no_star_and_keeps_the_tuis_moons(tmp_path, capsys, _scrape_clock):
    global_preferences.save_preferences({"availability": {"weekday_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    locked = _locked_schedule(count=6)
    locked.sun_times = SunTimes(sunrise="07:30", sunset="08:30")  # 08:00..08:50: 08:00 onwards can't finish
    save_schedule(locked, path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-09", "--days", "1"])

    entry = result["2026-10-09"]
    assert entry["locked"]["hour_known"] is True
    assert "recommended" not in entry
    assert entry["too_late"] == ["08:00", "08:10", "08:20", "08:30", "08:40", "08:50"]


def test_locked_day_with_a_few_open_slots_marks_them_exactly_like_the_tui(tmp_path, capsys, _scrape_clock):
    """Parity with the TUI itself: booking_opening() tolerates a few unblocked slots, and
    _compute_slot_rows() ★-marks those (no lock check), so picks_cli must too."""
    from src import tui

    global_preferences.save_preferences({"availability": {"weekday_window": {"after": "09:00", "before": "17:00"}}})
    db = tmp_path / "club.db"
    locked = _locked_schedule(count=36)  # 08:00..13:50, 2026-10-09 (a Friday)
    for slot in locked.slots:
        if slot.time in ("10:20", "12:00"):
            slot.block_reason = None
    locked.sun_times = SunTimes(sunrise="07:30", sunset="17:30")  # a 240 min round from 13:40 on cannot finish
    save_schedule(locked, path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-09", "--days", "1"])

    entry = result["2026-10-09"]
    assert "locked" in entry
    config = pipeline._resolved_config(None)
    rows = tui._compute_slot_rows(
        locked, config, "metric", "2026-10-09", pipeline._recommended_times_for(locked, config, "club"), None
    )
    tui_stars = sorted(row.time for row in rows if row.time_cell.startswith("\u2605"))
    tui_moons = sorted(row.time for row in rows if row.time_cell.startswith("\U0001f319"))
    assert tui_stars  # the fixture really has open, in-window slots
    assert tui_moons
    assert entry["recommended"] == tui_stars
    assert entry["too_late"] == tui_moons


def test_fully_locked_day_still_has_no_star(tmp_path, capsys, _scrape_clock):
    global_preferences.save_preferences({"availability": {"weekday_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    save_schedule(_locked_schedule(count=30), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-09", "--days", "1"])

    assert "recommended" not in result["2026-10-09"]


def test_slots_already_past_today_carry_no_marker(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: "2026-10-04")
    monkeypatch.setattr(clock, "now_hhmm", lambda: "15:05")
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    save_schedule(_marker_day(times=("09:00", "15:00", "15:10", "17:30")), path=db)

    result, _ = _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-04", "--days", "1"])

    entry = result["2026-10-04"]
    assert entry.get("recommended", []) == []  # 09:00 is past (like the TUI); the rest cannot finish
    assert entry["too_late"] == ["15:10", "17:30"]  # 15:00 is past


def test_marker_lists_come_from_the_cached_pipeline_without_a_second_ranking(tmp_path, capsys, monkeypatch):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    save_schedule(_marker_day(times=("09:00", "09:10")), path=db)
    calls = []
    real = pipeline._availability_pipeline

    def counting(schedule, config, club_id, cache=None):
        calls.append(schedule.date)
        return real(schedule, config, club_id, cache)

    monkeypatch.setattr(pipeline, "_availability_pipeline", counting)
    from src import recommend as recommend_module

    ranked = []
    real_ranked = recommend_module.ranked_matches
    monkeypatch.setattr(recommend_module, "ranked_matches", lambda *a, **k: ranked.append(1) or real_ranked(*a, **k))

    _run(capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-10-04", "--days", "1"])

    assert len(ranked) == 1  # one ranking for the pick and the ★ list together
