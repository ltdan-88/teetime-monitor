"""Real reservations on pc caddie: book a tee time and cancel it again (2026-10-14).

Until now teetime-monitor only *marked* a time as booked after you had booked it on pc caddie yourself. This
module does what you would do on the site, with your own login, one booking at a time and only when you press
the button (there is no scheduled or automatic booking):

  book:    tee sheet -> the time's "Book now" link -> form (step 2) -> "Make this reservation" -> confirm page
           (step 3, a pending reservation with a number) -> "Confirm booking"  (`task=prebook`, then `task=finish`)
  cancel:  My Reservations -> the row's "Cancel" -> the booking's page -> "Cancel selected bookings"

Everything on those pages is read from the page itself (the hidden `process` / `cati` values change on every
visit and must be passed back), never built by hand. pc caddie answers in English or German depending on the
request, so success is not judged by wording: after booking or cancelling, "My Reservations" is read again and
must show (or no longer show) the booking.

The site serves a bare PHP session only to requests that look like a browser; the session here carries a
browser-compatible User-Agent with our own product token appended.

Faster, without more requests (2026-10-18): the login is the one `scraper.logged_in()` keeps (a booking right after
a scrape pass or a look at My Reservations does not log in again), and the pages before the first click that
changes anything -- the tee sheet and the booking form, or My Reservations and the booking's page -- can be read
while the person still reads the dialog (`prepare()`). Pressing the button then only sends the two or three
requests that book or cancel and read the result. Progress is reported step by step (`start()`, `job()`).
"""

import contextlib
import re
import secrets
import threading
import time as time_module
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from . import clock, club_config, pipeline, recommend, scrape_once, scraper, storage
from .models import ConfirmedBooking, ReservationsSync

SITE = "https://www.pccaddie.net"
_TIMEOUT = 20


class BookingError(Exception):
    """A booking or cancellation that did not happen. `reason` is one of: login, unknown_course, not_bookable,
    taken, blocked, rejected, unconfirmed, not_found, not_cancelable, network, changed."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(f"{reason}: {message}" if message else reason)
        self.reason = reason
        self.message = message


@dataclass
class BookingResult:
    club_id: str
    course: str
    date: str
    time: str
    sync: ReservationsSync | None = None  # the My Reservations page read to verify it: recorded without a second login


user_agent = scraper.user_agent  # the browser-like user agent naming this program (moved to scraper.py)


def open_session(club_id: str, username: str, password: str) -> httpx.Client:
    """A logged-in client that pc caddie treats like a browser session. Raises BookingError('login') when the
    login is refused, BookingError('network') when the site cannot be reached."""
    client = scraper.new_client(_TIMEOUT)
    try:
        response = client.post(
            scraper.club_url(club_id, "start"),
            data={"service": "login", "rq[login]": username, scraper._PASSWORD_FIELD: password},
        )
        if scraper._PASSWORD_FIELD in response.text:
            raise BookingError("login", "pc caddie did not accept the login")
        response.raise_for_status()
    except BookingError:
        client.close()
        raise
    except httpx.HTTPError as error:
        client.close()
        raise BookingError("network", str(error)) from error
    return client


# ---- reading pages ---------------------------------------------------------------------------------------


def _soup(text: str) -> BeautifulSoup:
    return BeautifulSoup(text, "html.parser")


def _form_data(form: Tag, submit_value: tuple[str, str] | None) -> dict[str, list[str]]:
    """What a browser would send for `form` (hidden, text, checked radio/checkbox, selects), plus the one
    submit button pressed. Values are lists because names repeat (`rq[teetimes][]`)."""
    data: dict[str, list[str]] = {}

    def add(name: str, value: str) -> None:
        data.setdefault(name, []).append(value)

    for field in form.find_all(["input", "select", "textarea", "button"]):
        name = field.get("name")
        if not name or field.has_attr("disabled"):
            continue
        if field.name == "select":
            chosen = field.find("option", selected=True) or field.find("option")
            if chosen is not None:
                add(name, chosen.get("value", chosen.get_text(strip=True)))
        elif field.name == "textarea":
            add(name, field.get_text())
        elif field.name == "button" or (field.name == "input" and field.get("type") in ("submit", "image", "button")):
            continue  # only the pressed one, below
        elif field.get("type") in ("radio", "checkbox"):
            if field.has_attr("checked"):
                add(name, field.get("value", "on"))
        else:
            add(name, field.get("value", ""))
    if submit_value is not None:
        add(*submit_value)
    return data


def _message(page: str) -> str:
    """The page's own notice (an alert or error box), for the person to read."""
    soup = _soup(page)
    for selector in (".alert", ".error", ".pcco-error", "[role=alert]", ".message"):
        box = soup.select_one(selector)
        if box is not None and box.get_text(strip=True):
            return re.sub(r"\s+", " ", box.get_text(" ", strip=True))[:300]
    return ""


