# teetime-monitor

A local CLI tool that scrapes a pc caddie online club portal's tee sheet and shows it as
a live-refreshing terminal grid — a faster, leaner alternative to the club's own web/app
view, for personal use. In the spirit of [`brew-launcher`](https://github.com/) (fzf-based
CLI tooling).

Status: **early scaffolding** — no scraper or TUI code yet. See [`ROADMAP.md`](ROADMAP.md)
for the phased build plan and [`docs/spec-v1.md`](docs/spec-v1.md) for the original spec.

## Planned capabilities

- Scrape the full tee sheet (all slots, booked and free) for a given course/date, with a
  scheduled background scrape too — pc caddie hides past tee sheets, so history can't be
  filled in later, and this keeps it building even on days you don't open the app
- Terminal table view: time slot, occupancy, player names, colored by fill ratio
- A confirm-your-tee-time prompt (`c` in the TUI) — teetime-monitor never books for you,
  but this is what actually gives the stats below something to work with
- Rain/weather overlay per slot (via [Open-Meteo](https://open-meteo.com/), no API key
  needed)
- Sunrise/sunset-aware playability highlighting — flags tee times too late to finish a
  9- or 18-hole round before dark, based on a configurable estimated round duration
- Wind and temperature in the weather overlay too, not just rain
- Tournament/event days flagged, since pc caddie lists these on the tee sheet
- A "pick for me" recommended slot per day, scored against your own preferences (time of
  day, solo vs group, rain/wind/temperature tolerance, and friends if scraping confirms
  it's possible)
- A 4-5 day at-a-glance overview as the home screen, drilling into single-day detail
- Local pattern-recognition analytics over accumulated history ("when is this course
  usually emptiest?") — no AI calls, no external cost
- Personal stats (days since you last played, rounds logged, and more once there's real
  history to look at)
- An opt-in AI-assisted insights mode, later, once there's real history to analyze

See [`ROADMAP.md`](ROADMAP.md) for the full phase breakdown.

## Setup (once Phase 1 lands)

```bash
pip install -e .
playwright install chromium
cp .env.example .env      # fill in PCC_USER / PCC_PASS
cp config.example.yaml config.yaml   # fill in club URL, course, coordinates
```

## Project structure

```
teetime-monitor/
├── README.md
├── ROADMAP.md
├── pyproject.toml
├── .env.example
├── config.example.yaml
├── docs/
│   └── spec-v1.md        # original single-session spec (historical)
├── src/
│   ├── scraper.py         # Playwright login + tee sheet scrape
│   ├── scrape_once.py     # headless scrape for a cron/launchd schedule
│   ├── weather.py         # Open-Meteo rain + wind + sunrise/sunset client
│   ├── playability.py     # is a tee time playable before sunset? (implemented)
│   ├── recommend.py       # "pick for me" — score today's slots against your prefs
│   ├── models.py          # Slot / Schedule / WeatherPoint / SunTimes / ConfirmedBooking
│   ├── storage.py         # SQLite persistence — scraped sheets + confirmed bookings
│   ├── analytics.py       # local pattern-recognition + personal stats over history
│   └── tui.py              # Textual app: multi-day overview + day detail + confirm
└── tests/
    └── test_models.py
```

## Notes

Credentials are never hardcoded — read from `.env`, which is gitignored. This is a
personal tool built against one club's actual portal; the pc caddie CSS selectors are
unverified until inspected by hand (see the "Known risks" section of the v1 spec) —
that's the first real implementation step, before any scraper code is written.
