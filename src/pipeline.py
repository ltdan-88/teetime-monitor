"""The headless recommendation pipeline (2026-10-05), moved out of `tui.py` unchanged.

Everything a GUI subprocess needs to answer "what would the TUI show for this club
and day": the merged per-club config (`_resolved_config()`), the availability
pipeline behind the Pick column and the ★ markers (`_availability_pipeline()`,
`_shorter_round_alternative()`, `_recommended_times_for()`), crowd estimates and the
holiday/vacation/heatmap helpers they call, and the daylight check. No Textual or
Rich imports -- `picks_cli.py`, `search_cli.py` and `preview_club_cli.py` used to
reach these through `from . import tui`, which imported the whole TUI into every
GUI subprocess. `tui.py` imports these names back, so its own code and the tests'
`tui._xxx` references keep working; the clock is read through `clock.py` (see there).

Kept private (leading underscore) and with their original names and docstrings: this
was a move, not a redesign. Rich markup and everything widget-shaped (`_day_pick_text()`,
`_alternative_pick_text()`, `_locked_day_texts()`, ...) stays in `tui.py`.
"""

import time
from datetime import date as date_cls
from pathlib import Path

import yaml

from . import (
    analytics,
    calendar_context,
    clock,
    club_config,
    geocode,
    global_preferences,
    playability,
    recommend,
    storage,
)
from .models import DateRange, Schedule
from .scrape_once import _db_path
from .scraper import _holes_from_course_label
from .search import search as search_slots


def _load_club_config_safely(slug: str) -> dict:
    """`club_config.load_club_config(slug)`, or {} when the file is missing,
    unreadable, not valid YAML, or not a mapping -- the same tolerance
    `club_config.slug_for_club_id()` gives a malformed favorite."""
    try:
        config = club_config.load_club_config(slug)
    except (OSError, yaml.YAMLError):
        return {}
    return config if isinstance(config, dict) else {}


# {(db path, club name): time.monotonic() of a failed geocode} -- see
# _location_for_club(). Keyed by db path so it follows the per-club db the
# successful result would have been saved into.
_GEOCODE_FAILURES: dict[tuple[str, str], float] = {}
_GEOCODE_RETRY_SECONDS = 3600.0


def _looks_like_slug_fallback(name: str) -> bool:
    """True for the `club-0000001`-style slug `_favorite_clubs()` falls back to
    for a favorite saved without a name -- not a real club name, so never worth
    sending to Nominatim."""
    prefix, _, digits = name.partition("-")
    return prefix == "club" and digits.isdigit()


def _location_for_club(club_id: str, club_name: str) -> dict | None:
    """A club's {"lat", "lon"}, independent of whether it's ever been favorited
    (2026-09-08, direct feedback: "I don't want to first save a club in order to see
    weather forecast" — location used to only ever get looked up when a club was
    saved, via club_config.new_club_stub_with_location(), so a club visited without
    saving it (an ordinary state since the 2026-09-07 favorites rework — see
    _open_club()) never got one at all, no matter how long you kept it open. Cached
    in the club's own per-club db (storage.save_location/load_location) instead of
    clubs/*.yaml, since that db already exists the moment a club is scraped,
    regardless of favorite status — geocoded at most once per club, same one-time-
    lookup rule new_club_stub_with_location() already follows, just keyed by the
    club's db file instead of a saved config file."""
    path = _db_path(club_id)
    cached = storage.load_location(path=path)
    if cached is not None:
        return cached
    if not club_name or _looks_like_slug_fallback(club_name):
        return None
    # A failed lookup is remembered for _GEOCODE_RETRY_SECONDS: this runs on the
    # UI thread from every redraw (resize, expand, confirm), and an un-geocodable
    # name used to mean a fresh Nominatim request each time -- a frozen UI on a
    # slow network, and a burst against Nominatim's 1 request/second policy.
    failure_key = (str(path), club_name)
    failed_at = _GEOCODE_FAILURES.get(failure_key)
    if failed_at is not None and time.monotonic() - failed_at < _GEOCODE_RETRY_SECONDS:
        return None
    location = geocode.find_club_location(club_name)
    if location is None:
        _GEOCODE_FAILURES[failure_key] = time.monotonic()
        return None
    lat, lon = location
    found = {"lat": lat, "lon": lon}
    storage.save_location(found, path=path)
    return found


