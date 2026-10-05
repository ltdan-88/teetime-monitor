import SwiftUI

/// Small, pure display-formatting helpers used across the day list -- pulled out of
/// App.swift on their own so they can sit in the SPM test target alongside the rest
/// of this app's logic (see Tests/TeetimeMonitorCoreTests). App.swift's own `@main`
/// entry point and SwiftUI view bodies can't join that target without pulling the
/// whole windowing system into `swift test`; these three functions have no such
/// dependency and are exactly the kind of thing regression tests exist to catch a
/// silent WMO-code or threshold change in.

// WMO weather codes -> an icon, same mapping weather_icons.py uses.
func icon(for code: Int?) -> String {
    switch code ?? -1 {
    case 0: return "sun.max.fill"
    case 1, 2: return "cloud.sun.fill"
    case 3: return "cloud.fill"
    case 45, 48: return "cloud.fog.fill"
    case 51...57: return "cloud.drizzle.fill"
    case 61...67, 80...82: return "cloud.rain.fill"
    case 71...77, 85, 86: return "cloud.snow.fill"
    case 95...99: return "cloud.bolt.rain.fill"
    default: return "questionmark"
    }
}

/// The WMO code's own wording ("Light rain", "Thunderstorm with hail") in the current
/// language -- what the weather will actually be, which the icon alone can't say.
func conditionName(for code: Int?) -> String? {
    guard let code else { return nil }
    let key = "wmo.\(code)"
    let name = t(key)
    return name == key ? nil : name
}

/// The tooltip for one hour's weather icon: "Light rain · 20° · rain 63%/0.5mm ·
/// wind 10 km/h" (parts that aren't known are left out). Direct request,
/// 2026-10-02: a tooltip saying how the weather will actually be.
func weatherTooltip(_ w: WeatherPoint, units: String) -> String {
    var parts: [String] = []
    if let name = conditionName(for: w.code) { parts.append(name) }
    if let tempC = w.temperatureC {
        parts.append("\(wholeNumber(Units.temperature(tempC, units)))\(Units.temperatureSymbol(units))")
    }
    if let p = w.precipitationProbability {
        parts.append(t("weather.rain_part", ["v": precipitationCellText(probability: p, mm: w.precipitationMM, units: units)]))
    }
    if let wind = w.windKPH {
        parts.append(t("weather.wind_part", ["n": wholeNumber(Units.windSpeed(wind, units)), "unit": Units.windSymbol(units)]))
    }
    return parts.joined(separator: " · ")
}

/// "anonymous" / "2× anonymous" for booked seats whose names aren't public, or "" when
/// every booked seat has a name -- mirrors tui._anonymous_players_text().
func anonymousPlayersText(booked: Int, namedCount: Int) -> String {
    let count = booked - namedCount
    guard count > 0 else { return "" }
    let label = t("overview.anonymous")
    return count == 1 ? label : "\(count)× \(label)"
}

/// Player-name colour by gender: blue / magenta, the secondary grey when unknown.
/// Same two hues as the TUI's (tui._GENDER_COLORS).
func genderColor(_ gender: String?) -> Color {
    switch gender {
    case "male": return Color(red: 0x5a / 255.0, green: 0xa9 / 255.0, blue: 0xff / 255.0)
    case "female": return Color(red: 0xe3 / 255.0, green: 0x6b / 255.0, blue: 0xd0 / 255.0)
    default: return .secondary
    }
}

func fillColor(_ ratio: Double) -> Color {
    ratio >= 1.0 ? .red : (ratio >= 0.5 ? .orange : .green)
}

/// "70%" or "70%/1.5mm" -- mirrors `tui._slot_precipitation_cell()`'s own
/// "{probability}%{mm}" combination exactly: the amount suffix only appears
/// when there's a real, nonzero mm figure to show (Python's own `if
/// point.precipitation_mm else ""` -- 0.0 and nil are both falsy there),
/// not for every forecast point. Added 2026-09-19, direct report ("precipitation
/// amount in mm seems to still be missing") -- SlotRow/SearchResultRow
/// previously showed only the probability, dropping the actual amount TUI's
/// own table has always carried.
func precipitationCellText(probability: Double, mm: Double?, units: String) -> String {
    guard let mm, mm != 0 else { return "\(wholeNumber(probability))%" }
    return "\(wholeNumber(probability))%/" + precipitationAmountText(mm, units: units)
}

/// "1.5mm" / "0.06in" -- `tui._precipitation_amount_text()`: 1 decimal in mm, 2 in
/// inches.
func precipitationAmountText(_ mm: Double, units: String) -> String {
    let decimals = units == Units.imperial ? 2 : 1
    return String(format: "%.\(decimals)f", Units.precipitationMM(mm, units)) + Units.precipitationAmountLabel(units)
}

/// The rain (🌧, >= 50%) and wind (💨, >= 30 km/h on the raw value, whatever the
/// display units) flag thresholds -- `tui._SLOT_RAIN_ICON_THRESHOLD_PERCENT`/
/// `_SLOT_WIND_ICON_THRESHOLD_KPH`, shared by the slot and day cells.
let rainFlagPercent = 50.0
let windFlagKPH = 30.0

/// One slot row's precipitation cell exactly as `tui._slot_precipitation_cell()`
/// writes it, flag included: a forecast point with no probability shows "0%"
/// (plus its amount), not nothing.
func slotPrecipitationCellText(_ point: WeatherPoint?, units: String) -> String {
    guard let point else { return "" }
    let p = point.precipitationProbability ?? 0
    return (p >= rainFlagPercent ? "🌧 " : "") + precipitationCellText(probability: p, mm: point.precipitationMM, units: units)
}

