"""Headless, no-TUI scrape-and-store — meant to run on a schedule (cron/launchd).

Exists because pc caddie hides past tee sheets: any day nobody opens the TUI is a gap in
history that can never be filled in later.

`run()` scrapes one club/course/date's tee sheet and saves it via storage.py — always
real, no login needed for this part.

**Login (real as of 2026-09-06, once the actual form was inspected live — see
scraper.py's `login()`)**: `scrape_due_for_club()` logs in and syncs "My
Reservations" into `confirmed_bookings`, via `_sync_my_reservations()` below —
called there, once per pass, rather than from `run()` (moved 2026-09-16, once a
real booking traced live showed the old per-course/date call site logging in up
to a dozen-plus times for the exact same page in a single pass; see
`scrape_due_for_club()`'s own docstring). Every failure mode there is
best-effort, not fatal, since this must not stop an unattended run over one club:
no slug resolved for this `club_id` (can't look up credentials without it), no
`PCC_USER`/`PCC_PASS` configured yet, a `scraper.LoginError` (wrong credentials), or a
`NotImplementedError` from `scrape_my_reservations()` itself (a real booking exists
but its row markup isn't parseable yet — see that function's own docstring for why), or
anything else (offline, a timeout, a 5xx), reported as reason "other".
The last two aren't *silent* any more either — see `_sync_my_reservations()`'s own
docstring for the real gap found live (a `print()` nobody sees while the TUI has
the screen) and the `OverviewScreen` banner that now replaces it.

**Weather (added 2026-09-06, alongside making weather.py's fetch calls real)**: `run()`
also fetches the day's hourly forecast and sun times, using the club's YAML `location`
block, and attaches them to the schedule before it's saved — this is what actually
makes `recommend.exclude_unplayable()` and `booking_watch.check_for_changes()`'s
weather checks see real data instead of always getting `None` back. Skipped
(not fatal) if `location` isn't filled in yet (still the `0.0, 0.0` placeholder from
club.example.yaml — "null island," not a real course) or the request itself fails —
occupancy is still the primary thing this scrape is for, and a missing/late weather
overlay for one course/date shouldn't take that down.

**Adjustable scrape interval (added 2026-09-06, after feedback that once/twice-daily
was too infrequent, especially for a date you've actually booked)**: `main()` now
checks `_should_scrape()` before re-scraping a given course/date, using each club's
`scrape_interval_minutes` (normal) / `scrape_interval_minutes_booked` (shorter, once a
confirmed booking exists for that date — freshness matters more once there's something
to protect, see booking_watch.py) from its YAML. This flips the intended cron cadence:
fire this job *often* (e.g. every 15-30 min) and let it decide per course/date whether
a re-scrape is actually due, rather than tuning the cron schedule itself to match the
desired interval:

    */15 * * * * cd /path/to/teetime-monitor && .venv/bin/python -m src.scrape_once

`main()` loops every saved club (club_config.list_clubs()) via `scrape_due_for_club()`
(one club, every course x every day in its `overview_days` window) — so one cron
entry with no arguments covers everything currently configured, throttled per
course/date as above.

Installed as a real `launchd` job on 2026-09-07 (`~/Library/LaunchAgents/
com.teetimemonitor.scrape.plist`, firing every 15 minutes via `StartInterval`,
`_should_scrape()` still throttling what's actually fetched) — the standing,
persistent change every earlier version of this note left for "the user's own call"
has now actually been made. `tui.py` also calls `scrape_due_for_club()` directly for
whichever club it's showing — once on open and again on a timer while it stays
running — so a cron/launchd job isn't the only way this happens either; see that
module's own "Auto-refresh" docstring note. Between the two, history keeps
accumulating whether or not the TUI is ever opened on a given day, closing out the
"history can't be backfilled" risk this project has flagged since Phase 1 was first
scoped.

**Booking windows (2026-10-05)**: a day whose latest scrape was entirely "N Tage im Voraus
ab 20 Uhr buchbar" notices (booking_window.py) is due as soon as that opening time has
passed since the scrape -- so the 15-minute agent picks a newly opened day up within one
pass instead of waiting out `scrape_interval_minutes` -- provided the scrape is at least
`MIN_SCRAPE_AGE_AFTER_OPENING_MINUTES` old, so a day that stays "locked" can't loop.
"""

import argparse
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import date as date_cls
from pathlib import Path

import httpx

from . import booking_watch, booking_window, club_config, global_preferences, paths, storage
from . import weather as weather_module
from .models import ConfirmedBooking, SunTimes, WeatherPoint
from .recommend import _round_duration_minutes
from .scraper import (
    LoginError,
    NoTeeSheetError,
    fetch_available_dates,
    fetch_course_aliases,
    login,
    scrape_my_reservations,
    scrape_schedule,
)
from .search import resolve_buffer_minutes

DATA_DIR = paths.DATA_DIR  # ~/.local/share/teetime-monitor -- see paths.py

# Upper bound on how many days one pass will scrape, however many the club itself
# advertises — see scrape_due_for_club(). One real club offers 366 days of tee sheets;
# fetching a year of them every pass is not what "the overview window" means.
MAX_OVERVIEW_DAYS = 14

# See "Adjustable scrape interval" above — overridable per club via
# scrape_interval_minutes / scrape_interval_minutes_booked in its YAML.
DEFAULT_SCRAPE_INTERVAL_MINUTES = 360  # 6 hours
DEFAULT_SCRAPE_INTERVAL_MINUTES_BOOKED = 60  # 1 hour, once a booking exists for the date
# A locked day (see booking_window.py) is re-scraped once its opening time passes, but never
# when its latest scrape is younger than this -- see _should_scrape().
MIN_SCRAPE_AGE_AFTER_OPENING_MINUTES = 10

# How long scrape_due_for_club() waits for another process's pass on the same club
# (launchd, the TUI's timer, the GUI's --force) to finish before giving up on its own --
# see _club_lock().
CLUB_LOCK_WAIT_SECONDS = 600
_CLUB_LOCK_POLL_SECONDS = 0.5


