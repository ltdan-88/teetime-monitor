import SwiftUI

/// How large the whole interface renders -- direct request, 2026-09-18 ("maybe
/// offer different scales (e.g. small, medium, large)").
///
/// Two halves, both driven by the same `factor`:
///
/// - **Text**, via `scaledFont()` -- an explicitly-sized `Font`, because macOS has
///   no Dynamic Type and ignores `dynamicTypeSize` for semantic fonts (see
///   `TextRole` for the bug that taught us this the hard way).
/// - **Fixed pixel dimensions** (the 42pt time column, the 9pt seat pips, the
///   heat-strip blocks -- see `Metrics`), which would otherwise clip larger text or
///   strand smaller text.
///
/// Persisted as `GUI_SCALE=` in the same `~/.config/teetime-monitor/config` file
/// `THEME=`/`LANG=` already live in. Safe to add a GUI-only key there: Python's own
/// `user_config.save_value()` rewrites only the key it's given and leaves "every
/// other line untouched" (its own docstring), so this survives the TUI writing a
/// theme or language, and the TUI ignores a key it doesn't read.
enum AppScaleOption: String, CaseIterable {
    case small, medium, large

    var label: String {
        switch self {
        case .small: return "Small"
        case .medium: return "Medium"
        case .large: return "Large"
        }
    }

    /// Drives both halves of the scale -- font point sizes (`scaledFont`) and
    /// hardcoded pixel dimensions (`Metrics`) -- so text and the indicators beside
    /// it stay in proportion rather than drifting apart at the extremes.
    ///
    /// Shifted up a notch, direct request, 2026-09-19 ("make old large scale new
    /// medium scale, old medium is now small, large needs to be extra large"):
    /// the whole original 0.85/1.0/1.3 range read as too subtle end to end --
    /// what used to be Medium (1.0, effectively "no change") is now Small, what
    /// used to be Large (1.3) is now Medium, and the new Large is a genuinely
    /// bigger step up (1.6) rather than repeating the old ceiling under a new
    /// name. The old 0.85 tier is gone outright -- nothing in the request asked
    /// for a fourth, even-smaller tier, and three meaningfully different sizes
    /// reads better than four where the bottom one barely differs from the one
    /// above it. Enum case names/raw values (`small`/`medium`/`large`, what
    /// `GUI_SCALE=` actually persists) are unchanged, so this doesn't need its
    /// own migration -- only what each one *means* moved.
    var factor: CGFloat {
        switch self {
        case .small: return 1.0
        case .medium: return 1.3
        case .large: return 1.6
        }
    }
}

/// The running app's current scale -- a singleton observed via `@ObservedObject`
/// wherever it needs to redraw, exactly the shape `AppTheme` already uses (see
/// `Theme.swift`), and for the same reason: a `@Published` change on one shared
/// instance is what makes the whole window re-lay-out immediately on Save, with no
/// relaunch and nothing re-reading a file.
final class AppScale: ObservableObject {
    static let shared = AppScale()

    @Published var option: AppScaleOption

    private init() {
        // .small, not .medium -- .small is the tier whose factor is exactly 1.0
        // now (see AppScaleOption.factor's own docstring on the 2026-09-19
        // reshuffle), so this is what keeps a fresh install looking unchanged,
        // the same property .medium used to hold before that request moved
        // which tier means "no scaling" at all.
        option = AppScaleOption(rawValue: UserConfig.value("GUI_SCALE") ?? "") ?? .small
    }

    var factor: CGFloat { option.factor }

    /// Scale a hardcoded pixel dimension. Rounded so a scaled frame still lands on a
    /// whole point -- half-point frames make adjacent columns disagree about their
    /// own edges, which reads as misalignment rather than as a smaller size.
    func scaled(_ value: CGFloat) -> CGFloat { (value * factor).rounded() }
}

/// The text styles this app uses, with their real macOS point sizes.
///
/// **Why this exists at all**: the first version of the scale feature set
/// SwiftUI's `dynamicTypeSize` environment value and assumed semantic fonts
/// (`.caption2`, `.title2`...) would follow it. That is iOS behaviour. macOS has no
/// Dynamic Type -- `.body` is 13pt whatever that environment value says -- so
/// scaling appeared to do nothing at all, which is exactly what got reported
/// ("Scale changes don't seem to change any font size"). Scaling on macOS has to
/// compute the point size itself, which means every `.font()` call site names a
/// role here instead of a bare semantic font.
enum TextRole {
    case title2, headline, body, subheadline, caption, caption2

