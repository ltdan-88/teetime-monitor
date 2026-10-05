import SwiftUI
@testable import TeetimeMonitorCore

/// One rendered case: a name (also the reference PNG's filename), a fixed render
/// size (`ImageRenderer` needs a concrete proposal, not "however big it wants to
/// be"), and the view itself. Deliberately plain data, not a protocol -- there's
/// nothing here another case would need to override.
struct VisualRegressionCase {
    let name: String
    let size: CGSize
    /// The interface language the case renders in (set around the render, then back).
    var language = "en"
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
        Slot(time: "09:00", booked: 2, capacity: 4, blockReason: nil, players: []),
        Slot(time: "10:00", booked: 4, capacity: 4, blockReason: nil, players: []),
        Slot(time: "11:00", booked: 1, capacity: 4, blockReason: nil, players: []),
        Slot(time: "12:00", booked: 0, capacity: 4, blockReason: nil, players: []),
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

/// Four players spanning every real gap this row's fixed columns need to survive:
/// a long name against a short one, present vs. missing gender/status/handicap, and
/// a marked vs. unmarked friend (different button label -- see `Metrics.playerName`/
/// `.playerGender`/`.playerMemberStatus`/`.playerHandicap`'s own docstring for why
/// only the trailing button is allowed to vary in width at all). This is the fixture
/// that would have caught a `PlayerDirectorySheet` column-width regression directly:
/// dropping any of `PlayerRow`'s own `.frame()`s shows up as the gender/status/HCP
/// cells no longer lining up between these four rows.
private let multiPlayers: [KnownPlayer] = [
    KnownPlayer(name: "Bettina Brauch-Hasenmaier", lastSeen: "2026-09-27T10:00:00+00:00",
                isFriend: false, gender: "female", memberStatus: "member", handicap: 36.6),
    KnownPlayer(name: "Al Yu", lastSeen: "2026-09-26T10:00:00+00:00",
                isFriend: true, gender: "male", memberStatus: "guest", handicap: 12.3),
    KnownPlayer(name: "Dr. med. Philipp Dalheimer", lastSeen: "2026-09-25T10:00:00+00:00",
                isFriend: false, gender: nil, memberStatus: nil, handicap: nil),
    KnownPlayer(name: "Erika Mustermann", lastSeen: "2026-09-24T10:00:00+00:00",
                isFriend: false, gender: "unknown", memberStatus: "member", handicap: 5.0),
]

/// Seven days, one per thing the pick badge slot can hold: a booking, the ★ pick, a
/// shorter round on another course (2026-10-05), the too-dark moon, and three locks
/// (2026-10-05: "today 20:00", a weekday with a time, a date-level one) -- the
/// fixture that catches a wider badge pushing the HeatStrip (or anything left of it)
/// out of its column.
private let badgeDayFixtures: [Day] = [
    "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11",
].map { date in
    Day(date: date, slots: [], weather: dayWeather(low: 6, high: 15, code: 3, rainPercent: 10, windKPH: 12),
        sunrise: "07:30", sunset: "18:50", events: [], bookedTime: date == "2026-10-05" ? "10:20" : nil)
}

private func badgeModel() -> OverviewModel {
    let model = OverviewModel()
    model.picks = ["2026-10-06": DayPick(time: "16:00", score: 0, reasons: [])]
    model.alternatives = ["2026-10-07": ShorterRound(course: "9 Loch Tee 1", time: "16:10", holes: 9)]
    model.verdicts = ["2026-10-08": DayVerdict(windowAfter: "16:00", windowBefore: nil, unplayable: ["daylight"])]
    model.locked = [
        "2026-10-09": LockedDay(opensAt: "2026-10-05T20:00:00+02:00", hourKnown: true),
        "2026-10-10": LockedDay(opensAt: "2026-10-06T21:00:00+02:00", hourKnown: true),
        "2026-10-11": LockedDay(opensAt: "2026-10-07T00:00:00+02:00", hourKnown: false),
    ]
    model.now = { footerNow }
    return model
}

/// Fixed "now" for the footer case -- a Monday noon, UTC (see main.swift's pinned zone).
let footerNow = ISO8601DateFormatter().date(from: "2026-10-05T12:00:00Z")!

private func footerISO(minutesAgo: Double) -> String {
    ISO8601DateFormatter().string(from: footerNow.addingTimeInterval(-minutesAgo * 60))
}

/// Healthy, login rejected (the real 2026-10-03 incident's shape), failing.
let footerHealthModels: [OverviewModel] = {
    func model(_ health: ScrapeHealth) -> OverviewModel {
        let model = OverviewModel()
        model.lastScrape = footerNow.addingTimeInterval(-10 * 60)
        model.scrapeHealth = health
        return model
    }
    let recent = footerISO(minutesAgo: 5)
    return [
        model(ScrapeHealth(lastRunAt: recent, lastSuccessAt: recent)),
        model(ScrapeHealth(lastRunAt: recent, lastSuccessAt: recent, lastErrorKind: "login_rejected",
                           loginRejectedSince: footerISO(minutesAgo: 41 * 60 + 15))),
        model(ScrapeHealth(lastRunAt: recent, lastSuccessAt: footerISO(minutesAgo: 60),
                           lastErrorKind: "no_tee_sheet", consecutiveFailedRuns: 3,
                           failingSince: footerISO(minutesAgo: 45))),
    ]
}()

/// ContentView's footer row, right-hand half: Spacer, then status + "·" + version.
private func footerRow(_ model: OverviewModel) -> some View {
    HStack(alignment: .firstTextBaseline) {
        Spacer(minLength: 12)
        HStack(spacing: 6) {
            FreshnessRow(model: model, fixedNow: footerNow)
            Text("·").font(scaledFont(.caption2)).foregroundStyle(.tertiary)
            Text("v0.64.0").font(scaledFont(.caption2)).foregroundStyle(.secondary)
        }
    }
}

/// Players with and without a handicap (2026-10-05): the "(18,4)" brackets sit inside the
/// one players Text, so the columns before it keep their spots whether or not a seat has one.
private let hcpSlotDay = Day(
    date: "2026-09-26",
    slots: [
        Slot(time: "09:00", booked: 3, capacity: 4, blockReason: nil,
             players: ["Max Mustermann", "Erika Beispiel", "Gast Eins"]),
        Slot(time: "10:00", booked: 4, capacity: 4, blockReason: nil,
             players: ["Christel Römer-Dold", "Gertrud Zimmermann", "Geraldine Piper", "Margit Kraut"]),
        Slot(time: "11:00", booked: 1, capacity: 4, blockReason: nil, players: []),
    ],
    weather: [],
    sunrise: nil, sunset: nil, events: [], bookedTime: nil
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
    VisualRegressionCase(name: "day-card-header-badges", size: CGSize(width: 760, height: 400)) {
        let model = badgeModel()
        return AnyView(
            VStack(alignment: .leading, spacing: 6) {
                ForEach(badgeDayFixtures) { day in
                    DayCardHeader(day: day, model: model)
                }
            }
            .padding(8)
        )
    },
    // The same seven days in German: "heute 20:00" is the widest value either language has.
    VisualRegressionCase(name: "day-card-header-badges-de", size: CGSize(width: 760, height: 400), language: "de") {
        let model = badgeModel()
        return AnyView(
            VStack(alignment: .leading, spacing: 6) {
                ForEach(badgeDayFixtures) { day in
                    DayCardHeader(day: day, model: model)
                }
            }
            .padding(8)
        )
    },
    // 11:00 carries the recommended ★, 12:00 the too-late moon (2026-10-05); 09:00/10:00 carry
    // none -- the times, and every column after them, must line up across all four.
    VisualRegressionCase(name: "slot-row-multi", size: CGSize(width: 520, height: 140)) {
        let model = OverviewModel()
        model.verdicts = [multiSlotDay.date: DayVerdict(windowAfter: nil, windowBefore: nil, unplayable: [],
                                                         recommended: ["11:00"], tooLate: ["12:00"])]
        return AnyView(
            VStack(alignment: .leading, spacing: 4) {
                ForEach(multiSlotDay.slots) { slot in
                    SlotRow(slot: slot, day: multiSlotDay, model: model)
                }
            }
            .padding(8)
        )
    },
    // Handicaps in brackets after the names; the second row is too long for the canvas and
    // must truncate rather than push anything.
    VisualRegressionCase(name: "slot-row-hcp", size: CGSize(width: 520, height: 100)) {
        let model = OverviewModel()
        model.friendNames = ["Erika Beispiel"]
        model.playerGenders = ["Max Mustermann": "male", "Erika Beispiel": "female"]
        model.playerHandicaps = ["Max Mustermann": 18.4, "Erika Beispiel": 7.5, "Christel Römer-Dold": 36,
                                 "Gertrud Zimmermann": 24.3, "Geraldine Piper": 11.2, "Margit Kraut": 54]
        return AnyView(
            VStack(alignment: .leading, spacing: 4) {
                ForEach(hcpSlotDay.slots) { slot in
                    SlotRow(slot: slot, day: hcpSlotDay, model: model)
                }
            }
            .padding(8)
        )
    },
    // The footer's right-hand cluster in its three states (2026-10-05, scrape health):
    // healthy, login rejected, failing. The dot, the freshness text and the version must
    // keep the same right-anchored spots in all three -- the warning only ever takes
    // room from the Spacer on its left (the same Spacer(minLength: 12) ContentView's
    // footer row uses), and the narrow last row shows it truncating rather than pushing.
    VisualRegressionCase(name: "footer-health-multi", size: CGSize(width: 640, height: 130)) {
        AnyView(
            VStack(alignment: .trailing, spacing: 8) {
                ForEach(Array(footerHealthModels.enumerated()), id: \.offset) { _, model in
                    footerRow(model)
                }
                footerRow(footerHealthModels[1]).frame(width: 360)
            }
            .padding(8)
        )
    },
    VisualRegressionCase(name: "player-row-multi", size: CGSize(width: 500, height: 170)) {
        AnyView(
            VStack(alignment: .leading, spacing: 4) {
                ForEach(multiPlayers) { player in
                    HStack { PlayerRowColumns(player: player) }
                }
            }
            .padding(8)
        )
    },
]