class EmptyScheduleError(Exception):
    """A scrape came back with no slots for a course/date that had slots last time --
    pc caddie's intermittent table-less 200 page (see scraper.fetch_course_aliases()),
    not a real change. Raised by run() so that pass is logged and skipped instead of
    saving 0 slots as the new "latest" (which blanks the day and turns every occupied
    neighbour into a false BUFFER_SHRUNK on the next good pass)."""


SCRAPE_SOURCES = storage.SCRAPE_RUN_SOURCES  # 'agent' (launchd / main()), 'tui', 'gui'

# Daily database backups (2026-10-05) -- see _daily_backup().
BACKUPS_KEPT_PER_CLUB = 7

# Which error a pass reports when several went wrong at once. A rejected login ranks
# last (2026-10-05, review): when the course list also failed, the pass got nothing
# because of *that*, and "Scrapes failing since ...: login rejected" named the wrong
# cause. A no-op pass recorded as login_rejected also counts as a success (see
# storage.scrape_run_succeeded()), so ranking it first would have hidden a real
# course-list failure entirely. The login streak survives either way: an
# authenticated=0 run with some other error neither extends nor ends it (see
# storage.scrape_health()). See _RunStats.error() for the one exception.
_ERROR_PRIORITY = (
    storage.SCRAPE_ERROR_NO_TEE_SHEET,
    storage.SCRAPE_ERROR_NETWORK,
    storage.SCRAPE_ERROR_OTHER,
    storage.SCRAPE_ERROR_LOGIN_REJECTED,
)


@dataclass
class _RunStats:
    """What one scrape_due_for_club() call did, recorded as one `scrape_runs` row
    (2026-10-05, see storage.py's module docstring). `logged_in` is None while no
    credentials are configured, else whether this pass ended up authenticated."""

    attempted: int = 0
    saved: int = 0
    failed: int = 0
    logged_in: bool | None = None
    login_rejected: bool = False
    errors: list[tuple[str, str]] = field(default_factory=list)
    secrets: tuple[str, ...] = ()

    def add_error(self, kind: str, exc: BaseException | str) -> None:
        self.errors.append((kind, _short_error(exc, self.secrets)))

    def error(self) -> tuple[str | None, str | None]:
        """The single (kind, message) this run is recorded with -- see _ERROR_PRIORITY.
        A rejected login only counts while the pass really stayed anonymous.

        Exception: a pass that saved something is a success whatever else went wrong,
        so its recorded error never feeds the "failing" line -- there the rejected login
        goes first, since it's the one the user can fix and the login streak needs to
        see it (one flaky course per pass would otherwise hide a day-long rejection)."""
        kinds = {kind for kind, _ in self.errors}
        if self.login_rejected and self.logged_in is False:
            kinds.add(storage.SCRAPE_ERROR_LOGIN_REJECTED)
        priority = _ERROR_PRIORITY
        if self.saved > 0:
            priority = (storage.SCRAPE_ERROR_LOGIN_REJECTED, *_ERROR_PRIORITY)
        for kind in priority:
            if kind in kinds:
                message = next((m for k, m in self.errors if k == kind), "pc caddie rejected the login")
                return kind, message
        return None, None


def _short_error(exc: BaseException | str, secrets: tuple[str, ...] = ()) -> str:
    """One line, credentials masked -- `scrape_runs.error_message` is shown in the GUI's
    tooltip and must never carry a username/password, whatever an exception's text
    happened to include."""
    text = str(exc) if str(exc) else type(exc).__name__
    text = " ".join(text.split())
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text[: storage.SCRAPE_ERROR_MESSAGE_MAX_CHARS]


def _network_or_other(exc: BaseException) -> str:
    return storage.SCRAPE_ERROR_NETWORK if isinstance(exc, httpx.TransportError) else storage.SCRAPE_ERROR_OTHER


@dataclass
class _WeatherCache:
    """One pass's weather results, shared across every course: the forecast depends only
    on (lat, lon, date), so re-fetching it per course multiplied Open-Meteo requests by
    the course count. `failed` short-circuits the rest of the pass after one failure, so
    an outage costs one timeout per pass rather than one per course/date."""

    results: dict[tuple, tuple[list[WeatherPoint], SunTimes]] = field(default_factory=dict)
    failed: bool = False


def _log(message: str) -> None:
    """`print()` for this module's own best-effort failure notices, with a wall-clock
    timestamp prefixed. Added 2026-09-26: the launchd log (StandardOutPath, appended to
    forever, never rotated) had no timestamps at all, which made an intermittent
    failure (some passes fine, some not) impossible to correlate against time of day
    or how often it actually happens -- every line just looked identical no matter
    when it fired."""
    print(f"[{datetime.now(UTC).isoformat(timespec='seconds')}] {message}")


def _db_path(club_id: str) -> Path:
    """One SQLite file per club (see storage.py's module docstring for why) — keyed by
    the club's own pc caddie numeric id, not the local clubs/*.yaml filename slug, since
    that id is what scraper.py's functions already take and is guaranteed unique."""
    return DATA_DIR / f"{club_id}.db"


def _attach_weather(
    schedule, config: dict, club_id: str, course: str, date: str, cache: _WeatherCache | None = None
) -> None:
    """Fetch the day's forecast + sun times and attach them to `schedule` in place —
    see the module docstring's "Weather" note for why this is best-effort, not fatal.
    `cache` (one per scrape_due_for_club() pass) reuses a date's result across courses
    and stops retrying after the first failure -- see _WeatherCache."""
    location = config.get("location", {})
    lat, lon = location.get("lat"), location.get("lon")
    if not lat or not lon:
        return  # still the club.example.yaml placeholder (0.0, 0.0) -- not configured
    key = (lat, lon, date)
    if cache is not None:
        if cache.failed:
            return  # already failed once this pass -- the previous scrape's weather stays
        if key in cache.results:
            weather, sun_times = cache.results[key]
            schedule.weather, schedule.sun_times = list(weather), sun_times
            return
    try:
        weather = weather_module.fetch_hourly_weather(lat, lon, date)
        sun_times = weather_module.fetch_sun_times(lat, lon, date)
    except Exception as exc:  # noqa: BLE001 — a weather hiccup shouldn't sink the scrape
        _log(f"[scrape_once] weather fetch failed for {club_id}/{course}/{date}: {exc}")
        if cache is not None:
            cache.failed = True
        return
    schedule.weather, schedule.sun_times = weather, sun_times
    if cache is not None:
        cache.results[key] = (list(weather), sun_times)