def _resolved_config(club_slug: str | None, club_id: str | None = None, club_name: str = "") -> dict:
    """This club's own settings (`location`, `overview_days`, `default_course`,
    `identity` — genuinely per-club facts), with your global `availability`/
    `preferences`/`ai_assist`/`round_duration_minutes`/scrape-interval settings
    shallow-merged on top (added 2026-09-08, direct feedback: "i also want the
    settings/preferences to be global and not tied to a specific club" — those aren't
    per-club facts at all, so they overlay every club's own config rather than being
    duplicated into each one). `club_slug is None` (a club being visited without
    saving it) contributes nothing per-club from clubs/*.yaml, but still gets your
    global settings — recommendations now work even on a club you haven't favorited,
    which the old per-club-only design couldn't offer since there was nowhere for an
    unsaved club to have availability rules at all.

    `club_id`/`club_name` (added 2026-09-08, same feedback as `_location_for_club()`)
    fill in `location` from that club's own per-club db when clubs/*.yaml has none —
    whether because the club was never saved at all, or because it was saved before a
    location could be found. Both default to falsy so every existing caller that
    doesn't pass them keeps behaving exactly as before."""
    club_settings = _load_club_config_safely(club_slug) if club_slug is not None else {}
    if "location" not in club_settings and club_id is not None:
        location = _location_for_club(club_id, club_name)
        if location is not None:
            club_settings = {**club_settings, "location": location}
    return {**club_settings, **global_preferences.load_preferences()}


def _compute_crowd_estimates(
    schedules: list[Schedule],
    config: dict,
    club_id: str,
    db_path: Path | None = None,
    fetch_holidays: bool = True,
) -> dict[tuple[str, str, str], float]:
    """{(date, course, time): predicted occupancy 0-1} for every slot across
    `schedules` — the actual `analytics.crowd_heatmap()`/`predict_crowding()` work,
    factored out of `_crowd_estimates()` 2026-09-16 (direct follow-up: "Would it
    make sense to integrate heatmap data into the timeslots in overview screen?")
    so `OverviewScreen`'s own per-slot marker (`_slot_crowd_marker()`) can use this
    unconditionally — `_crowd_estimates()` below still exists solely for the AI-
    ranking use, gated behind `ai_assist.avoid_predicted_crowd` (see its own
    docstring for why that gate has to stay there); *visibility* of a slot's usual
    crowd level was never actually the same question as "should this bias the AI's
    picks," and conflating them would have made the marker only ever show up for
    the minority of users who also have AI ranking's crowd-avoidance switched on.

    One `analytics.crowd_heatmap()` per distinct course across `schedules` (a real,
    if modest, SQLite scan — cheap enough at this app's actual scale not to bother
    caching across calls). `calendar_context.classify_day()` picks the same
    weekday-or-special-type key `HeatmapScreen`'s own table uses — see that
    screen's docstring, and `analytics.crowd_heatmap()`'s, for why day-of-week
    (not a coarse workday/weekend split) is what the underlying data is actually
    keyed by. `_holidays_for_club()`'s own cache (see that function's docstring)
    is what actually makes calling this unconditionally, on every render, cheap —
    without it this would mean one live Nager.Date fetch per expanded day, every
    time the table redraws (load, refresh, expand/collapse, resize).

    `db_path` defaults to `_db_path(club_id)` — every existing caller here omits
    it and gets exactly that, unchanged. Added 2026-09-25 for `search_cli.py`,
    which already resolves its own `--db-path` (not necessarily this club's
    canonical one, e.g. an isolated copy under test) and would otherwise have no
    way to make this scan the same database its search results themselves come
    from.

    `fetch_holidays=False` (the overview's synchronous render) uses only the
    holidays already cached -- see `_holidays_for_club()`."""
    holidays = _holidays_for_club(config, fetch=fetch_holidays)
    vacation_ranges = _vacation_ranges_for_club(config)
    resolved_db_path = db_path if db_path is not None else _db_path(club_id)
    heatmaps: dict[str, dict] = {}
    estimates: dict[tuple[str, str, str], float] = {}
    for schedule in schedules:
        if schedule.course not in heatmaps:
            heatmaps[schedule.course] = _cached_crowd_heatmap(
                schedule.course, holidays, vacation_ranges, resolved_db_path
            )
        heatmap = heatmaps[schedule.course]
        day_type = calendar_context.classify_day(
            schedule.date,
            holidays,
            vacation_ranges,
            has_tournament=calendar_context.is_tournament_day(schedule.events, schedule.slots),
        )
        key = (
            day_type
            if day_type in calendar_context.SPECIAL_DAY_TYPES
            else date_cls.fromisoformat(schedule.date).strftime("%A")
        )
        for slot in schedule.slots:
            estimate = analytics.predict_crowding(key, slot.time, heatmap)
            if estimate is not None:
                estimates[(schedule.date, schedule.course, slot.time)] = estimate
    return estimates


