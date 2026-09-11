import asyncio
import threading

import pytest
from textual.app import App
from textual.geometry import Offset
from textual.widgets import DataTable, Input, Label, OptionList, Select, Static

from src import env_file, i18n, scrape_once, storage, theme, tui, user_config
from src.club_config import list_clubs as _real_list_clubs
from src.club_config import load_club_config as _real_load_club_config
from src.club_config import save_club_config as _real_save_club_config
from src.models import ConfirmedBooking, DateRange, Schedule, Slot, SunTimes, WeatherPoint


@pytest.fixture(autouse=True)
def _english_ui(monkeypatch, tmp_path):
    """Every test here reads English UI text unless it explicitly switches language
    itself — i18n's "current language" is deliberate module-level global state (see
    i18n.py's docstring), so without this a test that switches to German would leak
    that choice into every test that runs afterward in the same pytest process, and a
    fresh test would otherwise resolve its language from this machine's real locale
    env vars / real ~/.config/teetime-monitor/config, not a hermetic default."""
    monkeypatch.setattr(i18n, "CONFIG_FILE", tmp_path / "not-used-unless-a-test-wants-it")
    i18n.set_language("en")
    yield
    i18n._current_language = None


@pytest.fixture(autouse=True)
def _no_background_scraping(monkeypatch):
    """`TeetimeApp._periodic_scrape()` (added 2026-09-07) fires once automatically as
    soon as `TeetimeApp._start()` finishes — every test here that builds a real
    `TeetimeApp()` would otherwise kick off a real background-thread scrape against
    the live pc caddie site (real club_id "0000001" used throughout this file), since
    none of those tests otherwise mock scraper.py. Caught live: the full test suite's
    runtime jumped from ~15s to over a minute once this shipped, before this fixture
    was added. A no-op by default; a test that specifically wants to exercise the
    real wiring overrides `scrape_once.scrape_due_for_club` itself locally."""
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: [])


@pytest.fixture(autouse=True)
def _no_real_global_preferences_file(monkeypatch, tmp_path):
    """`global_preferences.py` (added 2026-09-08, once availability/preferences
    became shared across every club rather than per-club) is read by
    `OverviewScreen`/`DayDetailScreen` on every load, and written by `SettingsScreen`
    on save — both default to the real `~/.config/teetime-monitor/preferences.yaml`
    when nothing overrides them. Caught live: a test that pressed `e`, edited a field,
    and clicked save wrote for real to this developer's own home directory before
    this fixture existed. Redirects the default to a throwaway path for every test
    here; a test exercising the real file explicitly overrides this locally."""
    monkeypatch.setattr(tui.global_preferences, "PREFERENCES_FILE", tmp_path / "preferences.yaml")


@pytest.fixture(autouse=True)
def _no_real_env_file(monkeypatch, tmp_path):
    """`ClubBrowserScreen` (2026-09-09: "I want login setup within the tui directly
    when you run it") now pushes a real `CredentialsScreen()` with no explicit path,
    which defaults to `env_file.ENV_FILE` -- plain `.env` relative to CWD, the real
    repo root when pytest runs. Same class of risk `_no_real_global_preferences_file`
    above already guards against for a different file; a test that clicks Save here
    would otherwise write to this developer's own real `.env`. `CredentialsScreen`
    reads these live at construction time, not a frozen default, so patching the
    module attribute is enough -- no need to also pass explicit paths through."""
    monkeypatch.setattr(env_file, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(env_file, "ENV_EXAMPLE_FILE", tmp_path / ".env.example")


@pytest.fixture(autouse=True)
def _no_real_club_config_by_default(monkeypatch):
    """`DayDetailScreen._recommended_times()` (added 2026-09-07) calls
    `club_config.load_club_config(self.club_slug)` on every `load_schedule()` --
    every test here built via `_day_detail()` directly (not through a real
    `TeetimeApp`) never mocks that, and `_day_detail()`'s own default slug
    ("musterhausen") happens to match a real file this developer's own machine has
    on disk at `clubs/musterhausen.yaml` — meaning every such test would otherwise
    silently read real personal config off disk instead of running hermetically.
    Defaults to an empty config (no availability rules configured -> nothing gets
    marked recommended, the same as a genuinely blank club); a test that wants to
    exercise the recommendation-marking feature itself overrides this locally,
    same layering as `_no_background_scraping` above."""
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: {})


@pytest.fixture(autouse=True)
def _fake_course_aliases_by_default(monkeypatch):
    """`TeetimeApp._start()`/`_do_switch_club_or_course()` (both updated 2026-09-07,
    see scraper.py's module docstring on why a club's own course list can no longer be
    assumed from a hardcoded constant) call `fetch_course_aliases(club_id)` live --
    every test here that builds a real `TeetimeApp()` would otherwise make a real
    network request against the live pc caddie site (real club_id "0000001" used
    throughout this file, same test-isolation gap as `_no_background_scraping` above)
    for every single course-picking step. Defaults to Musterhausen's own confirmed
    real course set; a test exercising a *different* club's own courses (e.g. the
    switch-flow tests that add a second, distinct club) overrides this locally."""
    monkeypatch.setattr(
        tui, "fetch_course_aliases", lambda club_id: {"18 Loch Tee 1": "COUB", "9 Loch Tee 1": "COU1", "6 Loch Platz": "COU6"}
    )


@pytest.fixture(autouse=True)
def _some_credentials_by_default(monkeypatch):
    """`TeetimeApp._start()` (2026-09-10: "I want the login screen to appear first,
    whenever you don't have a login") now pushes `CredentialsScreen` before
    `ClubBrowserScreen` whenever `club_directory.credentials_configured()` is False --
    every test here that builds a real `TeetimeApp()` and expects to land straight
    on `ClubBrowserScreen` would otherwise depend on whether *this developer's own
    real machine* happens to have real `PCC_USER`/`PCC_PASS` set (it does, for
    actual day-to-day use of this app -- exactly the kind of environment-dependent
    flakiness that stayed invisible here until enough tests exercised a real
    `TeetimeApp` to notice it only sometimes failing). Defaults to "configured" so
    the credentials screen doesn't show unless a test explicitly wants it to; a test
    exercising the missing-credentials path itself overrides this locally (see
    `test_club_browser_r_pushes_credentials_screen_when_none_configured`).

    Patches both `any_credentials()` (needs a favorited club to pair credentials
    with -- see that function's own docstring) and `credentials_configured()` (the
    plain "are PCC_USER/PCC_PASS set at all" check, added 2026-09-10 once real,
    working credentials with zero favorited clubs turned out to make
    `any_credentials()` alone report "not configured" forever -- see that function's
    docstring for the real bug this fixed) so both report "configured" by default."""
    monkeypatch.setattr(tui.club_directory, "any_credentials", lambda: ("0000001", "user", "pass"))
    monkeypatch.setattr(tui.club_directory, "credentials_configured", lambda: True)


@pytest.fixture(autouse=True)
def _no_real_seed_directory_by_default(monkeypatch):
    """`ClubBrowserScreen.on_mount()` (2026-09-10, see club_directory.py's own "#4"
    note) falls back to `club_directory.load_seed_directory()` whenever the real
    cache is empty -- and that function resolves its default path from `__file__`,
    an absolute path anchored to the actual installed module, not CWD, so it finds
    the real ~1300-entry bundled `club_directory_seed.json` regardless of any test's
    own directory isolation. Every test here that doesn't explicitly care about seed
    behavior would otherwise silently load that real file. Defaults to empty so
    `self._directory` stays exactly whatever `load_cached_directory()` returned,
    same as every test here already assumed before the seed fallback existed; tests
    exercising the seed fallback itself override this locally."""
    monkeypatch.setattr(tui.club_directory, "load_seed_directory", lambda *a, **k: [])


@pytest.fixture(autouse=True)
def _no_real_last_active_club_by_default(monkeypatch, tmp_path):
    """`TeetimeApp._start()` (2026-09-10, see global_preferences.
    load_last_active_club()'s own docstring) now checks for a remembered last-used
    club/course on every launch -- and that function reads `user_config.CONFIG_FILE`
    directly, a real shared file (`~/.config/teetime-monitor/config`) that patching
    `theme.CONFIG_FILE` alone does *not* isolate from (that's a separate, aliased
    copy of the same Path, captured once at theme.py's own import time -- patching
    it doesn't reach code that reads `user_config.CONFIG_FILE` itself). Every test
    here that builds a real `TeetimeApp()` would otherwise read/write this
    developer's own real file -- caught live while building this exact feature, the
    same class of leak this project has hit and fixed more than once before."""
    monkeypatch.setattr(user_config, "CONFIG_FILE", tmp_path / "user-config-for-last-active")


@pytest.fixture(autouse=True)
def _fake_available_dates_by_default(monkeypatch):
    """`OverviewScreen.load_overview()` (added 2026-09-07) calls
    `fetch_available_dates(club_id)` live to know which of its day-rows are actually
    open for booking -- every test here that reaches a real `OverviewScreen` would
    otherwise make a real network request, same test-isolation gap as
    `_fake_course_aliases_by_default` above. Defaults to "every attempted date is
    open" (an empty real fetch result also means this, per that function's own
    fallback, so this mirrors the common case) rather than a fixed list, since tests
    seed schedules for whatever dates they need regardless."""
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])


@pytest.fixture(autouse=True)
def _no_real_geocoding_by_default(monkeypatch):
    """`club_config.add_favorite()` (via `new_club_stub_with_location()`, added
    2026-09-08) calls `geocode.find_club_location()` on every save -- most tests in
    this file mock `add_favorite()`/`club_config` itself entirely and never reach
    real code here, but a test that deliberately exercises the real favoriting path
    (e.g. to confirm `_favorites()` supplies the right name to it) would otherwise
    risk a real network request to the live Nominatim service, same test-isolation
    gap already caught and fixed in test_club_picker.py/test_club_config.py.
    Defaults to "nothing found" (`None`)."""
    monkeypatch.setattr(tui.club_config.geocode, "find_club_location", lambda name: None)


class _HostApp(App):
    """Minimal App that just pushes one screen — Textual screens need a running App to
    mount into; this stands in for the real TeetimeApp so each screen can be tested in
    isolation."""

    def __init__(self, screen):
        super().__init__()
        self._screen_to_push = screen
        self.result = "not dismissed yet"

    def on_mount(self):
        self.push_screen(self._screen_to_push, self._capture_result)

    def _capture_result(self, result):
        self.result = result


def _run(coro):
    asyncio.run(coro)


def _day_detail(club_id="0000001", club_slug="musterhausen", course="18 Loch Tee 1", date="2026-09-06"):
    return tui.DayDetailScreen(club_id, club_slug, course, date)


async def _reach_overview(app, pilot, club_id="0000001"):
    """Drive the club-first startup flow (2026-09-07) up to the multi-day overview --
    the app's actual home screen once a club/course is picked.

    Opens on `ClubBrowserScreen` here because every test using this helper leaves
    `global_preferences.load_last_active_club()` at its autouse-fixture default of
    "nothing remembered yet" (see `_no_real_last_active_club_by_default`) -- a real
    launch with a remembered club/course instead skips straight to `OverviewScreen`
    (2026-09-10, see `TeetimeApp._resume_last_active()`'s own docstring)."""
    await pilot.pause()
    assert isinstance(app.screen, tui.ClubBrowserScreen)
    app.screen.dismiss(club_id)
    await pilot.pause()
    await pilot.pause()
    assert isinstance(app.screen, tui.OverviewScreen)


async def _reach_day_detail(app, pilot, club_id="0000001"):
    """As `_reach_overview()`, then drills into the first day row -- for the many
    existing tests written against `DayDetailScreen` directly, from before
    `OverviewScreen` (added 2026-09-07) became the actual screen a club/course pick
    lands on."""
    await _reach_overview(app, pilot, club_id)
    table = app.screen.query_one(DataTable)
    table.focus()  # cursor already defaults to row 0 -- today's own row
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


# --- _initial_date -- opens on tomorrow instead of today once today's own cached
# schedule shows every slot has already passed (direct feedback 2026-09-07: showing
# "today" once the course has closed for the day isn't useful) ------------------------


def test_initial_date_returns_today_when_no_cached_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    assert tui._initial_date("0000001", "18 Loch Tee 1") == tui._TODAY()


def test_initial_date_returns_today_when_a_slot_is_still_upcoming(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "14:00")
    schedule = Schedule(date=tui._TODAY(), course="18 Loch Tee 1", slots=[Slot(time="15:00", booked=0, capacity=4)])
    storage.save_schedule(schedule, path=scrape_once._db_path("0000001"))

    assert tui._initial_date("0000001", "18 Loch Tee 1") == tui._TODAY()


def test_initial_date_returns_tomorrow_when_every_slot_has_passed(tmp_path, monkeypatch):
    from datetime import date as date_cls
    from datetime import timedelta

    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "22:00")
    schedule = Schedule(date=tui._TODAY(), course="18 Loch Tee 1", slots=[Slot(time="19:50", booked=0, capacity=4)])
    storage.save_schedule(schedule, path=scrape_once._db_path("0000001"))

    expected = (date_cls.fromisoformat(tui._TODAY()) + timedelta(days=1)).isoformat()
    assert tui._initial_date("0000001", "18 Loch Tee 1") == expected


def test_initial_date_ignores_a_different_course(tmp_path, monkeypatch):
    # Every slot passed, but for a different course -- today's own course has no
    # cached schedule yet, so this should still return today, not tomorrow.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "22:00")
    schedule = Schedule(date=tui._TODAY(), course="9 Loch Tee 1", slots=[Slot(time="19:50", booked=0, capacity=4)])
    storage.save_schedule(schedule, path=scrape_once._db_path("0000001"))

    assert tui._initial_date("0000001", "18 Loch Tee 1") == tui._TODAY()


# --- DayDetailScreen ------------------------------------------------------------------


def test_day_detail_screen_keeps_switcher_and_legend_fixed_with_many_slots(tmp_path, monkeypatch):
    # Direct feedback, 2026-09-11: "can you please fixate following two areas
    # in detailed view? 1) area until table header 2) area from legend to
    # bottom". Real bug found live: #table had no height constraint, so a day
    # with many slots (every 10 minutes across a whole opening window is 80+
    # rows) made the table taller than the viewport -- Screen's own default
    # "just scroll the whole thing" fallback kicked in, dragging the switcher
    # at the top and the legend/footer at the bottom out of view right along
    # with it. Fixed with height: 1fr on #table (same convention
    # SearchScreen's #search-results and ClubBrowserScreen's #club-results
    # already use), so the table alone absorbs the overflow via its own
    # built-in row scrolling.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    slots = [Slot(time=f"{h:02d}:{m:02d}", booked=0, capacity=4) for h in range(6, 20) for m in (0, 10, 20, 30, 40, 50)]
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=slots),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            screen = app.screen
            # No screen-level overflow at all -- everything fits exactly, so
            # there's nothing for the whole-screen fallback to scroll.
            assert screen.virtual_size.height == screen.size.height
            switcher_before = screen.query_one("#switcher").region
            legend_before = screen.query_one("#legend").region
            table = screen.query_one("#table", DataTable)
            table.focus()
            for _ in range(50):
                table.action_cursor_down()
            await pilot.pause()
            # The table itself absorbed all that movement internally...
            assert table.scroll_y > 0
            # ...while the areas around it never moved at all.
            assert screen.scroll_offset == Offset(0, 0)
            assert screen.query_one("#switcher").region == switcher_before
            assert screen.query_one("#legend").region == legend_before

    _run(scenario())


def test_day_detail_screen_hides_empty_banner_and_status_lines(tmp_path, monkeypatch):
    # Direct feedback, 2026-09-13: "check for spacing consistency" -- a plain
    # Static still reserves its own blank line even with nothing to show,
    # which is what made the gap above the table look inconsistent (bigger
    # once an empty #banners/#status -- and, before this same round of
    # feedback, the now-removed #daylight line -- stacked on top of each
    # other than the single blank line between the switcher's own two rows).
    # #banners/#status are now _AutoHideStatic, collapsing out of layout
    # entirely while blank.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            banners = screen.query_one("#banners")
            status = screen.query_one("#status")
            assert banners.styles.display == "none"
            assert status.styles.display == "none"

            status.update("Refreshed.")
            await pilot.pause()
            assert status.styles.display == "block"

            status.update("")
            await pilot.pause()
            assert status.styles.display == "none"

    _run(scenario())


