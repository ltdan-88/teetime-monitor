import Foundation
@testable import TeetimeMonitorCore

func runFormattingTests() {
    Harness.group("Formatting") {
        testIconMapping()
        testFillColorThresholds()
        testWeekdayFormatting()
        testHoursTextMatchesPythonG()
        testISODateIsGregorianAndDSTSafe()
        testDayPrecipitationMatchesTUI()
        testSlotPrecipitationCell()
        testLockWhenText()
        testLockSentence()
    }
}

/// Mirrors weather_icons.py's own WMO-code -> icon mapping (verified against it
/// when App.swift was first written) -- pinned as boundary cases per bucket, since
/// a future edit that shifts a range boundary by one is exactly the kind of change
/// that's easy to get subtly wrong.
private func testIconMapping() {
    Harness.checkEqual("clear sky", icon(for: 0), "sun.max.fill")
    Harness.checkEqual("mostly clear, low end", icon(for: 1), "cloud.sun.fill")
    Harness.checkEqual("mostly clear, high end", icon(for: 2), "cloud.sun.fill")
    Harness.checkEqual("overcast", icon(for: 3), "cloud.fill")
    Harness.checkEqual("fog, low end", icon(for: 45), "cloud.fog.fill")
    Harness.checkEqual("fog, high end", icon(for: 48), "cloud.fog.fill")
    Harness.checkEqual("drizzle, low end", icon(for: 51), "cloud.drizzle.fill")
    Harness.checkEqual("drizzle, high end", icon(for: 57), "cloud.drizzle.fill")
    Harness.checkEqual("rain, low end", icon(for: 61), "cloud.rain.fill")
    Harness.checkEqual("rain showers, high end", icon(for: 82), "cloud.rain.fill")
    Harness.checkEqual("snow, low end", icon(for: 71), "cloud.snow.fill")
    Harness.checkEqual("snow showers", icon(for: 86), "cloud.snow.fill")
    Harness.checkEqual("thunderstorm, low end", icon(for: 95), "cloud.bolt.rain.fill")
    Harness.checkEqual("thunderstorm, high end", icon(for: 99), "cloud.bolt.rain.fill")
    Harness.checkEqual("nil code", icon(for: nil), "questionmark")
    Harness.checkEqual("an unrecognized code", icon(for: 12345), "questionmark")
}

/// Same three fill-ratio thresholds `tui._heatmap_cell_style()`/`_heat_strip_blocks()`
/// use -- the exact boundary values, not just "somewhere in the middle."
private func testFillColorThresholds() {
    Harness.checkEqual("just under half is green", fillColor(0.49), .green)
    Harness.checkEqual("exactly half is orange, not green", fillColor(0.5), .orange)
    Harness.checkEqual("just under full is orange", fillColor(0.99), .orange)
    Harness.checkEqual("exactly full is red, not orange", fillColor(1.0), .red)
    Harness.checkEqual("over full (shouldn't happen, but) is still red", fillColor(1.5), .red)
    Harness.checkEqual("empty is green", fillColor(0.0), .green)
}

private func testWeekdayFormatting() {
    // 2026-09-18 is a real Friday.
    AppLanguage.shared.code = "en"
    Harness.checkEqual("English weekday format", weekday("2026-09-18"), "Fri 18 Sep")
    AppLanguage.shared.code = "de"
    Harness.checkEqual("German weekday format", weekday("2026-09-18"), "Fr. 18 Sept.")
    AppLanguage.shared.code = "en"

    Harness.checkEqual("an unparseable date passes through unchanged", weekday("not-a-date"), "not-a-date")
}

/// `f"{hours:g}"` -- quarter-hour round lengths keep both decimals (75 min was "1.2").
private func testHoursTextMatchesPythonG() {
    Harness.checkEqual("75 min", hoursText(75, language: "en"), "1.25")
    Harness.checkEqual("105 min", hoursText(105, language: "en"), "1.75")
    Harness.checkEqual("135 min, German comma", hoursText(135, language: "de"), "2,25")
    Harness.checkEqual("90 min", hoursText(90, language: "en"), "1.5")
    Harness.checkEqual("whole hours", hoursText(240, language: "en"), "4")
}

