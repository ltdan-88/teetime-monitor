from bs4 import BeautifulSoup

from src import scraper as scraper_module
from src.scraper import (
    STATUS_BLOCK_TIME,
    STATUS_BOOKABLE,
    STATUS_DISABLE_TIME,
    STATUS_OCCUPIED,
    LoginError,
    _event_names,
    _parse_club_directory_html,
    _parse_course_aliases_html,
    _parse_my_reservations_html,
    _parse_slot_row,
    club_url,
    fetch_club_directory,
    fetch_course_aliases,
    login,
    parse_schedule_html,
    parse_seats_free,
    scrape_my_reservations,
)


def test_parse_seats_free_extracts_count():
    assert parse_seats_free("seats-free-2 tt-grau") == 2


def test_parse_seats_free_full_empty_slot():
    assert parse_seats_free("seats-free-4 tt-grau") == 4


def test_parse_seats_free_blocked_row():
    assert parse_seats_free("seats-free-4 tt-rot pcco-tt-filter-display") == 4


def test_parse_seats_free_no_match_returns_none():
    assert parse_seats_free("some-other-class") is None


def test_club_url_bare():
    assert club_url("0000001", "tt_timetable_course") == (
        "https://www.pccaddie.net/clubs/0000001/app.php?cat=tt_timetable_course"
    )


def test_club_url_with_date_and_alias():
    url = club_url("0000001", "tt_timetable_course", date="2026-09-05", alias="COUB")
    assert url == (
        "https://www.pccaddie.net/clubs/0000001/app.php?cat=tt_timetable_course"
        "&date=DAY|2026-09-05&alias=ALIAS|COUB"
    )


# ---------------------------------------------------------------------------
# Fixture HTML below is reconstructed to match the confirmed real structure
# (see docs/pccaddie-markup-notes.md and the scraper.py module docstring) —
# not raw copy-pasted HTML, which would carry session tokens. Each row is
# wrapped in a bare <table> so BeautifulSoup parses <tr>/<td> correctly; a
# single row is pulled back out for _parse_slot_row(), a whole table for
# parse_schedule_html().


def _row(row_html: str):
    """Parse one <tr> fragment and return the Tag, the way _parse_slot_row expects."""
    soup = BeautifulSoup(f"<table>{row_html}</table>", "html.parser")
    return soup.select_one("tr")


def test_parse_slot_row_fully_open():
    row = _row(
        '<tr class="pcco-tt-time-person" data-time="06:00" data-status="bookable" '
        'data-seat_bookable="4">'
        '<td class="seats-free-4 tt-grau"><time class="pcco-tt-timestamp">06:00</time></td>'
        '<td colspan="4"><span class="tt-show-name"></span></td>'
        "</tr>"
    )
    slot = _parse_slot_row(row)
    assert slot.time == "06:00"
    assert slot.booked == 0
    assert slot.capacity == 4
    assert slot.players == []
    assert slot.block_reason is None


def test_parse_slot_row_anonymized_bookings_not_treated_as_players():
    # Two anonymized members booked ("Belegt" + the long-form German placeholder), two
    # seats still open — both anonymized variants must be excluded from `players`, not
    # just the first one (this is the exact bug caught live 2026-09-06 for "Belegt").
    row = _row(
        '<tr class="pcco-tt-time-person" data-time="06:40" data-status="bookable" '
        'data-seat_bookable="2">'
        '<td class="seats-free-2 tt-grau"><time class="pcco-tt-timestamp">06:40</time></td>'
        '<td><span class="tt-show-name tt-show-male">Belegt</span>'
        '<span class="tt-show-hcp">Member (16.3)</span></td>'
        '<td><span class="tt-show-name tt-show-female">Namensanzeige nach dem Login</span>'
        '<span class="tt-show-hcp">Member (20.5)</span></td>'
        '<td colspan="2"><span class="tt-show-name"></span></td>'
        "</tr>"
    )
    slot = _parse_slot_row(row)
    assert slot.booked == 2
    assert slot.players == []
    assert slot.block_reason is None