def test_day_detail_screen_search_opens_with_the_overviews_own_schedules(tmp_path, monkeypatch):
    # Direct question, 2026-09-13: "why is adhoc search not accessible from
    # detailed view?" -- '/' now opens the same SearchScreen as the overview's
    # own, reusing that screen's already-loaded data rather than fetching
    # anything fresh.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_course_aliases", lambda club_id: {"18 Loch Tee 1": "COUB"})
    storage.save_schedule(
        Schedule(date=tui._TODAY(), course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot, club_id="0000001")
            overview = app.screen_stack[-2]
            day_detail = app.screen
            day_detail.action_search()
            await pilot.pause()
            assert isinstance(app.screen, tui.SearchScreen)
            assert app.screen.schedules is overview._schedules
            assert app.screen.club_id == "0000001"

    _run(scenario())


def test_day_detail_shows_placeholder_when_never_scraped(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert "no data yet" in row[2]  # Time/Condition/Occupancy/...

    _run(scenario())


def test_day_detail_shows_occupancy_and_players(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            slots=[
                Slot(time="06:00", booked=0, capacity=4),
                Slot(time="08:00", booked=1, capacity=4, players=["Max Mustermann"]),
                Slot(time="15:30", booked=4, capacity=4, block_reason="Golf Beginner Kurs"),
            ],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.row_count == 3
            rows = [table.get_row_at(i) for i in range(3)]
            assert rows[0][0] == "06:00" and "0/4" in rows[0][2]
            assert rows[1][0] == "08:00" and "1/4" in rows[1][2] and rows[1][3] == "Max Mustermann"
            # Time/Condition/Occupancy/Players/Temperature/Precipitation/Wind/Events
            # -- the reason lives in its own Events column (index 7), not Occupancy.
            assert rows[2][0] == "15:30" and "—" in rows[2][2] and "Golf Beginner Kurs" in rows[2][7]

    _run(scenario())


def test_day_detail_shows_a_placeholder_for_a_block_reason_with_no_label(tmp_path, monkeypatch):
    # Direct feedback (a real screenshot): "why am I seeing timeslots without any
    # occupancies?" -- a real block-time row (confirmed live, Sonnenberg 2026-09-08)
    # can have an empty label ("" -- still not real occupancy, just nothing shown on
    # the site itself to say why), which rendered as a blank, confusing-looking row
    # before this fallback existed.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            slots=[Slot(time="10:00", booked=4, capacity=4, block_reason="")],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            row = app.screen.query_one(DataTable).get_row_at(0)
            assert "not bookable" in row[7]  # Events column now, not Occupancy

    _run(scenario())


# --- Past-slot dimming (2026-09-07, direct feedback: "can you hide or make
# timeslots less visible that are in the past? ... now is 11:18, so I need a visible
# feedback that I won't be able to make reservations for 11:10 or earlier today") ----


def test_day_detail_dims_past_slots_on_todays_date(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "_TODAY", lambda: "2026-09-07")
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "11:18")
    storage.save_schedule(
        Schedule(
            date="2026-09-07",
            course="18 Loch Tee 1",
            slots=[
                Slot(time="09:00", booked=0, capacity=4),
                Slot(time="11:10", booked=1, capacity=4, players=["Max Mustermann"]),
                Slot(time="14:00", booked=2, capacity=4),
            ],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail(date="2026-09-07"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            rows = [table.get_row_at(i) for i in range(3)]
            assert rows[0][0] == "[dim]09:00[/]"
            assert rows[1][0] == "[dim]11:10[/]"
            assert rows[1][3] == "[dim]Max Mustermann[/]"
            assert rows[2][0] == "14:00"  # still upcoming -- not dimmed

    _run(scenario())


def test_day_detail_does_not_dim_slots_on_a_different_date(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    # "Today" is tomorrow relative to this screen's own date -- late in the day, so
    # every slot on this schedule would be "in the past" if the check didn't first
    # confirm this screen is even showing today at all.
    monkeypatch.setattr(tui, "_TODAY", lambda: "2026-09-08")
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "23:59")
    storage.save_schedule(
        Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="06:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail(date="2026-09-07"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.get_row_at(0)[0] == "06:00"

    _run(scenario())


def test_day_detail_dims_a_blocked_past_slot_too(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "_TODAY", lambda: "2026-09-07")
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "16:00")
    storage.save_schedule(
        Schedule(
            date="2026-09-07",
            course="18 Loch Tee 1",
            slots=[Slot(time="15:30", booked=4, capacity=4, block_reason="Golf Beginner Kurs")],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail(date="2026-09-07"))
        async with app.run_test() as pilot:
            await pilot.pause()
            row = app.screen.query_one(DataTable).get_row_at(0)
            assert row[0] == "[dim]15:30[/]"
            assert "Golf Beginner Kurs" in row[7]  # Events column now, not Occupancy

    _run(scenario())


# --- Recommended-slot marking ("★") -- a lightweight step toward real
# recommendations (ROADMAP.md Phase 3), applied to the single-day view already built
# rather than waiting on the multi-day overview screen's own mockup sign-off ----------

_RECOMMEND_CONFIG = {
    "availability": {
        "min_open_spots": 1,
        "weekday_window": {"after": "10:00"},
        "weekend_window": {"after": "10:00"},
    }
}


def test_day_detail_marks_slots_matching_availability_with_a_star(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: _RECOMMEND_CONFIG)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            slots=[
                Slot(time="09:00", booked=0, capacity=4),  # before the configured window
                Slot(time="14:00", booked=0, capacity=4),  # within the window, open
            ],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            rows = [table.get_row_at(i) for i in range(2)]
            assert rows[0][0] == "09:00"
            assert rows[1][0] == "★ 14:00"

    _run(scenario())


def test_day_detail_does_not_star_a_fully_booked_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: _RECOMMEND_CONFIG)
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=4, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one(DataTable).get_row_at(0)[0] == "14:00"

    _run(scenario())


def test_day_detail_does_not_star_a_past_matching_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: _RECOMMEND_CONFIG)
    monkeypatch.setattr(tui, "_TODAY", lambda: "2026-09-07")
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "15:00")
    storage.save_schedule(
        Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail(date="2026-09-07"))
        async with app.run_test() as pilot:
            await pilot.pause()
            row = app.screen.query_one(DataTable).get_row_at(0)
            # Still dimmed (it's past), but not starred -- recommending something
            # already gone doesn't make sense.
            assert row[0] == "[dim]14:00[/]"

    _run(scenario())


def test_day_detail_does_not_star_a_slot_with_bad_weather(tmp_path, monkeypatch):
    from src.models import WeatherPoint

    config = {
        "availability": _RECOMMEND_CONFIG["availability"],
        "preferences": {"avoid_rain": True},
    }
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: config)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            slots=[Slot(time="14:00", booked=0, capacity=4)],
            weather=[WeatherPoint(time="14:00", precipitation_probability=90, precipitation_mm=5.0)],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one(DataTable).get_row_at(0)[0] == "14:00"  # not starred

    _run(scenario())


def test_day_detail_no_availability_config_means_no_stars(tmp_path, monkeypatch):
    # The autouse _no_real_club_config_by_default fixture already returns {} by
    # default -- this test just makes that behavior explicit and named.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one(DataTable).get_row_at(0)[0] == "14:00"

    _run(scenario())


# --- Per-tee-time weather + sunrise/sunset (2026-09-08, direct feedback: "Yes per
# tee time indicator, also don't forget about the sunrise and sunset times") --------


def test_weather_point_for_time_finds_the_covering_hourly_point():
    points = [
        WeatherPoint(time="14:00", precipitation_probability=10),
        WeatherPoint(time="15:00", precipitation_probability=90),
    ]
    # 14:40 falls under the 14:00 hourly point, not 15:00 -- an hourly point covers
    # the hour starting at its own timestamp (same rule weather.py's own
    # conditions_during_round() already uses).
    assert tui._weather_point_for_time(points, "14:40").precipitation_probability == 10
    assert tui._weather_point_for_time(points, "15:10").precipitation_probability == 90


def test_weather_point_for_time_none_before_the_first_point():
    points = [WeatherPoint(time="14:00", precipitation_probability=10)]
    assert tui._weather_point_for_time(points, "13:00") is None


def test_weather_point_for_time_none_with_no_forecast_at_all():
    assert tui._weather_point_for_time([], "14:00") is None


# _slot_temperature_cell()/_slot_precipitation_cell()/_slot_wind_cell() -- split
# 2026-09-09 out of the old combined _slot_weather_cell(), direct feedback: "can you
# please split weather into Temperature, Precipitation, and wind columns (both in
# the overview and detailed view)?"


def test_slot_temperature_cell_shows_the_temperature():
    # No "°" suffix -- the column header already states the unit (2026-09-13,
    # direct follow-up: "since the units are now in the headers, we don't
    # need the units in the rows, right?").
    points = [WeatherPoint(time="14:00", temperature_c=16)]
    assert tui._slot_temperature_cell(points, "14:00") == "16"


def test_slot_temperature_cell_blank_without_a_forecast():
    assert tui._slot_temperature_cell([], "14:00") == ""


def test_slot_precipitation_cell_shows_a_rain_icon_past_the_threshold():
    points = [WeatherPoint(time="14:00", precipitation_probability=90)]
    assert "🌧" in tui._slot_precipitation_cell(points, "14:00")


def test_slot_precipitation_cell_shows_the_actual_probability_and_amount():
    # Direct follow-up, 2026-09-08: "I don't see chance of rain or amount of rain
    # though" -- still holds now that this is its own dedicated column: the real
    # numbers show unconditionally, the icon is layered on top once above threshold.
    points = [WeatherPoint(time="14:00", precipitation_probability=70, precipitation_mm=1.5)]
    cell = tui._slot_precipitation_cell(points, "14:00")
    assert "70%" in cell
    assert "1.5mm" in cell


def test_slot_precipitation_cell_omits_amount_when_none_fell():
    points = [WeatherPoint(time="14:00", precipitation_probability=90, precipitation_mm=0.0)]
    cell = tui._slot_precipitation_cell(points, "14:00")
    assert "90%" in cell
    assert "mm" not in cell


def test_slot_precipitation_cell_shows_the_real_number_below_threshold_too():
    # A dedicated Precipitation column shows the real number always now, not just
    # once the icon threshold fires -- the whole point of splitting this out.
    points = [WeatherPoint(time="14:00", precipitation_probability=5, precipitation_mm=0.0)]
    cell = tui._slot_precipitation_cell(points, "14:00")
    assert cell == "5%"
    assert "🌧" not in cell


def test_slot_precipitation_cell_blank_without_a_forecast():
    assert tui._slot_precipitation_cell([], "14:00") == ""


def test_slot_wind_cell_shows_a_wind_icon_past_the_threshold():
    points = [WeatherPoint(time="14:00", wind_speed_kph=45)]
    assert "💨" in tui._slot_wind_cell(points, "14:00")


def test_slot_wind_cell_shows_the_actual_wind_speed():
    # No "km/h" suffix -- the column header already states the unit
    # (2026-09-13, same follow-up as _slot_temperature_cell()'s own test).
    points = [WeatherPoint(time="14:00", wind_speed_kph=45)]
    assert "45" in tui._slot_wind_cell(points, "14:00")


def test_slot_wind_cell_shows_the_real_number_below_threshold_too():
    points = [WeatherPoint(time="14:00", wind_speed_kph=5)]
    cell = tui._slot_wind_cell(points, "14:00")
    assert cell == "5"
    assert "💨" not in cell


def test_slot_wind_cell_blank_without_a_forecast():
    assert tui._slot_wind_cell([], "14:00") == ""


# --- units="imperial" -- direct feedback, 2026-09-13: "Can we adjust format
# (metric/imperial) in settings?" ----------------------------------------------


def test_slot_temperature_cell_converts_to_fahrenheit_in_imperial():
    points = [WeatherPoint(time="14:00", temperature_c=0)]
    assert tui._slot_temperature_cell(points, "14:00", units="imperial") == "32"


def test_slot_wind_cell_converts_to_mph_in_imperial():
    points = [WeatherPoint(time="14:00", wind_speed_kph=16)]  # below the icon threshold
    assert tui._slot_wind_cell(points, "14:00", units="imperial") == "10"


def test_slot_wind_cell_icon_threshold_still_checks_the_real_kph_value():
    # The icon threshold is an internal "worth noticing" cutoff in km/h, not
    # something a user sets in either unit -- converting the *display* number
    # must not also shift which slots get the icon.
    points = [WeatherPoint(time="14:00", wind_speed_kph=35)]  # above the kph threshold
    cell = tui._slot_wind_cell(points, "14:00", units="imperial")
    assert "💨" in cell
    assert "22" in cell  # 35kph -> ~22mph


def test_slot_precipitation_cell_converts_to_inches_in_imperial():
    points = [WeatherPoint(time="14:00", precipitation_probability=70, precipitation_mm=25.4)]
    cell = tui._slot_precipitation_cell(points, "14:00", units="imperial")
    assert "70%" in cell
    assert "1.00in" in cell


def test_slot_event_cell_shows_the_block_reason():
    slot = Slot(time="15:30", booked=4, capacity=4, block_reason="Golf Beginner Kurs")
    assert tui._slot_event_cell(slot) == "📋 Golf Beginner Kurs"


def test_slot_event_cell_placeholder_for_a_blank_reason():
    slot = Slot(time="10:00", booked=4, capacity=4, block_reason="")
    assert tui._slot_event_cell(slot) == f"📋 {i18n.t('table.not_bookable')}"


def test_slot_event_cell_empty_for_a_normal_slot():
    slot = Slot(time="09:00", booked=0, capacity=4)
    assert tui._slot_event_cell(slot) == ""


def test_day_detail_table_shows_temperature_precipitation_wind_and_events_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            slots=[
                Slot(time="14:00", booked=0, capacity=4),
                Slot(time="15:30", booked=4, capacity=4, block_reason="Golf Beginner Kurs"),
            ],
            weather=[
                WeatherPoint(
                    time="14:00", precipitation_probability=90, wind_speed_kph=40, temperature_c=16, weather_code=61
                ),
            ],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            headers = [str(col.label) for col in table.columns.values()]
            assert headers == [
                "Time", "Condition", "Occupancy", "Players", "Temperature (°C)", "Precipitation (%/mm)",
                "Wind (km/h)", "Events",
            ]
            open_row = table.get_row_at(0)
            # No "°"/"km/h" suffix on Temperature/Wind -- the column header
            # already states the unit (2026-09-13, direct follow-up: "since
            # the units are now in the headers, we don't need the units in
            # the rows, right?"). Precipitation keeps its own suffixes, since
            # that cell packs two different numbers together.
            assert open_row[1] == "🌧️"  # weather_code=61 -> rain icon
            assert open_row[4] == "16"
            assert "90%" in open_row[5]
            assert "40" in open_row[6]
            assert open_row[7] == ""
            blocked_row = table.get_row_at(1)
            assert "Golf Beginner Kurs" in blocked_row[7]

    _run(scenario())


def test_day_detail_notes_sunrise_and_sunset_on_their_nearest_rows(tmp_path, monkeypatch):
    # Direct feedback, 2026-09-13: "make sunrise and sunset to corresponding
    # rows" -- replacing the old standalone #daylight summary line (see
    # test_day_detail_shows_sunrise_and_sunset in this file's own history).
    # Plain wording plus the exact time in the Events column, not an icon in
    # Time (2026-09-13, same-day follow-up on this very feature: "i don't like
    # the icons for sunrise/sunset (just use the proper terms instead in
    # events with exact time)").
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            slots=[Slot(time=t, booked=0, capacity=4) for t in ("06:00", "06:30", "07:00", "19:30", "20:00")],
            sun_times=SunTimes(sunrise="06:50", sunset="19:58"),  # closest to 07:00 and 20:00 respectively
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            rows = [table.get_row_at(i) for i in range(table.row_count)]
            # Index matches slots' own order: 06:00, 06:30, 07:00, 19:30, 20:00.
            # Time column stays plain -- no icon.
            assert rows[2][0] == "07:00"
            assert rows[2][7] == i18n.t("events.sunrise", time="06:50")
            # 20:00 is already past sunset, so it also carries its own separate
            # 🌙 "too late to finish" Time marker -- independent of the Events
            # column note, not combined into one cell any more.
            assert rows[4][0] == "🌙 20:00"
            assert rows[4][7] == i18n.t("events.sunset", time="19:58")
            # Nowhere else.
            for i in (0, 1, 3):
                assert rows[i][7] == ""

    _run(scenario())


def test_day_detail_marks_the_confirmed_bookings_own_row(tmp_path, monkeypatch):
    # Direct question, 2026-09-13: "why don't i see confirmed tee times in
    # detailed view, but only in overview?" -- _day_pick_text() already does
    # the day-level equivalent for OverviewScreen's own Pick column; nothing
    # mirrored it at the per-slot level here until now.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            slots=[Slot(time="09:00", booked=0, capacity=4), Slot(time="09:10", booked=0, capacity=4)],
        ),
        path=scrape_once._db_path("0000001"),
    )
    storage.save_confirmed_booking(
        ConfirmedBooking(date="2026-09-06", course="18 Loch Tee 1", time="09:00", holes=18, source="manual"),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            rows = [table.get_row_at(i) for i in range(2)]
            assert f"📌 {i18n.t('overview.booked')}" in rows[0][7]
            assert rows[1][7] == ""

    _run(scenario())


def test_day_detail_has_no_sunrise_sunset_markers_without_sun_times(tmp_path, monkeypatch):
    # An unconfigured `location` (or nothing scraped yet) -- no markers at all,
    # not a fabricated or stale sunrise/sunset guess.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            row = app.screen.query_one(DataTable).get_row_at(0)
            assert row[0] == "14:00"

    _run(scenario())


def test_day_detail_action_confirm_prefills_clean_time_for_a_starred_slot(tmp_path, monkeypatch):
    # Regression test: the confirm form must get the plain "14:00" back, never the
    # decorated "★ 14:00" that's actually rendered in the table.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: _RECOMMEND_CONFIG)
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.get_row_at(0)[0] == "★ 14:00"  # sanity check
            table.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.query_one("#time", Input).value == "14:00"

    _run(scenario())


def test_day_detail_action_confirm_offers_to_cancel_the_already_confirmed_row(tmp_path, monkeypatch):
    # Direct question, 2026-09-13: "why can you confirm tee time within the
    # TUI, but cannot cancel or modify?" -- pressing enter on the row that's
    # already your confirmed booking should offer to cancel it instead of
    # opening a fresh confirm form for the exact same date/course/time.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )
    storage.save_confirmed_booking(
        ConfirmedBooking(date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="manual", confirmed_at="t1"),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one(DataTable).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.CancelBookingScreen)
            assert "14:00" in str(app.screen.query_one(Label).content)

    _run(scenario())


def test_day_detail_action_confirm_opens_a_fresh_form_for_a_different_row(tmp_path, monkeypatch):
    # A confirmed booking exists, but it's for a different time than the row
    # currently highlighted -- still the ordinary confirm form, not the cancel
    # screen (cancelling only ever targets the row that's actually confirmed).
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            slots=[Slot(time="14:00", booked=0, capacity=4), Slot(time="15:00", booked=0, capacity=4)],
        ),
        path=scrape_once._db_path("0000001"),
    )
    storage.save_confirmed_booking(
        ConfirmedBooking(date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="manual", confirmed_at="t1"),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            table.move_cursor(row=1)  # the 15:00 row
            table.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.ConfirmBookingScreen)
            assert app.screen.query_one("#time", Input).value == "15:00"

    _run(scenario())


def test_cancel_booking_screen_keep_dismisses_without_changing_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )
    storage.save_confirmed_booking(
        ConfirmedBooking(date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="manual", confirmed_at="t1"),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one(DataTable).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.CancelBookingScreen)
            await pilot.click("#keep")
            await pilot.pause()
            assert isinstance(app.screen, tui.DayDetailScreen)

    _run(scenario())

    saved = storage.load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001"))
    assert saved.time == "14:00"  # untouched


def test_cancel_booking_screen_confirm_writes_the_not_playing_sentinel(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="14:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )
    storage.save_confirmed_booking(
        ConfirmedBooking(
            date="2026-09-06", course="18 Loch Tee 1", time="14:00", source="my_reservations", confirmed_at="t1"
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one(DataTable).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.CancelBookingScreen)
            await pilot.click("#confirm-cancel")
            await pilot.pause()
            assert isinstance(app.screen, tui.DayDetailScreen)
            # The row's own 📌 marker is gone now that there's nothing confirmed.
            assert app.screen.query_one(DataTable).get_row_at(0)[6] == ""

    _run(scenario())

    saved = storage.load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001"))
    assert saved.time is None
    assert saved.source == "manual"  # a human decided this via the app, not the automatic sync


def test_day_detail_shows_and_dismisses_booking_watch_banner(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_booking_change(
        course="18 Loch Tee 1",
        date="2026-09-06",
        time="14:00",
        kind="party_grew",
        message="1 more player joined your 14:00 tee time since you booked",
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            banner = app.screen.query_one("#banners", Static)
            assert "1 more player" in str(banner.content)

            await pilot.press("x")
            await pilot.pause()
            banner = app.screen.query_one("#banners", Static)
            assert str(banner.content) == ""

    _run(scenario())

    remaining = storage.load_unacknowledged_booking_changes(path=scrape_once._db_path("0000001"))
    assert remaining == []


def test_day_detail_next_and_prev_day_reload_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    # Neither fixture date is "today" -- avoids load_schedule()'s past-slot dimming
    # (see the dedicated tests for that below), which would otherwise collide with
    # this test's own exact-text assertions once "today" catches up to 2026-09-07.
    monkeypatch.setattr(tui, "_TODAY", lambda: "2099-01-01")
    db = scrape_once._db_path("0000001")
    storage.save_schedule(
        Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="06:00", booked=0, capacity=4)]),
        path=db,
    )
    storage.save_schedule(
        Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="07:00", booked=1, capacity=4)]),
        path=db,
    )

    async def scenario():
        app = _HostApp(_day_detail(date="2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.get_row_at(0)[0] == "07:00"

            await pilot.press("p")
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.get_row_at(0)[0] == "06:00"

    _run(scenario())


def test_day_detail_refresh_scrapes_and_saves(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    fake_schedule = Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=2, capacity=4)])
    monkeypatch.setattr(tui, "scrape_schedule", lambda club_id, course, date: fake_schedule)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.get_row_at(0)[0] == "09:00"
            assert app.screen.query_one("#status", Static).content == "Refreshed."

    _run(scenario())

    loaded = storage.load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001"))
    assert loaded.slots[0].booked == 2


