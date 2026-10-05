import Foundation
@testable import TeetimeMonitorCore

func runCalendarContextTests() {
    Harness.group("CalendarContext") {
        testWeekdaysConstant()
        testWorkdayVsWeekend()
        testClassificationPriorityOrder()
        testVacationRangeMatching()
        testVacationRangesParsedFromYAML()
        testVacationRangesBlockStyleIndentedUnderKey()
        testVacationRangesBlockStyleDashAtKeyIndent()
        testVacationRangesEmptyListNoCrash()
        testCountryCodeFromYAML()
        testIsTournamentDayIgnoresRoutineBlocks()
        testIsTournamentDayRecognisesCompetitions()
        testIsTournamentDayBlockedShare()
        testHolesFromCourseLabel()
    }
}

/// Builds `total` slots, the first `blocked` of them blocked by `reason`.
private func tournamentSlots(_ reason: String?, blocked: Int, total: Int) -> [Slot] {
    (0..<total).map { i in
        Slot(time: String(format: "%02d:%02d", 8 + i / 6, (i % 6) * 10), booked: 0, capacity: 4,
             blockReason: i < blocked ? reason : nil, players: [])
    }
}

/// Mirrors tests/test_calendar_context.py's is_tournament_day cases.
private func testIsTournamentDayIgnoresRoutineBlocks() {
    Harness.check("no events is never a tournament",
                  !CalendarContext.isTournamentDay(events: [], slots: tournamentSlots(nil, blocked: 0, total: 10)))
    Harness.check("a weekly ladies' group blocking 11 of 85 slots is not a tournament",
                  !CalendarContext.isTournamentDay(events: ["Dienstag-Ladies"],
                                                   slots: tournamentSlots("Dienstag-Ladies", blocked: 11, total: 85)))
    Harness.check("a lesson and an instructor name are not a tournament",
                  !CalendarContext.isTournamentDay(events: ["Grundkurs", "Marco"],
                                                   slots: tournamentSlots("Grundkurs", blocked: 2, total: 60)))
}

private func testIsTournamentDayRecognisesCompetitions() {
    for name in ["HP Golf Cup", "Vierer-Clubmeisterschaften", "Matchplay", "Club Championship", "Herbstturnier"] {
        Harness.check("\(name) is a tournament",
                      CalendarContext.isTournamentDay(events: [name], slots: tournamentSlots(name, blocked: 1, total: 60)))
    }
}

private func testIsTournamentDayBlockedShare() {
    Harness.check("an unnamed event blocking half the day is a tournament",
                  CalendarContext.isTournamentDay(events: ["Nippenburg Quick 9"],
                                                  slots: tournamentSlots("Nippenburg Quick 9", blocked: 30, total: 60)))
    Harness.check("advance-booking notices never count toward the share",
                  !CalendarContext.isTournamentDay(events: ["Montagsgolfer"],
                                                   slots: tournamentSlots("4 Tage im Voraus buchbar", blocked: 50, total: 60)))
}

/// Mirrors scraper._holes_from_course_label(): an explicit "N Loch" mention wins
/// over the leading digits, the smallest one when there are several.
private func testHolesFromCourseLabel() {
    Harness.checkEqual("leading count", Store.holes(from: "18 Loch Tee 1"), 18)
    Harness.checkEqual("hyphenated", Store.holes(from: "9-Loch Schleife"), 9)
    Harness.checkEqual("count in parentheses", Store.holes(from: "Tee 10 (9 Loch)"), 9)
    Harness.checkEqual("count after a colon", Store.holes(from: "Kurzplatz: 6 Loch"), 6)
    Harness.checkEqual("narrowed loop", Store.holes(from: "18-Loch Schleife (nur erste 9-Loch)"), 9)
    Harness.checkEqual("bare 9 without Loch isn't a count", Store.holes(from: "Tee 1: 9 oder 18 Loch"), 18)
    Harness.check("no number at all", Store.holes(from: "Kurzplatz") == nil)
}

private func testWeekdaysConstant() {
    // Sunday-first, matching calendar_context.WEEKDAYS exactly -- the mockup's own
    // column order.
    Harness.checkEqual("weekdays starts on Sunday", CalendarContext.weekdays.first, "Sunday")
    Harness.checkEqual("weekdays has 7 entries", CalendarContext.weekdays.count, 7)
    Harness.checkEqual("special day types", CalendarContext.specialDayTypes, ["tournament", "public_holiday", "vacation"])
}