def test_parse_slot_row_fully_booked_all_anonymized_variants():
    # All 4 known anonymized-label variants in one row — none should leak into players.
    row = _row(
        '<tr class="pcco-tt-time-person" data-time="07:00" data-status="occupied" '
        'data-seat_bookable="0">'
        '<td class="seats-free-0 tt-grau"><time class="pcco-tt-timestamp">07:00</time></td>'
        '<td><span class="tt-show-name tt-show-male">Occupied</span></td>'
        '<td><span class="tt-show-name tt-show-female">Please login to see names</span></td>'
        '<td><span class="tt-show-name tt-show-male">Belegt</span></td>'
        '<td><span class="tt-show-name tt-show-male">Namensanzeige nach dem Login</span></td>'
        "</tr>"
    )
    slot = _parse_slot_row(row)
    assert slot.booked == 4
    assert slot.capacity == 4
    assert slot.players == []
    assert slot.block_reason is None


def test_parse_slot_row_real_name_is_kept_as_player():
    # A non-placeholder name (hypothetical friend booking, per docs/pccaddie-markup-
    # notes.md's "not yet observed on the real site" example) must survive as a player
    # -- but only on an authenticated fetch, since pc caddie never shows a real name to
    # a logged-out reader. See _parse_slot_row()'s `authenticated` parameter.
    row = _row(
        '<tr class="pcco-tt-time-person" data-time="08:00" data-status="bookable" '
        'data-seat_bookable="3">'
        '<td class="seats-free-3 tt-grau"><time class="pcco-tt-timestamp">08:00</time></td>'
        '<td><span class="tt-show-name tt-show-male">Max Mustermann</span>'
        '<span class="tt-show-hcp">(12.4)</span></td>'
        '<td colspan="3"><span class="tt-show-name"></span></td>'
        "</tr>"
    )
    slot = _parse_slot_row(row, authenticated=True)
    assert slot.booked == 1
    assert slot.players == ["Max Mustermann"]
    assert slot.block_reason is None


def test_parse_slot_row_unknown_seat_text_is_a_note_not_a_player_when_anonymous():
    # The same markup read anonymously -- which is the only way scrape_schedule()
    # ever reads it. Logged out, pc caddie shows no real names at all, so unrecognized
    # seat text is a club's own note ("Greenfee CHF 140.-", "Nur fuer Mitglieder"):
    # recording it as a player fabricated ~50 fake names across the 2026-09-07
    # cross-club sweep.
    row = _row(
        '<tr class="pcco-tt-time-person" data-time="08:00" data-status="bookable" '
        'data-seat_bookable="3">'
        '<td class="seats-free-3 tt-grau"><time class="pcco-tt-timestamp">08:00</time></td>'
        '<td><span class="tt-show-name">Greenfee CHF 140.-</span></td>'
        '<td colspan="3"><span class="tt-show-name"></span></td>'
        "</tr>"
    )
    slot = _parse_slot_row(row)
    assert slot.players == []
    assert slot.block_reason == "Greenfee CHF 140.-"


def test_parse_slot_row_merged_free_seat_cell_note_is_never_a_player():
    # The colspan rule: pc caddie merges the still-free seats into one trailing
    # <td colspan=N>, and that cell often carries a course note rather than being
    # empty. Confirmed on 27 of 45 real clubs swept 2026-09-07.
    row = _row(
        '<tr class="pcco-tt-time-person" data-time="08:20" data-status="bookable" '
        'data-seat_bookable="2">'
        '<td class="seats-free-2 tt-grau"><time class="pcco-tt-timestamp">08:20</time></td>'
        '<td><span class="tt-show-name">Namensanzeige nach dem Login</span></td>'
        '<td><span class="tt-show-name">Namensanzeige nach dem Login</span></td>'
        '<td colspan="2"><span class="tt-show-name">Nur fuer Mitglieder</span></td>'
        "</tr>"
    )
    slot = _parse_slot_row(row)
    assert slot.booked == 2  # the two real occupants, not the note
    assert slot.players == []
    assert slot.block_reason == "Nur fuer Mitglieder"


def test_parse_slot_row_clamps_negative_seat_bookable():
    # Two real clubs report a negative free-seat count on an over-full slot (one said
    # "-12" on a row visibly showing all 4 seats taken). Taken literally that produced
    # a nonsensical "16/4 booked".
    row = _row(
        '<tr class="pcco-tt-time-person" data-time="11:00" data-status="past-time" '
        'data-seat_bookable="-12">'
        '<td class="seats-free-0 tt-grau"><time class="pcco-tt-timestamp">11:00</time></td>'
        '<td><span class="tt-show-name">Namensanzeige nach dem Login</span></td>'
        "</tr>"
    )
    slot = _parse_slot_row(row)
    assert (slot.booked, slot.capacity) == (4, 4)


