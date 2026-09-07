# teetime-monitor

A local CLI tool that scrapes a pc caddie online club portal's tee sheet and shows it as
a live-refreshing terminal grid — a faster, leaner alternative to the club's own web/app
view, for personal use. In the spirit of [`brew-launcher`](https://github.com/) (fzf-based
CLI tooling).

Status: every backend piece is real and tested now — scraper, storage, scheduled
scrape, weather, holidays/vacations, the "did my booking's situation change" watcher,
the deterministic recommendation engine, the three Claude API calls, local-history
analytics/crowd-heatmap, and login (a plain form POST, confirmed 2026-09-06 by
inspecting the real site — no browser automation needed for it either). "My
Reservations" parsing is fully confirmed too (2026-09-07), against a real demo
booking. The TUI's single-day detail screen (club/course picker, the tee sheet itself,
confirming a booking, and the booking-watch banners) is real too, and it can search
pc caddie's own club directory inline (`club_picker.ClubSearchScreen`, added
2026-09-07) — no separate command needed to add a club beyond your first one — plus
a credentials setup screen (`credentials_screen.py`) it opens automatically the
moment it needs a login and none is configured yet. The TUI also keeps its data
current on its own now — it re-scrapes the active club's whole overview window once
on open and periodically while it stays running, not just when `r` is pressed — see
"Project structure" below. Still to come: the multi-day overview, ad hoc search, and
crowd-heatmap screens. See [`ROADMAP.md`](ROADMAP.md) for the phased build plan and
[`docs/spec-v1.md`](docs/spec-v1.md) for the original spec.

## Planned capabilities

- Save more than one club (`clubs/`), picking which one at startup — skipped
  automatically if you've only saved one. Add clubs beyond your first one by
  searching pc caddie's own directory instead of hand-typing a numeric id — from the
  TUI's own switch-club menu (`s`, then "🔍 Search for a club…"), or standalone via
  `python -m src.club_picker` — matching pc caddie's own in-app "Anlagenauswahl"
  feature (confirmed against real app screenshots, 2026-09-06)
- Course picker showing each club's own real options, fetched live from that club's
  tee-sheet page rather than assumed — confirmed 2026-09-07 that this genuinely
  differs per club: a first club's 27-hole "18 Loch Tee 1" / "9 Loch Tee 1" /
  "6 Loch Platz" (with the actual weekly A/B/C loop combination shown as an
  informational banner) turned out to be that club's own setup, not a platform-wide
  default — a second real club's own options share no names or codes with the first
  at all
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
- The TUI itself also scrapes automatically — once right when you open it, and
  periodically while it keeps running — covering the whole overview window, not just
  the day on screen. `r` still re-scrapes just the current day immediately, as a
  manual override; the automatic pass is what keeps everything current without
  needing either a keypress or a cron job to be set up first
- Terminal table view: time slot, occupancy, player names, colored by fill ratio.
  Real names only show for people on your pc caddie friends list (a native pc caddie
  feature) — everyone else appears anonymized as "Member (handicap)", confirmed on the
  real site. Today's own already-passed slots are dimmed rather than hidden — still
  visible for reference, but a clear visual cue you can't book them anymore. A slot
  that already matches your saved availability rules (and isn't rained/wind/dark
  out) gets a "★" next to its time — the deterministic half of Phase 3's
  recommendation engine, applied to today's view directly rather than waiting on the
  full multi-day overview screen
- Confirmed bookings read automatically from pc caddie's own "My Reservations" page —
  teetime-monitor never books for you, but this is what actually gives the stats below
  something to work with. A manual confirm keypress (`c` in the TUI) stays as a fallback
  for the rare same-day-booking timing gap — pre-filled from whatever row is
  highlighted and the course you're already viewing, not re-typed by hand
- Switch club or course at any time from the tee sheet itself (`s`) — not just at
  startup. Its club list also offers "🔍 Search for a club…", so a brand-new club can
  be found, saved, and switched to in that same menu — no separate command needed
  first. `escape` backs out of any picker with nothing changed; `q` quits
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
cp clubs/club.example.yaml clubs/my-club.yaml      # fill in club id, coordinates, etc.
                                                    # (your first club only -- see club_picker.py below
                                                    # for adding the rest by searching, not hand-typing)