def _booking_round_minutes(confirmed: ConfirmedBooking, config: dict) -> int:
    """The weather window booking_watch checks for a confirmed booking -- the same
    nine/eighteen mapping and 120/240 defaults as recommend._round_duration_minutes(),
    but from the booking's own hole count when it has one (a 9-hole round booked on an
    18-hole course). An unknown count falls back to the course label, then to 18."""
    if confirmed.holes is None:
        return _round_duration_minutes(confirmed.course, config)
    key = "eighteen" if confirmed.holes >= 18 else "nine"
    default = 240 if key == "eighteen" else 120
    return config.get("round_duration_minutes", {}).get(key, default)


def run(
    club_id: str,
    course: str,
    date: str,
    config: dict | None = None,
    slug: str | None = None,
    client: httpx.Client | None = None,
    course_aliases: dict[str, str] | None = None,
    weather_cache: _WeatherCache | None = None,
) -> list[booking_watch.BookingChange]:
    """Scrape one club/course/date's schedule (plus its weather overlay) and persist
    it, then check any confirmed booking for that date against what changed since the
    previous scrape. Intended to be called by cron/launchd — returns whatever
    BookingChanges were detected, and also persists each one via
    `storage.save_booking_change()` (added 2026-09-06 alongside tui.py) — this runs as
    a separate process from the interactive TUI, so a detected change needs to survive
    somewhere for the TUI's home screen to read on next open, not just exist as an
    in-memory return value nothing else reads.

    `client` (added 2026-09-27) is an optional already-authenticated session, passed
    straight through to `scrape_schedule()` — see `scrape_due_for_club()`'s own
    docstring for why this is built once per pass there rather than once per call
    here, and `scrape_schedule()`'s own docstring for what it actually changes
    (real player names instead of anonymized placeholders).

    `course_aliases`/`weather_cache` are the caller's per-pass course map and weather
    cache (see `_WeatherCache`); omitting `course_aliases` makes `scrape_schedule()`
    re-fetch it live, one extra tee-sheet request per call.

    Does *not* sync "My Reservations" itself any more (moved to the caller,
    `scrape_due_for_club()`, once per pass rather than once per course/date — see
    that function's own docstring) — `storage.load_confirmed_booking()` below still
    reads whatever the caller's own sync already landed for this club, since that
    runs before `run()` is ever called for the first course/date in a pass.

    `config`/`slug` are optional — `main()` already has each club's config and local
    clubs/*.yaml slug loaded from its own loop over `club_config.list_clubs()` and
    passes both straight through, rather than having `run()` redundantly re-derive
    them via `_club_config_and_slug_for_id()`. A caller (or test) with neither handy
    can omit both and `run()` looks them up itself the same way.

    Your global `availability`/`preferences` (2026-09-08 — no longer per-club, see
    `global_preferences.py`) are merged on top of whatever `config` this call ends up
    with either way, so `booking_watch.check_for_changes()`'s own buffer/preferences
    checks below always see your current settings regardless of which club this is.
    """
    DATA_DIR.mkdir(exist_ok=True)
    db_path = _db_path(club_id)
    if config is None or slug is None:
        resolved_config, resolved_slug = _club_config_and_slug_for_id(club_id)
        config = config if config is not None else resolved_config
        slug = slug if slug is not None else resolved_slug
    config = {**config, **global_preferences.load_preferences()}

    # The schedule as of the *previous* scrape, if any — needed as booking_watch's
    # "baseline" before this new scrape becomes "latest". None on the very first scrape
    # for this course/date, which just means there's nothing yet to compare against.
    baseline = storage.load_latest_schedule(course, date, path=db_path)
    # Its own timestamp, captured here (before this pass's save_schedule() below makes
    # a newer row "latest") — booking_watch's PARTY_GREW guard needs it. See that
    # function's own docstring and storage.first_confirmed_at()'s for why.
    baseline_scraped_at = storage.last_scraped_at(course, date, path=db_path)

    latest = scrape_schedule(club_id, course, date, course_aliases=course_aliases, client=client)
    if not latest.slots and baseline is not None and baseline.slots:
        # Slots never legitimately vanish from an open day (a not-yet-open day is empty
        # from its first scrape, so it never gets here) -- see EmptyScheduleError.
        raise EmptyScheduleError(
            f"{course}/{date} came back with no tee times after {len(baseline.slots)} last time; "
            "keeping the previous scrape"
        )
    _attach_weather(latest, config, club_id, course, date, weather_cache)
    storage.save_schedule(latest, path=db_path)

    # Piggybacks on this same scrape rather than a separate pass over the whole
    # database -- see storage.record_seen_players()'s own docstring. A dict keyed by
    # name collapses duplicates across slots (e.g. the same person in two different
    # flights that day) the same way the old set comprehension did, just keeping each
    # name's own PlayerSighting instead of the bare string -- and record_seen_players()
    # itself still no-ops on an empty list, so an anonymous scrape (no client) does
    # nothing extra here.
    seen_players = {p.name: p for slot in latest.slots for p in slot.player_details}
    storage.record_seen_players(list(seen_players.values()), datetime.now(UTC).isoformat(), path=db_path)

    # _sync_my_reservations() is *not* called here any more (moved to
    # scrape_due_for_club(), once per pass rather than once per course/date --
    # see that function's own docstring for why). storage.load_confirmed_booking()
    # below still sees this pass's own fresh sync either way, since the caller
    # runs it before this function is ever called for the first course/date.
    changes: list[booking_watch.BookingChange] = []
    if baseline is not None:
        confirmed = storage.load_confirmed_booking(course, date, path=db_path)
        if confirmed is not None and confirmed.time is not None:
            availability = config.get("availability", {})
            # Split into before/after (2026-09-08, same day as search.py's own
            # buffer split) -- see resolve_buffer_minutes()'s own docstring for the
            # backward-compatible fallback to a still-single, un-split
            # buffer_minutes key.
            buffer_before = resolve_buffer_minutes(availability, "before", 20)
            buffer_after = resolve_buffer_minutes(availability, "after", 20)
            round_duration = _booking_round_minutes(confirmed, config)
            preferences = config.get("preferences", {})
            booking_first_confirmed_at = storage.first_confirmed_at(course, date, confirmed.time, path=db_path)
            changes = booking_watch.check_for_changes(
                confirmed,
                baseline,
                latest,
                buffer_before,
                buffer_after,
                round_duration,
                preferences,
                baseline_scraped_at=baseline_scraped_at,
                booking_first_confirmed_at=booking_first_confirmed_at,
            )
            for change in changes:
                storage.save_booking_change(
                    course=course,
                    date=date,
                    time=confirmed.time,
                    kind=change.kind,
                    message=change.message,
                    params=change.params,
                    path=db_path,
                )

    return changes