private func testISODateIsGregorianAndDSTSafe() {
    // 2026-10-04 12:00 UTC.
    let noon = Date(timeIntervalSince1970: 1_791_115_200)
    Harness.checkEqual("today is Gregorian", ISODate.today(now: noon, timeZone: TimeZone(identifier: "UTC")!), "2026-10-04")
    Harness.checkEqual("today follows the given zone",
                        ISODate.today(now: noon, timeZone: TimeZone(identifier: "Pacific/Kiritimati")!), "2026-10-05")
    Harness.checkEqual("adding crosses a month end", ISODate.adding(days: 2, to: "2026-10-31"), "2026-11-02")
    // Santiago's clocks jump from 00:00 to 01:00 on 2026-09-06: local midnight
    // doesn't exist, which made a local-time parse return nil.
    Harness.check("a DST-at-midnight date still parses", ISODate.parse("2026-09-06") != nil)
    Harness.checkEqual("and classifies as the Sunday it is",
                        CalendarContext.classifyDay(date: "2026-09-06", holidays: [], vacationRanges: [], hasTournament: false),
                        "weekend")
    Harness.check("garbage doesn't parse", ISODate.parse("2026-13-45") == nil)
}

private func point(_ time: String, _ p: Double?, _ mm: Double? = nil, wind: Double? = nil) -> WeatherPoint {
    WeatherPoint(time: time, precipitationProbability: p, precipitationMM: mm, windKPH: wind, temperatureC: nil, code: nil)
}

/// `tui._precipitation_cell()`: a missing probability counts as 0 in the average
/// (not dropped), the total amount follows, and an all-wet day says so.
private func testDayPrecipitationMatchesTUI() {
    AppLanguage.shared.code = "en"
    let hours = (8..<20).map { String(format: "%02d:00", $0) }
    let half = Day(date: "2026-10-04", slots: [], weather: hours.enumerated().map { i, h in point(h, i < 6 ? 60 : nil) },
                   sunrise: nil, sunset: nil, events: [], bookedTime: nil)
    Harness.checkEqual("6x60% + 6xnull averages 30%, as the TUI does", half.precipAvg, 30)
    Harness.checkEqual("cell text", half.precipitationCellText(units: "metric"), "30%")

    let wet = Day(date: "2026-10-04", slots: [], weather: hours.map { point($0, 85, 0.35) },
                  sunrise: nil, sunset: nil, events: [], bookedTime: nil)
    Harness.check("every hour >= 70% is rain all day", wet.isRainAllDay)
    Harness.checkEqual("rain all day text", wet.precipitationCellText(units: "metric"), "🌧 rain all day")

    let mixed = Day(date: "2026-10-04", slots: [], weather: [point("09:00", 40, 1.2, wind: 31), point("13:00", 70, 3.0, wind: 12)],
                    sunrise: nil, sunset: nil, events: [], bookedTime: nil)
    Harness.checkEqual("flag + total mm", mixed.precipitationCellText(units: "metric"), "🌧 55%/4.2mm")
    Harness.checkEqual("wind flag on the raw km/h peak", mixed.windCellText(units: "imperial"), "💨 19")

    let nothing = Day(date: "2026-10-04", slots: [], weather: [point("07:00", 90)], sunrise: nil, sunset: nil,
                      events: [], bookedTime: nil)
    Harness.check("no daytime points -> no average", nothing.precipAvg == nil)
    Harness.checkEqual("and an empty cell", nothing.precipitationCellText(units: "metric"), "")
}

private func testSlotPrecipitationCell() {
    Harness.checkEqual("missing probability shows 0% with its amount",
                        slotPrecipitationCellText(point("10:00", nil, 1.2), units: "metric"), "0%/1.2mm")
    Harness.checkEqual("flagged", slotPrecipitationCellText(point("10:00", 50), units: "metric"), "🌧 50%")
    Harness.checkEqual("no point", slotPrecipitationCellText(nil, units: "metric"), "")
}

private func isoDate(_ s: String) -> Date { ISO8601DateFormatter().date(from: s)! }

