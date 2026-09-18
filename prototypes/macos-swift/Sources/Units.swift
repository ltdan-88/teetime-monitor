import Foundation

/// Metric/imperial display conversion -- ports `src/units.py` exactly, including
/// its deliberate narrowness: only the physical quantities this app actually
/// displays convert, and a percentage (rain probability, occupancy) is already
/// unit-agnostic and never touches this.
///
/// **Why this exists**: Settings has had a Units picker since Tier 1, and it wrote
/// `units:` to `preferences.yaml` correctly the whole time -- but nothing in this
/// app ever *read* it back. Every temperature was a hardcoded `"%.0f°"` and every
/// wind speed a bare km/h number, so switching to imperial changed the file, the
/// TUI, and nothing whatsoever on screen here. Reported directly: "changing metric
/// to imperial also doesn't change anything." The setting was never broken; the
/// display simply ignored it.
enum Units {
    static let metric = "metric"
    static let imperial = "imperial"

    static func celsiusToFahrenheit(_ c: Double) -> Double { c * 9 / 5 + 32 }
    static func kphToMph(_ kph: Double) -> Double { kph * 0.621371 }
    static func mmToInches(_ mm: Double) -> Double { mm * 0.0393701 }

    static func temperature(_ celsius: Double, _ units: String) -> Double {
        units == imperial ? celsiusToFahrenheit(celsius) : celsius
    }

    static func windSpeed(_ kph: Double, _ units: String) -> Double {
        units == imperial ? kphToMph(kph) : kph
    }

    static func precipitationMM(_ mm: Double, _ units: String) -> Double {
        units == imperial ? mmToInches(mm) : mm
    }

    /// Mirrors `units.SYMBOLS` -- used by the legend line, which is this app's
    /// equivalent of the TUI's own unit-bearing column headers.
    static func temperatureSymbol(_ units: String) -> String { units == imperial ? "°F" : "°C" }
    static func windSymbol(_ units: String) -> String { units == imperial ? "mph" : "km/h" }
}

/// The running app's current units -- same singleton shape as `AppTheme`/`AppScale`,
/// for the same reason: `SettingsSheet` assigning to it is what redraws every view
/// showing a temperature or wind speed, immediately and with no relaunch.
///
/// Seeded from `preferences.yaml` (the same file the TUI reads), not from its own
/// key, so the two front ends genuinely share one setting rather than each keeping
/// a private copy.
final class AppUnits: ObservableObject {
    static let shared = AppUnits()

    @Published var value: String

    private init() {
        value = Preferences.load().units
    }
}
