# teetime-monitor — macOS Swift prototype

A deliberately small SwiftUI prototype of the overview screen, built to answer one
question: **what would a native macOS version feel like, and what would it cost?**

Not a rewrite. Not shipped. Not wired into the Homebrew formula.

## What it does

Shows the multi-day overview — one card per bookable day, with the noon forecast, the
six-bucket occupancy heat strip, day events, and your confirmed booking. Click a day to
expand its tee times in place: seat pips, free count, per-slot weather, your own slot
flagged, and post-sunset slots dimmed.

## The shortcut that makes it cheap

**It does no scraping at all.** It opens the SQLite database the Python scraper already
maintains, read-only, and renders it. The launchd agent keeps working exactly as it
does today; this is a second reader of the same data.

That is why it's ~400 lines instead of ~5,000. It deliberately sidesteps the entire
expensive half of a real rewrite — the scraper, the login, the parsing rules, the
weather and calendar fetches, the recommendation pipeline — all of which stay in
Python. Treat that as the prototype's main finding, not a detail: a hybrid like this is
genuinely viable, and is far cheaper than porting the backend.

One piece of real logic *is* mirrored rather than skipped: the weather fallback from
v0.30.1 (when the newest scrape has no weather, fall back to the most recent earlier
scrape of the same course/date that does). Without it the prototype would show the same
blank column the Python app used to.

## Build and run

Needs **only the Command Line Tools** — no Xcode, no Swift Package Manager, no
dependencies:

```bash
./build.sh
open TeetimeMonitor.app
```

It reads `~/.local/share/teetime-monitor/<club_id>.db` — the same fixed location the
Python side uses since v0.31.0 (`src/paths.py`), honouring `TEETIME_MONITOR_DATA_DIR`
the same way. That shared convention is what makes the GUI possible at all: an app
launched from Finder gets `cwd = "/"`, so nothing working-directory-relative could
ever be found.

Point it at a copy instead with `--db`:

```bash
./TeetimeMonitor.app/Contents/MacOS/TeetimeMonitor --db /path/to/0497758.db
```

## What building it actually taught us

- **`@State` needs Xcode.** It's a macro now, and `SwiftUIMacros` ships with Xcode, not
  the Command Line Tools. A static SwiftUI view compiles fine without it; the moment
  you add state, it doesn't. The workaround used here is the older, macro-free
  `ObservableObject` / `@Published` / `@StateObject` trio — identical behaviour, builds
  with plain `swiftc`. `@Observable` also works (its macro plugin *is* bundled).
- **A double-clickable `.app` needs no Xcode either** — a hand-written `Info.plist`, a
  directory layout, and ad-hoc `codesign` are enough. See `build.sh`.
- **SQLite needs no dependency** — `import SQLite3` is in the macOS SDK.
- **Distribution wouldn't need notarization**, because the Homebrew formula builds from
  source; a Swift version could do the same with `swift build`.

## Tier 1: made productive (2026-09-18)

Preferences, Settings (minus login), confirm/cancel a booking, and banner
notifications -- all without a single Python change, because none of them ever
needed pc caddie: they're local file/SQLite edits the Python side already owns the
shape of.

- **Preferences & Settings** read and write the real `preferences.yaml` and
  `~/.config/teetime-monitor/config` directly. `YAML.swift` is a small hand-written
  codec scoped to this file's exact shape (nested maps of scalars, no lists) --
  verified byte-for-byte round-trip against a real saved file, both directions
  (Swift reads what Python wrote; Python reads what Swift writes).
- **Confirm/cancel** writes a `confirmed_bookings` row exactly like
  `storage.save_confirmed_booking()` does -- append-only, `source: "manual"`,
  `holes` derived the same leading-digits way `scraper._holes_from_course_label()`
  does. A confirming dialog on tap, not a silent write, matching why
  `ConfirmBookingScreen`/`CancelBookingScreen` exist on the Python side: this marks
  a *local* record of what you already booked on pc caddie's own site, not a real
  booking action.
- **Banners** read `booking_changes.message` -- the plain-English fallback that
  table's own schema comment says exists "for any non-TUI consumer." Deliberately
  not `i18n.render_booking_change()`'s kind+params re-rendering, which is real
  per-language logic this prototype doesn't reimplement.

A real, live notification surfaced during this work: an actual "1 more player
joined your tee time" banner had been sitting unseen in this developer's own
database the whole time, with no way for any front end to show it until this.

**Two real bugs caught before shipping**, both from testing against copies of real
data rather than trusting the code:
- Writing an *empty* time window (`{}`) instead of omitting the key entirely would
  have silently turned "no weekend rules configured" into "any weekend time is
  fine" -- confirmed by reading `recommend.default_criteria_from_config()`'s own
  `_window()` closure, which treats an absent key and a present-but-empty one as
  genuinely different outcomes.
