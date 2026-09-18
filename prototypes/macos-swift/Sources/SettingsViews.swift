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
            // Genuinely true, not a hope: `_resolved_config()` (tui.py) calls
            // `global_preferences.load_preferences()` fresh, uncached, on every render
            // -- so a running TUI already picks up anything saved here on its very next
            // refresh (periodic or manual), with no restart and no need to even reopen
            // its own Settings screen. Worth saying explicitly since it isn't obvious
            // from the UI, and it's the one genuinely good answer in an otherwise
            // restart-required corner of this app (theme/language, see SettingsSheet).
            Text("Applies immediately -- a running terminal app picks this up on its next refresh, no restart needed.")
                .font(.caption2).foregroundStyle(.secondary)
                .padding(.horizontal, 16).padding(.top, 2)
            Form {
                Section("Availability") {
                    Stepper("Min open spots: \(prefs.value.minOpenSpots)", value: $prefs.value.minOpenSpots, in: 1...4)
                    TimeWindowRow(label: "Weekday", after: $prefs.value.weekdayAfter, before: $prefs.value.weekdayBefore)
                    TimeWindowRow(label: "Weekend", after: $prefs.value.weekendAfter, before: $prefs.value.weekendBefore)
                    Stepper("Buffer before: \(prefs.value.bufferBeforeMinutes) min", value: $prefs.value.bufferBeforeMinutes, in: 0...60, step: 5)
                    Stepper("Buffer after: \(prefs.value.bufferAfterMinutes) min", value: $prefs.value.bufferAfterMinutes, in: 0...60, step: 5)
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
                    Stepper("Daylight buffer: \(prefs.value.daylightBufferMinutes) min", value: $prefs.value.daylightBufferMinutes, in: 0...60, step: 5)
                    Stepper("9 holes: \(prefs.value.roundDurationNine) min", value: $prefs.value.roundDurationNine, in: 60...240, step: 15)
                    Stepper("18 holes: \(prefs.value.roundDurationEighteen) min", value: $prefs.value.roundDurationEighteen, in: 120...360, step: 15)
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
///
/// Login (2026-09-18, Tier 2's first piece) shells out to `teetime-monitor-login`
/// rather than reimplementing `scraper.login()` or `.env` writing here -- see
/// `LoginClient.swift`. It's its own Save button and status line, separate from the
/// Units/Language/Theme Save below, because it's a real network call with its own
/// async result, not a local file edit -- same reason `CredentialsScreen` is its own
/// screen in the TUI rather than a section of `AppSettingsScreen` there either.
struct SettingsSheet: View {
    /// The currently-selected club's platform id, so login can verify against a real
    /// pc caddie session the same way `ClubBrowserScreen.action_login()` does --
    /// `nil` on a fresh install with nothing saved yet, in which case the save still
    /// happens, just unverified (see `CredentialsScreen`'s own `verify_against_club_id`).
    let verifyClubID: String?

    @Environment(\.dismiss) private var dismiss
    @StateObject private var units = Box(Preferences.load().units)
    @StateObject private var language = Box(UserConfig.value("LANG") ?? "en")
    // Seeded from the shared instance, not UserConfig directly, so this always starts
    // on whatever the app is actually showing right now -- matters the second time
    // this sheet opens in one session, after a theme change already happened live.
    @StateObject private var theme = Box(AppTheme.shared.name)
    @StateObject private var status = Box<String?>(nil)

    // Username is prefilled (not secret); password never is -- same rule
    // CredentialsScreen documents: a blank password on save means "keep what's
    // already there," so there's never a need to display or retype one that works.
    @StateObject private var loginUsername = Box(EnvStore.currentUsername() ?? "")
    @StateObject private var loginPassword = Box("")
    @StateObject private var isLoggingIn = Box(false)
    @StateObject private var loginStatus = Box<String?>(nil)

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Settings").font(.title2).bold().padding([.top, .horizontal], 16)
            Form {
                Section {
                    TextField("Username", text: $loginUsername.value)
                    SecureField(EnvStore.hasSavedPassword() ? "Password (unchanged)" : "Password",
                                text: $loginPassword.value)
                    HStack {
                        if let loginStatus = loginStatus.value {
                            Text(loginStatus).font(.caption2).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if isLoggingIn.value { ProgressView().controlSize(.small) }
                        Button("Save login") {
                            isLoggingIn.value = true
                            loginStatus.value = nil
                            LoginClient.run(username: loginUsername.value, password: loginPassword.value,
                                             clubID: verifyClubID) { result, error in
                                isLoggingIn.value = false
                                if let result {
                                    loginStatus.value = result.statusText
                                    // Never linger in the field once it's written --
                                    // re-entering this sheet always starts blank
                                    // again, same as CredentialsScreen's own reset.
                                    if result.saved { loginPassword.value = "" }
                                } else {
                                    loginStatus.value = error ?? "Something went wrong."
                                }
                            }
                        }
                        .disabled(isLoggingIn.value
                                  || loginUsername.value.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                } header: {
                    Text("pc caddie login")
                } footer: {
                    Text(verifyClubID == nil
                         ? "Saved either way; pick a club above to also verify it against pc caddie on save."
                         : "Verified live against pc caddie for the selected club when you save.")
                        .font(.caption2)
                }
                // Units lives in preferences.yaml, so like everything in PreferencesSheet
                // it's live in a running terminal app on its next refresh -- no restart.
                // Theme/language are the plain config file instead, and `i18n.py` caches
                // `_current_language` once per process (`get_language()`: resolved on
                // first call, then never re-read) while `club_config.py` calls
                // `load_dotenv()` once at import time -- so unlike units, those two
                // genuinely need the terminal app restarted, not just reopened, to see a
                // change made here. Verified directly against src/i18n.py and
                // src/tui.py's `_resolved_config()` rather than assumed.
                Section {
                    Picker("Units", selection: $units.value) {
                        Text("Metric").tag("metric"); Text("Imperial").tag("imperial")
                    }
                } header: {
                    Text("Display")
                } footer: {
                    Text("Applies immediately, same as Preferences -- no restart needed.")
                        .font(.caption2)
                }
                Section {
                    Picker("Language", selection: $language.value) {
                        Text("English").tag("en"); Text("Deutsch").tag("de")
                    }
                    Picker("Theme", selection: $theme.value) {
                        ForEach(ThemeColors.names, id: \.self) { Text($0.replacingOccurrences(of: "-", with: " ").capitalized).tag($0) }
                    }
                } header: {
                    Text("Terminal app")
                } footer: {
                    Text("Theme applies here immediately. Both of these only reach the terminal app the next time you restart it -- it caches them once at launch and won't notice a change while running, even if you reopen its own Settings screen.")
                        .font(.caption2)
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
                        // Applies immediately, no relaunch: AppTheme.shared is the
                        // same instance ContentView/DayCard observe via
                        // @ObservedObject, so this @Published assignment is what
                        // actually redraws the running window -- persisting to
                        // UserConfig above only makes it survive to the *next*
                        // launch, it doesn't by itself change anything on screen.
                        AppTheme.shared.name = theme.value
                        // Language is still config-file-only: this prototype has no
                        // localization system of its own yet, so that half genuinely
                        // only takes effect next time the *TUI* restarts.
                        status.value = "Units & theme applied. Theme/language reach the terminal app on its next restart."
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { dismiss() }
                    } catch {
                        status.value = "Couldn't save: \(error.localizedDescription)"
                    }
                }
                .keyboardShortcut(.defaultAction)
            }
            .padding(16)
        }
        .frame(width: 440, height: 500)
    }
}
