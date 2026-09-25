@testable import TeetimeMonitorCore

func runFormattingTests() {
    Harness.group("Formatting") {
        testIconMapping()
        testFillColorThresholds()
        testWeekdayFormatting()
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
