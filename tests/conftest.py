"""Shared test fixtures.

Added 2026-09-16 during a full-project audit, which found the suite was
*time-of-day dependent*: green when run before 21:00 local, red after it.
`OverviewScreen._render_table()` drops today's own row entirely once
`tui._NOW_HHMM() > tui.TODAY_HIDDEN_AFTER_HHMM` ("21:00") — a real, wanted
feature (2026-09-11: "I would prefer that the current day disappears ...
whenever it is after 9 pm") — but ~34 tests build their fixtures around
`tui._TODAY()` and assert on a row count or a column width that silently
changes once that cutoff passes. Nothing was wrong with the app; the tests
just read the real wall clock.

Freezing `_NOW_HHMM` for every test fixes the whole class at once rather than
patching each affected test. 08:00 is deliberately early: before the cutoff,
so today's row is always present, and before any realistic tee time, so
`_initial_date()`'s own "every slot has already passed" heuristic doesn't
kick in either.

A test that genuinely cares about a *different* time of day (the "today
disappears after 9pm" tests, `_initial_date()`'s own cases) still
monkeypatches `_NOW_HHMM` itself in its own body — that runs after this
fixture and wins, so those keep testing exactly what they always did.
"""

import pytest

from src import (
    club_config,
    club_directory,
    env_file,
    geocode,
    global_preferences,
    i18n,
    paths,
    scrape_once,
    tui,
)

# Well before TODAY_HIDDEN_AFTER_HHMM ("21:00") and before any realistic tee
# time -- see this module's own docstring for why both matter.
FROZEN_NOW_HHMM = "08:00"


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: FROZEN_NOW_HHMM)


@pytest.fixture(autouse=True)
def _english_ui(monkeypatch, tmp_path):
    """Every test reads English UI text unless it switches language itself.

    i18n's "current language" is deliberate module-level global state (see
    i18n.py's own docstring), so without this a test that switches to German
    leaks that choice into every test after it in the same pytest process, and a
    fresh test resolves its language from whatever locale the machine happens to
    have — which is how a suite passes on one developer's laptop and fails on
    another's.

    Consolidated here 2026-09-16 (audit follow-up) from three byte-identical
    copies in test_tui.py / test_settings_screen.py / test_credentials_screen.py,
    each carrying a comment pointing at one of the others as its source.
    """
    monkeypatch.setattr(i18n, "CONFIG_FILE", tmp_path / "not-used-unless-a-test-wants-it")
    i18n.set_language("en")
    yield
    i18n._current_language = None


@pytest.fixture(autouse=True)
def _no_real_global_preferences_file(monkeypatch, tmp_path):
    """`global_preferences.py` defaults to the real
    `~/.config/teetime-monitor/preferences.yaml` whenever nothing overrides it,
    and both the overview (on load) and the settings screen (on save) go through
    it. Caught live before the original per-file version of this fixture existed:
    a test that opened settings, edited a field and clicked save wrote for real
    into this developer's own home directory.

    Applied to every test rather than the two files that used to declare it
    separately -- there is no test anywhere that *wants* the real file, and the
    ones exercising a real preferences file pass an explicit path.
    """
    monkeypatch.setattr(global_preferences, "PREFERENCES_FILE", tmp_path / "preferences.yaml")


@pytest.fixture(autouse=True)
def _no_real_geocoding_by_default(monkeypatch):
    """`club_config.add_favorite()` calls `geocode.find_club_location()` on every
    save, which without this makes a real network request to the live Nominatim
    service. Defaults to "nothing found" (`None`); a test exercising the
    location-found path overrides it locally.

    Same consolidation as above -- test_club_config.py and test_tui.py each had
    their own copy, both patching the same `src.geocode` module object.
    """
    monkeypatch.setattr(geocode, "find_club_location", lambda name: None)