def _get(client: httpx.Client, url: str, referer: str | None = None) -> httpx.Response:
    try:
        return client.get(url, headers={"Referer": referer} if referer else None)
    except httpx.HTTPError as error:
        raise BookingError("network", str(error)) from error


def _post(client: httpx.Client, url: str, data: dict[str, list[str]], referer: str) -> httpx.Response:
    try:
        return client.post(url, data=data, headers={"Referer": referer})
    except httpx.HTTPError as error:
        raise BookingError("network", str(error)) from error


# ---- the tee sheet row ---------------------------------------------------------------------------------


def find_booking_link(sheet_html: str, time: str) -> str:
    """The "Book now" link of `time` on a tee sheet page. BookingError('taken') when the time has no free seat,
    'not_bookable' when there is no link (not open yet, blocked, a tournament)."""
    soup = _soup(sheet_html)
    row = soup.find("tr", class_="pcco-tt-time-person", attrs={"data-time": time})
    if row is None:
        raise BookingError("not_bookable", f"{time} is not on the tee sheet")
    free = row.get("data-seat_bookable")
    if row.get("data-status") != "bookable" or (free is not None and free.isdigit() and int(free) < 1):
        raise BookingError("taken", f"{time} has no free seat")
    action = soup.find("tr", class_="pcco-tt-time-action", attrs={"data-time": time})
    link = action.find("a", href=re.compile(r"cat=tt_book")) if action is not None else None
    if link is None:
        raise BookingError("not_bookable", f"{time} cannot be booked now")
    return link["href"].replace("&amp;", "&")


# ---- booking -------------------------------------------------------------------------------------------


@dataclass
class Prepared:
    """The pages read before the first click that changes anything: the booking form (book) or the booking's own
    page (cancel), with what the next step needs. Read while the dialog is open, used when the button is pressed."""

    kind: str  # "book" | "cancel"
    url: str
    html: str
    courses: list[str] = dataclass_field(default_factory=list)
    ahead: bool = False  # read before the button was pressed (a refusal then reads it all again, once)


class _Stale(Exception):
    """A page read ahead was refused before anything was booked or cancelled: read it again, then go on."""


def _check_logged_in(response: httpx.Response) -> httpx.Response:
    if scraper.logged_out(response.text):
        raise scraper.SessionExpired("the session ran out")
    return response


def prepare_book(client: httpx.Client, club_id: str, course: str, date: str, time: str) -> Prepared:
    """Tee sheet -> the time's booking link -> the booking form: reading only, nothing reserved yet."""
    aliases = scraper.fetch_course_aliases(club_id, client)  # remembered for hours; on the session's own connection
    if course not in aliases:  # a course that is new since: the list read fresh once
        aliases = scraper.fetch_course_aliases(club_id, client, fresh=True)
    alias = aliases.get(course)
    if alias is None:
        raise BookingError("unknown_course", course)
    sheet_url = scraper.club_url(club_id, scraper.TEE_SHEET_CATEGORY, date=date, alias=alias)
    sheet = _get(client, sheet_url)
    if sheet.status_code >= 400:
        raise BookingError("network", f"tee sheet answered {sheet.status_code}")
    link = find_booking_link(sheet.text, time)
    form_page = _check_logged_in(_get(client, urljoin(SITE, link), referer=sheet_url))
    if _soup(form_page.text).find("form", id="frm_book_data") is None:
        raise BookingError("blocked", _message(form_page.text) or f"the booking page answered {form_page.status_code}")
    return Prepared("book", str(form_page.url), form_page.text, list(aliases))