/// `lockWhenText()` against `tui._lock_when_text()` (the cross-language runner pins the
/// same cases against the real Python function) -- "today"/weekday/date, hour known or not.
private func testLockWhenText() {
    let now = isoDate("2026-10-05T16:28:00Z")  // Mon 18:28 in Berlin (+02:00)
    AppLanguage.shared.code = "en"
    defer { AppLanguage.shared.code = "en" }
    Harness.checkEqual("later today", lockWhenText(opensAt: "2026-10-05T20:00:00+02:00", hourKnown: true, now: now),
                       "today 20:00")
    Harness.checkEqual("a weekday", lockWhenText(opensAt: "2026-10-07T21:00:00+02:00", hourKnown: true, now: now),
                       "Wed 21:00")
    Harness.checkEqual("tomorrow is still a weekday", lockWhenText(opensAt: "2026-10-06T20:00:00+02:00", hourKnown: true, now: now),
                       "Tue 20:00")
    Harness.checkEqual("six days out is a weekday", lockWhenText(opensAt: "2026-10-11T08:00:00+02:00", hourKnown: true, now: now),
                       "Sun 08:00")
    Harness.checkEqual("seven days out is a date", lockWhenText(opensAt: "2026-10-12T08:00:00+02:00", hourKnown: true, now: now),
                       "Oct 12 08:00")
    Harness.checkEqual("no hour: the day only", lockWhenText(opensAt: "2026-10-07T00:00:00+02:00", hourKnown: false, now: now),
                       "Wed")
    // The opening's own calendar decides "today", not the machine's: 23:30 UTC is already
    // Tuesday in Berlin (+02:00), so 2026-10-06 20:00 is today there.
    Harness.checkEqual("today is the club's calendar day",
                       lockWhenText(opensAt: "2026-10-06T20:00:00+02:00", hourKnown: true, now: isoDate("2026-10-05T23:30:00Z")),
                       "today 20:00")
    Harness.checkEqual("a Z offset parses", lockWhenText(opensAt: "2026-10-05T20:00:00Z", hourKnown: true, now: now),
                       "today 20:00")
    Harness.checkEqual("a negative offset parses", lockWhenText(opensAt: "2026-10-05T20:00:00-05:00", hourKnown: true, now: now),
                       "today 20:00")
    Harness.check("garbage is nil", lockWhenText(opensAt: "soon", hourKnown: true, now: now) == nil)
    Harness.check("a bad offset is nil", lockWhenText(opensAt: "2026-10-05T20:00:00+xx", hourKnown: true, now: now) == nil)

    AppLanguage.shared.code = "de"
    Harness.checkEqual("German today", lockWhenText(opensAt: "2026-10-05T20:00:00+02:00", hourKnown: true, now: now),
                       "heute 20:00")
    Harness.checkEqual("German weekday", lockWhenText(opensAt: "2026-10-07T21:00:00+02:00", hourKnown: true, now: now),
                       "Mi 21:00")
    Harness.checkEqual("German date, day before month", lockWhenText(opensAt: "2026-10-12T08:00:00+02:00", hourKnown: true, now: now),
                       "12. Okt 08:00")
    Harness.checkEqual("German date, March umlaut", lockWhenText(opensAt: "2026-03-09T08:00:00+01:00", hourKnown: false, now: isoDate("2026-03-01T10:00:00Z")),
                       "9. Mär")
    Harness.checkEqual("German weekday, Sunday", lockWhenText(opensAt: "2026-10-11T08:00:00+02:00", hourKnown: true, now: now),
                       "So 08:00")
}

private func testLockSentence() {
    let now = isoDate("2026-10-05T16:28:00Z")
    AppLanguage.shared.code = "en"
    defer { AppLanguage.shared.code = "en" }
    Harness.checkEqual("sentence with an hour", lockSentence(opensAt: "2026-10-07T21:00:00+02:00", hourKnown: true, now: now),
                       "Booking opens Wed 21:00")
    Harness.checkEqual("sentence without an hour claims no time",
                       lockSentence(opensAt: "2026-10-07T00:00:00+02:00", hourKnown: false, now: now),
                       "Booking opens Wed (the club gives no time)")
    AppLanguage.shared.code = "de"
    Harness.checkEqual("German sentence", lockSentence(opensAt: "2026-10-07T21:00:00+02:00", hourKnown: true, now: now),
                       "Buchbar ab Mi 21:00")
    Harness.checkEqual("German date-level sentence",
                       lockSentence(opensAt: "2026-10-07T00:00:00+02:00", hourKnown: false, now: now),
                       "Buchbar ab Mi (Uhrzeit vom Club nicht angegeben)")
}
