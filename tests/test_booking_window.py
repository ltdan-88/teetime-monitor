import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src import booking_window as bw
from src.models import Slot

BERLIN = ZoneInfo("Europe/Berlin")


# --- parse_booking_window() -- the real strings from the maintainer's databases -------


@pytest.mark.parametrize(
    "label, expected",
    [
        # 0497758 (Niederreutin), Kurzplatz and members
        ("4 Tage im Voraus ab 20 Uhr buchbar (KP)", bw.BookingWindow(4, 20)),
        ("Mitglieder 4 Tage im voraus ab 20 Uhr buchbar", bw.BookingWindow(4, 20)),
        # extra text appended without a space: the 11:00 is the Doppelteestart's, not ours
        (
            "Mitglieder 4 Tage im voraus ab 20 Uhr buchbarDoppelteestart 11:00 Uhr, Ihre Startzeit gilt nur für 9-Loch!",
            bw.BookingWindow(4, 20),
        ),
        # 0497745
        ("Startzeiten 3 Tage vorher ab 21 Uhr", bw.BookingWindow(3, 21)),
        # 0497712 (Hetzenhof): no hour at all
        ("Buchung 1 Tag im voraus möglich.", bw.BookingWindow(1, None)),
        # near variants
        ("3 TAGE IM VORAUS AB 9 UHR", bw.BookingWindow(3, 9)),
        ("4 Tage im Voraus ab 20:00 Uhr buchbar", bw.BookingWindow(4, 20)),
        ("4 Tage im Voraus ab 20.30 Uhr buchbar", bw.BookingWindow(4, 20, 30)),
        ("2 Tagen im Voraus ab 08:00 Uhr", bw.BookingWindow(2, 8)),
        ("Gäste: 7 Tage vorher ab 12 Uhr.", bw.BookingWindow(7, 12)),
        ("14 Tage im Voraus", bw.BookingWindow(14, None)),
        ("  1 Tag  im  voraus   ab  18 Uhr ", bw.BookingWindow(1, 18)),
    ],
)
def test_parse_recognises_the_known_notice_shapes(label, expected):
    assert bw.parse_booking_window(label) == expected


@pytest.mark.parametrize(
    "label",
    [
        None,
        "",
        "Kanonenstart 13 Uhr, Sie müssen den Platz bis 12:30 Uhr verlassen haben.",
        "Doppelteestart 11:00 Uhr, Ihre Startzeit gilt nur für 9-Loch!",
        "Dienstag-Ladies",
        "Platzpflege",
        "Greenfee CHF 140.-",
        "Mitglieder buchbar ab 20 Uhr",  # an hour but no number of days
        "3 Tage vor dem Turnier",  # "vor", not "vorher"
        "Turnier 4 Tage",  # no "im Voraus"
        "4 Tage im Voraus ab 25 Uhr buchbar",  # impossible hour: never guess
        "4 Tage im Voraus ab 20:75 Uhr",  # impossible minute
        "0 Tage im Voraus",
        "9999 Tage im Voraus",
        "Booking 4 days in advance from 8pm",  # not German: not recognised
    ],
)
def test_parse_returns_none_for_anything_unrecognised(label):
    assert bw.parse_booking_window(label) is None


def test_an_hour_further_along_is_not_the_notices_hour():
    # "ab 13 Uhr" belongs to the Kanonenstart; the notice itself names no hour.
    assert bw.parse_booking_window("Buchung 1 Tag im voraus möglich. Kanonenstart ab 13 Uhr") == bw.BookingWindow(
        1, None
    )


# --- club_timezone() -------------------------------------------------------------------


def test_club_timezone_defaults_to_berlin():
    assert bw.club_timezone({}).key == "Europe/Berlin"
    assert bw.club_timezone(None).key == "Europe/Berlin"


def test_club_timezone_reads_the_club_yaml_key():
    assert bw.club_timezone({"timezone": "Europe/Lisbon"}).key == "Europe/Lisbon"