    /// macOS's own sizes for these styles. `caption`/`caption2` are both nominally
    /// 10pt on macOS; kept one point apart here so the hierarchy this app actually
    /// relies on (a 10pt caption2 detail under an 11pt caption label) stays visible.
    var size: CGFloat {
        switch self {
        case .title2: return 17
        case .headline: return 13
        case .body: return 13
        case .subheadline: return 11
        case .caption: return 11
        case .caption2: return 10
        }
    }

    var weight: Font.Weight { self == .headline ? .semibold : .regular }
}

/// One scaled font. A free function rather than a method on a per-view `scale`
/// property so a call site is a drop-in replacement for `.font(.caption2)` and
/// doesn't require every small view to hold its own `@ObservedObject` -- the views
/// that own the layout (`ContentView`, `DayCard`, and each sheet) observe
/// `AppScale.shared`, and re-rendering them recreates these child views with the
/// new size.
func scaledFont(_ role: TextRole, design: Font.Design = .default) -> Font {
    .system(size: (role.size * AppScale.shared.factor).rounded(),
            weight: role.weight, design: design)
}

/// Every hardcoded dimension this app lays out with, in one place at its
/// unscaled (1.0x, `.small` since the 2026-09-19 scale reshuffle -- see
/// `AppScaleOption.factor`'s own docstring) size -- so a row's own column
/// widths are defined once, next to each other, rather than as a dozen bare
/// numbers scattered across `App.swift` where nothing said which ones were
/// supposed to line up with which. Multiply through `AppScale.shared.scaled(...)`
/// at the use site.
enum Metrics {
    // Slot row columns
    static let slotTime: CGFloat = 42
    static let slotTemp: CGFloat = 24
    // Widened from 34 -- direct report, 2026-09-19 ("precipitation amount in mm
    // seems to still be missing"): this cell now shows "70%/1.5mm", not just
    // "70%" (mirrors tui._slot_precipitation_cell()'s own "%{mm}" combination),
    // and 34 was sized for the probability alone.
    // 56 still wrapped "63%/0.5mm" (esp. with the 🌧 flag) onto two lines, making
    // those rows taller than their neighbours; 78 fits it, and the cell is also
    // lineLimit(1) so it can never grow a row again.
    static let slotPrecip: CGFloat = 78
    static let slotWind: CGFloat = 30
    // A slot/search-result row's own per-time condition icon, before the
    // temperature column -- direct audit, 2026-09-26, following the day-card
    // header's identical bug (see Metrics.dayCondition): this icon had no
    // fixed width either, so the temp/precip/wind columns after it drifted
    // left/right by row depending on which weather glyph that specific time
    // happened to show. Narrower than Metrics.dayCondition (20) since both
    // real call sites (SlotRow, SearchResultRow) render this at .caption/
    // .caption2 size, smaller than the day header's own unscaled icon.
    static let slotCondition: CGFloat = 16
    static let seatPip: CGFloat = 9
    // Day card
    static let chevron: CGFloat = 10
    // Collapsed day-card header's own summary row -- direct report, 2026-09-26
    // ("icons, temperatures, wind, sunrise/sunset times etc. are not always
    // aligned between the different days"): every field here used to size to
    // its own content, so one day's wider condition icon (a fog/rain glyph vs.
    // a plain cloud, say) or a temperature/wind reading with more digits shoved
    // everything after it sideways relative to the row above and below. Same
    // fixed-column fix `SlotRow` already uses for its own time/temp/precip/wind
    // cells, applied here for the same reason -- sized for the widest plausible
    // value in German (the longer of the two languages this app ships), not
    // just "wide enough" for today's real data.
    static let dayWeekday: CGFloat = 96
    static let dayCondition: CGFloat = 20
    static let dayTemp: CGFloat = 64
    static let dayRain: CGFloat = 46
    static let dayWind: CGFloat = 36
    static let daySun: CGFloat = 98
    static let heatBlockWidth: CGFloat = 13
    static let heatBlockHeight: CGFloat = 7
    static let freshnessDot: CGFloat = 6
    // Reserved regardless of whether a day actually has a booking -- see the
    // booking-badge slot in DayCard's header. Fixed rather than sized to its own
    // content so HeatStrip lands at the same x on every row; sized for the widest
    // real value ("HH:MM" plus the flag icon and its padding), not just "wide enough".
    static let bookingBadge: CGFloat = 74
    // Heatmap grid
    static let heatCellWidth: CGFloat = 18
    static let heatCellHeight: CGFloat = 13
    static let heatHourLabel: CGFloat = 40
    static let legendSwatchWidth: CGFloat = 14
    static let legendSwatchHeight: CGFloat = 11
    // Player directory row (2026-09-27, direct request: "make the layout fit all
    // contents at a glance"). Each sized for the widest plausible real value, not
    // just today's data -- same reasoning as the day-card-header columns above. Name
    // is by far the widest: "Bettina Brauch-Hasenmaier"/"Dr. med. Philipp Dalheimer"
    // (this club's own real directory, checked directly) both comfortably fit in
    // 260, with real margin for a longer one still. Gender/member-status are sized
    // for German ("Unbekannt"/"Mitglied"), the longer of the two languages this app
    // ships, matching every other fixed column's own stated convention. The trailing
    // friend button is deliberately *not* fixed-width here -- nothing follows it on
    // the row, so a per-row/per-language width difference there can't misalign
    // anything the way a mid-row column's own width would.
    static let playerName: CGFloat = 260
    static let playerGender: CGFloat = 70
    static let playerMemberStatus: CGFloat = 70
    static let playerHandicap: CGFloat = 46
}

