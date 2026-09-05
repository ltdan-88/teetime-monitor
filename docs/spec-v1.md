# Tee Sheet TUI — Implementation Spec

## Goal
A local CLI tool that scrapes the full tee sheet (all slots, booked and free) from a pc caddie online club portal and displays it as a live-refreshing terminal grid — similar in spirit to `brew-launcher` (fzf-based CLI tooling on macOS).

No mobile support needed — pc caddie's own app already covers that. This is purely a faster/leaner terminal view for personal use.

## Scope for tomorrow's session (v1)
1. Scraper that logs into pc caddie and pulls one day's full tee sheet for one course
2. Local cache (JSON file is fine for v1 — no DB needed yet)
3. Textual TUI that renders the sheet as a table: time slot, occupancy (e.g. `3/4`), player names if visible
4. Manual refresh (press `r`) — auto-refresh on a timer can be v2
5. Config via `.env` (credentials) and a small `config.yaml` (club URL, default course, default date range)

Out of scope for v1: booking/auto-booking, notifications, multi-club support, packaging/distribution.

> **Superseded**: this was the original single-session spec. The project grew a broader
> scope (weather, multi-day overview, analytics) before this was implemented — see
> [`../ROADMAP.md`](../ROADMAP.md) for the actual phased plan and current storage design
> (SQLite from the start, not the flat JSON cache described below). Kept here verbatim as
> the historical starting point.

## Project structure
```
tee-sheet-tui/
├── README.md
├── pyproject.toml
├── .env.example
├── config.example.yaml
├── src/
│   ├── scraper.py       # Playwright login + tee sheet scrape
│   ├── models.py        # Slot / Schedule dataclasses
│   ├── storage.py        # save/load JSON cache
│   └── tui.py             # Textual app, entry point
└── tests/
    └── test_models.py    # basic unit tests for parsing logic
```

## Component details

### `scraper.py`
- Use Playwright (sync API) to launch a headless Chromium browser
- Log into `https://online.pccaddie.net/<club-slug>` using credentials from env vars `PCC_USER` / `PCC_PASS`
- Navigate to the "View Tee Times" (Anzeigen) screen for a given `course` and `date`
- Parse each tee time slot into a `Slot`:
  - `time: str` (e.g. `"09:10"`)
  - `booked: int`
  - `capacity: int`
  - `players: list[str]` (empty if none visible)
- **Important**: the actual CSS selectors are unknown until we inspect the real page. First implementation step should be: log in manually, use browser dev tools to identify the real selectors for the booking table, slot cells, and player names, and hardcode a `SELECTORS` dict at the top of `scraper.py` so it's easy to fix later if the club updates its site.
- Return a `Schedule` (date, course, list of `Slot`)

### `models.py`
```python
@dataclass
class Slot:
    time: str
    booked: int
    capacity: int
    players: list[str]

@dataclass
class Schedule:
    date: str
    course: str
    slots: list[Slot]
```

### `storage.py`
- `save_schedule(schedule: Schedule, path: str)` — dump to JSON
- `load_schedule(path: str) -> Schedule | None` — load if exists, else None
- Cache file path pattern: `cache/{course}_{date}.json`

### `tui.py`
- Textual `App` with a `DataTable` widget
- Columns: Time | Occupancy | Players
- Color the "Occupancy" cell by fill ratio (e.g. green if empty, yellow partial, red full) — Textual supports per-cell styling
- Keybindings: `r` = re-run scraper and refresh table, `q` = quit
- On startup: load from cache if present (instant display), then trigger a background refresh

### Config
`.env.example`:
```
PCC_USER=
PCC_PASS=
```
`config.example.yaml`:
```yaml
club_url: "https://online.pccaddie.net/<club-slug>"
default_course: ""
default_date: "today"   # or YYYY-MM-DD
```

## Acceptance criteria for v1
- [ ] Running `python -m src.tui` opens a terminal grid showing today's full tee sheet for the configured course
- [ ] Occupancy and player names match what's visible in the actual pc caddie web portal for the same day
- [ ] Pressing `r` re-scrapes and updates the table without restarting the app
- [ ] Credentials are never hardcoded — read from `.env`
- [ ] README documents setup: `pip install -e .`, `playwright install chromium`, copying `.env.example` → `.env`

## Known risks / things to validate first
- Real selectors for pc caddie's booking table are unverified — this must be the first task, before writing the rest of the scraper
- Session/login flow may include extra steps (cookie banner, 2FA, or a club-selection step before the login form) — inspect manually first
- If pc caddie renders the tee sheet via an iframe, Playwright will need `page.frame_locator(...)` instead of top-level selectors

## Suggested order of implementation
1. Manual login walkthrough + selector discovery (no code yet — just notes)
2. `models.py` + `storage.py` (quick, unblocks testing)
3. `scraper.py` against the real site
4. `tui.py` wired to scraper output
5. Polish: coloring, keybindings, README
