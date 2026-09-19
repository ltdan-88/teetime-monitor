import SwiftUI

/// The hour/minute preset lists `settings_screen.py`'s own `HOUR_CHOICES`/
/// `MINUTE_CHOICES` define -- "--" (unset) plus 05-21 for the hour, "--" plus
/// 00/15/30/45 for the minute. See that file's own docstring for why the hour
/// range stops well short of the full clock (no golf club is open at 2am).
enum TimeChoices {
    static let hours: [Int] = Array(5...21)
    static let minutes: [Int] = [0, 15, 30, 45]
}

/// A dropdown over a fixed integer preset list that also keeps an out-of-list
/// current value selectable -- the same rule `settings_screen.py`'s own `compose()`
/// applies to every one of its preset `Select` widgets ("an existing config with a
/// value outside this list still loads and stays selectable"), so a value saved by
/// hand, by an older preset list, or by this app's own pre-dropdown Stepper era
/// doesn't silently vanish the moment this ships.
///
/// Direct request, 2026-09-19: "can you please change the time entries into
/// dropdowns? other entries (e.g. empty slots, rain etc.) also would probably be
/// quicker to interact with if they were dropdowns instead." Applied only to the
/// fields that actually have a real Python preset list behind them (min open
/// spots, the two buffers, the daylight buffer, both round durations) -- the
/// weather thresholds (rain %/mm, wind kph, temp above/below) stay Steppers, since
/// `settings_screen.py` itself deliberately keeps those as free-form
/// `optional_float` fields ("a rain probability threshold could legitimately be
/// any value 0-100, not a small fixed preset" -- that module's own docstring).
struct IntChoicePicker: View {
    let choices: [Int]
    @Binding var value: Int
    /// `""` for a bare number (min open spots); `" min"` for every duration/buffer
    /// field -- mirrors `_int_choices`' own `f"{v} min" if v else "0"` formatting.
    var suffix: String = ""

    private var options: [Int] {
        choices.contains(value) ? choices : (choices + [value]).sorted()
    }

    private func label(_ v: Int) -> String {
        suffix.isEmpty || v == 0 ? "\(v)" : "\(v)\(suffix)"
    }

    var body: some View {
        Picker("", selection: $value) {
            ForEach(options, id: \.self) { Text(label($0)).tag($0) }
        }
        .labelsHidden()
    }
}