def test_day_detail_refresh_also_attaches_weather(tmp_path, monkeypatch):
    # Real regression caught live, 2026-09-08, while verifying the new per-slot
    # weather column: this manual 'r' path never called _attach_weather() at all,
    # so pressing it would silently overwrite any previously-attached weather/
    # sun_times with a weather-less schedule (storage.py's "latest scrape wins"
    # rule) -- undoing the whole point of persisting sun_times, from the single
    # most ordinary action on this screen.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    fake_schedule = Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=2, capacity=4)])
    monkeypatch.setattr(tui, "scrape_schedule", lambda club_id, course, date: fake_schedule)

    calls = []

    def fake_attach_weather(schedule, config, club_id, course, date):
        calls.append((club_id, course, date))
        schedule.sun_times = SunTimes(sunrise="06:42", sunset="19:58")

    monkeypatch.setattr(tui, "_attach_weather", fake_attach_weather)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()

    _run(scenario())

    assert calls == [("0000001", "18 Loch Tee 1", "2026-09-06")]
    loaded = storage.load_latest_schedule("18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001"))
    assert loaded.sun_times == SunTimes(sunrise="06:42", sunset="19:58")


def test_day_detail_refresh_failure_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    def broken_scrape(club_id, course, date):
        raise RuntimeError("no network")

    monkeypatch.setattr(tui, "scrape_schedule", broken_scrape)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            assert "Refresh failed" in str(app.screen.query_one("#status", Static).content)

    _run(scenario())


def test_day_detail_confirm_booking_persists_and_reloads(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one(DataTable).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            app.screen.query_one("#time", Input).value = "14:00"
            app.screen.query_one("#holes", Input).value = "18"
            await pilot.click("#save")
            await pilot.pause()

    _run(scenario())

    booking = storage.load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001"))
    assert booking is not None
    assert booking.time == "14:00"
    assert booking.holes == 18
    assert booking.source == "manual"


def test_confirm_booking_requires_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            assert "Enter a time" in str(app.screen.query_one("#confirm-status", Static).content)
            assert app.result == "not dismissed yet"

    _run(scenario())


def test_confirm_booking_rejects_non_numeric_holes(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#time", Input).value = "14:00"
            app.screen.query_one("#holes", Input).value = "nine"
            await pilot.click("#save")
            await pilot.pause()

            assert "must be a number" in str(app.screen.query_one("#confirm-status", Static).content)

    _run(scenario())


def test_confirm_booking_cancel_dismisses_without_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#cancel")
            await pilot.pause()
            assert app.result is False

    _run(scenario())

    booking = storage.load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001"))
    assert booking is None


def test_confirm_booking_escape_dismisses_without_saving(tmp_path, monkeypatch):
    # Found in a dedicated bug hunt (2026-09-10): this screen had no BINDINGS at
    # all -- escape did nothing, unlike every other screen in this app.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.result is False

    _run(scenario())

    booking = storage.load_confirmed_booking("18 Loch Tee 1", "2026-09-06", path=scrape_once._db_path("0000001"))
    assert booking is None


def test_confirm_booking_footer_is_translated(tmp_path, monkeypatch):
    # Found the same bug hunt: this screen yielded a plain Footer() instead of
    # TranslatedFooter, so its key hints stayed English-only regardless of
    # i18n.set_language() -- unlike every other screen in this app.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    i18n.set_language("de")

    async def scenario():
        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            text = app.screen.query_one(tui.TranslatedFooter).render()
            assert "Zurück" in text
            assert "Beenden" in text

    _run(scenario())


# --- Pre-filled confirm form (2026-09-07, direct feedback: "I already selected a
# specific time, and the TUI should know on which course I'm currently focused") -----


def test_confirm_booking_screen_prefills_time_and_holes_when_given():
    async def scenario():
        app = _HostApp(
            tui.ConfirmBookingScreen(
                "0000001", "18 Loch Tee 1", "2026-09-06", default_time="14:00", default_holes=18
            )
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one("#time", Input).value == "14:00"
            assert app.screen.query_one("#holes", Input).value == "18"

    _run(scenario())


def test_confirm_booking_screen_leaves_fields_blank_with_no_defaults():
    async def scenario():
        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one("#time", Input).value == ""
            assert app.screen.query_one("#holes", Input).value == ""

    _run(scenario())


def test_day_detail_action_confirm_prefills_time_from_the_selected_row(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=0, capacity=4), Slot(time="14:00", booked=1, capacity=4)],
    )
    storage.save_schedule(schedule, path=scrape_once._db_path("0000001"))

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            table.move_cursor(row=1)  # the "14:00" row
            table.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.query_one("#time", Input).value == "14:00"
            # "18 Loch Tee 1" -> 18 holes, derived from the course itself.
            assert app.screen.query_one("#holes", Input).value == "18"

    _run(scenario())


def test_day_detail_action_confirm_leaves_time_blank_with_no_data_scraped_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()  # only the "no data yet" placeholder row exists
            app.screen.query_one(DataTable).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.query_one("#time", Input).value == ""

    _run(scenario())


def test_day_detail_action_confirm_derives_holes_from_a_nine_hole_course(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail(course="9 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one(DataTable).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.query_one("#holes", Input).value == "9"

    _run(scenario())


def test_day_detail_escape_pops_back_to_the_overview_and_reloads_it(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        overview = tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1")
        app = _HostApp(overview)
        async with app.run_test() as pilot:
            await pilot.pause()
            reload_calls = []
            monkeypatch.setattr(overview, "load_overview", lambda: reload_calls.append("reload"))
            await app.push_screen(_day_detail())
            await pilot.pause()
            assert isinstance(app.screen, tui.DayDetailScreen)

            await pilot.press("escape")
            await pilot.pause()

            assert app.screen is overview
            assert reload_calls == ["reload"]

    _run(scenario())


def test_day_detail_escape_pops_quietly_with_no_overview_underneath():
    # Reached directly (a test, or any future standalone entry point) rather than
    # via OverviewScreen's own drill-down -- popping back to whatever's actually
    # there (here, the test harness's own blank base screen) must not raise, and
    # load_overview() is simply never called since it isn't an OverviewScreen.
    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, tui.DayDetailScreen)

    _run(scenario())


# --- OverviewScreen (ROADMAP.md Phase 4) -- pure helper functions first --------------


def _weather(time, prob=10, temp=20.0, mm=None, wind=None, code=None):
    return WeatherPoint(
        time=time,
        precipitation_probability=prob,
        temperature_c=temp,
        precipitation_mm=mm,
        wind_speed_kph=wind,
        weather_code=code,
    )


def test_heat_strip_blocks_colors_by_average_fill_ratio():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="08:10", booked=0, capacity=4),  # 08-10 window: open
            Slot(time="10:10", booked=2, capacity=4),  # 10-12 window: mid
            Slot(time="18:10", booked=4, capacity=4),  # 18-20 window: full
        ],
    )
    blocks = tui._heat_strip_blocks(schedule)
    assert blocks[0] == "open"
    assert blocks[1] == "mid"
    assert blocks[5] == "full"


def test_heat_strip_blocks_is_blocked_with_no_real_slot_in_the_window():
    # Nothing at all in 12-14, and an event fills every slot in 14-16 -- both read as
    # "blocked", not a fill ratio that would be meaningless (0 slots) or misleading
    # (an event isn't real occupancy, see scraper.py's module docstring).
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="14:10", booked=4, capacity=4, block_reason="Golf Beginner Kurs")],
    )
    blocks = tui._heat_strip_blocks(schedule)
    assert blocks[2] == "blocked"  # 12-14, no slot at all
    assert blocks[3] == "blocked"  # 14-16, only an event


def test_is_rain_all_day_true_when_every_daytime_point_is_wet():
    weather = [_weather("09:00", prob=80), _weather("15:00", prob=90)]
    assert tui._is_rain_all_day(weather) is True


def test_is_rain_all_day_false_when_only_part_of_the_day_is_wet():
    weather = [_weather("09:00", prob=90), _weather("15:00", prob=5)]
    assert tui._is_rain_all_day(weather) is False


def test_is_rain_all_day_false_with_no_weather_at_all():
    assert tui._is_rain_all_day([]) is False


# _temperature_cell()/_precipitation_cell()/_wind_cell()/_event_cell() -- split
# 2026-09-09 out of the old combined _day_tag_or_weather()/_weather_cell(), direct
# feedback: "It shouldn't mix up events with weather data. Can you make an extra
# column for the events?" then "can you please split weather into Temperature,
# Precipitation, and wind columns (both in the overview and detailed view)?"


def test_temperature_cell_shows_high_low():
    # No "°" suffix -- the column header already states the unit (2026-09-13,
    # direct follow-up: "since the units are now in the headers, we don't
    # need the units in the rows, right?").
    weather = [_weather("09:00", prob=5, temp=22.0), _weather("15:00", prob=10, temp=14.0)]
    assert tui._temperature_cell(weather) == "22/14"


def test_temperature_cell_blank_without_daytime_forecast():
    assert tui._temperature_cell([]) == ""


def test_precipitation_cell_shows_rain_all_day_over_a_plain_average():
    weather = [_weather("09:00", prob=95)]
    assert "rain all day" in tui._precipitation_cell(weather)


def test_precipitation_cell_shows_the_average_chance_and_total_mm():
    # Below the rain-all-day threshold (70%) so this exercises the plain average
    # branch, not the special "rain all day" phrase.
    weather = [_weather("09:00", prob=60, mm=1.0), _weather("15:00", prob=60, mm=1.0)]
    cell = tui._precipitation_cell(weather)
    assert "60%" in cell
    assert "2.0mm" in cell


def test_precipitation_cell_shows_the_real_number_below_threshold_too():
    # A dedicated column shows the real number always, not just once the icon
    # threshold fires -- the whole point of splitting this out of the old combined
    # cell (which only ever showed a number once a threshold had already fired).
    weather = [_weather("09:00", prob=5, temp=20.0)]
    cell = tui._precipitation_cell(weather)
    assert cell == "5%"
    assert "🌧" not in cell


def test_precipitation_cell_blank_without_daytime_forecast():
    assert tui._precipitation_cell([]) == ""


def test_wind_cell_shows_the_peak_daytime_wind():
    # No "km/h" suffix -- the column header already states the unit.
    weather = [_weather("09:00", wind=10), _weather("15:00", wind=40)]
    cell = tui._wind_cell(weather)
    assert "40" in cell
    assert "🌧" not in cell


def test_wind_cell_icon_only_past_the_threshold():
    calm = tui._wind_cell([_weather("09:00", wind=5)])
    windy = tui._wind_cell([_weather("09:00", wind=40)])
    assert "💨" not in calm and calm == "5"
    assert "💨" in windy and "40" in windy


def test_wind_cell_blank_without_daytime_forecast():
    assert tui._wind_cell([]) == ""


def test_temperature_cell_converts_to_fahrenheit_in_imperial():
    weather = [
        WeatherPoint(time="10:00", temperature_c=0),
        WeatherPoint(time="14:00", temperature_c=20),
    ]
    assert tui._temperature_cell(weather, units="imperial") == "68/32"


def test_wind_cell_converts_to_mph_in_imperial():
    weather = [WeatherPoint(time="14:00", wind_speed_kph=16)]  # below the icon threshold
    assert tui._wind_cell(weather, units="imperial") == "10"


def test_precipitation_cell_converts_to_inches_in_imperial():
    weather = [WeatherPoint(time="14:00", precipitation_probability=10, precipitation_mm=25.4)]
    cell = tui._precipitation_cell(weather, units="imperial")
    assert "1.00in" in cell


def test_column_header_metric_default():
    assert tui._column_header("table.temperature", "temperature", "metric") == "Temperature (°C)"


def test_column_header_imperial():
    assert tui._column_header("table.temperature", "temperature", "imperial") == "Temperature (°F)"
    assert tui._column_header("table.wind", "wind", "imperial") == "Wind (mph)"
    assert tui._column_header("table.precipitation", "precipitation", "imperial") == "Precipitation (%/in)"


def test_event_cell_shows_the_event_even_on_a_day_with_weather():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[],
        weather=[_weather("09:00", prob=5, temp=20.0)],
        events=["Herbstturnier"],
    )
    # 📋, not 🏆 -- 2026-09-08 direct feedback questioning why non-weather text
    # showed in the Weather column at all: `events` is genuinely just "the club
    # published a reason a slot isn't normally bookable," which is often a real
    # tournament but just as often a routine ladies'/members' day or a maintenance
    # closure -- nothing in the scraped data actually distinguishes the two, so a
    # trophy specifically claiming "competition" overclaimed what this can tell.
    # Changed from an earlier 📌 to 📋 2026-09-09, once that icon turned out to
    # already mean "confirmed booking" in the Pick column -- see _legend_line().
    assert tui._event_cell(schedule) == "📋 Herbstturnier"


def test_event_cell_empty_without_any_event():
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[], weather=[])
    assert tui._event_cell(schedule) == ""


def test_resolved_config_merges_global_preferences_over_club_settings(monkeypatch, tmp_path):
    # Direct feedback 2026-09-08: "i also want the settings/preferences to be global
    # and not tied to a specific club" -- availability/preferences come from the one
    # shared file regardless of which club's own config is loaded alongside it.
    monkeypatch.setattr(
        tui.club_config, "load_club_config", lambda slug, *a, **k: {"club_id": "0000001", "overview_days": 7}
    )
    preferences_file = tmp_path / "preferences.yaml"
    tui.global_preferences.save_preferences({"availability": {"min_open_spots": 3}}, preferences_file)
    monkeypatch.setattr(tui.global_preferences, "PREFERENCES_FILE", preferences_file)

    config = tui._resolved_config("home-club")

    assert config["club_id"] == "0000001"  # a genuinely per-club fact, untouched
    assert config["overview_days"] == 7  # ditto
    assert config["availability"]["min_open_spots"] == 3  # from the global file


def test_resolved_config_still_applies_global_preferences_to_an_unsaved_club(monkeypatch, tmp_path):
    # club_slug=None (a club reached by id, never favorited) has no per-club config at
    # all, but your global availability rules still apply -- recommendations now work
    # on a club you haven't favorited, which the old per-club-only design couldn't do.
    preferences_file = tmp_path / "preferences.yaml"
    tui.global_preferences.save_preferences({"availability": {"min_open_spots": 2}}, preferences_file)
    monkeypatch.setattr(tui.global_preferences, "PREFERENCES_FILE", preferences_file)

    config = tui._resolved_config(None)

    assert config["availability"]["min_open_spots"] == 2


# _location_for_club/_resolved_config's club_id/club_name fallback -- added
# 2026-09-08, direct feedback: "I don't want to first save a club in order to see
# weather forecast." A club opened without ever being favorited used to never get a
# location at all, since the lookup only ever ran at save time -- these now geocode
# (and cache, in the club's own per-club db) on demand instead, regardless of
# favorite status.


def test_resolved_config_geocodes_an_unsaved_club_from_its_name(monkeypatch, tmp_path):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.geocode, "find_club_location", lambda name: (48.78, 9.68))

    config = tui._resolved_config(None, "0000002", "Golfclub Sonnenberg e.V.")

    assert config["location"] == {"lat": 48.78, "lon": 9.68}


def test_resolved_config_caches_the_geocoded_location_for_next_time(monkeypatch, tmp_path):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(tui.geocode, "find_club_location", lambda name: calls.append(name) or (48.78, 9.68))

    tui._resolved_config(None, "0000002", "Golfclub Sonnenberg e.V.")
    tui._resolved_config(None, "0000002", "Golfclub Sonnenberg e.V.")

    assert calls == ["Golfclub Sonnenberg e.V."]  # geocoded once, read from cache the second time


def test_resolved_config_skips_geocoding_without_a_name(monkeypatch, tmp_path):
    # A club reached by typing its numeric id directly into search never has a name
    # to geocode with (see club_picker.py's on_input_changed()) -- no crash, just no
    # location, same as before this feature existed.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    def fail(name):
        raise AssertionError("should not have tried to geocode without a name")

    monkeypatch.setattr(tui.geocode, "find_club_location", fail)

    config = tui._resolved_config(None, "0000002", "")

    assert "location" not in config


def test_resolved_config_does_not_override_a_location_already_saved(monkeypatch, tmp_path):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        tui.club_config, "load_club_config", lambda slug, *a, **k: {"location": {"lat": 1.0, "lon": 2.0}}
    )

    def fail(name):
        raise AssertionError("should not have re-geocoded a club that already has a saved location")

    monkeypatch.setattr(tui.geocode, "find_club_location", fail)

    config = tui._resolved_config("home-club", "0000002", "Golfclub Sonnenberg e.V.")

    assert config["location"] == {"lat": 1.0, "lon": 2.0}


def test_resolved_config_fills_in_a_missing_location_even_for_a_saved_club(monkeypatch, tmp_path):
    # A club saved before a location could be found (e.g. the geocoder failed at the
    # time) isn't stuck without weather forever -- the same fallback applies whether
    # or not clubs/*.yaml exists at all.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: {})
    monkeypatch.setattr(tui.geocode, "find_club_location", lambda name: (48.78, 9.68))

    config = tui._resolved_config("home-club", "0000002", "Golfclub Sonnenberg e.V.")

    assert config["location"] == {"lat": 48.78, "lon": 9.68}


def test_availability_pipeline_empty_without_availability_configured():
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)])
    assert tui._availability_pipeline(schedule, {}, "0000001") == ([], [])


# _crowd_estimates() -- added 2026-09-10, the actual data behind `avoid_predicted_crowd`
# (moved under "AI ranking" the same day, direct follow-up: "make avoid crowds a child
# of AI option" -- see settings_screen.py's own comment on that Field for why it only
# ever does anything through this exact path).


def test_crowd_estimates_empty_when_the_setting_is_off(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("should not touch analytics.crowd_heatmap() at all when off")

    monkeypatch.setattr(tui.analytics, "crowd_heatmap", fail)
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)])

    assert tui._crowd_estimates([schedule], {}, "0000001") == {}


def test_crowd_estimates_returns_a_real_prediction_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    db_path = scrape_once._db_path("0000001")
    for date in ["2026-08-17", "2026-08-24", "2026-08-31"]:  # 3 Mondays
        storage.save_schedule(
            Schedule(date=date, course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=2, capacity=4)]),
            path=db_path,
        )

    config = {"ai_assist": {"avoid_predicted_crowd": True}}
    candidate = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)])

    estimates = tui._crowd_estimates([candidate], config, "0000001")

    assert estimates[("2026-09-07", "18 Loch Tee 1", "09:00")] == 0.5


