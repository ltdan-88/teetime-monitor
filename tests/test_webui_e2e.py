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
    ui.click(".resv-list .btn")
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


def test_the_tournament_calendar_is_a_month_grid_that_lists_the_day_you_tap(ui):
    ui.js("window.scrollTo(0, 0)")
    _open_sheet(ui, "t", "Tournaments")
    ui.wait("document.querySelectorAll('.tn-cell').length >= 28 && !document.querySelector('.sheet .status-line')")
    assert ui.count(".tn-wd") == 7 and ui.js("document.querySelectorAll('.tn-cell').length % 7") == 0  # whole weeks, seven columns
    columns = ui.js("[...new Set([...document.querySelectorAll('.tn-cell')].slice(0, 14).map((c) => Math.round(c.getBoundingClientRect().left)))].length")
    assert columns == 7  # every week lines up on the same seven columns
    ui.shot("tournaments-month")
    busy = ui.js("[...document.querySelectorAll('.tn-cell.has')].map((c) => c.getAttribute('aria-label'))")
    assert any("Autumn Trophy, Twilight Scramble" in label for label in busy), busy  # two on one day, both named
    shown = ui.text(".tn-list")
    assert "Autumn Trophy" in shown and "9 holes" in shown or "Winter Opener" in shown  # the month's list, before any day is picked
    first = ui.js("(() => { const cell = document.querySelector('.tn-cell.has'); const day = cell.getAttribute('aria-label').split(':')[0]; cell.click(); return day; })()")
    ui.wait("document.querySelector('.tn-cell.on')")
    assert ui.js("document.querySelector('.tn-head').textContent") == first
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
    ui.wait("document.querySelectorAll('.res').length > 3")
    ui.shot("search")
    # the column headings sit exactly over their values (every row shares the results' columns)
    edges = ui.js(
        """(() => { const right = (e) => Math.round(e.getBoundingClientRect().right);
        const head = [...document.querySelectorAll('.res-head .cell')].map(right);
        const row = [...document.querySelectorAll('.res:not(.res-head)')[0].querySelectorAll('.cell')].map(right);
        return [head, row]; })()"""
    )
    assert edges[0] == edges[1], edges
    ui.click(".res .btn", "Book")
    ui.wait("document.querySelectorAll('.sheet').length === 2")
    ui.click(".sheet.small .btn", "Not now")
    ui.wait("document.querySelectorAll('.sheet').length === 1")
    ui.set("#s-spots", "4")  # nothing has four open seats and a friend... a narrower search still answers
    ui.click(".criteria .actions .btn.pri")
    ui.wait("document.querySelector('.results-head')")
    _close_sheet(ui)


def test_search_weather_stays_under_its_headings_in_every_window_width(ui):
    """A hit nobody has booked yet has no players, so no chip: its temperature, rain and wind must still sit under
    their headings (they once slid one column to the left and the button landed on top of the wind)."""
    try:
        _open_sheet(ui, "s", "Search")
        ui.wait("document.querySelector('#s-spots') && document.querySelectorAll('.res').length > 3")  # the form and the first answer are in
        ui.set("#s-spots", "4")  # four open seats: only slots with nobody booked
        ui.click(".criteria .actions .btn.pri")
        ui.wait("(() => { const rows = [...document.querySelectorAll('.res:not(.res-head)')]; return rows.length > 0 && rows.every((r) => !r.querySelector('.who-chip')); })()")  # the new answer is in
        for width in (1280, 1000, 860, 744):
            ui.call("Emulation.setDeviceMetricsOverride", width=width, height=900, deviceScaleFactor=1, mobile=False)
            ui.wait(f"innerWidth === {width}")
            edges = ui.js(
                """(() => { const right = (e) => Math.round(e.getBoundingClientRect().right);
                const rows = [...document.querySelectorAll('.res:not(.res-head)')];
                const button = (r) => r.querySelector('.res-action .btn').getBoundingClientRect();
                return {head: [...document.querySelectorAll('.res-head .cell')].map(right),
                        rows: rows.map((r) => [...r.querySelectorAll('.cell')].map(right)),
                        chips: rows.filter((r) => r.querySelector('.who-chip')).length,
                        overlap: rows.some((r) => [...r.querySelectorAll('.cell')].some((c) => c.getBoundingClientRect().right > button(r).left + 1))}; })()"""
            )
            assert edges["chips"] == 0, edges  # the case under test: no players
            assert all(row == edges["head"] for row in edges["rows"]), (width, edges)
            assert not edges["overlap"], (width, edges)  # the button never sits on the weather
    finally:
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        _close_sheet(ui)