/// Mirrors `PreferencesScreen` (v0.29.0's split): what makes a good tee time *for
/// you*. Reads/writes the same `preferences.yaml` directly -- see
/// `PreferencesStore.swift` for the verified round-trip with Python.
struct PreferencesSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var language = AppLanguage.shared
    @StateObject private var prefs = Box(Preferences.load())
    @StateObject private var status = Box<String?>(nil)

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(t("prefs.title")).font(scaledFont(.title2)).bold().padding([.top, .horizontal], 16)
            // Genuinely true, not a hope: `_resolved_config()` (tui.py) calls
            // `global_preferences.load_preferences()` fresh, uncached, on every render
            // -- so a running TUI already picks up anything saved here on its very next
            // refresh (periodic or manual), with no restart and no need to even reopen
            // its own Settings screen. Worth saying explicitly since it isn't obvious
            // from the UI, and it's the one genuinely good answer in an otherwise
            // restart-required corner of this app (theme/language, see SettingsSheet).
            Text(t("prefs.live_note"))
                .font(scaledFont(.caption2)).foregroundStyle(.secondary)
                .padding(.horizontal, 16).padding(.top, 2)
            Form {
                Section(t("prefs.section.availability")) {
                    HStack {
                        Text(t("prefs.min_open_spots_label"))
                        Spacer()
                        IntChoicePicker(choices: [1, 2, 3, 4], value: $prefs.value.minOpenSpots)
                    }
                    TimeWindowRow(label: t("prefs.weekday"), after: $prefs.value.weekdayAfter, before: $prefs.value.weekdayBefore)
                    TimeWindowRow(label: t("prefs.weekend"), after: $prefs.value.weekendAfter, before: $prefs.value.weekendBefore)
                    HStack {
                        Text(t("prefs.buffer_before_label"))
                        Spacer()
                        IntChoicePicker(choices: [0, 10, 20, 30, 40, 50, 60], value: $prefs.value.bufferBeforeMinutes, suffix: " min")
                    }
                    HStack {
                        Text(t("prefs.buffer_after_label"))
                        Spacer()
                        IntChoicePicker(choices: [0, 10, 20, 30, 40, 50, 60], value: $prefs.value.bufferAfterMinutes, suffix: " min")
                    }
                }
                Section(t("prefs.section.weather")) {
                    Toggle(t("prefs.avoid_rain"), isOn: $prefs.value.avoidRain)
                    if prefs.value.avoidRain {
                        Stepper(t("prefs.above_percent", ["n": "\(Int(prefs.value.avoidRainProbabilityPercent))"]),
                                value: $prefs.value.avoidRainProbabilityPercent, in: 0...100, step: 5)
                        Stepper(t("prefs.above_mm", ["n": String(format: "%.1f", prefs.value.avoidRainMM)]),
                                value: $prefs.value.avoidRainMM, in: 0...10, step: 0.5)
                    }
                    Toggle(t("prefs.avoid_wind"), isOn: $prefs.value.avoidWind)
                    if prefs.value.avoidWind {
                        Stepper(t("prefs.above_kph", ["n": "\(Int(prefs.value.avoidWindKPH))"]), value: $prefs.value.avoidWindKPH, in: 0...80, step: 5)
                    }
                    OptionalTempRow(label: t("prefs.avoid_below"), value: $prefs.value.avoidTempBelowC)
                    OptionalTempRow(label: t("prefs.avoid_above"), value: $prefs.value.avoidTempAboveC)
                }
                Section(t("prefs.section.pace")) {
                    HStack {
                        Text(t("prefs.daylight_buffer_label"))
                        Spacer()
                        IntChoicePicker(choices: [0, 15, 30, 45, 60, 90], value: $prefs.value.daylightBufferMinutes, suffix: " min")
                    }
                    HStack {
                        Text(t("prefs.nine_holes_label"))
                        Spacer()
                        IntChoicePicker(choices: [60, 75, 90, 105, 120, 135, 150, 165, 180], value: $prefs.value.roundDurationNine, suffix: " min")
                    }
                    HStack {
                        Text(t("prefs.eighteen_holes_label"))
                        Spacer()
                        IntChoicePicker(choices: [150, 180, 210, 240, 270, 300, 330], value: $prefs.value.roundDurationEighteen, suffix: " min")
                    }
                }
                Section(t("prefs.section.priorities")) {
                    Toggle(t("prefs.prioritize_friends"), isOn: $prefs.value.prioritizeFriends)
                }
            }
            .formStyle(.grouped)

            HStack {
                if let status = status.value { Text(status).font(scaledFont(.caption)).foregroundStyle(.secondary) }
                Spacer()
                Button(t("button.cancel")) { dismiss() }
                Button(t("button.save")) {
                    do {
                        try prefs.value.save()
                        status.value = t("prefs.saved")
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { dismiss() }
                    } catch {
                        status.value = t("prefs.save_failed", ["error": error.localizedDescription])
                    }
                }
                .keyboardShortcut(.defaultAction)
            }
            .padding(16)
        }
        .sheetFrame(SheetSize.form)
    }
}

// Not private -- SearchSheet.swift reuses this row unchanged for its own
// weekday/weekend window fields, same "pre-filled from your saved defaults, edit
// for this one case" fields the TUI's own SearchScreen shares with its Preferences
// screen (see that class's own docstring).
struct TimeWindowRow: View {
    @ObservedObject private var language = AppLanguage.shared
    let label: String
    @Binding var after: String?
    @Binding var before: String?