def test_crowd_estimates_omits_a_slot_with_too_few_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    db_path = scrape_once._db_path("0000001")
    storage.save_schedule(
        Schedule(date="2026-08-17", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=2, capacity=4)]),
        path=db_path,
    )  # only 1 Monday -- below MIN_SAMPLES_FOR_PREDICTION

    config = {"ai_assist": {"avoid_predicted_crowd": True}}
    candidate = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)])

    assert tui._crowd_estimates([candidate], config, "0000001") == {}


# _too_late_for_daylight() -- added 2026-09-09, direct request: "It would also be
# great if you could immediately see in the detailed view, which of the timeslots
# are already too late until sunset." Deliberately independent of whether
# `availability` is configured at all -- a plain physics fact, not a preference.


def test_too_late_for_daylight_false_without_sun_times():
    # Unknown, not assumed bad -- same stance recommend._fails_playability() takes.
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[])
    assert tui._too_late_for_daylight("17:00", schedule, {}) is False


def test_too_late_for_daylight_true_past_the_cutoff():
    # 18-hole default round duration is 240 min; sunset 19:00 means the latest
    # playable start (no buffer) is 15:00 -- 17:00 is well past that.
    schedule = Schedule(
        date="2026-09-07", course="18 Loch Tee 1", slots=[], sun_times=SunTimes(sunrise="06:00", sunset="19:00")
    )
    assert tui._too_late_for_daylight("17:00", schedule, {}) is True


def test_too_late_for_daylight_false_comfortably_before_the_cutoff():
    schedule = Schedule(
        date="2026-09-07", course="18 Loch Tee 1", slots=[], sun_times=SunTimes(sunrise="06:00", sunset="19:00")
    )
    assert tui._too_late_for_daylight("09:00", schedule, {}) is False


def test_too_late_for_daylight_respects_the_configured_buffer():
    schedule = Schedule(
        date="2026-09-07", course="18 Loch Tee 1", slots=[], sun_times=SunTimes(sunrise="06:00", sunset="19:00")
    )
    # Latest playable start with no buffer is exactly 15:00 -- fine without a
    # buffer, too late once a 60-minute safety buffer is configured.
    assert tui._too_late_for_daylight("15:00", schedule, {}) is False
    assert tui._too_late_for_daylight("15:00", schedule, {"daylight_buffer_minutes": 60}) is True


def test_day_detail_marks_a_too_late_slot_with_a_moon(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            # 06:00/19:00 slots exactly match sun_times below, so they (not
            # 09:00/17:00) are the ones that pick up the 🌅/🌇 markers --
            # keeps this test's own 09:00/17:00 rows about 🌙 alone.
            slots=[Slot(time=t, booked=0, capacity=4) for t in ("06:00", "09:00", "17:00", "19:00")],
            sun_times=SunTimes(sunrise="06:00", sunset="19:00"),
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            rows = [table.get_row_at(i) for i in range(4)]
            assert rows[1][0] == "09:00"  # comfortably before sunset -- no marker
            assert rows[2][0] == "🌙 17:00"  # wouldn't finish before dark

    _run(scenario())


def test_day_detail_star_and_moon_are_mutually_exclusive(tmp_path, monkeypatch):
    # A daylight-failing candidate is never ★-recommended in the first place (see
    # exclude_unplayable()), so the same slot can never carry both markers.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda *a, **k: _RECOMMEND_CONFIG)
    storage.save_schedule(
        Schedule(
            date="2026-09-06",
            course="18 Loch Tee 1",
            # 06:00/19:00 slots exactly match sun_times below, so 17:00 (the
            # slot actually under test here) doesn't also pick up a 🌅/🌇
            # marker -- this test is about ★/🌙 alone.
            slots=[
                Slot(time="06:00", booked=0, capacity=4),
                Slot(time="17:00", booked=0, capacity=4),  # within _RECOMMEND_CONFIG's window
                Slot(time="19:00", booked=0, capacity=4),
            ],
            sun_times=SunTimes(sunrise="06:00", sunset="19:00"),  # but too late to finish before dark
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            row = app.screen.query_one(DataTable).get_row_at(1)
            assert row[0] == "🌙 17:00"
            assert "★" not in row[0]

    _run(scenario())


def test_day_pick_text_shows_a_confirmed_booking_first():
    booking = ConfirmedBooking(date="2026-09-07", course="18 Loch Tee 1", time="14:00", source="manual")
    text = tui._day_pick_text(None, {}, booking, has_pending_change=False, club_id="0000001")
    assert "14:00" in text
    assert "📌" in text
    assert "⚠" not in text


def test_day_pick_text_flags_a_pending_booking_watch_change():
    booking = ConfirmedBooking(date="2026-09-07", course="18 Loch Tee 1", time="14:00", source="manual")
    text = tui._day_pick_text(None, {}, booking, has_pending_change=True, club_id="0000001")
    assert "⚠" in text


def test_day_pick_text_dash_without_availability_configured():
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)])
    assert tui._day_pick_text(schedule, {}, None, False, "0000001") == "[dim]—[/]"


def test_day_pick_text_stars_the_earliest_playable_match_without_ai_ranking():
    # No ai_assist.enabled at all -- _availability_pipeline()'s playable still comes
    # back in search()'s own natural (chronological, real slots are always ordered
    # this way) order, so "best" and "earliest" agree exactly as they did before
    # ranked_matches() was wired in here.
    config = {"availability": {"weekday_window": {"after": "08:00"}}}
    schedule = Schedule(
        date="2026-09-07",  # a Monday
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=0, capacity=4), Slot(time="10:00", booked=0, capacity=4)],
    )
    assert tui._day_pick_text(schedule, config, None, False, "0000001") == "[yellow]★[/] 09:00"


def test_day_pick_text_stars_the_ai_ranked_slot_not_the_earliest(monkeypatch):
    # Direct feedback, 2026-09-08: "why does it always recommend 16:00 on any other
    # day?" -- once ai_assist.enabled is true, the star should reflect genuine
    # judgment (here: a later, AI-preferred slot), not just the first chronological
    # match, the same real ranking weekly_picks() already uses.
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "ai_assist": {"enabled": True},
    }
    schedule = Schedule(
        date="2026-09-07",  # a Monday
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=0, capacity=4), Slot(time="10:00", booked=0, capacity=4)],
    )

    def fake_rank_slots(candidates, context, preferences, model):
        # Reverse the order -- the later slot ranks first.
        return list(reversed(candidates))

    monkeypatch.setattr(tui.recommend.ai_assist, "rank_slots", fake_rank_slots)

    assert tui._day_pick_text(schedule, config, None, False, "0000001") == "[yellow]★[/] 10:00"


def test_day_pick_text_no_dry_picks_when_weather_excludes_everything():
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "preferences": {"avoid_rain": True},
    }
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=0, capacity=4)],
        weather=[_weather("09:00", prob=90)],
    )
    assert "no dry picks" in tui._day_pick_text(schedule, config, None, False, "0000001")


def test_day_pick_text_says_too_dark_when_only_daylight_excludes(tmp_path):
    # Real confusion reported live, 2026-09-08: "In the overview it says there are
    # no dry timeslots, but ... rain is only in the morning" -- the old message
    # unconditionally implied rain, but sun_times only started actually persisting
    # through storage.py the same day (see storage.init_db()'s own docstring), so a
    # slot simply too late to finish before dark could now be excluded too, and
    # would have been mislabeled as a rain problem.
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "daylight_buffer_minutes": 30,
        "round_duration_minutes": {"eighteen": 240},
    }
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="18:00", booked=0, capacity=4)],  # far too late to finish by 19:00
        sun_times=SunTimes(sunrise="06:00", sunset="19:00"),
    )
    text = tui._day_pick_text(schedule, config, None, False, "0000001")
    assert "dark" in text
    assert "dry" not in text


def test_day_pick_text_generic_message_when_both_reasons_apply(tmp_path):
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "daylight_buffer_minutes": 30,
        "round_duration_minutes": {"eighteen": 240},
        "preferences": {"avoid_rain": True},
    }
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="18:00", booked=0, capacity=4)],  # too late AND rainy
        weather=[_weather("18:00", prob=90)],
        sun_times=SunTimes(sunrise="06:00", sunset="19:00"),
    )
    text = tui._day_pick_text(schedule, config, None, False, "0000001")
    assert "dry" not in text
    assert "dark" not in text
    assert "playable" in text


# --- OverviewScreen itself ------------------------------------------------------------


def test_overview_screen_shows_a_row_per_attempted_day(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.row_count == 5  # club.example.yaml's overview_days default

    _run(scenario())


# _legend_line()/OVERVIEW_LEGEND/DAY_DETAIL_LEGEND -- added 2026-09-09, direct
# question: "Would it make sense to implement a legend, since we already have so
# many icons?"


def test_legend_pairs_renders_icon_and_meaning():
    pairs = tui._legend_pairs([("★", "legend.recommended"), ("🌧", "legend.rain")])
    assert pairs == ["★ recommended", "🌧 rain"]


# _wrap_legend() -- direct follow-up: "legend needs to wrap up, since some words
# might be cut off." A first attempt joined icon and meaning with a non-breaking
# space (U+00A0), expecting Rich to treat that as unbreakable; confirmed live it
# didn't help at all -- Rich's own wrapper splits on Python's \s regex, which
# matches U+00A0 too. Wrapping the legend explicitly, pair by pair, is what
# actually fixes it.


def test_wrap_legend_keeps_every_pair_on_one_line():
    pairs = ["★ recommended", "🌧 rain", "💨 wind"]
    wrapped = tui._wrap_legend(pairs, width=15)
    for pair in pairs:
        # A pair must appear intact on some one line -- never split with only
        # its icon on one line and its own meaning starting the next.
        assert any(pair in line for line in wrapped.split("\n"))


def test_wrap_legend_reproduces_and_fixes_the_real_bug():
    # The exact real case caught live in a narrow terminal: with these pairs at
    # width=45, a plain-space join wrapped right between "📌" and "booked".
    pairs = tui._legend_pairs(tui.OVERVIEW_LEGEND)
    wrapped = tui._wrap_legend(pairs, width=45)
    lines = wrapped.split("\n")
    assert not any(line.rstrip().endswith("📌") for line in lines)
    assert any("📌 booked" in line for line in lines)


def test_wrap_legend_one_line_when_everything_fits():
    pairs = ["★ recommended", "🌧 rain"]
    assert tui._wrap_legend(pairs, width=200) == "★ recommended  🌧 rain"


def test_wrap_legend_a_single_pair_too_wide_still_gets_its_own_line():
    # Never crop or drop real information to fit a layout constraint -- same
    # stance every other narrow-terminal fallback in this app already takes.
    pairs = ["⚠ changed since booked"]
    assert tui._wrap_legend(pairs, width=5) == "⚠ changed since booked"


def test_overview_legend_does_not_repeat_an_icon_with_two_meanings():
    # The real bug this responds to: 📌 used to mean both "confirmed booking" (Pick
    # column) and "event/closure note" (Events column) -- a legend would have had to
    # list the same icon twice with different meanings. Fixed by giving Events its
    # own icon (📋) instead, so every icon in one screen's own legend is unique.
    icons = [icon for icon, _ in tui.OVERVIEW_LEGEND]
    assert len(icons) == len(set(icons))
    assert "📌" in icons and "📋" in icons  # both still present, just not on one icon


def test_day_detail_legend_includes_the_moon_marker_overview_does_not():
    assert "🌙" in [icon for icon, _ in tui.DAY_DETAIL_LEGEND]
    assert "🌙" not in [icon for icon, _ in tui.OVERVIEW_LEGEND]


def test_overview_screen_shows_a_legend_line(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            legend = str(app.screen.query_one("#legend", Static).content)
            assert "★ recommended" in legend
            assert "📋 event/closure" in legend
            assert "📌 booked" in legend

    _run(scenario())


def test_day_detail_shows_a_legend_line_including_the_moon(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            legend = str(app.screen.query_one("#legend", Static).content)
            assert "🌙 too late for sunset" in legend

    _run(scenario())


def test_overview_screen_legend_never_splits_a_pair_at_a_narrow_width(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test(size=(45, 24)) as pilot:
            await pilot.pause()
            legend = str(app.screen.query_one("#legend", Static).content)
            lines = legend.split("\n")
            assert not any(line.rstrip().rstrip("[/]").endswith("📌") for line in lines)
            assert any("📌 booked" in line for line in lines)

    _run(scenario())


def test_overview_screen_shows_temperature_precipitation_wind_and_events_columns(tmp_path, monkeypatch):
    # Direct feedback on a real screenshot: "It shouldn't mix up events with weather
    # data. Can you make an extra column for the events?" then "can you please split
    # weather into Temperature, Precipitation, and wind columns"
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])
    storage.save_schedule(
        Schedule(
            date=tui._TODAY(),
            course="18 Loch Tee 1",
            slots=[Slot(time="09:00", booked=0, capacity=4)],
            weather=[_weather("09:00", prob=5, temp=20.0, wind=40, code=1)],
            events=["Herbstturnier"],
        ),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            headers = [str(col.label) for col in table.columns.values()]
            assert headers == [
                "Day", "Condition", "Temperature (°C)", "Precipitation (%/mm)", "Wind (km/h)", "Events",
                "Occupancy 08–20", "Pick",
            ]
            row = table.get_row_at(0)  # today, Day/Condition/Temperature/Precipitation/Wind/Events/Heat/Pick
            # No "°"/"km/h" suffix on Temperature/Wind any more (2026-09-13,
            # direct follow-up: "since the units are now in the headers, we
            # don't need the units in the rows, right?").
            assert row[1] == "🌤️"  # weather_code=1 -> mainly clear icon
            assert row[2] == "20/20"  # real temperature, not the event
            assert "5%" in row[3]
            assert "40" in row[4]
            assert row[5] == "📋 Herbstturnier"  # the event, in its own column

    _run(scenario())


def test_overview_screen_greys_out_a_date_the_club_has_not_opened_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [tui._TODAY()])  # only today

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            row = table.get_row_at(1)  # tomorrow -- not in the real open-dates set
            # Day/Condition/Temperature/Precipitation/Wind/Events/Heat/Pick
            assert "not open" in row[7]

    _run(scenario())


def test_overview_screen_shows_no_data_placeholder_for_an_unscraped_open_day(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            row = app.screen.query_one(DataTable).get_row_at(0)
            assert "…" in row[1]

    _run(scenario())


def test_overview_screen_hides_picks_section_without_availability_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: {})
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert str(app.screen.query_one("#picks", Static).content) == ""

    _run(scenario())


def test_overview_screen_shows_picks_once_availability_is_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        tui.club_config, "load_club_config",
        lambda slug, *a, **k: {"availability": {"weekday_window": {"after": "08:00"}}},
    )
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])
    storage.save_schedule(
        Schedule(date=tui._TODAY(), course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            content = str(app.screen.query_one("#picks", Static).content)
            assert "This week's picks" in content
            assert "09:00" in content

    _run(scenario())


def test_overview_screen_picks_spread_across_days_not_just_the_first_one(tmp_path, monkeypatch):
    # Direct feedback on a real screenshot: "why does it only recommend tee times on
    # Tuesday?" -- the first day alone had enough open slots to fill the whole
    # displayed list, crowding out every other day. overview_days defaults to 5; give
    # the first day 5 open slots and every other day exactly one, so a fix that
    # actually diversifies must show all 5 distinct dates, not 5 times on day one.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        tui.club_config, "load_club_config",
        lambda slug, *a, **k: {"availability": {"weekday_window": {"after": "08:00"}, "weekend_window": {"after": "08:00"}}},
    )
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])
    today = tui._TODAY()
    from datetime import date as date_cls
    from datetime import timedelta

    dates = [(date_cls.fromisoformat(today) + timedelta(days=offset)).isoformat() for offset in range(5)]
    db_path = scrape_once._db_path("0000001")
    storage.save_schedule(
        Schedule(
            date=dates[0],
            course="18 Loch Tee 1",
            slots=[Slot(time=t, booked=0, capacity=4) for t in ["09:00", "09:10", "09:20", "09:30", "09:40"]],
        ),
        path=db_path,
    )
    for date in dates[1:]:
        storage.save_schedule(
            Schedule(date=date, course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)]),
            path=db_path,
        )

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            content = str(app.screen.query_one("#picks", Static).content)
            for date in dates:
                assert date in content

    _run(scenario())


def test_overview_screen_row_selected_opens_that_dates_day_detail_screen(tmp_path, monkeypatch):
    from datetime import date as date_cls
    from datetime import timedelta

    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])
    tomorrow = (date_cls.fromisoformat(tui._TODAY()) + timedelta(days=1)).isoformat()

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            table.focus()
            await pilot.press("down")  # tomorrow's row
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.date == tomorrow

    _run(scenario())


