"""Generates ground-truth output from Python's own functions, for
`macos/`'s `CrossCheckRunner` to compare its Swift ports against.

Exists because those ports were, until now, verified exactly once by hand at the
point each was written (a probe script, a one-off diff against real data) and never
again -- real, but not a standing guard: if `units.py`'s conversion factor or
`calendar_context.py`'s classification order ever changes later, nothing would
catch `Units.swift`/`CalendarContext.swift` silently falling out of sync with it.
This script is the Python half of turning that into an automated check: it calls
the real functions directly (never reimplements their logic) for a fixed set of
inputs and writes {function: [{"args": ..., "expected": ...}]} as JSON.
`CrossCheckRunner` reads that same file, computes the Swift equivalents for the
same inputs, and fails if anything disagrees -- run together as one CI job (see
`.github/workflows/tests.yml`'s own `swift-tests` job).

Deliberately narrow: only the functions that are both (a) pure -- no I/O, no
network, no randomness, so "same input, same output" is actually a meaningful
claim -- and (b) genuinely duplicated in Swift rather than reached by shelling out
to a console script (contrast `search_cli.py`'s own `ranked_matches()` call, which
this doesn't need to cross-check since Swift never reimplements it, only invokes
it). `crowd_heatmap()` itself is deliberately excluded for the same "pure function"
reason in spirit but a practical one in fact: it reads a SQLite database rather
than taking plain arguments, so a meaningful cross-check would need a shared
fixture database in a format both languages agree on -- worth doing later, not
folded into this first pass. It's still covered, just less automatically: the
Swift-side test suite already pins the specific cell values one such comparison
produced (see `AnalyticsTests.swift`'s own docstring).
"""

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import calendar_context, club_directory, i18n, scraper, storage, tui, units, weather_icons
from src.models import DateRange, PlayerSighting, Slot, WeatherPoint, family_name
from src.settings_screen import ROUND_DURATION_EIGHTEEN_CHOICES, ROUND_DURATION_NINE_CHOICES


def _units_cases() -> dict:
    temps = [-10.0, 0.0, 20.0, 37.5, 100.0]
    winds = [0.0, 9.5, 18.0, 42.3, 100.0]
    precip = [0.0, 0.5, 1.5, 10.0, 25.4]
    modes = [units.METRIC, units.IMPERIAL]
    return {
        "units_temperature": [
            {"args": {"celsius": c, "units": m}, "expected": units.display_temperature(c, m)}
            for c in temps
            for m in modes
        ],
        "units_wind_speed": [
            {"args": {"kph": w, "units": m}, "expected": units.display_wind_speed(w, m)}
            for w in winds
            for m in modes
        ],
        "units_precipitation_mm": [
            {"args": {"mm": p, "units": m}, "expected": units.display_precipitation_mm(p, m)}
            for p in precip
            for m in modes
        ],
        "units_temperature_symbol": [
            {"args": {"units": m}, "expected": units.SYMBOLS[m]["temperature"]} for m in modes
        ],
        "units_wind_symbol": [{"args": {"units": m}, "expected": units.SYMBOLS[m]["wind"]} for m in modes],
        # Added 2026-09-19 alongside the GUI's own precipitation-mm display (item
        # 3, "precipitation amount in mm seems to still be missing") -- the one
        # units.py function that ported to Swift (Units.precipitationAmountLabel)
        # without ever gaining a cross-check.
        "units_precipitation_label": [
            {"args": {"units": m}, "expected": units.precipitation_amount_label(m)} for m in modes
        ],
    }


def _classify_day_cases() -> dict:
    holidays = ["2026-12-25", "2026-01-01"]
    vacations = [DateRange(start="2026-07-01", end="2026-07-14", label="summer")]
    vacation_payload = [{"start": vr.start, "end": vr.end} for vr in vacations]
    cases = [
        # (date, has_tournament) -- holidays/vacations held fixed across all cases,
        # same reasoning _crowd_buckets() itself always classifies against one
        # club's own fixed holiday/vacation set per call.
        ("2026-09-18", False),  # plain Friday -> workday
        ("2026-09-19", False),  # plain Saturday -> weekend
        ("2026-09-20", False),  # plain Sunday -> weekend
        ("2026-12-25", False),  # a real holiday -> public_holiday
        ("2026-12-25", True),  # tournament wins even on a holiday
        ("2026-07-05", False),  # inside the vacation range -> vacation
        ("2026-07-01", False),  # vacation range start boundary
        ("2026-07-14", False),  # vacation range end boundary
        ("2026-07-15", False),  # just past the vacation range -> workday (Wed)
        ("2026-06-15", True),  # tournament on an ordinary day
    ]
    return {
        "classify_day": [
            {
                "args": {"date": date, "holidays": holidays, "vacation_ranges": vacation_payload,
                         "has_tournament": has_tournament},
                "expected": calendar_context.classify_day(date, holidays, vacations, has_tournament),
            }
            for date, has_tournament in cases
        ]
    }


