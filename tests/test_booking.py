"""src/booking.py against a small fake of pc caddie (an httpx MockTransport), shaped like the real pages captured
2026-10-14: the tee sheet's hidden "Book now" row, the two-step form with its one-time `process`/`cati` values, the
confirm page, My Reservations and the cancellation page."""

import httpx
import pytest

from src import booking, scraper

CLUB = "0497758"
COURSE = "6 Loch Platz"
DAY = "2026-10-16"

SHEET = """
<table>
<tr class="pcco-tt-time-person" data-time="08:10" data-status="bookable" data-seat_bookable="4"><td>08:10</td></tr>
<tr id="pcco-tt-time-action-0810" class="pcco-tt-time-action hidden" data-time="08:10" data-status="bookable">
  <td><a href="/clubs/0497758/app.php?cat=tt_book&amp;way=timetable&amp;als_id=498&amp;date=2026-10-16&amp;time=08%3A10">Book now</a></td></tr>
<tr class="pcco-tt-time-person" data-time="08:20" data-status="occupied" data-seat_bookable="0"><td>08:20</td></tr>
<tr id="pcco-tt-time-action-0820" class="pcco-tt-time-action hidden" data-time="08:20" data-status="occupied"><td>full</td></tr>
<tr class="pcco-tt-time-person" data-time="08:30" data-status="disable-time" data-seat_bookable="4"><td>4 Tage im Voraus ab 20 Uhr buchbar</td></tr>
</table>
"""

FORM = """
<form id="frm_book_data" action="/clubs/0497758/app.php?cat=tt_book" method="post">
<input type="hidden" name="form_start" value="data_start">
<input type="hidden" name="process" value="TOKEN-ONE">
<input type="hidden" name="cati" value="1791997807">
<input type="radio" name="rq[teetimes][]" value="2026-10-16|08:10|498" checked>
<input type="checkbox" name="rq[players][1][option][a]" value="CART">
<input type="radio" name="rq[players][1][type]" value="self" checked>
<input type="radio" name="rq[players][2][type]" value="friend">
<select name="rq[players][2][friend][bd_id]"><option value="">-</option><option value="7">Max</option></select>
<input type="radio" name="rq[players][2][type]" value="ignore" checked>
<input type="text" name="rq[players][2][search][name]" value="">
<button class="btn" type="submit" name="cat" value="tt_timetable_course">Go back</button>
<button class="btn blue" name="task" value="prebook">Make this reservation</button>
<input type="hidden" name="form_end" value="data_end">
</form>
"""

PREBOOK = """
<form id="frm_book_prebook" action="/clubs/0497758/app.php?cat=tt_book" method="post">
<input type="hidden" name="form_start" value="prebook_start">
<input type="hidden" name="process" value="TOKEN-TWO">
<input type="hidden" name="cati" value="1791997845">
<button type="submit" name="task" value="finish">Confirm booking</button>
<button type="submit" name="task" value="cancel">Cancel booking</button>
<input type="hidden" name="form_end" value="prebook_end">
</form>
"""

ROW = """
<table class="meine-buchungen">
<tr><th>Details</th><th>Persons</th><th>Actions</th></tr>
<tr><td>Fri, 2026-10-16, 08:10 o'clock<br>Golfclub Domäne Niederreutin<br>6 Loch Platz</td><td>Khoe, Roberto *<br></td>
<td><a href="app.php?cat=reservations&amp;sel=1792131000%7C89%7C104&amp;task=view">Cancel</a></td></tr>
</table>
"""
NO_ROWS = "<html>No bookings found.</html>"

CANCEL_PAGE = """
<form action="/clubs/0497758/app.php?cat=reservations" method="post">
<input type="hidden" name="process" value="TOKEN-THREE">
<input type="checkbox" name="cancel[]" value="927308" checked> [927308] Khoe, Roberto
<button type="submit" name="task" value="back">Back to the overview</button>
<button type="submit" name="task" value="cancel_selected">Cancel selected bookings</button>
</form>
"""


