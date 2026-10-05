"""Core dataclasses shared across scraper, storage, weather, analytics, and TUI.

See ROADMAP.md Phase 1 for `Slot`/`Schedule`, Phase 2 for `WeatherPoint`/`SunTimes`/
`DateRange`.
"""

from dataclasses import dataclass, field


@dataclass
class PlayerSighting:
    """One real name plus whatever else pc caddie's own authenticated tee-sheet
    markup carries alongside it in the same cell (2026-09-27, direct follow-up to
    authenticated scraping) — a gender marker (`.tt-show-name`'s own
    `tt-show-male`/`tt-show-female`/`tt-show-unknown` class), member-vs-guest status,
    and a live handicap, all read off `.tt-show-hcp`'s sibling span
    ("Mitglied (25,1)"/"Gast"). Any field can be `None` — a guest's cell sometimes
    omits the handicap entirely, and a name with no recognized gender class at all
    just isn't recorded (`scraper._gender_from_classes()`'s own docstring). This is
    `Slot.player_details`'s own element type — kept separate from `Slot.players`
    (`list[str]`, unchanged) rather than replacing it, so every existing consumer of
    a slot's plain name list (GUI display, `storage.slots`'s own JSON column) is
    untouched; only `storage.record_seen_players()` reads this richer shape."""

    name: str
    gender: str | None = None  # "male" / "female" / "unknown" / None (not recorded)
    member_status: str | None = None  # "member" / "guest" / None
    handicap: float | None = None


def looks_like_player_name(text: str) -> bool:
    """False for a seat-cell text that is plainly a club's note or an event, not a
    person ("Doppelteestart 11:00 Uhr, Ihre Startzeit gilt nur für 9-Loch!") -- the
    scraper's colspan rule only catches notes in the merged free-seat cell, and some
    clubs also write them into a normal seat cell (2026-10-02, direct report: "the
    player directory has scraped elements that are not players but events"). Kept
    deliberately loose: a real name wrongly rejected loses data (and the scraper
    would demote its seat to a note), so only digits and sentence punctuation
    (names never have them) or an implausible length are rejected -- parentheses
    ("Müller (Gast)") and long multi-part names are fine."""
    return (
        0 < len(text) <= 60
        and len(text.split()) <= 8
        and not any(ch.isdigit() or ch in "!?:;@/" for ch in text)
    )


def family_name(full_name: str) -> str:
    """The last whitespace-separated token of a name — used as the sort key
    everywhere the player directory sorts "alphabetically by family name" (2026-09-27,
    direct request). A real heuristic, not a parsed structured name: pc caddie only
    ever gives a single free-text string, and this club's own 373 real names (checked
    directly against the live directory before picking this rule) never needs more —
    a hyphenated surname ("Brauch-Hasenmaier") is one token already, a middle initial
    ("Aindrias T. Wall") leaves the real surname as the last token regardless, and a
    leading title ("Dr.", "Prof.", "Dr. med.") never lands at the *end* of a name, so
    it never fools this. The one acknowledged gap: a nobility/prefix particle
    ("Dietrich von Bank") sorts under the following word ("Bank"), not folded into a
    combined "von Bank" the way some formal German cataloguing conventions would —
    simpler, and not worth a particle list for what pc caddie's own data actually
    contains."""
    return full_name.rsplit(maxsplit=1)[-1] if full_name.strip() else full_name


@dataclass
class Slot:
    time: str  # e.g. "09:10"
    booked: int
    capacity: int
    players: list[str] = field(default_factory=list)  # real names only (pc caddie
    # friends); anonymized "Occupied" placeholders are counted in `booked`, not stored
    # here as fake player names — see ROADMAP.md "Confirmed pc caddie markup reference"
    player_details: list[PlayerSighting] = field(default_factory=list)  # parallel to
    # `players` (2026-09-27) — same names, plus whatever gender/member-status/handicap
    # pc caddie's markup carried alongside them. Only ever non-empty when `players`
    # is (an authenticated fetch) — see PlayerSighting's own docstring.
    block_reason: str | None = None  # None = genuine member occupancy (or fully open).
    # Otherwise the label pc caddie showed: an event/lesson/guest/sponsor name, or an
    # advance-booking-window notice. The latter isn't real occupancy at all — just "not
    # bookable yet" — so callers (recommend.py, analytics.py) should treat a slot with
    # block_reason as unknown/blocked, not automatically as "crowded."


@dataclass
class WeatherPoint:
    time: str  # matches a Slot's time
    precipitation_probability: float | None = None  # 0-100
    precipitation_mm: float | None = None
    wind_speed_kph: float | None = None
    temperature_c: float | None = None
    weather_code: int | None = None  # WMO code (Open-Meteo's own scheme) -- direct
    # feedback, 2026-09-11: "I also would like icons for when it is sunny, overcast,
    # foggy, snowing etc." -- see weather_icons.py, the only thing that interprets this.


@dataclass
class RoundConditions:
    """Worst-case weather across an entire round's duration, not a single point in
    time — see weather.py's conditions_during_round(). Added 2026-09-05: a slot's
    weather can't be judged from its tee-off hour alone once the round runs 2-4+ hours.

    Precipitation and wind are one-sided (more is always worse), so those collapse to
    a single max. Temperature is two-sided — too cold and too hot are both bad — so it
    stays as a min/max pair rather than forcing it into one "worst" number; a caller
    checks min against `avoid_temp_below_c` and max against `avoid_temp_above_c`
    separately.
    """

    max_precipitation_probability: float | None = None  # 0-100
    max_precipitation_mm: float | None = None
    max_wind_speed_kph: float | None = None
    min_temperature_c: float | None = None
    max_temperature_c: float | None = None


