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
- Course picker for the 27-hole club's fixed options ("18 Loch Tee 1" / "9 Loch Tee 1" /
  "6 Loch Platz") — the actual weekly A/B/C loop combination just shows as an
  informational banner, confirmed by checking the real site rather than assumed
- Scrape the full tee sheet (all slots, booked and free) for a given course/date, with a
  scheduled background scrape too — pc caddie hides past tee sheets, so history can't be
  filled in later, and this keeps it building even on days you don't open the app.
  Occupancy and timing parse deterministically once inspected (plain code, no AI cost);
  the one genuinely ambiguous bit — telling an anonymized booking, an event/lesson
  block, and an actual friend's name apart — is a small
  [Claude](https://www.anthropic.com/claude) classification call, not a whole-page
  parse
- Terminal table view: time slot, occupancy, player names, colored by fill ratio.
  Real names only show for people on your pc caddie friends list (a native pc caddie
  feature) — everyone else appears anonymized as "Member (handicap)", confirmed on the
  real site
- Confirmed bookings read automatically from pc caddie's own "My Reservations" page —
  teetime-monitor never books for you, but this is what actually gives the stats below
  something to work with. A manual confirm keypress (`c` in the TUI) stays as a fallback
  for the rare same-day-booking timing gap
- A booking doesn't stop being watched once it's confirmed: if someone joins your
  flight or a neighboring slot fills in and shrinks your buffer, a plain banner shows
  up next time you open the app — no push notifications, just visible when you check
- Rain/weather overlay per slot (via [Open-Meteo](https://open-meteo.com/), no API key
  needed)
- Sunrise/sunset-aware playability highlighting — flags tee times too late to finish a
  9- or 18-hole round before dark, based on a configurable estimated round duration
- Wind and temperature in the weather overlay too, not just rain
- Tournament/event days flagged, sourced from pc caddie's dedicated events calendar
  (confirmed to exist as its own page, separate from the tee sheet)
- Public holidays and school-vacation periods factored in too, since both tend to mean
  a busier course
- Set your standing availability once (e.g. "workdays after 17:00, weekends after
  10:00, always solo") and the week's matching slots are highlighted automatically —
  no need to search every time
- A 4-5 day at-a-glance overview as the home screen, drilling into single-day detail
- Search for the one-off exceptions: type in "3 players, weekdays only, after 15:00,
  20 min clear of other flights" and get a ranked list for that specific case. Party
  size and time windows are checked exactly (plain code); weighing rain/wind/
  temperature/friends into a ranking with plain-language reasons is the same AI call
  behind the automatic weekly picks
- A crowd heatmap — historical occupancy grouped by day type (workday, weekend, public
  holiday, vacation, tournament), so a future vacation-week Monday gets compared
  against other vacation days, not typical Mondays. The raw numbers are plain
  aggregation; judging how much to trust a thin history for a rarer day type is an AI
  call, and that's what steers the automatic picks and search away from
  likely-overbooked windows
- Local pattern-recognition analytics over accumulated history ("when is this course
  usually emptiest?")
- Personal stats (days since you last played, rounds logged, and open-ended commentary
  once there's real history to look at)

See [`ROADMAP.md`](ROADMAP.md) for the full phase breakdown.

## Setup (once Phase 0/1 land)

```bash
pip install -e .
playwright install chromium
cp .env.example .env                              # fill in PCC_USER / PCC_PASS / ANTHROPIC_API_KEY
cp clubs/club.example.yaml clubs/my-club.yaml      # fill in club id, coordinates, etc.
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
│   ├── spec-v1.md              # original single-session spec (historical)
│   └── pccaddie-markup-notes.md # example HTML snippets for the real site's markup
├── src/
│   ├── club_config.py      # multi-club: list/load clubs, resolve credentials (implemented)
│   ├── scraper.py          # direct-URL fetch + mostly-deterministic parsing (partly implemented)
│   ├── scrape_once.py      # headless scrape for a cron/launchd schedule
│   ├── booking_watch.py    # did a confirmed booking's situation change since you booked it?
│   ├── ai_assist.py        # Claude API: booking-label classification, ranking, history summarization
│   ├── weather.py          # Open-Meteo rain + wind + sunrise/sunset client
│   ├── calendar_context.py # public holidays + vacation ranges -> day-type tag
│   ├── playability.py      # is a tee time playable before sunset? (implemented)
│   ├── recommend.py        # filters via search.py, ranks via ai_assist.rank_slots
│   ├── search.py           # exact hard-filtering — party size, time windows, buffer
│   ├── models.py           # Slot / Schedule / WeatherPoint / SunTimes / ConfirmedBooking / SlotMatch / ...
│   ├── storage.py          # SQLite persistence — scraped sheets + confirmed bookings
│   ├── analytics.py        # raw aggregation + crowd heatmap; ai_assist for interpretation
│   └── tui.py               # Textual app: club/course pickers, overview, day detail, search
└── tests/
    ├── test_models.py
    ├── test_club_config.py
    └── test_scraper.py
```

## Notes

Credentials are never hardcoded — read from `.env`, which is gitignored. One pc caddie
login covers every saved club (confirmed 2026-09-05), so plain `PCC_USER`/`PCC_PASS` is
normally all you need even with several clubs configured — see `.env.example` for the
rarer per-club override, and for `ANTHROPIC_API_KEY`. Club config files under `clubs/`
are gitignored too, aside from
the tracked `club.example.yaml` template. This is a personal tool built against one real
club's actual portal — a live walkthrough (2026-09-05, see `ROADMAP.md` "Live site
findings" and "Confirmed pc caddie markup reference") already confirmed the tee sheet
needs no login, real CSS classes for occupancy/blocking, and more; the login form
itself is the main remaining unverified piece, first real implementation step before
scraper.py's stub functions can be filled in. Note that every AI call (booking-label
classification, ranking, history summarization) sends data to Anthropic's API and costs
a small amount per call — see "Known risks" in `ROADMAP.md`.