def partner_choices(html: str) -> list[dict]:
    """Who the booking form offers as a partner (1.1.0): your friends list on pc caddie, the same for each of the other
    three places, "Surname, First name" each. As [{"id", "name": "First name Surname"}], in pc caddie's order."""
    form = _soup(html).find("form", id="frm_book_data")
    pick = form.find("select", attrs={"name": "rq[players][2][friend][bd_id]"}) if form else None
    choices = []
    for option in pick.find_all("option") if pick else []:
        value, label = option.get("value", "").strip(), option.get_text(" ", strip=True)
        if value:
            surname, _, first = label.partition(",")
            choices.append({"id": value, "name": f"{first.strip()} {surname.strip()}".strip()})
    return choices


SALUTATIONS = ("female", "male", "diverse")
_GUEST_NAME = re.compile(r"^[^\x00-\x1f<>]{1,40}$")
_CLUB_NUMBER = re.compile(r"^\d{7}$")


def guest(raw: dict) -> dict:
    """A guest as the booking form takes one (1.4.0): salutation, first name, surname and, if they have one, the home
    club as pc caddie's own club list gives it (`number` its 7 digits, `name` "9999 - Club name"). BookingError
    "bad_partners" for anything the form would not take."""
    first, last = str(raw.get("first", "")).strip(), str(raw.get("last", "")).strip()
    salutation, number = str(raw.get("salutation", "")), str(raw.get("club_number", "")).strip()
    club = str(raw.get("club_name", "")).strip() if number else ""
    if not (_GUEST_NAME.match(first) and _GUEST_NAME.match(last)) or salutation not in SALUTATIONS:
        raise BookingError("bad_partners", "a guest needs a salutation, first name and surname")
    if number and (not _CLUB_NUMBER.match(number) or not _GUEST_NAME.match(club[:40] or "?")):
        raise BookingError("bad_partners", "a home club from pc caddie's list")
    return {"salutation": salutation, "first": first, "last": last, "club_number": number, "club_name": club[:100]}


def _with_partners(data: dict[str, list[str]], html: str, partners: list) -> dict[str, list[str]]:
    """The form's own data with `partners` in places 2, 3 and 4, as a person filling in pc caddie's form would: a friend
    id from partner_choices() (any id the form does not offer is refused), or a guest (a dict, see guest())."""
    offered = {choice["id"] for choice in partner_choices(html)}
    friends = [partner for partner in partners if isinstance(partner, str)]
    if len(partners) > 3 or len(set(friends)) != len(friends) or not set(friends) <= offered:
        raise BookingError("bad_partners", "a partner the booking form does not offer")
    for place, partner in enumerate(partners, start=2):
        if isinstance(partner, str):
            data[f"rq[players][{place}][type]"] = ["friend"]
            data[f"rq[players][{place}][friend][bd_id]"] = [partner]
            continue
        visitor = guest(partner)
        data[f"rq[players][{place}][type]"] = ["combo"]
        for field, value in (("salutation", visitor["salutation"]), ("title", ""), ("forename", visitor["first"]),
                             ("surname", visitor["last"]), ("clubname", visitor["club_name"]), ("clubnumber", visitor["club_number"])):
            data[f"rq[players][{place}][combo][{field}]"] = [value]
    return data


# What pc caddie's own home-club field suggests (its `/pcco/clubselect.php`, one line a club: "0499999|9999|Name|049|
# Country"), kept for an hour per search: a guest's home club as its form would send it.
_CLUB_SEARCHES: dict[str, tuple[float, list[dict]]] = {}