class FakeSite:
    """A tiny pc caddie: remembers what was posted and whether the booking exists."""

    def __init__(self, *, taken_after_form: bool = False, never_appears: bool = False, cancel_sticks: bool = False):
        self.posts: list[dict[str, list[str]]] = []
        self.booked = False
        self.taken_after_form = taken_after_form
        self.never_appears = never_appears
        self.cancel_sticks = cancel_sticks
        self.referers: list[str | None] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.referers.append(request.headers.get("referer"))
        url = str(request.url)
        if request.method == "GET":
            if "cat=tt_timetable_course" in url:
                return httpx.Response(200, text=SHEET)
            if "cat=tt_book" in url:
                return httpx.Response(200, text=FORM)
            if "task=view" in url:
                return httpx.Response(200, text=CANCEL_PAGE)
            if "cat=reservations" in url:
                return httpx.Response(200, text=ROW if self.booked else NO_ROWS)
        else:
            fields: dict[str, list[str]] = {}
            from urllib.parse import parse_qsl

            for name, value in parse_qsl(request.content.decode(), keep_blank_values=True):
                fields.setdefault(name, []).append(value)
            self.posts.append(fields)
            if fields.get("form_start") == ["data_start"]:
                return httpx.Response(200, text="<p class='alert'>This time was just booked.</p>" if self.taken_after_form else PREBOOK)
            if fields.get("task") == ["finish"]:
                self.booked = not self.never_appears
                return httpx.Response(200, text="<h2>Booking completed</h2>")
            if fields.get("task") == ["cancel_selected"]:
                self.booked = self.cancel_sticks
                return httpx.Response(200, text="<p>cancelled</p>")
        return httpx.Response(404, text="?")


@pytest.fixture
def site(monkeypatch):
    fetched = []
    monkeypatch.setattr(scraper, "fetch_course_aliases", lambda club_id, client=None: fetched.append(client) or {"18 Loch Tee 1": "COUB", COURSE: "COU6"})

    def make(**options):
        fake = FakeSite(**options)
        fake.alias_fetches = fetched
        return fake, httpx.Client(transport=httpx.MockTransport(fake.handler), follow_redirects=True)

    return make


def test_booking_walks_the_two_steps_and_reads_the_result_from_my_reservations(site):
    fake, client = site()
    result = booking.book_slot(client, CLUB, COURSE, DAY, "08:10")
    assert (result.course, result.date, result.time) == (COURSE, DAY, "08:10") and fake.booked
    first, second = fake.posts
    # step 2: exactly what the browser sends, the page's own one-time values passed back, only the pressed button
    assert first["task"] == ["prebook"] and first["process"] == ["TOKEN-ONE"] and first["cati"] == ["1791997807"]
    assert first["rq[teetimes][]"] == ["2026-10-16|08:10|498"] and first["rq[players][1][type]"] == ["self"]
    assert first["rq[players][2][type]"] == ["ignore"] and "rq[players][1][option][a]" not in first  # no cart unless ticked
    assert "cat" not in first  # the "Go back" button is not pressed
    assert second["task"] == ["finish"] and second["process"] == ["TOKEN-TWO"]
    assert any(r and "cat=tt_timetable_course" in r for r in fake.referers)  # it comes from the tee sheet, like a click


def test_a_full_or_closed_time_is_refused_before_anything_is_sent(site):
    fake, client = site()
    with pytest.raises(booking.BookingError) as taken:
        booking.book_slot(client, CLUB, COURSE, DAY, "08:20")
    assert taken.value.reason == "taken"
    with pytest.raises(booking.BookingError) as closed:
        booking.book_slot(client, CLUB, COURSE, DAY, "08:30")
    assert closed.value.reason == "taken" or closed.value.reason == "not_bookable"
    with pytest.raises(booking.BookingError) as missing:
        booking.book_slot(client, CLUB, COURSE, DAY, "23:50")
    assert missing.value.reason == "not_bookable"
    assert fake.posts == []


def test_someone_faster_is_reported_with_pc_caddies_own_words(site):
    fake, client = site(taken_after_form=True)
    with pytest.raises(booking.BookingError) as error:
        booking.book_slot(client, CLUB, COURSE, DAY, "08:10")
    assert error.value.reason == "rejected" and "just booked" in error.value.message
    assert not fake.booked and len(fake.posts) == 1  # it stopped before confirming