@dataclass
class SunTimes:
    sunrise: str  # "HH:MM", local time
    sunset: str  # "HH:MM", local time


@dataclass
class Schedule:
    date: str  # YYYY-MM-DD
    course: str
    slots: list[Slot] = field(default_factory=list)
    weather: list[WeatherPoint] = field(default_factory=list)
    sun_times: SunTimes | None = None
    events: list[str] = field(default_factory=list)  # tournament/event notes, if any
    available_courses: list[str] = field(default_factory=list)  # this week's options


@dataclass
class ConfirmedBooking:
    """Your own tee time.

    Populated automatically each scrape from pc caddie's own "My Reservations" page
    (source="my_reservations") — revised 2026-09-05 once that page turned out to exist.
    The TUI's `c` keybinding (source="manual") remains as a fallback for the same-day
    booking timing gap: pc caddie hides past tee sheets, so if a same-day booking is
    made and played between two scheduled scrapes, there's no way to reconstruct it
    later without the manual record. See ROADMAP.md Phase 1.
    """

    date: str  # YYYY-MM-DD
    course: str
    time: str | None  # None means "confirmed not playing that day"
    holes: int | None = None  # 9 or 18, if noted at confirmation time
    source: str = "manual"  # "my_reservations" or "manual"
    confirmed_at: str = ""  # ISO 8601 timestamp


@dataclass
class ReservationsSync:
    """What one "My Reservations" page fetch actually carries (2026-09-27, direct
    follow-up: "would it make sense to have the option to choose to play with
    similar HCP or with better HCP for better pace?") — `scraper.scrape_my_
    reservations()`'s own real return shape, not just the bookings list it used to
    be. `my_handicap` is your own live handicap index, read off the same page's
    account-menu markup ("Mein Handicap Index: 43,8") -- entered by the club
    itself, not something this app collects, so it's picked up for free on every
    existing sync pass rather than added as a second thing to maintain. `None`
    when the page's markup didn't have it this time (a transient fetch variant,
    or a locale this hasn't been confirmed against) — a caller should keep
    whatever value it already had rather than clobbering it with nothing, the
    same "don't overwrite good data with missing data" stance
    `storage.record_seen_players()`'s own COALESCE already takes for gender/
    member-status/handicap."""

    bookings: list[ConfirmedBooking]
    my_handicap: float | None = None


@dataclass
class KnownPlayer:
    """One real name ever seen in a `Slot.players` list (2026-09-27) — only possible
    at all from an authenticated scrape, see `scraper.scrape_schedule()`'s own
    `client` parameter. Accumulated automatically (`scrape_once.run()` calls
    `storage.record_seen_players()` after every scrape), browsable as a directory in
    both front ends, with `is_friend` the one thing a person actually edits —
    everything else here is derived from what scraping has already observed.

    `first_seen`/`last_seen` are ISO 8601 timestamps of when this name was recorded,
    not necessarily when it last had a real booking — a name already known stays
    known even through a stretch with no bookings, same "history isn't rewritten"
    stance the rest of storage.py takes. Neither is shown in the directory UI
    (2026-09-27, direct feedback: "i dont need the date when players have been
    added") — kept in storage regardless, since `record_seen_players()`'s own upsert
    needs `first_seen` to not get clobbered on a later sighting.

    `gender`/`member_status`/`handicap` (2026-09-27, direct follow-up: "are there any
    further scrapable information... that would be worth to display?" — checked
    directly against the live authenticated tee sheet HTML, see
    `PlayerSighting`'s own docstring) are each the *most recently seen* non-null
    value for this name — `storage.record_seen_players()`'s own upsert keeps a prior
    value rather than clearing it if one particular sighting happened to omit it
    (a guest's cell sometimes has no handicap span at all).
    """

    name: str
    first_seen: str
    last_seen: str
    is_friend: bool = False
    gender: str | None = None
    member_status: str | None = None
    handicap: float | None = None


@dataclass
class DateRange:
    """A labeled span of dates — used for a club's manually-entered vacation periods
    (ROADMAP.md Phase 2), since there's no universal free API for those."""

    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    label: str = ""


@dataclass
class TimeWindow:
    after: str | None = None  # "HH:MM"
    before: str | None = None  # "HH:MM"


@dataclass
class SlotMatch:
    """One scored candidate slot, returned by recommend.py or search.py.

    `reasons` is a short list of plain-language tags for why it scored the way it did
    (e.g. "dry", "calm", "3 open spots", "20 min clear of other flights") — meant to be
    shown next to the slot in the TUI, not just a bare number.
    """

    date: str  # YYYY-MM-DD
    course: str
    slot: Slot
    score: float
    reasons: list[str] = field(default_factory=list)
    # `quality.py`'s own explanation (2026-10-05): reason KEYS ("dry", "room_around", ...),
    # localised only at the edges, filled by `ranked_matches(rank_by_quality=True)`.
    # Separate from `reasons`, which stays what it always was -- the AI's free-text
    # sentences -- so neither can be mistaken for the other.
    quality_reasons: list[str] = field(default_factory=list)