def search_home_clubs(club: dict, text: str) -> dict:
    """Clubs whose name or number contains `text` (at least 3 characters), as {"clubs": [{"number", "name", "label"}]}."""
    text = " ".join(text.split())[:40]
    if len(text) < 3:
        return {"clubs": []}
    held = _CLUB_SEARCHES.get(text.lower())
    if held and time_module.monotonic() - held[0] < 3600:
        return {"clubs": held[1]}
    url = f"{SITE}/pcco/clubselect.php?" + urlencode({"club": club["id"], "q": text, "limit": 10})
    try:
        with session_for(club) as client:
            lines = _get(client, url).text.splitlines()
    except (BookingError, scraper.SessionExpired, scraper.LoginError):
        return {"clubs": [], "error": "network"}
    clubs = []
    for line in lines:
        parts = line.split("|")
        if len(parts) >= 5 and _CLUB_NUMBER.match(parts[0]):
            clubs.append({"number": parts[0], "name": f"{parts[1]} - {parts[2]}", "label": f"{parts[2]} ({parts[4]})"})
    _CLUB_SEARCHES[text.lower()] = (time_module.monotonic(), clubs)
    return {"clubs": clubs}


def commit_book(client: httpx.Client, club_id: str, course: str, date: str, time: str, prepared: Prepared, progress=None, partners=()) -> BookingResult:
    """"Make this reservation" -> "Confirm booking" -> My Reservations must show it. `partners`: friend ids that play
    with you (partner_choices()); none books you alone."""
    form = _soup(prepared.html).find("form", id="frm_book_data")
    action = urljoin(prepared.url, form.get("action", ""))
    data = _with_partners(_form_data(form, ("task", "prebook")), prepared.html, list(partners))
    step2 = _check_logged_in(_post(client, action, data, referer=prepared.url))
    prebook = _soup(step2.text).find("form", id="frm_book_prebook")
    if prebook is None:
        if prepared.ahead:
            raise _Stale()
        raise BookingError("rejected", _message(step2.text) or "pc caddie did not offer the reservation")
    finish = _post(client, urljoin(str(step2.url), prebook.get("action", "")), _form_data(prebook, ("task", "finish")), referer=str(step2.url))
    if finish.status_code >= 400:
        raise BookingError("rejected", _message(finish.text) or f"pc caddie answered {finish.status_code}")
    if progress:
        progress("confirm")
    html, parsed = reservations(client, club_id, prepared.courses)
    if not _listed(parsed, course, date, time):
        raise BookingError("unconfirmed", _message(finish.text) or "the booking is not in My Reservations")
    return BookingResult(club_id, course, date, time, _sync_of(html, parsed))


def book_slot(client: httpx.Client, club_id: str, course: str, date: str, time: str) -> BookingResult:
    """Book `time` on `date` on `course` for yourself alone and confirm it. Raises BookingError."""
    return commit_book(client, club_id, course, date, time, prepare_book(client, club_id, course, date, time))


# ---- My Reservations ---------------------------------------------------------------------------------------


def reservations(client: httpx.Client, club_id: str, courses: list[str] | None = None) -> tuple[str, list]:
    """(the page's html, the parsed bookings) of My Reservations. `courses` is the club's course list (the parser's
    guard against a misread course name); fetched here when the caller does not have it yet."""
    response = _get(client, scraper.club_url(club_id, scraper.MY_RESERVATIONS_CATEGORY))
    if response.status_code >= 400:
        raise BookingError("network", f"My Reservations answered {response.status_code}")
    try:
        if courses is None:
            courses = list(scraper.fetch_course_aliases(club_id, client))
        parsed = scraper._parse_my_reservations_html(response.text, courses)
    except NotImplementedError as error:
        raise BookingError("changed", "My Reservations looks different than expected") from error
    return response.text, parsed


def _listed(parsed: list, course: str, date: str, time: str) -> bool:
    return any(b.course == course and b.date == date and b.time == time for b in parsed)


def _sync_of(html: str, parsed: list) -> ReservationsSync:
    return ReservationsSync(bookings=parsed, my_handicap=scraper._parse_my_handicap_html(html))


def reservation_exists(client: httpx.Client, club_id: str, course: str, date: str, time: str) -> bool:
    _, parsed = reservations(client, club_id)
    return _listed(parsed, course, date, time)


# ---- cancelling -------------------------------------------------------------------------------------------