def test_overview_screen_highlights_todays_row_when_today_still_has_upcoming_slots(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "08:00")
    storage.save_schedule(
        Schedule(date=tui._TODAY(), course="18 Loch Tee 1", slots=[Slot(time="19:50", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one(DataTable).cursor_row == 0

    _run(scenario())


def test_overview_screen_highlights_tomorrows_row_once_today_is_fully_closed(tmp_path, monkeypatch):
    # Direct feedback 2026-09-07, the same evening OverviewScreen shipped: "why is
    # the TUI still showing today at this time (11:12 PM)?" -- _initial_date()'s own
    # "today's closed, default to tomorrow" logic was written for the old launch flow
    # that opened straight on a DayDetailScreen, and silently stopped being called at
    # all once that flow became this overview screen instead. Fixed by using it to
    # pick which row starts highlighted here, rather than leaving it dead code.
    #
    # "20:00" here, not the original 22:00 -- deliberately *before*
    # TODAY_HIDDEN_AFTER_HHMM (21:00, added 2026-09-11), so today's own row still
    # exists to move the cursor *off of*. At or past that cutoff, today's row is
    # gone entirely (see the dedicated tests below), and tomorrow becoming row 0 is
    # simply a side effect of that, not this function's own doing.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "20:00")
    storage.save_schedule(
        Schedule(date=tui._TODAY(), course="18 Loch Tee 1", slots=[Slot(time="19:50", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one(DataTable).cursor_row == 1  # tomorrow's row

    _run(scenario())


# --- Today's row drops out of the overview entirely once it's past a fixed clock
# cutoff -- added 2026-09-11, direct feedback ("i would prefer if today ... didn't
# show up anymore after sunset"), refined the very same day to a plain fixed time
# instead ("I would prefer that the current day disappears from the overview
# whenever it is after 9 pm") -- simpler and predictable year-round, and no longer
# needs a cached schedule to exist at all. Genuinely different from _initial_date()'s
# own "every slot's own time has passed" heuristic above (the club's booking hours,
# not a fixed cutoff). --------------------------------------------------------------


def test_overview_screen_drops_todays_row_once_past_the_cutoff(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "21:01")

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            # Today's own row is gone entirely -- not just deprioritized -- so only
            # the remaining overview_days - 1 rows (tomorrow onward) show at all.
            assert tui._TODAY() not in app.screen._row_dates
            assert table.row_count == 4

    _run(scenario())


def test_overview_screen_keeps_todays_row_exactly_at_the_cutoff(tmp_path, monkeypatch):
    # TODAY_HIDDEN_AFTER_HHMM itself is still shown -- only strictly *after* it hides.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: tui.TODAY_HIDDEN_AFTER_HHMM)

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert tui._TODAY() in app.screen._row_dates

    _run(scenario())


def test_overview_screen_keeps_todays_row_well_before_the_cutoff(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: "08:00")

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert tui._TODAY() in app.screen._row_dates

    _run(scenario())


def test_edit_settings_saves_and_reflects_immediately_in_the_overview(tmp_path, monkeypatch):
    # Direct feedback 2026-09-08: "i don't even know where to configure from the UI"
    # -- settings_screen.py used to only be reachable as its own separate command,
    # with nothing in the running app pointing at it. `e` now opens it directly.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    preferences_file = tmp_path / "preferences.yaml"
    monkeypatch.setattr(tui.global_preferences, "PREFERENCES_FILE", preferences_file)
    # Just enough of a favorite for _reach_overview() to skip the course picker --
    # its own default_course is still a genuinely per-club fact, unaffected by
    # availability/preferences becoming global.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "18 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_overview(app, pilot)

            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, tui.SettingsScreen)

            widget = app.screen.query_one("#field-availability-min_open_spots")
            widget.value = "3"
            await pilot.click("#save")
            await pilot.pause()
            # escape, not "q" -- SettingsScreen's own q now quits the whole app,
            # matching every other screen's convention (2026-09-09 fix; see that
            # module's own docstring for the direct feedback this responds to).
            await pilot.press("escape")
            await pilot.pause()

            # Back on the overview, reloaded -- a saved availability change can
            # immediately affect its per-day pick column and "This week's picks".
            assert isinstance(app.screen, tui.OverviewScreen)

    _run(scenario())

    saved = tui.global_preferences.load_preferences(preferences_file)
    assert saved["availability"]["min_open_spots"] == 3


def test_edit_settings_units_change_rebuilds_the_overviews_own_column_headers(tmp_path, monkeypatch):
    # Direct feedback, 2026-09-13: "Can we adjust format (metric/imperial) in
    # settings?" A units change needs a full screen rebuild, not just a row
    # reload -- a table's own column headers are only ever set once in
    # on_mount(), so a plain load_overview() would leave a stale "(°C)" header
    # next to freshly converted °F numbers.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    preferences_file = tmp_path / "preferences.yaml"
    monkeypatch.setattr(tui.global_preferences, "PREFERENCES_FILE", preferences_file)
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "18 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_overview(app, pilot)
            table = app.screen.query_one(DataTable)
            headers_before = [str(col.label) for col in table.columns.values()]
            assert "Temperature (°C)" in headers_before

            await pilot.press("e")
            await pilot.pause()
            app.screen.query_one("#field-units").value = "imperial"
            await pilot.click("#save")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            assert isinstance(app.screen, tui.OverviewScreen)
            headers_after = [str(col.label) for col in app.screen.query_one(DataTable).columns.values()]
            assert "Temperature (°F)" in headers_after

    _run(scenario())

    saved = tui.global_preferences.load_preferences(preferences_file)
    assert saved["units"] == "imperial"


def test_edit_settings_works_on_a_club_that_was_never_favorited(tmp_path, monkeypatch):
    # Direct same-day follow-up: "i also want the settings/preferences to be global
    # and not tied to a specific club" -- unlike the old per-club design, opening
    # settings on a club you haven't saved needs nothing special any more: there's
    # no club-specific file to create, just the one shared settings file.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])
    preferences_file = tmp_path / "preferences.yaml"
    monkeypatch.setattr(tui.global_preferences, "PREFERENCES_FILE", preferences_file)

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            app.screen.dismiss("0000001")  # a club id typed in, never saved
            await pilot.pause()
            assert isinstance(app.screen, tui.CoursePickerScreen)
            app.screen.dismiss("18 Loch Tee 1")
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, tui.OverviewScreen)
            assert app.screen.club_slug is None

            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, tui.SettingsScreen)
            await pilot.click("#save")
            await pilot.pause()
            await pilot.press("escape")  # not "q" -- see the other e->settings test above
            await pilot.pause()

            # Still unsaved -- editing global settings never favorites anything.
            assert isinstance(app.screen, tui.OverviewScreen)
            assert app.screen.club_slug is None

    _run(scenario())

    assert preferences_file.exists()  # the global file was written...
    assert not (tmp_path / "clubs").exists()  # ...and nothing club-specific was ever created


def test_overview_screen_footer_says_enter_opens_a_day(tmp_path, monkeypatch):
    # Direct feedback 2026-09-07: "the club selector also doesn't say that you need
    # to hit enter" -- true of every screen here that opens something via Textual's
    # own built-in Enter behavior (OptionList/DataTable), not a real BINDINGS entry
    # this app declares, which is exactly why it never showed up in the footer on its
    # own anywhere. Checked here for OverviewScreen; see the matching ClubBrowserScreen
    # and CoursePickerScreen tests below for the other two.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            text = app.screen.query_one(tui.TranslatedFooter).render()
            assert "enter" in text and "Open" in text
            assert "Settings" in text
            assert "Search" in text  # `/` -- SearchScreen, added 2026-09-08

    _run(scenario())


def test_overview_screen_club_visited_not_saved_has_no_availability_computed(tmp_path, monkeypatch):
    # club_slug=None (a club reached by id, never favorited) must not try to load a
    # config file that doesn't exist -- same handling as DayDetailScreen's own.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", None, "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert str(app.screen.query_one("#picks", Static).content) == ""

    _run(scenario())


# --- SearchScreen (ROADMAP.md Phase 4, ad hoc search -- "we should build the ad hoc
# search screen next", 2026-09-08) -------------------------------------------------


def test_overview_screen_slash_opens_search_screen(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            assert isinstance(app.screen, tui.SearchScreen)

    _run(scenario())


def _search_screen(schedules=None, config=None, club_id="0000001"):
    return tui.SearchScreen(schedules or [], config or {}, club_id)


def test_search_screen_prefills_from_saved_availability(tmp_path):
    config = {
        "availability": {
            "min_open_spots": 3,
            "weekday_window": {"after": "17:00"},
            "buffer_before_minutes": 20,
            "buffer_after_minutes": 10,
        }
    }

    async def scenario():
        app = _HostApp(_search_screen(config=config))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one("#search-min-open-spots").value == "3"
            assert app.screen.query_one("#search-weekday-after-hh").value == "17"
            assert app.screen.query_one("#search-weekday-after-mm").value == "00"
            assert app.screen.query_one("#search-buffer-before").value == "20"
            assert app.screen.query_one("#search-buffer-after").value == "10"
            # Nothing saved for the weekend window -- both dropdowns start blank.
            assert app.screen.query_one("#search-weekend-after-hh").value == ""

    _run(scenario())


def test_search_screen_prefill_falls_back_to_the_old_single_buffer_key(tmp_path):
    config = {"availability": {"buffer_minutes": 15}}

    async def scenario():
        app = _HostApp(_search_screen(config=config))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.query_one("#search-buffer-before").value == "15"
            assert app.screen.query_one("#search-buffer-after").value == "15"

    _run(scenario())


def test_search_screen_hour_dropdown_excludes_implausible_hours():
    async def scenario():
        from textual.widgets import Select

        app = _HostApp(_search_screen())
        async with app.run_test() as pilot:
            await pilot.pause()
            hour_select = app.screen.query_one("#search-weekday-after-hh", Select)
            offered = hour_select._legal_values - {""}
            assert "02" not in offered
            assert "05" in offered
            assert "21" in offered

    _run(scenario())


def test_search_screen_runs_search_and_shows_results():
    schedule = Schedule(
        date="2026-09-07",  # Monday
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=1, capacity=4, players=["Max Mustermann"])],
        weather=[
            WeatherPoint(
                time="09:00", temperature_c=16, precipitation_probability=10, wind_speed_kph=8, weather_code=95
            )
        ],
    )

    async def scenario():
        app = _HostApp(_search_screen(schedules=[schedule]))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search-weekday-after-hh").value = "05"
            await pilot.click("#run")
            await pilot.pause()
            table = app.screen.query_one("#search-results", DataTable)
            # No per-row Course column any more (2026-09-13, direct question:
            # "why does adhoc search need to mention course, couldn't it be
            # mentioned once in the header?") -- it's in the Header's own
            # title instead, checked separately below. Occupancy/Players/
            # Temperature/Precipitation/Wind columns added the same day
            # (direct question: "why does adhoc search not show occupancy,
            # player, or weather data?"). Condition (2026-09-11, "I also would
            # like icons for when it is sunny, overcast, foggy, snowing etc.")
            # added after Time, matching DayDetailScreen's own placement.
            assert [str(col.label) for col in table.columns.values()] == [
                "Date", "Time", "Condition", "Occupancy", "Players", "Temperature (°C)", "Precipitation (%/mm)",
                "Wind (km/h)", "Notes",
            ]
            assert table.row_count == 1
            row = table.get_row_at(0)
            assert row[1] == "09:00"
            assert row[2] == "⛈️"  # weather_code=95 -> thunderstorm icon
            assert row[3] == "1/4"
            assert row[4] == "Max Mustermann"
            # No "°"/"km/h" suffix on Temperature/Wind any more (2026-09-13,
            # direct follow-up: "since the units are now in the headers, we
            # don't need the units in the rows, right?").
            assert row[5] == "16"
            assert row[6] == "10%"
            assert row[7] == "8"
            assert "18 Loch Tee 1" in app.screen.title

    _run(scenario())


def test_search_screen_uses_typed_in_criteria_not_saved_defaults():
    # The whole point of ad hoc search -- "just this once," not your saved rules.
    schedule = Schedule(
        date="2026-09-07",  # Monday
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=0, capacity=4), Slot(time="18:00", booked=0, capacity=4)],
    )
    # A saved default that would only ever match the evening slot.
    config = {"availability": {"weekday_window": {"after": "17:00"}}}

    async def scenario():
        app = _HostApp(_search_screen(schedules=[schedule], config=config))
        async with app.run_test() as pilot:
            await pilot.pause()
            # Override the pre-filled 17:00 with a morning window instead.
            app.screen.query_one("#search-weekday-after-hh").value = "05"
            app.screen.query_one("#search-weekday-before-hh").value = "12"
            app.screen.query_one("#search-weekday-before-mm").value = "00"
            await pilot.click("#run")
            await pilot.pause()
            table = app.screen.query_one("#search-results", DataTable)
            assert table.row_count == 1
            assert table.get_row_at(0)[1] == "09:00"

    _run(scenario())


def test_search_screen_confirm_prefills_the_highlighted_results_own_date_and_time(tmp_path, monkeypatch):
    # Direct question, 2026-09-13: "can we confirm tee times from adhoc
    # search?" A single search's results can span several different days, so
    # this has to come from the highlighted row's own match, not from any one
    # fixed date/course the way DayDetailScreen's own `c` can.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    schedules = [
        Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)]),
        Schedule(date="2026-09-08", course="18 Loch Tee 1", slots=[Slot(time="10:00", booked=0, capacity=4)]),
    ]

    async def scenario():
        app = _HostApp(_search_screen(schedules=schedules, club_id="0000001"))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search-weekday-after-hh").value = "05"
            await pilot.click("#run")
            await pilot.pause()
            table = app.screen.query_one("#search-results", DataTable)
            assert table.row_count == 2
            table.move_cursor(row=1)  # the second day's own result
            await pilot.press("c")
            await pilot.pause()

            assert isinstance(app.screen, tui.ConfirmBookingScreen)
            assert app.screen.query_one("#time", Input).value == "10:00"
            assert app.screen.date == "2026-09-08"
            assert app.screen.course == "18 Loch Tee 1"

    _run(scenario())


def test_search_screen_confirm_saves_and_shows_a_status_message(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="09:00", booked=0, capacity=4)])

    async def scenario():
        app = _HostApp(_search_screen(schedules=[schedule], club_id="0000001"))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#search-weekday-after-hh").value = "05"
            await pilot.click("#run")
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, tui.ConfirmBookingScreen)
            await pilot.click("#save")
            await pilot.pause()

            assert isinstance(app.screen, tui.SearchScreen)
            assert str(app.screen.query_one("#search-status", Static).content) == i18n.t("confirm.confirmed")

    _run(scenario())

    saved = storage.load_confirmed_booking("18 Loch Tee 1", "2026-09-07", path=scrape_once._db_path("0000001"))
    assert saved is not None
    assert saved.time == "09:00"


def test_search_screen_confirm_does_nothing_with_no_results(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_search_screen())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, tui.SearchScreen)  # nothing pushed

    _run(scenario())


def test_search_screen_shows_no_matches_message():
    schedule = Schedule(
        date="2026-09-07",  # Monday
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=4, capacity=4)],  # fully booked
    )

    async def scenario():
        app = _HostApp(_search_screen(schedules=[schedule]))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#run")
            await pilot.pause()
            table = app.screen.query_one("#search-results", DataTable)
            assert table.row_count == 0
            assert app.screen.query_one("#search-status", Static).content

    _run(scenario())


def test_search_screen_cancel_dismisses_without_running():
    async def scenario():
        app = _HostApp(_search_screen())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#cancel")
            await pilot.pause()
            assert app.result is None

    _run(scenario())


def test_search_screen_footer_renders_translated_hints():
    async def scenario():
        app = _HostApp(_search_screen())
        async with app.run_test() as pilot:
            await pilot.pause()
            text = app.screen.query_one(tui.TranslatedFooter).render()
            assert "Back" in text
            assert "Quit" in text

    _run(scenario())


def test_search_screen_sets_its_own_title():
    # Never actually set before this (2026-09-10 bug hunt) -- the mockup's own
    # "Search" screen shows "Search this week" in its Header; the real screen just
    # showed the app's bare default title.
    async def scenario():
        app = _HostApp(_search_screen())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.title == i18n.t("search.title")

    _run(scenario())


# --- ClubBrowserScreen / CoursePickerScreen --------------------------------------------


def test_club_browser_footer_says_enter_opens_a_club(monkeypatch):
    # Direct feedback 2026-09-07: "the club selector also doesn't say that you need
    # to hit enter" -- see OverviewScreen's matching test above for the fuller note.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            text = app.screen.query_one(tui.TranslatedFooter).render()
            assert "enter" in text and "Open" in text

    _run(scenario())


def test_club_browser_status_mentions_enter_once_matches_are_shown(monkeypatch):
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(
        tui.club_directory, "load_cached_directory", lambda *a, **k: [("0491605", "1. Golfclub Leipzig e.V.")]
    )

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "leipzig"
            await pilot.pause()
            status = str(app.screen.query_one("#club-status", Static).content)
            assert "enter" in status

    _run(scenario())


# --- Bundled seed directory fallback -- added 2026-09-10, direct pushback ("a First
# time User would not know anything about a club id"): name search should work on a
# brand-new install with zero setup, not just once a real login+fetch has happened. --


def test_club_browser_falls_back_to_the_seed_when_the_real_cache_is_empty(monkeypatch):
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])
    monkeypatch.setattr(
        tui.club_directory, "load_seed_directory", lambda *a, **k: [("0491605", "1. Golfclub Leipzig e.V.")]
    )

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "leipzig"
            await pilot.pause()
            status = str(app.screen.query_one("#club-status", Static).content)
            assert "1 " in status or "matches" in status  # match_count, not no_directory_yet

    _run(scenario())


def test_club_browser_never_touches_the_seed_when_a_real_cache_already_exists(monkeypatch):
    # The seed is a first-run fallback only -- a real cache, however small, always
    # wins outright, never merged with or topped up from the bundled data.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(
        tui.club_directory, "load_cached_directory", lambda *a, **k: [("0000001", "Golfclub Musterhausen")]
    )
    seed_calls = []
    monkeypatch.setattr(tui.club_directory, "load_seed_directory", lambda *a, **k: seed_calls.append(1) or [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()

    _run(scenario())
    assert seed_calls == []


def test_club_browser_shows_the_seed_specific_hint_with_no_favorites(monkeypatch):
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])
    monkeypatch.setattr(
        tui.club_directory,
        "load_seed_directory",
        lambda *a, **k: [("0491605", "1. Golfclub Leipzig e.V.")],
    )

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            status = str(app.screen.query_one("#club-status", Static).content)
            assert status == i18n.t("picker.no_favorites_hint_with_seed", count=1)

    _run(scenario())


def test_club_browser_real_refresh_clears_the_seed_flag(monkeypatch):
    # Once a real fetch succeeds, the seed-specific hint must not linger -- the
    # directory is genuinely live data now, not the bundled snapshot.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])
    monkeypatch.setattr(
        tui.club_directory, "load_seed_directory", lambda *a, **k: [("0491605", "1. Golfclub Leipzig e.V.")]
    )
    monkeypatch.setattr(tui.club_directory, "any_credentials", lambda: ("0000001", "user", "pass"))
    monkeypatch.setattr(
        tui.club_directory, "refresh_directory", lambda *a, **k: [("0000002", "Golfclub Sonnenberg")]
    )

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen._directory_is_seed is True
            app.screen.action_refresh_directory()
            await pilot.pause()
            assert app.screen._directory_is_seed is False
            status = str(app.screen.query_one("#club-status", Static).content)
            assert status == i18n.t("picker.directory_refreshed", count=1)

    _run(scenario())


def test_club_browser_lists_favorites_and_dismisses_with_the_club_id(tmp_path, monkeypatch):
    # An empty search box lists your favorites -- no directory and no login involved.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club", "guest-club"])
    configs = {"home-club": {"club_id": "0000001"}, "guest-club": {"club_id": "0352001"}}
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: configs[slug])
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda *a, **k: True)
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            option_list = app.screen.query_one(OptionList)
            assert option_list.option_count == 2
            option_list.focus()  # focus starts in the search box, not the list
            option_list.highlighted = 1
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            # Dismisses with the club's numeric pc caddie id, not a local slug --
            # the id is what every scraper call actually needs, and a club reached
            # from the directory has no slug at all.
            assert app.result == "0352001"

    _run(scenario())


def test_club_browser_offers_a_typed_club_id_directly(tmp_path, monkeypatch):
    # The path that needs neither the directory cache nor credentials -- and the only
    # way to reach a club on a brand-new install, before any login exists.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda *a, **k: False)
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "000001"
            await pilot.pause()
            option_list = app.screen.query_one(OptionList)
            assert option_list.option_count == 1
            option_list.focus()  # focus starts in the search box, not the list
            option_list.highlighted = 0
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.result == "0000001"  # normalized to 7 digits

    _run(scenario())


def test_club_browser_enter_in_the_search_box_opens_the_result(tmp_path, monkeypatch):
    # Caught in a live run, not by the other tests here (which drive the OptionList
    # directly): focus stays in the Input, so without an Input.Submitted handler
    # typing a club id showed the right result and then Enter did nothing at all.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda *a, **k: False)
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).focus()
            await pilot.press(*"0352002")
            await pilot.pause()
            await pilot.press("enter")  # never leaves the search box
            await pilot.pause()
            assert app.result == "0352002"

    _run(scenario())


