# teetime-monitor

A local CLI tool that scrapes a pc caddie online club portal's tee sheet and shows it as
a live-refreshing terminal grid — a faster, leaner alternative to the club's own web/app
view, for personal use. In the spirit of [`brew-launcher`](https://github.com/) (fzf-based
CLI tooling).

Status: every backend piece is real and tested now — scraper, storage, scheduled
scrape, weather, holidays/vacations, the "did my booking's situation change" watcher,
the deterministic recommendation engine, the three Claude API calls, local-history
analytics/crowd-heatmap, and login (a plain form POST, confirmed 2026-09-06 by
inspecting the real site — no browser automation needed for it either). The TUI's
single-day detail screen (club/course picker, the tee sheet itself, confirming a
booking, and the booking-watch banners) is real too — see "Project structure" below.
Still to come: the multi-day overview, ad hoc search, and crowd-heatmap screens, and
parsing an actual populated "My Reservations" list (only the empty state is confirmed
so far). See [`ROADMAP.md`](ROADMAP.md) for the phased build plan and
[`docs/spec-v1.md`](docs/spec-v1.md) for the original spec.

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
- The scheduled scrape's interval is adjustable per club, and automatically tightens
  once a date has a confirmed booking on it — e.g. every 6 hours normally, every hour
  once you've actually booked that date, since freshness matters more once there's
  something to protect
- Terminal table view: time slot, occupancy, player names, colored by fill ratio.
  Real names only show for people on your pc caddie friends list (a native pc caddie
  feature) — everyone else appears anonymized as "Member (handicap)", confirmed on the
  real site
- Confirmed bookings read automatically from pc caddie's own "My Reservations" page —
  teetime-monitor never books for you, but this is what actually gives the stats below
  something to work with. A manual confirm keypress (`c` in the TUI) stays as a fallback
  for the rare same-day-booking timing gap