def _crowd_estimates(
    schedules: list[Schedule], config: dict, club_id: str, db_path: Path | None = None
) -> dict[tuple[str, str, str], float]:
    """{(date, course, time): predicted occupancy 0-1}, for biasing AI ranking only
    — entirely skipped (empty dict, no analytics/DB work at all) unless
    `ai_assist.avoid_predicted_crowd` is actually on, since nothing downstream does
    anything with it otherwise. Added 2026-09-10, direct follow-up to finding
    `avoid_predicted_crowd` had zero real effect despite reaching Claude's own
    prompt verbatim: "make avoid crowds a child of AI option" — moving where it
    lives in Settings only fixes the framing, not the underlying gap, so this is
    the actual data behind it.

    For the Overview's own visible per-slot marker, call
    `_compute_crowd_estimates()` directly instead — see that function's own
    docstring for why this gate doesn't apply there.

    `db_path` just threads through to `_compute_crowd_estimates()` — see its own
    docstring for the one caller (`search_cli.py`) that actually needs it."""
    ai_config = config.get("ai_assist", {})
    if not ai_config.get("avoid_predicted_crowd", False):
        return {}
    return _compute_crowd_estimates(schedules, config, club_id, db_path=db_path)


def _availability_pipeline(
    schedule: Schedule, config: dict, club_id: str, cache: dict | None = None
) -> tuple[list, list]:
    """(deterministic candidates, still-playable matches) for one schedule against
    your global `availability` rules (see `_resolved_config()`) — factored out so both
    the per-day pick column below and the expanded slot rows' own ★ marker derive from one
    place. `([], [])` with no `availability` configured at all — nothing to check
    against, not an error.

    `playable` goes through `recommend.ranked_matches()` (not a bare
    `exclude_unplayable()`, as this used to call directly) — the exact same pipeline
    `weekly_picks()` uses, so "the best slot for one day" can never disagree with "the
    best slots for the week" about what counts as best. With `ai_assist.enabled`
    false (the default), `ranked_matches()` returns exactly what `exclude_unplayable()`
    alone would have — same items, same order — so this is a behavior-preserving
    change until AI ranking is actually turned on; only then does `playable`'s order
    start reflecting genuine judgment instead of plain chronological order. Direct
    feedback this responds to (2026-09-08): "why does it always recommend 16:00 on
    any other day?" — `_day_pick_text()` used to take the literal earliest playable
    time, which is exactly 16:00 every day once a saved window starts at 16:00 and
    that slot happens to be open, regardless of how good the rest of the window is.

    `cache` is an optional memo, keyed by (date, course). Measured 2026-09-17:
    `_render_table()` reaches this twice for every expanded day with identical
    arguments — once via `_day_pick_text()` for the Pick column, once via
    `_recommended_times_for()` for the ★ markers on the expanded slot rows — and it
    was the single most expensive thing left in a render after the heatmap cache.

    Was per-render (a fresh dict inside `_render_table()`, thrown away at the end)
    until 2026-09-27, direct follow-up: "the TUI is still very unresponsive...
    when changing window size." With `ai_assist.enabled`, this call makes a real
    network round trip (a live ranking call per day) — a fresh cache on every call
    meant a resize/expand/collapse (`_rerender_preserving_cursor()`, redrawing the
    exact *same* schedules) re-ran that live call for every displayed day, every
    time (confirmed live: ~1.9s for one resize on the real club, almost entirely
    that I/O). `OverviewScreen._pick_cache` (see its own `__init__` docstring) is
    now what callers actually pass — it persists across a screen's whole
    lifetime, cleared by `load_overview()` on every genuinely-new-dataset call
    (a fresh open, a periodic/forced refresh), never by a pure re-layout. A
    settings change gets a fresh one for free a different way —
    `_rebuild_current_screen()` replaces the whole `OverviewScreen` instance, and
    `__init__` starts this empty."""
    key = (schedule.date, schedule.course)
    if cache is not None and key in cache:
        return cache[key]
    if not config.get("availability"):
        return [], []
    criteria = recommend.default_criteria_from_config(config)
    candidates = search_slots([schedule], criteria)
    crowd_estimates = _crowd_estimates([schedule], config, club_id)
    friend_names = storage.load_friend_names(path=_db_path(club_id))
    known_handicaps = storage.load_known_handicaps(path=_db_path(club_id))
    my_handicap = storage.load_my_handicap(path=_db_path(club_id))
    playable = recommend.ranked_matches(
        [schedule],
        criteria,
        config,
        crowd_estimates,
        friend_names,
        known_handicaps=known_handicaps,
        my_handicap=my_handicap,
    )
    result = (candidates, playable)
    if cache is not None:
        cache[key] = result
    return result