def test_parse_slot_row_block_time_event():
    row = _row(
        '<tr class="pcco-tt-time-person" data-time="15:30" data-status="block-time" '
        'data-seat_bookable="4">'
        '<td class="seats-free-4 tt-rot pcco-tt-filter-display">'
        '<time class="pcco-tt-timestamp">15:30</time></td>'
        '<td colspan="4"><span class="tt-show-name">FC 110 After Work (E)</span></td>'
        "</tr>"
    )
    slot = _parse_slot_row(row)
    assert slot.block_reason == "FC 110 After Work (E)"
    assert slot.players == []


def test_parse_slot_row_disable_time_advance_booking_window():
    # The advance-booking-window notice — a distinct data-status from block-time, found
    # live 2026-09-06, but must be handled the same way (not a real player name).
    row = _row(
        '<tr class="pcco-tt-time-person" data-time="18:00" data-status="disable-time" '
        'data-seat_bookable="4">'
        '<td class="seats-free-4 tt-grau"><time class="pcco-tt-timestamp">18:00</time></td>'
        '<td colspan="4"><span class="tt-show-name">4 Tage im Voraus ab 20 Uhr '
        "buchbar (KP)</span></td>"
        "</tr>"
    )
    slot = _parse_slot_row(row)
    assert slot.block_reason == "4 Tage im Voraus ab 20 Uhr buchbar (KP)"
    assert slot.players == []


def test_parse_slot_row_block_time_with_an_empty_label():
    # Confirmed live 2026-09-08 (Sonnenberg): a real block-time row whose merged
    # free-seat cell has no text at all -- blocked, with nothing shown on the site
    # itself to say why. Faithfully "" (not None -- still not real occupancy); a
    # display fallback is tui.py's own job, not this parser's.
    row = _row(
        '<tr class="pcco-tt-time-person" data-time="10:00" data-status="block-time" '
        'data-seat_bookable="4">'
        '<td class="seats-free-4 tt-rot"><time class="pcco-tt-timestamp">10:00</time></td>'
        '<td colspan="4"><span class="tt-show-name"></span></td>'
        "</tr>"
    )
    slot = _parse_slot_row(row)
    assert slot.block_reason == ""
    assert slot.players == []


def test_parse_slot_row_falls_back_to_seats_free_class_without_data_attr():
    # No data-seat_bookable at all — parse_seats_free() on the time cell's class is the
    # documented fallback path.
    row = _row(
        '<tr class="pcco-tt-time-person" data-time="09:00" data-status="bookable">'
        '<td class="seats-free-2 tt-grau"><time class="pcco-tt-timestamp">09:00</time></td>'
        '<td><span class="tt-show-name tt-show-male">Occupied</span></td>'
        '<td colspan="3"><span class="tt-show-name"></span></td>'
        "</tr>"
    )
    slot = _parse_slot_row(row)
    assert slot.booked == 2


