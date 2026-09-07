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
accuracy, what `.tt-show-hcp` actually holds). A second pass (2026-09-06), writing and
then actually running `src/scraper.py` against the live site, found the row-level
`data-*` attributes below and two more label/status variants — see "Row-level
`data-*` attributes" and the updated label table further down. Snippets below are
reconstructed to match the confirmed classes/structure — not raw copy-pasted HTML
(which would carry session tokens).

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
regex — implemented and tested, but now a documented *fallback* only (see below).

### Row-level `data-*` attributes (found 2026-09-06, primary source)

The `<tr class="pcco-tt-time-person">` itself carries clean, structured attributes —
found while actually writing `src/scraper.py`'s parser, not the earlier browser-based
research pass, and a more robust source than parsing the time cell's `seats-free-N`
class string:

```html
<tr class="pcco-tt-time-person" data-time="06:40" data-status="bookable"
    data-seat_bookable="2">
  ...
</tr>
```

- `data-time` — the slot's time, directly (`"06:40"`), no need to re-parse the
  `<time class="pcco-tt-timestamp">` text inside the first `<td>`.
- `data-seat_bookable` — the free-seat count as a plain integer. Preferred over
  `seats-free-N`; `parse_seats_free()` stays only for a row that's somehow missing this
  attribute.