def _directory_cases() -> dict:
    directory = [
        ("0352001", "Golf Club Grand Ducal de Luxembourg"),
        ("0491605", "1. Golfclub Leipzig e.V."),
        ("0000001", "Golfclub Domäne Musterhausen e.V."),
        ("0497712", "Golfclub Hetzenhof e.V."),
    ]
    directory_payload = [list(entry) for entry in directory]
    queries = ["leipzig", "LEIPZIG", "golf", "   ", "hetzenhof", "nonexistent"]
    id_queries = [
        "491605", "0491605", "12345", "12345678",
        "https://pccaddie.net/clubs/0491605/booking",
        "https://pccaddie.net/clubs/491605/booking",
        "Golfclub Leipzig",
    ]
    return {
        "directory_search": [
            {
                "args": {"query": q, "directory": directory_payload},
                "expected": [list(entry) for entry in club_directory.search(directory, q)],
            }
            for q in queries
        ],
        "looks_like_club_id": [
            {"args": {"query": q}, "expected": club_directory.looks_like_club_id(q)} for q in id_queries
        ],
    }


def _family_name_cases() -> dict:
    # Real names from this project's own player directory (2026-09-27) -- covers the
    # cases that actually justified the "last whitespace token" rule: a hyphenated
    # surname, a middle initial, a leading title, and the one acknowledged gap (a
    # nobility particle, "von Bank" sorting under "Bank" alone).
    names = [
        "Max Mustermann",
        "Bettina Brauch-Hasenmaier",
        "Aindrias T. Wall",
        "Dr. med. Philipp Dalheimer",
        "Dietrich von Bank",
        "Annette MERKLINGER",
        "",
    ]
    return {
        "family_name": [{"args": {"name": n}, "expected": family_name(n)} for n in names],
    }


def _whole_number_cases() -> dict:
    # Every TUI weather cell formats a measured value with `f"{x:.0f}"` inline
    # rather than through one named function -- this pins that exact expression
    # against the GUI's `wholeNumber()` (2026-09-27: the GUI used to truncate
    # with `Int()`, so the same database showed a low of 12° in the TUI and 11°
    # in the GUI). Halves on both sides of even/odd, a value just under a half,
    # and a small negative (a winter low) are the cases where truncation,
    # half-up and half-to-even rounding genuinely disagree.
    values = [11.6, 11.4, 11.5, 12.5, 0.5, 1.5, 10.7, 16.66, 99.9, -0.4, -2.5, -3.6, 0.0]
    return {"whole_number": [{"args": {"value": v}, "expected": f"{v:.0f}"} for v in values]}


def _hours_text_cases() -> dict:
    # The hours part of `tui._window_hint_text()` (`f"{hours:g}"`, decimal comma in
    # German) for every round duration either Settings screen offers -- the GUI's
    # `%.1f` once showed 75 min as "1.2" against the TUI's "1.25".
    minutes = sorted({int(value) for _, value in [*ROUND_DURATION_NINE_CHOICES, *ROUND_DURATION_EIGHTEEN_CHOICES]})
    return {
        "hours_text": [
            {"args": {"minutes": m, "language": lang},
             "expected": f"{m / 60:g}".replace(".", "," if lang == "de" else ".")}
            for m in minutes
            for lang in i18n.SUPPORTED_LANGUAGES
        ]
    }


def _holes_cases() -> dict:
    labels = ["18 Loch Tee 1", "6 Loch Platz", "9-Loch Schleife", "Kurzplatz", "Tee 10 (9 Loch)", "Kurzplatz: 6 Loch",
              "18-Loch Schleife (nur erste 9-Loch)", "Tee 1: 9 oder 18 Loch", ""]
    return {"holes_from_label": [{"args": {"course": c}, "expected": scraper._holes_from_course_label(c)} for c in labels]}


def _weather_payload(points: list[WeatherPoint]) -> list[dict]:
    return [
        {"time": w.time, "p": w.precipitation_probability, "mm": w.precipitation_mm,
         "wind": w.wind_speed_kph, "temp": w.temperature_c, "code": w.weather_code}
        for w in points
    ]