@pytest.mark.parametrize("bad", ["Mars/Olympus_Mons", "", "  ", 5, None])
def test_club_timezone_falls_back_to_berlin_for_a_bad_value(bad):
    assert bw.club_timezone({"timezone": bad}).key == "Europe/Berlin"


# --- opens_at_for() --------------------------------------------------------------------


def test_opens_at_is_the_opening_day_at_the_stated_hour_club_local():
    opens = bw.opens_at_for(bw.BookingWindow(4, 20), "2026-10-09", BERLIN)
    assert opens == datetime(2026, 10, 5, 20, 0, tzinfo=BERLIN)
    assert opens.isoformat() == "2026-10-05T20:00:00+02:00"  # CEST


def test_opens_at_without_an_hour_is_the_start_of_the_opening_day():
    opens = bw.opens_at_for(bw.BookingWindow(1, None), "2026-10-08", BERLIN)
    assert opens.isoformat() == "2026-10-07T00:00:00+02:00"


def test_opens_at_counts_calendar_days_across_the_spring_dst_change():
    # 2026-03-29 is the spring-forward day. Tee date the 30th, 3 days ahead: Friday the
    # 27th, still CET (+01:00) -- N x 24 h from the tee date's own offset would be off.
    opens = bw.opens_at_for(bw.BookingWindow(3, 21), "2026-03-30", BERLIN)
    assert opens.isoformat() == "2026-03-27T21:00:00+01:00"
    # And a notice resolving to the change day itself: "1 Tag ... ab 21 Uhr" for the 30th.
    resolved = bw.opens_at_for(bw.BookingWindow(1, 21), "2026-03-30", BERLIN)
    assert resolved.isoformat() == "2026-03-29T21:00:00+02:00"  # already CEST that evening


def test_opens_at_on_the_autumn_change_day_uses_the_new_offset_after_the_change():
    # 2026-10-25 clocks go back at 03:00. 21:00 that day is CET (+01:00).
    opens = bw.opens_at_for(bw.BookingWindow(1, 21), "2026-10-26", BERLIN)
    assert opens.isoformat() == "2026-10-25T21:00:00+01:00"


def test_opens_at_in_the_nonexistent_spring_hour_lands_on_a_real_instant():
    # 02:30 on 2026-03-29 does not exist in Berlin; it must map to a valid wall time.
    opens = bw.opens_at_for(bw.BookingWindow(1, 2, 30), "2026-03-30", BERLIN)
    assert opens.astimezone(UTC) == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    assert opens.isoformat() == "2026-03-29T03:30:00+02:00"


def test_opens_at_in_the_ambiguous_autumn_hour_takes_the_first_occurrence():
    # 02:30 on 2026-10-25 happens twice; the first one is still CEST.
    opens = bw.opens_at_for(bw.BookingWindow(1, 2, 30), "2026-10-26", BERLIN)
    assert opens.isoformat() == "2026-10-25T02:30:00+02:00"


# --- day_booking_status() ---------------------------------------------------------------

NOTICE = "4 Tage im Voraus ab 20 Uhr buchbar (KP)"


def _slots(count: int, reason: str | None = NOTICE, other: int = 0, other_reason: str | None = None):
    slots = [Slot(time=f"{8 + i // 6:02d}:{(i % 6) * 10:02d}", booked=0, capacity=4, block_reason=reason) for i in range(count)]
    slots += [
        Slot(time=f"18:{i:02d}", booked=0, capacity=4, block_reason=other_reason) for i in range(other)
    ]
    return slots


def _berlin(*args):
    return datetime(*args, tzinfo=BERLIN)


def test_status_locked_before_the_opening_time():
    status = bw.day_booking_status(_slots(84), "2026-10-09", _berlin(2026, 10, 5, 18, 28), BERLIN)
    assert status == {"locked": True, "opens_at": _berlin(2026, 10, 5, 20, 0), "hour_known": True}