    var body: some View {
        HStack {
            // 120, not the original 70 -- direct report, 2026-09-19, with a
            // screenshot showing "Am Wochenende" ("Unter der Woche"'s own 15
            // characters is the longer of the two German labels this row ever
            // shows) wrapping mid-*word* into three lines because 70pt isn't wide
            // enough even for one word of it. 120 comfortably fits both German
            // labels on one line at every scale this app offers.
            Text(label).frame(width: 120, alignment: .leading)
            Spacer()
            // The two time pickers as their own trailing group, not flush against
            // the label -- matches every other field in this form (a label on the
            // left, its control pinned to the trailing edge via a Spacer), which
            // this row didn't previously do; same report flagged the result as
            // visually inconsistent with the rows around it.
            HStack(spacing: 4) {
                OptionalTimeField(placeholder: t("prefs.after"), value: $after)
                Text("–")
                OptionalTimeField(placeholder: t("prefs.before"), value: $before)
            }
        }
    }
}

/// Hour + ":" + minute, each its own dropdown -- not the free-text "17:00" field
/// this used to be. Direct request, 2026-09-19 ("change the time entries into
/// dropdowns"); mirrors settings_screen.py's own "optional_time" compose() branch
/// exactly, including its two behaviours: "--" (an empty hour) means "not set" and
/// blanks the whole value, and choosing an hour with no minute chosen yet collapses
/// to :00 rather than being a second, redundant way to mean "not set". An
/// out-of-list value already saved (hand-edited YAML, or the pre-05:00 range this
/// prototype used to accept via free text) stays loaded and selectable, same as
/// every other IntChoicePicker on this screen.
struct OptionalTimeField: View {
    let placeholder: String
    @Binding var value: String?

    private var hourPart: String { value.map { String($0.prefix(2)) } ?? "" }
    private var minutePart: String { value.map { String($0.suffix(2)) } ?? "" }

    private var hourOptions: [String] {
        let base = TimeChoices.hours.map { String(format: "%02d", $0) }
        return hourPart.isEmpty || base.contains(hourPart) ? base : ([hourPart] + base)
    }
    private var minuteOptions: [String] {
        let base = TimeChoices.minutes.map { String(format: "%02d", $0) }
        return minutePart.isEmpty || base.contains(minutePart) ? base : ([minutePart] + base)
    }

    private var hour: Binding<String> {
        Binding(
            get: { hourPart },
            set: { newHour in
                value = newHour.isEmpty ? nil : "\(newHour):\(minutePart.isEmpty ? "00" : minutePart)"
            }
        )
    }
    private var minute: Binding<String> {
        Binding(
            get: { minutePart },
            set: { newMinute in
                guard !hourPart.isEmpty else { return }
                value = "\(hourPart):\(newMinute.isEmpty ? "00" : newMinute)"
            }
        )
    }