def _day_cell_cases() -> dict:
    # The collapsed day row's summary cells, straight from the TUI's own cell
    # functions: nulls inside the daytime window (counted as 0 in the rain average,
    # not dropped), points outside 08:00-20:00, the 🌧 >= 50% / 💨 >= 30 km/h flags
    # and the all-day >= 70% phrase.
    hours = [f"{h:02d}:00" for h in range(6, 22)]
    fixtures = {
        "half_null": [WeatherPoint(t, 60 if i % 2 else None, None, 12, 14 + i / 3, 3) for i, t in enumerate(hours)],
        "wet": [WeatherPoint(t, 85, 0.35, 31, 9.6, 63) for t in hours],
        "mixed": [WeatherPoint("07:00", 100, 9, 50, 2, 95), WeatherPoint("09:00", 40, 1.2, 29.6, 11.5, 61),
                  WeatherPoint("13:00", 70, 3.0, 12, 18.5, 2), WeatherPoint("19:00", None, None, None, None, None)],
        "dry_windy": [WeatherPoint("10:00", 0, 0, 30, 25.5, 0), WeatherPoint("14:00", 10, None, 18, -0.5, 45)],
        "night_only": [WeatherPoint("05:00", 90, 4, 40, 3, 95)],
        "empty": [],
    }
    cases: dict = {"day_temperature_cell": [], "day_precipitation_cell": [], "day_wind_cell": [],
                   "day_condition_code": [], "slot_precipitation_cell": []}
    for name, points in fixtures.items():
        payload = _weather_payload(points)
        daytime_codes = [w.weather_code for w in points if "08:00" <= w.time < "20:00"]
        for m in (units.METRIC, units.IMPERIAL):
            cases["day_temperature_cell"].append(
                {"args": {"fixture": name, "weather": payload, "units": m}, "expected": tui._temperature_cell(points, m)})
            cases["day_wind_cell"].append(
                {"args": {"fixture": name, "weather": payload, "units": m}, "expected": tui._wind_cell(points, m)})
            for lang in i18n.SUPPORTED_LANGUAGES:
                i18n.set_language(lang)
                cases["day_precipitation_cell"].append(
                    {"args": {"fixture": name, "weather": payload, "units": m, "language": lang},
                     "expected": tui._precipitation_cell(points, m)})
            for w in points:
                cases["slot_precipitation_cell"].append(
                    {"args": {"weather": payload, "time": w.time, "units": m},
                     "expected": tui._slot_precipitation_cell(points, w.time, m)})
        # Swift draws SF Symbols, not the TUI's emoji, so the runner maps the code
        # Swift picks through this same emoji table: same icon <=> same severity pick.
        cases["day_condition_code"].append(
            {"args": {"fixture": name, "weather": payload,
                      "icons": {str(code): weather_icons.icon_for_code(code) for code in weather_icons._SEVERITY_ORDER}},
             "expected": weather_icons.worst_icon(daytime_codes)})
    i18n.set_language("en")
    cases["severity_order"] = [{"args": {}, "expected": weather_icons._SEVERITY_ORDER}]
    # Codes sharing one TUI icon must share one GUI symbol too, and every code the
    # TUI knows must be known to the GUI. (The GUI may be coarser -- SF Symbols has
    # no separate "partly cloudy" or "snow showers" glyph.)
    groups: dict[str, list[int]] = {}
    for code in weather_icons._SEVERITY_ORDER:
        groups.setdefault(weather_icons.icon_for_code(code), []).append(code)
    cases["condition_icon_groups"] = [{"args": {"codes": codes}, "expected": True} for codes in groups.values()]
    return cases


def _slot_row_cases() -> dict:
    times = ["06:50", "07:00", "07:10", "07:20", "18:40", "18:50", "19:00"]
    targets = ["07:05", "07:15", "06:00", "18:55", "23:00", "07:00"]
    anonymous = [(0, 0), (1, 0), (3, 1), (4, 4), (2, 3)]
    cases = {
        "closest_slot_time": [
            {"args": {"times": times, "target": target}, "expected": tui._closest_slot_time(times, target)}
            for target in targets
        ],
        "anonymous_players_text": [],
    }
    for lang in i18n.SUPPORTED_LANGUAGES:
        i18n.set_language(lang)
        for booked, named in anonymous:
            slot = Slot(time="09:00", booked=booked, capacity=4, players=[f"P{i}" for i in range(named)])
            cases["anonymous_players_text"].append(
                {"args": {"booked": booked, "named": named, "language": lang}, "expected": tui._anonymous_players_text(slot)})
    i18n.set_language("en")
    return cases


