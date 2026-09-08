"""Best-effort club-location lookup via OpenStreetMap's free Nominatim geocoder
(ROADMAP.md Phase 0/2), added 2026-09-08 — direct follow-up after being asked
whether the scraper could discover a club's location automatically.

Checked first, live, before writing any of this: pc caddie itself exposes nothing
usable. The tee-sheet page's own footer links to an "Impressum" (German legal
imprint), but that reveals the *platform vendor's* address (PC CADDIE://online
GmbH, Bad Oldesloe) — not each individual club's; the club directory
(`scraper.fetch_club_directory()`) is plain `[club_id] Name` pairs, no city or
address anywhere. A general-purpose geocoder that only knows place names (e.g.
Open-Meteo's own geocoding API, already used for weather.py's `location` input)
returns nothing for a golf club's business name — confirmed live, "Golfclub
Sonnenberg" has zero hits there, since that kind of service is built for towns and
cities, not individual venues.

Nominatim (https://nominatim.openstreetmap.org/), OpenStreetMap's own free
geocoder, indexes individual mapped features by name too, including many golf
courses tagged `leisure=golf_course`. **Its actual pc caddie club name has to be
normalized first, though** — confirmed live against three real clubs before this
was added: querying the *exact* name pc caddie gives each club
("Golf Club Sonnenberg e.V.", "Golfclub Domäne Musterhausen e.V.", "Nippenburg
Golfclub GmbH") returned zero results for all three. Two things fixed it: dropping
the German legal-entity suffix ("e.V.", "GmbH", ...), since OSM's own tagging never
carries one, and merging a two-word/hyphenated "Golf Club"/"Golf-Club" into the
one-word "Golfclub" OSM actually uses — word *order* and extra descriptive words
(e.g. "Domäne") turned out not to matter once those two were fixed, confirmed by
testing several phrasings live. `_normalize_query()` below does just those two
substitutions, nothing more exotic.

**Best-effort, not a precise pin, even after normalizing.** OpenStreetMap doesn't
have every club mapped, and a free-text name search over it can return the wrong
nearby feature instead of the course itself — of the three real clubs tested, one
matched the actual `leisure=golf_course` feature directly, and two matched a
different nearby feature that happened to reference the club's name in its own (a
campsite, a parking area). Acceptable for what this is actually used for —
weather.py's own forecast lookup, where being a few hundred meters to a kilometer
off the real clubhouse changes nothing (Open-Meteo's own forecast grid isn't that
granular either) — but this is not a substitute for looking up and hand-entering
the real address if precision ever mattered for something else. Returns `None` on
no match or any request failure, the same "don't fabricate, don't crash" contract
`scrape_once._attach_weather()` already expects of a `location` lookup.

Used by `club_picker.py` when a new club is saved — the one moment a club's real
name is known and nothing's been geocoded for it yet. Deliberately not re-run for
already-saved clubs (no "back-fill every existing club automatically" pass) —
consistent with this project's current stance while it has no real users yet (see
the [[teetime-monitor-no-migration-needed]] memory note): a one-time,
one-directional lookup at save time is all this needs for now.

Nominatim's own usage policy
(https://operations.osmfoundation.org/policies/nominatim/) requires a real,
identifying User-Agent — never a browser-spoofing one — and caps casual usage at
roughly one request per second. Both are trivially satisfied here: one lookup,
once, whenever a person manually adds a club through the UI.
"""

import re

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Required by Nominatim's own usage policy (see module docstring) — identifies this
# tool honestly rather than spoofing a browser's User-Agent.
USER_AGENT = "teetime-monitor (personal tee-time tool; https://github.com/ltdan-88/teetime-monitor)"

# German legal-entity suffixes pc caddie's own club names carry that OpenStreetMap's
# tagging never does — see module docstring for why these specifically broke the
# match for all three real clubs tested. Anchored to the end of the string, since
# it's always a trailing suffix, never a real part of the club's own name.
_LEGAL_SUFFIX_RE = re.compile(
    r"\s*\b(?:e\.?\s?V\.?|e\.?\s?K\.?|gGmbH|GmbH(?:\s*&\s*Co\.?\s*KG)?|AG)\.?\s*$",
    re.IGNORECASE,
)
# pc caddie sometimes writes this as two words or hyphenated; OSM's own tagging
# convention is the single word "Golfclub" — see module docstring.
_GOLF_CLUB_RE = re.compile(r"\bgolf[\s-]club\b", re.IGNORECASE)


def _normalize_query(club_name: str) -> str:
    normalized = _LEGAL_SUFFIX_RE.sub("", club_name)
    normalized = _GOLF_CLUB_RE.sub("Golfclub", normalized)
    return normalized.strip()


def find_club_location(club_name: str) -> tuple[float, float] | None:
    """Best-effort (lat, lon) for a club's name, via a single Nominatim search —
    `None` if the normalized name is empty, nothing matched, or the request itself
    failed (no network, the service is down, an unexpected response shape). Never
    raises — see module docstring for why this has to be as forgiving as
    weather.py's own lookups."""
    query = _normalize_query(club_name)
    if not query:
        return None
    try:
        response = httpx.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        response.raise_for_status()
        results = response.json()
    except Exception:  # noqa: BLE001 — best-effort, see module docstring
        return None
    if not results:
        return None
    try:
        return float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, ValueError, TypeError):
        return None
