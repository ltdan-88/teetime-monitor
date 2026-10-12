#!/usr/bin/env python3
"""Takes the README's screenshots (assets/en/*.png and assets/de/*.png) from the demo club -- no login, no
network, nothing of yours in them (2026-10-12).

  python scripts/make_screenshots.py            # both languages, the browser version and the terminal app
  python scripts/make_screenshots.py --lang de  # one language

The browser version is driven through Chrome, Chromium or Edge (set CHROME if it is not found); the
terminal app runs headless in Textual and is drawn to a picture by the same browser. Needs the dev
install (`pip install -e ".[dev]"`) plus `websockets`.
"""

import argparse
import asyncio
import base64
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"  {path}  {len(data) // 1024} KB")


# ---------------------------------------------------------------- the browser version


def web_shots(lang: str, out: Path) -> None:
    from test_webui_e2e import Page, _chrome

    executable = _chrome()
    assert executable, "no Chrome, Chromium or Edge found (set CHROME)"
    server = subprocess.Popen(
        [sys.executable, str(REPO / "scripts" / "webui_demo.py"), tempfile.mkdtemp(), "--serve", "--offline"],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ, "PYTHONUNBUFFERED": "1", "TEETIME_MONITOR_LANG": lang},
    )  # fmt: skip
    url = next(m.group(0) for m in (re.search(r"http://127\.0\.0\.1:\d+/\?t=[\w-]+", line) for line in server.stdout) if m)
    page = Page(executable)

    def view(width, height, scale=2, mobile=False):
        page.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=scale, mobile=mobile)
        if mobile:
            page.call("Emulation.setEmulatedMedia", features=[{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"}])
        else:
            page.call("Emulation.setEmulatedMedia", features=[])
        time.sleep(0.4)

    def shot(name):
        time.sleep(0.5)
        _write(out / f"{name}.png", base64.b64decode(page.call("Page.captureScreenshot", format="png")["data"]))

    def open_sheet(key, heading):
        page.key(key)
        page.wait(f"document.querySelector('.sheet h2') && document.querySelector('.sheet h2').textContent.includes({heading!r})")
        page.wait("document.querySelector('.sheet').contains(document.activeElement)")

    def close_sheet():
        page.click(".sheet-head .icon-btn")
        page.wait("!document.querySelector('.scrim')")

    try:
        page.go(url)
        page.wait("document.querySelectorAll('.card').length > 0")
        page.js("document.documentElement.dataset.theme = 'dark'; localStorage.clear()")
        page.wait("!/Updating|Aktualisiere/.test(document.querySelector('.footer').innerText)", 60)  # the first scrape pass is over
        view(1280, 760)
        page.js("window.scrollTo(0, 0)")
        shot("web-overview")
        page.click("button.dh", index=2)  # a sunny day with a pick
        page.wait("document.querySelector('.card.open .slot .names')")
        view(1280, 1000)
        page.wait("document.querySelectorAll('.card.open .slot').length > 6")
        shot("web-day")
        page.click("button.dh", index=2)  # close it again
        view(1280, 900)
        open_sheet("s", "")
        page.wait("document.querySelectorAll('.res').length > 3")
        shot("web-search")
        close_sheet()
        open_sheet("h", "")
        page.wait("document.querySelector('.hm-grid')")
        shot("web-heatmap")
        close_sheet()
        open_sheet("p", "")
        page.wait("document.querySelectorAll('.player-list li').length > 3")
        shot("web-players")
        close_sheet()
        view(390, 800, scale=3, mobile=True)
        page.js("window.scrollTo(0, 0)")
        shot("web-phone")
        page.click("button.dh", index=2)
        page.wait("document.querySelector('.card.open .slot')")
        shot("web-phone-day")
    finally:
        page.close()
        server.kill()


# ---------------------------------------------------------------- the terminal app


def tui_shots(lang: str, out: Path) -> None:
    from test_webui_e2e import Page, _chrome

    demo = Path(tempfile.mkdtemp())
    import webui_demo

    webui_demo.seed(demo)
    os.environ["TEETIME_MONITOR_NO_UPDATE_CHECK"] = "1"
    os.environ["TEETIME_MONITOR_LANG"] = lang
    from src import i18n, scrape_once, tui

    scrape_once.scrape_due_for_club = lambda *a, **k: []
    import tomllib
    from datetime import date, timedelta

    tui.fetch_course_aliases = lambda club_id: {"18 Loch Tee 1": "18 Loch Tee 1"}  # no network: the demo club's one course
    tui.fetch_available_dates = lambda club_id: [(date.today() + timedelta(days=n)).isoformat() for n in range(0, 5)]
    tui._version = lambda: tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    tui._FIRST_SCRAPE_DELAY_SECONDS = 0.01
    i18n.set_language(lang)

    executable = _chrome()
    assert executable, "no Chrome, Chromium or Edge found (set CHROME)"
    svgs: dict[str, str] = {}

    async def drive():
        app = tui.TeetimeApp()
        async with app.run_test(size=(132, 38)) as pilot:
            await pilot.pause(1.0)

            async def press(*keys, wait=0.8):
                for key in keys:
                    await pilot.press(key)
                    await pilot.pause(wait)

            await press("escape")  # skip the login screen
            await press("down", "enter", wait=2.0)  # the demo club
            await press("enter", wait=2.0) if type(app.screen).__name__ == "CoursePickerScreen" else None
            print("  terminal app on:", type(app.screen).__name__)
            await pilot.pause(1.5)
            svgs["tui-overview"] = app.export_screenshot()
            table = app.screen.query_one("DataTable")
            table.focus()
            table.move_cursor(row=2)  # a sunny day with a pick
            await pilot.pause(0.5)
            await press("enter", wait=1.5)
            svgs["tui-day"] = app.export_screenshot()
            await press("enter", wait=0.3)  # (a second enter would mark a tee time: leave the day as it is)
            await press("escape", wait=0.6)
            await press("slash", wait=1.2)
            svgs["tui-search"] = app.export_screenshot()
            await press("escape", wait=0.6)
            await press("h", wait=1.2)
            svgs["tui-heatmap"] = app.export_screenshot()
            await press("escape", wait=0.6)

    asyncio.run(drive())

    page = Page(executable, width=1400, height=900)
    try:
        for name, svg in svgs.items():
            width, height = (float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg).groups())
            page.call("Emulation.setDeviceMetricsOverride", width=1400, height=round(1400 * height / width), deviceScaleFactor=2, mobile=False)
            page.go("data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode())
            time.sleep(0.6)
            _write(out / f"{name}.png", base64.b64decode(page.call("Page.captureScreenshot", format="png")["data"]))
    finally:
        page.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lang", choices=["en", "de"])
    parser.add_argument("--only", choices=["web", "tui"])
    parser.add_argument("--out", type=Path, default=REPO / "assets")
    args = parser.parse_args()
    if not args.lang:  # each language in its own process: the demo data and the app's language are fixed at start-up
        for lang in ("en", "de"):
            command = [sys.executable, __file__, "--lang", lang, "--out", str(args.out)] + (["--only", args.only] if args.only else [])
            subprocess.run(command, check=True)
        return
    print(args.lang)
    if args.only in (None, "web"):
        web_shots(args.lang, args.out / args.lang)
    if args.only in (None, "tui"):
        tui_shots(args.lang, args.out / args.lang)


if __name__ == "__main__":
    main()