private func testWorkdayVsWeekend() {
    // 2026-09-18 is a real Friday, 2026-09-19/20 a real Sat/Sun -- verified against
    // Python's own date.weekday() before writing this test, not assumed.
    Harness.checkEqual("Friday classifies as workday",
                        CalendarContext.classifyDay(date: "2026-09-18", holidays: [], vacationRanges: [], hasTournament: false),
                        "workday")
    Harness.checkEqual("Saturday classifies as weekend",
                        CalendarContext.classifyDay(date: "2026-09-19", holidays: [], vacationRanges: [], hasTournament: false),
                        "weekend")
    Harness.checkEqual("Sunday classifies as weekend",
                        CalendarContext.classifyDay(date: "2026-09-20", holidays: [], vacationRanges: [], hasTournament: false),
                        "weekend")
    Harness.checkEqual("Monday classifies as workday",
                        CalendarContext.classifyDay(date: "2026-09-21", holidays: [], vacationRanges: [], hasTournament: false),
                        "workday")
}

/// Mirrors classify_day()'s own "most-specific first" order exactly: a tournament
/// on a public holiday is still "tournament", a holiday that also falls in a
/// vacation range is still "public_holiday" -- each check short-circuits the ones
/// below it.
private func testClassificationPriorityOrder() {
    let holidays = ["2026-12-25"]
    let vacations = [VacationRange(start: "2026-12-20", end: "2027-01-05", label: "Christmas")]

    Harness.checkEqual("tournament wins over everything, even on a holiday+vacation date",
                        CalendarContext.classifyDay(date: "2026-12-25", holidays: holidays, vacationRanges: vacations, hasTournament: true),
                        "tournament")
    Harness.checkEqual("holiday wins over vacation when both apply",
                        CalendarContext.classifyDay(date: "2026-12-25", holidays: holidays, vacationRanges: vacations, hasTournament: false),
                        "public_holiday")
    Harness.checkEqual("vacation applies when not a holiday and no tournament",
                        CalendarContext.classifyDay(date: "2026-12-22", holidays: holidays, vacationRanges: vacations, hasTournament: false),
                        "vacation")
    Harness.checkEqual("plain weekday outside any special range",
                        CalendarContext.classifyDay(date: "2026-06-15", holidays: holidays, vacationRanges: vacations, hasTournament: false),
                        "workday")
}

private func testVacationRangeMatching() {
    let vacations = [VacationRange(start: "2026-07-01", end: "2026-07-14", label: "summer")]
    Harness.checkEqual("date at the start boundary matches",
                        CalendarContext.classifyDay(date: "2026-07-01", holidays: [], vacationRanges: vacations, hasTournament: false),
                        "vacation")
    Harness.checkEqual("date at the end boundary matches",
                        CalendarContext.classifyDay(date: "2026-07-14", holidays: [], vacationRanges: vacations, hasTournament: false),
                        "vacation")
    Harness.checkEqual("date just outside the range does not match",
                        CalendarContext.classifyDay(date: "2026-07-15", holidays: [], vacationRanges: vacations, hasTournament: false),
                        "workday")
}

/// The real gap this closed: `vacationRanges()` used to always return `[]`. Verified
/// against a real `yaml.safe_load()` of the identical fixture text before writing
/// this parser (`{'start': '2026-07-04', 'end': '2026-09-15', 'label': 'summer
/// break'}, {'start': '2026-12-20', 'end': '2027-01-05'}]`) -- pinned here so that
/// stays true.
private func testVacationRangesParsedFromYAML() {
    let dir = TempDir()
    let path = dir.file("club.yaml")
    try! """
    calendar:
      country_code: DE
      vacation_ranges:
        - { start: "2026-07-04", end: "2026-09-15", label: "summer break" }
        - { start: "2026-12-20", end: "2027-01-05" }
    overview_days: 5
    """.write(toFile: path, atomically: true, encoding: .utf8)

    let ranges = CalendarContext.vacationRanges(clubYAMLPath: path)
    Harness.checkEqual("both ranges parsed", ranges.count, 2)
    Harness.checkEqual("first range start", ranges.first?.start, "2026-07-04")
    Harness.checkEqual("first range end", ranges.first?.end, "2026-09-15")
    Harness.checkEqual("first range label", ranges.first?.label, "summer break")
    Harness.checkEqual("second range with no label defaults to empty, not a crash",
                        ranges.last?.label, "")

    // The actual point of parsing this at all: classify_day() now sees it.
    Harness.checkEqual("a date inside the parsed range classifies as vacation",
                        CalendarContext.classifyDay(date: "2026-08-01", holidays: [], vacationRanges: ranges, hasTournament: false),
                        "vacation")
}

