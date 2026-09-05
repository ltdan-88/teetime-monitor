# teetime-monitor

A local CLI tool that scrapes a pc caddie online club portal's tee sheet and shows it as
a live-refreshing terminal grid — a faster, leaner alternative to the club's own web/app
view, for personal use. In the spirit of [`brew-launcher`](https://github.com/) (fzf-based
CLI tooling).

Status: **early scaffolding** — no scraper or TUI code yet. See [`ROADMAP.md`](ROADMAP.md)
for the phased build plan and [`docs/spec-v1.md`](docs/spec-v1.md) for the original spec.

## Planned capabilities

- Scrape the full tee sheet (all slots, booked and free) for a given course/date
- Terminal table view: time slot, occupancy, player names, colored by fill ratio
- Rain/weather overlay per slot (via [Open-Meteo](https://open-meteo.com/), no API key
  needed)
- A 4-5 day at-a-glance overview as the home screen, drilling into single-day detail
- Local pattern-recognition analytics over accumulated history ("when is this course
  usually emptiest?") — no AI calls, no external cost
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
│   ├── weather.py         # Open-Meteo rain forecast client
│   ├── models.py          # Slot / Schedule / WeatherPoint dataclasses
│   ├── storage.py         # SQLite persistence + history queries
│   ├── analytics.py       # local pattern-recognition over history
│   └── tui.py              # Textual app: multi-day overview + day detail
└── tests/
    └── test_models.py
```

## Notes

Credentials are never hardcoded — read from `.env`, which is gitignored. This is a
personal tool built against one club's actual portal; the pc caddie CSS selectors are
unverified until inspected by hand (see the "Known risks" section of the v1 spec) —
that's the first real implementation step, before any scraper code is written.
