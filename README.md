<h1 align="center">teetime-monitor</h1>

<p align="center">
  <strong>Your club's tee sheet is public. Checking it by hand, over and over, isn't.</strong><br>
  A fast terminal view of a pc caddie club's tee sheet — weather, crowd history, and your own
  booking rules layered on top, refreshed in the background so you don't have to.
</p>

<p align="center">
  <a href="https://github.com/ltdan-88/teetime-monitor/releases"><img alt="Version" src="https://img.shields.io/github/v/tag/ltdan-88/teetime-monitor?label=version&color=89b4fa"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-a6e3a1"></a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux-cba6f7">
  <img alt="Languages" src="https://img.shields.io/badge/UI-English%20%7C%20Deutsch-f9e2af">
</p>

<p align="center">🇬🇧 <strong>English</strong> · <a href="README.de.md">🇩🇪 Deutsch</a></p>

<p align="center"><img src="assets/en/overview.png" alt="The multi-day overview: weather, occupancy, events, and a Pick column, with a booking-change banner at the top"></p>

## Why this exists

pc caddie's own web view works fine — the problem is checking it. A slot near your
existing booking fills in, the forecast for your round gets worse, or something
opens up three weeks out — none of that shows up unless you happen to look, in a
browser, again.

`teetime-monitor` mirrors your club's tee sheet into a terminal table that refreshes
itself in the background, adds weather/daylight/crowd context the site itself
doesn't show, and tells you when something about a booking you already made
changes — no browser tab left open, no page to remember to reload.

## Quick start

```bash
brew install ltdan-88/teetime-monitor/teetime-monitor
teetime-monitor
```

That's it — opens on the club browser (or straight back on whichever club/course
you had open last, once you've picked one before). Type a club id, paste its
booking link, or search once you've fetched the directory, and you're on its tee
sheet.