def test_search_rows_keep_their_dates_on_one_line(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.res').length > 3")
    shape = ui.js(
        """(() => { const rows = [...document.querySelectorAll('.res:not(.res-head)')];
        return [new Set(rows.map((r) => Math.round(r.getBoundingClientRect().height))).size,
                rows.every((r) => getComputedStyle(r.querySelector('.res-date')).whiteSpace === 'nowrap')]; })()"""
    )
    assert shape == [1, True], shape  # every row is as tall as the others: no date wraps onto a second line
    _close_sheet(ui)


def test_search_shows_its_matches_before_the_ai_has_ranked_them(ui):
    """With AI ranking on, the AI's answer takes seconds: the plain matches must be on screen at once, with a
    note that the AI is still ranking. Here the quick answer claims the AI is pending and the second request
    is held back to see the in-between state."""
    ui.js(
        """(() => { const real = window.fetch.bind(window);
        window.fetch = async (url, options) => {
          if (!/api\\/search$/.test(String(url)) || !options || !options.body) return real(url, options);
          const quick = JSON.parse(options.body).ai === false;
          if (!quick) await new Promise((done) => setTimeout(done, 2500));
          const data = await (await real(url, options)).json();
          if (quick) data.ai_pending = true;
          return new Response(JSON.stringify(data), {status: 200, headers: {'Content-Type': 'application/json'}}); }; })()"""
    )
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.res').length > 3")  # the matches are there ...
    ui.wait("document.querySelector('.results-head .ranking')")  # ... while the AI is still ranking
    assert not ui.js("document.querySelector('.criteria .btn.pri').disabled")  # and you can search again
    ui.wait("!document.querySelector('.results-head .ranking')", 30)
    _close_sheet(ui)
    ui.js("window.__beforeReload = true; location.reload()")  # drop the delay again
    ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")


def test_heatmap_shows_the_history(ui):
    _open_sheet(ui, "h", "heatmap")
    ui.wait("document.querySelectorAll('.hm-cell').length > 20")
    ui.shot("heatmap")
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
    ui.wait("document.querySelector('.view-panel')")
    ui.wait("document.querySelector('.view-panel #v-theme')")
    ui.js("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")  # let the page finish drawing


def test_the_view_menu_holds_what_changes_how_the_page_looks_and_reads(ui):
    _open_view(ui)
    ui.shot("view-menu")
    for control in ("#v-language", "#v-theme", "#v-units", "#v-hcp"):
        assert ui.count(control) == 1, control
    assert ui.count(".view-panel .stepper button") == 2
    ui.key("Escape")
    ui.wait("!document.querySelector('.view-panel')")
    _open_sheet(ui, ",", "Settings")  # and none of it is buried in Settings any more
    ui.wait("document.querySelector('#login-user')")
    assert ui.count("#f-theme") == 0 and ui.count("#f-scale") == 0 and ui.count("#f-field-__language__") == 0
    assert ui.count("#f-field-units") == 0
    _close_sheet(ui)


def test_a_theme_is_chosen_in_the_view_menu_and_survives_a_reload(ui):
    _open_view(ui)
    ui.set("#v-theme", "solarized-light")
    ui.wait(f"{BACKGROUND} === 'rgb(253, 246, 227)'")
    ui.shot("theme-solarized-light")
    ui.js("window.__beforeReload = true; location.reload()")
    # wait for the NEW page: the old one still shows cards and the theme until the reload replaces it
    ui.wait(f"window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0 && {BACKGROUND} === 'rgb(253, 246, 227)'")
    _open_view(ui)
    ui.set("#v-theme", "catppuccin")
    ui.wait(f"{BACKGROUND} === 'rgb(30, 30, 46)'")
    ui.key("Escape")


def test_the_scale_is_stepped_in_the_view_menu_and_remembered(ui):
    assert ui.js("getComputedStyle(document.documentElement).fontSize") == "12.8px"
    _open_view(ui)
    ui.click(".view-panel .stepper button", "A+")
    ui.wait("getComputedStyle(document.documentElement).fontSize === '14.4px'")
    assert "90" in ui.text(".stepper-value")
    ui.js("localStorage.getItem('tm_scale') === '90' || (() => { throw new Error('not saved'); })()")
    ui.click(".view-panel .stepper button", "A−")
    ui.wait("getComputedStyle(document.documentElement).fontSize === '12.8px'")
    ui.key("Escape")


def test_units_and_handicaps_switch_from_the_view_menu(ui):
    if not ui.count(".card.open"):  # (closing a looked-at club leaves every day collapsed)
        ui.click("button.dh", index=0)
        ui.wait("document.querySelector('.card.open .names')")
    before = ui.js("document.querySelector('.dh .temp').textContent")
    names = "document.querySelector('.card.open .names')?.textContent || ''"
    assert "(18.4)" in ui.js(names) or "(22.1)" in ui.js(names)
    _open_view(ui)
    ui.set("#v-units", "imperial")
    ui.wait(f"document.querySelector('.dh .temp').textContent !== {json.dumps(before)}")
    ui.js("document.querySelector('#v-hcp').click()")
    ui.wait(f"!/\\(\\d+\\.\\d\\)/.test({names})")
    ui.js("document.querySelector('#v-hcp').click()")  # and back to how it was
    ui.set("#v-units", "metric")
    ui.wait(f"document.querySelector('.dh .temp').textContent === {json.dumps(before)}")
    ui.wait(f"/\\(\\d+\\.\\d\\)/.test({names})")
    ui.key("Escape")


def test_the_language_switches_to_german_in_the_view_menu_and_back(ui):
    _open_view(ui)
    ui.set("#v-language", "de")
    ui.wait("document.querySelector('.tool-label')?.textContent === 'Aktualisieren' || document.querySelector('.tool-label')?.textContent === 'Aktualisiere…'", 30)
    ui.shot("overview-de")
    assert ui.js("document.documentElement.lang") == "de"  # screen readers pronounce German as German
    _open_view(ui)
    assert ui.js("document.querySelector('.tool.on .tool-label').textContent") == "Ansicht"
    ui.set("#v-language", "en")
    ui.wait("document.querySelector('.tool-label')?.textContent === 'Refresh' || document.querySelector('.tool-label')?.textContent === 'Updating…'", 30)


def test_reset_filters_clears_everything_without_searching_again(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.res').length > 3")
    rows = ui.count(".res")
    ui.set("#s-spots", "3")
    ui.set("#s-wd-after", "10")
    ui.click(".criteria .actions .btn", "Reset")
    ui.wait("document.querySelector('#s-spots').value === '1' && document.querySelector('#s-wd-after').value === ''")
    assert ui.js("document.querySelector('#s-before').value") == "0"
    assert ui.count(".res") == rows  # the results stay until you search again
    ui.click(".criteria .actions .btn.pri")  # no window at all means any time: more matches than with your Preferences
    ui.wait(f"document.querySelectorAll('.res').length > {rows}")
    _close_sheet(ui)


def test_the_default_course_sits_on_the_club_row(ui):
    _open_sheet(ui, ",", "Settings")
    ui.wait("document.querySelector('.club-head .select select')")
    heads = ui.js(
        """(() => { const r = (e) => { const b = e.getBoundingClientRect(); return b.top + b.height / 2; };
        const head = [...document.querySelectorAll('.club-head')].find((h) => h.querySelector('.select'));
        return [r(head.querySelector('strong')), r(head.querySelector('.select')), r(head.querySelector('.btn'))]; })()"""
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
    assert heads == ["Name", "Gender", "Status", "HCP", "Next tee time"], heads  # every column of the directory is shown
    assert ui.js("document.querySelector('.player-list li:not(.letter) .player-meta').textContent.trim()") in ("Male", "Female", "Unknown")
    heads = ui.js("[...document.querySelectorAll('.player-head span')].map((e) => e.textContent.trim()).filter(Boolean)")
    assert heads == ["Name", "Gender", "Status", "HCP", "Next tee time"], heads  # every column of the directory is shown
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
            for key in (",", "e", "s"):
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
                if key != "s":  # (Search scrolls its results inside the window instead)
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
        # the View menu stays inside the screen, with the version and the update check
        ui.js("document.querySelector('[data-view-button]').click()")
        ui.wait("document.querySelector('.view-panel')")
        box = ui.js("(() => { const r = document.querySelector('.view-panel').getBoundingClientRect(); return [r.left, r.right, innerWidth, document.documentElement.scrollWidth]; })()")
        assert box[0] >= 0 and box[1] <= box[2] + 1 and box[3] <= box[2] + 1, box
        assert re.search(r"v\d", ui.text(".view-about")) and ui.js("getComputedStyle(document.querySelector('.view-about')).display") != "none"
        ui.key("Escape")
        # the footer: one slim row, the version and the check are not in it
        assert ui.js("document.querySelector('.footer').getBoundingClientRect().height") < 60
        assert ui.js("getComputedStyle(document.querySelector('.footer .about')).display") == "none"
        # Search scrolls as a whole, and its results fit the screen
        _open_sheet(ui, "s", "Search")
        ui.wait("document.querySelectorAll('.res').length > 3")
        scroll = ui.js("(() => { const b = document.querySelector('.sheet-body'); b.scrollTop = 400; return [b.scrollHeight > b.clientHeight, b.scrollTop > 0, getComputedStyle(b).overflowY, document.documentElement.scrollWidth <= innerWidth]; })()")
        assert scroll == [True, True, "auto", True], scroll
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
        assert scroll == [True, True, "auto"], scroll
        _close_sheet(ui)
        _open_sheet(ui, "p", "Player")  # the intro is dropped on a short screen, so the list gets the room
        ui.wait("document.querySelectorAll('.player-list li').length > 3")
        assert ui.js("document.querySelector('.player-list').getBoundingClientRect().height") > 150
        _close_sheet(ui)
    finally:
        ui.call("Emulation.setEmulatedMedia", features=[])
        ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        ui.js("window.scrollTo(0, 0)")


def test_collapsed_days_are_all_the_same_height(ui):
    """A day with an event note, one with a pick badge and one with neither used to differ in height: the note line
    is kept for every day once any day has a note, and the badge slot always has the badge's height."""
    def heights():
        return ui.js("(() => [...document.querySelectorAll('.card:not(.open)')].map((c) => Math.round(c.getBoundingClientRect().height)))()")

    ui.js("window.scrollTo(0, 0)")
    while ui.count(".card.open"):
        ui.click(".card.open button.dh")
        ui.wait("document.querySelectorAll('.card.open').length === 0 || true")
    ui.wait("document.querySelectorAll('.card').length === 5 && !document.querySelector('.card.open')")
    assert ui.count(".dh .events") == 5 and ui.js("[...document.querySelectorAll('.dh .events')].filter((e) => e.textContent.trim()).length") >= 1  # some days have notes, all have the line
    assert len(set(heights())) == 1, heights()
    ui.call("Emulation.setDeviceMetricsOverride", width=390, height=800, deviceScaleFactor=2, mobile=True)
    try:
        ui.js("window.scrollTo(0, 0)")
        assert len(set(heights())) == 1, heights()  # and on a phone, where the note is its own row
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


def test_the_app_name_is_always_in_view(ui):
    assert "Teetime Monitor" in ui.text(".brand.in-bar") and ui.js("getComputedStyle(document.querySelector('.brand.top')).display") == "none"
    ui.call("Emulation.setDeviceMetricsOverride", width=393, height=800, deviceScaleFactor=2, mobile=True)
    try:
        assert "Teetime Monitor" in ui.text(".brand.top") and ui.js("getComputedStyle(document.querySelector('.brand.in-bar')).display") == "none"
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
    assert ui.count(".legend .tool-ico") == 9  # every toolbar icon is named
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


def test_search_puts_the_criteria_beside_the_results_on_a_large_landscape_screen(ui):
    try:
        ui.call("Emulation.setDeviceMetricsOverride", width=1400, height=800, deviceScaleFactor=1, mobile=False)
        _open_sheet(ui, "s", "")
        ui.wait("document.querySelectorAll('.res').length > 3")
        side = ui.js("(() => { const c = document.querySelector('.criteria').getBoundingClientRect(), r = document.querySelector('.results').getBoundingClientRect(); return [c.right <= r.left, r.width, r.height]; })()")
        assert side[0] is True and side[1] > 700 and side[2] > 400  # criteria left, results right, both with room
        _close_sheet(ui)
        ui.call("Emulation.setDeviceMetricsOverride", width=820, height=1100, deviceScaleFactor=1, mobile=False)  # upright: one column again
        _open_sheet(ui, "s", "")
        ui.wait("document.querySelectorAll('.res').length > 3")
        assert ui.js("document.querySelector('.criteria').getBoundingClientRect().bottom <= document.querySelector('.results-head').getBoundingClientRect().top + 1")
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
            _open_view(ui)
            ui.set("#v-theme", theme)
            ui.js("new Promise((done) => setTimeout(done, 300))")
            ui.key("Escape")
            failing = ui.js(CONTRAST_JS)
            assert failing == [], (theme, failing[:3])
    finally:
        _open_view(ui)
        ui.set("#v-theme", original)
        ui.key("Escape")


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
        for key, ready in (("s", ".results-head"), ("h", ".hm-wrap, .empty"), ("p", ".player-list"), ("e", "#f-field-availability-min_open_spots"), (",", "#login-user"), ("a", ".search-box input"), ("?", ".legend")):
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
    page.js("document.querySelector('[data-view-button]').click()")
    page.wait("document.querySelector('.view-panel')")
    page.click(".view-panel .btn", "Log out")
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
    page.js("document.querySelector('[data-view-button]').click()")
    page.wait("document.querySelector('.view-panel')")
    page.click(".view-panel .btn", "Log out")
    page.wait("document.documentElement.dataset.ready")
    page.set("#password", "swing and a miss")  # the old password is refused ...
    page.click("#submit")
    page.wait("!document.querySelector('#error').hidden")
    page.set("#password", "a brand new secret")  # ... the new one works
    page.click("#submit")
    page.wait("document.querySelectorAll('.card').length > 0")
