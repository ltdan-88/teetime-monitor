# The browser version (web UI)

*[Deutsche Version](WEBUI.de.md)*

A graphical version of Teetime Monitor that runs in a browser window, for Windows and Linux (the Mac has
its own native app; it runs on a Mac too). It is the same data and the same recommendations as the terminal app, in the dark
card layout of the Mac app (light when your system is light), in English or German.

**Status: complete.** Everything the Mac app does is here:

- **Overview:** pick a club and course; each day with weather, the recommended pick, your booking or the
  time its booking opens, and the occupancy bar. Days start collapsed (like the Mac app); open one for every tee time with players (friends starred,
  names coloured by gender, handicaps if you like), weather per slot and sunrise/sunset. Click a time to mark
  it as your booking, click your booking to cancel it. Notices ("a player joined your flight") appear on top.
- **Search**, **Crowd heatmap**, **Players** (friends), **Preferences** (availability, weather, pace,
  priorities), **Settings** (clubs, pc caddie login, language, units, scraping, AI ranking) and **Add club**
  (search the club directory, add a club, or open one just to look at it).
- Scrolling works like the Mac app: an opened day keeps its header pinned while its times scroll, opens at its
  recommended time (slots outside your availability window are dimmed), and the player list scrolls under a fixed
  search with an A–Z index. **Settings > Scale** makes the whole page smaller or larger (this browser only; the
  browser's own zoom, Ctrl +/-, works too).
- **Refresh** fetches new tee sheets; opening the page also fetches whatever is due.
- A **View** menu in the toolbar (key `v`) with what changes how the page looks and reads, one click from the
  Overview: language (English or German), the same eleven colour themes as the terminal and Mac apps (with none
  chosen it follows your system's dark or light), scale, units and handicaps. And single-letter keys like the
  terminal app: `r` refresh, `s` search, `h` heatmap, `p` players, `e` preferences, `,` settings, `a` add club,
  `v` view menu, `?` legend, Esc closes a window.

What differs from the Mac app on purpose: no menu bar (everything is in the toolbar), notifications only
while the page is open, and no background scraper (nothing runs while the window is closed).

## Start it

- **Portable Windows / Linux download:** double-click `TeetimeMonitor-Web.cmd` (Windows), or run
  `./TeetimeMonitor-Web.sh` (Linux). See [WINDOWS-APP.md](WINDOWS-APP.md) and [LINUX-APP.md](LINUX-APP.md).
- **Installed with Scoop, Homebrew or pip:** run `teetime-monitor-web` in a terminal.

A window opens (Edge, Chrome or Chromium without tabs and address bar if one is installed, else your
default browser). If nothing opens, copy the link printed in the terminal into a browser. **Closing the
window stops the program** (a minute or two later); `--keep-running` keeps it running, Ctrl+C always stops
it. Other options: `--no-browser` (only print the link), `--port N`, `--help`.

When it opens, it also asks the scraper for anything that is due, like the terminal app does; the footer
says *Updating…* meanwhile. **Refresh** fetches everything now.

## Phones and tablets

The page itself adapts: down to a phone's width the forms stack, the toolbar spreads over two rows and every control
is finger-sized (checked at 390 px and on tablet sizes). What does **not** work is running it there: the program
(scraping, your pc caddie login, the data) is a Python program on your computer and listens on that computer only
(`127.0.0.1`), so a phone or tablet cannot open it, and nothing can be installed on one. Reaching it from a phone
on your home network would need a "listen on the network" option, which is a security decision (the link and its
token would travel unencrypted over your Wi-Fi), so it is deliberately not there yet. A real phone app would need
the scraping on a server, which this project does not have.

## Is it safe?

Your pc caddie login is behind it, so it is built conservatively:

- It listens on **127.0.0.1 only**, on a random port, never on the network.
- Every request needs a random **token** that only the printed link contains; the page keeps it in a
  cookie that scripts cannot read. Other programs and other websites cannot use the server.
- It refuses requests for another host name or from another website, and the page may load nothing from
  the internet (strict Content-Security-Policy). No fonts, scripts or images come from anywhere else.
- No new software is needed: it is plain Python from the standard library plus one small, bundled
  JavaScript library (Preact, see `src/webui/static/vendor/LICENSES.txt`).

## Changing the page

The page is plain JavaScript modules in `src/webui/static/` (Preact + htm, vendored; no build step); its texts
are in `strings.json` (English and German) plus the app's own catalog (`src/i18n.py`). `tests/test_webui_strings.py`
checks that every text the scripts use exists in both languages, and `tests/test_webui_e2e.py` (opt-in:
`TEETIME_E2E=1`, needs Chrome, Chromium or Edge) clicks through every screen of a demo server in a real browser.

## For developers

`src/webui/data.py` builds the JSON (reusing `storage`, `pipeline` and `picks_cli.compute_picks`),
`src/webui/server.py` serves it with `src/webui/static/` (no build step). To look at it without a pc
caddie login: `python scripts/webui_demo.py /tmp/demo --serve` seeds a fake club and starts it.