def test_club_browser_does_not_use_the_open_by_id_prompt_as_a_club_name(tmp_path, monkeypatch):
    # "open this club" is a prompt, not a name -- it was ending up as the tee sheet's
    # own window title for any club reached by id (caught live).
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda *a, **k: False)
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "0352002"
            await pilot.pause()
            assert app.screen._names == {}

    _run(scenario())


def test_club_browser_searches_the_cached_directory_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda *a, **k: False)
    monkeypatch.setattr(
        tui.club_directory, "load_cached_directory",
        lambda *a, **k: [("0491605", "1. Golfclub Leipzig e.V."), ("0000001", "Golfclub Musterhausen")],
    )

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "leipzig"
            await pilot.pause()
            option_list = app.screen.query_one(OptionList)
            assert option_list.option_count == 1
            option_list.focus()  # focus starts in the search box, not the list
            option_list.highlighted = 0
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.result == "0491605"

    _run(scenario())


def test_club_browser_f_toggles_favorite(tmp_path, monkeypatch):
    monkeypatch.setattr(tui.club_config, "CLUBS_DIR", tmp_path)
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory",
                        lambda *a, **k: [("0000001", "Golfclub Musterhausen")])
    added = []
    monkeypatch.setattr(tui.club_config, "is_favorite", lambda club_id, *a, **k: club_id in added)
    monkeypatch.setattr(tui.club_config, "add_favorite",
                        lambda club_id, name="", *a, **k: added.append(club_id) or "slug")

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "musterhausen"
            await pilot.pause()
            # Deliberately does NOT set `highlighted` -- with focus still in the
            # search box Textual highlights nothing, and `f` silently did nothing at
            # exactly the moment the one obvious target was on screen (caught live).
            app.screen.action_toggle_favorite()
            await pilot.pause()
            assert added == ["0000001"]

    _run(scenario())


# --- Inline login setup -- added 2026-09-09, direct feedback: "I want login setup
# within the tui directly when you run it." CredentialsScreen has existed since
# 2026-09-07 but was never actually pushed from the running main app -- `r` without
# credentials configured used to just print a status line naming a separate command
# to run instead. ----------------------------------------------------------------


def test_club_browser_r_pushes_credentials_screen_when_none_configured(monkeypatch):
    monkeypatch.setattr(tui.club_directory, "any_credentials", lambda: None)
    monkeypatch.setattr(tui.club_directory, "credentials_configured", lambda: False)

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_refresh_directory()
            await pilot.pause()
            assert isinstance(app.screen, tui.CredentialsScreen)

    _run(scenario())


def test_club_browser_r_shows_needs_a_club_when_credentials_exist_but_no_favorite(monkeypatch):
    # Real bug found live, 2026-09-10: any_credentials() is None has two different
    # causes -- no credentials at all, or real working credentials with no favorited
    # club yet to pair them with (see club_directory.credentials_configured()'s own
    # docstring). Pushing CredentialsScreen again for the second case would be
    # actively misleading, since the login itself is fine.
    monkeypatch.setattr(tui.club_directory, "any_credentials", lambda: None)
    monkeypatch.setattr(tui.club_directory, "credentials_configured", lambda: True)

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_refresh_directory()
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)  # not pushed into CredentialsScreen
            status = app.screen.query_one("#club-status", Static)
            assert i18n.t("picker.directory_needs_a_club") in str(status.content)

    _run(scenario())


def test_club_browser_r_uses_a_typed_club_id_with_no_favorite_needed(monkeypatch):
    # Direct pushback the same day, right after the fix above shipped: "it is a
    # chicken-and-egg problem" -- favoriting was never actually required, just
    # knowing a real club_id to authenticate against, which a typed id in the search
    # box already provides without ever being favorited. This is the case that
    # pushback fixed: real credentials, no favorite at all, but a club id typed into
    # #club-search -- 'r' should use it directly rather than asking for a favorite.
    monkeypatch.setattr(tui.club_directory, "any_credentials", lambda: None)
    monkeypatch.setattr(tui.club_directory, "credentials_configured", lambda: True)
    monkeypatch.setattr(tui.club_config, "resolve_credentials", lambda club_id: ("plain-user", "plain-pass"))
    seen_calls = []
    monkeypatch.setattr(
        tui.club_directory,
        "refresh_directory",
        lambda club_id, user, password: (seen_calls.append((club_id, user, password)), [("0000002", "Golfclub Sonnenberg")])[1],
    )

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#club-search", Input).value = "0000002"
            await pilot.pause()  # let on_input_changed's own status update settle first
            app.screen.action_refresh_directory()
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            status = app.screen.query_one("#club-status", Static)
            assert i18n.t("picker.directory_refreshed", count=1) in str(status.content)

    _run(scenario())
    assert seen_calls == [("0000002", "plain-user", "plain-pass")]


def test_club_browser_l_opens_credentials_screen_proactively(monkeypatch):
    # Credentials are already configured here -- 'l' still opens the screen, unlike
    # 'r' above, which only pushes it reactively once it discovers none exist.
    monkeypatch.setattr(tui.club_directory, "any_credentials", lambda: ("0000001", "user", "pass"))

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            # Not pilot.press("l") -- focus starts in #club-search, and a focused
            # Input gets first refusal on a printable key before any Screen-level
            # binding sees it (same reasoning as CredentialsScreen's own "q" note),
            # so a real keypress would just type "l" into the search box instead.
            app.screen.action_login()
            await pilot.pause()
            assert isinstance(app.screen, tui.CredentialsScreen)

    _run(scenario())


def test_saving_credentials_from_club_browser_retries_the_directory_fetch(monkeypatch):
    # any_credentials() reports "none yet" the first time (driving the reactive push
    # from 'r'), then "configured" from the second call onward -- simulating the
    # save actually taking effect, same shape the real club_config-backed function
    # would show once CredentialsScreen writes real values to .env.
    calls = iter([None, ("0000001", "someone@example.com", "hunter2")])
    monkeypatch.setattr(tui.club_directory, "any_credentials", lambda: next(calls, ("0000001", "someone@example.com", "hunter2")))
    monkeypatch.setattr(tui.club_directory, "credentials_configured", lambda: False)
    monkeypatch.setattr(tui.club_directory, "refresh_directory", lambda *a, **k: [("0000001", "Golfclub Musterhausen")])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_refresh_directory()
            await pilot.pause()
            assert isinstance(app.screen, tui.CredentialsScreen)

            app.screen.query_one("#username").value = "someone@example.com"
            app.screen.query_one("#password").value = "hunter2"
            await pilot.click("#save")
            await pilot.pause()
            # Save itself doesn't dismiss the screen (it just writes and shows
            # "Saved.", so a typo can be fixed without reopening it) -- escape
            # dismisses with whatever _saved ended up as, same as the Cancel button.
            await pilot.press("escape")
            await pilot.pause()

            # Dismissing after a real save popped CredentialsScreen and retried the
            # fetch automatically --
            # back on ClubBrowserScreen, with the retried fetch's own result shown.
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            status = app.screen.query_one("#club-status", Static)
            assert i18n.t("picker.directory_refreshed", count=1) in str(status.content)

    _run(scenario())


# --- Real bug found live, 2026-09-08: un/re-favoriting a club from the plain
# favorites list (the default view, no search typed) handed geocode.find_club_location()
# the file *slug* instead of the club's real name, since ClubBrowserScreen._favorites()
# used to return the slug as if it were the display name -- a confirmed dead end for
# geocoding ("still no weather data" even after following the fix-it steps) --------


def _wire_real_club_config_to(monkeypatch, clubs_dir):
    """`club_config.list_clubs()`/`load_club_config()` still take a frozen
    `clubs_dir: Path = CLUBS_DIR` default (bound at import time, unlike
    `add_favorite()`/`is_favorite()`'s own `None`-sentinel pattern) -- patching
    `club_config.CLUBS_DIR` alone doesn't reach them. Same wiring already used
    further down this file (`test_day_detail_renders_german_table_headers...`);
    factored out here since the tests below need the exact same thing."""
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: _real_list_clubs(clubs_dir))
    monkeypatch.setattr(
        tui.club_config, "load_club_config", lambda slug, *a, **k: _real_load_club_config(slug, clubs_dir)
    )


def test_favorites_shows_the_saved_name_not_the_slug(tmp_path, monkeypatch):
    _wire_real_club_config_to(monkeypatch, tmp_path)
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])
    # A favorite saved with its real name persisted (2026-09-08's own fix) --
    # not just the lowercase, hyphenated slug this file happens to be named after.
    _real_save_club_config(
        "golfclub-domane-musterhausen-e-v",
        {"club_id": "0000001", "name": "Golfclub Domäne Musterhausen e.V."},
        tmp_path,
    )

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            option = app.screen.query_one(OptionList).get_option_at_index(0)
            assert "Golfclub Domäne Musterhausen e.V." in str(option.prompt)
            assert "golfclub-domane-musterhausen-e-v" not in str(option.prompt)

    _run(scenario())


def test_favorites_falls_back_to_the_slug_when_no_name_was_ever_saved(tmp_path, monkeypatch):
    # A favorite saved before this fix existed -- no `name` key at all. Must not
    # crash, and the slug is still better than nothing to show.
    _wire_real_club_config_to(monkeypatch, tmp_path)
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])
    _real_save_club_config("home-club", {"club_id": "0000001"}, tmp_path)

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            option = app.screen.query_one(OptionList).get_option_at_index(0)
            assert "home-club" in str(option.prompt)

    _run(scenario())


def test_unfavorite_then_refavorite_from_the_favorites_list_geocodes_with_the_real_name(
    tmp_path, monkeypatch
):
    # The exact real-world sequence that broke: a club already favorited with its
    # real name known sits on the plain favorites list (empty search box) --
    # toggling it off and back on must still pass that real name to the geocoder,
    # not the file's own slug.
    _wire_real_club_config_to(monkeypatch, tmp_path)
    monkeypatch.setattr(tui.club_config, "CLUBS_DIR", tmp_path)  # add_favorite/is_favorite's own default
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])
    _real_save_club_config(
        "golfclub-domane-musterhausen-e-v",
        {"club_id": "0000001", "name": "Golfclub Domäne Musterhausen e.V."},
        tmp_path,
    )
    seen_names = []
    monkeypatch.setattr(
        tui.club_config.geocode, "find_club_location", lambda name: seen_names.append(name) or None
    )

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen())
        async with app.run_test() as pilot:
            await pilot.pause()
            option_list = app.screen.query_one(OptionList)
            option_list.focus()
            option_list.highlighted = 0
            await pilot.pause()
            app.screen.action_toggle_favorite()  # unfavorite
            await pilot.pause()
            # This was the *only* favorite -- unfavoriting it emptied the list, so
            # re-favoriting means finding it again by *name* (a search against the
            # cached directory carries the real name back with it); typing the
            # numeric id instead deliberately does not (`store_names=False`, see
            # `on_input_changed()`'s own comment -- "open this club" is a prompt,
            # not a name), so that path alone still can't geocode either.
            app.screen._directory = [("0000001", "Golfclub Domäne Musterhausen e.V.")]
            app.screen.query_one("#club-search", Input).value = "musterhausen"
            await pilot.pause()
            option_list = app.screen.query_one(OptionList)
            option_list.focus()
            option_list.highlighted = 0
            await pilot.pause()
            app.screen.action_toggle_favorite()  # re-favorite
            await pilot.pause()

    _run(scenario())

    assert seen_names == ["Golfclub Domäne Musterhausen e.V."]


def test_course_picker_footer_says_enter_opens_a_course():
    # Same gap, same fix as ClubBrowserScreen/OverviewScreen -- see their tests above.
    async def scenario():
        app = _HostApp(tui.CoursePickerScreen(["18 Loch Tee 1", "9 Loch Tee 1"]))
        async with app.run_test() as pilot:
            await pilot.pause()
            text = app.screen.query_one(tui.TranslatedFooter).render()
            assert "enter" in text and "Open" in text

    _run(scenario())


def test_course_picker_dismisses_with_selected_course():
    async def scenario():
        app = _HostApp(tui.CoursePickerScreen(["18 Loch Tee 1", "9 Loch Tee 1"]))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.result == "18 Loch Tee 1"

    _run(scenario())


# --- Version display -- added 2026-09-10, direct request: "implement a version
# display like with brew launcher" (that project shows its version both via
# `--version` and always, directly in its running UI's border). ------------------


def test_version_reads_installed_package_metadata(monkeypatch):
    monkeypatch.setattr(tui.importlib.metadata, "version", lambda name: "1.2.3")
    assert tui._version() == "1.2.3"


def test_version_falls_back_to_dev_when_not_installed(monkeypatch):
    def raise_not_found(name):
        raise tui.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(tui.importlib.metadata, "version", raise_not_found)
    assert tui._version() == "dev"


def test_main_prints_version_and_exits_without_launching_the_app(monkeypatch, capsys):
    monkeypatch.setattr(tui, "_version", lambda: "1.2.3")
    monkeypatch.setattr(tui.sys, "argv", ["teetime-monitor", "--version"])
    ran = []
    monkeypatch.setattr(tui.TeetimeApp, "run", lambda self: ran.append(True))

    tui.main()

    assert ran == []
    assert "teetime-monitor 1.2.3" in capsys.readouterr().out


def test_teetime_app_shows_the_version_in_its_sub_title(monkeypatch):
    monkeypatch.setattr(tui, "_version", lambda: "1.2.3")
    assert tui.TeetimeApp().sub_title == "v1.2.3"


# --- Credentials screen shown first at startup -- added 2026-09-10, direct request:
# "I want the login screen to appear first, whenever you don't have a login." -------


def test_start_shows_credentials_screen_first_when_none_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_directory, "any_credentials", lambda: None)
    monkeypatch.setattr(tui.club_directory, "credentials_configured", lambda: False)

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, tui.CredentialsScreen)

    _run(scenario())


def test_start_skips_credentials_screen_when_already_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    # The default autouse fixture already reports "configured" -- this is the same
    # thing spelled out explicitly, as a real assertion rather than an implicit
    # assumption every other startup test here already makes.

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)

    _run(scenario())


def test_start_reaches_club_browser_after_dismissing_credentials_without_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_directory, "any_credentials", lambda: None)
    monkeypatch.setattr(tui.club_directory, "credentials_configured", lambda: False)

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, tui.CredentialsScreen)
            await pilot.press("escape")
            await pilot.pause()
            # Entirely skippable -- escaping without saving still reaches the club
            # browser, not a dead end or an unexpected app exit.
            assert isinstance(app.screen, tui.ClubBrowserScreen)

    _run(scenario())


# --- TeetimeApp startup flow ------------------------------------------------------------


def test_app_opens_the_club_browser_then_honors_default_course(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    # TeetimeApp.on_mount() applies a theme, which persists to disk -- redirect it
    # away from the real ~/.config/teetime-monitor/config for the duration of the test.
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            # The club browser is the home screen now, always -- but once a club is
            # picked, a favorite's own default_course still skips the course picker.
            await _reach_day_detail(app, pilot)
            screen = app.screen
            assert isinstance(screen, tui.DayDetailScreen)
            assert screen.course == "9 Loch Tee 1"
            assert screen.club_id == "0000001"
            assert screen.club_slug == "home-club"  # resolved from the club id

    _run(scenario())


# --- Resume the last-used club/course, skipping both pickers -- added 2026-09-10,
# direct feedback: "when you launch teetime-monitor you are greeted with which club
# to select, then which course. I think this is redundant since you can now select
# club and courses from the overview." ------------------------------------------


def test_start_resumes_the_last_active_club_skipping_both_pickers(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(
        tui.global_preferences,
        "load_last_active_club",
        lambda *a, **k: {"club_id": "0000001", "slug": "home-club", "course": "9 Loch Tee 1"},
    )
    monkeypatch.setattr(
        tui.club_config, "load_club_config", lambda slug, *a, **k: {"club_id": "0000001"}
    )
    monkeypatch.setattr(tui, "fetch_course_aliases", lambda club_id: {"9 Loch Tee 1": "COU1"})

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            # Never shown ClubBrowserScreen or CoursePickerScreen at all -- straight
            # to the overview with the remembered club/course.
            assert isinstance(app.screen, tui.OverviewScreen)
            assert app.screen.club_id == "0000001"
            assert app.screen.course == "9 Loch Tee 1"

    _run(scenario())


def test_start_resumes_the_last_active_club_even_when_its_yaml_file_is_missing(tmp_path, monkeypatch):
    # Real crash, found live 2026-09-11: clubs/*.yaml is deliberately cwd-relative
    # (see club_config.py's own docstring), but the remembered slug in
    # ~/.config/teetime-monitor/config is not -- it survives across whatever
    # directory teetime-monitor happens to be launched from next. Launching from a
    # directory whose clubs/ doesn't have this particular file raised an unguarded
    # FileNotFoundError straight out of _resume_last_active() and crashed the whole
    # app before it ever got a chance to fall back to the pickers. This should
    # degrade to an empty config and still resume -- the live fetch_course_aliases()
    # check right after is what actually decides whether the remembered club/course
    # is still good, not whether its local settings file happens to be readable.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(
        tui.global_preferences,
        "load_last_active_club",
        lambda *a, **k: {"club_id": "0000001", "slug": "home-club", "course": "9 Loch Tee 1"},
    )
    # list_clubs() and load_club_config() both read the same real clubs/ directory,
    # so they can't disagree about whether "home-club" is there -- the true-to-life
    # shape of this bug is a clubs/ directory that simply doesn't have this file at
    # all (list_clubs() -> []), while the *remembered* slug (a separate, non-
    # cwd-relative file -- see global_preferences.load_last_active_club()) still
    # names it anyway.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])

    def missing(slug, *a, **k):
        raise FileNotFoundError(2, "No such file or directory", f"clubs/{slug}.yaml")

    monkeypatch.setattr(tui.club_config, "load_club_config", missing)
    monkeypatch.setattr(tui, "fetch_course_aliases", lambda club_id: {"9 Loch Tee 1": "COU1"})

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, tui.OverviewScreen)
            assert app.screen.club_id == "0000001"
            assert app.screen.course == "9 Loch Tee 1"

    _run(scenario())


def test_start_falls_back_to_pickers_when_the_remembered_course_no_longer_exists(tmp_path, monkeypatch):
    # The club's own course lineup changed since -- a stale remembered choice
    # should degrade to asking again, not silently open onto a course that
    # doesn't exist any more.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(
        tui.global_preferences,
        "load_last_active_club",
        lambda *a, **k: {"club_id": "0000001", "slug": "home-club", "course": "a course that no longer exists"},
    )
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config, "load_club_config", lambda slug, *a, **k: {"club_id": "0000001"}
    )
    monkeypatch.setattr(tui, "fetch_course_aliases", lambda club_id: {"9 Loch Tee 1": "COU1"})

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)

    _run(scenario())


def test_start_falls_back_to_pickers_when_the_remembered_clubs_fetch_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(
        tui.global_preferences,
        "load_last_active_club",
        lambda *a, **k: {"club_id": "0000001", "slug": "home-club", "course": "9 Loch Tee 1"},
    )
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config, "load_club_config", lambda slug, *a, **k: {"club_id": "0000001"}
    )

    def boom(club_id):
        raise RuntimeError("no network")

    monkeypatch.setattr(tui, "fetch_course_aliases", boom)

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)

    _run(scenario())