def test_status_works_from_a_utc_now_like_the_real_scrape_time():
    # The observed case: scraped at 16:28 UTC = 18:28 CEST, opens 20:00 local.
    now = datetime(2026, 10, 5, 16, 28, tzinfo=UTC)
    status = bw.day_booking_status(_slots(84), "2026-10-09", now, BERLIN)
    assert status["locked"] is True
    assert status["opens_at"].isoformat() == "2026-10-05T20:00:00+02:00"


def test_status_not_locked_at_or_after_the_opening_time():
    opening = _berlin(2026, 10, 5, 20, 0)
    for now in (opening, opening + timedelta(minutes=1), opening + timedelta(days=2)):
        assert bw.day_booking_status(_slots(84), "2026-10-09", now, BERLIN) == {
            "locked": False, "opens_at": None, "hour_known": False,
        }


def test_status_hour_unknown_without_an_hour_in_the_notice():
    slots = _slots(80, reason="Buchung 1 Tag im voraus möglich.")
    status = bw.day_booking_status(slots, "2026-10-08", _berlin(2026, 10, 5, 12, 0), BERLIN)
    assert status["locked"] is True and status["hour_known"] is False
    assert status["opens_at"] == _berlin(2026, 10, 7, 0, 0)


def test_status_threshold_is_ninety_percent_of_the_slots():
    now = _berlin(2026, 10, 5, 12, 0)
    # 9 of 10 recognised: locked ...
    assert bw.day_booking_status(_slots(9, other=1), "2026-10-09", now, BERLIN)["locked"] is True
    # ... 8 of 10 is not
    assert bw.day_booking_status(_slots(8, other=2), "2026-10-09", now, BERLIN)["locked"] is False
    # an event blocking a few slots of a locked day does not unlock it
    slots = _slots(80, other=4, other_reason="Kanonenstart 13 Uhr")
    assert bw.day_booking_status(slots, "2026-10-09", now, BERLIN)["locked"] is True


@pytest.mark.parametrize(
    "notices, events, free, locked",
    [
        # The real ratios from the maintainer's databases: event-reserved slots carry the
        # event's name instead of the notice, and the day is still not bookable.
        (73, 11, 0, True),  # 0497758 18 Loch Tee 1, 2026-10-08
        (55, 17, 0, True),  # 0497745, 2026-09-29
        (60, 12, 0, True),  # 0497745, 2026-09-30
        (15, 57, 0, True),  # 0497745, 2026-09-14: "Stadler Trophy" everywhere else
        (44, 40, 0, True),  # 0497758, 2026-10-06
        # but slots with no reason at all count against the day:
        (60, 0, 12, False),
        (60, 12, 12, False),
        (73, 0, 11, False),
        (9, 0, 1, True),  # exactly 90% of the open-looking slots
        (8, 0, 2, False),
        # the sanity floor: a stray few notices among a day of events are not a locked day
        (4, 80, 0, False),  # 4 slots and under 15% of the day
        (5, 80, 0, True),
        (3, 3, 0, True),  # a tiny sheet: 50% of the day
    ],
)
def test_status_ignores_event_blocked_slots_but_not_unblocked_ones(notices, events, free, locked):
    slots = _slots(notices) + _slots(events, reason="Stadler Trophy") + _slots(free, reason=None)
    now = _berlin(2026, 10, 5, 12, 0)
    assert bw.day_booking_status(slots, "2026-10-09", now, BERLIN)["locked"] is locked


def test_status_not_locked_for_an_ordinary_day_or_no_slots():
    now = _berlin(2026, 10, 5, 12, 0)
    assert bw.day_booking_status(_slots(40, reason=None), "2026-10-09", now, BERLIN)["locked"] is False
    assert bw.day_booking_status(_slots(40, reason="Dienstag-Ladies"), "2026-10-09", now, BERLIN)["locked"] is False
    assert bw.day_booking_status([], "2026-10-09", now, BERLIN)["locked"] is False


