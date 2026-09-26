import SwiftUI
@testable import TeetimeMonitorCore

/// One rendered case: a name (also the reference PNG's filename), a fixed render
/// size (`ImageRenderer` needs a concrete proposal, not "however big it wants to
/// be"), and the view itself. Deliberately plain data, not a protocol -- there's
/// nothing here another case would need to override.
struct VisualRegressionCase {
    let name: String
    let size: CGSize
    let view: () -> AnyView
}

/// A `WeatherPoint` at noon and at 08:00 -- enough for `Day.tempHighLow` (needs a
/// real hi/lo spread, not one point where hi == lo) while keeping every other
/// aggregate (`precipAvg`/`windPeak`/`conditionCode`) trivial to reason about
/// (both points share the same code/rain/wind, so their average/max/worst is
/// just that one value).
private func dayWeather(low: Double, high: Double, code: Int, rainPercent: Double, windKPH: Double) -> [WeatherPoint] {
    [
        WeatherPoint(time: "08:00", precipitationProbability: rainPercent, precipitationMM: nil,
                     windKPH: windKPH, temperatureC: low, code: code),
        WeatherPoint(time: "12:00", precipitationProbability: rainPercent, precipitationMM: nil,
                     windKPH: windKPH, temperatureC: high, code: code),
    ]
}

/// Three days, three different WMO codes (sun/cloud/rain -- genuinely different
/// SF Symbol glyph widths, not just different colors) -- this is the fixture that
/// would have caught the day-card-header column bug directly: a regression that
/// drops any of `DayCardHeader`'s per-field `.frame()`s shows up as the temp/rain/
/// wind/sun columns no longer lining up between these three rows.
private let multiDayFixtures: [Day] = [
    Day(date: "2026-09-26", slots: [], weather: dayWeather(low: 5, high: 26, code: 0, rainPercent: 0, windKPH: 13),
        sunrise: "07:16", sunset: "19:14", events: ["SVB Saisonabschluss (E)"], bookedTime: nil),
    Day(date: "2026-09-27", slots: [], weather: dayWeather(low: 9, high: 28, code: 3, rainPercent: 0, windKPH: 9),
        sunrise: "07:18", sunset: "19:12", events: ["Flying Eagles Spieltraining · Marco"], bookedTime: "10:20"),
    Day(date: "2026-09-28", slots: [], weather: dayWeather(low: 11, high: 24, code: 61, rainPercent: 60, windKPH: 22),
        sunrise: "07:20", sunset: "19:10", events: [], bookedTime: nil),
]

/// One day, four slots an hour apart (`Day.weather(at:)` looks up by hour, so
/// same-hour slots would all resolve to the same forecast point -- spacing these
/// an hour apart is what makes each slot legitimately get its own `WeatherPoint`)
/// with four different WMO codes -- the fixture that would have caught the
/// `SlotRow` condition-icon bug: a regression there shows up as the temp/precip/
/// wind cells (each already in their own fixed column) drifting together,
/// following whichever icon column lost its own width.
private let multiSlotDay = Day(
    date: "2026-09-26",
    slots: [
        Slot(time: "09:00", booked: 2, capacity: 4, blockReason: nil),
        Slot(time: "10:00", booked: 4, capacity: 4, blockReason: nil),
        Slot(time: "11:00", booked: 1, capacity: 4, blockReason: nil),
        Slot(time: "12:00", booked: 0, capacity: 4, blockReason: nil),
    ],
    weather: [
        WeatherPoint(time: "09:00", precipitationProbability: 5, precipitationMM: nil,
                     windKPH: 8, temperatureC: 18, code: 0),
        WeatherPoint(time: "10:00", precipitationProbability: 20, precipitationMM: nil,
                     windKPH: 14, temperatureC: 19, code: 3),
        WeatherPoint(time: "11:00", precipitationProbability: 70, precipitationMM: 1.5,
                     windKPH: 19, temperatureC: 17, code: 61),
        WeatherPoint(time: "12:00", precipitationProbability: 30, precipitationMM: nil,
                     windKPH: 35, temperatureC: 16, code: 45),
    ],
    sunrise: "07:16", sunset: "19:14", events: [], bookedTime: "10:00"
)

let allCases: [VisualRegressionCase] = [
    // Wide enough that leadingSummary's own natural content and the trailing
    // heat-strip/badge overlay (anchored to leadingSummary's *resolved* frame,
    // not its natural content width -- see that property's own docstring) can't
    // visually collide; narrower canvases were tried and did exactly that.
    VisualRegressionCase(name: "day-card-header-multi", size: CGSize(width: 760, height: 200)) {
        let model = OverviewModel()
        model.expanded = []
        return AnyView(
            VStack(alignment: .leading, spacing: 6) {
                ForEach(multiDayFixtures) { day in
                    DayCardHeader(day: day, model: model)
                }
            }
            .padding(8)
        )
    },
    VisualRegressionCase(name: "slot-row-multi", size: CGSize(width: 520, height: 140)) {
        let model = OverviewModel()
        return AnyView(
            VStack(alignment: .leading, spacing: 4) {
                ForEach(multiSlotDay.slots) { slot in
                    SlotRow(slot: slot, day: multiSlotDay, model: model)
                }
            }
            .padding(8)
        )
    },
]
