import Foundation
@testable import TeetimeMonitorCore

func runPicksClientTests() {
    Harness.group("PicksClient") {
        testParsesPickWindowAndUnplayable()
        testParsesTheWindowHint()
        testVisibleSlotsRunSunriseRowToSunsetRow()
    }
}

/// `picks_cli.py`'s own output shape (2026-09-27, bundle C of the TUI/GUI
/// consistency audit): a day with no pick is an object now, carrying its window
/// and why -- the GUI dims and explains from these, never re-deciding them.
private func testParsesPickWindowAndUnplayable() {
    let result = PicksClient.parse([
        "2026-09-27": ["time": "11:00", "score": 0.0, "reasons": [String](),
                       "window": ["after": "11:00", "before": "18:00"]],
        "2026-09-28": ["time": NSNull(), "window": ["after": "16:00", "before": NSNull()],
                       "unplayable": ["daylight"]],
        "2026-09-29": NSNull(),
    ])
    Harness.check("a real pick still parses", result.picks["2026-09-27"]?.time == "11:00")
    Harness.check("a no-pick day has no DayPick", result.picks["2026-09-28"] == nil)
    Harness.check("its reason comes through", result.verdicts["2026-09-28"]?.unplayable == ["daylight"])
    Harness.check("its window comes through", result.verdicts["2026-09-28"]?.windowAfter == "16:00")
    Harness.check("a null day has no verdict", result.verdicts["2026-09-29"] == nil)
    let verdict = result.verdicts["2026-09-27"]!
    Harness.check("before the window is outside", verdict.isOutsideWindow("10:50"))
    Harness.check("inside the window is not", !verdict.isOutsideWindow("14:00"))
    Harness.check("after the window is outside", verdict.isOutsideWindow("18:10"))
}

private func testParsesTheWindowHint() {
    let result = PicksClient.parse([
        "_hint": ["window_after": "16:00", "latest_start": "14:40", "sunset": "19:10", "round_minutes": 240, "days": 3],
    ])
    Harness.check("hint parses", result.hint?.latestStart == "14:40" && result.hint?.roundMinutes == 240)
    Harness.check("_hint is never mistaken for a date", result.verdicts["_hint"] == nil)
    Harness.check("whole hours read without a decimal", hoursText(240) == "4")
}

/// Same rule as `tui._compute_slot_rows()`: nothing before the sunrise row or
/// after the sunset row -- replacing a fixed 07:00-19:30 clip only this app had.
private func testVisibleSlotsRunSunriseRowToSunsetRow() {
    let slots = ["06:00", "06:50", "07:10", "12:00", "19:00", "19:40"].map {
        Slot(time: $0, booked: 0, capacity: 4, blockReason: nil, players: [])
    }
    let day = Day(date: "2026-09-28", slots: slots, weather: [], sunrise: "07:08", sunset: "19:05",
                  events: [], bookedTime: nil)
    Harness.check("sunrise row through sunset row",
                  day.visibleSlots.map(\.time) == ["07:10", "12:00", "19:00"])
    let noSun = Day(date: "2026-09-28", slots: slots, weather: [], sunrise: nil, sunset: nil,
                    events: [], bookedTime: nil)
    Harness.check("every slot without sun times", noSun.visibleSlots.count == 6)
}
