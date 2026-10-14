# For developers

[Back to the README](../README.md) · [Releasing](RELEASING.md) · [What pc caddie's pages look like](pccaddie-markup-notes.md) · [Build history](history/ROADMAP.md)

## Run it from a checkout

```bash
pip install -e ".[dev]" websockets
python -m src.tui                   # the terminal app
python -m src.webui.server          # the browser version
python scripts/webui_demo.py /tmp/demo --serve   # the browser version on a fake club: no login, no network
pytest -q                           # the test suite (about a minute and a half)
ruff check src/ tests/ scripts/
TEETIME_E2E=1 pytest tests/test_webui_e2e.py     # the browser version in a real Chrome/Chromium/Edge (about 30 s)
python scripts/make_screenshots.py               # retakes the README's screenshots (assets/en, assets/de)
```

## How the Python side is layered

- `src/tui.py` — the terminal app: Textual widgets, Rich markup, key bindings, layout.
- `src/pipeline.py` — headless logic with no Textual/Rich imports: `_resolved_config()` (club YAML + global
  preferences), `_availability_pipeline()` (the Pick column and the ★ markers), `_shorter_round_alternative()`,
  `_crowd_estimates()` with its holiday/vacation/heatmap caches, `_too_late_for_daylight()`.
- `src/quality.py` — the free, deterministic, explainable slot score behind a day's Pick: `score_matches()` weighs
  weather margin over the real round, room around the group, predicted crowd and daylight cushion, and names up to
  three reason keys. Reason keys are localised only at the edges (`i18n.py`, `webui/static/strings.json`).
- `src/clock.py` — the one time seam: `today()`, `now_hhmm()`, `now_utc()`. Call them as `clock.today()` (never
  `from .clock import today`) so one test patch reaches every module.
- `src/booking.py` — real reservations on pc caddie: book a time and cancel your booking (a logged-in browser-like session,
  the site's own two-step form with its one-time `process`/`cati` values, success read back from My Reservations).
  Both front ends call `book_for_club()` / `cancel_for_club()`; `tests/test_booking.py` runs it against a fake of the site.
- `src/webui/` — the browser version. `server.py` (stdlib `ThreadingHTTPServer`, no framework), `data.py` (builds the
  JSON from `storage`, `pipeline` and `picks_cli.compute_picks`), `settings_api.py`, `tools_api.py`, `clubs_api.py`,
  `auth.py` (the `--serve` password), `updates.py` (release check and the Pi's "Update now"). The page is plain
  JavaScript modules in `static/` (vendored Preact + htm, no build step); texts are in `static/strings.json`
  (English and German) plus the app's own catalog `src/i18n.py`.
- The `*_cli.py` modules (`picks_cli`, `search_cli`, `login_cli`, `ai_login_cli`, `add_club_cli`, `directory_cli`,
  `preview_club_cli`) hold logic the browser version shares with the terminal app. They depend only on `pipeline.py`
  and the leaf modules, never on `tui.py` (`tests/test_import_hygiene.py` enforces this).

Rules of thumb: logic more than one front end needs goes in `pipeline.py` (or a leaf module); markup and widgets stay
in `tui.py` and `webui/static/`. Tests patch moved state where it now lives, e.g. `pipeline._HOLIDAY_CACHE`,
`pipeline._resolved_config`, `clock.today`.

SQLite: the background scraper, the terminal app and the web server share each club's `.db`, so every connection goes
through `storage._open()`/`_connect()`, which sets `busy_timeout=5000` and switches the file to WAL once. WAL leaves
`<db>-wal`/`<db>-shm` beside the file, so never copy a bare `.db`: use `storage.backup_db()`.

## Module map

```
src/
├── tui.py                    # the terminal app -- club browser, overview, search, heatmap
├── pipeline.py / clock.py    # headless recommendation logic; the time seam
├── scraper.py                # fetch, login, tee-sheet parsing
├── scrape_once.py            # scheduled scrape + "My Reservations" sync
├── storage.py                # SQLite persistence
├── net.py / doctor.py        # OS certificate store; the `--doctor` report
├── search.py / recommend.py  # hard filters, then weather/daylight + AI ranking
├── quality.py                # the free, explainable score behind the ★ Pick
├── ai_assist.py              # the three AI calls (classify, rank, summarize), multi-provider
├── weather.py                # Open-Meteo client
├── booking_watch.py          # did a confirmed booking's situation change?
├── playability.py            # does this round finish before sunset?
├── analytics.py              # crowd heatmap + readiness
├── calendar_context.py       # holidays + vacations -> day type
├── club_config.py / club_directory.py / geocode.py   # saved clubs, the club list, weather location
├── global_preferences.py     # the shared preferences file
├── theme.py / i18n.py / units.py                     # themes, English/German text, metric/imperial
├── models.py                 # Slot / Schedule / WeatherPoint / ConfirmedBooking
├── *_screen.py               # terminal screens: preferences, logins, player directory
└── webui/                    # the browser version (see above)
```

## The browser version's safety design

It sits in front of a pc caddie login, so it is conservative: it listens on 127.0.0.1 only (random port); every
request needs a random token that only the printed link contains (kept in an HttpOnly cookie); it refuses another
`Host` or `Origin`; and a strict Content-Security-Policy lets the page load nothing from elsewhere. The only
bundled third-party code is Preact (`src/webui/static/vendor/LICENSES.txt`). `--serve` mode swaps the token for a
password (PBKDF2-SHA256, signed 30-day cookie, per-address lockout) — see `src/webui/auth.py`.

## Screenshots

`scripts/make_screenshots.py` takes every picture in the README from the demo club in both languages (the browser
through Chrome, the terminal app headless in Textual, drawn by the same browser). The app icon's artwork is
`assets/icon/make_icon.swift`; `assets/icon/make_web_icons.sh` (needs a Mac with the Command Line Tools)
regenerates `src/webui/static/icons/`.
