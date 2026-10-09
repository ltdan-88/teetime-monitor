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

    /// Mirrors `units.precipitation_amount_label()` -- the one per-cell unit
    /// suffix that survived the header taking over every other unit label (see
    /// that function's own docstring): a precipitation cell packs two numbers
    /// together ("70%/1.5mm"), so this is what tells them apart. Added
    /// 2026-09-19 alongside actually displaying the mm/in amount at all (direct
    /// report, "precipitation amount in mm seems to still be missing") --
    /// SlotRow/SearchResultRow previously showed only the probability
    /// percentage, never the amount.
    static func precipitationAmountLabel(_ units: String) -> String { units == imperial ? "in" : "mm" }
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

/// Whether players' handicaps show next to their names (`show_handicaps` in
/// `preferences.yaml`, default on) -- same singleton shape as `AppUnits`, so flipping
/// it in Settings redraws the slot rows at once.
final class AppShowHandicaps: ObservableObject {
    static let shared = AppShowHandicaps()

    @Published var value: Bool

    private init() {
        value = Preferences.load().showHandicaps
    }
}

/// The group size (`availability.min_open_spots`, 1-4): one shared value behind the
/// overview's quick "Group" picker and Preferences' "Min open spots (party size)" row
/// (2026-10-09), same singleton shape as `AppShowHandicaps`. Seeded from
/// `preferences.yaml`, the file the TUI reads too.
final class AppPartySize: ObservableObject {
    static let shared = AppPartySize()
    static let choices = [1, 2, 3, 4]

    @Published var value: Int

    /// Writes the preference; a seam so tests don't touch the real file.
    var persist: (Int) throws -> Void = { try Preferences.setMinOpenSpots($0) }
    /// Reads the saved preference; a seam like `persist`.
    var loadSaved: () -> Int = { Preferences.load().minOpenSpots }

    private init() {
        value = Preferences.load().minOpenSpots
    }

    /// Follows a change made behind this app's back (the TUI's Group dropdown or its
    /// Preferences, another GUI process): re-reads the file and publishes only when it
    /// differs. Called when Preferences opens, on app activation and from each
    /// `OverviewModel.reload()`. Every write here is synchronous (`choose()`), so the
    /// file is always the truth -- there is no pending write to protect (2026-10-09).
    func refreshFromFile() {
        let saved = loadSaved()
        if saved != value { value = saved }
    }

    /// The picker's choice: written first, shown only once it is saved (a failed write
    /// leaves the old value on screen). Returns whether it was saved. Re-reads the file
    /// first, so picking the size the picker still shows after an outside change (the
    /// TUI saved a different one) is a real write, not a no-op.
    @discardableResult
    func choose(_ spots: Int) -> Bool {
        refreshFromFile()
        guard spots != value else { return true }
        do { try persist(spots) } catch { objectWillChange.send(); return false }  // re-reads the picker's binding
        value = spots
        return true
    }
}
