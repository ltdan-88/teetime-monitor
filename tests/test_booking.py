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
<select name="rq[players][2][friend][bd_id]"><option value="">- choose a friend -</option><option value="7">Mustermann, Max</option><option value="9">Musterfrau, Erika</option></select>
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
    monkeypatch.setattr(scraper, "fetch_course_aliases", lambda club_id, client=None, fresh=False: fetched.append(client) or {"18 Loch Tee 1": "COUB", COURSE: "COU6"})

    def make(**options):
        fake = FakeSite(**options)
        fake.alias_fetches = fetched
        return fake, httpx.Client(transport=httpx.MockTransport(fake.handler), follow_redirects=True)

    return make


def test_the_partners_offered_are_your_pc_caddie_friends_first_name_first():
    assert booking.partner_choices(FORM) == [{"id": "7", "name": "Max Mustermann"}, {"id": "9", "name": "Erika Musterfrau"}]
    assert booking.partner_choices("<p>no form</p>") == []


def test_partners_go_into_places_two_and_three_as_friends(site):
    fake, client = site()
    prepared = booking.prepare_book(client, CLUB, COURSE, DAY, "08:10")
    booking.commit_book(client, CLUB, COURSE, DAY, "08:10", prepared, partners=["9", "7"])
    first = fake.posts[0]
    assert first["rq[players][2][type]"] == ["friend"] and first["rq[players][2][friend][bd_id]"] == ["9"]
    assert first["rq[players][3][type]"] == ["friend"] and first["rq[players][3][friend][bd_id]"] == ["7"]
    assert first["rq[players][1][type]"] == ["self"] and fake.booked


@pytest.mark.parametrize("partners", [["8"], ["7", "7"], ["7", "9", "7", "9"]])
def test_a_partner_the_form_does_not_offer_is_refused_before_anything_is_sent(site, partners):
    fake, client = site()
    prepared = booking.prepare_book(client, CLUB, COURSE, DAY, "08:10")
    with pytest.raises(booking.BookingError) as refused:
        booking.commit_book(client, CLUB, COURSE, DAY, "08:10", prepared, partners=partners)
    assert refused.value.reason == "bad_partners" and fake.posts == [] and not fake.booked


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


# ---- read ahead, steps, and a page that went stale (2026-10-18) -------------------------------------------------


@pytest.fixture
def through(site, monkeypatch, tmp_path):
    """book_for_club()/cancel_for_club() against the fake site: `session_for` hands out its client (a fresh one when
    asked for, so a test can make the first one run out)."""
    import contextlib

    from src import pipeline, scrape_once

    clients = {}

    def make(**options):
        fake, client = site(**options)
        clients["reused"] = clients["fresh"] = client
        return fake, clients

    @contextlib.contextmanager
    def session_for(club, fresh=False):
        yield clients["fresh" if fresh else "reused"]

    monkeypatch.setattr(booking, "session_for", session_for)
    monkeypatch.setattr(pipeline, "_resolved_config", lambda *a, **k: {})
    monkeypatch.setattr(scrape_once, "_sync_my_reservations", lambda *a, **k: "ok")
    booking._prepared.clear()
    return make, tmp_path / "club.db"


CLUB_ROW = {"id": CLUB, "slug": None, "name": "Club"}


def test_pages_read_while_the_dialog_is_open_leave_only_the_booking_itself_for_the_button(through):
    make, db = through
    fake, _ = make()
    assert booking.prepare(CLUB_ROW, "book", COURSE, DAY, "08:10") == {"ok": True}
    booking._prepared[("book", CLUB, COURSE, DAY, "08:10")][1].wait(5)
    assert booking.prepare(CLUB_ROW, "book", COURSE, DAY, "08:10") == {"ok": True}  # asked again: not read twice
    read_ahead = len(fake.referers)
    assert fake.posts == [] and read_ahead >= 2  # the tee sheet and the form: reading only, nothing reserved
    steps = []
    assert booking.book_for_club(CLUB_ROW, db, COURSE, DAY, "08:10", steps.append) == {"ok": True}
    assert fake.booked and len(fake.posts) == 2  # make this reservation, confirm it
    assert len(fake.referers) - read_ahead == 3  # the two posts and My Reservations: nothing read twice
    assert steps == ["login", "book", "confirm"]