python -m src.credentials_screen                   # set PCC_USER/PCC_PASS from the UI -- creates .env
                                                    # for you if it doesn't exist yet (still add
                                                    # ANTHROPIC_API_KEY to it by hand afterward)
python -m src.club_picker my-club                   # search pc caddie's directory to add another club --
                                                    # opens the credentials screen above automatically
                                                    # first if you skipped it
python -m src.settings_screen my-club              # adjust availability/weather preferences + scrape interval
python -m src.scrape_once                          # one-off scrape of every saved club's overview window
python -m src.tui                                  # the tee sheet itself, single-day detail view
```

The TUI's own auto-refresh (see "Planned capabilities" above) covers history while
it's open, but pc caddie hides past tee sheets entirely — any day nobody opens the
app is a permanent gap otherwise. To keep `scrape_once` running unattended too (on
macOS, via `launchd`, checking every 15 minutes and self-throttling per club's own
configured interval):

```bash
cat > ~/Library/LaunchAgents/com.teetimemonitor.scrape.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.teetimemonitor.scrape</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/teetime-monitor/.venv/bin/python</string>
        <string>-m</string><string>src.scrape_once</string>
    </array>
    <key>WorkingDirectory</key><string>/path/to/teetime-monitor</string>
    <key>StartInterval</key><integer>900</integer>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>~/Library/Logs/teetime-monitor.log</string>
    <key>StandardErrorPath</key><string>~/Library/Logs/teetime-monitor.log</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.teetimemonitor.scrape.plist
```

Check on it with `cat ~/Library/Logs/teetime-monitor.log` (empty means no errors);
remove it later with `launchctl unload ...` plus deleting the plist file.

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
│   ├── club_picker.py      # search pc caddie's directory, add a club -- ClubSearchScreen (pushable from tui.py) + a thin standalone wrapper (implemented)
│   ├── credentials_screen.py # Textual screen (standalone or pushed): set PCC_USER/PCC_PASS (implemented)
│   ├── env_file.py         # read/write .env KEY=value pairs in place (implemented)
│   ├── translated_footer.py # shared bilingual footer widget, used by every screen (implemented)
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
    ├── test_club_picker.py
    ├── test_credentials_screen.py
    ├── test_env_file.py
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
rarer per-club override, and for `ANTHROPIC_API_KEY`. Set `PCC_USER`/`PCC_PASS` via
`python -m src.credentials_screen` (or club_picker.py, which opens the same screen
automatically the moment it needs a login it doesn't have) rather than hand-editing
`.env` — Claude never sees, types, or handles the value either way, this just saves
opening a text editor. Fixed 2026-09-07, found while building that screen: `.env` is
now actually loaded into the environment (`club_config.py` calls `python-dotenv`'s
`load_dotenv()`) — a real, easy-to-miss gap before this, since a `.env` file sitting
there doing nothing looks identical to one that was never created. Club config files
under `clubs/` are gitignored too, aside from the tracked `club.example.yaml`
template. This is a
personal tool, built against real pc caddie portals rather than assumed markup — a
live walkthrough (2026-09-05, see `ROADMAP.md` "Live site findings" and "Confirmed pc
caddie markup reference") confirmed the tee sheet needs no login, and `scraper.py`'s
tee-sheet scraping is now verified against the live site (2026-09-06) — and, since a
second real club was added 2026-09-07, verified to genuinely differ per club too:
course names/alias codes and the booking-date window both turned out to be that
club's own setup, not a platform-wide constant, so `scraper.fetch_course_aliases()`
now reads each club's own options live instead of assuming any fixed set (see
`ROADMAP.md` "Known risks"). Login is implemented too
(2026-09-06) — the user logged into the real site themselves and Claude inspected the
resulting form's HTML directly, never entering or seeing the actual password; it
turned out to be a plain POST, no JavaScript, no CSRF token. `scrape_my_reservations()`
uses it to parse real reservation rows too, confirmed 2026-09-07 against an actual
demo booking (both English and German date/time formats). Note that every AI call
(booking-label classification, ranking, history summarization) sends data to
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
