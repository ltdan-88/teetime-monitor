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
    # the column headings sit exactly over their values (every row shares the results' columns)
    edges = ui.js(
        """(() => { const right = (e) => Math.round(e.getBoundingClientRect().right);
        const head = [...document.querySelectorAll('.res-head .cell')].map(right);
        const row = [...document.querySelectorAll('.res:not(.res-head)')[0].querySelectorAll('.cell')].map(right);
        return [head, row]; })()"""
    )
    assert edges[0] == edges[1], edges
    ui.click(".res .btn", "Mark booked")
    ui.wait("document.querySelectorAll('.sheet').length === 2")
    ui.click(".sheet.small .btn", "Not now")
    ui.wait("document.querySelectorAll('.sheet').length === 1")
    ui.set("#s-spots", "4")  # nothing has four open seats and a friend... a narrower search still answers
    ui.click(".criteria .actions .btn.pri")
    ui.wait("document.querySelector('.results-head')")
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
    ui.click(".hint-bar .btn")  # the way straight to the setting
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


def test_a_newer_version_is_announced_and_a_pi_server_can_install_it(ui):
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
    ui.wait("document.querySelector('.update-note')")
    ui.shot("update-notice")
    assert "Version 9.9.9 is available" in ui.text(".update-note")
    assert ui.js("document.querySelector('.update-note a').href") == "https://example.invalid/notes"
    ui.click(".update-note .link-btn")
    ui.wait("document.querySelector('.sheet h2')?.textContent.includes('9.9.9')")
    ui.shot("update-sheet")
    ui.click(".sheet .btn", "Cancel")
    ui.wait("!document.querySelector('.scrim')")
    ui.click(".update-note .link-btn")
    ui.wait("document.querySelector('.sheet .btn.pri')")
    ui.click(".sheet .btn.pri")  # install: the first poll says "idle", the next one "failed"
    ui.wait("document.querySelector('.sheet .status-line.error')?.textContent.includes('no matching distribution')", 30)
    ui.click(".sheet .btn", "Cancel")
    ui.wait("!document.querySelector('.scrim')")
    assert ui.count(".card") > 0  # the page is still usable
    ui.js("window.__beforeReload = true; location.reload()")  # drop the rewriting again
    ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0")


def test_the_page_waits_for_a_fresh_server_process_after_an_update(ui):
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
    ui.wait("document.querySelector('.update-note .link-btn')")
    ui.js("window.__beforeReload = true")
    ui.click(".update-note .link-btn")
    ui.wait("document.querySelector('.sheet .btn.pri')")
    ui.click(".sheet .btn.pri")
    ui.wait("document.querySelector('.sheet .status-line')?.textContent.includes('Restarting')", 30)
    assert ui.js("window.__beforeReload") is True  # not reloaded while the old process still answered
    ui.wait("window.__beforeReload === undefined && document.querySelectorAll('.card').length > 0", 60)  # reloaded by the "idle" answer


def test_check_for_updates_says_what_it_found(ui):
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
    assert "Version 9.9.9 is available" in ui.text(".update-note")  # the found release shows its notice at once
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
        for width, whole_table in ((744, True), (834, True), (390, False)):
            ui.call("Emulation.setDeviceMetricsOverride", width=width, height=1100, deviceScaleFactor=2, mobile=True)
            ui.js("window.scrollTo(0, 0)")
            if not ui.count(".card.open"):
                ui.click("button.dh", index=1)
            ui.wait("document.querySelector('.card.open .slot')")
            shape = ui.js(
                """(() => { const rows = [...document.querySelectorAll('.card.open .slot')].filter((r) => !r.querySelector('.names'));
                const visible = (sel) => { const e = document.querySelector('.card.open .slot ' + sel); return !!e && getComputedStyle(e).display !== 'none'; };
                return {sameHeight: new Set(rows.map((r) => Math.round(r.getBoundingClientRect().height))).size, tall: Math.min(...rows.map((r) => r.getBoundingClientRect().height)),
                        free: visible('.free'), rain: visible('.rain'), wind: visible('.wind'), head: !!document.querySelector('.slots-head') && getComputedStyle(document.querySelector('.slots-head')).display !== 'none',
                        overflow: document.documentElement.scrollWidth > innerWidth}; })()"""
            )
            assert shape["sameHeight"] == 1 and shape["tall"] >= 43, (width, shape)  # rows without names are all one height, a finger tall
            assert shape["free"] and not shape["overflow"], (width, shape)
            chip = ui.js("(() => { const c = document.querySelector('.card.open .slot .who-chip'); return !!c && getComputedStyle(c).display !== 'none'; })()")
            assert chip == (not whole_table), (width, chip)  # the names are inline on a tablet, a chip on a phone
            assert (shape["rain"] and shape["wind"] and shape["head"]) == whole_table, (width, shape)  # weather columns and headings on tablets only
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
        assert ui.js("getComputedStyle(document.querySelector('.footer .check-update')).display") == "none"
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
        [sys.executable, str(ROOT / "scripts" / "webui_demo.py"), str(tmp_path_factory.mktemp("demo-served")), "--serve", "--offline", "--password", "swing and a miss"],
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
