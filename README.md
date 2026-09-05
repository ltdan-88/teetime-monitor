# teetime-monitor

A local CLI tool that scrapes a pc caddie online club portal's tee sheet and shows it as
a live-refreshing terminal grid — a faster, leaner alternative to the club's own web/app
view, for personal use. In the spirit of [`brew-launcher`](https://github.com/) (fzf-based
CLI tooling).

Status: **early scaffolding** — no scraper or TUI code yet. See [`ROADMAP.md`](ROADMAP.md)
for the phased build plan and [`docs/spec-v1.md`](docs/spec-v1.md) for the original spec.

## Planned capabilities

- Save more than one club (`clubs/`), picking which one at startup — skipped
  automatically if you've only saved one
- Course picker for clubs that rotate which 9-hole loops make up "the 18-hole course"
  week to week (this one plays 27 holes) — detected live from the site each run, not
  hardcoded
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
- Public holidays and school-vacation periods factored in too, since both tend to mean
  a busier course
- Set your standing availability once (e.g. "workdays after 17:00, weekends after
  10:00, always solo") and the week's matching slots are highlighted automatically —
  no need to search every time
- A 4-5 day at-a-glance overview as the home screen, drilling into single-day detail
- Search for the one-off exceptions: type in "3 players, weekdays only, after 15:00,
  20 min clear of other flights" and get a ranked list for that specific case, using
  the same rain/wind/temperature/friends scoring as your default weekly picks
- A crowd heatmap — historical occupancy grouped by day type (workday, weekend, public
  holiday, vacation, tournament), so a future vacation-week Monday gets compared
  against other vacation days, not typical Mondays. Also what steers the automatic
  picks and search results away from likely-overbooked windows
- Local pattern-recognition analytics over accumulated history ("when is this course
  usually emptiest?") — no AI calls, no external cost
- Personal stats (days since you last played, rounds logged, and more once there's real
  history to look at)
- An opt-in AI-assisted insights mode, later, once there's real history to analyze

See [`ROADMAP.md`](ROADMAP.md) for the full phase breakdown.

## Setup (once Phase 0/1 land)

```bash
pip install -e .
playwright install chromium
cp .env.example .env                              # fill in PCC_USER / PCC_PASS
cp clubs/club.example.yaml clubs/my-club.yaml      # fill in club URL, coordinates, etc.
                                                    # repeat for each club you want saved
```

## Project structure

```
teetime-monitor/
├── README.md
├── ROADMAP.md
├── pyproject.toml
├── .env.example
├── clubs/
│   └── club.example.yaml  # template — copy per real club (real ones are gitignored)
├── docs/
│   └── spec-v1.md          # original single-session spec (historical)
├── src/
│   ├── club_config.py      # multi-club: list/load clubs, resolve credentials (implemented)
│   ├── scraper.py          # Playwright login + tee sheet scrape
│   ├── scrape_once.py      # headless scrape for a cron/launchd schedule
│   ├── weather.py          # Open-Meteo rain + wind + sunrise/sunset client
│   ├── calendar_context.py # public holidays + vacation ranges -> day-type tag
│   ├── playability.py      # is a tee time playable before sunset? (implemented)
│   ├── recommend.py        # auto weekly picks from your saved default availability
│   ├── search.py           # shared search engine — ad hoc form + recommend.py's defaults
│   ├── models.py           # Slot / Schedule / WeatherPoint / SunTimes / ConfirmedBooking / SlotMatch / ...
│   ├── storage.py          # SQLite persistence — scraped sheets + confirmed bookings
│   ├── analytics.py        # pattern-recognition + crowd heatmap + personal stats
│   └── tui.py               # Textual app: club/course pickers, overview, day detail, search
└── tests/
    ├── test_models.py
    └── test_club_config.py
```

## Notes

Credentials are never hardcoded — read from `.env`, which is gitignored (see
`.env.example` for the single-club vs multi-club namespacing). Club config files under
`clubs/` are gitignored too, aside from the tracked `club.example.yaml` template. This is
a personal tool built against one real club's actual portal; the pc caddie CSS selectors
(and how it exposes the 27-hole course rotation) are unverified until inspected by hand
(see "Known risks" in `ROADMAP.md`) — that's the first real implementation step, before
any scraper code is written.
