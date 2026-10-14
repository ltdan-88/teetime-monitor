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
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from . import clock, club_config, pipeline, recommend, scrape_once, scraper, storage
from .models import ConfirmedBooking

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


def user_agent() -> str:
    try:
        from importlib.metadata import version

        product = version("teetime-monitor")
    except Exception:  # noqa: BLE001 -- a checkout that was never installed
        product = "dev"
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/130.0.0.0 Safari/537.36 teetime-monitor/{product}"
    )


def open_session(club_id: str, username: str, password: str) -> httpx.Client:
    """A logged-in client that pc caddie treats like a browser session. Raises BookingError('login') when the
    login is refused, BookingError('network') when the site cannot be reached."""
    client = httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": user_agent(), "Accept-Language": "en-US,en;q=0.9"})
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


def book_slot(client: httpx.Client, club_id: str, course: str, date: str, time: str) -> BookingResult:
    """Book `time` on `date` on `course` for yourself alone and confirm it. Raises BookingError."""
    aliases = scraper.fetch_course_aliases(club_id)
    alias = aliases.get(course)
    if alias is None:
        raise BookingError("unknown_course", course)
    sheet_url = scraper.club_url(club_id, scraper.TEE_SHEET_CATEGORY, date=date, alias=alias)
    sheet = _get(client, sheet_url)
    if sheet.status_code >= 400:
        raise BookingError("network", f"tee sheet answered {sheet.status_code}")
    link = find_booking_link(sheet.text, time)

    form_page = _get(client, urljoin(SITE, link), referer=sheet_url)
    form = _soup(form_page.text).find("form", id="frm_book_data")
    if form is None:
        raise BookingError("blocked", _message(form_page.text) or f"the booking page answered {form_page.status_code}")
    action = urljoin(str(form_page.url), form.get("action", ""))
    step2 = _post(client, action, _form_data(form, ("task", "prebook")), referer=str(form_page.url))

    prebook = _soup(step2.text).find("form", id="frm_book_prebook")
    if prebook is None:
        raise BookingError("rejected", _message(step2.text) or "pc caddie did not offer the reservation")
    finish = _post(client, urljoin(str(step2.url), prebook.get("action", "")), _form_data(prebook, ("task", "finish")), referer=str(step2.url))
    if finish.status_code >= 400:
        raise BookingError("rejected", _message(finish.text) or f"pc caddie answered {finish.status_code}")

    if not reservation_exists(client, club_id, course, date, time):
        raise BookingError("unconfirmed", _message(finish.text) or "the booking is not in My Reservations")
    return BookingResult(club_id, course, date, time)


# ---- My Reservations ---------------------------------------------------------------------------------------


def reservations(client: httpx.Client, club_id: str) -> tuple[str, list]:
    """(the page's html, the parsed bookings) of My Reservations."""
    response = _get(client, scraper.club_url(club_id, scraper.MY_RESERVATIONS_CATEGORY))
    if response.status_code >= 400:
        raise BookingError("network", f"My Reservations answered {response.status_code}")
    try:
        parsed = scraper._parse_my_reservations_html(response.text, list(scraper.fetch_course_aliases(club_id)))
    except NotImplementedError as error:
        raise BookingError("changed", "My Reservations looks different than expected") from error
    return response.text, parsed


def reservation_exists(client: httpx.Client, club_id: str, course: str, date: str, time: str) -> bool:
    _, parsed = reservations(client, club_id)
    return any(b.course == course and b.date == date and b.time == time for b in parsed)


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


def cancel_booking(client: httpx.Client, club_id: str, course: str, date: str, time: str) -> BookingResult:
    """Cancel your booking of `time` on `date` on `course`. Raises BookingError('not_found') when My Reservations
    does not show it (cancelled already, or never made)."""
    html, parsed = reservations(client, club_id)
    if not any(b.course == course and b.date == date and b.time == time for b in parsed):
        raise BookingError("not_found", f"no booking at {time} on {date}")
    list_url = scraper.club_url(club_id, scraper.MY_RESERVATIONS_CATEGORY)
    page = _get(client, urljoin(SITE, _cancel_link(html, course, date, time)), referer=list_url)
    form = next((f for f in _soup(page.text).find_all("form") if f.find("input", attrs={"type": "checkbox"})), None)
    if form is None:
        raise BookingError("changed", _message(page.text) or "the cancellation page has no form")
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
    action = urljoin(str(page.url), form.get("action", "") or str(page.url))
    done = _post(client, action, _form_data(form, pressed), referer=str(page.url))
    if done.status_code >= 400:
        raise BookingError("rejected", _message(done.text) or f"pc caddie answered {done.status_code}")
    if reservation_exists(client, club_id, course, date, time):
        raise BookingError("unconfirmed", _message(done.text) or "the booking is still in My Reservations")
    return BookingResult(club_id, course, date, time)