    var body: some View {
        HStack(spacing: 2) {
            Picker("", selection: hour) {
                Text("--").tag("")
                ForEach(hourOptions, id: \.self) { Text($0).tag($0) }
            }
            .labelsHidden().frame(width: 62)
            Text(":")
            Picker("", selection: minute) {
                Text("--").tag("")
                ForEach(minuteOptions, id: \.self) { Text($0).tag($0) }
            }
            .labelsHidden().frame(width: 62)
        }
        .help(placeholder)
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
    @ObservedObject private var uiLanguage = AppLanguage.shared
    @StateObject private var units = Box(Preferences.load().units)
    @StateObject private var language = Box(UserConfig.value("LANG") ?? "en")
    // Seeded from the shared instance, not UserConfig directly, so this always starts
    // on whatever the app is actually showing right now -- matters the second time
    // this sheet opens in one session, after a theme change already happened live.
    @StateObject private var theme = Box(AppTheme.shared.name)
    @StateObject private var scaleOption = Box(AppScale.shared.option)
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
            Text(t("settings.title")).font(scaledFont(.title2)).bold().padding([.top, .horizontal], 16)
            Form {
                Section {
                    TextField(t("settings.username"), text: $loginUsername.value)
                    SecureField(EnvStore.hasSavedPassword() ? t("settings.password_unchanged") : t("settings.password"),
                                text: $loginPassword.value)
                    HStack {
                        if let loginStatus = loginStatus.value {
                            Text(loginStatus).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if isLoggingIn.value { ProgressView().controlSize(.small) }
                        Button(t("settings.save_login")) {
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
                                    loginStatus.value = error ?? t("error.generic")
                                }
                            }
                        }
                        .disabled(isLoggingIn.value
                                  || loginUsername.value.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                } header: {
                    Text(t("settings.section.login"))
                } footer: {
                    Text(verifyClubID == nil
                         ? t("settings.login_footer_no_club")
                         : t("settings.login_footer_club"))
                        .font(scaledFont(.caption2))
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
                    Picker(t("settings.units"), selection: $units.value) {
                        Text(t("settings.metric")).tag("metric"); Text(t("settings.imperial")).tag("imperial")
                    }
                    Picker(t("settings.scale"), selection: $scaleOption.value) {
                        ForEach(AppScaleOption.allCases, id: \.self) { Text(t("settings.scale.\($0.rawValue)")).tag($0) }
                    }
                    // Lives here, not under "Terminal app", because it now changes
                    // *this* app's own interface too -- see I18n.swift. It still
                    // also writes LANG= for the TUI, which picks it up on its next
                    // restart (hence the mention in that section's footer).
                    Picker(t("settings.language"), selection: $language.value) {
                        ForEach(I18n.supported, id: \.self) { Text(I18n.label($0)).tag($0) }
                    }
                } header: {
                    Text(t("settings.section.display"))
                } footer: {
                    Text(t("settings.display_footer"))
                        .font(scaledFont(.caption2))
                }
                Section {
                    Picker(t("settings.theme"), selection: $theme.value) {
                        ForEach(ThemeColors.names, id: \.self) { Text($0.replacingOccurrences(of: "-", with: " ").capitalized).tag($0) }
                    }
                } header: {
                    Text(t("settings.section.terminal"))
                } footer: {
                    Text(t("settings.terminal_footer"))
                        .font(scaledFont(.caption2))
                }
            }
            .formStyle(.grouped)

            HStack {
                if let status = status.value { Text(status).font(scaledFont(.caption)).foregroundStyle(.secondary) }
                Spacer()
                Button(t("button.cancel")) { dismiss() }
                Button(t("button.save")) {
                    do {
                        // `units` round-trips through Preferences (same overlay-only-
                        // known-keys save() Tier 1's Preferences edits already use, so
                        // this can't clobber an availability/weather change made from
                        // the other sheet); theme/language are the plain config file.
                        var p = Preferences.load()
                        p.units = units.value
                        try p.save()
                        // Persisting alone changed nothing on screen before this --
                        // the app saved `units` correctly and then never read it
                        // back (see Units.swift). This is the line that actually
                        // reformats every temperature and wind speed on screen.
                        AppUnits.shared.value = units.value
                        AppLanguage.shared.code = language.value
                        try UserConfig.setValue("THEME", theme.value)
                        try UserConfig.setValue("LANG", language.value)
                        // Applies immediately, no relaunch: AppTheme.shared is the
                        // same instance ContentView/DayCard observe via
                        // @ObservedObject, so this @Published assignment is what
                        // actually redraws the running window -- persisting to
                        // UserConfig above only makes it survive to the *next*
                        // launch, it doesn't by itself change anything on screen.
                        AppTheme.shared.name = theme.value
                        try UserConfig.setValue("GUI_SCALE", scaleOption.value.rawValue)
                        AppScale.shared.option = scaleOption.value
                        // Language is still config-file-only: this prototype has no
                        // localization system of its own yet, so that half genuinely
                        // only takes effect next time the *TUI* restarts.
                        status.value = t("settings.applied")
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { dismiss() }
                    } catch {
                        status.value = t("prefs.save_failed", ["error": error.localizedDescription])
                    }
                }
                .keyboardShortcut(.defaultAction)
            }
            .padding(16)
        }
        .sheetFrame(SheetSize.form)
    }
}
