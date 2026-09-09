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
booking. The TUI opens straight into a club browser: search pc caddie's whole club
directory, pick a favorite, or just type a club id — nothing has to be saved to config
first, and saving a club only ever means "favorite" (`f`). Picking a club/course lands
on the multi-day overview — the app's actual home screen (added 2026-09-07): one row
per bookable day with weather, a heat-strip of how full the day is, and that day's own
pick, plus "This week's picks" once you've set availability rules. Enter drills into
the single-day tee sheet (confirming a booking, the booking-watch banners), `escape`
pops back. There's also a credentials setup screen (`credentials_screen.py`) it opens
automatically the moment it needs a login and none is configured yet. The TUI keeps
its data current on its own — it re-scrapes the active club's whole booking window
once on open and periodically while it stays running, not just when `r` is pressed —
see "Project structure" below.

The scraper was checked against **79 real pc caddie clubs** on 2026-09-07 (not just
the two it was built against), across German, Swiss, Luxembourgish and
Italian-speaking clubs; every one of them now either loads correctly or reports
cleanly that the club publishes no tee sheet. See `src/scraper.py`'s module docstring
for what that sweep found and fixed — several of the failures were serious, including
one that made the tool unusable for nearly half of all clubs. `h` opens the crowd
heatmap screen — for now a data-readiness view (how close each weekday and each
special day type is to having enough history), since every real club here is still
too early in accumulating that history for the colored grid itself to say much yet. See [`ROADMAP.md`](ROADMAP.md)
for the phased build plan and [`docs/spec-v1.md`](docs/spec-v1.md) for the original
spec.

## Planned capabilities

- Open the app, pick a club, pick a course — in that order, with no setup step in
  front of it. The club browser is the home screen: an empty search box lists your
  favorites, typing searches pc caddie's whole club directory, and typing a club id
  (e.g. `0000001`) jumps straight to that club. `f` toggles a club as a favorite,
  `s` reopens the same browser from the tee sheet to switch clubs mid-session
- Favorites (`clubs/*.yaml`) are exactly that — a shortcut and a place to keep a
  club's own settings, never a precondition for looking at a club. Only favorites are
  scraped on a schedule, which is what keeps a club you merely glanced at from
  accumulating history you didn't ask for