def test_status_takes_the_most_common_notice_when_slots_disagree():
    # An odd slot with another count of days must not move the whole day's opening.
    slots = _slots(20) + _slots(1, reason="1 Tag im Voraus ab 20 Uhr")
    status = bw.day_booking_status(slots, "2026-10-09", _berlin(2026, 10, 5, 12, 0), BERLIN)
    assert status["opens_at"] == _berlin(2026, 10, 5, 20, 0)


def test_status_a_tie_between_notices_takes_the_earlier_opening():
    slots = _slots(5) + _slots(5, reason="1 Tag im Voraus ab 20 Uhr")
    status = bw.day_booking_status(slots, "2026-10-09", _berlin(2026, 10, 5, 12, 0), BERLIN)
    assert status["opens_at"] == _berlin(2026, 10, 5, 20, 0)


def test_status_across_the_dst_change_day():
    slots = _slots(30, reason="1 Tag im Voraus ab 21 Uhr")
    # Sat 2026-03-28 22:00 CET (= 21:00 UTC): Mon 03-30 opens Sun 03-29 21:00 CEST (= 19:00 UTC).
    now = datetime(2026, 3, 28, 21, 0, tzinfo=UTC)
    status = bw.day_booking_status(slots, "2026-03-30", now, BERLIN)
    assert status["locked"] is True
    assert status["opens_at"].isoformat() == "2026-03-29T21:00:00+02:00"
    # One minute before 19:00 UTC on the 29th: still locked; at 19:00 UTC: open.
    assert bw.day_booking_status(slots, "2026-03-30", datetime(2026, 3, 29, 18, 59, tzinfo=UTC), BERLIN)["locked"]
    assert not bw.day_booking_status(slots, "2026-03-30", datetime(2026, 3, 29, 19, 0, tzinfo=UTC), BERLIN)["locked"]


def test_status_naive_now_is_read_as_club_local():
    status = bw.day_booking_status(_slots(84), "2026-10-09", datetime(2026, 10, 5, 19, 59), BERLIN)
    assert status["locked"] is True
    assert not bw.day_booking_status(_slots(84), "2026-10-09", datetime(2026, 10, 5, 20, 0), BERLIN)["locked"]


@contextmanager
def _machine_timezone(name: str):
    """Run with the *machine's* zone (TZ) set to `name`, restoring it afterwards -- by hand,
    not monkeypatch.undo(), which would also undo the suite's autouse fixtures."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is POSIX only")
    previous = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


@pytest.mark.parametrize("machine_tz", ["America/Los_Angeles", "Asia/Tokyo", "UTC", "Europe/Lisbon"])
def test_club_timezone_decides_the_instant_not_the_machines_zone(machine_tz):
    """The same wall clock "ab 20 Uhr" is a different instant in Lisbon than in Berlin,
    and neither depends on the zone the machine happens to run in."""
    now = datetime(2026, 10, 5, 18, 30, tzinfo=UTC)  # 20:30 Berlin, 19:30 Lisbon
    with _machine_timezone(machine_tz):
        berlin = bw.day_booking_status(_slots(84), "2026-10-09", now, bw.club_timezone({}))
        lisbon = bw.day_booking_status(_slots(84), "2026-10-09", now, bw.club_timezone({"timezone": "Europe/Lisbon"}))
        # a naive "now" is club-local, never machine-local
        naive = bw.day_booking_status(_slots(84), "2026-10-09", datetime(2026, 10, 5, 19, 30), bw.club_timezone({}))
    assert berlin["locked"] is False  # 20:30 CEST is past Berlin's 20:00
    assert lisbon["locked"] is True  # 19:30 WEST is before Lisbon's 20:00
    assert lisbon["opens_at"].isoformat() == "2026-10-05T20:00:00+01:00"
    assert naive["locked"] is True