def test_parse_schedule_html_full_page():
    html = f"""
    <html><body>
    <table class="pcco-tt-timetable some-other-class">
      <tr class="pcco-tt-time-person" data-time="06:00" data-status="{STATUS_BOOKABLE}"
          data-seat_bookable="4">
        <td class="seats-free-4 tt-grau"><time class="pcco-tt-timestamp">06:00</time></td>
        <td colspan="4"><span class="tt-show-name"></span></td>
      </tr>
      <tr class="pcco-tt-time-person" data-time="07:00" data-status="{STATUS_OCCUPIED}"
          data-seat_bookable="0">
        <td class="seats-free-0 tt-grau"><time class="pcco-tt-timestamp">07:00</time></td>
        <td><span class="tt-show-name tt-show-male">Belegt</span></td>
        <td><span class="tt-show-name tt-show-female">Occupied</span></td>
        <td><span class="tt-show-name tt-show-male">Occupied</span></td>
        <td><span class="tt-show-name tt-show-male">Occupied</span></td>
      </tr>
      <tr class="pcco-tt-time-person" data-time="15:30" data-status="{STATUS_BLOCK_TIME}"
          data-seat_bookable="4">
        <td class="seats-free-4 tt-rot"><time class="pcco-tt-timestamp">15:30</time></td>
        <td colspan="4"><span class="tt-show-name">Golf Beginner Kurs</span></td>
      </tr>
      <tr class="pcco-tt-time-person" data-time="18:00" data-status="{STATUS_DISABLE_TIME}"
          data-seat_bookable="4">
        <td class="seats-free-4 tt-grau"><time class="pcco-tt-timestamp">18:00</time></td>
        <td colspan="4"><span class="tt-show-name">4 Tage im Voraus ab 20 Uhr buchbar (KP)</span></td>
      </tr>
    </table>
    </body></html>
    """
    schedule = parse_schedule_html(html, date="2026-09-06", course="18 Loch Tee 1")

    assert schedule.date == "2026-09-06"
    assert schedule.course == "18 Loch Tee 1"
    assert len(schedule.slots) == 4
    assert schedule.available_courses == ["18 Loch Tee 1", "9 Loch Tee 1", "6 Loch Platz"]

    # Every real occupancy row parsed with zero false-positive player names — the exact
    # invariant the live 1092-slot sweep (2026-09-06) confirmed against production data.
    assert all(slot.players == [] for slot in schedule.slots)

    # Only the genuine block-time row counts as a day-level event -- disable-time is
    # just a booking-window notice, not a day-level event, and must not show up here
    # (2026-09-08 fix: it was incorrectly flooding into events/the overview's Weather
    # column before this).
    assert schedule.events == ["Golf Beginner Kurs"]

    open_slot, full_slot, blocked_slot, disabled_slot = schedule.slots
    assert (open_slot.booked, open_slot.capacity) == (0, 4)
    assert (full_slot.booked, full_slot.capacity) == (4, 4)
    assert blocked_slot.block_reason == "Golf Beginner Kurs"
    assert disabled_slot.block_reason == "4 Tage im Voraus ab 20 Uhr buchbar (KP)"


def test_parse_schedule_html_missing_table_returns_empty_schedule():
    schedule = parse_schedule_html("<html><body>no table here</body></html>", date="2026-09-06", course="18 Loch Tee 1")
    assert schedule.slots == []
    assert schedule.events == []


# _event_names() -- factored out 2026-09-08 so schedule.events only ever reflects a
# genuine block-time row, never a disable-time advance-booking notice (that had been
# silently flooding into events, and from there into the overview's Weather column
# and calendar_context's "tournament" day-type classification, both of which treat any
# non-empty events as a day-level flag).


def test_event_names_includes_block_time_reasons():
    rows = [
        _row(
            '<tr data-status="block-time"><td colspan="4">'
            '<span class="tt-show-name">Herbstturnier</span></td></tr>'
        )
    ]
    assert _event_names(rows) == ["Herbstturnier"]


def test_event_names_excludes_disable_time_reasons():
    # An advance-booking-window notice is a per-slot booking-window mechanic, not a
    # day-level event -- must never show up here even though it does carry a
    # block_reason on the Slot itself.
    rows = [
        _row(
            '<tr data-status="disable-time"><td colspan="4">'
            '<span class="tt-show-name">4 Tage im Voraus ab 20 Uhr buchbar (KP)</span>'
            "</td></tr>"
        )
    ]
    assert _event_names(rows) == []


def test_event_names_excludes_blank_block_time_labels():
    # A real block-time row can carry an empty label (confirmed live 2026-09-08,
    # Sonnenberg) -- an empty string isn't a meaningful event name to show.
    rows = [_row('<tr data-status="block-time"><td colspan="4"><span class="tt-show-name"></span></td></tr>')]
    assert _event_names(rows) == []


def test_event_names_deduplicates_and_sorts():
    rows = [
        _row('<tr data-status="block-time"><td><span class="tt-show-name">Zebra Cup</span></td></tr>'),
        _row('<tr data-status="block-time"><td><span class="tt-show-name">Alpha Cup</span></td></tr>'),
        _row('<tr data-status="block-time"><td><span class="tt-show-name">Zebra Cup</span></td></tr>'),
    ]
    assert _event_names(rows) == ["Alpha Cup", "Zebra Cup"]