extension Day {
    /// The day row's rain cell exactly as `tui._precipitation_cell()` writes it:
    /// "🌧 rain all day" when every daytime hour is >= 70%, else the average chance
    /// with the day's total amount ("🌧 55%/4.2mm"), "" with no daytime forecast.
    func precipitationCellText(units: String) -> String {
        guard let avg = precipAvg else { return "" }
        if isRainAllDay { return "🌧 " + t("overview.rain_all_day") }
        let total = precipTotalMM
        let amount = total != 0 ? "/" + precipitationAmountText(total, units: units) : ""
        return (avg >= rainFlagPercent ? "🌧 " : "") + "\(wholeNumber(avg))%" + amount
    }

    /// The day row's wind cell exactly as `tui._wind_cell()` writes it: the peak,
    /// with 💨 at >= 30 km/h.
    func windCellText(units: String) -> String {
        guard let peak = windPeak else { return "" }
        return (peak >= windFlagKPH ? "💨 " : "") + wholeNumber(Units.windSpeed(peak, units))
    }

    /// `tui._temperature_cell()`'s "24/14".
    func temperatureCellText(units: String) -> String {
        guard let (hi, lo) = tempHighLow else { return "" }
        return "\(wholeNumber(Units.temperature(hi, units)))/\(wholeNumber(Units.temperature(lo, units)))"
    }
}

/// A whole-number display of a measured value (temperature, wind, rain %) --
/// exactly what Python's own `f"{x:.0f}"` produces, which is what every TUI cell
/// uses. Replaces `Int(x)` everywhere a number is *shown* (2026-09-27, found
/// comparing real renders of both apps from the same database): `Int()`
/// truncates, so a daily low of 11.6° read 11° here and 12° in the TUI, and a
/// 10.7 km/h peak read 10 vs. 11 -- the same data disagreeing across the two
/// front ends. `%.0f` rounds the same way Python's formatting does (round-half-
/// to-even on the exact binary value); `CrossCheckRunner`'s `whole_number`
/// group pins that equivalence rather than assuming it.
func wholeNumber(_ value: Double) -> String { String(format: "%.0f", value) }

/// Date-only "yyyy-MM-dd" strings, the shape every `date` column in the database
/// uses. Always Gregorian: a user-chosen Buddhist or Japanese system calendar made a
/// plain `DateFormatter` write today as "2569-10-04"/"0008-10-04", so `date >= ?`
/// matched nothing (or everything). Parsed at UTC midnight, since local midnight
/// doesn't exist on a DST-at-00:00 day (Santiago, Beirut, Havana) and `date(from:)`
/// returned nil there.
enum ISODate {
    static let utc = TimeZone(identifier: "UTC")!

    static var utcCalendar: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = utc
        return c
    }

    /// Today's local date as "yyyy-MM-dd", whatever the system calendar is.
    static func today(now: Date = Date(), timeZone: TimeZone = .current) -> String {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = timeZone
        let d = c.dateComponents([.year, .month, .day], from: now)
        return String(format: "%04d-%02d-%02d", d.year ?? 0, d.month ?? 0, d.day ?? 0)
    }

    static func parse(_ iso: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = utcCalendar
        f.timeZone = utc
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: iso)
    }

    /// `iso` moved by `days` calendar days ("2026-10-31" + 1 -> "2026-11-01").
    static func adding(days: Int, to iso: String) -> String? {
        guard let d = parse(iso), let moved = utcCalendar.date(byAdding: .day, value: days, to: d) else { return nil }
        return today(now: moved, timeZone: utc)
    }
}

func weekday(_ iso: String) -> String {
    guard let d = ISODate.parse(iso) else { return iso }
    // Formatting, unlike parsing, follows the chosen language -- "Fr 19 Sep"
    // rather than "Fri 19 Sep" when the interface is German. UTC, same as the
    // parse, so the day can't shift by one.
    let o = DateFormatter(); o.dateFormat = "EEE d MMM"; o.locale = currentLocale()
    o.calendar = ISODate.utcCalendar; o.timeZone = ISODate.utc
    return o.string(from: d)
}

/// "4" / "3,5" / "1,25" -- a round's length in hours, for the window hint.
/// Mirrors `tui._window_hint_text()`'s own `f"{hours:g}"` with the decimal comma
/// German uses. C's `%g` is the same six-significant-digit, trailing-zero-free
/// format as Python's `:g` (a fixed `%.1f` showed 75 min as "1.2" instead of
/// "1.25"); the `hours_text` cross-check group pins that.
func hoursText(_ minutes: Int) -> String {
    hoursText(minutes, language: AppLanguage.shared.code)
}

func hoursText(_ minutes: Int, language: String) -> String {
    let text = String(format: "%g", Double(minutes) / 60)
    return language == "de" ? text.replacingOccurrences(of: ".", with: ",") : text
}

/// The overview's window-too-late hint line, plus -- when `picks_cli.py` found
/// one on those days -- where a shorter round still fits (2026-10-05). Same two
/// sentences as `tui._window_hint_text()`.
func windowHintText(_ hint: WindowHint) -> String {
    var text = t("hint.window_too_late", [
        "after": hint.windowAfter,
        "hours": hoursText(hint.roundMinutes),
        "sunset": hint.sunset,
        "latest": hint.latestStart,
    ])
    if !hint.alternativeCourses.isEmpty {
        text += " " + t("overview.hint_alternative", ["courses": hint.alternativeCourses.joined(separator: ", ")])
    }
    return text
}