def _row_matches(row: Tag, course: str, date: str, time: str) -> bool:
    text = re.sub(r"\s+", " ", row.get_text(" ", strip=True))
    german = f"{date[8:10]}.{date[5:7]}.{date[:4]}"
    return course in text and (date in text or german in text) and time in text


def _cancel_link(html: str, course: str, date: str, time: str) -> str:
    """The address of the booking's own page (the one with the "Cancel selected bookings" button), found in its
    row of My Reservations."""
    for row in _soup(html).find_all("tr"):
        if not row.find("td") or not _row_matches(row, course, date, time):
            continue
        for link in row.find_all("a", href=True):
            if "sel=" in link["href"]:
                return link["href"].replace("&amp;", "&")
        for button in row.find_all(["form", "button", "input"]):
            target = button.get("action") or button.get("formaction") or button.get("data-href") or ""
            if "sel=" in target:
                return target.replace("&amp;", "&")
        if re.search(r"not cancel|nicht stornier|cannot be cancel", row.get_text(" ", strip=True), re.I):
            raise BookingError("not_cancelable", "the cancellation period of this booking is over")
    raise BookingError("changed", "My Reservations has no cancel link for this booking")


_CANCEL_WORDS = re.compile(r"cancel|storn|l[öo]sch|delete", re.I)
_BACK_WORDS = re.compile(r"back|zur[üu]ck|overview|[üu]bersicht", re.I)


def prepare_cancel(client: httpx.Client, club_id: str, course: str, date: str, time: str) -> Prepared:
    """My Reservations -> the booking's row -> its own page with the cancel button: reading only."""
    courses = list(scraper.fetch_course_aliases(club_id, client))  # for both reads of My Reservations
    html, parsed = reservations(client, club_id, courses)
    if not _listed(parsed, course, date, time):
        raise BookingError("not_found", f"no booking at {time} on {date}")
    list_url = scraper.club_url(club_id, scraper.MY_RESERVATIONS_CATEGORY)
    page = _check_logged_in(_get(client, urljoin(SITE, _cancel_link(html, course, date, time)), referer=list_url))
    if next((f for f in _soup(page.text).find_all("form") if f.find("input", attrs={"type": "checkbox"})), None) is None:
        raise BookingError("changed", _message(page.text) or "the cancellation page has no form")
    return Prepared("cancel", str(page.url), page.text, courses)


def commit_cancel(client: httpx.Client, club_id: str, course: str, date: str, time: str, prepared: Prepared, progress=None) -> BookingResult:
    """"Cancel selected bookings" -> My Reservations must no longer show it."""
    form = next(f for f in _soup(prepared.html).find_all("form") if f.find("input", attrs={"type": "checkbox"}))
    boxes = form.find_all("input", attrs={"type": "checkbox"})
    for box in boxes:  # your one booking, selected as the page does it; select it if the page left it open
        if len(boxes) == 1 and not box.has_attr("checked"):
            box["checked"] = "checked"
    submits = [b for b in form.find_all(["button", "input"]) if (b.name == "button" and b.get("type") in (None, "submit")) or b.get("type") == "submit"]
    button = next(
        (b for b in submits if _CANCEL_WORDS.search(b.get_text(" ", strip=True) + " " + (b.get("value") or "")) and not _BACK_WORDS.search(b.get_text(" ", strip=True))),
        None,
    )
    if button is None:
        raise BookingError("changed", "the cancellation page has no cancel button")
    pressed = (button["name"], button.get("value", "")) if button.get("name") else None
    action = urljoin(prepared.url, form.get("action", "") or prepared.url)
    done = _post(client, action, _form_data(form, pressed), referer=prepared.url)
    if scraper.logged_out(done.text):
        raise scraper.SessionExpired("the session ran out")  # not sent as you: nothing was cancelled
    if done.status_code >= 400:
        raise BookingError("rejected", _message(done.text) or f"pc caddie answered {done.status_code}")
    if progress:
        progress("confirm")
    html, parsed = reservations(client, club_id, prepared.courses)
    if _listed(parsed, course, date, time):
        if prepared.ahead:
            raise _Stale()  # the page read ahead may have been out of date: read it again and try once more
        raise BookingError("unconfirmed", _message(done.text) or "the booking is still in My Reservations")
    return BookingResult(club_id, course, date, time, _sync_of(html, parsed))