def _shorter_round_alternative(
    schedule: Schedule, config: dict, club_id: str, cache: dict | None = None, db_path: Path | None = None
) -> dict | None:
    """`recommend.shorter_round_alternative()` for one day of the selected
    course, with the club's other courses scraped for that date loaded from its
    own DB (2026-10-05) -- what the Pick column shows instead of "too dark to
    finish", and what `picks_cli.py` hands the GUI as `"alternative"`.

    Gated on this day's own cached `_availability_pipeline()` result first, so
    the common case (a day with a pick) never loads a sibling schedule at all;
    only courses that could qualify (known, smaller hole count) are loaded.
    Memoized in the same `cache` as the pipeline, under its own
    ("alternative", date, course) key. `db_path` defaults to the club's own DB;
    `picks_cli.py` passes its `--db-path`."""
    key = ("alternative", schedule.date, schedule.course)
    if cache is not None and key in cache:
        return cache[key]
    candidates, playable = _availability_pipeline(schedule, config, club_id, cache)
    alternative = None
    selected_holes = _holes_from_course_label(schedule.course)
    if (
        candidates
        and not playable
        and selected_holes is not None
        and recommend.unplayable_reasons(candidates, [schedule], config) == {"daylight"}
    ):
        path = db_path if db_path is not None else _db_path(club_id)
        by_course = {schedule.course: schedule}
        for course in storage.courses_scraped_on(schedule.date, path=path):
            holes = _holes_from_course_label(course)
            if course == schedule.course or holes is None or holes >= selected_holes:
                continue
            sibling = storage.load_latest_schedule(course, schedule.date, path=path)
            if sibling is not None:
                by_course[course] = sibling
        if len(by_course) > 1:
            alternative = recommend.shorter_round_alternative(
                schedule.date,
                schedule.course,
                by_course,
                config,
                friend_names=storage.load_friend_names(path=path),
                known_handicaps=storage.load_known_handicaps(path=path),
                my_handicap=storage.load_my_handicap(path=path),
            )
    if cache is not None:
        cache[key] = alternative
    return alternative


