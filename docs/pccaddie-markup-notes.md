# pc caddie markup reference (illustrative examples)

Companion to [`../ROADMAP.md`](../ROADMAP.md)'s "Confirmed pc caddie markup reference" —
that section has the narrative and the *why*; this file has concrete example snippets
to write a parser and its tests against, so Phase 1 implementation doesn't need to
re-derive them from scratch. Primary source: the real site 2026-09-05 (club id 0000001,
"Musterhausen"), cross-checked the same evening against 3 other real pc caddie clubs
(Golf Club Segeberg, Golf Club Schloß Klingenburg, Green Eagle Golf Courses) to confirm
`table.pcco-tt-timetable` and `seats-free-N`/`tt-grau` are platform markup, not
Musterhausen-specific — see ROADMAP.md "Cross-club validation" for the full list of
config differences found between clubs (course-selector layout, daylight-display
accuracy, what `.tt-show-hcp` actually holds). Snippets below are reconstructed to
match the confirmed classes/structure — not raw copy-pasted HTML (which would carry
session tokens).

## URLs

```
# Tee sheet for one course/date — confirmed working as a plain GET, no login needed:
https://www.pccaddie.net/clubs/0000001/app.php?cat=tt_timetable_course&date=DAY|2026-09-05&alias=ALIAS|COUB

# All 3 courses, aggregate counts only, one date — good for the Phase 4 overview:
https://www.pccaddie.net/clubs/0000001/app.php?cat=tt_timetable_course_alias&date=DAY|2026-09-05

# Needs login:
https://www.pccaddie.net/clubs/0000001/app.php?cat=reservations       # "My Reservations"
https://www.pccaddie.net/clubs/0000001/app.php?cat=ts_calendar        # tournaments/events
https://www.pccaddie.net/clubs/0000001/app.php?cat=ts_calendar_course # lessons/courses
```

Course aliases confirmed for this club (a different club will likely have different
alias codes, but the same `ALIAS|<code>` shape — check via the page's own `<select
id="timetable_selection_alias">` once logged into that club):

| Display name    | alias code |
|------------------|-----------|
| 18 Loch Tee 1    | `COUB`    |
| 9 Loch Tee 1     | `COU1`    |
| 6 Loch Platz     | `COU6`    |

## Tee sheet table structure

One `<table class="pcco-tt-timetable ...">`, one `<tr class="pcco-tt-time-person">` per
time slot. First `<td>` in each row is the time cell; the class carries the free-seat
count directly:

```html
<!-- Fully open slot: 4 of 4 seats free -->
<td class="seats-free-4 tt-grau"><time class="pcco-tt-timestamp">06:00</time></td>

<!-- 2 of 4 seats booked by anonymized members -->
<td class="seats-free-2 tt-grau"><time class="pcco-tt-timestamp">06:40</time></td>

<!-- Blocked for an event — tt-rot instead of tt-grau -->
<td class="seats-free-4 tt-rot pcco-tt-filter-display"><time class="pcco-tt-timestamp">15:30</time></td>
```

`parse_seats_free()` in `src/scraper.py` extracts the `N` from `seats-free-N` via
regex — already implemented and tested (`tests/test_scraper.py`).

Each of the (up to) 4 player cells that follow has a name span and a handicap span:

```html
<!-- Anonymized member booking, logged in (not a friend) -->
<td>
  <span class="tt-show-name tt-show-male">Occupied</span>
  <span class="tt-show-hcp">Member (16.3)</span>
</td>

<!-- Female member, anonymized (gender only changes the CSS class, not the text) -->
<td>
  <span class="tt-show-name tt-show-female">Occupied</span>
  <span class="tt-show-hcp">Member (20.5)</span>
</td>

<!-- Anonymized, NOT logged in at all — a second, distinct anonymized-state text,
     confirmed identical wording at every club checked (Musterhausen before login,
     plus all 3 other clubs cross-checked). classify_booking_label() should treat
     this the same as "Occupied": label = "anonymized". -->
<td>
  <span class="tt-show-name tt-show-male">Please login to see names</span>
</td>

<!-- Event/lesson/guest/sponsor block — the whole row's cells carry the label instead -->
<td>
  <span class="tt-show-name">FC 110 After Work (E)</span>
</td>

<!-- Advance-booking-window notice — NOT real occupancy, just "can't book this far ahead yet" -->
<td>
  <span class="tt-show-name">Mitglieder 4 Tage im voraus ab 20 Uhr buchbar</span>
</td>

<!-- Hypothetical friend booking (not yet observed on the real site — see ROADMAP.md
     "Known risks"). Expected shape, unconfirmed: -->
<td>
  <span class="tt-show-name tt-show-male">Max Mustermann</span>
  <span class="tt-show-hcp">(12.4)</span>  <!-- no "Member" prefix, unlike the anonymized case -->
</td>
```

Confirmed real label text seen in `.tt-show-name` spans that are **not** a person's
name (feed these as negative examples when testing/prompting
`ai_assist.classify_booking_label()`):

- `"Occupied"` — literal anonymized placeholder
- `"Gäste"` — reserved for guests
- `"Golf Beginner"`, `"Golf Beginner Kurs"` — lesson bookings (from `ts_calendar_course`)
- `"Stadler Business Golf"` — a sponsor/corporate booking
- `"FC 110 After Work (E)"`, `"5. Best Agers"`, `"7. Damengolf Afterwork"` — tournament
  names (from `ts_calendar`, and shown directly in the tee sheet too)
- `"Mitglieder 4 Tage im voraus ab 20 Uhr buchbar"`,
  `"4 Tage im Voraus ab 20 Uhr buchbar (KP)"` — advance-booking-window notices

## "Overview Areas" page structure

One `<table class="... pcco-tt-areas show-table-3">`, one column per course, aggregate
seat icons only:

```html
<i class="fas fa-search-plus"></i>          <!-- zoom/detail control, not a seat -->
<i class="fa fa-ban occupied"></i>          <!-- one booked seat -->
<i class="fa fa-circle-o bookable"></i>     <!-- one free seat -->
```

Count `.occupied` vs `.bookable` icons per row/course to get the aggregate — no names,
no per-slot detail; use the per-course tee sheet above for that.

## Things confirmed absent / not yet confirmed

- No confirmed example of an actual friend's real name in the wild — a scan across all
  5 available days × all 3 courses on 2026-09-05 found none of this account's 4 friends
  with a booking. Re-check once one does.
- The real login form markup — not inspected, to avoid disrupting the user's active
  session. First real task once Phase 1 implementation starts.