/// One standard size per sheet *kind*, rather than the five different hand-picked
/// (width, height) pairs this prototype had accumulated -- 460x560, 440x500,
/// 640x680, 560x560, 700x620, no two alike and none of them chosen for a reason that
/// outlived the sheet being written. Sheets that do the same kind of job now open at
/// the same size, and all of them grow with the chosen scale.
enum SheetSize {
    // Widths trimmed 2026-09-19, direct report ("Search, heatmap, add club,
    // Preferences and settings screen are too wide"): none of these were ever
    // measured against what their own content actually needs -- e.g. the
    // heatmap's widest real grid (7 weekday columns at Metrics.heatCellWidth
    // plus the hour-label column) comes to roughly 260pt, nowhere near the
    // 720pt it had. Reduced to comfortably fit each sheet's real content
    // (including the longest German field labels, which is what actually
    // drives `form`) rather than picking a smaller number arbitrarily.
    /// A form of settings controls: Preferences, Settings.
    static let form = CGSize(width: 460, height: 560)
    /// A form plus a result list, stacked: Add a Club (the list is the thing
    /// being searched *for*, so it takes the full width once results appear).
    static let browser = CGSize(width: 520, height: 640)
    /// Wide data display: the heatmap's two grids, side by side (2026-09-19 on)
    /// with a fixed-footer legend rather than stacked.
    ///
    /// Height trimmed from 640 to 500, same direct report as `split` above,
    /// with a screenshot this time showing roughly 300pt of pure blank space
    /// between the last grid row and the legend footer: side-by-side grids
    /// are much shorter than the stacked layout this height was originally
    /// picked for (a season's worth of operating hours, ~14 rows, comes to
    /// roughly 350pt total including both header rows and padding), and nothing
    /// was resizing the ScrollView above the fixed footer down to match.
    static let wide = CGSize(width: 560, height: 500)
    /// The player directory (2026-09-27, direct request: "make the layout fit all
    /// contents at a glance (make screen wider if no other option)") -- wider than
    /// every other sheet on purpose: it's the one screen in this app with a fixed
    /// name/gender/status/handicap/friend-button row, and `.browser`'s 520 wasn't
    /// picked with that row in mind. Sized as the sum of `Metrics.playerName` +
    /// `.playerGender` + `.playerMemberStatus` + `.playerHandicap` plus inter-column
    /// spacing, padding, and room for the trailing friend button's own longest real
    /// label ("Als Freund/in markieren") -- not a round number chosen by eye.
    static let directory = CGSize(width: 700, height: 640)
}

extension View {
    /// Apply one of `SheetSize`'s standard sizes, scaled, *and* force this sheet's
    /// own color scheme to match the chosen theme rather than the system's. Every
    /// sheet in this app ends with this instead of its own literal
    /// `.frame(width:height:)`. The text-scale half needs nothing here -- each
    /// sheet's own `.font(scaledFont(...))` call sites already read the current
    /// scale.
    ///
    /// The color-scheme half is here for the same reason `sheetFrame` already
    /// carries the scale environment instead of relying on inheritance from
    /// `ContentView`'s root: a `.sheet`'s content is its own window and doesn't
    /// reliably inherit modifiers from the presenting view. Without it, a sheet
    /// opened while running a light theme under a Dark Mode system (or vice versa)
    /// renders `Color.secondary`/`.tertiary`/native control chrome for the *wrong*
    /// appearance -- confirmed as the cause of a real visibility bug reported
    /// live (dropdowns and seat pips unreadable under solarized-light).
    func sheetFrame(_ size: CGSize) -> some View {
        let scale = AppScale.shared
        let isDark = AppTheme.shared.colors.isDark
        return frame(width: scale.scaled(size.width), height: scale.scaled(size.height))
            .preferredColorScheme(isDark ? .dark : .light)
    }
}