def test_start_ignores_a_remembered_club_when_none_was_ever_saved(tmp_path, monkeypatch):
    # The default, autouse-fixture-backed case (see _no_real_last_active_club_by_
    # default) -- explicit here as a real assertion rather than an implicit
    # assumption every other startup test already makes.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)

    _run(scenario())


def test_open_club_saves_the_last_active_club(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )
    saved = []
    monkeypatch.setattr(
        tui.global_preferences, "save_last_active_club", lambda *a, **k: saved.append(a)
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_overview(app, pilot)

    _run(scenario())
    assert saved == [("0000001", "home-club", "9 Loch Tee 1")]


# --- Auto-refresh (2026-09-07, direct feedback: "can we make autorefresh for the
# maximum timeframe, whenever you run the TUI and at the defined time intervals? I
# think hitting 'r' makes only sense as a manual override") ------------------------


def test_periodic_scrape_runs_once_on_open_with_the_active_slug_and_config(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    club_cfg = {"club_id": "0000001", "default_course": "9 Loch Tee 1"}
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: club_cfg)

    calls = []

    def fake_scrape(slug, config):
        calls.append((slug, config))
        return []

    monkeypatch.setattr(scrape_once, "scrape_due_for_club", fake_scrape)

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            for _ in range(20):
                if calls:
                    break
                await pilot.pause(0.05)
            assert calls == [("home-club", club_cfg)]

    _run(scenario())


def test_periodic_scrape_picks_up_a_club_config_change_mid_session(tmp_path, monkeypatch):
    # Real gap found and fixed 2026-09-08, from a real screenshot: a location added
    # to a club's own clubs/*.yaml after this session's already-running app opened
    # it (e.g. via `f`-to-favorite while already viewing that club) must take
    # effect on the very next scheduled scrape, not stay invisible until the app
    # restarts or the club is reopened -- "I still don't see any weather forecast"
    # even after a location had genuinely been added. Root cause: _periodic_scrape()
    # was handing scrape_due_for_club() the exact dict snapshotted once in
    # _open_club(), never re-read afterward.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    club_cfg = {"club_id": "0000001", "default_course": "9 Loch Tee 1"}
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: club_cfg)

    calls = []
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: calls.append(config) or [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            for _ in range(20):
                if calls:
                    break
                await pilot.pause(0.05)
            assert "location" not in calls[0]

            # The club's own file gains a location mid-session -- e.g. by hand, or
            # by re-favoriting through the now-fixed automatic lookup.
            club_cfg["location"] = {"lat": 48.5, "lon": 8.8}
            app._periodic_scrape_running = False
            app._periodic_scrape()
            for _ in range(20):
                if len(calls) > 1:
                    break
                await pilot.pause(0.05)
            assert calls[-1].get("location") == {"lat": 48.5, "lon": 8.8}

    _run(scenario())


def test_periodic_scrape_still_runs_for_a_club_visited_without_saving_it(tmp_path, monkeypatch):
    # Direct feedback 2026-09-07: "I selected a random club... the tee times don't
    # automatically refresh, I had to hit 'r'". Root cause: an unsaved club's config
    # is {} (nothing to load club_id back out of), and scrape_due_for_club() silently
    # does nothing at all without a club_id in the config it's handed -- auto-refresh
    # was never running for any club that wasn't a saved favorite, the exact case the
    # same-day favorites rework was supposed to make first-class.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])  # no favorites at all
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    calls = []
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: calls.append(config) or [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            app.screen.dismiss("0352002")  # a club reached by id, never saved
            await pilot.pause()
            assert isinstance(app.screen, tui.CoursePickerScreen)
            app.screen.dismiss("18 Loch Tee 1")
            for _ in range(20):
                if calls:
                    break
                await pilot.pause(0.05)
            assert calls and calls[0].get("club_id") == "0352002"

    _run(scenario())


def test_periodic_scrape_reloads_the_day_detail_screen_when_done(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            screen = app.screen
            reload_calls = []
            monkeypatch.setattr(screen, "load_schedule", lambda: reload_calls.append("load"))
            monkeypatch.setattr(screen, "refresh_banners", lambda: reload_calls.append("banners"))

            # Trigger another pass directly rather than waiting on the real interval
            # timer (15 minutes) -- exercises the same _finish_periodic_scrape() path
            # that the timer would eventually reach on its own.
            app._periodic_scrape_running = False
            app._periodic_scrape()

            for _ in range(20):
                if reload_calls:
                    break
                await pilot.pause(0.05)
            assert "load" in reload_calls
            assert "banners" in reload_calls

    _run(scenario())


def test_periodic_scrape_skips_a_new_pass_while_one_is_already_running(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )
    calls = []
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: calls.append(1) or [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            for _ in range(20):  # wait for the automatic on-open pass to finish
                if calls:
                    break
                await pilot.pause(0.05)
            assert calls == [1]

            # Force the flag on to simulate a pass still in flight, and confirm a
            # second call is a genuine no-op -- no additional scrape gets started.
            app._periodic_scrape_running = True
            app._periodic_scrape()
            await pilot.pause(0.1)
            assert calls == [1]

    _run(scenario())


def test_periodic_scrape_shows_refreshing_then_refreshed_status(tmp_path, monkeypatch):
    # Direct feedback 2026-09-07: "I noticed a slight delay between the auto-refresh
    # and seeing the updated schedule. Wouldn't it be better if the tool had a
    # loading screen?" -- a status-line message instead, so the delay is explained
    # without blocking the UI (the whole point of running this in a thread).
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )
    proceed = threading.Event()
    started = threading.Event()

    def fake_scrape(slug, config):
        started.set()
        proceed.wait(timeout=2)
        return []

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            # Reach day detail first, on the fast no-op scrape the autouse fixture
            # already installs -- only then swap in the slow one and trigger it
            # directly (same pattern as the sibling periodic_scrape tests above).
            # Racing the slow scrape against _reach_day_detail's own navigation
            # (through OverviewScreen, added 2026-09-07) would show "Refreshing…" on
            # whichever screen was current when the scrape *started*, not the one
            # navigated to afterward -- a real but narrow inconsistency, not what
            # this test is actually about.
            await _reach_day_detail(app, pilot)
            monkeypatch.setattr(scrape_once, "scrape_due_for_club", fake_scrape)
            app._periodic_scrape_running = False
            app._periodic_scrape()

            await asyncio.get_event_loop().run_in_executor(None, started.wait, 2)
            await pilot.pause()
            assert "Refreshing" in str(app.screen.query_one("#status", Static).content)

            proceed.set()
            for _ in range(20):
                if "Refreshed" in str(app.screen.query_one("#status", Static).content):
                    break
                await pilot.pause(0.05)
            assert "Refreshed" in str(app.screen.query_one("#status", Static).content)

    _run(scenario())


# --- Switching club/course from the day-detail screen (2026-09-07, direct feedback:
# "how can i switch to a different course from the time schedule menu? It is somehow
# not possible to return to the previous menus like choosing the course or login") --


def test_switch_action_honors_default_course_skipping_the_course_picker(tmp_path, monkeypatch):
    # Direct feedback, 2026-09-11: "when you go to the club selector by hitting s,
    # it still asks you to select a course. This seems redundant" -- once the
    # overview's own inline course selector already makes changing course trivial
    # without any picker, forcing one here too, even onto a club whose course is
    # already unambiguous (a saved default_course), stopped serving a purpose.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.course == "9 Loch Tee 1"  # default_course, honored at launch

            await pilot.press("s")
            await pilot.pause()
            # Switching opens the very same club browser the app launches into.
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            app.screen.dismiss("0000001")
            await pilot.pause()
            await pilot.pause()
            # ...and lands straight on the overview with the saved default_course,
            # no course picker at all -- this club's only own real ambiguity was
            # already resolved.
            assert isinstance(app.screen, tui.OverviewScreen)
            assert app.screen.course == "9 Loch Tee 1"
            assert app.screen.club_id == "0000001"
            # Pops back to the app's base first, so the old DayDetailScreen this
            # switch started from isn't left buried underneath.
            assert len(app.screen_stack) == 2  # base + the one fresh OverviewScreen

    _run(scenario())


def test_switch_action_still_shows_the_course_picker_when_genuinely_ambiguous(tmp_path, monkeypatch):
    # No default_course set, and more than one real course -- there's still a
    # genuine choice to make here, so this one still asks. default_course is set
    # during the *initial* launch only (so _reach_day_detail()'s own setup stays
    # unambiguous, same as every other test using it -- OverviewScreen's own
    # _config() re-reads it too, not just _open_club(), so a call-counting mock
    # can't tell "initial setup" and "the switch itself" apart reliably) and
    # dropped right before pressing `s`, simulating the switch landing on a club
    # with no default -- the actual scenario under test here.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    state = {"has_default": True}

    def load_club_config(slug, *a, **k):
        if state["has_default"]:
            return {"club_id": "0000001", "default_course": "9 Loch Tee 1"}
        return {"club_id": "0000001"}

    monkeypatch.setattr(tui.club_config, "load_club_config", load_club_config)

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            state["has_default"] = False

            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            app.screen.dismiss("0000001")
            await pilot.pause()
            assert isinstance(app.screen, tui.CoursePickerScreen)

            app.screen.dismiss("18 Loch Tee 1")
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, tui.OverviewScreen)
            assert app.screen.course == "18 Loch Tee 1"

    _run(scenario())


def test_switch_action_shows_club_picker_when_multiple_clubs_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club", "guest-club"])
    configs = {
        "home-club": {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
        "guest-club": {"club_id": "0352001", "default_course": "18 Loch Tee 1"},
    }
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: configs[slug])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.club_id == "0000001"

            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)

            app.screen.dismiss("0352001")
            await pilot.pause()
            await pilot.pause()
            # Lands straight on the overview with guest-club's own saved
            # default_course -- no course picker at all any more (2026-09-11,
            # direct feedback: "when you go to the club selector by hitting s, it
            # still asks you to select a course. This seems redundant").
            assert isinstance(app.screen, tui.OverviewScreen)
            assert app.screen.club_id == "0352001"
            assert app.screen.club_slug == "guest-club"
            assert app.screen.course == "18 Loch Tee 1"

    _run(scenario())


# --- ClubPickerScreen / CoursePickerScreen: escape backs out, q quits (2026-09-07,
# direct feedback: "how do I quit from club/course picker or return to the
# schedule?" -- there was previously no way to back out short of force-quitting) ----


def test_club_browser_escape_dismisses_with_none(monkeypatch):
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen(allow_cancel=True))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_cancel()
            await pilot.pause()
            assert app.result is None

    _run(scenario())


def test_club_browser_escape_does_nothing_when_cancel_is_disallowed(monkeypatch):
    # At launch there's nothing behind the club list to go back to, so escape must
    # not drop the user onto a blank app.
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])
    monkeypatch.setattr(tui.club_directory, "load_cached_directory", lambda *a, **k: [])

    async def scenario():
        app = _HostApp(tui.ClubBrowserScreen(allow_cancel=False))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_cancel()
            await pilot.pause()
            assert app.result == "not dismissed yet"

    _run(scenario())


def test_course_picker_screen_escape_dismisses_with_none():
    async def scenario():
        app = _HostApp(tui.CoursePickerScreen(["18 Loch Tee 1", "9 Loch Tee 1"]))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_cancel()
            await pilot.pause()
            assert app.result is None

    _run(scenario())


# --- Switching club/course: backing out at any step leaves the schedule unchanged,
# and searching for a new club integrates directly into the same flow (2026-09-07,
# direct feedback: "I want to be able to switch clubs on the fly. It is a hassle if
# you need to first save clubs into the config") --------------------------------------


def test_switch_action_cancelling_club_picker_leaves_schedule_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            original_screen = app.screen
            assert isinstance(original_screen, tui.DayDetailScreen)

            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            app.screen.action_cancel()
            await pilot.pause()

            assert app.screen is original_screen
            assert app.screen.course == "9 Loch Tee 1"

    _run(scenario())


def test_switch_action_cancelling_course_picker_leaves_schedule_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    # default_course set during the *initial* launch only (_reach_day_detail()'s
    # own setup, kept unambiguous like every other test using it -- see the
    # previous test's own comment for why a call-counting mock can't reliably
    # tell "initial setup" and "the switch itself" apart), dropped right before
    # pressing `s` so the switch step itself is a genuine choice between several
    # real courses -- the one case that still shows the course picker at all (see
    # the two tests above).
    state = {"has_default": True}

    def load_club_config(slug, *a, **k):
        if state["has_default"]:
            return {"club_id": "0000001", "default_course": "9 Loch Tee 1"}
        return {"club_id": "0000001"}

    monkeypatch.setattr(tui.club_config, "load_club_config", load_club_config)

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            original_screen = app.screen
            original_course = app.screen.course
            state["has_default"] = False

            await pilot.press("s")
            await pilot.pause()
            app.screen.dismiss("0000001")  # the only real club
            await pilot.pause()
            assert isinstance(app.screen, tui.CoursePickerScreen)
            app.screen.action_cancel()
            await pilot.pause()

            assert app.screen is original_screen
            assert app.screen.course == original_course

    _run(scenario())


def test_switch_action_reaches_an_unsaved_club_from_the_directory(tmp_path, monkeypatch):
    """Switching to a club that was never saved to config -- the whole point of the
    2026-09-07 rework. The old flow needed a club saved to clubs/*.yaml before it could
    be opened at all; now a directory hit is enough, and saving is purely optional
    (the `f` favorite toggle, tested separately)."""
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    (tmp_path / "clubs").mkdir()
    (tmp_path / "clubs" / "home-club.yaml").write_text("club_id: '0000001'\ndefault_course: '18 Loch Tee 1'\n")
    monkeypatch.setattr(tui.club_config, "CLUBS_DIR", tmp_path / "clubs")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: _real_list_clubs(tmp_path / "clubs"))
    monkeypatch.setattr(
        tui.club_config, "load_club_config", lambda slug, *a, **k: _real_load_club_config(slug, tmp_path / "clubs")
    )
    monkeypatch.setattr(
        tui.club_directory, "load_cached_directory",
        lambda *a, **k: [("0491605", "1. Golfclub Leipzig e.V.")],
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            assert isinstance(app.screen, tui.DayDetailScreen)
            assert app.screen.club_slug == "home-club"

            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, tui.ClubBrowserScreen)
            app.screen.query_one("#club-search", Input).value = "leipzig"
            await pilot.pause()
            options = app.screen.query_one(OptionList)
            assert options.option_count == 1
            options.focus()
            options.highlighted = 0
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # Straight into course-picking for a club that has no clubs/*.yaml at all.
            assert isinstance(app.screen, tui.CoursePickerScreen)
            app.screen.dismiss("9 Loch Tee 1")
            await pilot.pause()
            await pilot.pause()

            assert isinstance(app.screen, tui.OverviewScreen)
            assert app.screen.club_id == "0491605"
            assert app.screen.club_slug is None  # visited, not saved
            assert app.screen.course == "9 Loch Tee 1"

    _run(scenario())

    # Nothing was written to config -- visiting a club must not save it.
    assert tui.club_config.list_clubs(tmp_path / "clubs") == ["home-club"]


def _fake_option_selected(option_id: str):
    class _FakeOption:
        id = option_id

    class _FakeEvent:
        option = _FakeOption()

    return _FakeEvent()


def test_app_exits_cleanly_with_no_clubs_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()

    _run(scenario())


# --- Themes -------------------------------------------------------------------------