**Requirements:** macOS or Linux · [Homebrew](https://brew.sh/) · a one-time
Playwright Chromium download (only needed for logging into pc caddie itself —
reading the public tee sheet never does). A pc caddie login is optional: it's only
for downloading the searchable club directory and reading your own confirmed
reservations automatically — a typed-in club id, favorites, and the tee sheet
itself all work without one. Optional: an [Anthropic](https://www.anthropic.com/)
API key, only if you turn on AI-ranked recommendations (off by default).

## What you get

### The multi-day overview

The home screen once you're on a club: one row per day it's actually taking
bookings for right now — real weather, a six-block heat strip for how full
08:00–20:00 is, that day's own events/closures, and a **Pick** — a confirmed
booking, the recommended time, or why nothing qualifies.

**Enter** expands a day in place into its own per-slot rows; **enter** again on a
slot confirms it — or, if it's already your confirmed booking, offers to cancel it
locally instead.

<p align="center"><img src="assets/en/expanded.png" alt="A day expanded in place into its own per-slot rows, showing occupancy for each tee time"></p>

### Weather & playability

[Open-Meteo](https://open-meteo.com/), no API key needed, split into its own
Condition / Temperature / Precipitation / Wind columns — real numbers always
visible, not hidden behind an icon until some threshold is crossed. A 🌙 marks any
tee time that wouldn't finish before dark, based on your own estimated pace for a
9- or 18-hole round.

### It watches bookings you already made

Confirmed reservations are read automatically from pc caddie's own "My
Reservations" page — teetime-monitor never books or cancels anything on the real
site. If something about one changes — someone joins your flight, a neighboring
slot fills in and shrinks your buffer, the forecast for that day gets worse — a
banner shows up next time you open the app (see the one at the top of the overview
screenshot above). **x** dismisses it.

### Search for one-off criteria

Your saved availability covers the usual case; **Search** (from Actions) is for the
exception — "just this once, 3 players, after 15:00" — pre-filled from your saved
defaults so you're tweaking one thing, not typing everything from scratch. Checked
against every day already loaded, no fresh scrape, with the same weather/daylight
sanity check and optional AI ranking the automatic picks use.

<p align="center"><img src="assets/en/search.png" alt="The search screen, pre-filled from saved availability, showing five matching Saturday tee times"></p>

### Your own rules, applied automatically

Set your standing availability once — party size, weekday/weekend time windows,
buffer to nearby flights — and matching slots get a ★ automatically on the
overview, no need to search every time. Global, not per-club: your own
availability and weather comfort don't change depending on which course you're
checking.

Turn on **AI-ranked recommendations** (Settings → AI ranking) to have Claude pick
the best of an already-filtered shortlist instead of just the earliest one that
clears your rules. Off by default — it's a real, paid API call per recommendation,
not just a free quality bump. Settings also covers your estimated pace for 9/18
holes and the scrape interval, grouped into collapsible sections instead of
hand-edited YAML.

<p align="center"><img src="assets/en/settings.png" alt="The settings screen: Availability and Weather groups, with real values already filled in"></p>

### A crowd heatmap

Historical occupancy grouped by actual weekday, plus a separate comparison for
tournament/public-holiday/vacation days, so a future vacation-week Monday gets
compared against other vacation days, not typical Mondays. A readiness table
(how many hours of history each weekday/day-type has) sits above the actual
colored grid — hour-of-day as rows, weekday or day type as columns, a full-color
block once an hour has enough samples to trust, the same block dimmed while it's
still thin, blank where nothing's been scraped yet.

<p align="center"><img src="assets/en/heatmap.png" alt="The crowd heatmap: readiness tables plus the colored occupancy grid, by weekday and by special day type"></p>

### One menu ties it together

Press **t** (or **ctrl+p**) for **Actions**: **Find a club** (search the whole pc
caddie directory, or jump straight to a club id), **Search**, **Heatmap**, and
**Settings** — plus Theme, Language, and Textual's own utilities, all fully
translated and arranged with this app's own actions first.

<p align="center"><img src="assets/en/actions.png" alt="The Actions menu open: Find a club, Search, Heatmap, and Settings, fully translated"></p>

Two inline dropdowns above the table switch between clubs/courses you've already
favorited without opening any menu at all — Actions is for finding a club you
haven't saved yet, or reaching the things that don't need a key of their own.

### Bilingual, themed

Every screen — table headers, footer key hints, banners, the Actions menu itself —
works in English or German, switchable anytime from Actions. Defaults to German if
your system locale looks German. Ten color themes (the same palette set
[`brew-launcher`](https://github.com/ltdan-88/brew-launcher) uses), switchable the
same way.

## Reference

| Key | Action | Where |
|---|---|---|
| **enter** | Expand a day in place / confirm or cancel the highlighted tee time | Overview |
| **r** | Force-refresh the whole loaded window right now, bypassing the usual interval | Overview |
| **x** | Dismiss booking-change banners | Overview |
| **t** / **ctrl+p** | Open **Actions** — Find a club, Search, Heatmap, Settings, Language, Theme, and Textual's own utilities | Overview |
| **q** | Quit | everywhere |
| **escape** | Back — returns to Actions if that's where the current screen was opened from, otherwise to the overview | any screen opened from Actions |
| **f** | Toggle favorite on the highlighted club | Club browser |
| **r** | Refresh the cached club directory | Club browser |
| **l** | Set up or edit your pc caddie login | Club browser |
| **c** | Confirm the highlighted search result | Search |

`teetime-monitor --version` (or `-v`) prints the installed version and exits — it
also shows in the app's own header the whole time it's running.

## Configuration

Nothing here is required — `brew install` + `teetime-monitor` works with zero
setup. Expand this for scheduled background scraping, per-club facts, and where
everything is stored.

<details>
<summary><strong>Show configuration details</strong></summary>

Like `terraform`/`docker-compose`, this reads its own state from whatever
directory you run it in — pick one and always launch it from there.

```
.env                                          # PCC_USER / PCC_PASS / ANTHROPIC_API_KEY -- gitignored
clubs/<your-club-id>.yaml                     # per-club: location, overview_days, default_course, identity
~/.config/teetime-monitor/preferences.yaml    # availability/weather rules, AI ranking, round pace, scrape interval -- global
~/.config/teetime-monitor/config              # THEME=, LANG= -- also global
```

`python -m src.credentials_screen` sets `PCC_USER`/`PCC_PASS` from the UI (creates
`.env` from `.env.example` if you don't have one yet — still add
`ANTHROPIC_API_KEY` by hand afterward). `r`/`l` in the running app's club browser
open the same screen inline, right when it's needed. One pc caddie login covers
every club under the same account — the rarer per-club override
(`PCC_USER__<club-id>`) is documented in `.env.example`.

`f` in the app writes a minimal `clubs/<id>.yaml` for you; copy
`clubs/club.example.yaml` over it for the fully annotated version (weather
coordinates, public-holiday country code, hand-entered vacation ranges). Standing
availability, AI ranking, and scrape interval are edited from **Actions →
Settings** (or `python -m src.settings_screen` standalone) — one shared file, since
none of that actually varies by club.

### Keep history building while you're not looking

The running app scrapes automatically — once on open, and periodically while it
stays running — but pc caddie hides past tee sheets entirely, so any day nobody
opens the app is a permanent gap otherwise. To also scrape unattended (macOS, via
`launchd`, checking every 15 minutes and self-throttling per club's own configured
interval):

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

### From source instead

```bash
pip install -e .
python -m src.tui
```

</details>

## Project structure

<details>
<summary><strong>Show the module layout</strong></summary>

```
teetime-monitor/
├── README.md / README.de.md
├── ROADMAP.md                    # full phase-by-phase build history
├── pyproject.toml
├── .env.example
├── clubs/
│   └── club.example.yaml         # template -- copy per real club (real ones are gitignored)
├── docs/
│   ├── spec-v1.md                # original single-session spec (historical)
│   └── pccaddie-markup-notes.md  # example HTML snippets for the real site's markup
├── src/
│   ├── tui.py                    # the app itself -- club browser, overview, search, heatmap, settings
│   ├── scraper.py                # direct-URL fetch, login, tee-sheet parsing
│   ├── scrape_once.py            # scheduled scrape, per-club interval, "My Reservations" sync
│   ├── storage.py                # SQLite persistence
│   ├── search.py / recommend.py  # hard filters, then weather/daylight + AI ranking
│   ├── ai_assist.py              # the three Claude API calls (classification, ranking, summarization)
│   ├── weather.py                # Open-Meteo client
│   ├── booking_watch.py          # did a confirmed booking's situation change?
│   ├── playability.py            # is a tee time playable before sunset?
│   ├── analytics.py              # crowd heatmap + readiness
│   ├── calendar_context.py       # public holidays + vacation ranges -> day-type
│   ├── settings_screen.py        # shared preferences screen (pushed from the app, or standalone)
│   ├── credentials_screen.py     # shared login screen (pushed from the app, or standalone)
│   ├── club_config.py            # favorites: load/save clubs/*.yaml
│   ├── club_directory.py         # cached pc caddie club directory + id parsing
│   ├── geocode.py                # best-effort weather-location lookup for a new club
│   ├── global_preferences.py     # shared availability/AI/pace/interval file
│   ├── theme.py / i18n.py        # 10 color themes; English/German UI text
│   ├── user_config.py            # shared THEME=/LANG= config file
│   ├── units.py                  # metric/imperial display conversion
│   ├── env_file.py                # read/write .env in place
│   ├── translated_footer.py      # shared bilingual footer widget
│   └── models.py                 # Slot / Schedule / WeatherPoint / ConfirmedBooking / ...
└── tests/                        # one file per module above, plus test_tui.py
```

</details>

## Troubleshooting

**"No tee sheet found" for a club I know is real.** Some clubs simply don't
publish one through pc caddie — `scrape_once`/the overview both say so cleanly
rather than erroring. Double-check the club id against its own booking link.

**Weather looks off, or missing.** The club's coordinates come from a best-effort
Nominatim search on the club's name, cached after the first lookup — not always
the exact clubhouse pin. Edit `location:` in `clubs/<id>.yaml` by hand for an exact
fix.

**AI-ranked recommendations aren't doing anything.** They're off by default
(Settings → AI ranking) and need `ANTHROPIC_API_KEY` set in `.env` either way —
without a key, turning the setting on will just fail quietly on the next
recommendation.

**A confirmed booking isn't showing up.** It's read from pc caddie's own "My
Reservations" page on each scheduled scrape, not in real time — press `r` (Refresh)
on the overview to force one immediately. Cancelling on the real site is
recognized the same way, automatically, next sync.

**Nothing happens the first time I open a club — is it stuck?** The club
directory and the tee sheet itself both need a live fetch the first time; a slow
connection or a cold pc caddie server can make that first load take a few seconds.
`Refreshing…` in the top-right shows it's actually working.

## Credentials & data

`.env` is gitignored — `PCC_USER`/`PCC_PASS`/`ANTHROPIC_API_KEY` are never
hardcoded or sent anywhere except pc caddie's own login form and Anthropic's API
respectively. One pc caddie login covers every club saved under the same account.
Per-club files under `clubs/` are gitignored too, aside from the tracked
`club.example.yaml` template — only `location`, `overview_days`, `default_course`,
and `identity` actually live there; everything else (availability, AI ranking,
scrape interval, theme, language) is shared and global, described under
[Configuration](#configuration) above.

## License

[MIT](LICENSE)