_RESERVATIONS_SYNC_FAILED_KIND = "reservations_sync_failed"


def _sync_my_reservations(
    club_id: str, slug: str | None, db_path: Path, known_courses: list[str] | None = None
) -> str | None:
    """Best-effort: log in and save any confirmed bookings pc caddie shows for this
    account. Called once per `scrape_due_for_club()` pass (moved there 2026-09-16,
    see that function's own docstring) rather than once per course/date — "My
    Reservations" isn't scoped to either, so the old per-course/date call site
    logged in up to a dozen-plus times in a single pass for the exact same page,
    and each one was a separate chance for a transient failure. This is the
    login-dependent counterpart to the always-runs schedule scrape above.

    A genuine failure (`LoginError`/`NotImplementedError`) is still swallowed
    rather than propagated — see the module docstring's "Login" note for the full
    list of why a bad pass here must not take down the rest of a scrape — but is
    no longer *only* a `print()` nobody sees. Found live, 2026-09-16, the direct
    reason this changed: a real booking synced instantly when this function was
    run by hand, but two in-app `r` presses hadn't picked it up, and nothing
    anywhere said why not -- `print()` output is invisible while the Textual TUI
    has the screen, so a real, persistent failure looked identical to "nothing
    new to sync." `_report_reservations_sync_failure()` now writes a real,
    visible `OverviewScreen` banner instead (deduplicated -- see its own
    docstring), and a subsequent successful pass clears it via
    `_clear_reservations_sync_failure()`, so a transient problem that resolves
    itself doesn't leave a stale banner behind.

    Also reconciles cancellations (2026-09-13, see `_reconcile_cancelled_
    reservations()`'s own docstring) — this used to only ever *add* rows here,
    so cancelling a booking on pc caddie's own real site never actually cleared
    teetime-monitor's own "still booked" state.

    `known_courses` (2026-09-17) is this club's real course list, passed through to the
    parser as a guard on the course name it reads — see
    `scraper._parse_my_reservations_html()`'s own docstring for the live corruption that
    motivated it, and note the interaction with `_reconcile_cancelled_reservations()`
    below: a wrong course name there doesn't merely store a bad row, it makes the *real*
    booking look cancelled. A mismatch now raises `NotImplementedError`, which this
    function already routes to a visible "parsing" failure banner. `None` (the caller
    couldn't fetch the course list this pass) keeps the old unvalidated behavior rather
    than skipping the sync entirely.

    Returns how it went (2026-10-05, for the pass's `scrape_runs` row): None when it
    was skipped (no slug or no credentials), else "ok", "login" (rejected), "parsing"
    (logged in fine, page unparseable), "network" or "other"."""
    if not slug:
        return None  # can't resolve credentials (keyed by slug) without knowing it
    username, password = club_config.resolve_credentials(slug)
    if not username or not password:
        return None  # PCC_USER/PCC_PASS not configured yet for this club
    try:
        sync = scrape_my_reservations(club_id, username, password, known_courses)
    except LoginError as exc:
        _log(f"[scrape_once] login failed for {club_id}: {exc}")
        _report_reservations_sync_failure("login", db_path)
        return "login"
    except NotImplementedError:
        # a real booking exists but scraper.py can't parse its row markup yet
        _report_reservations_sync_failure("parsing", db_path)
        return "parsing"
    except Exception as exc:  # noqa: BLE001 — offline, a timeout, a 5xx on login or the page
        # Must not escape: from the TUI's worker it would exit the app, and from main()
        # it would stop every later club's pass.
        _log(f"[scrape_once] reservations sync failed for {club_id}: {exc}")
        _report_reservations_sync_failure("other", db_path)
        return "network" if isinstance(exc, httpx.TransportError) else "other"
    for booking in sync.bookings:
        storage.save_confirmed_booking(booking, path=db_path)
    _reconcile_cancelled_reservations(sync.bookings, db_path)
    # Only when this pass actually found it -- see ReservationsSync's own
    # docstring: never overwrite an already-cached handicap with a transient miss.
    if sync.my_handicap is not None:
        storage.save_my_handicap(sync.my_handicap, path=db_path)
    _clear_reservations_sync_failure(db_path)
    return "ok"


