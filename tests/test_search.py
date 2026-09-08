from src.models import Schedule, Slot, TimeWindow
from src.search import SearchCriteria, resolve_buffer_minutes, search

# 2026-09-07 is a Monday (weekday), 2026-09-12 is a Saturday (weekend) — used throughout
# to exercise the weekday/weekend window split.


def test_search_finds_open_slot_within_weekday_window():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="18:00", booked=0, capacity=4)],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow(after="17:00"))

    matches = search([schedule], criteria)

    assert len(matches) == 1
    assert matches[0].slot.time == "18:00"
    assert matches[0].date == "2026-09-07"
    assert matches[0].course == "18 Loch Tee 1"


def test_search_excludes_slot_before_window_start():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=0, capacity=4)],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow(after="17:00"))

    assert search([schedule], criteria) == []


def test_search_skips_day_type_with_no_window_configured():
    # Only weekday_window is set -- "weekdays only", per the docstring's stated meaning
    # of leaving weekend_window as None.
    schedule = Schedule(
        date="2026-09-12",  # Saturday
        course="18 Loch Tee 1",
        slots=[Slot(time="11:00", booked=0, capacity=4)],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow(after="17:00"))

    assert search([schedule], criteria) == []


def test_search_applies_weekend_window_on_weekend_dates():
    schedule = Schedule(
        date="2026-09-12",  # Saturday
        course="18 Loch Tee 1",
        slots=[Slot(time="10:30", booked=0, capacity=4)],
    )
    criteria = SearchCriteria(
        weekday_window=TimeWindow(after="17:00"),
        weekend_window=TimeWindow(after="10:00"),
    )

    matches = search([schedule], criteria)
    assert len(matches) == 1


def test_search_respects_min_open_spots():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="18:00", booked=3, capacity=4)],  # only 1 open spot
    )
    criteria = SearchCriteria(min_open_spots=3, weekday_window=TimeWindow())

    assert search([schedule], criteria) == []


def test_search_excludes_blocked_slots():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="18:00", booked=0, capacity=4, block_reason="Golf Beginner Kurs")],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow())

    assert search([schedule], criteria) == []


def test_search_buffer_excludes_slot_too_close_to_another_flight():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="18:00", booked=0, capacity=4),
            Slot(time="18:10", booked=2, capacity=4),  # another flight, 10 min away
        ],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow(), buffer_before_minutes=20, buffer_after_minutes=20)

    matches = search([schedule], criteria)
    # 18:00 is too close to the booked 18:10 neighbor and drops out; 18:10 itself only
    # checks against 18:00 (empty, not "another flight"), so it still passes.
    assert [m.slot.time for m in matches] == ["18:10"]


def test_search_buffer_allows_slot_far_enough_from_another_flight():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="18:00", booked=0, capacity=4),
            Slot(time="18:30", booked=2, capacity=4),  # 30 min away, clears a 20-min buffer
        ],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow(), buffer_before_minutes=20, buffer_after_minutes=20)

    matches = search([schedule], criteria)
    # Both clear the buffer: 18:00 is 30 min from the 18:30 flight, and 18:30 (2 open
    # spots) has only an empty neighbor at 18:00, which doesn't count against it either.
    assert {m.slot.time for m in matches} == {"18:00", "18:30"}


def test_search_buffer_ignores_fully_open_neighbors():
    # A neighboring slot with nobody in it isn't "another flight" -- shouldn't count
    # against the buffer at all, however close it is.
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="18:00", booked=0, capacity=4),
            Slot(time="18:10", booked=0, capacity=4),
        ],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow(), buffer_before_minutes=20, buffer_after_minutes=20)

    matches = search([schedule], criteria)
    assert {m.slot.time for m in matches} == {"18:00", "18:10"}


def test_search_buffer_treats_block_time_as_another_flight():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="18:00", booked=0, capacity=4),
            Slot(time="18:10", booked=0, capacity=4, block_reason="Gäste"),
        ],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow(), buffer_before_minutes=20, buffer_after_minutes=20)

    matches = search([schedule], criteria)
    assert matches == []  # 18:00 is too close to the guest block at 18:10


