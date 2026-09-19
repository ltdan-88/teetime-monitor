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
    /// Range chosen to be unmistakable at a glance: the first attempt leaned on
    /// `dynamicTypeSize`, which does nothing on macOS, and "no visible change" is
    /// exactly the failure this must not repeat. 0.85/1.3 moves a 10pt caption
    /// between roughly 9pt and 13pt.
    var factor: CGFloat {
        switch self {
        case .small: return 0.85
        case .medium: return 1.0
        case .large: return 1.3
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
        option = AppScaleOption(rawValue: UserConfig.value("GUI_SCALE") ?? "") ?? .medium
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

/// Every hardcoded dimension this app lays out with, in one place at its `.medium`
/// size -- so a row's own column widths are defined once, next to each other, rather
/// than as a dozen bare numbers scattered across `App.swift` where nothing said
/// which ones were supposed to line up with which. Multiply through
/// `AppScale.shared.scaled(...)` at the use site.
enum Metrics {
    // Slot row columns
    static let slotTime: CGFloat = 42
    static let slotTemp: CGFloat = 24
    static let slotPrecip: CGFloat = 34
    static let slotWind: CGFloat = 30
    static let seatPip: CGFloat = 9
    // Day card
    static let chevron: CGFloat = 10
    static let heatBlockWidth: CGFloat = 13
    static let heatBlockHeight: CGFloat = 7
    static let freshnessDot: CGFloat = 6
    // Reserved regardless of whether a day actually has a booking -- see the
    // booking-badge slot in DayCard's header. Fixed rather than sized to its own
    // content so HeatStrip lands at the same x on every row; sized for the widest
    // real value ("HH:MM" plus the flag icon and its padding), not just "wide enough".
    static let bookingBadge: CGFloat = 74
    // Toolbar
    static let picker: CGFloat = 230
    // Heatmap grid
    static let heatCellWidth: CGFloat = 18
    static let heatCellHeight: CGFloat = 13
    static let heatHourLabel: CGFloat = 40
    static let legendSwatchWidth: CGFloat = 14
    static let legendSwatchHeight: CGFloat = 11
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
    /// Criteria on the left, results on the right: Search only. Added
    /// 2026-09-19, direct follow-up on the sheet-width trim above ("would it
    /// make sense to place search results on the right instead? ... the
    /// results don't need that much width") -- unlike Add a Club, here the
    /// list is a *comparison* against the criteria beside it, and each result
    /// row is genuinely narrow (a time, a weather icon, an open-spot count,
    /// a chevron), so it doesn't need Add a Club's full-width list treatment.
    ///
    /// 760, widened from a first attempt at 680 that shipped broken: with the
    /// criteria column pinned to a hardcoded 340 (a guess at Form's own real
    /// per-row overhead, not measured), its longest German row didn't fit and
    /// `Form`'s grouped style clipped each label's own *leading* characters
    /// rather than wrapping or truncating -- reported live with a screenshot.
    /// The criteria column now sizes itself to its own natural content width
    /// instead (see SearchSheet's own `.fixedSize` comment), so this number
    /// only has to be wide enough to comfortably fit that natural width *plus*
    /// a real results column with room to spare -- generous on purpose, since
    /// guessing too narrow is what broke it the first time and this
    /// environment can't self-verify rendered layout to catch a repeat.
    ///
    /// Height trimmed from 640 to 540, direct report, 2026-09-19 ("search
    /// screen has too much height"): the criteria column's own natural height
    /// (five form rows plus the Search button) is well under 640, and the
    /// results List's own `.frame(maxHeight: .infinity)` was stretching to
    /// fill that leftover space rather than shrinking to it -- kept a bit
    /// taller than the heatmap sheet below on purpose, since unlike a fixed
    /// grid, more results genuinely benefit from more visible rows before
    /// scrolling.
    static let split = CGSize(width: 760, height: 540)
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