def _booking_change_cases() -> dict:
    changes = [
        ("party_grew", {"count": 1, "time": "14:00"}),
        ("party_grew", {"count": 2, "time": "14:00"}),
        ("buffer_shrunk", {"time": "09:10", "neighbor_time": "09:00"}),
        ("neighbor_crowded", {"time": "09:10", "neighbor_time": "09:20"}),
        ("weather_worsened", {"time": "11:00", "reason_keys": ["rain_chance", "wind"]}),
        ("reservations_sync_failed", {"reason": "login"}),
        ("reservations_sync_failed", {"reason": "parsing"}),
        ("reservations_sync_failed", {}),
        ("something_new", {"time": "10:00"}),
    ]
    cases = []
    for lang in i18n.SUPPORTED_LANGUAGES:
        i18n.set_language(lang)
        for kind, params in changes:
            cases.append({"args": {"kind": kind, "params": json.dumps(params), "language": lang},
                          "expected": i18n.render_booking_change(kind, params)})
    i18n.set_language("en")
    return {"render_booking_change": cases}


def _club_yaml_cases() -> dict:
    # Club files as PyYAML really writes them -- with and without allow_unicode
    # (club files saved before it was turned on hold `"Golfclub W\xFCrzburg"`) --
    # against what `yaml.safe_load` reads back. Swift line-scans these keys.
    clubs = [
        {"club_id": "0497758", "name": "Golfclub Würzburg e.V.", "default_course": "Übungsplatz"},
        {"club_id": "0000001", "name": "Golfclub Domäne Niederreutin", "default_course": "9 Loch Tee 1"},
        {"club_id": "0352001", "name": "Club 'Le Grand' — Ducal", "default_course": "18 Loch: Tee 10"},
        {"club_id": "0491605", "name": "Golf Club Ærø", "default_course": "it's 6"},
    ]
    cases = []
    for club in clubs:
        for allow_unicode in (False, True):
            text = yaml.safe_dump(club, sort_keys=False, allow_unicode=allow_unicode)
            loaded = yaml.safe_load(text)
            cases.append({"args": {"text": text},
                          "expected": [loaded["club_id"], loaded["name"], loaded["default_course"]]})
    return {"club_yaml_scalars": cases}


def _store_players_cases() -> dict:
    # A database built by `storage.py` itself (its real schema, its own writers),
    # shipped as SQL for CrossCheckRunner to load and read through `Store`'s raw
    # SQL -- so a renamed column, or a typo in Swift's SQL, fails here instead of
    # silently emptying the player directory (`Store.query()` reads a failed
    # prepare as "no rows").
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "club.db"
        storage.init_db(path)
        storage.record_seen_players(
            [
                PlayerSighting("Max Mustermann", "male", "member", 12.5),
                PlayerSighting("Bettina Brauch-Hasenmaier", "female", "guest", None),
                PlayerSighting("Dr. med. Philipp Dalheimer", "unknown", None, 36.0),
                PlayerSighting("Annette MERKLINGER", None, "member", 4.2),
                # ß casefolds to "ss": Heßlinger sorts before Heusel in Python.
                PlayerSighting("Uwe Heßlinger", "male", None, None),
                PlayerSighting("Eva Heusel", "female", None, None),
                PlayerSighting("Jan Hesse", None, None, 20.1),
            ],
            "2026-09-27T10:00:00+00:00",
            path,
        )
        storage.set_player_friend("Max Mustermann", True, path)
        storage.set_player_friend("Annette MERKLINGER", True, path)
        storage.save_my_handicap(43.8, path)
        with sqlite3.connect(path) as conn:
            sql = "\n".join(line for line in conn.iterdump() if "sqlite_sequence" not in line)
        expected = {
            "friend_names": sorted(storage.load_friend_names(path)),
            "player_genders": storage.load_player_genders(path),
            "known_players": [
                [p.name, p.last_seen, p.is_friend, p.gender, p.member_status, p.handicap]
                for p in storage.load_known_players(path)
            ],
            "my_handicap": storage.load_my_handicap(path),
        }
    return {"store_players": [{"args": {"sql": sql}, "expected": expected}]}


def main() -> None:
    reference = {
        **_units_cases(),
        **_classify_day_cases(),
        **_directory_cases(),
        **_family_name_cases(),
        **_whole_number_cases(),
        **_hours_text_cases(),
        **_holes_cases(),
        **_day_cell_cases(),
        **_slot_row_cases(),
        **_booking_change_cases(),
        **_club_yaml_cases(),
        **_store_players_cases(),
    }
    json.dump(reference, sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