- A booking doesn't stop being watched once it's confirmed: if someone joins your
  flight, a neighboring slot fills in and shrinks your buffer, or the weather forecast
  for the round itself gets worse, a plain banner shows up next time you open the app —
  no push notifications, just visible when you check
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
- A standalone settings screen for adjusting availability/weather preferences and the
  scrape interval without hand-editing YAML — run it with
  `python -m src.settings_screen <club-id>`. Built ahead of the main tee-sheet TUI,
  since these are the dials you'd actually want to reach for day to day
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
- Color themes, the same 10 named ones [`brew-launcher`](https://github.com/) uses
  (catppuccin, gruvbox, tokyonight, nord, dracula, green, amber, solarized-dark,
  solarized-light, red-sands) — switch via `ctrl+p` or the `t` key, applied
  immediately and remembered next time you open the app
- Bilingual UI (English/German) — every label, button, table header, and status
  message across the tee-sheet screen and the settings screen. Defaults to German if
  your system locale looks German, English otherwise; switch anytime from the same
  `ctrl+p` command palette as themes, applied immediately and remembered next time

See [`ROADMAP.md`](ROADMAP.md) for the full phase breakdown.

## Setup

```bash
pip install -e .
playwright install chromium
cp .env.example .env                              # fill in PCC_USER / PCC_PASS / ANTHROPIC_API_KEY
cp clubs/club.example.yaml clubs/my-club.yaml      # fill in club id, coordinates, etc.
                                                    # repeat for each club you want saved

python -m src.settings_screen my-club              # adjust availability/weather preferences + scrape interval
python -m src.scrape_once                          # one-off scrape of every saved club's overview window
python -m src.tui                                  # the tee sheet itself, single-day detail view
```

`tui.py`'s multi-day overview, ad hoc search, and crowd-heatmap screens aren't built
yet — see "Project structure" above for what's real today versus still a stub.

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
│   ├── club_config.py      # multi-club: list/load/save clubs, resolve credentials (implemented)
│   ├── scraper.py          # direct-URL fetch, login, parsing (implemented, verified live)
│   ├── storage.py          # SQLite persistence — scraped sheets + confirmed bookings (implemented)
│   ├── scrape_once.py      # headless scheduled scrape, adjustable per-club interval (implemented)
│   ├── search.py           # exact hard-filtering — party size, time windows, buffer (implemented)
│   ├── recommend.py        # filters via search.py + weather/daylight, ranks via ai_assist (implemented)
│   ├── settings_screen.py  # standalone Textual screen: edit preferences/interval (implemented)
│   ├── weather.py          # Open-Meteo rain + wind + sunrise/sunset client (implemented)
│   ├── booking_watch.py    # did a confirmed booking's situation change since you booked it? (implemented)
│   ├── playability.py      # is a tee time playable before sunset? (implemented)
│   ├── calendar_context.py # public holidays + vacation ranges -> day-type tag (implemented)
│   ├── ai_assist.py        # Claude API: booking-label classification, ranking, history summarization (implemented)
│   ├── models.py           # Slot / Schedule / WeatherPoint / SunTimes / ConfirmedBooking / SlotMatch / ...
│   ├── analytics.py        # raw aggregation + crowd heatmap; ai_assist for interpretation (implemented)
│   ├── theme.py            # 10 color themes, same set as brew-launcher (implemented)
│   ├── i18n.py             # English/German UI text lookup (implemented)
│   ├── user_config.py      # shared KEY=value config file, used by theme.py + i18n.py (implemented)
│   └── tui.py               # main Textual app: club/course pickers, day detail (implemented);
│                            #   multi-day overview, search, heatmap screens (not yet built)
└── tests/
    ├── test_models.py
    ├── test_club_config.py
    ├── test_scraper.py
    ├── test_storage.py
    ├── test_scrape_once.py
    ├── test_search.py
    ├── test_recommend.py
    ├── test_settings_screen.py
    ├── test_weather.py
    ├── test_booking_watch.py
    ├── test_calendar_context.py
    ├── test_ai_assist.py
    ├── test_analytics.py
    ├── test_theme.py
    ├── test_i18n.py
    ├── test_user_config.py
    ├── test_tui.py
    └── test_playability.py
```

## Notes

Credentials are never hardcoded — read from `.env`, which is gitignored. One pc caddie
login covers every saved club (confirmed 2026-09-05), so plain `PCC_USER`/`PCC_PASS` is
normally all you need even with several clubs configured — see `.env.example` for the
rarer per-club override, and for `ANTHROPIC_API_KEY`. Club config files under `clubs/`
are gitignored too, aside from the tracked `club.example.yaml` template. This is a
personal tool built against one real club's actual portal — a live walkthrough
(2026-09-05, see `ROADMAP.md` "Live site findings" and "Confirmed pc caddie markup
reference") confirmed the tee sheet needs no login, and `scraper.py`'s tee-sheet
scraping is now verified against the live site (2026-09-06). Login is implemented too
(2026-09-06) — the user logged into the real site themselves and Claude inspected the
resulting form's HTML directly, never entering or seeing the actual password; it
turned out to be a plain POST, no JavaScript, no CSRF token. `scrape_my_reservations()`
uses it, though it only confirms the empty "no bookings" state so far — the real row
markup for an actual booking is still unconfirmed and will need a follow-up once
there's one to look at. Note that every AI
call (booking-label classification, ranking, history summarization) sends data to
Anthropic's API and costs a small amount per call — see "Known risks" in `ROADMAP.md`.
Also note: `settings_screen.py` saves a club's whole config file on every save, so any
hand-written comments in that club's own `clubs/*.yaml` (e.g. ones copied over from
`club.example.yaml` when it was first created) won't survive — the checked-in
`club.example.yaml` template itself is never touched, so it stays available as
reference regardless.

Theme choice is separate from any club's YAML — it's a "how do I like my terminal to
look" preference, not a per-club fact — and lives in its own file,
`~/.config/teetime-monitor/config`, in the same spirit as `brew-launcher`'s own config
file. Set `TEETIME_MONITOR_THEME=<name>` to override it for one run without changing
the saved default. Language works the same way, sharing that same file
(`TEETIME_MONITOR_LANG=en` or `=de` to override for one run) — English and German are
supported, defaulting to German if your system locale looks German — and covers
everything in both screens, including the footer's key hints and the passive banners
`booking_watch.py` writes for a booking whose situation changed. One thing stays
English-only regardless of language: Textual's own built-in command-palette entries
("Theme"/"Quit"/"Keys"/"Screenshot"/"Maximize") — see `ROADMAP.md`'s bilingual-UI note
for why.