/// The block-style shape `yaml.safe_load()` also accepts alongside the flow-style
/// `{ ... }` form above -- the dash's own siblings indented on the lines under it.
/// Verified against a real `yaml.safe_load()` of the identical fixture text before
/// writing this: `[{'start': '2026-07-04', 'end': '2026-09-15', 'label': 'summer
/// break'}, {'start': '2026-12-20', 'end': '2027-01-05'}]`.
private func testVacationRangesBlockStyleIndentedUnderKey() {
    let dir = TempDir()
    let path = dir.file("club.yaml")
    try! """
    calendar:
      country_code: DE
      vacation_ranges:
        - start: "2026-07-04"
          end: "2026-09-15"
          label: "summer break"
        - start: "2026-12-20"
          end: "2027-01-05"
    overview_days: 5
    """.write(toFile: path, atomically: true, encoding: .utf8)

    let ranges = CalendarContext.vacationRanges(clubYAMLPath: path)
    Harness.checkEqual("both block-style ranges parsed", ranges.count, 2)
    Harness.checkEqual("first range start", ranges.first?.start, "2026-07-04")
    Harness.checkEqual("first range end", ranges.first?.end, "2026-09-15")
    Harness.checkEqual("first range label", ranges.first?.label, "summer break")
    Harness.checkEqual("second range with no label defaults to empty, not a crash",
                        ranges.last?.label, "")
}

/// The other legal indentation, per the same `yaml.safe_load()` check: the dash
/// lined up with `vacation_ranges:` itself rather than indented under it. Verified
/// against real `yaml.safe_load()` output: `[{'start': '2026-07-04', 'end':
/// '2026-09-15', 'label': 'summer'}]`.
private func testVacationRangesBlockStyleDashAtKeyIndent() {
    let dir = TempDir()
    let path = dir.file("club.yaml")
    try! """
    calendar:
      vacation_ranges:
      - start: "2026-07-04"
        end: "2026-09-15"
        label: summer
    """.write(toFile: path, atomically: true, encoding: .utf8)

    let ranges = CalendarContext.vacationRanges(clubYAMLPath: path)
    Harness.checkEqual("range parsed with dash at the key's own indent", ranges.count, 1)
    Harness.checkEqual("start", ranges.first?.start, "2026-07-04")
    Harness.checkEqual("end", ranges.first?.end, "2026-09-15")
    Harness.checkEqual("bare (unquoted) label", ranges.first?.label, "summer")
}

private func testVacationRangesEmptyListNoCrash() {
    let dir = TempDir()
    let path = dir.file("club.yaml")
    try! "calendar:\n  country_code: \"\"\n  vacation_ranges: []\n".write(
        toFile: path, atomically: true, encoding: .utf8)
    Harness.check("an empty list parses to no ranges, not a crash",
                   CalendarContext.vacationRanges(clubYAMLPath: path).isEmpty)
}

private func testCountryCodeFromYAML() {
    let dir = TempDir()
    let path = dir.file("club.yaml")
    try! "calendar:\n  country_code: DE\n  vacation_ranges: []\n".write(
        toFile: path, atomically: true, encoding: .utf8)
    Harness.checkEqual("country_code reads through YAML.swift's own map-of-scalars parser fine",
                        CalendarContext.countryCode(clubYAMLPath: path), "DE")

    let blankPath = dir.file("blank.yaml")
    try! "calendar:\n  country_code: \"\"\n".write(toFile: blankPath, atomically: true, encoding: .utf8)
    Harness.check("a blank country_code is nil, not an empty string",
                   CalendarContext.countryCode(clubYAMLPath: blankPath) == nil)

    Harness.check("a missing file returns nil, not a crash",
                   CalendarContext.countryCode(clubYAMLPath: "/nonexistent/path.yaml") == nil)
}