- The club directory needs one login to download (pc caddie doesn't publish it), so
  it's fetched once and cached locally, refreshed on demand with `r`. Favorites and
  typed club ids both work with no login and no cached list at all — including on a
  brand-new install, which the old flow couldn't do
- Weather needs a location pc caddie itself doesn't publish anywhere, so any club you
  open — favorited or not — gets one looked up automatically: a best-effort search
  against OpenStreetMap's free Nominatim geocoder, using the club's own name, cached
  after the first lookup so it isn't repeated on every visit. Not always the exact
  clubhouse pin, but close enough for a forecast; still editable by hand in a
  favorite's own YAML either way
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
  recommendation engine, the same pipeline behind the overview's own picks below
- Confirmed bookings read automatically from pc caddie's own "My Reservations" page —
  teetime-monitor never books for you, but this is what actually gives the stats below
  something to work with. A manual confirm keypress (`c` in the TUI) stays as a fallback
  for the rare same-day-booking timing gap — pre-filled from whatever row is
  highlighted and the course you're already viewing, not re-typed by hand
- Two dropdowns right at the top of the overview — club and course — switch between
  clubs/courses you already have saved without leaving the screen at all (added
  2026-09-09, direct feedback: "would it be possible to integrate club and course
  selectors into the overview screen... this would make navigation much quicker").
  Picking a different club there refetches its course list and reloads in place,
  same as picking a different course does. `s` still opens the full searchable club
  browser ("🔍 Search for a club…") for finding and saving a club you haven't added
  yet — the dropdowns are a faster path for ones you already switch between
  regularly, not a replacement for discovering a new one. `escape` backs out of any
  picker with nothing changed; `q` quits
- A booking doesn't stop being watched once it's confirmed: if someone joins your
  flight, a neighboring slot fills in and shrinks your buffer, or the weather forecast
  for the round itself gets worse, a plain banner shows up next time you open the app —
  no push notifications, just visible when you check
- Weather (via [Open-Meteo](https://open-meteo.com/), no API key needed) as its own
  Temperature / Precipitation / Wind columns, both on the multi-day overview
  (that day's own high/low, average rain chance, and peak wind) and right on the
  single-day tee sheet (that exact hour's own reading, one row per tee time) — split
  apart rather than crammed into one combined column, so the real numbers are always
  visible, not just an icon once rain or wind crosses a plain visual threshold (the
  icon itself still shows past that threshold, layered on top of the number). The
  day's own sunrise/sunset shows above the single-day table, and each tee time whose
  round wouldn't finish before dark gets its own 🌙 marker directly in the Time
  column — independent of whether you've set any availability rules at all. The
  overview's own day-level "no dry picks" message only appears when weather is
  genuinely the reason nothing's recommended — a separate "too dark to finish" shows
  up instead when daylight is what actually excluded everything
- Sunrise/sunset-aware playability highlighting — flags tee times too late to finish a
  9- or 18-hole round before dark, based on your own estimated pace (adjustable in
  settings, defaulting to 2 hours for 9 holes / 4 hours for 18); the single-day tee
  sheet marks each such slot directly with a 🌙, not just a day-level summary
- Tournament/event days flagged in their own Events column (both overview and
  single-day tee sheet) — sourced directly from the tee sheet's own scraped
  block-reason labels, not a separate events-calendar fetch
- A dim legend line at the bottom of both screens spells out what each icon
  actually means (★ recommended, 🌧 rain, 💨 wind, 📋 event/closure, 📌 booked,
  ⚠ changed since booked, plus 🌙 too late for sunset on the single-day tee sheet)
  — added once there were enough of them that guessing started to feel necessary
- Public holidays and school-vacation periods factored in too, since both tend to mean
  a busier course
- Set your standing availability once (e.g. "workdays after 17:00, weekends after
  10:00, always solo") and the week's matching slots are highlighted automatically —
  no need to search every time. **Global, not per-club** — your own availability and
  weather comfort don't change depending on which course you're checking, so it's one
  shared set of rules that applies everywhere, not something to re-enter for every
  club you add
- A settings screen for adjusting that availability/weather preferences, your own
  estimated pace for 9/18 holes, and the scrape interval without hand-editing YAML —
  press `e` from the overview or the tee sheet itself, no separate command needed,
  and works the same regardless of which club is active (or even whether one is
  saved as a favorite at all). Still runnable on its own too via
  `python -m src.settings_screen`. Fields are grouped into collapsible sections
  (Availability / Weather / Priorities / AI ranking / Timing & scraping); ones with
  only a handful of sensible values (party size, the daylight buffer, round
  duration, both scrape intervals, and the buffer to nearby flights in 10-minute
  steps) are dropdowns rather than free text, so they can't hold a typo; the
  weekday/weekend time windows are hour and minute dropdowns rather than typing
  "17:00" by hand, with the hour list itself trimmed to 05:00-21:00 — no golf club
  is open at 2am; Save/Cancel sit right-aligned like an ordinary dialog's buttons,
  not hugging the window's left edge. Below about 72 columns wide, each field
  switches to label-above-field instead of side-by-side, so nothing gets clipped in
  a narrow terminal window
- AI-ranked recommendations (`ai_assist.enabled`) are a plain on/off switch in that
  same settings screen — moved there from `clubs/*.yaml` on request, since wanting
  this on or off never actually varied by club. No model choice is offered alongside
  it: the ranking task is just picking the best of an already-short, already-filtered
  list and writing one short reason, well within a fast/cheap model's reach, so it
  always uses Haiku rather than presenting a quality/cost dial that isn't a real
  tradeoff here. Off by default: with a real Anthropic API key configured, turning it
  on means a real, paid API call every time a recommendation gets computed — once per
  visible day on the overview, plus once for the weekly digest — not just a free
  quality bump, worth knowing before opting in
- The buffer to nearby flights is two separate settings, not one — how much clearance
  you want to the group ahead of you (who might be slow) and to the group behind you
  (who might be crowding in) aren't the same concern, so each has its own dial
- A multi-day at-a-glance overview as the home screen (`OverviewScreen`, added
  2026-09-07) — one row per day the club is actually taking bookings for right now
  (not a fixed count: a club's real window ranges 1-31 days, checked live each
  refresh), showing real weather split into its own Temperature/Precipitation/Wind
  columns, that day's own event/closure note (📌) in a separate Events column —
  split apart 2026-09-09 so a tournament or maintenance closure never crowds out the
  actual forecast — a six-block "heat strip" for how full 08:00-20:00 is, and that
  day's own pick — a
  confirmed booking, a recommended ★ slot, or why neither applies. That slot is the
  AI-ranked best match once `ai_assist.enabled` is on, otherwise the earliest one that
  clears your rules — not a promise that it's the best *time of day*, just the first
  one that isn't excluded. "This week's picks" below shows up to one recommendation
  per day across the whole loaded window (not just whichever day happened to have the
  most open slots), shown only once you've actually set availability rules. `enter`
  drills into that day's own single-day detail table; `escape` there pops back
- Search for the one-off exceptions (`/` from the overview): a small form, pre-filled
  from your saved availability so you're tweaking one case rather than typing
  everything from scratch — e.g. "just this once, 3 players, weekdays only, after
  15:00" — searched across every day already loaded, no fresh scrape. Party size,
  time windows, and the before/after buffer are checked exactly (plain code); the
  weather/daylight sanity check and the same AI ranking behind the automatic weekly
  picks both still apply on top
- A crowd heatmap — historical occupancy grouped by actual weekday (Sun-Sat), plus a
  separate "special days" comparison for tournament/public holiday/vacation days, so
  a future vacation-week Monday gets compared against other vacation days rather than
  typical Mondays, without costing a typical Monday one of its own samples either
  (matches the original mockup's own grid — reworked 2026-09-09 after a first version
  grouped by day type alone and lost weekday granularity entirely). Plain aggregation,
  with a minimum-sample-size floor deciding how much of a thin, rarer history to
  actually trust before it steers the automatic picks and search away from
  likely-overbooked windows. `h` opens the heatmap screen: right now a readiness view
  (how many hours each weekday and each special day type have hit that floor, and how
  many samples each has so far), since every real club here is still too early into
  accumulating history for the colored grid itself to be worth showing yet — the same
  floor is what will decide when it is
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

Via [Homebrew](https://brew.sh/) (macOS/Linux):

```bash
brew install ltdan-88/teetime-monitor/teetime-monitor
teetime-monitor                                    # opens on the club browser
```

Playwright needs a real Chromium binary the first time, and (like `terraform`/
`docker-compose`) this reads its own state — saved clubs, credentials, scrape
history — from whatever directory you run it in, not a fixed install location. The
formula's own `caveats` (shown right after install, or `brew info teetime-monitor`
any time after) spell out both.

From source instead:

```bash
pip install -e .
python -m src.tui                                  # that's it -- opens on the club browser
```

No club has to be configured first: type a club id (or search, once you've downloaded
the directory) and you're on its tee sheet. Everything below is optional, in the order
you're likely to want it:

```bash
python -m src.credentials_screen                   # set PCC_USER/PCC_PASS from the UI -- creates .env
                                                    # for you if it doesn't exist yet (still add
                                                    # ANTHROPIC_API_KEY to it by hand afterward).
                                                    # Needed to download the club directory (press 'r'
                                                    # in the club browser) and to read "My Reservations"
cp clubs/club.example.yaml clubs/my-club.yaml      # a favorite's own set-once facts -- coordinates
                                                    # for the weather overlay, course lineup, etc.
                                                    # 'f' in the app writes a minimal version of this
                                                    # for you; copy the template over it for the
                                                    # annotated reference. Availability/weather
                                                    # preferences and the scrape interval are global,
                                                    # not club-specific -- 'e' in the app edits those
python -m src.settings_screen                      # ...or edit those outside the running app
python -m src.scrape_once                          # one-off scrape of every favorite's booking window
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

`tui.py`'s crowd-heatmap screen (`h`) is real, but currently shows a data-readiness
view rather than the colored grid itself — see "Project structure" above for what's
real today versus still a stub.

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
│   ├── club_config.py      # favorites: list/load/save clubs, resolve credentials (implemented)
│   ├── club_directory.py   # locally cached pc caddie club directory + club-id parsing (implemented)
│   ├── global_preferences.py # shared availability/preferences/scrape-interval file, not per-club (implemented)
│   ├── scraper.py          # direct-URL fetch, login, parsing (implemented, verified live)
│   ├── storage.py          # SQLite persistence — scraped sheets + confirmed bookings (implemented)
│   ├── scrape_once.py      # headless scheduled scrape, adjustable per-club interval (implemented)
│   ├── search.py           # exact hard-filtering — party size, time windows, buffer (implemented)
│   ├── recommend.py        # filters via search.py + weather/daylight, ranks via ai_assist (implemented)
│   ├── settings_screen.py  # edit preferences/interval -- pushed from tui.py ('e') + standalone (implemented)
│   ├── club_picker.py      # search pc caddie's directory, add a club -- ClubSearchScreen (pushable from tui.py) + a thin standalone wrapper (implemented)
│   ├── geocode.py          # best-effort weather-location lookup for a new club, via OpenStreetMap (implemented)
│   ├── credentials_screen.py # Textual screen (standalone or pushed): set PCC_USER/PCC_PASS (implemented)
│   ├── env_file.py         # read/write .env KEY=value pairs in place (implemented)
│   ├── translated_footer.py # shared bilingual footer widget, used by every screen (implemented)
│   ├── weather.py          # Open-Meteo rain + wind + sunrise/sunset client (implemented)
│   ├── booking_watch.py    # did a confirmed booking's situation change since you booked it? (implemented)
│   ├── playability.py      # is a tee time playable before sunset? (implemented)
│   ├── calendar_context.py # public holidays + vacation ranges -> day-type tag (implemented)
│   ├── ai_assist.py        # Claude API: booking-label classification, ranking, history summarization (implemented)
│   ├── models.py           # Slot / Schedule / WeatherPoint / SunTimes / ConfirmedBooking / SlotMatch / ...
│   ├── analytics.py        # raw aggregation + crowd heatmap + readiness (implemented)
│   ├── theme.py            # 10 color themes, same set as brew-launcher (implemented)
│   ├── i18n.py             # English/German UI text lookup (implemented)
│   ├── user_config.py      # shared KEY=value config file, used by theme.py + i18n.py (implemented)
│   └── tui.py               # main Textual app: club browser, course picker, multi-day
│                            #   overview, day detail, ad hoc search, heatmap (implemented;
│                            #   heatmap screen currently shows readiness, not the grid yet)
└── tests/
    ├── test_models.py
    ├── test_club_config.py
    ├── test_global_preferences.py
    ├── test_scraper.py
    ├── test_storage.py
    ├── test_scrape_once.py
    ├── test_search.py
    ├── test_recommend.py
    ├── test_settings_screen.py
    ├── test_club_picker.py
    ├── test_geocode.py
    ├── test_club_directory.py
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
Also note: `settings_screen.py` saves its whole file on every save, so any hand-written
comments in it won't survive — the checked-in `club.example.yaml` template itself is
never touched, so it stays available as reference regardless.

Your availability/weather preferences, AI-ranking choice, estimated round duration,
and scrape interval live at `~/.config/teetime-monitor/preferences.yaml` — one shared
file, not per-club (moved there 2026-09-08; previously part of each club's own YAML —
`ai_assist` followed the same day, `round_duration_minutes` the day after, once
turning each on/adjusting it for the first time raised the question of where it
belonged). `location`, `overview_days`, `default_course`, and `identity` stay in
`clubs/*.yaml`, since each of those really is a per-club fact.

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