def test_app_applies_resolved_theme_on_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    theme.save_theme("nord", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "nord"

    _run(scenario())


def test_app_persists_theme_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.theme = "green"
            await pilot.pause()

    _run(scenario())

    assert theme.load_saved_theme(tmp_path / "theme-config") == "green"


def test_app_persists_a_native_textual_theme_with_no_brew_launcher_equivalent(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.theme = "monokai"  # a real Textual theme, not one of the 10 named here
            await pilot.pause()

    _run(scenario())

    assert theme.load_saved_theme(tmp_path / "theme-config") == "monokai"


def test_day_detail_t_binding_opens_command_palette(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            from textual.command import CommandPalette

            assert any(isinstance(screen, CommandPalette) for screen in app.screen_stack)

    _run(scenario())


# --- Language (bilingual UI) ----------------------------------------------------------


def test_day_detail_renders_german_table_headers_and_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    i18n.set_language("de")

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert [str(col.label) for col in table.columns.values()] == [
                "Zeit", "Wetterlage", "Belegung", "Spieler", "Temperatur (°C)", "Niederschlag (%/mm)",
                "Wind (km/h)", "Termine",
            ]
            row = table.get_row_at(0)
            assert row[2] == "noch keine Daten"

    _run(scenario())


def test_confirm_booking_renders_german_labels_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    i18n.set_language("de")

    async def scenario():
        from textual.widgets import Button

        app = _HostApp(tui.ConfirmBookingScreen("0000001", "18 Loch Tee 1", "2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert str(app.screen.query_one("#save", Button).label) == "Speichern"
            await pilot.click("#save")
            await pilot.pause()
            assert "Uhrzeit" in str(app.screen.query_one("#confirm-status", Static).content)

    _run(scenario())


def test_app_switch_language_command_rebuilds_day_detail_screen_in_german(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club"])
    monkeypatch.setattr(
        tui.club_config,
        "load_club_config",
        lambda slug, *a, **k: {"club_id": "0000001", "default_course": "9 Loch Tee 1"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot)
            assert i18n.get_language() == "en"  # default, per the autouse fixture

            app.action_switch_language()
            await pilot.pause()

            table = app.screen.query_one(DataTable)
            assert [str(col.label) for col in table.columns.values()] == [
                "Zeit", "Wetterlage", "Belegung", "Spieler", "Temperatur (°C)", "Niederschlag (%/mm)",
                "Wind (km/h)", "Termine",
            ]

    _run(scenario())

    # The autouse fixture points i18n.CONFIG_FILE at this same tmp_path -- confirms
    # action_switch_language() actually persisted the change, not just applied it live.
    assert i18n.load_saved_language(tmp_path / "not-used-unless-a-test-wants-it") == "de"


def test_day_detail_footer_renders_translated_hints_in_english(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            footer = app.screen.query_one(tui.TranslatedFooter)
            text = footer.render()
            assert "Refresh" in text
            assert "Confirm/cancel tee time" in text
            assert "Settings" in text
            assert "Quit" in text

    _run(scenario())


def test_day_detail_footer_wraps_instead_of_hiding_hints_in_a_narrow_window(tmp_path, monkeypatch):
    # Point 5, direct feedback (2026-09-08): "the bottom menu bar (the one that
    # shows the keybinds) doesn't scale well when you resize the window (i.e. some
    # elements might be hidden, if the window is too narrow)". DayDetailScreen has
    # ten key hints -- one long joined line is far wider than a narrow terminal, so
    # a fixed height: 1 footer could only clip it, not wrap it. Checks the actual
    # resolved height at a narrow width, not just that the CSS text changed.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test(size=(40, 24)) as pilot:
            await pilot.pause()
            footer = app.screen.query_one(tui.TranslatedFooter)
            assert footer.size.height > 1

    _run(scenario())


def test_day_detail_footer_renders_translated_hints_in_german(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    i18n.set_language("de")

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            footer = app.screen.query_one(tui.TranslatedFooter)
            text = footer.render()
            assert "Aktualisieren" in text
            assert "Tee-Zeit bestätigen/stornieren" in text
            assert "Beenden" in text

    _run(scenario())


def test_day_detail_banner_renders_localized_from_params(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_booking_change(
        course="18 Loch Tee 1",
        date="2026-09-06",
        time="14:00",
        kind="party_grew",
        message="2 more players joined your 14:00 tee time since you booked",
        params={"count": 2, "time": "14:00"},
        path=scrape_once._db_path("0000001"),
    )
    i18n.set_language("de")

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            banner = app.screen.query_one("#banners", Static)
            assert "weitere Spieler sind" in str(banner.content)
            assert "14:00" in str(banner.content)

    _run(scenario())


# --- Inline club/course selectors on OverviewScreen -- added 2026-09-09, direct
# feedback: "would it be possible to integrate club and course selectors into the
# overview screen (i.e. no need to jump between screens)? I believe this would make
# navigation much quicker." Course switching is self-contained (no App-level state to
# update, since scrape_once.scrape_due_for_club() already scrapes every one of a
# club's courses regardless of which is showing) -- club switching also has to update
# TeetimeApp._club_slug/_club_config, the exact bookkeeping _open_club() itself does,
# so the periodic background scrape follows the switch too (see that method's own
# docstring for the real bug this fixes once before). ---------------------------------


def test_refresh_course_options_does_not_spuriously_switch_the_active_course(tmp_path, monkeypatch):
    # Regression test for a real bug found live, 2026-09-10, while adding
    # last-active-club persistence: _refresh_course_options()'s own set_options()
    # call used to briefly reset the course Select to its new first option (not
    # necessarily the active course) before immediately correcting it back --
    # firing a real, non-blank Select.Changed for that transient wrong value along
    # the way, which on_select_changed() treated as a genuine switch. Harmless
    # before _switch_course() started persisting state, but not any more. The
    # active course is now kept first in the options list handed to set_options(),
    # so there's no transient wrong value left to spuriously switch to.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    # The live course list's own order puts the active course last -- exactly the
    # shape that used to produce a transient first-option value different from it.
    monkeypatch.setattr(
        tui, "fetch_course_aliases", lambda club_id: {"18 Loch Tee 1": "COUB", "9 Loch Tee 1": "COU1"}
    )
    switches = []
    saved = []
    monkeypatch.setattr(tui.global_preferences, "save_last_active_club", lambda *a, **k: saved.append(a))

    async def scenario():
        screen = tui.OverviewScreen("0000001", "musterhausen", "9 Loch Tee 1")
        screen._switch_course = lambda course: switches.append(course)
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert screen.course == "9 Loch Tee 1"  # never actually changed
            assert screen.query_one("#course-select", Select).value == "9 Loch Tee 1"

    _run(scenario())
    assert switches == []  # _switch_course() itself never got called at all
    assert saved == []  # and so nothing spurious was ever persisted either


def test_overview_screen_switches_course_inline_without_leaving_the_screen(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        screen = tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1")
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            course_select = app.screen.query_one("#course-select", Select)
            assert course_select.value == "18 Loch Tee 1"
            course_select.value = "9 Loch Tee 1"
            await pilot.pause()
            assert app.screen is screen  # stayed on the same screen -- no navigation
            assert screen.course == "9 Loch Tee 1"
            # OverviewScreen doesn't set its own title at all any more
            # (2026-09-11, direct feedback: "remove the club/course names since
            # they will be redundant" -- the labelled #switcher dropdowns
            # already show both) -- Header falls back to the App's own plain
            # TITLE instead, so there's genuinely nothing screen-specific left
            # to assert here.
            assert screen.title is None

    _run(scenario())


def test_overview_screen_switching_course_inline_saves_the_last_active_club(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    saved = []
    monkeypatch.setattr(tui.global_preferences, "save_last_active_club", lambda *a, **k: saved.append(a))

    async def scenario():
        screen = tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1")
        app = _HostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.query_one("#course-select", Select).value = "9 Loch Tee 1"
            await pilot.pause()

    _run(scenario())
    assert saved == [("0000001", "musterhausen", "9 Loch Tee 1")]


def test_overview_screen_switches_club_inline_and_keeps_periodic_scrape_in_sync(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club", "second-club"])
    configs = {
        "home-club": {"club_id": "0000001"},
        "second-club": {"club_id": "0500000", "name": "Musterclub", "default_course": "9 Loch Tee 1"},
    }
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: configs[slug])
    monkeypatch.setattr(
        tui,
        "fetch_course_aliases",
        lambda club_id: {"9 Loch Tee 1": "COU1"} if club_id == "0500000" else {"18 Loch Tee 1": "COUB"},
    )
    calls = []
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config: calls.append((slug, config)) or [])

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_overview(app, pilot, club_id="0000001")
            screen = app.screen
            calls.clear()  # drop whatever _start() itself already triggered

            club_select = screen.query_one("#club-select", Select)
            assert club_select.value == "0000001"
            club_select.value = "0500000"
            await pilot.pause()
            await pilot.pause()

            assert app.screen is screen  # still the same OverviewScreen -- no push/pop
            assert screen.club_id == "0500000"
            assert screen.club_slug == "second-club"
            assert screen.course == "9 Loch Tee 1"  # configs["second-club"]'s default_course
            assert screen.query_one("#course-select", Select).value == "9 Loch Tee 1"
            # No title assertion here any more -- see the analogous course-switch
            # test's own comment: OverviewScreen doesn't set a title at all now.
            assert screen.title is None

            # The App's own active-club bookkeeping followed the switch too -- the
            # exact state _periodic_scrape() reads on its next tick.
            assert app._club_slug == "second-club"
            assert app._club_config.get("club_id") == "0500000"

            for _ in range(20):
                if calls:
                    break
                await pilot.pause(0.05)
            assert calls[-1][0] == "second-club"

    _run(scenario())


def test_overview_screen_switching_club_inline_saves_the_last_active_club(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["home-club", "second-club"])
    configs = {
        "home-club": {"club_id": "0000001"},
        "second-club": {"club_id": "0500000", "name": "Musterclub", "default_course": "9 Loch Tee 1"},
    }
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: configs[slug])
    monkeypatch.setattr(
        tui,
        "fetch_course_aliases",
        lambda club_id: {"9 Loch Tee 1": "COU1"} if club_id == "0500000" else {"18 Loch Tee 1": "COUB"},
    )
    saved = []
    monkeypatch.setattr(tui.global_preferences, "save_last_active_club", lambda *a, **k: saved.append(a))

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_overview(app, pilot, club_id="0000001")
            saved.clear()  # drop whatever _open_club() itself already saved on open
            app.screen.query_one("#club-select", Select).value = "0500000"
            await pilot.pause()
            await pilot.pause()

    _run(scenario())
    assert saved == [("0500000", "second-club", "9 Loch Tee 1")]


def test_overview_screen_switcher_rows_are_labelled(tmp_path, monkeypatch):
    # Direct feedback, 2026-09-11: "I want labels to the left of club and course
    # selector drop downs."
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            labels = {str(label.content) for label in app.screen.query(Label)}
            assert i18n.t("switcher.club_label") in labels
            assert i18n.t("switcher.course_label") in labels

    _run(scenario())


def test_day_detail_screen_has_a_labelled_club_course_switcher(tmp_path, monkeypatch):
    # Direct feedback, 2026-09-11: "I want the club and course selector drop
    # downs also implemented in the detailed view."
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert screen.query_one("#club-select", Select).value == "0000001"
            assert screen.query_one("#course-select", Select).value == "18 Loch Tee 1"
            labels = {str(label.content) for label in screen.query(Label)}
            assert i18n.t("switcher.club_label") in labels
            assert i18n.t("switcher.course_label") in labels

    _run(scenario())


def test_day_detail_screen_switches_course_inline_keeping_the_same_date(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    storage.save_schedule(
        Schedule(date="2026-09-06", course="9 Loch Tee 1", slots=[Slot(time="08:00", booked=0, capacity=4)]),
        path=scrape_once._db_path("0000001"),
    )

    async def scenario():
        app = _HostApp(_day_detail())
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            screen.query_one("#course-select", Select).value = "9 Loch Tee 1"
            await pilot.pause()

            assert app.screen is screen  # reloaded in place -- no navigation
            assert screen.course == "9 Loch Tee 1"
            assert screen.date == "2026-09-06"  # unchanged by a course switch
            table = screen.query_one(DataTable)
            assert table.get_row_at(0)[0] == "08:00"  # the new course's own schedule

    _run(scenario())


def test_day_detail_screen_switches_club_inline_keeping_the_same_date(tmp_path, monkeypatch):
    # A real TeetimeApp, not a bare _HostApp -- _switch_club() also touches App-level
    # bookkeeping (app._periodic_scrape()) that only a real app has, same reasoning
    # as OverviewScreen's own analogous inline-club-switch test above.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theme, "CONFIG_FILE", tmp_path / "theme-config")
    monkeypatch.setattr(tui.club_config, "list_clubs", lambda *a, **k: ["musterhausen", "second-club"])
    configs = {
        "musterhausen": {"club_id": "0000001"},
        "second-club": {"club_id": "0500000", "name": "Musterclub", "default_course": "9 Loch Tee 1"},
    }
    monkeypatch.setattr(tui.club_config, "load_club_config", lambda slug, *a, **k: configs[slug])
    monkeypatch.setattr(
        tui,
        "fetch_course_aliases",
        lambda club_id: {"9 Loch Tee 1": "COU1"} if club_id == "0500000" else {"18 Loch Tee 1": "COUB"},
    )

    async def scenario():
        app = tui.TeetimeApp()
        async with app.run_test() as pilot:
            await _reach_day_detail(app, pilot, club_id="0000001")
            screen = app.screen
            today = tui._TODAY()
            screen.query_one("#club-select", Select).value = "0500000"
            await pilot.pause()
            await pilot.pause()

            assert app.screen is screen  # reloaded in place -- no navigation
            assert screen.club_id == "0500000"
            assert screen.club_slug == "second-club"
            assert screen.course == "9 Loch Tee 1"  # configs["second-club"]'s default_course
            assert screen.date == today  # unchanged by a club switch

    _run(scenario())


def test_day_detail_screen_title_shows_app_name_and_date_not_club_or_course(tmp_path, monkeypatch):
    # Direct feedback, 2026-09-11: "I want the header to include the name of the
    # TUI 'teetime-monitor' and remove the club/course names since they will be
    # redundant." The date stays (see _set_title()'s own docstring) -- nothing
    # else on this screen shows which day it is.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_day_detail(club_slug="musterhausen", course="18 Loch Tee 1", date="2026-09-06"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.title == f"{tui.TeetimeApp.TITLE} — 2026-09-06"
            assert "musterhausen" not in app.screen.title
            assert "18 Loch Tee 1" not in app.screen.title

    _run(scenario())


# HeatmapScreen (ROADMAP.md Phase 5) -- added 2026-09-08, direct request: "Can we
# still start building the UI for the heat map? We need a menu to track how much data
# has been collected, and how much is still needed to be functional." Also the first
# tests exercising _holidays_for_club()/_vacation_ranges_for_club(), the first real
# wiring of calendar_context.py into the running app.


def test_holidays_for_club_skips_the_fetch_without_a_country_code(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("should not have called fetch_public_holidays() at all")

    monkeypatch.setattr(tui.calendar_context, "fetch_public_holidays", fail)
    assert tui._holidays_for_club({}) == []


def test_holidays_for_club_returns_the_fetched_list(monkeypatch):
    monkeypatch.setattr(tui.calendar_context, "fetch_public_holidays", lambda code, year: ["2026-01-01"])
    config = {"calendar": {"country_code": "DE"}}
    assert tui._holidays_for_club(config) == ["2026-01-01"]


def test_holidays_for_club_returns_empty_list_on_a_failed_fetch(monkeypatch):
    def fail(code, year):
        raise RuntimeError("network down")

    monkeypatch.setattr(tui.calendar_context, "fetch_public_holidays", fail)
    config = {"calendar": {"country_code": "DE"}}
    assert tui._holidays_for_club(config) == []


def test_vacation_ranges_for_club_empty_without_configuration():
    assert tui._vacation_ranges_for_club({}) == []


def test_vacation_ranges_for_club_builds_date_ranges():
    config = {
        "calendar": {
            "vacation_ranges": [
                {"start": "2026-07-04", "end": "2026-09-15", "label": "summer break"},
                {"start": "2026-12-20", "end": "2027-01-05"},
            ]
        }
    }
    ranges = tui._vacation_ranges_for_club(config)
    assert ranges == [
        DateRange(start="2026-07-04", end="2026-09-15", label="summer break"),
        DateRange(start="2026-12-20", end="2027-01-05", label=""),
    ]


def test_readiness_status_text_no_data():
    assert tui._readiness_status_text({"hours_seen": 0, "hours_ready": 0}) == i18n.t("heatmap.status.no_data")


def test_readiness_status_text_collecting():
    text = tui._readiness_status_text({"hours_seen": 4, "hours_ready": 0})
    assert text == i18n.t("heatmap.status.collecting", seen=4)


def test_readiness_status_text_partial():
    text = tui._readiness_status_text({"hours_seen": 4, "hours_ready": 2})
    assert text == i18n.t("heatmap.status.partial", ready=2, seen=4)


def test_readiness_status_text_fully_ready():
    text = tui._readiness_status_text({"hours_seen": 3, "hours_ready": 3})
    assert text == i18n.t("heatmap.status.ready", ready=3, seen=3)


def test_heatmap_cell_style_thresholds():
    assert tui._heatmap_cell_style(1.0) == "full"
    assert tui._heatmap_cell_style(0.5) == "mid"
    assert tui._heatmap_cell_style(0.49) == "open"


def _empty_readiness():
    return {
        "by_weekday": {wd: {"hours_seen": 0, "hours_ready": 0, "total_samples": 0} for wd in tui.calendar_context.WEEKDAYS},
        "special_days": {dt: {"hours_seen": 0, "hours_ready": 0, "total_samples": 0} for dt in tui.calendar_context.SPECIAL_DAY_TYPES},
    }


def test_heatmap_preview_markup_no_preview_when_nothing_ready():
    heatmap = {"by_weekday": {"Monday": {"09": {"average": 0.2, "samples": 1}}}, "special_days": {}}
    readiness = _empty_readiness()
    readiness["by_weekday"]["Monday"] = {"hours_seen": 1, "hours_ready": 0, "total_samples": 1}
    assert tui._heatmap_preview_markup(heatmap, readiness) == i18n.t("heatmap.no_preview")


def test_heatmap_preview_markup_shows_only_ready_hours_sorted():
    heatmap = {
        "by_weekday": {
            "Monday": {
                "18": {"average": 1.0, "samples": 3},  # ready, full
                "09": {"average": 0.3, "samples": 3},  # ready, open
                "16": {"average": 0.2, "samples": 1},  # seen but not ready -- excluded
            }
        },
        "special_days": {},
    }
    readiness = _empty_readiness()
    readiness["by_weekday"]["Monday"] = {"hours_seen": 3, "hours_ready": 2, "total_samples": 7}

    markup = tui._heatmap_preview_markup(heatmap, readiness)

    label = i18n.t("heatmap.weekday.monday")
    assert markup == f"{label}: 09 [green]■[/] 18 [bold red]■[/]"


def test_heatmap_preview_markup_shows_weekdays_then_special_days():
    heatmap = {
        "by_weekday": {"Monday": {"09": {"average": 0.3, "samples": 3}}},
        "special_days": {"tournament": {"10": {"average": 0.9, "samples": 3}}},
    }
    readiness = _empty_readiness()
    readiness["by_weekday"]["Monday"] = {"hours_seen": 1, "hours_ready": 1, "total_samples": 3}
    readiness["special_days"]["tournament"] = {"hours_seen": 1, "hours_ready": 1, "total_samples": 3}

    markup = tui._heatmap_preview_markup(heatmap, readiness)

    monday_label = i18n.t("heatmap.weekday.monday")
    tournament_label = i18n.t("heatmap.day_type.tournament")
    lines = markup.split("\n")
    assert lines[0].startswith(f"{monday_label}:")
    assert lines[1].startswith(f"{tournament_label}:")


def _heatmap_screen(club_id="0000001", course="18 Loch Tee 1", config=None):
    return tui.HeatmapScreen(club_id, course, config or {})


def test_heatmap_screen_shows_a_row_per_weekday_and_per_special_day_type(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)

    async def scenario():
        app = _HostApp(_heatmap_screen())
        async with app.run_test() as pilot:
            await pilot.pause()
            weekday_table = app.screen.query_one("#weekday-table")
            special_table = app.screen.query_one("#special-table")
            assert weekday_table.row_count == 7  # one per calendar_context.WEEKDAYS
            assert special_table.row_count == 3  # one per calendar_context.SPECIAL_DAY_TYPES

    _run(scenario())


def test_heatmap_screen_reports_a_ready_hour_after_enough_scrapes(tmp_path, monkeypatch):
    # Three Mondays at the same hour -- exactly MIN_SAMPLES_FOR_PREDICTION, so that
    # hour should read as ready, and it should show up in the weekday table, not the
    # special-days one.
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    db_path = scrape_once._db_path("0000001")
    for date in ["2026-08-17", "2026-08-24", "2026-08-31"]:
        storage.save_schedule(
            Schedule(
                date=date,
                course="18 Loch Tee 1",
                slots=[Slot(time="09:00", booked=2, capacity=4)],
            ),
            path=db_path,
        )

    async def scenario():
        app = _HostApp(_heatmap_screen())
        async with app.run_test() as pilot:
            await pilot.pause()
            weekday_table = app.screen.query_one("#weekday-table")
            monday_row = weekday_table.get_row_at(1)  # Monday is index 1 in WEEKDAYS (Sunday first)
            assert str(monday_row[0]) == i18n.t("heatmap.weekday.monday")
            assert str(monday_row[1]) == "1"  # hours_seen
            assert str(monday_row[2]) == "1"  # hours_ready
            assert str(monday_row[3]) == "3"  # total_samples
            preview = app.screen.query_one("#preview", Static)
            assert "09" in str(preview.content)

    _run(scenario())


def test_heatmap_screen_escape_pops_back_to_overview(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", None, "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()
            assert isinstance(app.screen, tui.HeatmapScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, tui.OverviewScreen)

    _run(scenario())


def test_overview_screen_h_opens_heatmap_screen(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_once, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tui, "fetch_available_dates", lambda club_id: [])

    async def scenario():
        app = _HostApp(tui.OverviewScreen("0000001", "musterhausen", "18 Loch Tee 1"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()
            assert isinstance(app.screen, tui.HeatmapScreen)
            assert app.screen.club_id == "0000001"
            assert app.screen.course == "18 Loch Tee 1"

    _run(scenario())