def _too_late_for_daylight(slot_time: str, schedule: Schedule, config: dict) -> bool:
    """Would a round starting at `slot_time`, at this club's own estimated pace for
    the active course (`recommend._round_duration_minutes()`) plus your configured
    `daylight_buffer_minutes`, finish before sunset? Added 2026-09-09, direct
    request: "It would also be great if you could immediately see in the detailed
    view, which of the timeslots are already too late until sunset."

    Deliberately independent of whether `availability` is configured at all —
    unlike the ★ recommendation (`_availability_pipeline()`), this is a plain
    physics fact about the slot, not a judgment against your own standing rules, so
    it has to work identically on a club you haven't set any preferences for yet.
    Reuses `recommend._round_duration_minutes()`/`playability.is_playable()`
    directly rather than a second, hand-rolled duration/buffer calculation — so this
    marker can never disagree with what `exclude_unplayable()` already uses to
    decide the same question for the ★ system. `False` (not "too late") with no
    `sun_times` at all — unknown, not assumed bad, same stance
    `recommend._fails_playability()` already takes."""
    if schedule.sun_times is None:
        return False
    duration = recommend._round_duration_minutes(schedule.course, config)
    buffer_minutes = config.get("daylight_buffer_minutes", 0)
    return not playability.is_playable(slot_time, schedule.sun_times.sunset, duration, buffer_minutes)


def _recommended_times_for(
    schedule: Schedule, config: dict, club_id: str, cache: dict | None = None
) -> set[str]:
    """Thin wrapper around `_availability_pipeline()` returning just the still-
    playable slot times — factored out 2026-09-14 (ROADMAP.md's queued "nested/
    collapsed overview" item) once `OverviewScreen`'s own expanded slot rows
    needed the exact same ★ computation `DayDetailScreen._recommended_times()`
    already did, without a `Screen` instance to hang it off of. That method is now
    a one-line delegate to this."""
    _, playable = _availability_pipeline(schedule, config, club_id, cache)
    return {candidate.slot.time for candidate in playable}


# {(country_code, year): holidays} -- a plain process-lifetime cache, not
# calendar_context.fetch_public_holidays() re-fetching every call. Added
# 2026-09-16 alongside _compute_crowd_estimates() (see that function's own
# docstring): once the Overview's own per-slot crowd marker meant every table
# render calls _holidays_for_club() once per expanded day -- not just the rare
# ai_assist.avoid_predicted_crowd path this used to be gated behind -- an
# uncached version would mean one live Nager.Date fetch per expanded day on
# every load/refresh/expand/collapse/resize. A year's public holidays for a
# given country don't change mid-session, so caching them is exact, not an
# approximation. A failed fetch is cached too, as a float (time.monotonic() of
# the failure) instead of a list, and retried only after _HOLIDAY_RETRY_SECONDS --
# render paths call this synchronously, so an uncached failure (offline, Nager
# down, a 404 for a bad country code) used to cost a fresh network attempt on the
# UI thread on every redraw.
_HOLIDAY_CACHE: dict[tuple[str, int], list[str] | float] = {}
_HOLIDAY_RETRY_SECONDS = 600.0


def _holidays_for_year(country_code: str, year: int, fetch: bool = True) -> list[str]:
    """One (country, year) entry of `_HOLIDAY_CACHE`, fetched on a miss or once a
    cached failure is older than `_HOLIDAY_RETRY_SECONDS` -- unless `fetch` is
    False, which never touches the network (see `_holidays_for_club()`)."""
    cache_key = (country_code, year)
    cached = _HOLIDAY_CACHE.get(cache_key)
    if isinstance(cached, list):
        return cached
    if not fetch or (cached is not None and time.monotonic() - cached < _HOLIDAY_RETRY_SECONDS):
        return []
    try:
        holidays = calendar_context.fetch_public_holidays(country_code, year)
    except Exception:
        _HOLIDAY_CACHE[cache_key] = time.monotonic()
        return []
    _HOLIDAY_CACHE[cache_key] = holidays
    return holidays


