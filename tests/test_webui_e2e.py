"""The web UI in a real browser (2026-10-10): every screen driven through Chrome's DevTools protocol.

Opt-in (`TEETIME_E2E=1`) because it needs Chrome, Chromium or Edge: a demo server with a fake club
(`scripts/webui_demo.py --offline`, no network) is started, the page is opened, and each screen is
clicked through. It fails on any exception or console error in the page, which is what unit tests
of the JSON cannot see. `TEETIME_E2E_SHOTS=dir` also saves a screenshot of every screen there.
"""

import base64
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
            if self.js(f"Boolean({expression})"):
                return
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
        [sys.executable, str(ROOT / "scripts" / "webui_demo.py"), str(tmp_path_factory.mktemp("demo")), "--serve", "--offline"],
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


def test_marking_and_cancelling_a_booking(ui):
    before = ui.count(".pill.booked")
    ui.click(".card.open .slot.clickable")
    ui.wait("document.querySelector('.sheet h2')")
    assert "as your booking" in ui.text(".sheet h2")
    ui.shot("booking-dialog")
    ui.click(".sheet .btn.pri")
    ui.wait(f"document.querySelectorAll('.pill.booked').length === {before + 1}")
    ui.click(".card.open .slot.mine")
    ui.wait("document.querySelector('.sheet h2')")
    assert "Cancel your" in ui.text(".sheet h2")
    ui.click(".sheet .btn.danger")
    ui.wait(f"document.querySelectorAll('.pill.booked').length === {before}")


def test_search_lists_matches_and_offers_to_mark_one_booked(ui):
    _open_sheet(ui, "s", "Search")
    ui.wait("document.querySelectorAll('.res').length > 3")
    ui.shot("search")
    ui.click(".res .btn", "Mark booked")
    ui.wait("document.querySelectorAll('.sheet').length === 2")
    ui.click(".sheet.small .btn", "Not now")
    ui.wait("document.querySelectorAll('.sheet').length === 1")
    ui.set("#s-spots", "4")  # nothing has four open seats and a friend... a narrower search still answers
    ui.click(".criteria .actions .btn.pri")
    ui.wait("document.querySelector('.results-head')")
    _close_sheet(ui)


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
    ui.call("Emulation.setDeviceMetricsOverride", width=1280, height=520, deviceScaleFactor=1, mobile=False)
    _open_sheet(ui, "p", "Player")
    ui.wait("document.querySelectorAll('.player-list li').length > 8")
    heads = ui.js("[...document.querySelectorAll('.player-head span')].map((e) => e.textContent.trim()).filter(Boolean)")
    assert heads == ["Name", "Gender", "Status", "HCP"], heads  # every column of the directory is shown
    assert ui.js("document.querySelector('.player-list li:not(.letter) .player-meta').textContent.trim()") in ("Male", "Female", "Unknown")
    heads = ui.js("[...document.querySelectorAll('.player-head span')].map((e) => e.textContent.trim()).filter(Boolean)")
    assert heads == ["Name", "Gender", "Status", "HCP"], heads  # every column of the directory is shown
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