@pytest.fixture(autouse=True)
def _no_real_credentials_by_default(monkeypatch):
    """`club_config.resolve_credentials()` reads bare `PCC_USER`/`PCC_PASS` straight
    from `os.environ` -- which, unlike every other piece of state this file isolates,
    isn't something a `tmp_path`-redirected file path can protect against, because
    `load_dotenv()` (see club_config.py's own module docstring) has already merged
    this project's own real `.env` into the *process's* environment by the time any
    test runs, for the whole pytest session, regardless of which test file.

    Found live, 2026-09-16: moving `_sync_my_reservations()` to run unconditionally
    at the top of every `scrape_due_for_club()` call (see that function's own
    docstring) meant ~10 pre-existing tests in test_scrape_once.py started actually
    reaching `scraper.login()` with this developer's real, working credentials and
    hitting the real pc caddie site with a fake club id -- a 404, not a security
    incident, but entirely by luck: nothing had isolated this before, it simply
    hadn't been exercised from this exact call site yet. Defaults every test to "no
    credentials configured" (matching a fresh install); a test that genuinely wants
    to exercise the login path already sets its own explicit
    `monkeypatch.setattr(club_config, "resolve_credentials", ...)`, which -- set
    after this fixture in the same test -- wins over this default the normal way.
    """
    monkeypatch.delenv("PCC_USER", raising=False)
    monkeypatch.delenv("PCC_PASS", raising=False)
    monkeypatch.setattr(club_config, "resolve_credentials", lambda club_id: ("", ""))


@pytest.fixture(autouse=True)
def _no_stale_holiday_cache(monkeypatch):
    """`tui._HOLIDAY_CACHE` is deliberate process-lifetime state (see its own
    docstring) -- exactly the kind of module-level global that leaks between
    tests in the same pytest process. Caught before it could actually bite:
    `test_holidays_for_club_returns_the_fetched_list` and
    `test_holidays_for_club_returns_empty_list_on_a_failed_fetch` both use
    country_code "DE" against the same frozen `_TODAY()` year (see
    `_frozen_clock` above) -- without this, whichever of the two runs first
    would cache its own result under that (country_code, year) key, and the
    other would silently read the first one's cached list back instead of
    exercising its own mocked `fetch_public_holidays()` at all.
    """
    monkeypatch.setattr(tui, "_HOLIDAY_CACHE", {})


@pytest.fixture(autouse=True)
def _no_stale_heatmap_cache(monkeypatch):
    """`tui._HEATMAP_CACHE` is deliberate process-lifetime state (see its own
    docstring), so it leaks between tests exactly like `_HOLIDAY_CACHE` above.

    Its key includes the database's own (mtime_ns, size), which makes a real stale
    read unlikely -- but every test builds its database under a fresh `tmp_path`,
    and there is no guarantee two tests' files can't land on the same path with the
    same fingerprint within one run. Isolating it costs nothing and removes the
    question entirely, rather than relying on that argument holding forever.
    """
    monkeypatch.setattr(tui, "_HEATMAP_CACHE", {})


@pytest.fixture(autouse=True)
def _no_real_state_directories(monkeypatch, tmp_path):
    """Nothing may touch the real `~/.config/teetime-monitor` or
    `~/.local/share/teetime-monitor` (see `paths.py`).

    Added 2026-09-17 when state moved out of the working directory into those fixed
    locations. Before the move, a test that forgot to redirect `DATA_DIR`/`CLUBS_DIR`
    wrote into the *repo checkout* — messy, but visible in `git status` and harmless.
    Afterwards the same mistake would write into this developer's real, live install,
    silently. That is a strictly worse failure mode, and this project has already been
    bitten repeatedly by exactly this class of leak (see the credentials, preferences
    and geocoding fixtures above), so the guard goes in with the move rather than after
    the first incident.

    Patches the consumer constants *and* `paths` itself, because the two are reached
    by different code. Each consumer module binds its own constant at import time, so
    redirecting `paths` alone would never reach `club_config.CLUBS_DIR` and friends.
    But the reverse gap is just as real and was caught the same day: `tui.main()` and
    `scrape_once.main()` call `paths.needs_migration()` / `paths.migrate_from()`
    *directly*, so guarding only the consumers let the three tests that invoke `main()`
    run a real migration into this developer's live install -- copying every club and
    all five databases into `~/.config` and `~/.local/share` for real. Caught by
    parking the real directories and re-running the suite to see them reappear.

    Tests that want their own directory still override these locally, exactly as
    before, and win the normal way.
    """
    config, data = tmp_path / "config", tmp_path / "data"
    monkeypatch.setattr(club_config, "CLUBS_DIR", config / "clubs")
    monkeypatch.setattr(scrape_once, "DATA_DIR", data)
    monkeypatch.setattr(club_directory, "DATA_DIR", data)
    monkeypatch.setattr(env_file, "ENV_FILE", config / ".env")
    monkeypatch.setattr(paths, "CONFIG_DIR", config)
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(paths, "CLUBS_DIR", config / "clubs")
    monkeypatch.setattr(paths, "ENV_FILE", config / ".env")
    monkeypatch.setattr(paths, "MANAGED_DIRS", (config, config / "clubs", data))
