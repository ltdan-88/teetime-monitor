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
    let amount = Units.precipitationMM(mm, units)
    let decimals = units == Units.imperial ? 2 : 1
    return "\(wholeNumber(probability))%/" + String(format: "%.\(decimals)f", amount) + Units.precipitationAmountLabel(units)
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

func weekday(_ iso: String) -> String {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
    f.locale = Locale(identifier: "en_US_POSIX")  // parsing a fixed ISO shape
    guard let d = f.date(from: iso) else { return iso }
    // Formatting, unlike parsing, follows the chosen language -- "Fr 19 Sep"
    // rather than "Fri 19 Sep" when the interface is German.
    let o = DateFormatter(); o.dateFormat = "EEE d MMM"; o.locale = currentLocale()
    return o.string(from: d)
}

/// "4" / "3,5" -- a round's length in hours, for the window hint. Mirrors
/// `tui._window_hint_text()`'s own `f"{hours:g}"` with the decimal comma German
/// uses.
func hoursText(_ minutes: Int) -> String {
    let hours = Double(minutes) / 60
    let text = hours == hours.rounded() ? String(Int(hours)) : String(format: "%.1f", hours)
    return AppLanguage.shared.code == "de" ? text.replacingOccurrences(of: ".", with: ",") : text
}