# --- Asymmetric buffer (2026-09-08, direct follow-up: "does a symmetric buffer make
# sense or should it be adjustable asymmetrically?" -> "split it like in your
# recommendation") -----------------------------------------------------------------


def test_search_buffer_before_alone_rejects_a_close_flight_ahead():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="17:50", booked=2, capacity=4),  # group ahead, 10 min before 18:00
            Slot(time="18:00", booked=0, capacity=4),
        ],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow(), buffer_before_minutes=20, buffer_after_minutes=0)

    matches = search([schedule], criteria)
    assert "18:00" not in {m.slot.time for m in matches}


def test_search_buffer_before_alone_allows_a_close_flight_behind():
    # The flip side: with only buffer_before set, a group behind you -- however
    # close -- doesn't disqualify the slot at all. (Deliberately no earlier
    # neighbor in this schedule, so a naive "use whichever buffer is bigger"
    # implementation that ignores direction entirely would also -- wrongly --
    # reject 18:00 here; only a genuinely direction-aware check keeps it.)
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="18:00", booked=0, capacity=4),
            Slot(time="18:05", booked=2, capacity=4),  # 5 min behind, well inside 20
        ],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow(), buffer_before_minutes=20, buffer_after_minutes=0)

    matches = search([schedule], criteria)
    assert "18:00" in {m.slot.time for m in matches}


def test_search_buffer_after_alone_rejects_a_close_flight_behind():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="18:00", booked=0, capacity=4),
            Slot(time="18:10", booked=2, capacity=4),  # group behind, 10 min after 18:00
        ],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow(), buffer_before_minutes=0, buffer_after_minutes=20)

    matches = search([schedule], criteria)
    assert "18:00" not in {m.slot.time for m in matches}


def test_search_buffer_after_alone_allows_a_close_flight_ahead():
    # The flip side, same reasoning as the "before alone" pair above: no later
    # neighbor in this schedule, so only a genuinely direction-aware check (not a
    # "use whichever buffer is bigger" shortcut) keeps 18:00 in the results.
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="17:55", booked=2, capacity=4),  # 5 min ahead, well inside 20
            Slot(time="18:00", booked=0, capacity=4),
        ],
    )
    criteria = SearchCriteria(weekday_window=TimeWindow(), buffer_before_minutes=0, buffer_after_minutes=20)

    matches = search([schedule], criteria)
    assert "18:00" in {m.slot.time for m in matches}


# --- resolve_buffer_minutes (back-compat reader) ------------------------------------


def test_resolve_buffer_minutes_prefers_the_direction_specific_key():
    availability = {"buffer_before_minutes": 15, "buffer_minutes": 30}
    assert resolve_buffer_minutes(availability, "before") == 15


def test_resolve_buffer_minutes_falls_back_to_the_old_single_key():
    # A config saved before the before/after split (or hand-edited against the old
    # docs) only has the one key -- used for both directions rather than silently
    # losing its buffer protection entirely.
    availability = {"buffer_minutes": 30}
    assert resolve_buffer_minutes(availability, "before") == 30
    assert resolve_buffer_minutes(availability, "after") == 30


def test_resolve_buffer_minutes_default_when_nothing_set():
    assert resolve_buffer_minutes({}, "before", default=20) == 20


def test_search_across_multiple_days():
    schedules = [
        Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="18:00", booked=0, capacity=4)]),
        Schedule(date="2026-09-08", course="18 Loch Tee 1", slots=[Slot(time="19:00", booked=0, capacity=4)]),
    ]
    criteria = SearchCriteria(weekday_window=TimeWindow(after="17:00"))

    matches = search(schedules, criteria)
    assert {(m.date, m.slot.time) for m in matches} == {("2026-09-07", "18:00"), ("2026-09-08", "19:00")}
