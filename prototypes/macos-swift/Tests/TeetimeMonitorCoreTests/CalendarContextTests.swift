import Foundation
@testable import TeetimeMonitorCore

func runCalendarContextTests() {
    Harness.group("CalendarContext") {
        testWeekdaysConstant()
        testWorkdayVsWeekend()
        testClassificationPriorityOrder()
        testVacationRangeMatching()
        testVacationRangesParsedFromYAML()
        testVacationRangesEmptyListNoCrash()
        testCountryCodeFromYAML()
    }
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
