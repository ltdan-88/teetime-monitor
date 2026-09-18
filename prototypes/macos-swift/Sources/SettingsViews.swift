import SwiftUI

/// Mirrors `PreferencesScreen` (v0.29.0's split): what makes a good tee time *for
/// you*. Reads/writes the same `preferences.yaml` directly -- see
/// `PreferencesStore.swift` for the verified round-trip with Python.
struct PreferencesSheet: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var prefs = Box(Preferences.load())
    @StateObject private var status = Box<String?>(nil)

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Preferences").font(.title2).bold().padding([.top, .horizontal], 16)
            Form {
                Section("Availability") {
                    Stepper("Min open spots: \(prefs.value.minOpenSpots)", value: $prefs.value.minOpenSpots, in: 1...4)
                    TimeWindowRow(label: "Weekday", after: $prefs.value.weekdayAfter, before: $prefs.value.weekdayBefore)
                    TimeWindowRow(label: "Weekend", after: $prefs.value.weekendAfter, before: $prefs.value.weekendBefore)
                    Stepper("Buffer before: \(prefs.value.bufferBeforeMinutes)m", value: $prefs.value.bufferBeforeMinutes, in: 0...60, step: 5)
                    Stepper("Buffer after: \(prefs.value.bufferAfterMinutes)m", value: $prefs.value.bufferAfterMinutes, in: 0...60, step: 5)
                }
                Section("Weather") {
                    Toggle("Avoid rain", isOn: $prefs.value.avoidRain)
                    if prefs.value.avoidRain {
                        Stepper("...above \(Int(prefs.value.avoidRainProbabilityPercent))%",
                                value: $prefs.value.avoidRainProbabilityPercent, in: 0...100, step: 5)
                        Stepper("...above \(String(format: "%.1f", prefs.value.avoidRainMM))mm",
                                value: $prefs.value.avoidRainMM, in: 0...10, step: 0.5)
                    }
                    Toggle("Avoid wind", isOn: $prefs.value.avoidWind)
                    if prefs.value.avoidWind {
                        Stepper("...above \(Int(prefs.value.avoidWindKPH))kph", value: $prefs.value.avoidWindKPH, in: 0...80, step: 5)
                    }
                    OptionalTempRow(label: "Avoid below", value: $prefs.value.avoidTempBelowC)
                    OptionalTempRow(label: "Avoid above", value: $prefs.value.avoidTempAboveC)
                }
                Section("Pace & daylight") {
                    Stepper("Daylight buffer: \(prefs.value.daylightBufferMinutes)m", value: $prefs.value.daylightBufferMinutes, in: 0...60, step: 5)
                    Stepper("9 holes: \(prefs.value.roundDurationNine)m", value: $prefs.value.roundDurationNine, in: 60...240, step: 15)
                    Stepper("18 holes: \(prefs.value.roundDurationEighteen)m", value: $prefs.value.roundDurationEighteen, in: 120...360, step: 15)
                }
                Section("Priorities") {
                    Toggle("Prioritize friends' slots", isOn: $prefs.value.prioritizeFriends)
                }
            }
            .formStyle(.grouped)

            HStack {
                if let status = status.value { Text(status).font(.caption).foregroundStyle(.secondary) }
                Spacer()
                Button("Cancel") { dismiss() }
                Button("Save") {
                    do {
                        try prefs.value.save()
                        status.value = "Saved"
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { dismiss() }
                    } catch {
                        status.value = "Couldn't save: \(error.localizedDescription)"
                    }
                }
                .keyboardShortcut(.defaultAction)
            }
            .padding(16)
        }
        .frame(width: 460, height: 560)
    }
}

private struct TimeWindowRow: View {
    let label: String
    @Binding var after: String?
    @Binding var before: String?

    var body: some View {
        HStack {
            Text(label).frame(width: 70, alignment: .leading)
            OptionalTimeField(placeholder: "after", value: $after)
            Text("–")
            OptionalTimeField(placeholder: "before", value: $before)
        }
    }
}

private struct OptionalTimeField: View {
    let placeholder: String
    @Binding var value: String?

    var body: some View {
        TextField(placeholder, text: Binding(
            get: { value ?? "" },
            set: { value = $0.isEmpty ? nil : $0 }
        ))
        .frame(width: 70)
        .textFieldStyle(.roundedBorder)
    }
}

private struct OptionalTempRow: View {
    let label: String
    @Binding var value: Double?

    var body: some View {
        HStack {
            Toggle(label, isOn: Binding(
                get: { value != nil },
                set: { value = $0 ? (value ?? 0) : nil }
            ))
            if value != nil {
                TextField("°C", value: Binding(get: { value ?? 0 }, set: { value = $0 }), format: .number)
                    .frame(width: 50).textFieldStyle(.roundedBorder)
            }
        }
    }
}

/// Mirrors `AppSettingsScreen` (v0.29.0's other half): how the app itself runs.
/// Login/Account is intentionally absent -- it needs a real network call
/// (`scraper.login()`), which is Tier 2 (a Python subcommand), not a file edit.
struct SettingsSheet: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var units = Box(Preferences.load().units)
    @StateObject private var language = Box(UserConfig.value("LANG") ?? "en")
    @StateObject private var theme = Box(UserConfig.value("THEME") ?? "catppuccin")
    @StateObject private var status = Box<String?>(nil)

    static let themes = ["catppuccin", "gruvbox", "tokyonight", "nord", "dracula",
                          "solarized-dark", "solarized-light", "green", "amber", "red-sands"]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Settings").font(.title2).bold().padding([.top, .horizontal], 16)
            Form {
                Section("Account") {
                    LabeledContent("pc caddie login") {
                        Text("Not available in this prototype yet").foregroundStyle(.secondary).font(.caption)
                    }
                }
                Section("Display") {
                    Picker("Units", selection: $units.value) {
                        Text("Metric").tag("metric"); Text("Imperial").tag("imperial")
                    }
                    Picker("Language", selection: $language.value) {
                        Text("English").tag("en"); Text("Deutsch").tag("de")
                    }
                    Picker("Theme", selection: $theme.value) {
                        ForEach(Self.themes, id: \.self) { Text($0.replacingOccurrences(of: "-", with: " ").capitalized).tag($0) }
                    }
                }
            }
            .formStyle(.grouped)

            HStack {
                if let status = status.value { Text(status).font(.caption).foregroundStyle(.secondary) }
                Spacer()
                Button("Cancel") { dismiss() }
                Button("Save") {
                    do {
                        // `units` round-trips through Preferences (same overlay-only-
                        // known-keys save() Tier 1's Preferences edits already use, so
                        // this can't clobber an availability/weather change made from
                        // the other sheet); theme/language are the plain config file.
                        var p = Preferences.load()
                        p.units = units.value
                        try p.save()
                        try UserConfig.setValue("THEME", theme.value)
                        try UserConfig.setValue("LANG", language.value)
                        // Honest, not aspirational: this prototype has no theming or
                        // localization system of its own yet -- Theme/Language are
                        // shared, global settings (see paths.py), so saving them here
                        // takes effect the next time the *TUI* opens, not this window.
                        status.value = "Saved — takes effect next time the terminal app opens"
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { dismiss() }
                    } catch {
                        status.value = "Couldn't save: \(error.localizedDescription)"
                    }
                }
                .keyboardShortcut(.defaultAction)
            }
            .padding(16)
        }
        .frame(width: 420, height: 320)
    }
}