- `data-status` — one of four confirmed values:
  - `bookable` — at least one seat free
  - `occupied` — fully booked
  - `block-time` — an event/lesson/guest/sponsor block (row's `.tt-show-name` carries
    the block's label, e.g. a tournament name)
  - `disable-time` — an "advance booking window" notice (e.g. "4 Tage im Voraus ab 20
    Uhr buchbar") — **not real occupancy**, just "not bookable yet." Found live
    2026-09-06 during a full 5-day x 3-course sweep, after this exact label had
    initially slipped through and been miscounted as a real player name. `block-time`
    and `disable-time` are handled identically by `_parse_slot_row()` — both become
    `Slot.block_reason`, never a fake player.

### Colspan-merged empty seats

Free/empty player positions in a row aren't rendered individually — pc caddie merges
them into one trailing `<td colspan="N">` holding a single *empty* `.tt-show-name`
span:

```html
<!-- 2 of 4 seats booked, 2 free -->
<tr class="pcco-tt-time-person" data-time="06:40" data-status="bookable" data-seat_bookable="2">
  <td class="seats-free-2 tt-grau"><time class="pcco-tt-timestamp">06:40</time></td>
  <td><span class="tt-show-name tt-show-male">Belegt</span>
      <span class="tt-show-hcp">Member (16.3)</span></td>
  <td><span class="tt-show-name tt-show-female">Namensanzeige nach dem Login</span>
      <span class="tt-show-hcp">Member (20.5)</span></td>
  <td colspan="2"><span class="tt-show-name"></span></td>
</tr>
```

`_parse_slot_row()` just iterates every `.tt-show-name` span and skips the blank one —
no colspan arithmetic needed to figure out how many empty seats that trailing cell
represents.

Each of the (up to) 4 player cells that follow has a name span and a handicap span:

```html
<!-- Anonymized member booking, logged in (not a friend), EN locale -->
<td>
  <span class="tt-show-name tt-show-male">Occupied</span>
  <span class="tt-show-hcp">Member (16.3)</span>
</td>

<!-- Same, but the server's default (DE) locale short form — this variant only
     surfaced during an actual end-to-end run against the live site (2026-09-06), not
     the earlier browser-based research pass, which had EN selected. -->
<td>
  <span class="tt-show-name tt-show-female">Belegt</span>
  <span class="tt-show-hcp">Member (20.5)</span>
</td>

<!-- Same idea, DE locale long form -->
<td>
  <span class="tt-show-name tt-show-male">Namensanzeige nach dem Login</span>
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
`ai_assist.classify_booking_label()`); `src/scraper.py`'s `KNOWN_ANONYMIZED_LABELS`
covers the first four (the real anonymized-placeholder variants) exactly:

- `"Occupied"`, `"Belegt"`, `"Namensanzeige nach dem Login"`,
  `"Please login to see names"` — anonymized-placeholder text, four confirmed
  variants (two locales x logged-in/not) — see "Row-level `data-*` attributes" above
- `"Gäste"` — reserved for guests
- `"Golf Beginner"`, `"Golf Beginner Kurs"` — lesson bookings (from `ts_calendar_course`)
- `"Stadler Business Golf"` — a sponsor/corporate booking
- `"FC 110 After Work (E)"`, `"5. Best Agers"`, `"7. Damengolf Afterwork"` — tournament
  names (from `ts_calendar`, and shown directly in the tee sheet too)
- `"Mitglieder 4 Tage im voraus ab 20 Uhr buchbar"`,
  `"4 Tage im Voraus ab 20 Uhr buchbar (KP)"` — advance-booking-window notices
  (`data-status="disable-time"` on the row — see above)

A full sweep of every date/course the live site offered on 2026-09-06 (5 dates x 3
courses, 1092 slots total) found exactly these 7 block/event reasons and zero other
non-name text — i.e. the negative-example list above is not just illustrative, it's
now confirmed exhaustive for this club as of that date.

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

## Login form (confirmed 2026-09-06)

A plain HTML `<form>`, no JavaScript, no CSRF token — inspected live while the user
was logged in themselves; Claude never entered or saw a real password to confirm this:

```html
<form method="post" action="/clubs/<club_id>/app.php?cat=start">
  <input type="hidden" name="service" value="login">
  <input type="text" name="rq[login]">
  <input type="password" name="rq[password]">
</form>
```

A failed attempt re-renders a page still containing the `rq[password]` field name — a
reliable success/failure signal without needing to match error-message text (which
would also need a language variant, unlike this).

## "My Reservations" page structure (confirmed 2026-09-06/07)

One `<table class="table table-bordered table-striped table-condensed cf
meine-buchungen">`, header row of `<th>`s, then one `<tr>` of `<td>`s per booking.
Confirmed against a real demo booking:

```html
<tr>
  <td>Mon, 2026-09-07, 19:50 o'clock<br>Golfclub Domäne Musterhausen<br>6 Loch Platz</td>
  <td>Mustermann, Max *<br></td>
  <td><!-- "Save to calendar" button, "Show"/"Cancel" links --></td>
</tr>
```

German equivalent's Details cell: `Mo, 07.09.2026, 19:50 Uhr<br>...` — same club/course
lines, only the date/time line's format differs (`DD.MM.YYYY` + "Uhr" instead of
already-ISO + "o'clock"). The course name (last line) is always exactly one of
`COURSE_ALIASES`'s own keys. The Persons cell's "*" (seen on the account's own name)
isn't otherwise explained anywhere on the page — not parsed, since `ConfirmedBooking`
has no players field to put it in. Empty state (no bookings at all) shows plain page
text "No bookings found." (English) / "Keine Buchungen gefunden." (German, not directly
observed but handled defensively), no table at all.

## Things confirmed absent / not yet confirmed

- No confirmed example of an actual friend's real name in the wild — a scan across all
  5 available days × all 3 courses on 2026-09-05 found none of this account's 4 friends
  with a booking. Re-check once one does.
- What a multi-person booking's Persons cell looks like beyond the single-person case
  above (the demo booking was solo) — presumably each person on their own line,
  matching the booking flow's "Person 1"/"Person 2"/etc., but not yet seen rendered
  back on this page.


## Cross-club findings (2026-09-07, 79 real clubs)

See ROADMAP.md "Cross-club validation sweep" for the full table. The two structural
rules worth having here, since they're what a parser actually needs to get right:

### A seat is a `<td>` without `colspan`; the merged cell is not a seat

pc caddie renders each genuinely occupied seat as its own `<td>` (no `colspan`), then
merges whatever seats are still free into one trailing `<td colspan="N">`. That merged
cell is frequently **not** empty — it carries a course note. Reading every
`.tt-show-name` as a player turns those notes into fabricated player names, which
happened on 27 of 45 clubs checked.

```html
<!-- 2 seats taken, 2 free, and a club note in the merged free cell -->
<tr class="pcco-tt-time-person" data-time="08:20" data-status="past-time" data-seat_bookable="2">
  <td class="seats-free-2 tt-grau"><time>08:20</time></td>
  <td><span class="tt-show-name">Namensanzeige nach dem Login</span></td>
  <td><span class="tt-show-name">Namensanzeige nach dem Login</span></td>
  <td colspan="2"><span class="tt-show-name">Nur für Mitglieder</span></td>
</tr>
```

Real examples seen in that merged cell: `"Nur für Mitglieder"`, `"Platzpflege"`,
`"Keine Startzeit erforderlich!"`, `"Blocco"`, `"Mo bis Do keine Startzeiten nötig"`,
`"Course maintenance"`, `"Kurzfristige Carbuchung online nicht möglich. Ab Vortag 17 Uhr"`.

Anonymized placeholders come in **four languages, two forms each** — all eight must be
recognized or they read as real names:

| Language | Long form | Short form |
| --- | --- | --- |
| German | `Namensanzeige nach dem Login` | `Belegt` |
| English | `Please login to see names` | `Occupied` |
| French | `Veuillez faire le login pour visualiser les noms` | `Occupe` |
| Italian | `Per visualizzare i nomi bisogna fare il login` | `Occupato` |

### Not every club has an "Area" selector, or a tee sheet at all

18 of the 39 clubs with a working tee sheet have no `<select id="timetable_selection_alias">`
whatsoever — they run one course, addressed by omitting the `alias` query parameter
entirely. A further 7 clubs publish no `table.pcco-tt-timetable` at all (online booking
not offered); a club can even have the course selector *and* no timetable behind it, so
"does this club have a tee sheet" has to be answered from the table, not the selector.

### Other per-club variation

- `<select id="timetable_selection_date">` lists exactly the bookable days: **1 to 31**
  across the sample. Requesting a date outside it returns a page with no timetable and a
  "Selection invalid." notice.
- The header row's first cell is localized (`Zeit` / `Ora` / `Heure`), but the seat
  columns are always `- 1 -`, `- 2 -`, … — a locale-independent way to count seats per
  slot (4 on every club checked).
- `data-seat_bookable` can be **negative** on an over-full slot (`-1`, `-12` observed),
  so it needs clamping to the real seat range.
- `data-status="past-time"` is a fifth value beyond the four originally documented, and
  by far the most common one on any given page. It parses like a normal row.
