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
  When your window opens too late for a full round on several days, one line says so (with the numbers and a
  button to Preferences); a day where only a shorter round on another course still fits shows that slot as a
  badge, and clicking it switches to that course. In **Players**, the "Next tee time" button on a name (or a
  double-click) jumps to that player's tee time, switching course if needed. The slot columns have headings
  (°C, rain, wind) and tooltips, and the settings cards balance their columns.
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
while the page is open, and no background scraper (nothing runs while the window is closed) -- unless you run
it as a server: `teetime-monitor-web --serve` (password, fetches by itself, for the whole home network) is
described in [RASPBERRY-PI.md](RASPBERRY-PI.md).

## Updates

Every few hours the program checks GitHub's public release list (a single request that sends nothing about you); when a
newer version exists the footer says **Version X is available** and links to the release notes, with the command
that updates your kind of install (`brew upgrade teetime-monitor`, `scoop update teetime-monitor`). On a
Raspberry Pi server there is an **Update now** button ([RASPBERRY-PI.md](RASPBERRY-PI.md)). The portable downloads
and the Mac app are updated by downloading the new release. The footer's **Check for updates** looks right away. `TEETIME_MONITOR_NO_UPDATE_CHECK=1` turns the check off.

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

The page adapts to the screen, in three steps: on a **tablet** (about 640 to 1200 px, such as a portrait iPad) every
day keeps its whole table (weather, free seats, rain and wind, with column headings), long lists of names wrap
inside their column, and every row is finger-sized and equally tall; in any window up to 860 px wide (a phone, a portrait tablet, or a narrow browser window on a computer) the players
are a chip with their count (★ when a friend plays) that opens the names as a vertical list under the seats; on a
**phone** the toolbar also spreads over two rows, the forms stack and each time slot is one slim row (time, seats, free, the player chip, and weather, temperature, rain and wind on the right; in Search results the chip, and a small flag button to mark a time as booked); the View menu opens
across the screen and holds the version and **Check for updates**, and Search scrolls as a whole (also with the phone
on its side, where windows use nearly the whole short screen). Wider windows show the names in the row. (Checked at 390, 640, 744, 834 and 1100 px.)

A touch screen has no hover, so a tooltip never shows. Instead: touch and hold any icon, number or heading and its
explanation appears as a bubble; what a day's badge means (why it is the pick, or why there is none) is written out
above the day's times, with a button to switch to a shorter round on another course; a tapped heatmap square shows its
numbers; and the Legend (footer, ⓘ) names every toolbar icon and badge. The °C / rain / wind headings stay pinned under
the day header while the times scroll, and the app's name is always at the top.

**As an app icon:** in Safari on an iPhone or iPad open the page, tap Share, then *Add to Home Screen*: it gets the same
icon as the Mac app, its own name and opens without the browser's bars (on Android: menu, *Install app* or *Add to Home
screen*). The icons are made from the Mac icon's artwork by `macos/icon/make_web_icons.sh`.

The program itself cannot run on a phone or tablet. Run it on a Raspberry Pi (or any always-on computer) with
`teetime-monitor-web --serve` and open its address from the device's browser: [RASPBERRY-PI.md](RASPBERRY-PI.md).

## Is it safe?

Your pc caddie login is behind it, so it is built conservatively:

- It listens on **127.0.0.1 only**, on a random port, never on the network (only `--serve`, for a Raspberry Pi
  server, opens it to your home network, and then it asks for a password: [RASPBERRY-PI.md](RASPBERRY-PI.md)).
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