def test_a_booking_that_never_shows_in_my_reservations_is_not_called_a_success(site):
    _, client = site(never_appears=True)
    with pytest.raises(booking.BookingError) as error:
        booking.book_slot(client, CLUB, COURSE, DAY, "08:10")
    assert error.value.reason == "unconfirmed"


def test_an_unknown_course_is_refused(site):
    _, client = site()
    with pytest.raises(booking.BookingError) as error:
        booking.book_slot(client, CLUB, "Nowhere", DAY, "08:10")
    assert error.value.reason == "unknown_course"


def test_cancelling_follows_the_row_to_the_booking_page_and_checks_it_is_gone(site):
    fake, client = site()
    fake.booked = True
    booking.cancel_booking(client, CLUB, COURSE, DAY, "08:10")
    assert not fake.booked
    [posted] = fake.posts
    assert posted["task"] == ["cancel_selected"] and posted["cancel[]"] == ["927308"] and posted["process"] == ["TOKEN-THREE"]


def test_cancelling_what_is_not_booked_says_so_and_sends_nothing(site):
    fake, client = site()
    with pytest.raises(booking.BookingError) as error:
        booking.cancel_booking(client, CLUB, COURSE, DAY, "08:10")
    assert error.value.reason == "not_found" and fake.posts == []


def test_a_cancellation_that_does_not_stick_is_not_called_done(site):
    fake, client = site(cancel_sticks=True)
    fake.booked = True
    with pytest.raises(booking.BookingError) as error:
        booking.cancel_booking(client, CLUB, COURSE, DAY, "08:10")
    assert error.value.reason == "unconfirmed"


def test_a_booking_past_its_cancellation_time_says_so(monkeypatch):
    html = ROW.replace('<a href="app.php?cat=reservations&amp;sel=1792131000%7C89%7C104&amp;task=view">Cancel</a>', "Not cancelable")
    with pytest.raises(booking.BookingError) as error:
        booking._cancel_link(html, COURSE, DAY, "08:10")
    assert error.value.reason == "not_cancelable"


def test_the_row_is_found_in_german_too():
    german = ROW.replace("Fri, 2026-10-16, 08:10 o'clock", "Fr, 16.10.2026, 08:10 Uhr")
    assert "sel=" in booking._cancel_link(german, COURSE, DAY, "08:10")


def test_the_session_looks_like_a_browser_but_names_this_program():
    agent = booking.user_agent()
    assert agent.startswith("Mozilla/5.0") and "Chrome/" in agent and "teetime-monitor/" in agent


def test_the_form_serializer_follows_the_browser_rules():
    from bs4 import BeautifulSoup

    form = BeautifulSoup(FORM, "html.parser").find("form")
    data = booking._form_data(form, ("task", "prebook"))
    assert data["rq[players][2][friend][bd_id]"] == [""]  # a select with no selection sends its first option
    assert data["rq[players][2][search][name]"] == [""]  # an empty text field is still sent
    assert "rq[players][2][type]" in data and data["rq[players][2][type]"] == ["ignore"]  # only the checked radio


def test_booking_asks_for_the_course_list_once_on_the_sessions_own_connection(site):
    fake, client = site()
    booking.book_slot(client, CLUB, COURSE, DAY, "08:10")
    assert fake.alias_fetches == [client]  # not again for the verification, and not on a connection of its own


def test_cancelling_asks_for_the_course_list_once_too(site):
    fake, client = site()
    fake.booked = True
    booking.cancel_booking(client, CLUB, COURSE, DAY, "08:10")
    assert fake.alias_fetches == [client]


def test_the_page_that_verified_the_booking_comes_back_for_recording(site):
    fake, client = site()
    booked = booking.book_slot(client, CLUB, COURSE, DAY, "08:10")
    assert [(b.course, b.date, b.time) for b in booked.sync.bookings] == [(COURSE, DAY, "08:10")]
    cancelled = booking.cancel_booking(client, CLUB, COURSE, DAY, "08:10")
    assert cancelled.sync.bookings == []