# ---------------------------------------------------------------------------
# login() / scrape_my_reservations() -- tested against a fake httpx.Client, never a
# real network call or a real password. The real login form's field names
# (service / rq[login] / rq[password]) and POST target were confirmed 2026-09-06 by
# inspecting the live, already-authenticated-by-the-user session's login form directly
# — Claude never entered or saw a real password to get this.


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Records calls and returns canned responses — stands in for httpx.Client."""

    def __init__(self, post_response_text: str = "", get_response_text: str = ""):
        self.post_calls: list[tuple[str, dict]] = []
        self.get_calls: list[str] = []
        self.closed = False
        self._post_response_text = post_response_text
        self._get_response_text = get_response_text

    def post(self, url, data=None):
        self.post_calls.append((url, data))
        return _FakeResponse(self._post_response_text)

    def get(self, url):
        self.get_calls.append(url)
        return _FakeResponse(self._get_response_text)

    def close(self):
        self.closed = True


def test_login_posts_the_confirmed_field_names(monkeypatch):
    fake_client = _FakeClient(post_response_text="<html>Welcome back</html>")
    monkeypatch.setattr(scraper_module.httpx, "Client", lambda **kwargs: fake_client)

    client = login("0000001", "user@example.com", "hunter2")

    assert client is fake_client
    url, data = fake_client.post_calls[0]
    assert url == "https://www.pccaddie.net/clubs/0000001/app.php?cat=start"
    assert data == {"service": "login", "rq[login]": "user@example.com", "rq[password]": "hunter2"}


def test_login_raises_when_response_still_shows_the_login_form(monkeypatch):
    fake_client = _FakeClient(post_response_text='<input type="password" name="rq[password]">')
    monkeypatch.setattr(scraper_module.httpx, "Client", lambda **kwargs: fake_client)

    try:
        login("0000001", "user@example.com", "wrong-password")
        assert False, "expected LoginError"
    except LoginError:
        pass

    assert fake_client.closed  # doesn't leak a client for a session that never authenticated


def test_scrape_my_reservations_returns_empty_list_for_confirmed_empty_state(monkeypatch):
    fake_client = _FakeClient(
        post_response_text="<html>Welcome back</html>",
        get_response_text="<html>No bookings found.</html>",
    )
    monkeypatch.setattr(scraper_module.httpx, "Client", lambda **kwargs: fake_client)

    result = scrape_my_reservations("0000001", "user@example.com", "hunter2")

    assert result == []
    assert fake_client.closed
    assert fake_client.get_calls[0] == "https://www.pccaddie.net/clubs/0000001/app.php?cat=reservations"


def test_scrape_my_reservations_raises_for_unrecognized_markup(monkeypatch):
    fake_client = _FakeClient(
        post_response_text="<html>Welcome back</html>",
        get_response_text="<html><table><tr><td>14:00</td></tr></table></html>",
    )
    monkeypatch.setattr(scraper_module.httpx, "Client", lambda **kwargs: fake_client)

    try:
        scrape_my_reservations("0000001", "user@example.com", "hunter2")
        assert False, "expected NotImplementedError"
    except NotImplementedError:
        pass

    assert fake_client.closed  # cleaned up even though parsing raised


# Real "My Reservations" row markup, confirmed live 2026-09-07 against an actual demo
# booking (see scraper.py's module docstring) — the Details cell's three lines
# (date/time, club name, course name) confirmed in both languages; the Persons/Actions
# cells' real content is trimmed to the minimum needed to look like a real row, since
# ConfirmedBooking has no players field to parse them into.
_REAL_ROW_HTML_EN = """
<table class="table table-bordered table-striped table-condensed cf meine-buchungen">
<tr><th>Details</th><th>Persons</th><th class="hideprint pcco-actions">Actions</th></tr>
<tr>
<td>Mon, 2026-09-07, 19:50 o'clock<br>Golfclub Domäne Musterhausen<br>6 Loch Platz</td>
<td>Mustermann, Max *<br></td>
<td>Show</td>
</tr>
</table>
"""

_REAL_ROW_HTML_DE = """
<table class="table table-bordered table-striped table-condensed cf meine-buchungen">
<tr><th>Details</th><th>Personen</th><th class="hideprint pcco-actions">Aktionen</th></tr>
<tr>
<td>Mo, 07.09.2026, 19:50 Uhr<br>Golfclub Domäne Musterhausen<br>6 Loch Platz</td>
<td>Mustermann, Max *<br></td>
<td>Anzeigen</td>
</tr>
</table>
"""


def test_parse_my_reservations_html_empty_state_english():
    assert _parse_my_reservations_html("<html>No bookings found.</html>") == []


def test_parse_my_reservations_html_empty_state_german():
    assert _parse_my_reservations_html("<html>Keine Buchungen gefunden.</html>") == []


def test_parse_my_reservations_html_raises_for_unrecognized_markup():
    try:
        _parse_my_reservations_html("<html><table><tr><td>14:00</td></tr></table></html>")
        assert False, "expected NotImplementedError"
    except NotImplementedError:
        pass


def test_parse_my_reservations_html_parses_a_real_booking_english():
    [booking] = _parse_my_reservations_html(_REAL_ROW_HTML_EN)
    assert booking.date == "2026-09-07"
    assert booking.time == "19:50"
    assert booking.course == "6 Loch Platz"
    assert booking.holes == 6
    assert booking.source == "my_reservations"
    assert booking.confirmed_at  # a real ISO timestamp was stamped, not left blank


def test_parse_my_reservations_html_parses_a_real_booking_german():
    [booking] = _parse_my_reservations_html(_REAL_ROW_HTML_DE)
    assert booking.date == "2026-09-07"
    assert booking.time == "19:50"
    assert booking.course == "6 Loch Platz"


def test_scrape_my_reservations_returns_confirmed_bookings_for_a_real_row(monkeypatch):
    fake_client = _FakeClient(post_response_text="<html>Welcome back</html>", get_response_text=_REAL_ROW_HTML_EN)
    monkeypatch.setattr(scraper_module.httpx, "Client", lambda **kwargs: fake_client)

    [booking] = scrape_my_reservations("0000001", "user@example.com", "hunter2")

    assert (booking.date, booking.time, booking.course) == ("2026-09-07", "19:50", "6 Loch Platz")
    assert fake_client.closed


# ---------------------------------------------------------------------------
# fetch_club_directory() -- confirmed 2026-09-07 by inspecting "My Golf" live: the
# whole platform directory sits in one <select>, not fetched per keystroke.

_CLUB_DIRECTORY_HTML = """
<select id="user_association_club" name="rq[user_association_club]">
<option value=""></option>
<option value="0352001">[0352001] Golf Club Grand Ducal de Luxembourg</option>
<option value="0491605">[0491605] 1. Golfclub Leipzig e.V.</option>
<option value="0000001">[0000001] Golfclub Domäne Musterhausen e.V.</option>
</select>
"""


def test_parse_club_directory_html_extracts_id_and_name():
    entries = _parse_club_directory_html(_CLUB_DIRECTORY_HTML)
    assert entries == [
        ("0352001", "Golf Club Grand Ducal de Luxembourg"),
        ("0491605", "1. Golfclub Leipzig e.V."),
        ("0000001", "Golfclub Domäne Musterhausen e.V."),
    ]


def test_parse_club_directory_html_skips_the_blank_placeholder_option():
    entries = _parse_club_directory_html(_CLUB_DIRECTORY_HTML)
    assert all(club_id for club_id, _ in entries)


def test_parse_club_directory_html_raises_for_unrecognized_markup():
    try:
        _parse_club_directory_html("<html><body>no select here</body></html>")
        assert False, "expected NotImplementedError"
    except NotImplementedError:
        pass


def test_fetch_club_directory_returns_parsed_entries(monkeypatch):
    fake_client = _FakeClient(post_response_text="<html>Welcome back</html>", get_response_text=_CLUB_DIRECTORY_HTML)
    monkeypatch.setattr(scraper_module.httpx, "Client", lambda **kwargs: fake_client)

    entries = fetch_club_directory("0000001", "user@example.com", "hunter2")

    assert ("0000001", "Golfclub Domäne Musterhausen e.V.") in entries


# ---------------------------------------------------------------------------
# fetch_course_aliases() / _parse_course_aliases_html() -- confirmed 2026-09-07 that
# a club's own course lineup isn't universal: this fixture is modeled on the real
# markup found for a second real club ("Golf Club Sonnenberg e.V."), whose options
# (names *and* alias codes) share no pattern with Musterhausen's own COURSE_ALIASES.

_SONNENBERG_ALIASES_HTML = """
<select id="timetable_selection_alias" name="rq[timetable_selection_alias]">
<option value="ALIAS|A001">18-Loch Schleife</option>
<option value="ALIAS|1810">18-Loch Schleife (nur erste 9-Loch)</option>
<option value="ALIAS|1811">18-Loch-Schleife (nur zweite 9-Loch)</option>
<option value="ALIAS|0901">9-Loch Schleife</option>
<option value="ALIAS|0601">Kurzplatz</option>
</select>
"""


def test_parse_course_aliases_html_extracts_name_and_code():
    aliases = _parse_course_aliases_html(_SONNENBERG_ALIASES_HTML)
    assert aliases == {
        "18-Loch Schleife": "A001",
        "18-Loch Schleife (nur erste 9-Loch)": "1810",
        "18-Loch-Schleife (nur zweite 9-Loch)": "1811",
        "9-Loch Schleife": "0901",
        "Kurzplatz": "0601",
    }


def test_parse_course_aliases_html_falls_back_to_one_implicit_course_without_a_selector():
    # 18 of the 39 real clubs with a working tee sheet (46%) have no "Area" selector at
    # all -- they run a single course, addressed with no alias parameter. Raising for
    # those, as this used to, made nearly half of pc caddie's clubs unusable.
    aliases = _parse_course_aliases_html("<html><body>no select here</body></html>")
    assert aliases == {scraper_module.SINGLE_COURSE_NAME: ""}


class _FakeGetResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


_A_TIMETABLE = '<table class="pcco-tt-timetable"><tr><td>Zeit</td><td>- 1 -</td></tr></table>'


def test_fetch_course_aliases_returns_this_clubs_own_options(monkeypatch):
    monkeypatch.setattr(
        scraper_module.httpx, "get",
        lambda url, timeout, follow_redirects: _FakeGetResponse(_SONNENBERG_ALIASES_HTML + _A_TIMETABLE),
    )

    aliases = fetch_course_aliases("0000002")

    assert aliases["18-Loch Schleife"] == "A001"
    assert aliases["Kurzplatz"] == "0601"
    # Confirms this is genuinely per-club, not Musterhausen's own COURSE_ALIASES --
    # none of Sonnenberg's real names or codes match Musterhausen's at all.
    assert "18 Loch Tee 1" not in aliases


def test_fetch_course_aliases_raises_no_tee_sheet_error_when_the_club_has_none(monkeypatch):
    # 7 of the 79 clubs exercised end-to-end 2026-09-07 publish no tee sheet at all
    # (some were PC CADDIE's own demo clubs). A club can even offer a course selector
    # and still have no timetable behind it, which is why this is checked against the
    # whole page rather than inferred from the selector's absence.
    monkeypatch.setattr(
        scraper_module.httpx, "get",
        lambda url, timeout, follow_redirects: _FakeGetResponse(_SONNENBERG_ALIASES_HTML),
    )
    try:
        fetch_course_aliases("0499001")
        assert False, "expected NoTeeSheetError"
    except scraper_module.NoTeeSheetError:
        pass


def test_parse_available_dates_html_reads_the_clubs_own_booking_window():
    # 1 to 31 days across the real clubs swept, against a configured default of 5.
    html = """
    <select id="timetable_selection_date">
    <option value="DAY|2026-09-07">07.09.2026</option>
    <option value="DAY|2026-09-08">08.09.2026</option>
    <option value="">--</option>
    </select>
    """
    assert scraper_module._parse_available_dates_html(html) == ["2026-09-07", "2026-09-08"]


def test_parse_available_dates_html_returns_empty_without_a_date_selector():
    assert scraper_module._parse_available_dates_html("<html></html>") == []


def test_capacity_is_read_from_the_table_header_not_assumed():
    html = """
    <table class="pcco-tt-timetable">
      <tr><th>Ora</th><th>- 1 -</th><th>- 2 -</th><th>- 3 -</th></tr>
      <tr class="pcco-tt-time-person" data-time="08:00" data-status="bookable"
          data-seat_bookable="1"><td class="seats-free-1"></td></tr>
    </table>
    """
    schedule = parse_schedule_html(html, date="2026-09-07", course="Course")
    assert schedule.slots[0].capacity == 3  # not the usual 4
    assert schedule.slots[0].booked == 2