def cancel_booking(client: httpx.Client, club_id: str, course: str, date: str, time: str) -> BookingResult:
    """Cancel your booking of `time` on `date` on `course`. Raises BookingError('not_found') when My Reservations
    does not show it (cancelled already, or never made)."""
    return commit_cancel(client, club_id, course, date, time, prepare_cancel(client, club_id, course, date, time))


# ---- what both front ends call -----------------------------------------------------------------------


_DATE_OK = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_OK = re.compile(r"^\d{2}:\d{2}$")


@contextlib.contextmanager
def session_for(club: dict, fresh: bool = False):
    """The logged-in session for `club` (the kept one while it is fresh, see `scraper.logged_in()`). Raises
    BookingError: no_login, login (refused), network."""
    username, password = club_config.resolve_credentials(club.get("slug") or club["id"])
    if not username or not password:
        raise BookingError("no_login")
    try:
        with scraper.logged_in(club["id"], username, password, fresh=fresh, login_with=open_session) as client:
            yield client
    except httpx.HTTPError as error:
        raise BookingError("network", str(error)) from error


def _read_back(club: dict, db_path: Path) -> None:
    """Read My Reservations into the database again: what pc caddie shows is the one truth about what is booked."""
    if club.get("slug"):
        courses = storage.upcoming_courses(clock.today(), path=db_path)  # from the database: no further request to the site
        scrape_once._sync_my_reservations(club["id"], club["slug"], db_path, courses or None)


# ---- read ahead while the dialog is open ------------------------------------------------------------------------
# {(kind, club id, course, date, time): (when, Event set once read, Prepared or None)}. Kept PREPARED_SECONDS: the
# booking form's one-time values are fresh enough for that long, and a dialog left open longer just reads again.
PREPARED_SECONDS = 120
_prepared: dict[tuple, list] = {}
_prepared_lock = threading.Lock()


def _valid(date: str, time: str) -> bool:
    return bool(_TIME_OK.match(time or "") and _DATE_OK.match(date or ""))


def prepare(club: dict, kind: str, course: str, date: str, time: str) -> dict:
    """Read the pages before the first click that changes anything, in the background, for the dialog that is open.
    Nothing is booked or cancelled. Reading the same thing twice within PREPARED_SECONDS is not repeated."""
    if kind not in ("book", "cancel") or not _valid(date, time):
        return {"error": "bad_time"}
    key = (kind, club["id"], course, date, time)
    with _prepared_lock:
        held = _prepared.get(key)
        if held and time_module.monotonic() - held[0] < PREPARED_SECONDS:
            return {"ok": True}
        entry = [time_module.monotonic(), threading.Event(), None]
        _prepared[key] = entry

    def read() -> None:
        try:
            with session_for(club) as client:
                reader = prepare_book if kind == "book" else prepare_cancel
                entry[2] = reader(client, club["id"], course, date, time)
                entry[2].ahead = True
        except Exception:  # noqa: BLE001 -- pressing the button reads it again and says what is wrong
            entry[2] = None
        finally:
            entry[1].set()

    threading.Thread(target=read, daemon=True, name="booking-prepare").start()
    return {"ok": True}


def partners(club: dict, course: str, date: str, time: str) -> dict:
    """The partners the booking form being read ahead offers (partner_choices()), waiting a little for it; the read
    stays for the button. {"partners": [...]}, an empty list when there is no such read or it did not work."""
    with _prepared_lock:
        entry = _prepared.get(("book", club["id"], course, date, time))
    if entry is None or not entry[1].wait(20) or entry[2] is None:
        return {"partners": []}
    return {"partners": partner_choices(entry[2].html)}


