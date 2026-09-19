"""Generates ground-truth output from Python's own functions, for
`prototypes/macos-swift`'s `CrossCheckRunner` to compare its Swift ports against.

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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import calendar_context, club_directory, units
from src.models import DateRange


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


def main() -> None:
    reference = {**_units_cases(), **_classify_day_cases(), **_directory_cases()}
    json.dump(reference, sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