- The `KEY=value` writer grew one blank line on every single save (a `split` vs.
  Python's own `splitlines()` mismatch on a trailing newline) -- caught by writing
  the same key five times and diffing the byte count, not by inspection.

## What's still Tier 2 (needs a Python subcommand)

Login/credentials (a real `scraper.login()` call), search (running
`recommend.ranked_matches()`'s actual ranking), add-a-club (the platform directory
search, also needs login), and the heatmap (porting or exposing
`analytics.crowd_heatmap()`'s aggregation). None of these are local file edits --
each is real logic that has to stay in Python, reached the same way `--force`
already is: a small, well-scoped console-script addition, not a reimplementation.

## Polish round (2026-09-18): live theming, sunrise/sunset, full weather

Four direct remarks after using Tier 1:

1. **"m" for minutes is ambiguous with meters.** Every Stepper label in Preferences
   now spells out "min" — matches Python's own `settings_screen.py` labels, which
   spell "(minutes)" out in full rather than abbreviating at all.
2. **"Do theme changes work, and can it not need a relaunch?"** They didn't apply to
   this app at all before this — Settings only ever wrote `THEME=` to the shared
   config file for the *TUI* to pick up next launch. New `Theme.swift` gives the
   Swift app its own live rendering of all 10 themes (`AppTheme`, a singleton
   `ObservableObject` every themed view observes) — picking a theme and hitting Save
   redraws the running window immediately, no relaunch. The three brew-launcher
   originals (green/amber/red-sands) use the *exact* hex values from `theme.py`'s
   own `CUSTOM_THEMES`; the seven Textual built-ins aren't defined in this repo at
   all (Textual's own registry owns them), so those use each palette's own
   well-known published colors instead — close to what the TUI renders, not a
   byte-for-byte extraction of it.
3. **Sunrise/sunset now show two ways**, both mirroring `tui.py` exactly: a compact
   "↑07:06 ↓19:29" on the collapsed day row, and — the specific slot row nearest
   each one — a labeled marker, using the identical `_closest_slot_time()` logic
   including its earlier-wins tie-break. Found and fixed while wiring this up: the
   expanded view's own 07:00–19:30 row clip would have silently hidden the sunrise
   marker on any day sunrise falls earlier than 07:00 (it was 06:51 as of
   2026-09-08) — the clip now always keeps whichever row carries a marker.
4. **Precipitation, wind and day-level condition were genuinely missing**, not just
   unstyled — the data was already parsed and sitting in `WeatherPoint`, never
   rendered. Every slot row now shows rain% (🌧 above 50%) and wind speed (💨 above
   30kph), the same thresholds `tui._slot_precipitation_cell()`/`_slot_wind_cell()`
   use. The collapsed day header now shows the actual day-level summary
   (`tui._condition_cell()`'s "worst icon across daytime", `_temperature_cell()`'s
   high/low, `_precipitation_cell()`'s average, `_wind_cell()`'s peak) instead of
   whatever the forecast happened to say at noon.

## Labels, and what actually needs a TUI restart (2026-09-18)

Two more direct remarks after the polish round above:

1. **Some columns/fields had no label at all** — the day header's temp/rain/wind
   figures were bare numbers with no unit or icon (unlike wind, which already had
   one), and the expanded slot row's rain%/wind cells were the same. Fixed by giving
   every one of those its own icon (`Label`, not bare text — temp gets
   `thermometer.medium`, rain gets `drop.fill`, matching the icon wind already had)
   plus a `.help()` tooltip for the exact figure on hover. Added a `LegendLine`
   below the day list, one line for the whole window rather than repeated per card —
   the same role and placement `tui.py`'s own `OVERVIEW_LEGEND` plays under the
   TUI's table, for the same reason: icons that "seemed obvious" while building them
   aren't obvious to someone opening the app cold.
2. **Which settings actually need a TUI restart, checked against the source rather
   than assumed:**
   - **Preferences (availability, weather thresholds, buffers, pace, priorities) and
     Settings' Units/AI/scrape-interval fields are already live in a running TUI —
     no restart, no need to even reopen its own Settings screen.** `tui.py`'s
     `_resolved_config()` calls `global_preferences.load_preferences()` fresh,
     uncached, on every single render — this was already true of the codebase
     before any of this work, not something added here. Both sheets now say so
     explicitly instead of leaving it to be assumed.
   - **Theme and language are the one place that's genuinely different**, and do
     need an actual restart — not just reopening Settings within the same running
     TUI session. `i18n.get_language()` resolves once per process and caches
     (`_current_language`), never re-reading the file after that; `club_config.py`
     calls `load_dotenv()` once at import time for `.env` credentials, same
     pattern. Confirmed this isn't fixed by simply reopening the TUI's own Settings
     screen either: its Theme field's `getter` *does* re-read disk, but the
     `setter` that actually repaints `app.theme` only fires when the picked value
     differs from what the getter returns — so an unchanged reselection (which is
     what reopening-without-touching-anything amounts to) applies nothing. Fixed
     `SettingsSheet`'s messaging to say "next restart" specifically rather than the
     vaguer, easy-to-misread "next time it opens."

## What it deliberately doesn't do

No scraping (beyond shelling out to the existing scraper binary), no login, no real
booking on pc caddie itself, no search, no heatmap, no i18n of its own (theme is
now live; language still only affects the TUI, next launch).