def test_a_form_read_ahead_that_pc_caddie_refuses_is_read_again_once(through):
    make, db = through
    fake, _ = make(taken_after_form=True)
    booking.prepare(CLUB_ROW, "book", COURSE, DAY, "08:10")
    result = booking.book_for_club(CLUB_ROW, db, COURSE, DAY, "08:10")
    assert result["error"] == "rejected" and "just booked" in result["message"]  # the second time, its own words
    assert len(fake.posts) == 2 and not fake.booked  # tried twice, never confirmed


def test_a_session_that_ran_out_mid_way_logs_in_again_and_goes_on(through):
    make, db = through
    fake, clients = make()
    def ran_out(request):  # the public tee sheet still shows; anything behind the login asks for it again
        if "cat=tt_timetable_course" in str(request.url):
            return httpx.Response(200, text=SHEET)
        return httpx.Response(200, text='<form><input name="rq[password]"></form>')

    logged_out = httpx.Client(transport=httpx.MockTransport(ran_out), follow_redirects=True)
    fresh = clients["fresh"]
    clients["reused"] = logged_out
    clients["fresh"] = fresh
    assert booking.book_for_club(CLUB_ROW, db, COURSE, DAY, "08:10") == {"ok": True} and fake.booked


def test_the_page_follows_a_booking_step_by_step(through):
    import time as clock

    make, db = through
    fake, _ = make()
    started = booking.start("book", CLUB_ROW, db, COURSE, DAY, "08:10")
    deadline = clock.time() + 5
    while booking.job(started["job"])["state"] == "running" and clock.time() < deadline:
        clock.sleep(0.02)
    assert booking.job(started["job"]) == {"kind": "book", "state": "ok", "step": "confirm", "error": None, "message": None}
    assert booking.job("nope") is None and booking.start("book", CLUB_ROW, db, COURSE, DAY, "8 Uhr") == {"error": "bad_time"}


def test_cancelling_reads_the_bookings_page_ahead_too(through):
    make, db = through
    fake, _ = make()
    fake.booked = True
    booking.prepare(CLUB_ROW, "cancel", COURSE, DAY, "08:10")
    booking._prepared[("cancel", CLUB, COURSE, DAY, "08:10")][1].wait(5)
    assert fake.posts == []
    assert booking.cancel_for_club(CLUB_ROW, db, COURSE, DAY, "08:10") == {"ok": True} and not fake.booked


def test_my_reservations_read_a_moment_ago_is_not_read_again_unless_asked(monkeypatch, tmp_path):
    import time as clock

    from src import scrape_once

    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    read = []
    monkeypatch.setattr(scrape_once, "_sync_my_reservations", lambda club_id, *a, **k: read.append(club_id) or "ok")
    clubs = [{"slug": "a", "id": "1", "name": "A"}, {"slug": "b", "id": "2", "name": "B"}]
    monkeypatch.setattr(scrape_once, "RESERVATIONS_READ", {str(scrape_once._db_path("1")): clock.time() - 60})
    result = booking.upcoming_reservations(clubs, refresh=True)
    assert read == ["2"] and result["checked_at"] is None  # only the club not read lately; B was never read here
    scrape_once.RESERVATIONS_READ[str(scrape_once._db_path("2"))] = clock.time() - 30
    read.clear()
    result = booking.upcoming_reservations(clubs, refresh=True)
    assert read == [] and result["checked_at"] <= clock.time() - 60  # both fresh: pc caddie is not asked
    booking.upcoming_reservations(clubs, refresh=True, force=True)
    assert sorted(read) == ["1", "2"]  # the button that checks now
