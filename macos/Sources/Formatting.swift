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
    guard let mm, mm != 0 else { return "\(Int(probability))%" }
    let amount = Units.precipitationMM(mm, units)
    let decimals = units == Units.imperial ? 2 : 1
    return "\(Int(probability))%/" + String(format: "%.\(decimals)f", amount) + Units.precipitationAmountLabel(units)
}

func weekday(_ iso: String) -> String {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
    f.locale = Locale(identifier: "en_US_POSIX")  // parsing a fixed ISO shape
    guard let d = f.date(from: iso) else { return iso }
    // Formatting, unlike parsing, follows the chosen language -- "Fr 19 Sep"
    // rather than "Fri 19 Sep" when the interface is German.
    let o = DateFormatter(); o.dateFormat = "EEE d MMM"; o.locale = currentLocale()
    return o.string(from: d)
}
