"""The web UI in a real browser (2026-10-10): every screen driven through Chrome's DevTools protocol.

Opt-in (`TEETIME_E2E=1`) because it needs Chrome, Chromium or Edge: a demo server with a fake club
(`scripts/webui_demo.py --offline`, no network) is started, the page is opened, and each screen is
clicked through. It fails on any exception or console error in the page, which is what unit tests
of the JSON cannot see. `TEETIME_E2E_SHOTS=dir` also saves a screenshot of every screen there.
"""

import base64
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEETIME_E2E"), reason="set TEETIME_E2E=1 to drive a real browser")

ROOT = Path(__file__).resolve().parent.parent
SHOTS = os.environ.get("TEETIME_E2E_SHOTS")


def _chrome() -> str | None:
    candidates = [os.environ.get("CHROME")]
    candidates += [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    candidates += [shutil.which(name) for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge")]
    return next((c for c in candidates if c and Path(c).exists()), None)


class Page:
    """Just enough of the DevTools protocol: navigate, run script, press keys, take a screenshot."""

    def __init__(self, executable: str, width: int = 1280, height: int = 900):
        websockets = pytest.importorskip("websockets.sync.client")
        self.proc = subprocess.Popen(
            [executable, "--headless=new", "--disable-gpu", "--no-sandbox", "--remote-debugging-port=0",
             f"--user-data-dir={tempfile.mkdtemp()}", "--no-first-run", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )  # fmt: skip
        endpoint = None
        for line in self.proc.stderr:  # "DevTools listening on ws://127.0.0.1:PORT/devtools/browser/ID"
            match = re.search(r"ws://127\.0\.0\.1:(\d+)/", line)
            if match:
                endpoint = int(match.group(1))
                break
        assert endpoint, "Chrome did not start"
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{endpoint}/json"))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:  # noqa: BLE001 -- still starting
                time.sleep(0.5)
        self.ws = websockets.connect(page["webSocketDebuggerUrl"], max_size=50_000_000)
        self.counter = 0
        self.problems: list[str] = []
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)

    def call(self, method, **params):
        self.counter += 1
        mine = self.counter
        self.ws.send(json.dumps({"id": mine, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv(timeout=60))
            event = message.get("method")
            if event == "Runtime.exceptionThrown":
                details = message["params"]["exceptionDetails"]
                self.problems.append("exception: " + str(details.get("exception", {}).get("description", details.get("text"))))
            elif event == "Runtime.consoleAPICalled" and message["params"]["type"] in ("error", "assert"):
                self.problems.append("console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in message["params"]["args"]))
            if message.get("id") == mine:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})

    def js(self, expression):
        result = self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"].get("exception", {}).get("description", str(result["exceptionDetails"])))
        return result["result"].get("value")

    def go(self, url):
        self.call("Page.navigate", url=url)

    def wait(self, expression, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.js(f"Boolean({expression})"):
                    return
            except RuntimeError:
                pass  # the page is still navigating (no document yet): look again
            time.sleep(0.15)
        raise AssertionError(f"timed out waiting for: {expression}\npage text: {self.text()[:600]}")

    def text(self, selector="body"):
        return self.js(f"document.querySelector({json.dumps(selector)})?.innerText || ''")

    def count(self, selector):
        return self.js(f"document.querySelectorAll({json.dumps(selector)}).length")

    def click(self, selector, text=None, index=0):
        ok = self.js(
            f"""(() => {{ const els=[...document.querySelectorAll({json.dumps(selector)})].filter(e => {json.dumps(text)} === null || e.textContent.includes({json.dumps(text)}));
            if (els.length <= {index}) return false; els[{index}].click(); return true; }})()"""
        )
        assert ok, f"nothing to click: {selector} {text!r}"

    def set(self, selector, value):
        self.js(
            f"""(() => {{ const e=document.querySelector({json.dumps(selector)}); const proto=Object.getPrototypeOf(e);
            Object.getOwnPropertyDescriptor(proto,'value').set.call(e,{json.dumps(value)});
            e.dispatchEvent(new Event('input',{{bubbles:true}})); e.dispatchEvent(new Event('change',{{bubbles:true}})); }})()"""
        )

    def key(self, key):
        self.js(f"window.dispatchEvent(new KeyboardEvent('keydown', {{key: {json.dumps(key)}, bubbles: true}}))")

    def shot(self, name):
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            Path(SHOTS, f"{name}.png").write_bytes(base64.b64decode(self.call("Page.captureScreenshot", format="png")["data"]))

    def close(self):
        try:
            self.ws.close()
        finally:
            self.proc.kill()


@pytest.fixture(scope="module")
def ui(tmp_path_factory):
    executable = _chrome()
    if executable is None:
        pytest.skip("no Chrome, Chromium or Edge found (set CHROME)")
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "webui_demo.py"), str(tmp_path_factory.mktemp("demo")), "--serve", "--offline", "--at", "09:30"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ, "PYTHONUNBUFFERED": "1", "TEETIME_MONITOR_LANG": "en"},
    )  # fmt: skip
    url = None
    for line in server.stdout:
        match = re.search(r"http://127\.0\.0\.1:\d+/\?t=[\w-]+", line)
        if match:
            url = match.group(0)
            break
    assert url, "the demo server did not start"
    page = Page(executable)
    page.go(url)
    page.wait("document.querySelectorAll('.card').length > 0")
    yield page
    page.close()
    server.kill()


SHEET_READY = "document.querySelector('.sheet') && document.querySelector('.sheet').contains(document.activeElement)"


def _open_sheet(ui, key, title_contains):
    ui.key(key)
    ui.wait(f"document.querySelector('.sheet h2') && document.querySelector('.sheet h2').textContent.includes({json.dumps(title_contains)})")
    ui.wait(SHEET_READY)  # the sheet's own key handling and focus are set up after it is drawn


def _chip(ui, text, scope=".sf"):
    """Click the filter chip or button whose text is exactly `text` (a plain "4" must not match "14–17")."""
    ui.js(
        f"""(() => {{ const el = [...document.querySelectorAll({json.dumps(scope + ' .chip, ' + scope + ' .btn, .results .btn')})].find((e) => e.textContent.trim() === {json.dumps(text)});
        if (!el) throw new Error('no chip ' + {json.dumps(text)}); el.click(); }})()"""
    )


def _chip_on(ui, text):
    return ui.js(f"[...document.querySelectorAll('.sf .chip')].find((e) => e.textContent.trim() === {json.dumps(text)})?.getAttribute('aria-pressed')")


def _search_rows(ui):
    return ui.count(".results .res:not(.res-head)")


def _close_sheet(ui):
    ui.click(".sheet-head .icon-btn")
    ui.wait("!document.querySelector('.scrim')")


# The page waits whole seconds in a few places (a message that fades back after six seconds, a poll every three,
# a retry after 600 ms ...). Those tests run the page's long timers ten times faster instead of sitting through them.
HURRY = "(() => { if (window.__hurried) return; window.__hurried = true; const real = window.setTimeout.bind(window); window.setTimeout = (fn, ms, ...rest) => real(fn, ms >= 500 ? ms / 10 : ms, ...rest); })()"


@contextlib.contextmanager
def hurried(ui):
    identifier = ui.call("Page.addScriptToEvaluateOnNewDocument", source=HURRY)["identifier"]  # also after a reload
    ui.js(HURRY)
    try:
        yield
    finally:
        ui.call("Page.removeScriptToEvaluateOnNewDocument", identifier=identifier)


@pytest.fixture
def hurry(ui):
    with hurried(ui):
        yield
    if ui.js("window.__hurried === true"):  # the page the test left behind still runs hurried: start the next test on a normal one
        ui.js("location.reload()")
        ui.wait("window.__hurried === undefined && document.querySelectorAll('.card').length > 0")


def test_the_overview_shows_five_days_all_collapsed_on_launch(ui):
    assert ui.count(".card") == 5
    assert ui.count(".card.open") == 0  # like the Mac app: nothing open until you open a day
    ui.click("button.dh", index=0)
    ui.wait("document.querySelectorAll('.card.open .slot').length > 20")
    assert "Golfclub Beispiel" in ui.js("document.querySelector('#club').selectedOptions[0].textContent")
    ui.shot("overview")


def test_a_day_opens_and_closes_like_an_accordion(ui):
    ui.click("button.dh", index=2)
    ui.wait("document.querySelectorAll('.card')[2].classList.contains('open')")
    ui.click("button.dh", index=2)
    ui.wait("!document.querySelectorAll('.card')[2].classList.contains('open')")
    ui.click("button.dh", index=1)  # leave the second day open for the next tests
    ui.wait("document.querySelectorAll('.card')[1].classList.contains('open')")


def test_booking_and_cancelling_a_time(ui):
    before = ui.count(".pill.booked")
    ui.click(".card.open .slot.clickable")
    ui.wait("document.querySelector('.sheet h2')")
    assert "on pc caddie" in ui.text(".sheet h2") and "Book now" in ui.text(".sheet .btn.pri")
    ui.shot("booking-dialog")
    ui.click(".sheet .btn.pri")
    ui.wait(f"document.querySelectorAll('.pill.booked').length === {before + 1}")
    ui.click(".card.open .slot.mine")
    ui.wait("document.querySelector('.sheet h2')")
    assert "Cancel your" in ui.text(".sheet h2")
    ui.click(".sheet .btn.danger")
    ui.wait(f"document.querySelectorAll('.pill.booked').length === {before}")


def test_the_reservations_window_lists_your_bookings_and_cancels_one(ui):
    ui.js("window.scrollTo(0, 0)")
    kept = ui.js("fetch('/api/reservations').then((r) => r.json()).then((j) => j.reservations[0])")  # the demo's booking, to put back at the end
    _open_sheet(ui, "b", "My reservations")
    ui.wait("document.querySelectorAll('.resv-list li').length > 0 && !document.querySelector('.sheet .status-line')")  # the demo has one booking
    shown = ui.text(".resv-list li")
    assert "11:00" in shown and "Golfclub Beispiel" in shown, shown
    ui.shot("reservations")
    ui.click(".resv-list .icon-btn.danger")
    ui.wait("document.querySelectorAll('.sheet').length === 2")
    assert "Cancel your" in ui.text(".sheet.small h2")
    ui.click(".sheet.small .btn.danger")
    ui.wait("document.querySelectorAll('.sheet').length === 1 && document.querySelector('.sheet .empty h3')")  # the list is checked again, then says it is empty
    assert "No upcoming reservations" in ui.text(".sheet") and ui.count(".resv-list li") == 0
    _close_sheet(ui)
    ui.wait("document.querySelectorAll('.pill.booked').length === 0")  # the overview follows
    ui.js(  # put the demo's booking back and start the next test on a fresh page
        f"""fetch('/api/booking', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({json.dumps(kept)})}}).then(() => {{ window.__beforeReload = true; location.reload(); }})"""
    )
    ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.pill.booked').length === 1")


def _tournament_month(ui, name):
    """Page the Tournaments window to the month that lists `name` (the demo's dates follow today)."""
    for _ in range(3):
        if ui.js(f"[...document.querySelectorAll('.tn-cell.has')].some((c) => c.getAttribute('aria-label').includes({json.dumps(name)}))"):
            return
        before = ui.text(".tn-month")
        ui.click(".tn-step:last-child")
        ui.wait(f"document.querySelector('.tn-month').textContent !== {json.dumps(before)}")
    raise AssertionError(f"{name} is in no month")


def test_the_tournament_calendar_is_a_month_grid_that_lists_the_day_you_tap(ui):
    ui.js("window.scrollTo(0, 0)")
    _open_sheet(ui, "t", "Tournaments")
    ui.wait("document.querySelectorAll('.tn-cell').length >= 28 && !document.querySelector('.sheet .status-line')")
    assert ui.count(".tn-wd") == 7 and ui.js("document.querySelectorAll('.tn-cell').length % 7") == 0  # whole weeks, seven columns
    columns = ui.js("[...new Set([...document.querySelectorAll('.tn-cell')].slice(0, 14).map((c) => Math.round(c.getBoundingClientRect().left)))].length")
    assert columns == 7  # every week lines up on the same seven columns
    _tournament_month(ui, "Twilight Scramble")
    ui.shot("tournaments-month")
    busy = ui.js("[...document.querySelectorAll('.tn-cell.has')].map((c) => c.getAttribute('aria-label'))")
    assert any("Autumn Trophy, Twilight Scramble" in label for label in busy), busy  # two on one day, both named
    first = ui.js("(() => { const cell = document.querySelector('.tn-cell.has'); const day = cell.getAttribute('aria-label').split(':')[0]; cell.click(); return day; })()")
    ui.wait("document.querySelector('.tn-cell.on')")
    assert ui.count(".tn-head") == 0  # no heading over the list: the calendar's title already names the month
    assert all(when.startswith(first) for when in ui.js("[...document.querySelectorAll('.tn-when b')].map((e) => e.textContent)"))  # only the picked day
    listed = ui.text(".tn-list")
    assert "Register by" in listed or "Registration" in listed
    assert ui.js("document.querySelector('.tn-item a[href*=\"sub=detail\"]').target") == "_blank"
    assert "entrylist" not in ui.js("document.querySelector('.sheet').innerHTML")  # the entry list names other members: never linked
    ui.shot("tournaments-day")
    ui.click(".tn-cell.on")  # a second tap clears the day: the month's list is back
    ui.wait("!document.querySelector('.tn-cell.on')")
    before = ui.text(".tn-month")
    ui.click(".tn-step:last-child")
    ui.wait(f"document.querySelector('.tn-month').textContent !== {json.dumps(before)}")
    _close_sheet(ui)


def test_the_tournament_filters_are_on_off_chips_that_narrow_the_list_and_the_dots(ui):
    ui.js("window.scrollTo(0, 0)")
    _open_sheet(ui, "t", "Tournaments")
    ui.wait("document.querySelectorAll('.tn-cell').length >= 28 && !document.querySelector('.sheet .status-line')")
    _tournament_month(ui, "Twilight Scramble")
    count = lambda: ui.count(".tn-item")  # noqa: E731
    everything, dots = count(), ui.count(".tn-cell.has")
    chips = ui.js("[...document.querySelectorAll('.tn-filters .tn-pick')].map((b) => b.textContent)")
    assert "All" not in chips and ui.count(".tn-filters .tn-pick[aria-pressed=true]") == 0, chips  # nothing on means everything shown
    ui.click(".tn-filters .tn-pick", text="9")
    ui.wait("document.querySelectorAll('.tn-item').length === 1")
    assert "Twilight Scramble" in ui.text(".tn-list") and ui.count(".tn-cell.has") < dots  # the dots follow the filter
    ui.click(".tn-filters .tn-pick", text="18")  # a second size adds to the first: 9 or 18
    ui.wait("document.querySelectorAll('.tn-item').length > 1")
    assert ui.count(".tn-filters .tn-pick[aria-pressed=true]") == 2
    ui.click(".tn-filters .tn-pick", text="Members only")
    ui.wait("[...document.querySelectorAll('.tn-item')].every((i) => i.textContent.includes('Members only'))")
    ui.click(".tn-filters .tn-pick", text="Guests welcome")  # both kinds on: no narrowing by who
    ui.wait(f"document.querySelectorAll('.tn-item').length >= {count() + 1} || [...document.querySelectorAll('.tn-item')].some((i) => i.textContent.includes('Guests welcome'))")
    ui.click(".tn-filters .tn-pick", text="9")  # off again
    ui.wait("![...document.querySelectorAll('.tn-item')].some((i) => i.textContent.includes('9 holes'))")
    ui.click(".tn-filters .icon-btn.danger")  # Clear filters
    ui.wait(f"document.querySelectorAll('.tn-item').length === {everything} && document.querySelectorAll('.tn-filters .tn-pick[aria-pressed=true]').length === 0")
    ui.click(".tn-filters > .tn-pick", text="Registration open")
    ui.wait("[...document.querySelectorAll('.tn-item')].every((i) => !i.textContent.includes('closed') && !i.textContent.includes('not open yet'))")
    _close_sheet(ui)


def test_the_refresh_button_sits_beside_the_status_it_renews(ui):
    ui.js("window.scrollTo(0, 0)")
    assert ui.count(".toolbar .refresh-btn, .toolbar-tools [aria-keyshortcuts=r]") == 0  # no longer in the toolbar
    gap = ui.js("""(() => { const b = document.querySelector('.footer .refresh-btn').getBoundingClientRect(), s = document.querySelector('.footer .status .dot').getBoundingClientRect();
      return s.left - b.right; })()""")
    assert 0 <= gap < 24, gap  # right next to the dot and the "updated ..." text
    ui.click(".footer .refresh-btn")
    ui.wait("document.querySelector('.footer .refresh-btn svg.spin') || document.querySelector('.footer .refresh-btn:not([disabled])')")


def test_a_tournament_slot_on_the_tee_sheet_opens_the_calendar_on_that_day(ui):
    ui.js("window.scrollTo(0, 0)")
    if not ui.js("document.querySelectorAll('.card')[1].classList.contains('open')"):  # the page remembers the day last opened
        ui.click("button.dh", index=1)  # the demo's day with the club championship blocking the midday times
    ui.wait("document.querySelector('.card.open .tourn-link')")
    name = ui.text(".card.open .tourn-link")
    assert "Clubmeisterschaften" in name
    assert ui.js("document.querySelectorAll('.card.open .slot.blocked .tourn-link').length") >= 3  # every blocked time of the event links
    ui.click(".card.open .tourn-link")
    ui.wait("document.querySelector('.sheet h2') && document.querySelector('.sheet h2').textContent === 'Tournaments' && document.querySelector('.tn-cell.on')")
    assert "Clubmeisterschaften" in ui.text(".tn-list")  # opened on that day, the event listed
    ui.shot("tournaments-from-slot")
    ui.click('.tn-item [aria-label="Tee sheet"]')  # and back to that day's times
    ui.wait("!document.querySelector('.scrim') && document.querySelectorAll('.card.open .slot').length > 20")


def test_a_booking_pc_caddie_refuses_says_why_and_the_dialog_stays_open(ui):
    ui.js(
        """(() => { const real = window.fetch.bind(window);
        window.fetch = async (url, options) => /api\\/booking/.test(String(url)) && options && options.method === 'POST'
          ? new Response(JSON.stringify({error: 'taken', message: 'no free seat'}), {status: 409, headers: {'Content-Type': 'application/json'}})
          : real(url, options); })()"""
    )
    try:
        ui.click(".card.open .slot.clickable")
        ui.wait("document.querySelector('.sheet .btn.pri')")
        ui.click(".sheet .btn.pri")
        ui.wait("document.querySelector('.sheet .status-line.error')")
        assert "no longer free" in ui.text(".sheet .status-line.error")  # in words, not a message key
        assert ui.count(".sheet") == 1 and ui.js("!document.querySelector('.sheet .btn.pri').disabled")  # still there, can be tried again
        ui.click(".sheet .btn", "Not now")
        ui.wait("!document.querySelector('.scrim')")
    finally:
        ui.js("window.__beforeReload = true; location.reload()")  # drop the rewriting again
        ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")


def test_search_lists_matches_and_offers_to_book_one(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.results .res:not(.res-head)').length > 3")
    ui.shot("search")
    # the column headings sit exactly over their values (every row has the same columns)
    edges = ui.js(
        """(() => { const right = (e) => Math.round(e.getBoundingClientRect().right);
        const head = [...document.querySelectorAll('.res-head .cell')].map(right);
        const row = [...document.querySelectorAll('.res:not(.res-head)')[0].querySelectorAll('.cell')].map(right);
        return [head, row]; })()"""
    )
    assert edges[0] == edges[1], edges
    assert ui.js("document.querySelector('.res .mark').textContent.trim()") == ""  # the booking button is only its flag
    assert ui.js("document.querySelector('.res .mark').getAttribute('aria-label')") == "Book"
    ui.click(".res .mark")
    ui.wait("document.querySelectorAll('.sheet').length === 2")
    ui.click(".sheet.small .btn", "Not now")
    ui.wait("document.querySelectorAll('.sheet').length === 1")
    _close_sheet(ui)


def test_search_filters_with_chips_and_a_strip_of_days_that_counts_matches(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.strip .sday').length === 14 && document.querySelectorAll('.results .res:not(.res-head)').length > 3")
    start = _search_rows(ui)
    assert _chip_on(ui, "My times") == "true"  # your Preferences are on when Search opens
    assert ui.js("document.querySelectorAll('.dayhead').length") >= 1
    shown = int(ui.js("[...document.querySelectorAll('.res-head .rcount')][0].textContent.match(/\\d+/)[0]"))
    assert shown == start  # the line above the results counts the same rows
    counted = ui.js("[...document.querySelectorAll('.strip .sday .c')].map((e) => Number(e.textContent) || 0).reduce((a, b) => a + b, 0)")
    assert counted == start  # and so do the days of the strip, together
    ui.js("document.querySelector('.strip .sday:not(.off):not(.zero):not(.empty)').click()")  # one day: its rows only, no day heading needed
    ui.wait("document.querySelectorAll('.dayhead').length === 0 && document.querySelectorAll('.strip .sday[aria-pressed=true]').length === 1")
    assert 0 < _search_rows(ui) <= start
    ui.js("document.querySelector('.strip .sday[aria-pressed=true]').click()")  # and back
    ui.wait(f"document.querySelectorAll('.results .res:not(.res-head)').length === {start}")
    _chip(ui, "Weekend")  # weekdays dim in the strip, the list keeps weekend days only
    ui.wait("document.querySelectorAll('.strip .sday.off').length > 0")
    assert ui.js("[...document.querySelectorAll('.dayhead')].every((e) => /Sat|Sun/.test(e.textContent))") is True
    _chip(ui, "Weekend")
    _chip(ui, "My times")  # turning your rules off shows more
    ui.wait(f"document.querySelectorAll('.results .res:not(.res-head)').length > {start}")
    _close_sheet(ui)


def test_search_weather_stays_under_its_headings_in_every_window_width(ui):
    """A hit nobody has booked yet has no players: its temperature, rain and wind must still sit under their
    headings, and the button never lands on the weather."""
    try:
        _open_sheet(ui, "s", "Search")
        ui.wait("document.querySelector('.sf') && document.querySelectorAll('.results .res:not(.res-head)').length > 3")
        _chip(ui, "4")  # four open seats: only slots with nobody booked
        ui.wait("(() => { const rows = [...document.querySelectorAll('.results .res:not(.res-head)')]; return rows.length > 0 && rows.every((r) => r.querySelector('.res-open').textContent.includes('4')); })()")
        for width in (1280, 1000, 860, 744):
            ui.call("Emulation.setDeviceMetricsOverride", width=width, height=900, deviceScaleFactor=1, mobile=False)
            ui.wait(f"innerWidth === {width}")
            edges = ui.js(
                """(() => { const right = (e) => Math.round(e.getBoundingClientRect().right);
                const rows = [...document.querySelectorAll('.res:not(.res-head)')];
                const button = (r) => r.querySelector('.res-action .btn').getBoundingClientRect();
                return {head: [...document.querySelectorAll('.res-head .cell')].map(right),
                        rows: rows.map((r) => [...r.querySelectorAll('.cell')].map(right)),
                        overlap: rows.some((r) => [...r.querySelectorAll('.cell')].some((c) => c.getBoundingClientRect().right > button(r).left + 1))}; })()"""
            )
            assert all(row == edges["head"] for row in edges["rows"]), (width, edges)
            assert not edges["overlap"], (width, edges)
    finally:
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        _close_sheet(ui)


def test_search_rows_are_one_height_and_keep_their_times_on_one_line(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.results .res:not(.res-head)').length > 3")
    shape = ui.js(
        """(() => { const rows = [...document.querySelectorAll('.res:not(.res-head)')];
        return [new Set(rows.map((r) => Math.round(r.getBoundingClientRect().height))).size,
                rows.every((r) => getComputedStyle(r.querySelector('.res-time')).whiteSpace === 'nowrap')]; })()"""
    )
    assert shape == [1, True], shape  # every row is as tall as the others: no time wraps onto a second line
    _close_sheet(ui)


def test_heatmap_shows_the_history(ui):
    _open_sheet(ui, "h", "heatmap")
    ui.wait("document.querySelectorAll('.hm-cell').length > 20")
    ui.shot("heatmap")
    _close_sheet(ui)


def test_the_player_directory_filters_by_club_and_gender_together_with_its_sorting(ui):
    _open_sheet(ui, "p", "Player")
    ui.wait("document.querySelectorAll('.player-list li .player-name').length > 5")
    every = ui.count(".player-list li .player-name")
    clubs = ui.js("[...document.querySelectorAll('#p-club option')].map((o) => o.textContent)")
    assert clubs == ["All clubs", "Beispiel", "Guests"], clubs  # the clubs the list knows (short, so the menu stays narrow), and guests
    ui.set("#p-gender", "female")
    ui.wait(f"document.querySelectorAll('.player-list li .player-name').length < {every}")
    assert ui.js("[...document.querySelectorAll('.player-list li .player-name')].every((e) => e.classList.contains('alt'))")  # only women
    ui.set("#p-sort", "club")  # sorting keeps the filter, and heads the list with the club
    ui.wait("document.querySelector('.player-list li.letter')?.textContent === 'Golfclub Beispiel'")
    assert ui.js("[...document.querySelectorAll('.player-list li .player-name')].every((e) => e.classList.contains('alt'))")
    assert ui.count(".alpha") == 0  # the A-Z index belongs to the name order only
    ui.set("#p-club", "__guests")  # every demo player is a member here
    ui.wait("document.querySelectorAll('.player-list li .player-name').length === 0")
    ui.set("#p-club", "all")
    ui.set("#p-gender", "all")
    ui.set("#p-sort", "name")
    ui.wait(f"document.querySelectorAll('.player-list li .player-name').length === {every}")
    _close_sheet(ui)


def test_players_can_be_marked_as_friends(ui):
    _open_sheet(ui, "p", "Player")
    ui.wait("document.querySelectorAll('.player-list li').length > 3")
    ui.shot("players")
    ui.js("document.querySelector('.star-btn:not(.on)').click()")
    ui.wait("document.querySelectorAll('.star-btn.on').length >= 3")
    ui.set(".players-tools input[type=search]", "zzzz")
    ui.wait("document.querySelectorAll('.player-list li:not(.player-head)').length === 0")
    _close_sheet(ui)


def test_preferences_save_and_come_back(ui):
    _open_sheet(ui, "e", "Preferences")
    ui.wait("document.querySelector('#f-field-availability-min_open_spots')")
    ui.shot("preferences")
    ui.set("#f-field-availability-min_open_spots", "3")
    ui.click(".actions .btn.pri")
    ui.wait("document.querySelector('.status-line.ok')")
    _close_sheet(ui)
    _open_sheet(ui, "e", "Preferences")
    ui.wait("document.querySelector('#f-field-availability-min_open_spots')?.value === '3'")
    ui.set("#f-field-availability-min_open_spots", "2")
    ui.click(".actions .btn.pri")
    ui.wait("document.querySelector('.status-line.ok')")
    _close_sheet(ui)


def test_settings_save_the_login_and_report_what_pc_caddie_said(ui):
    _open_sheet(ui, ",", "Settings")
    ui.wait("document.querySelector('#login-user')")
    ui.shot("settings")
    ui.set("#login-user", "someone@example.com")
    ui.set("#login-pass", "hunter2")
    ui.click("form .btn.pri", "Save and check")
    ui.wait("document.querySelector('.status-line.error')")
    assert "rejected" in ui.text(".status-line.error")  # the offline demo's login is always refused
    ui.set("#ai-key", "sk-test")
    ui.click("form .btn", "Save key")
    ui.wait("document.querySelectorAll('.status-line.error').length >= 2")
    _close_sheet(ui)


def test_add_club_finds_clubs_adds_one_and_opens_another(ui):
    ui.key("a")
    ui.wait("document.querySelector('.search-box input')")
    ui.set(".search-box input", "golf")
    ui.wait("document.querySelectorAll('.club-results li').length > 5")
    ui.shot("add-club")
    ui.click(".club-results .btn.pri", "Add")
    ui.wait("document.querySelector('.saved-mark')")
    ui.click(".club-results .btn", "Open")
    ui.wait("document.querySelector('.preview-bar')")
    assert "not in your clubs" in ui.text(".preview-bar")
    ui.wait("document.querySelector('.empty h2') && document.querySelector('.empty h2').textContent.includes('no online tee sheet')")
    ui.shot("preview")
    ui.click(".preview-bar .btn", "Close")
    ui.wait("!document.querySelector('.preview-bar') && document.querySelectorAll('.card').length > 0")
    options = ui.js("[...document.querySelectorAll('#club option')].map((o) => o.textContent)")
    assert len(options) == 3 and options[-1].startswith("＋"), options  # the demo club, the one just added, "Add club..."
    assert options[:2] == sorted(options[:2], key=str.casefold), options  # clubs are in alphabetical order


BACKGROUND = "getComputedStyle(document.body).backgroundColor"


def _open_view(ui):
    ui.key("v")
    ui.wait("document.querySelector('.view-panel #v-hcp')")
    ui.js("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")  # let the page finish drawing


def _open_display(ui):
    """Settings, where language, theme, size and units live (set once, so not in the View menu)."""
    ui.key(",")
    ui.wait("document.querySelector('.sheet .display-group #v-theme')")
    ui.wait(SHEET_READY)
    ui.js("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")


def _close_display(ui):
    ui.key("Escape")
    ui.wait("!document.querySelector('.scrim')")


def test_the_view_menu_holds_three_switches_and_settings_the_rest(ui):
    _open_view(ui)
    ui.shot("view-menu")
    assert [ui.count(c) for c in ("#v-hcp", "#v-tips", "#v-history")] == [1, 1, 1]
    assert ui.count(".view-panel select, .view-panel .stepper") == 0  # language, theme, size and units moved out
    assert ui.count(".view-panel .view-more") == 0  # no explaining line: the Legend says where things are
    ui.key("Escape")
    ui.wait("!document.querySelector('.view-panel')")
    _open_display(ui)  # Settings: a Display group that applies at once, and About with the version and the update check
    for control in ("#v-language", "#v-theme", "#v-units"):
        assert ui.count(".display-group " + control) == 1, control
    assert ui.count(".display-group .stepper button") == 2
    assert ui.count("#f-field-__language__") == 0 and ui.count("#f-field-units") == 0  # not twice
    assert re.search(r"v\d", ui.text(".about-group")) and ui.count(".about-group .check-update") == 1
    ui.shot("settings-display")
    _close_display(ui)


def test_a_theme_is_chosen_in_settings_and_survives_a_reload(ui):
    _open_display(ui)
    ui.set("#v-theme", "solarized-light")
    ui.wait(f"{BACKGROUND} === 'rgb(253, 246, 227)'")
    ui.shot("theme-solarized-light")
    ui.js("window.__beforeReload = true; location.reload()")
    # wait for the NEW page: the old one still shows cards and the theme until the reload replaces it
    ui.wait(f"window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0 && {BACKGROUND} === 'rgb(253, 246, 227)'")
    _open_display(ui)
    ui.set("#v-theme", "catppuccin")
    ui.wait(f"{BACKGROUND} === 'rgb(30, 30, 46)'")
    _close_display(ui)


def test_the_scale_is_stepped_in_settings_and_remembered(ui):
    assert ui.js("getComputedStyle(document.documentElement).fontSize") == "12.8px"
    _open_display(ui)
    ui.click(".display-group .stepper button", "A+")
    ui.wait("getComputedStyle(document.documentElement).fontSize === '14.4px'")
    assert "90" in ui.text(".stepper-value")
    ui.js("localStorage.getItem('tm_scale') === '90' || (() => { throw new Error('not saved'); })()")
    ui.click(".display-group .stepper button", "A−")
    ui.wait("getComputedStyle(document.documentElement).fontSize === '12.8px'")
    _close_display(ui)


def test_units_switch_in_settings_and_handicaps_in_the_view_menu(ui):
    if not ui.count(".card.open"):  # (closing a looked-at club leaves every day collapsed)
        ui.click("button.dh", index=0)
        ui.wait("document.querySelector('.card.open .names')")
    before = ui.js("document.querySelector('.dh .temp').textContent")
    names = "document.querySelector('.card.open .names')?.textContent || ''"
    assert "(18.4)" in ui.js(names) or "(22.1)" in ui.js(names)
    _open_display(ui)
    ui.set("#v-units", "imperial")
    ui.wait(f"document.querySelector('.dh .temp').textContent !== {json.dumps(before)}")
    ui.set("#v-units", "metric")
    ui.wait(f"document.querySelector('.dh .temp').textContent === {json.dumps(before)}")
    _close_display(ui)
    _open_view(ui)
    ui.js("document.querySelector('#v-hcp').click()")
    ui.wait(f"!/\\(\\d+\\.\\d\\)/.test({names})")
    ui.js("document.querySelector('#v-hcp').click()")  # and back to how it was
    ui.wait(f"/\\(\\d+\\.\\d\\)/.test({names})")
    ui.key("Escape")


def test_the_language_switches_to_german_in_settings_and_back(ui):
    _open_display(ui)
    ui.set("#v-language", "de")
    ui.wait("document.querySelector('.tool-label')?.textContent === 'Suchen'", 30)
    ui.shot("overview-de")
    assert ui.js("document.documentElement.lang") == "de"  # screen readers pronounce German as German
    _open_view(ui)
    assert ui.js("document.querySelector('.tool.on .tool-label').textContent") == "Ansicht"
    ui.key("Escape")
    _open_display(ui)
    ui.set("#v-language", "en")
    ui.wait("document.querySelector('.tool-label')?.textContent === 'Search'", 30)


def test_clear_filters_shows_everything_and_is_in_reach(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.results .res:not(.res-head)').length > 3")
    start = _search_rows(ui)
    assert ui.count(".sf-actions .sf-clear") == 1  # right after the filters while anything is on
    _chip(ui, "Weekend")
    _chip(ui, "3+")
    ui.click(".sf-actions .sf-clear")
    ui.wait("document.querySelectorAll('.sf .chip[aria-pressed=true]').length === 1")  # only "1+" is left on: nothing narrows
    assert _search_rows(ui) > start  # your own rules are off too: more than when Search opened
    assert ui.count(".sf-actions .sf-clear") == 0  # nothing left to clear
    ui.click(".sf-actions .sf-reset")  # one tap back to your Preferences
    ui.wait(f"document.querySelectorAll('.results .res:not(.res-head)').length === {start} && document.querySelectorAll('.sf-actions .sf-reset').length === 0")
    assert _chip_on(ui, "My times") == "true" and _chip_on(ui, "2+") == "true"
    assert ui.js("getComputedStyle(document.querySelector('.sf-actions .sf-clear')).color") != ui.js("getComputedStyle(document.querySelector('.sf-chip')).color")  # (the trash can is red)
    _close_sheet(ui)


def test_the_default_course_sits_on_the_club_row(ui):
    _open_sheet(ui, ",", "Settings")
    ui.wait("document.querySelector('.club-head .select select')")
    heads = ui.js(
        """(() => { const r = (e) => { const b = e.getBoundingClientRect(); return b.top + b.height / 2; };
        const head = [...document.querySelectorAll('.club-head')].find((h) => h.querySelector('.select'));
        return [r(head.querySelector('strong')), r(head.querySelector('.select')), r(head.querySelector('.icon-btn.danger'))]; })()"""
    )
    assert max(heads) - min(heads) < 4, heads  # name, course and Remove on one line
    _close_sheet(ui)


def test_an_opened_day_keeps_its_header_pinned_and_scrolls_to_its_pick(ui):
    ui.js("window.scrollTo(0, 0)")
    ui.click("button.dh", index=3)  # opens the fourth day (the accordion closes the others)
    ui.wait("document.querySelectorAll('.card')[3].classList.contains('open')")
    pick = ui.text(".card.open .pill.pick").strip()
    ui.wait(f"(() => {{ const r = document.querySelector('.card.open [data-slot$=\" {pick}\"]'); if (!r) return false; const b = r.getBoundingClientRect(); return b.top > 100 && b.bottom < window.innerHeight; }})()")
    ui.js("window.scrollBy(0, 400)")
    ui.wait("(() => { const h = document.querySelector('.card.open .dh-wrap').getBoundingClientRect().top; const bar = document.querySelector('.toolbar').getBoundingClientRect().bottom; return Math.abs(h - bar) < 3; })()")
    dimmed = ui.count(".card.open .slot.dimmed")
    assert dimmed > 5  # slots outside your availability window are dimmed
    ui.js("window.scrollTo(0, 0)")
    ui.click("button.dh", index=3)
    ui.click("button.dh", index=1)
    ui.wait("document.querySelectorAll('.card')[1].classList.contains('open')")


def test_the_player_list_scrolls_under_a_fixed_search_with_letter_headers(ui):
    ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=380, deviceScaleFactor=1, mobile=False)  # short: ten players do not fit
    _open_sheet(ui, "p", "Player")
    ui.wait("document.querySelectorAll('.player-list li').length > 8")
    heads = ui.js("[...document.querySelectorAll('.player-head span')].map((e) => e.textContent.trim()).filter(Boolean)")
    assert heads == ["Name", "Gender", "Club", "HCP", "Next tee time"], heads  # every column of the directory is shown (Club: where each one is a member)
    assert ui.js("document.querySelector('.player-list li:not(.letter) .player-meta').textContent.trim()") in ("Male", "Female", "Unknown")
    heads = ui.js("[...document.querySelectorAll('.player-head span')].map((e) => e.textContent.trim()).filter(Boolean)")
    assert heads == ["Name", "Gender", "Club", "HCP", "Next tee time"], heads  # every column of the directory is shown (Club: where each one is a member)
    edges = ui.js(
        """(() => { const list = document.querySelector('.player-list').getBoundingClientRect();
        const head = document.querySelector('.player-head .r').getBoundingClientRect();
        const cell = document.querySelector('.player-list li:not(.letter):not(.player-head) .player-hcp').getBoundingClientRect();
        return [list.right - cell.right, head.right - cell.right]; })()"""
    )
    assert edges[0] >= 8, edges  # the HCP column is not under the scrollbar
    assert abs(edges[1]) < 1.5, edges  # and the header sits right above it
    assert ui.count("li.letter") >= 3
    assert ui.count(".alpha button") >= 3
    top = ui.js("document.querySelector('.players-tools').getBoundingClientRect().top")
    ui.js("document.querySelector('.player-list').scrollTop = 120")
    assert ui.js("document.querySelector('.player-list').scrollTop") > 0
    assert ui.js("document.querySelector('.players-tools').getBoundingClientRect().top") == top  # the search stays put
    ui.js("document.querySelector('.player-list').scrollTop = 0")
    ui.js("document.querySelector('.alpha button:last-child').click()")  # jumps to the last letter
    ui.wait("document.querySelector('.player-list').scrollTop > 20")
    _close_sheet(ui)
    ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)


def test_the_hover_highlight_covers_a_day_with_its_event_note(ui):
    box = ui.js(
        """(() => { const dh = [...document.querySelectorAll('button.dh')].find((b) => b.querySelector('.events'));
        if (!dh) return null; const d = dh.getBoundingClientRect(); const e = dh.querySelector('.events').getBoundingClientRect();
        return [d.top, d.bottom, e.top, e.bottom]; })()"""
    )
    assert box is not None, "the demo has days with events"
    assert box[0] <= box[2] and box[3] <= box[1], box  # the note sits inside the button, so inside the highlight


def test_the_days_show_before_the_picks_are_ready(ui):
    """With AI ranking on, the picks take seconds: the days must not wait for them. The page's second
    request (the one with picks) is held back here to see the in-between state."""
    ui.js(
        """(() => { const real = window.fetch.bind(window);
        window.fetch = (url, options) => /api\\/overview/.test(String(url)) && !/picks=0/.test(String(url))
          ? new Promise((done) => setTimeout(done, 2500)).then(() => real(url, options)) : real(url, options); })()"""
    )
    if not ui.count(".card.open"):
        ui.click("button.dh", index=1)
        ui.wait("document.querySelector('.card.open .slot.clickable')")
    ui.click(".card.open .slot.clickable")  # marking a booking drops the ranked picks, so they are worked out again
    ui.wait("document.querySelector('.sheet .btn.pri')")
    ui.click(".sheet .btn.pri")
    ui.wait("document.querySelector('.footer')?.textContent.includes('updating picks')", 30)
    assert ui.count(".card") == 5  # the days are on screen while the picks are still being worked out
    ui.wait("!document.querySelector('.footer')?.textContent.includes('updating picks')", 30)
    ui.click(".card.open .slot.mine")  # put the booking back as it was
    ui.wait("document.querySelector('.sheet .btn.danger')")
    ui.click(".sheet .btn.danger")
    ui.js("window.__beforeReload = true; location.reload()")  # drop the delay again
    ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")


def test_the_window_hint_and_the_shorter_round_badge(ui):
    """The server sends a standing hint (your window opens too late) and, on a day ruled out by daylight, a
    shorter round on another course. The demo data has neither, so the overview responses are rewritten here:
    a second course "Other" exists, and the second day offers a 9-hole slot on it."""
    ui.js(
        """(() => { const real = window.fetch.bind(window);
        window.fetch = async (url, options) => { const response = await real(url, options);
          if (!/api\\/overview/.test(String(url))) return response;
          const data = await response.json();
          data.courses = [...new Set([...data.courses, 'Other'])];
          if (/course=Other/.test(String(url))) data.course = 'Other';
          data.hint = {window_after: '17:00', latest_start: '15:40', sunset: '19:08', round_minutes: 240, days: 3, alternative_courses: ['Other']};
          const slot = data.days[1].slots.find((s) => !s.past && s.block_reason == null && s.time > '12:00');
          data.days[1].pick = {alternative: {time: slot.time, course: 'Other', holes: 9}};
          return new Response(JSON.stringify(data), {status: 200, headers: {'Content-Type': 'application/json'}}); }; })()"""
    )
    _open_sheet(ui, "e", "Preferences")  # saving reloads the overview, now through the rewritten fetch
    ui.wait("document.querySelector('#f-field-availability-min_open_spots')")
    ui.click(".actions .btn.pri")
    ui.wait("document.querySelector('.status-line.ok')")
    _close_sheet(ui)
    ui.wait("document.querySelector('.hint-bar')")
    ui.shot("hint")
    text = ui.text(".hint-bar")
    assert "17:00" in text and "15:40" in text and "19:08" in text and "4 h" in text and "Other" in text, text
    ui.click(".hint-bar .icon-btn", index=0)  # the gear: the way straight to the setting
    ui.wait("document.querySelector('.sheet h2')?.textContent.includes('Preferences')")
    _close_sheet(ui)
    badge = ".pill.link"
    time_text = ui.text(badge).split("·")[0].strip()
    ui.click(badge)
    ui.wait("document.querySelector('.toolbar select#course')?.value === 'Other' || document.querySelector('#course')?.value === 'Other'")
    ui.wait(f"document.querySelector('.card.open [data-slot$=\" {time_text}\"].flash')")  # the slot is open, in view and flashing
    assert ui.js("document.querySelectorAll('.card.open').length") == 1
    ui.js("window.__beforeReload = true; location.reload()")  # drop the rewriting again
    ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")


def test_weather_icons_name_the_exact_condition(ui):
    title = ui.js("document.querySelector('.dh .cond').title")
    assert title and title[0].isupper(), title  # "Light rain", not the category "rain / rain showers"


def test_a_booked_player_can_be_jumped_to_from_the_directory(ui):
    ui.js("window.scrollTo(0, 0)")
    _open_sheet(ui, "p", "Player")
    ui.wait("document.querySelectorAll('.player-list li').length > 3")
    ui.shot("players-jump")
    assert ui.count(".tee-btn") > 0  # people seen on the loaded days show their next tee time, as a button
    assert "next tee time" in ui.text(".player-head").lower()
    name = ui.js("document.querySelector('.tee-btn').closest('li').querySelector('.player-name').textContent")
    ui.js("document.querySelector('.tee-btn').click()")
    hits = ui.js(
        """(() => { const e = document.querySelector('.jump-choice'); return e ? [...e.querySelectorAll('.btn')].length - 1 : 0; })()"""
    )
    if hits:  # booked more than once: asks which tee time
        ui.click(".jump-choice .btn", index=0)
    ui.wait("!document.querySelector('.scrim')")
    ui.wait("document.querySelector('.card.open .slot.flash')")
    assert name in ui.text(".card.open .slot.flash"), name
    # A double-click on a name does the same
    ui.js("window.scrollTo(0, 0)")
    _open_sheet(ui, "p", "Player")
    ui.wait("document.querySelectorAll('.player-list li').length > 3")
    ui.js("document.querySelector('.tee-btn').closest('li').dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))")
    hits = ui.count(".jump-choice")
    if hits:
        ui.click(".jump-choice .btn", index=0)
    ui.wait("!document.querySelector('.scrim')")
    ui.wait("document.querySelector('.card.open .slot.flash')")
    # And a player with no tee time on the loaded days gets a notice instead of a jump
    ui.js(
        """(() => { const real = window.fetch.bind(window);
        window.fetch = async (url, options) => { const response = await real(url, options);
          if (!/api\\/players/.test(String(url)) || (options && options.method)) return response;
          const data = await response.json();
          for (const player of data.players) player.upcoming = [];
          return new Response(JSON.stringify(data), {status: 200, headers: {'Content-Type': 'application/json'}}); }; })()"""
    )
    _open_sheet(ui, "p", "Player")
    ui.wait("document.querySelectorAll('.player-list li').length > 3")
    assert ui.count(".tee-btn") == 0
    ui.js("document.querySelector('.player-list li:not(.letter):not(.player-head)').dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))")
    ui.wait("document.querySelector('.sheet .banner')")
    _close_sheet(ui)
    ui.js("window.__beforeReload = true; location.reload()")
    ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")


def test_form_fields_have_air_between_them_and_the_last_row_clears_the_window_edge(ui):
    """Fields in a form are at least 10 px apart (they once sat 2 px apart on a touch screen, where controls are taller),
    and the last control of a scrolling window clears its bottom edge once scrolled all the way down."""
    try:
        for width, height, touch in ((1280, 800, False), (1000, 617, False), (1180, 820, True), (390, 800, True)):
            ui.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=touch)
            ui.call("Emulation.setEmulatedMedia", features=[{"name": "pointer", "value": "coarse"}] if touch else [])
            for key in (",", "e"):
                ui.js("window.scrollTo(0, 0)")
                _open_sheet(ui, key, "")
                ui.wait("document.querySelector('.sheet .field-row')")
                shape = ui.js(
                    """(() => { const sheet = [...document.querySelectorAll('.sheet')].pop();
                    const fields = [...sheet.querySelectorAll('.field-row > :last-child')].filter((e) => e.getBoundingClientRect().height > 4).map((e) => e.getBoundingClientRect());
                    let tightest = 99;
                    for (const a of fields) for (const b of fields) { const overlap = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                      const gap = b.top - a.bottom; if (overlap > 20 && gap > -1) tightest = Math.min(tightest, gap); }
                    const body = [...sheet.querySelectorAll('.sheet-body')].pop(); body.scrollTop = body.scrollHeight;
                    const bottom = Math.max(...[...body.querySelectorAll('*')].filter((e) => e.getBoundingClientRect().height > 2).map((e) => e.getBoundingClientRect().bottom));
                    return {fields: fields.length, tightest, clearance: Math.round(body.getBoundingClientRect().bottom - bottom)}; })()"""
                )
                assert shape["fields"] >= 2 and shape["tightest"] >= 10, (key, width, height, touch, shape)
                assert shape["clearance"] >= 8, (key, width, height, touch, shape)
                _close_sheet(ui)
    finally:
        ui.call("Emulation.setEmulatedMedia", features=[])
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)


def test_weather_numbers_and_icons_are_colored(ui):
    """Temperature, rain and wind carry a color that follows their value (cold blue ... hot red, wetter = bluer,
    windier = amber/red), and weather icons have their own; a calm dry value stays grey."""
    ui.js("window.scrollTo(0, 0)")
    colored = ui.js(
        """(() => { const style = (sel) => [...document.querySelectorAll(sel)].map((e) => e.getAttribute('style') || '');
        return {temps: style('.dh .temp span[style]').length, rain: style('.dh .rain[style]').length, wind: style('.dh .wind[style]').length,
                icons: [...document.querySelectorAll('.dh .cond')].map((e) => e.className + '|' + getComputedStyle(e).color)}; })()"""
    )
    assert colored["temps"] >= 4 and colored["rain"] >= 1 and colored["wind"] >= 1, colored
    kinds = {entry.split("|")[0] for entry in colored["icons"]}
    colors = {entry.split("|")[1] for entry in colored["icons"]}
    assert len(kinds) >= 3 and len(colors) >= 3, colored["icons"]  # sunny, rainy and cloudy days do not look alike
    ui.click("button.dh", index=2)
    ui.wait("document.querySelector('.card.open .slot .temp')")
    cells = ui.js("[...document.querySelectorAll('.card.open .slot .temp')].map((e) => e.getAttribute('style') || '').filter(Boolean).length")
    assert cells > 5
    ui.click("button.dh", index=2)


def test_the_jump_choice_lines_its_buttons_up_at_every_width(ui):
    """A player with several tee times is asked which one: the question sits on its own line and the buttons are one
    width and line up (on a phone they once wrapped into three different widths beside the question)."""
    ui.js(
        """(() => { const real = window.fetch.bind(window);
        window.fetch = async (url, options) => { const response = await real(url, options);
          if (!/api\\/players/.test(String(url)) || (options && options.method)) return response;
          const data = await response.json();
          data.players[0].upcoming = [{date: data.players[0].upcoming?.[0]?.date || '2030-01-02', time: '10:40', course: '9 Loch Tee 1'},
            {date: '2030-01-02', time: '14:40', course: '18 Loch Tee 1'}, {date: '2030-01-03', time: '11:10', course: '18 Loch Tee 1'}];
          return new Response(JSON.stringify(data), {status: 200, headers: {'Content-Type': 'application/json'}}); }; })()"""
    )
    try:
        for width in (1280, 390):
            ui.call("Emulation.setDeviceMetricsOverride", width=width, height=900, deviceScaleFactor=1, mobile=width < 500)
            ui.js("window.scrollTo(0, 0)")
            _open_sheet(ui, "p", "Player")
            ui.wait("document.querySelectorAll('.player-list li').length > 3")
            ui.js("document.querySelector('.player-list li:not(.letter):not(.player-head)').dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))")
            ui.wait("document.querySelector('.jump-choice')")
            shape = ui.js(
                """(() => { const box = document.querySelector('.jump-choice'); const label = box.querySelector('span').getBoundingClientRect();
                const buttons = [...box.querySelectorAll('.btn')].map((b) => b.getBoundingClientRect());
                return {labelWidth: Math.round(label.width), boxWidth: Math.round(box.getBoundingClientRect().width - 32),
                        widths: [...new Set(buttons.map((b) => Math.round(b.width)))], below: buttons.every((b) => b.top >= label.bottom - 1),
                        inside: buttons.every((b) => b.right <= box.getBoundingClientRect().right + 1), count: buttons.length}; })()"""
            )
            assert shape["count"] == 4 and shape["labelWidth"] >= shape["boxWidth"] - 2, (width, shape)  # the question has the whole line
            assert len(shape["widths"]) == 1 and shape["below"] and shape["inside"], (width, shape)  # equal buttons, under it
            ui.shot(f"jump-choice-{width}")
            _close_sheet(ui)
    finally:
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        ui.js("window.__beforeReload = true; location.reload()")
        ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")


def test_a_newer_version_is_announced_and_a_pi_server_can_install_it(ui, hurry):
    """Rewritten answers stand in for GitHub and for a Pi: a newer release exists and this server may update
    itself; the install then fails, which must be shown and leave the page usable."""
    ui.js(
        """(() => { const real = window.fetch.bind(window); window.__polls = 0;
        const json = (body) => new Response(JSON.stringify(body), {status: 200, headers: {'Content-Type': 'application/json'}});
        const info = {current: '0.78.0', latest: '9.9.9', newer: true, url: 'https://example.invalid/notes', command: null, can_update: true, install: {state: 'idle', error: null}};
        window.fetch = async (url, options) => {
          if (/api\\/update\\/apply/.test(String(url))) return json({state: 'running', error: null});
          if (/api\\/update/.test(String(url))) { window.__polls += options && options.method ? 0 : 1;
            return json({...info, install: window.__polls > 1 ? {state: 'failed', error: 'no matching distribution'} : info.install}); }
          return real(url, options); }; })()"""
    )
    ui.js("window.dispatchEvent(new Event('focus'))")  # the page looks again when you come back to the tab
    ui.wait("document.querySelector('.update-banner')")
    ui.shot("update-notice")
    assert "Version 9.9.9 is available" in ui.text(".update-banner")
    assert ui.js("document.querySelector('.update-banner a').href") == "https://example.invalid/notes"
    ui.click(".update-banner .btn.pri")
    ui.wait("document.querySelector('.sheet h2')?.textContent.includes('9.9.9')")
    ui.shot("update-sheet")
    ui.click(".sheet .btn", "Cancel")
    ui.wait("!document.querySelector('.scrim')")
    ui.click(".update-banner .btn.pri")
    ui.wait("document.querySelector('.sheet .btn.pri')")
    ui.click(".sheet .btn.pri")  # install: the first poll says "idle", the next one "failed"
    ui.wait("document.querySelector('.sheet .status-line.error')?.textContent.includes('no matching distribution')", 30)
    ui.click(".sheet .btn", "Cancel")
    ui.wait("!document.querySelector('.scrim')")
    assert ui.count(".card") > 0  # the page is still usable
    # the banner sits above the days (not in the footer) and can be dismissed for that version
    assert ui.js("document.querySelector('.update-banner').getBoundingClientRect().bottom <= document.querySelector('.card').getBoundingClientRect().top")
    ui.click(".update-banner .icon-btn")
    ui.wait("!document.querySelector('.update-banner')")
    ui.js("window.dispatchEvent(new Event('focus'))")
    ui.js("new Promise((done) => setTimeout(done, 500))")
    assert ui.count(".update-banner") == 0  # still gone after the page looked again
    ui.js("localStorage.removeItem('tm_update_dismissed'); window.__beforeReload = true; location.reload()")  # drop the rewriting again
    ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")


def test_the_page_waits_for_a_fresh_server_process_after_an_update(ui, hurry):
    """After the install the old process still answers (and already reports the new version): the page must
    wait until it has gone down and a new one says "idle", then reload. Here the server answers "restarting",
    fails twice, then answers "idle" -- the page must reload only then."""
    ui.js(
        """(() => { const real = window.fetch.bind(window); let polls = 0;
        const json = (body) => new Response(JSON.stringify(body), {status: 200, headers: {'Content-Type': 'application/json'}});
        const info = {current: '0.78.0', latest: '9.9.9', newer: true, url: 'https://example.invalid/notes', command: null, can_update: true};
        window.fetch = async (url, options) => {
          if (/api\\/update\\/apply/.test(String(url))) return json({state: 'running', error: null});
          if (/api\\/update/.test(String(url))) { polls += 1; window.__updatePolls = polls;
            if (polls === 1) return json({...info, install: {state: 'restarting', error: null}});
            if (polls <= 3) throw new TypeError('Failed to fetch');
            return json({...info, install: {state: 'idle', error: null}}); }
          return real(url, options); }; })()"""
    )
    ui.js("window.dispatchEvent(new Event('focus'))")  # polls = 1: "restarting" is what the sheet sees first ...
    ui.wait("document.querySelector('.update-banner .btn.pri')")
    ui.js("window.__beforeReload = true")
    ui.click(".update-banner .btn.pri")
    ui.wait("document.querySelector('.sheet .btn.pri')")
    ui.click(".sheet .btn.pri")
    ui.wait("document.querySelector('.sheet .status-line')?.textContent.includes('Restarting')", 30)
    assert ui.js("window.__beforeReload") is True  # not reloaded while the old process still answered
    ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0", 60)  # reloaded by the "idle" answer


def test_check_for_updates_says_what_it_found(ui, hurry):
    # the demo server never calls out (the check is switched off there): the button says so
    ui.shot("footer-check")
    ui.click(".footer .check-update")
    ui.wait("document.querySelector('.check-update')?.textContent.includes('switched off')")
    ui.wait("document.querySelector('.check-update')?.textContent === 'Check for updates'", 15)  # back to normal after a few seconds
    # answers standing in for GitHub: up to date, a failure, and a newer release
    ui.js(
        """(() => { const real = window.fetch.bind(window); window.__answers = [
          {check_ok: true, newer: false, check_disabled: false}, {check_ok: false, newer: false, check_disabled: false},
          {check_ok: true, newer: true, latest: '9.9.9', url: 'https://example.invalid/notes', command: null, can_update: false, check_disabled: false, install: {state: 'idle'}}];
        window.fetch = async (url, options) => {
          if (/api\\/update\\/check/.test(String(url))) return new Response(JSON.stringify({current: '0.80.1', ...window.__answers.shift()}), {status: 200, headers: {'Content-Type': 'application/json'}});
          return real(url, options); }; })()"""
    )
    for expected in ("up to date", "Could not reach", "new version"):
        ui.click(".footer .check-update")
        ui.wait(f"document.querySelector('.check-update')?.textContent.includes({json.dumps(expected)})")
        ui.wait("document.querySelector('.check-update')?.textContent === 'Check for updates'", 15)
    assert "Version 9.9.9 is available" in ui.text(".update-banner")  # the found release shows its notice at once
    ui.js("window.__beforeReload = true; location.reload()")  # drop the rewriting again
    ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")


def test_the_footer_shows_the_version(ui):
    text = ui.text(".footer .version")
    assert re.fullmatch(r"v\d+\.\d+\.\d+|vdev", text.strip()), text


def test_a_tablet_gets_the_whole_table_with_even_rows_and_a_phone_two_lines(ui):
    """A portrait iPad is 744-834 px wide: it must not get the phone layout (names on a second line, no free
    count, no weather columns) and every row must be as tall as the next; a phone keeps the compact one."""
    ui.call("Emulation.setEmulatedMedia", features=[{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"}])
    try:
        for width in (744, 834, 390):
            ui.call("Emulation.setDeviceMetricsOverride", width=width, height=1100, deviceScaleFactor=2, mobile=True)
            ui.js("window.scrollTo(0, 0)")
            if not ui.count(".card.open"):
                ui.click("button.dh", index=1)
            ui.wait("document.querySelector('.card.open .slot')")
            shape = ui.js(
                """(() => { const rows = [...document.querySelectorAll('.card.open .slot')].filter((r) => !r.querySelector('.names, .note'));
                const visible = (sel) => { const e = document.querySelector('.card.open .slot ' + sel); return !!e && getComputedStyle(e).display !== 'none'; };
                return {sameHeight: new Set(rows.map((r) => Math.round(r.getBoundingClientRect().height))).size, tall: Math.min(...rows.map((r) => r.getBoundingClientRect().height)),
                        free: visible('.free'), rain: visible('.rain'), wind: visible('.wind'), head: !!document.querySelector('.slots-head') && getComputedStyle(document.querySelector('.slots-head')).display !== 'none',
                        overflow: document.documentElement.scrollWidth > innerWidth}; })()"""
            )
            assert shape["sameHeight"] == 1 and shape["tall"] >= 43, (width, shape)  # rows without names are all one height, a finger tall
            assert shape["free"] and not shape["overflow"], (width, shape)
            chip = ui.js("(() => { const c = document.querySelector('.card.open .slot .who-chip'); return !!c && getComputedStyle(c).display !== 'none'; })()")
            assert chip is True, (width, chip)  # up to 860 px (phone, narrow window, portrait tablet) the names are behind a chip
            assert shape["rain"] and shape["wind"] and shape["head"], (width, shape)  # weather columns and their headings on every screen size
    finally:
        ui.call("Emulation.setEmulatedMedia", features=[])
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        ui.js("window.scrollTo(0, 0)")


def test_a_phone_shows_players_on_demand_and_keeps_its_menus_on_screen(ui):
    """Names would wrap over two lines of every row on a phone: a chip with the count opens them as a list.
    The View menu opens across the screen (it ran off the right edge), Search scrolls as a whole, and the footer
    is one slim row with the version and the update check inside the View menu."""
    ui.call("Emulation.setEmulatedMedia", features=[{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"}])
    ui.call("Emulation.setDeviceMetricsOverride", width=390, height=800, deviceScaleFactor=2, mobile=True)
    try:
        ui.js("window.scrollTo(0, 0)")
        if not ui.count(".card.open"):
            ui.click("button.dh", index=1)
        ui.wait("document.querySelector('.card.open .slot .who-chip')")
        assert ui.js("getComputedStyle(document.querySelector('.card.open .slot .names')).display") == "none"  # no names inline
        before = ui.count(".who-list")
        ui.js("document.querySelector('.card.open .slot .who-chip').click()")
        ui.wait("document.querySelector('.card.open .who-list')")
        assert before == 0 and not ui.count(".scrim")  # the list opened, and the tap did not start a booking
        starts = ui.js("(() => { const row = document.querySelector('.card.open .who-list').closest('.slot'); return [row.querySelector('.seats').getBoundingClientRect().left, row.querySelector('.who-list').getBoundingClientRect().left]; })()")
        assert abs(starts[0] - starts[1]) < 1.5, starts  # the names start exactly where the seat squares start
        assert ui.js("document.querySelector('.card.open .who-list').innerText.length") > 3
        ui.js("document.querySelector('.card.open .slot .who-chip').click()")
        ui.wait("!document.querySelector('.card.open .who-list')")
        # the View menu stays inside the screen (the version and the update check are in Settings)
        ui.js("document.querySelector('[data-view-button]').click()")
        ui.wait("document.querySelector('.view-panel')")
        box = ui.js("(() => { const r = document.querySelector('.view-panel').getBoundingClientRect(); return [r.left, r.right, innerWidth, document.documentElement.scrollWidth, r.top]; })()")
        assert box[0] >= 0 and box[1] <= box[2] + 1 and box[3] <= box[2] + 1, box
        toolbar = ui.js("document.querySelector('.toolbar').getBoundingClientRect().bottom")
        assert box[4] >= toolbar - 1, (box, toolbar)  # all of it below the toolbar, nothing hidden under it
        ui.key("Escape")
        # the footer: one slim row, the version and the check are not in it
        assert ui.js("document.querySelector('.footer').getBoundingClientRect().height") < 60
        assert ui.js("getComputedStyle(document.querySelector('.footer .about')).display") == "none"
        # Search keeps its filters on screen and only the results scroll
        _open_sheet(ui, "s", "Search")
        ui.wait("document.querySelectorAll('.res').length > 3")
        scroll = ui.js("(() => { const r = document.querySelector('.results'); r.scrollTop = 400; return [r.scrollHeight > r.clientHeight, r.scrollTop > 0, getComputedStyle(document.querySelector('.sheet-body')).overflowY, document.documentElement.scrollWidth <= innerWidth]; })()")
        assert scroll == [True, True, "hidden", True], scroll
        _close_sheet(ui)
    finally:
        ui.call("Emulation.setEmulatedMedia", features=[])
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        ui.js("window.scrollTo(0, 0)")


def test_a_narrow_computer_window_and_a_phone_on_its_side_use_the_chip_and_scroll(ui):
    """The chip is not only for phones: any window up to 860 px wide gets it, with the weather columns kept in their
    places for slots without players. On a phone on its side (844 x 390) Search must scroll as a whole."""
    ui.call("Emulation.setDeviceMetricsOverride", width=820, height=700, deviceScaleFactor=1, mobile=False)  # a mouse, a narrow window
    try:
        ui.js("window.scrollTo(0, 0)")
        if not ui.count(".card.open"):
            ui.click("button.dh", index=1)
        ui.wait("document.querySelector('.card.open .slot .who-chip')")
        assert ui.js("getComputedStyle(document.querySelector('.card.open .slot .names')).display") == "none"
        columns = ui.js(
            """(() => { const rows = [...document.querySelectorAll('.card.open .slot')].slice(0, 14);
            const edge = (r, sel) => Math.round(r.querySelector(sel).getBoundingClientRect().right);
            return new Set(rows.map((r) => [edge(r, '.temp'), edge(r, '.rain'), edge(r, '.wind')].join())).size; })()"""
        )
        assert columns == 1, columns  # temperature, rain and wind line up in every row, with or without a chip
        ui.call("Emulation.setDeviceMetricsOverride", width=844, height=390, deviceScaleFactor=2, mobile=True)
        ui.call("Emulation.setEmulatedMedia", features=[{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"}])
        _open_sheet(ui, "s", "Search")
        ui.wait("document.querySelectorAll('.res').length > 3")
        scroll = ui.js("(() => { const b = document.querySelector('.sheet-body'); b.scrollTop = 300; return [b.scrollHeight > b.clientHeight, b.scrollTop > 0, getComputedStyle(b).overflowY]; })()")
        assert scroll == [True, True, "auto"], scroll  # short and wide: the whole of Search scrolls
        _close_sheet(ui)
        _open_sheet(ui, "p", "Player")  # the intro is dropped on a short screen, so the list gets the room
        ui.wait("document.querySelectorAll('.player-list li').length > 3")
        assert ui.js("document.querySelector('.player-list').getBoundingClientRect().height") > 150
        _close_sheet(ui)
    finally:
        ui.call("Emulation.setEmulatedMedia", features=[])
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        ui.js("window.scrollTo(0, 0)")


def test_a_day_is_only_as_tall_as_what_it_says(ui):
    """The event line used to be kept on every day once any day had one, which left an empty band on most days
    (2026-10-16: "is this screen too crowded?"). Now only a day with an event has the line; the others are one height,
    and the badge slot keeps a day with a badge as tall as one without."""
    def heights(with_note):
        return ui.js(f"[...document.querySelectorAll('.card:not(.open)')].filter((c) => !!c.querySelector('.events') === {str(with_note).lower()}).map((c) => Math.round(c.getBoundingClientRect().height))")

    ui.js("window.scrollTo(0, 0)")
    while ui.count(".card.open"):
        ui.click(".card.open button.dh")
        ui.wait("document.querySelectorAll('.card.open').length === 0 || true")
    ui.wait("document.querySelectorAll('.card').length === 5 && !document.querySelector('.card.open')")
    assert ui.js("[...document.querySelectorAll('.dh .events')].every((e) => e.textContent.trim())")  # no empty placeholder line
    assert 1 <= ui.count(".dh .events") < 5
    for width, mobile in ((1280, False), (390, True)):
        ui.call("Emulation.setDeviceMetricsOverride", width=width, height=800, deviceScaleFactor=2 if mobile else 1, mobile=mobile)
        try:
            ui.js("window.scrollTo(0, 0)")
            plain, noted = heights(False), heights(True)
            assert len(set(plain)) == 1 and len(set(noted)) == 1, (width, plain, noted)
            assert min(noted) > max(plain), (width, plain, noted)  # the note adds its line, nothing else does
        finally:
            ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)


def test_a_dropped_connection_at_page_load_is_retried_and_a_dead_server_gets_a_retry_button(ui, hurry):
    """On Wi-Fi (or while a server restarts) the first requests can fail outright: the page tries again a few times
    before giving up, and when it does give up it says so and offers a button, in plain words even without its texts."""
    def blocked(count):
        return ui.call(
            "Page.addScriptToEvaluateOnNewDocument",
            source="""(() => { const real = window.fetch.bind(window); let n = 0;
            window.fetch = (url, options) => (/api\\/bootstrap/.test(String(url)) && n++ < COUNT) ? Promise.reject(new TypeError('Failed to fetch')) : real(url, options); })()""".replace("COUNT", str(count)),
        )["identifier"]

    script = None
    try:
        script = blocked(2)  # the first two attempts fail ...
        ui.js("location.reload()")
        ui.wait("document.querySelectorAll('.card').length > 0", 30)  # ... the third gets through
        ui.call("Page.removeScriptToEvaluateOnNewDocument", identifier=script)
        script = blocked(1000)  # a server that is not there at all
        ui.js("location.reload()")
        ui.wait("document.querySelector('.empty .btn.pri')", 40)
        assert "Cannot reach" in ui.text(".empty h2") and "error." not in ui.text(".empty")  # words, not message keys
        ui.call("Page.removeScriptToEvaluateOnNewDocument", identifier=script)
        script = None
        ui.click(".empty .btn.pri")  # the button reloads, and now it works
        ui.wait("document.querySelectorAll('.card').length > 0", 30)
    finally:
        if script:
            ui.call("Page.removeScriptToEvaluateOnNewDocument", identifier=script)
        ui.js("location.reload()")
        ui.wait("document.querySelectorAll('.card').length > 0", 30)


def test_the_app_name_shows_where_there_is_room_and_a_phone_gives_its_row_to_the_days(ui):
    assert "Teetime Monitor" in ui.text(".brand.in-bar") and ui.js("getComputedStyle(document.querySelector('.brand.top')).display") == "none"
    ui.call("Emulation.setDeviceMetricsOverride", width=760, height=900, deviceScaleFactor=1, mobile=False)
    try:
        assert "Teetime Monitor" in ui.text(".brand.top") and ui.js("getComputedStyle(document.querySelector('.brand.in-bar')).display") == "none"  # a narrow window: its own row
        ui.call("Emulation.setDeviceMetricsOverride", width=393, height=800, deviceScaleFactor=2, mobile=True)
        hidden = ui.js("[...document.querySelectorAll('.brand')].every((b) => getComputedStyle(b).display === 'none')")
        assert hidden  # a phone: the home-screen icon and the tab say it (2026-10-16)
    finally:
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)


def test_the_weather_headings_stay_pinned_under_the_day_header(ui):
    """The °C / rain / wind headings sit in the pinned header block, so they stay in view while the slots scroll,
    on a computer and on a phone."""
    def pinned():
        return ui.js(
            """(() => { const head = document.querySelector('.card.open .slots-head').getBoundingClientRect(); const wrap = document.querySelector('.card.open .dh-wrap').getBoundingClientRect();
            const bar = document.querySelector('.toolbar').getBoundingClientRect(); return [head.top >= bar.bottom - 1, Math.abs(head.bottom - wrap.bottom) < 2, head.height > 10, head.bottom < innerHeight]; })()"""
        )

    ui.js("window.scrollTo(0, 0)")
    if not ui.count(".card.open"):
        ui.click("button.dh", index=1)
    ui.wait("document.querySelector('.card.open .slots-head')")
    ui.js("window.scrollBy(0, 500)")
    assert pinned() == [True, True, True, True], pinned()
    ui.call("Emulation.setDeviceMetricsOverride", width=393, height=800, deviceScaleFactor=2, mobile=True)
    try:
        assert ui.js("getComputedStyle(document.querySelector('.card.open .slots-head')).display") != "none"  # phones have them too
        ui.js("window.scrollTo(0, 0); window.scrollBy(0, 500)")
        assert pinned() == [True, True, True, True], pinned()
    finally:
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        ui.js("window.scrollTo(0, 0)")


def test_touch_and_hold_shows_a_tooltip_and_does_not_tap_what_is_held(ui):
    """A touch screen has no hover: holding anything with a title shows it as a bubble, and the release does not
    count as a tap (a slot row would open the booking dialog)."""
    ui.call("Emulation.setDeviceMetricsOverride", width=393, height=800, deviceScaleFactor=2, mobile=True)
    ui.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
    try:
        ui.js("window.scrollTo(0, 0)")
        if not ui.count(".card.open"):
            ui.click("button.dh", index=1)
        ui.wait("document.querySelector('.card.open .slot.clickable .temp')")
        ui.js("document.querySelector('.card.open .slot.clickable .temp').scrollIntoView({block: 'center'})")
        point = ui.js("(() => { const r = document.querySelector('.card.open .slot.clickable .temp').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        expected = ui.js("document.querySelector('.card.open .slot.clickable .temp').title")
        ui.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": point[0], "y": point[1]}])
        time.sleep(0.9)
        assert ui.text(".touch-tip") == expected and expected, (ui.text(".touch-tip"), expected)
        ui.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        time.sleep(0.4)
        assert ui.count(".scrim") == 0  # the held slot was not tapped
        ui.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": point[0], "y": point[1]}])  # a short tap still works
        time.sleep(0.1)
        ui.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        ui.wait("document.querySelector('.scrim')")
        ui.click(".sheet.small .btn", "Not now")
        ui.wait("!document.querySelector('.scrim')")
    finally:
        ui.call("Emulation.setTouchEmulationEnabled", enabled=False)
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        ui.js("window.scrollTo(0, 0)")


def test_what_a_badge_means_is_written_out_and_the_legend_explains_the_toolbar(ui):
    ui.js("window.scrollTo(0, 0)")
    while ui.count(".card.open"):
        ui.click(".card.open button.dh")
        ui.wait("document.querySelectorAll('.card.open').length === 0")
    ui.js("document.querySelector('.card:has(.pill.pick) button.dh').click()")  # a day that has a recommended pick
    ui.wait("document.querySelector('.card.open .slots')")
    assert ui.js("(document.querySelector('.card.open .day-why')?.textContent || '').trim().length") > 5  # the pick, in words
    ui.key("?")
    ui.wait("document.querySelector('.sheet h2')?.textContent.includes('Legend')")
    assert ui.count(".legend .tool-ico") == 9  # every tool is named, View and Heatmap included
    assert ui.count(".legend-group") == 5 and ui.count(".legend-group[open]") == 1  # accordion: the tee times first, the rest folded
    assert "Tee times" in ui.js("document.querySelector('.legend-group[open] summary').textContent")
    assert ui.js("document.querySelector('.legend-group:not([open]) .tool-ico').checkVisibility({contentVisibilityAuto: true})") is False  # folded away
    ui.click(".legend-group summary", text="Toolbar")  # opening one closes the other: only one group is open at a time
    ui.wait("document.querySelector('.legend-group[open] summary')?.textContent.includes('Toolbar')")
    assert ui.count(".legend-group[open]") == 1
    ui.click(".legend-group summary", text="Weather")
    ui.wait("document.querySelector('.legend-group[open] summary')?.textContent.includes('Weather')")
    assert ui.count(".legend-group[open]") == 1
    ui.click(".legend-group summary", text="Toolbar")
    ui.wait("document.querySelector('.legend-group[open] summary')?.textContent.includes('Toolbar')")
    ui.wait("document.querySelector('.legend-group .tool-ico').checkVisibility({contentVisibilityAuto: true})")  # unfolded
    assert "touch and hold" in ui.text(".sheet").lower()
    _close_sheet(ui)
    _open_sheet(ui, "h", "heatmap")  # a tapped square shows its numbers (no hover on a touch screen)
    ui.wait("document.querySelectorAll('.hm-cell:not(.none)').length > 3")
    ui.js("document.querySelector('.hm-cell:not(.none)').click()")
    ui.wait("/%/.test(document.querySelector('.hm-picked')?.textContent || '')")
    _close_sheet(ui)


def test_a_blocked_slot_says_why_on_every_screen_size(ui):
    """A tournament or frost block used to be a blank spot in the phone layout (its note was hidden along with the names)."""
    ui.js("window.scrollTo(0, 0)")
    if not ui.count(".card.open"):
        ui.click("button.dh", index=1)
    ui.wait("document.querySelector('.card.open .slot.blocked')")
    def shown():
        return ui.js("""(() => { const row = document.querySelector('.card.open .slot.blocked'); const note = row.querySelector('.blocked-note'); const r = note.getBoundingClientRect();
                         const free = [...document.querySelectorAll('.card.open .slot:not(.blocked) .seats')][0].getBoundingClientRect().left;  // where the seat squares start
                         return [getComputedStyle(note).display !== 'none', r.width > 40, note.textContent.trim().length > 3, r.right <= innerWidth + 1, Math.abs(r.left - free) < 2]; })()""")
    assert shown() == [True, True, True, True, True], shown()  # and the text starts where the squares would, using their room
    for width in (744, 393):
        ui.call("Emulation.setDeviceMetricsOverride", width=width, height=900, deviceScaleFactor=2, mobile=True)
        try:
            assert shown() == [True, True, True, True, True], (width, shown())
        finally:
            ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)


def test_the_page_can_be_added_to_a_home_screen_with_the_app_icon(ui):
    head = ui.js("""(() => ({ touch: document.querySelector('link[rel=apple-touch-icon]')?.getAttribute('href'), manifest: document.querySelector('link[rel=manifest]')?.getAttribute('href'),
                              standalone: document.querySelector('meta[name=apple-mobile-web-app-capable]')?.content }))()""")
    assert head == {"touch": "/icons/apple-touch-icon.png", "manifest": "/manifest.webmanifest", "standalone": "yes"}, head
    sizes = ui.js("""(async () => { const out = {}; for (const path of ['/icons/apple-touch-icon.png', '/icons/icon-192.png', '/icons/icon-512.png']) {
        const image = new Image(); image.src = path; await image.decode(); out[path] = [image.naturalWidth, image.naturalHeight]; } return out; })()""")
    assert sizes == {"/icons/apple-touch-icon.png": [180, 180], "/icons/icon-192.png": [192, 192], "/icons/icon-512.png": [512, 512]}, sizes
    manifest = ui.js("fetch('/manifest.webmanifest', {credentials: 'same-origin'}).then((r) => r.json())")
    assert manifest["name"] == "Teetime Monitor" and manifest["display"] == "standalone" and len(manifest["icons"]) == 2
    assert ui.js("document.querySelector('.brand.in-bar img').naturalWidth") > 0  # the name in the toolbar carries the same icon


def test_the_history_switch_shows_the_past_days_and_goes_back(ui):
    ui.key("v")
    ui.wait("document.querySelector('.view-panel')")
    ui.click("#v-history")
    ui.wait("document.querySelector('.preview-bar') && document.querySelectorAll('.card').length > 10")
    assert "Past days" in ui.text(".preview-bar")
    first, second = ui.js("[...document.querySelectorAll('.card .day')].slice(0, 2).map(e => e.textContent)")
    assert first != second
    assert ui.js("document.querySelector('.card .day').textContent") != ui.js("document.querySelector('.card:last-of-type .day').textContent")
    ui.js("document.querySelector('.card button.dh').click()")  # a past day opens like any other
    ui.wait("document.querySelector('.card.open .slot .names, .card.open .slot')")
    assert ui.count(".card.open .slot.clickable") == 0 and ui.count(".card.open .slot.past") == 0  # nothing to book, nothing dimmed as passed
    ui.js("document.querySelector('.card button.dh').click()")
    ui.click(".preview-bar .btn")  # back to the coming days
    ui.wait("!document.querySelector('.preview-bar') && document.querySelectorAll('.card').length > 0 && document.querySelectorAll('.card').length < 10")
    ui.key("Escape")


def test_search_puts_the_filters_beside_the_results_on_a_large_landscape_screen_and_above_them_otherwise(ui):
    try:
        for width, height, beside in ((1400, 800, True), (820, 1100, False)):
            ui.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
            _open_sheet(ui, "s", "")
            ui.wait("document.querySelectorAll('.results .res:not(.res-head)').length > 3")
            geometry = ui.js("(() => { const f = document.querySelector('.sf').getBoundingClientRect(), r = document.querySelector('.results').getBoundingClientRect(); return [f.right <= r.left + 1, f.bottom <= r.top + 1, Math.round(r.height), Math.round(r.width)]; })()")
            if beside:
                assert geometry[0] is True and geometry[2] > 450 and geometry[3] > 700, geometry  # filters left, results right, both with room
            else:
                assert geometry[1] is True and geometry[2] > 300, geometry  # one column: filters, then results
            _close_sheet(ui)
    finally:
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)


def test_on_a_phone_search_hides_most_filters_behind_one_button_and_the_results_get_the_room(ui):
    try:
        ui.call("Emulation.setDeviceMetricsOverride", width=390, height=800, deviceScaleFactor=1, mobile=True)
        _open_sheet(ui, "s", "Search")
        ui.wait("document.querySelectorAll('.results .res:not(.res-head)').length > 3")
        assert ui.js("getComputedStyle(document.querySelector('.sf-panel')).display") == "none"  # closed to begin with
        assert ui.js("document.querySelector('.results').getBoundingClientRect().height") > 350
        ui.click(".sf-more")
        ui.wait("getComputedStyle(document.querySelector('.sf-panel')).display !== 'none'")
        assert ui.js("document.querySelector('.sf-foot .btn.pri').textContent").startswith("Show ")  # and a button to close it again
        ui.click(".sf-foot .btn.pri")
        ui.wait("getComputedStyle(document.querySelector('.sf-panel')).display === 'none'")
        assert ui.js("document.documentElement.scrollWidth <= innerWidth")  # nothing pushes the page wider
        _close_sheet(ui)
    finally:
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)


def test_a_pill_in_the_day_header_fits_inside_its_card_on_a_phone(ui):
    try:
        ui.call("Emulation.setDeviceMetricsOverride", width=390, height=800, deviceScaleFactor=1, mobile=True)
        ui.js("document.querySelector('.badge-slot').innerHTML = '<span class=\"pill quiet link\"><svg width=15 height=15></svg>16:00 · 9H</span>'")
        ui.js("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
        fits = ui.js("(() => { const pill = document.querySelector('.badge-slot .pill'), card = document.querySelector('.card'); return [pill.scrollWidth <= pill.clientWidth, pill.getBoundingClientRect().right <= card.getBoundingClientRect().right]; })()")
        assert fits == [True, True]  # the text sits inside the pill and the pill inside the card
    finally:
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        ui.js("window.dispatchEvent(new Event('focus'))")


def test_the_window_hint_can_be_dismissed_and_stays_away(ui):
    ui.js("""(() => { const real = window.fetch; window.fetch = async (...args) => { const response = await real(...args);
      if (!String(args[0]).startsWith('/api/overview')) return response;
      const body = await response.json(); body.hint = { window_after: '16:00', round_minutes: 240, sunset: '18:32', latest_start: '14:02', alternative_courses: [] };
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }); }; })()""")
    for _ in range(2):  # the past days and back: the overview is read again
        ui.key("v")
        ui.wait("document.querySelector('.view-panel')")
        ui.click("#v-history")
        ui.wait("document.querySelector('#v-history')?.checked || document.querySelector('.preview-bar')")
        ui.click("#v-history")
        ui.wait("!document.querySelector('.preview-bar')")
        ui.key("Escape")
        if _ == 0:
            ui.wait("document.querySelector('.hint-bar')")
            ui.click(".hint-bar .icon-btn", index=1)  # the cross
            ui.wait("!document.querySelector('.hint-bar')")
        else:
            ui.js("new Promise((done) => setTimeout(done, 400))")
            assert ui.count(".hint-bar") == 0  # put away for good (until the window changes)
    ui.js("localStorage.removeItem('tm_hint_dismissed')")


def test_the_tip_cards_sit_at_the_bottom_swipe_on_a_phone_and_can_be_switched_off(ui):
    ui.js("window.scrollTo(0, 0)")
    ui.wait("document.querySelectorAll('.tp-card').length >= 3")
    kinds = ui.js("[...document.querySelectorAll('.tp-card .tp-label')].map((e) => e.textContent)")
    assert "Your next round" in kinds and "Best weather" in kinds
    gap = ui.js("document.querySelector('.footer').getBoundingClientRect().top - document.querySelector('.tp').getBoundingClientRect().bottom")
    assert 0 <= gap < 80  # at the bottom of the free space, just above the footer
    assert ui.count(".tp-dots") == 0  # they all fit on a wide screen: no swiping, no dots
    try:
        ui.call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=True)
        ui.wait("document.querySelectorAll('.tp-dots span').length >= 3")
        assert ui.count(".tp-dots span.on") == 1
        ui.js("(() => { const kids = document.querySelector('.tp-track').children; document.querySelector('.tp-track').scrollTo({ left: kids[1].offsetLeft - kids[0].offsetLeft }); })()")
        ui.wait("document.querySelectorAll('.tp-dots span')[1].classList.contains('on')")  # the dots follow the swipe
    finally:
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
    ui.key("v")
    ui.wait("document.querySelector('.view-panel')")
    ui.click("#v-tips")
    ui.wait("document.querySelectorAll('.tp-card').length === 0")  # the switch hides them
    ui.click("#v-tips")
    ui.wait("document.querySelectorAll('.tp-card').length >= 3")
    ui.key("Escape")


def test_the_flag_and_the_clouds_move_faster_the_harder_the_wind_blows(ui):
    ui.wait("document.querySelectorAll('.tp-scene').length >= 3")
    pairs = ui.js(
        """[...document.querySelectorAll('.tp-card')].map((card) => {
          const wind = Number((card.querySelector('.tp-wind')?.textContent || '').split(' ')[0]);
          const scene = card.querySelector('.tp-scene');
          return [wind, parseFloat(scene.style.getPropertyValue('--flag-dur')), parseFloat(scene.style.getPropertyValue('--cloud-dur'))]; })"""
    )
    pairs = [p for p in pairs if p[0] == p[0]]
    ordered = sorted(pairs)
    for (w1, f1, c1), (w2, f2, c2) in zip(ordered, ordered[1:], strict=False):
        assert w1 == w2 or (f1 >= f2 and c1 >= c2)  # more wind: a quicker flag and quicker clouds


def test_each_card_moves_its_own_way_and_out_of_step_with_the_others(ui):
    ui.wait("document.querySelectorAll('.tp-scene').length >= 3")
    ways = ui.js("[...document.querySelectorAll('.tp-card')].map((c) => [c.querySelector('[class$=\"-x\"]').getAttribute('class'), c.querySelector('.tp-scene').style.getPropertyValue('--phase')])")
    assert len({w[0] for w in ways}) >= 3  # roll, chip, wobble, (a roll per friend): not one show on every card
    assert len({w[1] for w in ways}) == len(ways)  # each starts at a different point of its loop (read from the style: a machine set to reduce motion has no animation to measure)


def test_the_scenes_follow_the_season_of_their_date_and_every_card_has_another_course(ui):
    ui.wait("document.querySelectorAll('.tp-scene').length >= 3")
    seasons = ui.js("""(async () => { const { seasonOf } = await import('/scene.js');
      return [seasonOf('2026-04-20'), seasonOf('2026-07-15'), seasonOf('2026-10-18'), seasonOf('2026-01-12'), seasonOf('2026-04-20', true), seasonOf('2026-12-01'), seasonOf('2026-03-01')]; })()""")
    assert seasons == ["spring", "summer", "autumn", "winter", "autumn", "winter", "spring"]  # the south swaps the halves of the year
    shown = ui.js("[...document.querySelectorAll('.tp-card')].map((c) => [c.querySelector('.tp-scene').getAttribute('class').split(' ').pop(), c.querySelector('.tp-scene').innerHTML.length])")
    assert all(s[0] in ("tp-spring", "tp-summer", "tp-autumn", "tp-winter") for s in shown)
    assert len({s[1] for s in shown}) >= 3  # ponds, bunkers and trees differ from card to card


def test_every_card_has_a_couple_of_guest_animals_and_not_the_same_ones(ui):
    ui.wait("document.querySelectorAll('.tp-scene').length >= 3")
    guests = ui.js("""[...document.querySelectorAll('.tp-card')].map((c) => [...c.querySelectorAll('.tp-guest')].map((g) => g.getAttribute('class') + '/' + (g.querySelector('.tp-mole,.tp-frog,.tp-squirrel,.tp-waddle,.tp-hop') || g).getAttribute('class')))""")
    assert all(1 <= len(cards) <= 2 for cards in guests), guests
    assert len({g for cards in guests for g in cards}) >= 3  # a mole here, a rabbit there: not the same visitor on every card
    for cards in guests:
        assert len(set(cards)) == len(cards)  # two different animals on one card


def test_a_cards_scene_is_drawn_without_the_icon_outline(ui):
    ui.wait("document.querySelectorAll('.tp-scene').length >= 1")
    assert ui.js("getComputedStyle(document.querySelector('.tp-scene')).stroke") == "none"
    assert ui.count(".tp-scene .tp-rays, .tp-scene .tp-cloud") >= 1


# every visible plain text against what it sits on (colours resolved through a canvas, so `color-mix()` values count)
CONTRAST_JS = r"""(() => {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d', { willReadFrequently: true });
  const parse = (c) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return { r: d[0], g: d[1], b: d[2], a: d[3] / 255 }; };
  const over = (top, bot) => ({ r: top.r * top.a + bot.r * (1 - top.a), g: top.g * top.a + bot.g * (1 - top.a), b: top.b * top.a + bot.b * (1 - top.a), a: 1 });
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const bg = (e) => { let stack = []; for (let n = e; n; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a > 0) { stack.push(c); if (c.a === 1) break; } } let base = { r: 30, g: 30, b: 46, a: 1 }; for (const c of stack.reverse()) base = over(c, base); return base; };
  const rows = new Map();
  for (const e of document.querySelectorAll('body *')) {
    const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    if (!r.width || !r.height || s.visibility === 'hidden' || e.closest('.tp-card, svg')) continue;
    if (![...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
    const fg = parse(s.color); if (!fg) continue; const back = bg(e); const text = over({ ...fg, a: fg.a * Number(s.opacity) }, back);
    const cr = ratio(text, back); const big = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && parseInt(s.fontWeight) >= 700);
    const need = big ? 3 : 4.5;
    if (cr < need) { const k = e.tagName.toLowerCase() + '.' + String(e.className).split(' ')[0] + ' ' + s.color + ' on ' + s.backgroundColor; if (!rows.has(k)) rows.set(k, [cr.toFixed(2), need, (e.textContent || '').trim().slice(0, 30)]); }
  }
  return [...rows.entries()].slice(0, 25);
})()"""


def test_text_reads_at_4_5_to_1_in_the_themes_that_were_weakest(ui):
    ui.wait("document.querySelectorAll('.card').length > 0")
    original = ui.js("document.documentElement.getAttribute('data-scheme') === 'light' ? 'catppuccin-latte' : 'catppuccin'")
    try:
        for theme in ("catppuccin-latte", "dracula", "solarized-light", "amber", "red-sands", "catppuccin"):
            _open_display(ui)
            ui.set("#v-theme", theme)
            ui.js("new Promise((done) => setTimeout(done, 300))")
            _close_display(ui)
            failing = ui.js(CONTRAST_JS)
            assert failing == [], (theme, failing[:3])
    finally:
        _open_display(ui)
        ui.set("#v-theme", original)
        _close_display(ui)


def test_the_page_has_a_heading_and_the_occupancy_bars_have_words_and_patterns_not_only_colours(ui):
    ui.wait("document.querySelectorAll('.heat').length > 0")
    assert ui.js("document.querySelector('main h1')?.textContent") == "Teetime Monitor"
    assert "Occupancy by time of day" in ui.js("document.querySelector('.heat').getAttribute('aria-label')")
    assert "08–10" in ui.js("document.querySelector('.heat span').title")
    assert ui.js("getComputedStyle(document.querySelector('.heat .o-mid')).backgroundImage") == "none"  # half booked is plain orange: no dots
    assert "repeating-linear-gradient" in ui.js("(() => { const css = [...document.styleSheets].flatMap((s) => [...s.cssRules]).find((r) => r.selectorText === '.o-full'); return css ? css.style.backgroundImage : ''; })()")  # fully booked keeps its stripes


def test_on_a_touch_screen_the_main_controls_are_at_least_44_px_tall(ui):
    try:
        ui.call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=True)
        ui.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
        ui.wait("matchMedia('(pointer: coarse)').matches")
        ui.js("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
        small = ui.js("[...document.querySelectorAll('.tool, .btn, .select select')].filter((e) => e.getBoundingClientRect().width > 0 && e.getBoundingClientRect().height < 43.5).map((e) => e.className + ' ' + Math.round(e.getBoundingClientRect().height))")
        assert small == [], small
    finally:
        ui.call("Emulation.setTouchEmulationEnabled", enabled=False)
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)


def test_the_legend_and_escape(ui):
    ui.key("?")
    ui.wait(SHEET_READY)
    ui.key("Escape")
    ui.wait("!document.querySelector('.scrim')")


def test_six_tools_fit_a_phone_at_every_text_size_view_sits_in_the_footer_and_heatmap_is_a_search_tab(ui):
    ui.call("Emulation.setEmulatedMedia", features=[{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"}])
    try:
        for scale in (90, 110, 125):
            ui.js(f"localStorage.setItem('tm_scale', '{scale}'); window.__beforeReload = true; location.reload()")
            ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")
            for width in (360, 390, 430):
                ui.call("Emulation.setDeviceMetricsOverride", width=width, height=850, deviceScaleFactor=2, mobile=True)
                ui.js("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
                shape = ui.js("""(() => { const shown = [...document.querySelectorAll('.toolbar-tools > *')].map((e) => e.getBoundingClientRect()).filter((b) => b.width > 0);
                  return {n: shown.length, right: Math.max(...shown.map((b) => b.right)), narrow: Math.min(...shown.map((b) => b.width)), page: document.documentElement.scrollWidth, w: innerWidth}; })()""")
                assert shape["n"] == 6 and shape["right"] <= shape["w"] and shape["page"] <= shape["w"] + 1, (scale, width, shape)
                assert shape["narrow"] >= 44, (scale, width, shape)  # a finger still hits every button
                one_line = ui.js("[...document.querySelectorAll('.dh .day')].every((e) => e.getBoundingClientRect().height < parseFloat(getComputedStyle(e).fontSize) * 1.8)")
                assert one_line, (scale, width)  # "Sa 17 Okt" stays on one line; the low (then the high) gives way instead
        assert ui.count(".more-wrap, .more-panel") == 0  # no More menu any more
        ui.js("document.querySelector('.footer [data-view-button]').click()")  # View sits in the footer and opens upwards
        ui.wait("document.querySelector('.view-panel #v-hcp')")
        box = ui.js("""(() => { const p = document.querySelector('.view-panel').getBoundingClientRect(), f = document.querySelector('.footer').getBoundingClientRect();
          return {bottom: p.bottom, footer: f.top, left: p.left, right: p.right, w: innerWidth, top: p.top}; })()""")
        assert box["bottom"] <= box["footer"] + 1 and box["top"] >= 0 and box["left"] >= 0 and box["right"] <= box["w"] + 1, box
        ui.key("Escape")
        ui.wait("!document.querySelector('.view-panel')")
    finally:
        ui.js("localStorage.removeItem('tm_scale'); window.__beforeReload = true; location.reload()")
        ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")
        ui.call("Emulation.setEmulatedMedia", features=[])
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
    assert ui.js("[...document.querySelectorAll('.toolbar-tools > .tool .tool-label')].map((e) => e.textContent)") == ["Search", "Players", "Reservations", "Tournaments", "Preferences", "Settings"]
    assert ui.js("[...document.querySelectorAll('.footer .tool')].map((e) => e.textContent.trim())")[-2:] == ["View", "Legend"]  # beside each other at the bottom
    _open_sheet(ui, "s", "Search")  # Search and the Heatmap: one window, two tabs
    assert ui.js("[...document.querySelectorAll('.sheet-tab')].map((e) => e.textContent.trim() + (e.getAttribute('aria-selected') === 'true' ? '*' : ''))") == ["Open times*", "Heatmap"]
    ui.click(".sheet-tab", text="Heatmap")
    ui.wait("document.querySelector('.sheet h2')?.textContent.toLowerCase().includes('heatmap') && document.querySelector('.sheet-tab[aria-selected=true]').textContent.trim() === 'Heatmap'")
    ui.wait("document.querySelector('.hm-wrap, .sheet .empty')")
    ui.click(".sheet-tab", text="Open times")
    ui.wait("document.querySelector('.sheet .sf')")
    _close_sheet(ui)


def test_every_screen_fits_the_window_at_three_widths(ui):
    """The layout review as a test: nothing sticks out sideways, and the toolbar keeps every button on screen."""
    for width in (560, 800, 1280):
        ui.call("Emulation.setDeviceMetricsOverride", width=width, height=900, deviceScaleFactor=1, mobile=False)
        ui.js("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
        problems = ui.js(
            """(() => { const out = []; const w = window.innerWidth;
            if (document.documentElement.scrollWidth > w + 1) out.push('page scrolls sideways');
            for (const el of document.querySelectorAll('.toolbar-tools > *')) { const b = el.getBoundingClientRect(); if (b.right > w + 1 || b.left < -1) out.push('toolbar button off screen: ' + el.textContent.trim()); }
            return out; })()"""
        )
        assert problems == [], (width, "overview", problems)
        for key, ready in (("s", ".sf"), ("h", ".hm-wrap, .empty"), ("p", ".player-list"), ("e", "#f-field-availability-min_open_spots"), (",", "#login-user"), ("a", ".search-box input"), ("?", ".legend")):
            _open_sheet(ui, key, "")
            ui.wait(f"document.querySelector({json.dumps(ready)})")
            problems = ui.js(
                """(() => { const out = []; const w = window.innerWidth; const sheet = document.querySelector('.sheet'); const body = sheet.querySelector('.sheet-body');
                const s = sheet.getBoundingClientRect(); if (s.left < -1 || s.right > w + 1) out.push('sheet wider than the window');
                if (body.scrollWidth > body.clientWidth + 1) out.push('content wider than its sheet (' + body.scrollWidth + ' > ' + body.clientWidth + ')');
                return out; })()"""
            )
            assert problems == [], (width, key, problems)
            ui.shot(f"layout-{width}-{ready[:6].strip('#.').replace(' ', '')}") if width == 560 else None
            _close_sheet(ui)
    ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)


def test_a_narrow_window_still_works(ui):
    ui.call("Emulation.setDeviceMetricsOverride", width=520, height=900, deviceScaleFactor=1, mobile=False)
    time.sleep(0.5)
    assert ui.js("document.documentElement.scrollWidth <= window.innerWidth + 1")
    ui.shot("narrow")
    ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)


def test_nothing_went_wrong_in_the_page(ui):
    assert ui.problems == []


# ---- the server mode (--serve): a password instead of the link --------------------------------------------


@pytest.fixture(scope="module")
def served_ui(tmp_path_factory):
    executable = _chrome()
    if executable is None:
        pytest.skip("no Chrome, Chromium or Edge found (set CHROME)")
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "webui_demo.py"), str(tmp_path_factory.mktemp("demo-served")), "--serve", "--offline", "--at", "09:30", "--password", "swing and a miss"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ, "PYTHONUNBUFFERED": "1", "TEETIME_MONITOR_LANG": "en"},
    )  # fmt: skip
    port = None
    for line in server.stdout:
        match = re.search(r"serving on port (\d+)", line)
        if match:
            port = int(match.group(1))
            break
    assert port, "the served demo did not start"
    page = Page(executable)
    page.go(f"http://127.0.0.1:{port}/")
    page.wait("document.documentElement.dataset.ready")  # the first thing anyone gets is the login page, wired up
    yield page, port
    page.close()
    server.kill()


def test_the_server_asks_for_its_password_and_remembers_you(served_ui):
    page, port = served_ui
    assert page.js("location.pathname") == "/login"
    page.shot("login")
    page.set("#password", "not the password")
    page.click("#submit")
    page.wait("!document.querySelector('#error').hidden")  # a wrong password says so, and stays on the login page
    assert page.js("location.pathname") == "/login"
    page.set("#password", "swing and a miss")
    page.click("#submit")
    page.wait("document.querySelectorAll('.card').length > 0")  # the Overview, with its data
    page.js("window.__beforeReload = true; location.reload()")
    page.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")  # still logged in
    page.key(",")  # Log out sits in Settings, under About
    page.wait("document.querySelector('.about-group .btn')")
    page.click(".about-group .btn", "Log out")
    page.wait("document.documentElement.dataset.ready")  # back at the login page
    page.go(f"http://127.0.0.1:{port}/api/bootstrap")
    page.wait("document.body.innerText.includes('auth')")  # and nothing is open without it: the data answers 401


def test_the_server_password_is_changed_in_settings(served_ui):
    page, port = served_ui
    page.go(f"http://127.0.0.1:{port}/")
    page.wait("document.documentElement.dataset.ready")
    page.set("#password", "swing and a miss")
    page.click("#submit")
    page.wait("document.querySelectorAll('.card').length > 0")
    _open_sheet(page, ",", "Settings")
    page.wait("document.querySelector('#pw-current')")
    page.shot("settings-served")

    def change(current, new, again):
        page.set("#pw-current", current)
        page.set("#pw-new", new)
        page.set("#pw-again", again)
        page.click(".sheet button[type=submit]", "Change password")

    change("swing and a miss", "short", "short")
    page.wait("document.querySelector('.sheet .status-line.error')?.textContent.includes('at least 8')")
    change("swing and a miss", "a brand new secret", "something else entirely")
    page.wait("document.querySelector('.sheet .status-line.error')?.textContent.includes('differ')")
    change("not the password", "a brand new secret", "a brand new secret")
    page.wait("document.querySelector('.sheet .status-line.error')?.textContent.includes('not right')")
    change("swing and a miss", "a brand new secret", "a brand new secret")
    page.wait("document.querySelector('.sheet .status-line.ok')?.textContent.includes('Password changed')")
    _close_sheet(page)
    page.js("window.__beforeReload = true; location.reload()")
    page.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")  # this browser stays logged in
    page.key(",")  # Log out sits in Settings, under About
    page.wait("document.querySelector('.about-group .btn')")
    page.click(".about-group .btn", "Log out")
    page.wait("document.documentElement.dataset.ready")
    page.set("#password", "swing and a miss")  # the old password is refused ...
    page.click("#submit")
    page.wait("!document.querySelector('#error').hidden")
    page.set("#password", "a brand new secret")  # ... the new one works
    page.click("#submit")
    page.wait("document.querySelectorAll('.card').length > 0")


@pytest.fixture(scope="module")
def two_clubs_ui(tmp_path_factory):
    """The demo with a second saved club, where a member of that club is booked tomorrow."""
    executable = _chrome()
    if executable is None:
        pytest.skip("no Chrome, Chromium or Edge found (set CHROME)")
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "webui_demo.py"), str(tmp_path_factory.mktemp("demo-two")), "--serve", "--offline", "--at", "09:30", "--second-club"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ, "PYTHONUNBUFFERED": "1", "TEETIME_MONITOR_LANG": "en"},
    )  # fmt: skip
    url = None
    for line in server.stdout:
        match = re.search(r"http://127\.0\.0\.1:\d+/\?t=[\w-]+", line)
        if match:
            url = match.group(0)
            break
    assert url, "the demo server did not start"
    page = Page(executable)
    page.go(url)
    page.wait("document.querySelectorAll('.card').length > 0")
    yield page
    page.close()
    server.kill()


def test_a_players_tee_time_at_another_club_shows_that_club_and_jumps_there(two_clubs_ui):
    ui = two_clubs_ui
    assert ui.js("document.querySelector('#club').value") == "golfclub-beispiel"
    _open_sheet(ui, "p", "Player")
    ui.wait("[...document.querySelectorAll('.player-list li')].some((li) => li.textContent.includes('Nina Nachbar'))")
    row = "[...document.querySelectorAll('.player-list li')].find((li) => li.textContent.includes('Nina Nachbar'))"
    assert ui.js(f"{row}.querySelector('.tee-btn .tee-club').textContent.trim()") == "Nachbar"  # the club, without "Golfclub … e.V."
    assert "Golfclub Nachbar e.V." in ui.js(f"{row}.textContent")  # her home club in the Club column
    ui.js(f"{row}.querySelector('.tee-btn').click()")
    ui.wait("!document.querySelector('.scrim') && document.querySelector('#club').value === 'golfclub-nachbar'")  # switched club
    ui.wait("document.querySelector('.card.open [data-slot$=\" 10:00\"]')")  # and opened her day at her time
    ui.wait("document.querySelector('.card.open')?.innerText.includes('Nina Nachbar')")  # (the other club's day loads a moment after the switch)
    assert "Nina Nachbar" in ui.text(".card.open")


def test_the_player_directory_filters_by_tee_time(two_clubs_ui):
    ui = two_clubs_ui
    _open_sheet(ui, "p", "Player")
    nina = "[...document.querySelectorAll('.player-list li .player-name')].some((e) => e.textContent === 'Nina Nachbar')"
    ui.wait(nina)
    every = ui.count(".player-list li .player-name")
    ui.set("#p-tee", "any")  # a tee time from now on, at any saved club: each row keeps its tee time button
    ui.wait("document.querySelectorAll('.player-list li .player-name').length === document.querySelectorAll('.player-list li .tee-btn').length")
    assert ui.js(nina)
    ui.set("#p-tee", "today")  # Nina plays tomorrow only
    ui.wait(f"!({nina})")
    assert 0 < ui.count(".player-list li .player-name") < every
    ui.set("#p-tee", "all")
    ui.wait(f"document.querySelectorAll('.player-list li .player-name').length === {every}")
    _close_sheet(ui)


def test_a_sheet_keeps_its_size_between_tabs_and_months(ui):
    box = "(() => { const r = document.querySelector('.sheet').getBoundingClientRect(); return [r.top, r.width, r.height].map(Math.round).join(); })()"
    _open_sheet(ui, "s", "Search")
    search = ui.js(box)
    ui.click(".sheet-tab", "Heatmap")
    ui.wait("document.querySelector('.sheet h2').textContent.includes('heatmap')")
    assert ui.js(box) == search  # Search and Heatmap are tabs of one sheet: no jump when switching
    _close_sheet(ui)
    _open_sheet(ui, "t", "Tournaments")
    ui.wait("document.querySelectorAll('.tn-cell').length > 0")
    first = ui.js(box)
    for _ in range(5):  # months of four, five and six weeks
        ui.click(".tn-step", index=1)
        ui.wait("document.querySelectorAll('.tn-cell').length > 0")
        assert ui.js(box) == first
    _close_sheet(ui)


def test_the_week_starts_on_sunday_with_imperial_units_else_on_monday(ui):
    first_days = "[...document.querySelectorAll('.tn-wd')].map((e) => e.textContent).slice(0, 2).join()"
    heat_days = "[...document.querySelectorAll('.hm-head .hd')].map((e) => e.textContent).slice(0, 2).join()"
    for units, tournament_days, heatmap_days in (("metric", "Mon,Tue", "Mon,Tue"), ("imperial", "Sun,Mon", "Sun,Mon")):
        _open_display(ui)
        ui.set("#v-units", units)
        _close_display(ui)
        _open_sheet(ui, "t", "Tournaments")
        ui.wait("document.querySelectorAll('.tn-cell').length > 0")
        assert ui.js(first_days) == tournament_days
        _close_sheet(ui)
        _open_sheet(ui, "s", "Search")
        ui.click(".sheet-tab", "Heatmap")
        ui.wait("document.querySelectorAll('.hm-cell').length > 20")
        assert ui.js(heat_days) == heatmap_days
        _close_sheet(ui)
    _open_display(ui)
    ui.set("#v-units", "metric")
    _close_display(ui)


def test_search_and_tournaments_have_no_club_choice_of_their_own(two_clubs_ui):
    ui = two_clubs_ui
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.strip .sday').length === 14")
    assert ui.count("#tool-club") == 0 and ui.count(".sheet select#club") == 0  # Search looks at the club of the page
    _close_sheet(ui)
    _open_sheet(ui, "t", "Tournaments")
    ui.wait("document.querySelectorAll('.tn-item').length > 0")
    assert ui.count("#tn-club") == 0 and ui.count(".tn-filters select") == 0
    _close_sheet(ui)


def test_a_page_reloads_by_itself_when_the_server_was_restarted(ui):
    """After an update the server is a new process: the open page (whose scripts are the old ones) loads again at once."""
    ui.js("window.__oldPage = true")
    ui.js(
        """(() => { const real = window.fetch.bind(window);
        window.fetch = (url, options) => String(url).includes('/api/ping')
          ? real(url, options).then((r) => r.json()).then((body) => new Response(JSON.stringify({ ...body, boot: 'another-process' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
          : real(url, options); })()"""
    )  # (the next ping names a process the page was not loaded from)
    ui.wait("window.__oldPage === undefined && document.querySelectorAll('.card').length > 0", timeout=30)


def test_the_cannot_reach_screen_goes_away_by_itself_when_the_server_answers_again(ui):
    ui.js("window.__oldPage = true; window.__realFetch = window.fetch")
    ui.js("window.fetch = (url, options) => String(url).includes('/api/ping') ? Promise.reject(new TypeError('Failed to fetch')) : window.__realFetch(url, options)")
    ui.wait("document.body.innerText.includes('Cannot reach')", timeout=20)  # the server restarting: the page says so
    ui.js("window.fetch = window.__realFetch")  # ... and it is back
    ui.wait("window.__oldPage === undefined && document.querySelectorAll('.card').length > 0", timeout=30)


def test_a_tournament_in_the_loaded_days_shows_its_forecast(ui):
    _open_sheet(ui, "t", "Tournaments")
    ui.wait("document.querySelectorAll('.tn-item').length > 0")
    ui.wait("document.querySelector('.tn-item .chip.wx')")
    assert "°" in ui.text(".tn-item .chip.wx") and "%" in ui.text(".tn-item .chip.wx")
    assert ui.js("[...document.querySelectorAll('.tn-item')].some((li) => !li.querySelector('.chip.wx'))")  # the far ones have none
    _close_sheet(ui)


def test_the_gear_in_search_opens_preferences_and_brings_you_back(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelector('.sf-gear')")
    ui.click(".sf-gear")
    ui.wait("document.querySelector('.sheet h2')?.textContent.toLowerCase().includes('preferences')")
    ui.click(".sheet-head .icon-btn")  # (closing it brings Search back, so the scrim stays)
    ui.wait("document.querySelector('.sheet h2')?.textContent.includes('Search') && document.querySelectorAll('.strip .sday').length === 14")  # and Search is open again
    _close_sheet(ui)


def test_search_draws_for_a_club_with_several_courses_with_a_chip_for_each(ui):
    """A club with more than one course once crashed Search on its first draw (it read the filters before they existed):
    the page sat on "Loading" for ever. The demo club has one course, so the answer is given a second one here."""
    ui.js(
        """(() => { const real = window.fetch.bind(window);
        window.fetch = async (url, options) => { const response = await real(url, options);
          if (!String(url).includes('/api/search/slots')) return response;
          const data = await response.json();
          data.courses = [...data.courses, '9 Loch Platz'];
          data.slots = data.slots.map((slot, i) => (i % 2 ? { ...slot, course: '9 Loch Platz' } : slot));
          return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } }); }; })()"""
    )
    try:
        _open_sheet(ui, "s", "Search")
        ui.wait("document.querySelectorAll('.strip .sday').length === 14 && document.querySelectorAll('.results .res:not(.res-head)').length > 3")
        assert ui.count(".sf .chip") > 0 and "9 Loch Platz" in ui.text(".sf")  # a chip for each course
        assert ui.js("document.querySelectorAll('.results .res-course').length") > 0 and "9 Loch Platz" in ui.text(".results")  # and the course named on each row
        _chip(ui, "9 Loch Platz")
        ui.wait("[...document.querySelectorAll('.results .res-course')].every((e) => !e.textContent.trim())")  # one course chosen: no need to name it
        _close_sheet(ui)
    finally:
        ui.js("window.__beforeReload = true; location.reload()")  # drop the override
        ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")


def test_search_keeps_its_filters_while_you_look_at_the_heatmap_and_forgets_them_when_closed(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.strip .sday').length === 14 && document.querySelectorAll('.results .res:not(.res-head)').length > 3")
    _chip(ui, "Weekend")
    _chip(ui, "3+")
    ui.js("document.querySelector('.sf-more')?.getAttribute('aria-expanded')")  # (a phone's panel is not under test here)
    ui.click(".sheet-tab", text="Heatmap")
    ui.wait("document.querySelector('.hm-wrap, .sheet .empty')")
    ui.click(".sheet-tab", text="Open times")
    ui.wait("document.querySelectorAll('.strip .sday').length === 14")
    assert _chip_on(ui, "Weekend") == "true" and _chip_on(ui, "3+") == "true"  # as you left them
    _close_sheet(ui)
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.strip .sday').length === 14")
    assert _chip_on(ui, "Weekend") == "false" and _chip_on(ui, "3+") == "false"  # a new visit starts from your Preferences again
    _close_sheet(ui)


def test_search_keeps_the_units_in_a_row_pinned_above_the_scrolling_results_and_the_clear_button_beside_the_filters(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.results .res:not(.res-head)').length > 8")
    shape = ui.js(
        """(() => { const r = document.querySelector('.results'); r.scrollTop = 300;
        const head = document.querySelector('.res-head').getBoundingClientRect(), box = r.getBoundingClientRect();
        const clear = document.querySelector('.sf-actions .sf-clear').getBoundingClientRect(), filters = document.querySelector('.sf').getBoundingClientRect();
        return {pinned: Math.abs(head.top - box.top) < 2, scrolled: r.scrollTop > 0, units: document.querySelectorAll('.res-head .cell').length,
                clearInHeader: !!document.querySelector('.res-head .btn'), clearWithFilters: clear.top >= filters.top - 1 && clear.bottom <= filters.bottom + 1}; })()"""
    )
    assert shape == {"pinned": True, "scrolled": True, "units": 3, "clearInHeader": False, "clearWithFilters": True}, shape
    _close_sheet(ui)


def test_the_courses_you_can_play_are_a_card_in_preferences_that_saves_at_once(ui):
    """A 9 hole membership: the 18 hole course is switched off and Search never shows it. The demo club has one course,
    so the list of courses is given a second one here."""
    ui.js(
        """(() => { const real = window.fetch.bind(window);
        window.fetch = async (url, options) => { const response = await real(url, options);
          if (!String(url).includes('/api/club/courses')) return response;
          const data = await response.json();
          return new Response(JSON.stringify({ ...data, courses: [...data.courses.filter((c) => c.name !== '9 Loch Platz'), { name: '9 Loch Platz', play: true }] }), { status: 200, headers: { 'Content-Type': 'application/json' } }); }; })()"""
    )
    try:
        _open_sheet(ui, "e", "")
        ui.wait("document.querySelector('#c-play-1')")
        ui.js("document.querySelector('#c-play-1').click()")  # switch the second course off
        ui.wait("document.querySelector('#c-play-1').checked === false")
        ui.js("document.querySelector('#c-play-1').click()")  # and back on: leave the demo as it was
        ui.wait("document.querySelector('#c-play-1').checked === true")
        _close_sheet(ui)
    finally:
        ui.js("window.__beforeReload = true; location.reload()")  # drop the override
        ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")


def test_where_the_names_do_not_fit_a_row_shows_the_same_chip_as_the_days_and_a_tap_lists_them(ui):
    try:
        ui.call("Emulation.setDeviceMetricsOverride", width=390, height=800, deviceScaleFactor=1, mobile=True)
        _open_sheet(ui, "s", "Search")
        ui.wait("document.querySelectorAll('.results .res .who-chip').length > 0")
        assert ui.js("getComputedStyle(document.querySelector('.results .res .res-people')).display") == "none"  # no names inline
        assert ui.count(".results .who-list") == 0
        ui.js("document.querySelector('.results .res .who-chip').click()")
        ui.wait("document.querySelector('.results .who-list')")
        assert ui.js("document.querySelector('.results .who-list').innerText.length") > 3
        assert not ui.count(".scrim + .scrim")  # and the tap did not start a booking
        _close_sheet(ui)
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        _open_sheet(ui, "s", "Search")  # room enough: the names are inline and there is no chip
        ui.wait("document.querySelectorAll('.results .res').length > 3")
        assert ui.js("getComputedStyle(document.querySelector('.results .res .who-chip')).display") == "none"
        _close_sheet(ui)
    finally:
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)


def test_each_days_heading_gives_way_to_the_next_instead_of_stacking(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.dayhead').length >= 2")
    ui.js("(() => { const r = document.querySelector('.results'); const second = document.querySelectorAll('.dayhead')[1]; r.scrollTop += second.getBoundingClientRect().top - r.getBoundingClientRect().top - 20; })()")
    overlap = ui.js(
        """(() => { const heads = [...document.querySelectorAll('.dayhead')].map((e) => e.getBoundingClientRect()).filter((b) => b.height > 0);
        return heads.some((a, i) => heads.some((b, j) => i < j && b.top < a.bottom - 1 && b.bottom > a.top + 1)); })()"""
    )
    assert overlap is False  # two headings never sit on top of each other
    _close_sheet(ui)


def test_friends_and_four_free_seats_exclude_each_other_and_today_is_the_bold_day(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.strip .sday').length === 14 && document.querySelectorAll('.results .res:not(.res-head)').length > 3")
    _chip(ui, "4")  # four free seats: nobody is booked, so no friend can be there
    assert _chip_on(ui, "4") == "true"
    _chip(ui, "\u2605 Friends")
    ui.wait("[...document.querySelectorAll('.sf .chip')].find((e) => e.textContent.trim() === '1+')?.getAttribute('aria-pressed') === 'true'")  # back to 1+
    assert _chip_on(ui, "\u2605 Friends") == "true" and _chip_on(ui, "4") == "false"
    assert ui.js("[...document.querySelectorAll('.sf .chip')].find((e) => e.textContent.trim() === '4').disabled") is True  # and 4 cannot be picked while friends is on
    _chip(ui, "3+")  # three free seats and a friend still fit together
    assert _chip_on(ui, "3+") == "true"
    _chip(ui, "\u2605 Friends")
    assert ui.js("[...document.querySelectorAll('.sf .chip')].find((e) => e.textContent.trim() === '4').disabled") is False
    weight = ui.js("(() => { const today = document.querySelector('.sday.today .n'), other = document.querySelector('.sday:not(.today) .n'); return [Number(getComputedStyle(today).fontWeight), Number(getComputedStyle(other).fontWeight), getComputedStyle(today).boxShadow]; })()")
    assert weight[0] >= 700 and weight[1] < 700 and weight[2] == "none", weight  # bold, not outlined
    _close_sheet(ui)