def _take(kind: str, club: dict, course: str, date: str, time: str) -> Prepared | None:
    """What was read ahead for this, waiting for a read still under way; used once."""
    with _prepared_lock:
        entry = _prepared.pop((kind, club["id"], course, date, time), None)
    if entry is None:
        return None
    entry[1].wait(30)
    if time_module.monotonic() - entry[0] > PREPARED_SECONDS:
        return None
    return entry[2]


# ---- book and cancel, with progress -------------------------------------------------------------------------------


def _run(kind: str, club: dict, course: str, date: str, time: str, progress, partners=()) -> BookingResult:
    """Book or cancel: with what was read ahead when there is something, else read now; a session that ran out, or a
    page read ahead that pc caddie refused before anything changed, reads it all again once with a fresh login."""
    prepared = _take(kind, club, course, date, time)
    reader, committer = (prepare_book, commit_book) if kind == "book" else (prepare_cancel, commit_cancel)

    def attempt(fresh: bool) -> BookingResult:
        nonlocal prepared
        progress("login")
        with session_for(club, fresh=fresh) as client:
            if prepared is None:
                prepared = reader(client, club["id"], course, date, time)
            progress(kind)
            if kind == "book":
                return committer(client, club["id"], course, date, time, prepared, progress, partners=partners)
            return committer(client, club["id"], course, date, time, prepared, progress)

    try:
        return attempt(False)
    except (scraper.SessionExpired, _Stale):
        prepared = None
        return attempt(True)


def book_for_club(club: dict, db_path: Path, course: str, date: str, time: str, progress=None, partners=()) -> dict:
    """Book for yourself (and `partners`, friend ids from your pc caddie friends list) on pc caddie, then record it. `club` is {"id", "slug", "name"}. `{"ok": True}` or
    `{"error": reason, "message": ...}`; nothing is recorded unless pc caddie accepted it. `progress(step)` hears
    "login", "book" and "confirm" as they start."""
    if not _valid(date, time):
        return {"error": "bad_time"}
    try:
        result = _run("book", club, course, date, time, progress or (lambda step: None), partners)
    except BookingError as error:
        return {"error": error.reason, "message": error.message}
    except scraper.SessionExpired:
        return {"error": "login", "message": "pc caddie ended the session"}
    config = pipeline._resolved_config(club.get("slug"), club["id"], club.get("name"))
    storage.save_confirmed_booking(  # at once, whether or not the read-back works
        ConfirmedBooking(date=date, course=course, time=time, holes=recommend.holes_for_course(course, config), source="my_reservations", confirmed_at=datetime.now(UTC).isoformat()),
        path=db_path,
    )
    _record_read(club, db_path, result)
    return {"ok": True}


def cancel_for_club(club: dict, db_path: Path, course: str, date: str, time: str, progress=None) -> dict:
    """Cancel your booking on pc caddie, then record "no booking that day"."""
    if not _valid(date, time):
        return {"error": "bad_time"}
    try:
        result = _run("cancel", club, course, date, time, progress or (lambda step: None))
    except BookingError as error:
        return {"error": error.reason, "message": error.message}
    except scraper.SessionExpired:
        return {"error": "login", "message": "pc caddie ended the session"}
    storage.save_confirmed_booking(  # the newest row wins, as the reconciliation writes it
        ConfirmedBooking(date=date, course=course, time=None, holes=None, source="my_reservations", confirmed_at=datetime.now(UTC).isoformat()),
        path=db_path,
    )
    _record_read(club, db_path, result)
    return {"ok": True}


