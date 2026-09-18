import SwiftUI

/// How large the whole interface renders -- direct request, 2026-09-18 ("maybe
/// offer different scales (e.g. small, medium, large)").
///
/// Two halves, because neither alone is enough:
///
/// - **Text** scales through SwiftUI's own `dynamicTypeSize` environment value.
///   Every view in this app already uses *semantic* fonts (`.caption2`, `.headline`,
///   `.title2`...) rather than hardcoded point sizes, so setting that one
///   environment value at the root scales all of it correctly, with no per-view
///   change and no `.scaleEffect` blurriness.
/// - **Fixed pixel frames** (the 42pt time column, the 9pt seat pips, the heat-strip
///   blocks -- see `Metrics` below) can't follow `dynamicTypeSize` on their own, and
///   would clip larger text or leave gaps around smaller text. Those multiply by
///   `factor` instead.
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

    /// `.medium` maps to `.large`, which is macOS's *own* default Dynamic Type size
    /// -- so "Medium" means "exactly what every other Mac app shows", not a shrunken
    /// middle setting, and an install that never touches this looks unchanged.
    var dynamicTypeSize: DynamicTypeSize {
        switch self {
        case .small: return .small
        case .medium: return .large
        case .large: return .xxLarge
        }
    }

    /// Multiplier for hardcoded pixel dimensions. Deliberately gentler than the text
    /// ramp above: these are mostly small indicators (pips, heat blocks) where a
    /// proportional jump would dominate a row rather than match it.
    var factor: CGFloat {
        switch self {
        case .small: return 0.88
        case .medium: return 1.0
        case .large: return 1.22
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
    var dynamicTypeSize: DynamicTypeSize { option.dynamicTypeSize }

    /// Scale a hardcoded pixel dimension. Rounded so a scaled frame still lands on a
    /// whole point -- half-point frames make adjacent columns disagree about their
    /// own edges, which reads as misalignment rather than as a smaller size.
    func scaled(_ value: CGFloat) -> CGFloat { (value * factor).rounded() }
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
    /// A form of settings controls: Preferences, Settings.
    static let form = CGSize(width: 480, height: 560)
    /// A form plus a result list: Search, Add a Club.
    static let browser = CGSize(width: 620, height: 640)
    /// Wide data display: the heatmap's two grids.
    static let wide = CGSize(width: 720, height: 640)
}

extension View {
    /// Apply one of `SheetSize`'s standard sizes, scaled, *and* the matching text
    /// scale. Every sheet in this app ends with this instead of its own literal
    /// `.frame(width:height:)`.
    ///
    /// The `dynamicTypeSize` half is set here rather than relied on from
    /// `ContentView`'s root: a `.sheet`'s content is presented in its own window,
    /// and doesn't reliably inherit environment modifiers attached to the
    /// presenting view *after* the `.sheet` modifier itself. Setting it at each
    /// sheet is what makes a scale change actually reach them too, instead of
    /// leaving every sheet at the system default while the main window scales.
    func sheetFrame(_ size: CGSize) -> some View {
        let scale = AppScale.shared
        return frame(width: scale.scaled(size.width), height: scale.scaled(size.height))
            .environment(\.dynamicTypeSize, scale.dynamicTypeSize)
    }
}
