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

## What it deliberately doesn't do

No scraping (beyond shelling out to the existing scraper binary), no login, no real
booking on pc caddie itself, no search, no heatmap, no i18n, no theming of its own.