def _report_reservations_sync_failure(reason: str, db_path: Path) -> None:
    """Surfaces a "My Reservations" sync failure as a real `OverviewScreen`
    banner (an ordinary `booking_changes` row, same mechanism as a detected
    booking-watch change) rather than only the `print()` that used to be the
    only trace of it — see `_sync_my_reservations()`'s own docstring for why
    that was found to be a real problem, not just a style nitpick. `reason` is
    "login", "parsing" or "other" (network/server errors), matching
    `_sync_my_reservations()`'s own catch clauses; rendered via
    `i18n.render_booking_change()`, not stored as pre-rendered English text, same convention every other banner kind here
    already follows.

    Skips writing a new row if an identical one is already pending and
    unacknowledged — every scheduled pass would otherwise write a fresh banner
    every `AUTO_REFRESH_INTERVAL_SECONDS` for as long as the underlying problem
    persists, which would bury the overview in duplicates of the same warning
    rather than saying it once."""
    pending = storage.load_unacknowledged_booking_changes(path=db_path)
    already_flagged = any(
        change["kind"] == _RESERVATIONS_SYNC_FAILED_KIND and change["params"].get("reason") == reason
        for change in pending
    )
    if already_flagged:
        return
    storage.save_booking_change(
        course="",
        date=date_cls.today().isoformat(),
        time=None,
        kind=_RESERVATIONS_SYNC_FAILED_KIND,
        message=f"Couldn't check your reservations ({reason}).",
        params={"reason": reason},
        path=db_path,
    )


def _clear_reservations_sync_failure(db_path: Path) -> None:
    """A successful sync means whatever was wrong before, now isn't — acknowledges
    any still-pending `reservations_sync_failed` banner so a resolved problem
    doesn't sit there forever needing a manual `x` to go away. Scoped to just
    that one kind (not every unacknowledged change) so this can't accidentally
    dismiss an unrelated, still-genuinely-pending booking-watch banner."""
    pending = storage.load_unacknowledged_booking_changes(path=db_path)
    stale_ids = [change["id"] for change in pending if change["kind"] == _RESERVATIONS_SYNC_FAILED_KIND]
    if stale_ids:
        storage.acknowledge_booking_changes(stale_ids, path=db_path)


def _reconcile_cancelled_reservations(live_bookings: list[ConfirmedBooking], db_path: Path) -> None:
    """A previously-known *future* booking that's silently disappeared from pc
    caddie's own live "My Reservations" list has been cancelled there directly —
    found live, 2026-09-13, answering a direct question: "how do i cancel/modify
    confirmed tee times?" `_sync_my_reservations()` above only ever *added* rows,
    so cancelling on the real site never actually cleared teetime-monitor's own
    "still booked" state; the stale confirmation just sat there, unacknowledged,
    until (if ever) a brand new confirmation for that same course/date overwrote
    it.

    Deliberately only checks *future* (today or later) dates — a *past* date
    disappearing from "My Reservations" is completely normal (that page isn't a
    history view; it naturally drops a booking once its date has passed) and
    must never be mistaken for a cancellation, or every single played round
    would get flagged "cancelled" the moment its own date passed.

    Only ever reconciles `source="my_reservations"` rows — a `source="manual"`
    confirmation (the TUI's own `c`, the same-day-booking timing-gap fallback
    this whole mechanism exists alongside — see `ConfirmedBooking`'s own
    docstring) is deliberately never auto-cancelled by this live comparison,
    since "My Reservations" was never going to confirm or deny it in the first
    place.

    Writes a `time=None` sentinel row rather than deleting anything —
    `confirmed_bookings` is deliberately append-only (`load_all_confirmed_
    bookings()`'s own docstring: analytics needs the full history), and
    `time=None` already means "confirmed not playing that day" everywhere this
    gets read back (`ConfirmedBooking.time`'s own docstring; `booking_watch.
    check_for_changes()` and every confirmed-booking display in `tui.py` already
    treat a falsy `.time` as "nothing to show" here) — reusing an existing,
    already-correct sentinel rather than inventing a new one, and "latest wins"
    (`load_confirmed_booking()`) means this new row simply supersedes the stale
    one going forward without erasing it."""
    today = date_cls.today().isoformat()
    live_keys = {(booking.course, booking.date) for booking in live_bookings}
    for known in storage.load_all_confirmed_bookings(path=db_path):
        if known.source != "my_reservations" or known.time is None:
            continue  # a manual record, or already reconciled/genuinely "not playing"
        if known.date < today:
            continue
        if (known.course, known.date) in live_keys:
            continue
        storage.save_confirmed_booking(
            ConfirmedBooking(
                date=known.date,
                course=known.course,
                time=None,
                holes=None,
                source="my_reservations",
                confirmed_at=datetime.now(UTC).isoformat(),
            ),
            path=db_path,
        )


def _club_config_and_slug_for_id(club_id: str) -> tuple[dict, str | None]:
    """club_config.py keys clubs by their local clubs/*.yaml filename slug, not the pc
    caddie numeric club_id run() otherwise uses throughout — this bridges the two by
    matching on the config's own `club_id:` field, returning both the config and the
    slug (needed to resolve credentials via club_config.resolve_credentials(), itself
    keyed by slug). Returns ({}, None) if no saved club's config matches, which can
    legitimately happen in a test that calls run() directly without a real
    clubs/*.yaml on disk."""
    for slug in club_config.list_clubs():
        config = club_config.load_club_config(slug)
        if config.get("club_id") == club_id:
            return config, slug
    return {}, None


def _should_scrape(club_id: str, course: str, date: str, config: dict) -> bool:
    """Whether this course/date is actually due for a re-scrape yet, per the club's
    adjustable interval (shorter once a confirmed booking exists for that date) — see
    the module docstring's "Adjustable scrape interval". Lets `main()` be scheduled to
    run frequently without hammering the site on every course/date every time it fires.
    """
    db_path = _db_path(club_id)
    last = storage.last_scraped_at(course, date, path=db_path)
    if last is None:
        return True  # never scraped for this course/date -- always due

    confirmed = storage.load_confirmed_booking(course, date, path=db_path)
    is_booked = confirmed is not None and confirmed.time is not None
    interval_minutes = config.get(
        "scrape_interval_minutes_booked" if is_booked else "scrape_interval_minutes",
        DEFAULT_SCRAPE_INTERVAL_MINUTES_BOOKED if is_booked else DEFAULT_SCRAPE_INTERVAL_MINUTES,
    )

    now = _utcnow()
    last_at = datetime.fromisoformat(last)
    elapsed_minutes = (now - last_at).total_seconds() / 60
    if elapsed_minutes >= interval_minutes:
        return True
    # A day that has opened for booking since its last scrape is due right away, not
    # after the rest of a 6-hour interval (2026-10-05): its latest scrape was a sheet
    # of "4 Tage im Voraus ab 20 Uhr buchbar" notices, and the 20:00 that notice names
    # has passed. Throttled twice over, so it can neither re-scrape every pass nor
    # loop on a day that stays "locked" after its opening time (a notice misread, a
    # club whose sheet lags): it needs the opening to fall *after* that scrape, and
    # the scrape itself to be at least MIN_SCRAPE_AGE_AFTER_OPENING_MINUTES old.
    if elapsed_minutes < MIN_SCRAPE_AGE_AFTER_OPENING_MINUTES:
        return False
    return _opened_since(course, date, last_at, now, config, db_path)


