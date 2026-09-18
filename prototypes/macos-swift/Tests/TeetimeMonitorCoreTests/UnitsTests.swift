@testable import TeetimeMonitorCore

/// Ported from `src/units.py` -- these reference values were cross-checked directly
/// against the real Python functions when `Units.swift` was written (`20C ->
/// 68.0000F`, `18kph -> 11.1847mph`, `1.5mm -> 0.0591in`). Pinning them here is what
/// makes that a permanent regression test instead of a one-time check that nothing
/// re-runs.
func runUnitsTests() {
    Harness.group("Units") {
        Harness.checkClose("20C -> F", Units.celsiusToFahrenheit(20), 68.0, tolerance: 1e-6)
        Harness.checkClose("0C -> F", Units.celsiusToFahrenheit(0), 32.0, tolerance: 1e-6)
        Harness.checkClose("18kph -> mph", Units.kphToMph(18), 11.184678, tolerance: 1e-4)
        Harness.checkClose("1.5mm -> in", Units.mmToInches(1.5), 0.0590552, tolerance: 1e-6)

        Harness.checkClose("temperature() metric passthrough", Units.temperature(20, Units.metric), 20, tolerance: 1e-9)
        Harness.checkClose("temperature() imperial converts", Units.temperature(20, Units.imperial), 68, tolerance: 1e-6)
        Harness.checkClose("windSpeed() metric passthrough", Units.windSpeed(18, Units.metric), 18, tolerance: 1e-9)
        Harness.checkClose("precipitationMM() metric passthrough", Units.precipitationMM(1.5, Units.metric), 1.5, tolerance: 1e-9)

        Harness.checkEqual("temperatureSymbol metric", Units.temperatureSymbol(Units.metric), "\u{b0}C")
        Harness.checkEqual("temperatureSymbol imperial", Units.temperatureSymbol(Units.imperial), "\u{b0}F")
        Harness.checkEqual("windSymbol metric", Units.windSymbol(Units.metric), "km/h")
        Harness.checkEqual("windSymbol imperial", Units.windSymbol(Units.imperial), "mph")

        // An unrecognized units string (can't happen from the picker, but Preferences
        // is a plain string field loaded from a hand-editable YAML file) must fall
        // back to metric, not crash or silently misconvert.
        Harness.checkClose("unknown units string falls back to metric",
                            Units.temperature(20, "garbage"), 20, tolerance: 1e-9)
    }
}