# ---- what both front ends call -----------------------------------------------------------------------


_DATE_OK = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_OK = re.compile(r"^\d{2}:\d{2}$")


def _session_for(club: dict, date: str, time: str) -> tuple[httpx.Client, None] | tuple[None, dict]:
    """(a logged-in session, None), or (None, the `{"error": ...}` answer) when it cannot be started."""
    if not (_TIME_OK.match(time or "") and _DATE_OK.match(date or "")):
        return None, {"error": "bad_time"}
    username, password = club_config.resolve_credentials(club.get("slug") or club["id"])
    if not username or not password:
        return None, {"error": "no_login"}
    try:
        return open_session(club["id"], username, password), None
    except BookingError as error:
        return None, {"error": error.reason, "message": error.message}


def _read_back(club: dict, db_path: Path) -> None:
    """Read My Reservations into the database again: what pc caddie shows is the one truth about what is booked."""
    if club.get("slug"):
        courses = storage.upcoming_courses(clock.today(), path=db_path)  # from the database: no further request to the site
        scrape_once._sync_my_reservations(club["id"], club["slug"], db_path, courses or None)


def book_for_club(club: dict, db_path: Path, course: str, date: str, time: str) -> dict:
    """Book for yourself on pc caddie, then record it. `club` is {"id", "slug", "name"}. `{"ok": True}` or
    `{"error": reason, "message": ...}`; nothing is recorded unless pc caddie accepted it."""
    client, failure = _session_for(club, date, time)
    if failure is not None:
        return failure
    try:
        book_slot(client, club["id"], course, date, time)
    except BookingError as error:
        return {"error": error.reason, "message": error.message}
    finally:
        client.close()
    config = pipeline._resolved_config(club.get("slug"), club["id"], club.get("name"))
    storage.save_confirmed_booking(  # at once, whether or not the read-back works
        ConfirmedBooking(date=date, course=course, time=time, holes=recommend.holes_for_course(course, config), source="my_reservations", confirmed_at=datetime.now(UTC).isoformat()),
        path=db_path,
    )
    _safely_read_back(club, db_path)
    return {"ok": True}


def cancel_for_club(club: dict, db_path: Path, course: str, date: str, time: str) -> dict:
    """Cancel your booking on pc caddie, then record "no booking that day"."""
    client, failure = _session_for(club, date, time)
    if failure is not None:
        return failure
    try:
        cancel_booking(client, club["id"], course, date, time)
    except BookingError as error:
        return {"error": error.reason, "message": error.message}
    finally:
        client.close()
    storage.save_confirmed_booking(  # the newest row wins, as the reconciliation writes it
        ConfirmedBooking(date=date, course=course, time=None, holes=None, source="my_reservations", confirmed_at=datetime.now(UTC).isoformat()),
        path=db_path,
    )
    _safely_read_back(club, db_path)
    return {"ok": True}


def _safely_read_back(club: dict, db_path: Path) -> None:
    try:
        _read_back(club, db_path)
    except Exception:  # noqa: BLE001 -- the booking itself is done; the next scrape reads it back anyway
        pass


def upcoming_reservations(clubs: list[dict], refresh: bool = False) -> dict:
    """Your upcoming bookings at `clubs` ({"slug", "id", "name"} each), earliest first: what the databases know (the
    newest word per course and day), without cancelled bookings and without times already gone today. With
    `refresh`, My Reservations is read from pc caddie first (bookings made on its own site appear, cancelled ones go);
    `refresh_problems` then names the clubs where that did not work (no login saved, no connection)."""
    today, now = clock.today(), clock.now_hhmm()
    found, problems = [], []
    for club in clubs:
        db = scrape_once._db_path(club["id"])
        if refresh:
            courses = storage.upcoming_courses(today, path=db) if db.exists() else []
            status = scrape_once._sync_my_reservations(club["id"], club["slug"], db, courses or None)
            if status != "ok":
                problems.append({"club": club["name"], "reason": status or "no_login"})
        if not db.exists():
            continue
        for item in storage.load_all_confirmed_bookings(db):
            if item.time and (item.date > today or (item.date == today and item.time >= now)):
                found.append({"slug": club["slug"], "club_id": club["id"], "club": club["name"], "course": item.course, "date": item.date, "time": item.time})
    found.sort(key=lambda r: (r["date"], r["time"], r["club"]))
    return {"reservations": found, "refreshed": refresh, "refresh_problems": problems}