# {job id: {"kind", "state": running|ok|failed, "step", "error", "message", "at"}}: a booking pressed in the page runs
# here while the page asks how far it got (`job()`); kept JOB_SECONDS after it ended.
JOB_SECONDS = 600
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start(kind: str, club: dict, db_path: Path, course: str, date: str, time: str, on_done=None, partners=()) -> dict:
    """Book or cancel in the background; `{"job": id}` at once, `job(id)` then says how far it is."""
    if kind not in ("book", "cancel") or not _valid(date, time):
        return {"error": "bad_time"}
    job_id = secrets.token_hex(8)
    state = {"kind": kind, "state": "running", "step": "login", "error": None, "message": None, "at": time_module.monotonic()}
    with _jobs_lock:
        for old in [key for key, value in _jobs.items() if time_module.monotonic() - value["at"] > JOB_SECONDS]:
            del _jobs[old]
        _jobs[job_id] = state

    def step(name: str) -> None:
        with _jobs_lock:
            state["step"] = name

    def work() -> None:
        try:
            if kind == "book":
                result = book_for_club(club, db_path, course, date, time, progress=step, partners=partners)
            else:
                result = cancel_for_club(club, db_path, course, date, time, progress=step)
        except Exception as error:  # noqa: BLE001 -- said on the page, never lost
            result = {"error": "other", "message": f"{type(error).__name__}: {error}"}
        if on_done:
            on_done(result)
        with _jobs_lock:
            state.update(state="ok" if result.get("ok") else "failed", error=result.get("error"), message=result.get("message"), at=time_module.monotonic())

    threading.Thread(target=work, daemon=True, name=f"booking-{kind}").start()
    return {"job": job_id}


def job(job_id: str) -> dict | None:
    with _jobs_lock:
        found = _jobs.get(job_id)
        return {key: found[key] for key in ("kind", "state", "step", "error", "message")} if found else None


def _record_read(club: dict, db_path: Path, result: BookingResult | None) -> None:
    """Record the My Reservations page the booking or cancellation was just verified with; without one, read it again."""
    try:
        if result is not None and result.sync is not None:
            scrape_once._apply_reservations_sync(result.sync, db_path)
        else:
            _read_back(club, db_path)
    except Exception:  # noqa: BLE001 -- the booking itself is done; the next scrape reads it back anyway
        pass


# My Reservations read less than this long ago (by a scrape pass, a booking, or this window) is not read again unless
# asked to (`force`): the window opens at once, and pc caddie is not asked for the same page every few seconds.
RESERVATIONS_FRESH_SECONDS = 600


def upcoming_reservations(clubs: list[dict], refresh: bool = False, force: bool = False) -> dict:
    """Your upcoming bookings at `clubs` ({"slug", "id", "name"} each), earliest first: what the databases know (the
    newest word per course and day), without cancelled bookings and without times already gone today. With
    `refresh`, My Reservations is read from pc caddie first (bookings made on its own site appear, cancelled ones go)
    for each club not read in the last RESERVATIONS_FRESH_SECONDS (every one with `force`), two clubs at a time;
    `refresh_problems` then names the clubs where that did not work (no login saved, no connection), and
    `checked_at` is when the least recent of them was read (epoch seconds; None when never)."""
    today, now = clock.today(), clock.now_hhmm()
    found, problems = [], []
    if refresh:
        stale = [club for club in clubs if force or time_module.time() - scrape_once.RESERVATIONS_READ.get(str(scrape_once._db_path(club["id"])), 0) > RESERVATIONS_FRESH_SECONDS]

        def read(club: dict) -> dict | None:
            db = scrape_once._db_path(club["id"])
            courses = storage.upcoming_courses(today, path=db) if db.exists() else []
            status = scrape_once._sync_my_reservations(club["id"], club["slug"], db, courses or None)
            return None if status == "ok" else {"club": club["name"], "reason": status or "no_login"}

        with ThreadPoolExecutor(max_workers=2) as pool:  # the requests themselves still go one by one (scraper.pace())
            problems = [problem for problem in pool.map(read, stale) if problem]
    read_at = [scrape_once.RESERVATIONS_READ.get(str(scrape_once._db_path(club["id"]))) for club in clubs]
    checked_at = None if not read_at or None in read_at else min(read_at)
    for club in clubs:
        db = scrape_once._db_path(club["id"])
        if not db.exists():
            continue
        for item in storage.load_all_confirmed_bookings(db):
            if item.time and (item.date > today or (item.date == today and item.time >= now)):
                found.append({"slug": club["slug"], "club_id": club["id"], "club": club["name"], "course": item.course, "date": item.date, "time": item.time})
    found.sort(key=lambda r: (r["date"], r["time"], r["club"]))
    return {"reservations": found, "refreshed": refresh, "refresh_problems": problems, "checked_at": checked_at}