def _holidays_for_club(config: dict, fetch: bool = True) -> list[str]:
    """Public holidays for a club's configured `calendar.country_code`, via the
    free Nager.Date API (calendar_context.fetch_public_holidays()), cached per
    (country, year) in `_HOLIDAY_CACHE` (see that cache's own comment). Empty list
    — not an error — with no country_code configured, or if every fetch fails;
    day-type classification still works with just tournament/weekend/workday in
    that case, the same graceful-degradation every other optional-config feature
    here already follows (e.g. `_location_for_club()`'s own None-on-failure).

    Covers last year through next year, not just this one: the overview window
    crosses into January in late December, and the heatmap classifies the whole
    scrape history, which still holds last year's holidays after New Year.

    `fetch=False` returns only what's already cached -- for the overview's
    synchronous render, whose holidays `load_overview()`/`_finish_fresh_load()`
    warm off-thread, so a redraw never waits on Nager.Date."""
    country_code = config.get("calendar", {}).get("country_code")
    if not country_code:
        return []
    year = date_cls.fromisoformat(clock.today()).year
    holidays: set[str] = set()
    for each_year in (year - 1, year, year + 1):
        holidays.update(_holidays_for_year(country_code, each_year, fetch=fetch))
    return sorted(holidays)


# {(db path, course): (inputs fingerprint, heatmap)} -- one entry per course, so this
# stays bounded no matter how long a session runs. Added 2026-09-17 after profiling
# the real app against real data: analytics.crowd_heatmap() walks every date ever
# scraped for a course and loads each one's latest schedule, measured at ~15ms against
# a 1.3MB database, and _render_table() called it once per *expanded day* -- five days
# open meant ~75ms of identical full-history scanning on every single render, and a
# render happens on every expand, collapse, confirm, cancel, resize and refresh.
#
# The heatmap only changes when the database does, so the cache key is the file's own
# (mtime_ns, size) fingerprint plus the holiday/vacation inputs -- exact invalidation
# rather than a timeout, so a fresh scrape is picked up on the very next render with no
# staleness window at all.
_HEATMAP_CACHE: dict[tuple[str, str], tuple] = {}


def _cached_crowd_heatmap(
    course: str, holidays: list[str], vacation_ranges: list[DateRange], db_path: Path
) -> dict:
    """`analytics.crowd_heatmap()`, memoized on the database's own fingerprint — see
    `_HEATMAP_CACHE` above for the measured cost this exists to remove. Falls straight
    through to an uncached call if the database can't be stat'd (it may not exist yet on
    a first run), since a missing file is exactly the case where there's nothing worth
    caching anyway."""
    try:
        stat = db_path.stat()
    except OSError:
        return analytics.crowd_heatmap(course, holidays, vacation_ranges, path=db_path)
    inputs = (
        stat.st_mtime_ns,
        stat.st_size,
        tuple(holidays),
        tuple((vr.start, vr.end) for vr in vacation_ranges),
    )
    cache_key = (str(db_path), course)
    cached = _HEATMAP_CACHE.get(cache_key)
    if cached is not None and cached[0] == inputs:
        return cached[1]
    heatmap = analytics.crowd_heatmap(course, holidays, vacation_ranges, path=db_path)
    _HEATMAP_CACHE[cache_key] = (inputs, heatmap)
    return heatmap


def _vacation_ranges_for_club(config: dict) -> list[DateRange]:
    """A club's hand-entered `calendar.vacation_ranges` (see clubs/club.example.yaml)
    as real DateRange objects, ready for calendar_context.classify_day(). Empty list
    with nothing configured, same as _holidays_for_club()."""
    ranges = config.get("calendar", {}).get("vacation_ranges") or []
    return [DateRange(start=r["start"], end=r["end"], label=r.get("label", "")) for r in ranges]