def _opened_since(
    course: str, date: str, last_at: datetime, now: datetime, config: dict, db_path: Path
) -> bool:
    """Whether the latest scrape of this course/date was a locked day (see
    `booking_window.booking_opening()`) whose opening time lies between that scrape
    and `now`."""
    schedule = storage.load_latest_schedule(course, date, path=db_path)
    if schedule is None:
        return False
    opening = booking_window.booking_opening(schedule.slots, date, booking_window.club_timezone(config))
    return opening is not None and last_at < opening[0] <= now


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _try_lock(handle) -> bool:
    """Non-blocking exclusive lock on an open file; False if another holder has it."""
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass  # closing the handle releases it anyway


@contextmanager
def _club_lock(club_id: str, wait_seconds: float | None = None) -> Iterator[bool]:
    """Per-club inter-process lock around one whole scrape_due_for_club() pass. The
    launchd agent, the TUI's timer and the GUI's `--force` refresh are separate
    processes; two overlapping passes read the same baseline and each saved the same
    booking-watch banner (and doubled every request). A second pass waits for the first
    (up to `wait_seconds`, default CLUB_LOCK_WAIT_SECONDS) rather than skipping, so an
    explicit refresh still means "now" -- afterwards `_should_scrape()` sees the first
    pass's fresh rows. Yields False if the wait ran out; an unopenable lock file yields
    True (unlocked) rather than blocking scraping altogether."""
    wait_seconds = CLUB_LOCK_WAIT_SECONDS if wait_seconds is None else wait_seconds
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handle = open(DATA_DIR / f"{club_id}.lock", "a+")  # noqa: SIM115 — held across the yield
    except OSError as exc:
        _log(f"[scrape_once] couldn't open the lock file for {club_id}, scraping unlocked: {exc}")
        yield True
        return
    try:
        deadline = time.monotonic() + wait_seconds
        acquired = _try_lock(handle)
        while not acquired and time.monotonic() < deadline:
            time.sleep(_CLUB_LOCK_POLL_SECONDS)
            acquired = _try_lock(handle)
        try:
            yield acquired
        finally:
            if acquired:
                _unlock(handle)
    finally:
        handle.close()


def scrape_due_for_club(
    slug: str, config: dict, force: bool = False, source: str = "agent"
) -> list[booking_watch.BookingChange]:
    """Scrape every course x day in `slug`'s `overview_days` window that's actually
    due per `_should_scrape()`, skipping the rest. Extracted 2026-09-07 from `main()`'s
    own per-club loop so `tui.py` can call this directly too — both once on open and
    again on a timer while it stays running (direct feedback: "I think hitting 'r'
    makes only sense as a manual override" — see that module's own "Auto-refresh"
    note) — without needing a separately-scheduled process for that to happen at all.
    One course/date's own failure is caught and skipped, not fatal, same stance as
    `main()`'s own: it must not stop the rest of this club's window, let alone (from
    `main()`) every other saved club.

    `force=True` (added 2026-09-15, `OverviewScreen`'s own manual `r` override —
    "why don't we integrate those missing features into the overview screen"
    once the since-retired `DayDetailScreen`'s own `r` was found to
    unconditionally re-scrape its one day, no throttle at all) skips the
    `_should_scrape()` check entirely, scraping every course/date in the window
    regardless of how recently it was last fetched — the same "you explicitly
    asked, so do it now" contract that screen's own refresh gave for a single
    day, just for the whole loaded window at once.

    Merges your global `availability`/`preferences`/scrape-interval settings on top of
    `config` right away (2026-09-08 — no longer per-club, see `global_preferences.py`)
    since `_should_scrape()` below needs `scrape_interval_minutes` from them before
    `run()` ever gets a chance to merge it again on its own.

    Syncs "My Reservations" exactly once here, before the course/date loop below —
    moved 2026-09-16 (direct feedback, once a real booking synced instantly when
    run by hand but hadn't landed after two in-app `r` presses: "I need you to fix
    it, especially to make it reliably refresh next time I make a reservation")
    from `run()`, which used to call it once per course/date and so logged in
    (and re-fetched the whole reservations page) up to a dozen-plus times in a
    single pass for no benefit — every one of those logins was redundant, since
    "My Reservations" isn't scoped to a course or date at all, and each one was
    also a real chance for a transient failure that the single-call version below
    no longer multiplies. See `_sync_my_reservations()`'s own docstring for how a
    failure is now actually surfaced instead of only ever reaching a `print()`
    nothing sees while the TUI has the screen.

    The whole pass runs under `_club_lock()` so overlapping processes don't scrape (and
    write booking-watch banners for) the same club at once.

    Records exactly one `scrape_runs` row per call (2026-10-05 -- see storage.py's
    module docstring for the 20-hour silent login failure that motivated it), tagged
    with `source` ('agent' from main()/launchd, 'tui', 'gui'): also when nothing was
    due (a no-op success, so the health line can tell "the agent is alive and idle"
    from "the agent stopped"). Two exceptions: a config with no club_id at all (there's
    no database to record into), and a call that gave up waiting for the club lock (the
    pass holding it records its own row -- see the comment at the lock check). An
    `agent` pass that succeeded also takes the day's backup (see `_daily_backup()`).
    Recording or backing up never fails the pass itself."""
    if source not in SCRAPE_SOURCES:
        raise ValueError(f"unknown scrape source {source!r}; expected one of {SCRAPE_SOURCES}")
    config = {**config, **global_preferences.load_preferences()}
    club_id = config.get("club_id")
    if not club_id:
        _log(f"[scrape_once] {slug}: no club_id set in its config, skipping")
        return []
    started_at = datetime.now(UTC).isoformat()
    stats = _RunStats()
    lock_busy = False
    try:
        with _club_lock(club_id) as acquired:
            if not acquired:
                # Not recorded (2026-10-05, review): the pass holding the lock records
                # its own row, and this one -- started later, so sorting as the newest --
                # used to count as a failure *and* end a login-rejected streak (its
                # login outcome unknown), making the login warning vanish mid-outage. A
                # holder that hangs for good still surfaces: no row lands at all, so the
                # last success goes stale (see scrape_health.health_status()).
                _log(f"[scrape_once] {slug}: another pass still running after {CLUB_LOCK_WAIT_SECONDS}s, skipping")
                lock_busy = True
                return []
            return _scrape_due_for_club_locked(slug, club_id, config, force, stats)
    except BaseException as exc:
        stats.add_error(_network_or_other(exc), exc)
        raise
    finally:
        if not lock_busy:
            succeeded = _record_run(club_id, source, started_at, stats)
            if succeeded and source == "agent":
                _daily_backup(club_id)


