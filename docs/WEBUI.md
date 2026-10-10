# The browser version (web UI)

*[Deutsche Version](WEBUI.de.md)*

A graphical version of Teetime Monitor that runs in a browser window, for Windows and Linux (the Mac has
its own native app). It is the same data and the same recommendations as the terminal app, in the dark
card layout of the Mac app (light when your system is light), in English or German.

**Status: first version.** It shows the **Overview**: pick a club and course, see each day with weather,
the recommended pick, your booking and the occupancy bar, and open a day to see every tee time with the
players, friends starred. Refresh fetches new tee sheets. Search, the crowd heatmap, the player directory,
Preferences, logins and *Add club* are still in the terminal app and will follow; add and log in to your
clubs there first (or use the Mac app).

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

## Is it safe?

Your pc caddie login is behind it, so it is built conservatively:

- It listens on **127.0.0.1 only**, on a random port, never on the network.
- Every request needs a random **token** that only the printed link contains; the page keeps it in a
  cookie that scripts cannot read. Other programs and other websites cannot use the server.
- It refuses requests for another host name or from another website, and the page may load nothing from
  the internet (strict Content-Security-Policy). No fonts, scripts or images come from anywhere else.
- No new software is needed: it is plain Python from the standard library plus one small, bundled
  JavaScript library (Preact, see `src/webui/static/vendor/LICENSES.txt`).

## For developers

`src/webui/data.py` builds the JSON (reusing `storage`, `pipeline` and `picks_cli.compute_picks`),
`src/webui/server.py` serves it with `src/webui/static/` (no build step). To look at it without a pc
caddie login: `python scripts/webui_demo.py /tmp/demo --serve` seeds a fake club and starts it.