def _record_run(club_id: str, source: str, started_at: str, stats: _RunStats) -> bool:
    """Writes this pass's `scrape_runs` row; returns whether the pass counts as a
    success (see storage.scrape_run_succeeded()). A failed write is logged, never
    raised -- health bookkeeping must not be what breaks a scrape."""
    error_kind, error_message = stats.error()
    try:
        storage.record_scrape_run(
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            source=source,
            attempted=stats.attempted,
            saved=stats.saved,
            failed=stats.failed,
            authenticated=stats.logged_in,
            error_kind=error_kind,
            error_message=error_message,
            path=_db_path(club_id),
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"[scrape_once] {club_id}: couldn't record this scrape run: {exc}")
    return storage.scrape_run_succeeded(stats.saved, stats.attempted, error_kind)


def _daily_backup(club_id: str, today: str | None = None) -> Path | None:
    """One SQLite online backup of this club's database per day, at
    DATA_DIR/backups/<club_id>-YYYY-MM-DD.db, keeping the newest
    BACKUPS_KEPT_PER_CLUB (2026-10-05). The databases are the only record of tee sheets
    pc caddie hides once they're past -- a corrupted file would lose history that can't
    be re-scraped. Taken after a successful agent pass only (the TUI/GUI never do it,
    so an interactive refresh never waits on one). Returns the backup written, None if
    today's already exists or anything went wrong (logged, never raised)."""
    try:
        source = _db_path(club_id)
        if not source.exists():
            return None
        backups = DATA_DIR / "backups"
        day = today or date_cls.today().isoformat()
        target = backups / f"{club_id}-{day}.db"
        if target.exists():
            return None
        storage.backup_db(source, target)
        existing = sorted(backups.glob(f"{club_id}-????-??-??.db"))
        for stale in existing[:-BACKUPS_KEPT_PER_CLUB]:
            stale.unlink(missing_ok=True)
        return target
    except Exception as exc:  # noqa: BLE001
        _log(f"[scrape_once] {club_id}: daily backup failed: {exc}")
        return None


def _scrape_due_for_club_locked(
    slug: str, club_id: str, config: dict, force: bool, stats: _RunStats | None = None
) -> list[booking_watch.BookingChange]:
    """scrape_due_for_club()'s body, run while holding that club's `_club_lock()`.
    Fills in `stats` as it goes (see _RunStats)."""
    stats = stats if stats is not None else _RunStats()
    username, password = club_config.resolve_credentials(slug) if slug else ("", "")
    stats.secrets = tuple(secret for secret in (username, password) if secret)
    # Fetched fresh per club rather than assumed from a hardcoded constant — confirmed
    # 2026-09-07 that a club's own course lineup (names *and* alias codes) isn't
    # universal, so a fixed COURSE_ALIASES silently scraped the wrong thing for a
    # second real club added the same day. One bad club's fetch must not stop every
    # other saved club (same stance as everything else in this function), so this is
    # caught here and skipped, not left to propagate out of main()'s own loop.
    #
    # Runs *before* _sync_my_reservations() (reordered 2026-09-17) purely so the real
    # course list can be handed to it as a parse guard — see
    # scraper._parse_my_reservations_html()'s own docstring for the live corruption
    # that guard exists to stop. Deliberately does NOT gate the sync: a failed course
    # fetch still lets reservations sync (unvalidated, exactly as before), since the
    # two are independent and "My Reservations" is worth reading either way.
    courses = None
    try:
        courses = fetch_course_aliases(club_id)
    except NoTeeSheetError as exc:
        _log(f"[scrape_once] {slug}: couldn't load its course list, skipping: {exc}")
        stats.add_error(storage.SCRAPE_ERROR_NO_TEE_SHEET, exc)
    except Exception as exc:  # noqa: BLE001
        _log(f"[scrape_once] {slug}: couldn't load its course list, skipping: {exc}")
        stats.add_error(_network_or_other(exc), exc)

    sync_outcome = _sync_my_reservations(club_id, slug, _db_path(club_id), list(courses) if courses else None)
    if sync_outcome is not None:
        # Overridden below by the schedule scrape's own login, when that runs.
        stats.logged_in = sync_outcome in ("ok", "parsing")
        stats.login_rejected = sync_outcome == "login"

    if courses is None:
        return []

    # The club's own bookable-date window, straight from its tee sheet, in preference
    # to the configured `overview_days`. Confirmed 2026-09-07 across 79 real clubs to
    # range from 1 day to 31 (8 being the most common) against a configured default of
    # 5 — so the fixed number was simultaneously asking several clubs for dates their
    # site rejects outright ("Selection invalid.") and never looking at most of the
    # window the rest actually offer. `overview_days` stays the fallback for a club
    # whose page has no date selector at all (5 of 45 in that sweep). The club's own
    # window is still capped: one club advertised 366 days, and scraping a year of tee
    # sheets every pass is not what "the overview window" means. The cap is
    # MAX_OVERVIEW_DAYS, or the club's configured `overview_days` if that's been set
    # higher deliberately.
    dates = []
    try:
        dates = fetch_available_dates(club_id)
    except Exception as exc:  # noqa: BLE001 — non-fatal, falls back to the config value
        _log(f"[scrape_once] {slug}: couldn't read its booking window ({exc}); using overview_days")
    overview_days = config.get("overview_days", 5)
    if dates:
        target_dates = dates[:max(overview_days, MAX_OVERVIEW_DAYS)]
    else:
        today = date_cls.today()
        target_dates = [(today + timedelta(days=offset)).isoformat() for offset in range(overview_days)]

    # One authenticated session for the *whole* date/course loop below (2026-09-27),
    # not one login per call -- same "up to a dozen logins in one pass" bug class
    # already fixed once here for _sync_my_reservations() above, just for the
    # schedule scrape instead of the reservations sync. Confirmed live the same day:
    # an authenticated fetch of the ordinary tee sheet shows real player names for
    # anyone who's opted into pc caddie's own reciprocal name-sharing, where an
    # anonymous fetch (what every scrape_schedule() call used before this) only ever
    # shows placeholder text -- see that function's own docstring. A second, separate
    # login from _sync_my_reservations()'s own scrape_my_reservations() call above is
    # accepted here rather than reworking that function's own established signature
    # for a marginal saving.
    client = None
    if username and password:
        try:
            client = login(club_id, username, password)
            stats.logged_in, stats.login_rejected = True, False
        except (LoginError, httpx.HTTPError) as exc:
            _log(f"[scrape_once] {slug}: couldn't log in for the schedule scrape, falling back to anonymous: {exc}")
            stats.logged_in = False
            if isinstance(exc, LoginError):
                stats.login_rejected = True
                stats.add_error(storage.SCRAPE_ERROR_LOGIN_REJECTED, exc)
            else:
                stats.add_error(_network_or_other(exc), exc)

    changes: list[booking_watch.BookingChange] = []
    weather_cache = _WeatherCache()
    try:
        for target_date in target_dates:
            for course in courses:
                counted = False
                try:
                    # Inside the try: a sqlite "database is locked" here must not end the pass.
                    if not force and not _should_scrape(club_id, course, target_date, config):
                        continue
                    stats.attempted += 1
                    counted = True
                    changes.extend(
                        run(
                            club_id,
                            course,
                            target_date,
                            config,
                            slug,
                            client=client,
                            course_aliases=courses,
                            weather_cache=weather_cache,
                        )
                    )
                    stats.saved += 1
                except httpx.TransportError as exc:
                    # Offline or pc caddie hanging: every remaining course/date would wait
                    # out its own 15 s timeout too. The next pass picks them all up.
                    _log(f"[scrape_once] {slug}/{course}/{target_date} network error, stopping this pass: {exc}")
                    stats.attempted += 0 if counted else 1
                    stats.failed += 1
                    stats.add_error(storage.SCRAPE_ERROR_NETWORK, exc)
                    return changes
                except Exception as exc:  # noqa: BLE001 — one bad course/date must not
                    # stop the rest of this club's window (or, from main(), every other
                    # saved club).
                    _log(f"[scrape_once] {slug}/{course}/{target_date} failed: {exc}")
                    stats.attempted += 0 if counted else 1
                    stats.failed += 1
                    stats.add_error(storage.SCRAPE_ERROR_OTHER, exc)
    finally:
        if client is not None:
            client.close()
    return changes


def main(argv: list[str] | None = None) -> None:
    """The unattended entry point (`teetime-monitor-scrape`, and the launchd agent).

    `--force` bypasses `_should_scrape()`'s per-course/date interval, the same override
    the TUI's own `r` key has always had. Added 2026-09-17 once a GUI front end grew a
    Refresh button: without it, pressing Refresh usually did nothing at all — the
    throttle correctly decided nothing was due — which is indistinguishable from the
    button being broken. That is exactly the invisible-failure shape this project has
    been bitten by before (see the v0.21.0 reservations-sync banner), so the fix is to
    let an explicit human request actually mean "now", rather than to explain the
    silence afterwards.

    `--source agent|tui|gui` (2026-10-05) tags this pass's `scrape_runs` rows -- the
    GUI's Refresh passes `--source gui`; launchd passes nothing and gets 'agent' (which
    is also the only source that takes the daily backup, see `_daily_backup()`).
    """
    paths.force_utf8_stdio()
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="teetime-monitor-scrape", description="Scrape every saved club once.")
    parser.add_argument("-f", "--force", action="store_true", help="ignore the per-course/date scrape interval")
    parser.add_argument("--source", choices=SCRAPE_SOURCES, default="agent", help="who triggered this pass")
    # parse_known_args: unknown arguments were always ignored here (an older launchd
    # plist or wrapper passing something extra must not stop the agent); a bad
    # --source value still errors out.
    args, _unknown = parser.parse_known_args(argv)
    force, source = args.force, args.source
    # One-time move off the old working-directory layout (2026-09-17, see paths.py).
    # The launchd agent still runs with a WorkingDirectory set, so an install that
    # predates the move migrates itself on its next scheduled pass without anyone
    # having to notice -- and `needs_migration()` is false forever after.
    if paths.needs_migration():
        for item in paths.migrate_from():
            _log(f"[scrape_once] migrated to {paths.CONFIG_DIR}: {item}")
    paths.ensure_dirs()
    for slug in club_config.list_clubs():
        config = club_config.load_club_config(slug)
        scrape_due_for_club(slug, config, force=force, source=source)


if __name__ == "__main__":
    main()
