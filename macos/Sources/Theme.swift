import SwiftUI

/// Colors for the 10 themes `theme.py`'s own `ALL_THEME_NAMES` lists.
///
/// The three brew-launcher-original palettes (`green`/`amber`/`red-sands`) use the
/// **exact** hex values from `theme.py`'s own `CUSTOM_THEMES` dict — copied directly,
/// not approximated. The seven Textual built-ins (`catppuccin`/`gruvbox`/`tokyonight`/
/// `nord`/`dracula`/`solarized-dark`/`solarized-light`) aren't defined in this repo at
/// all — Textual's own theme registry owns them, which this Swift prototype has no
/// access to — so those seven use each palette's own well-known published colors
/// (Catppuccin Mocha, Gruvbox Dark, Tokyo Night, Nord, Dracula, Solarized) instead.
/// Close to what the TUI actually renders, not a byte-for-byte extraction of it.
struct ThemeColors {
    let accent: Color
    let background: Color
    let surface: Color
    let foreground: Color
    /// Drives `.preferredColorScheme` at the root of every window/sheet -- see
    /// `AppTheme`'s own docstring on the real bug this exists to fix (2026-09-19):
    /// plain `Color.secondary`/`.tertiary` resolve against the *system's* light/dark
    /// state, which can silently disagree with a *theme* that's the opposite (macOS
    /// in Dark Mode with the app set to solarized-light, say), making pips/dropdown
    /// text render with almost no contrast against this theme's own background.
    let isDark: Bool

    /// A muted/secondary tone derived from *this theme's own* foreground, not
    /// SwiftUI's system `Color.secondary` -- correct contrast against this theme's
    /// background by construction, unlike a system color that might be tuned for
    /// the opposite appearance. Used everywhere a `.secondary`-style tone used to
    /// be hardcoded (seat pips, muted labels).
    var muted: Color { foreground.opacity(0.6) }
    /// Same reasoning, dimmer still -- an "empty"/inactive indicator (an open seat
    /// pip, a heat-strip cell with no data).
    var faint: Color { foreground.opacity(0.18) }

    static let all: [String: ThemeColors] = [
        // --- Textual built-ins: each palette's own standard published colors ---
        "catppuccin": ThemeColors(accent: Color(hex: "#cba6f7"), background: Color(hex: "#1e1e2e"),
                                   surface: Color(hex: "#313244"), foreground: Color(hex: "#cdd6f4"), isDark: true),
        // Added 2026-09-19, direct feedback ("i would like to have more light
        // colored themes"): Catppuccin's own official light variant, "Latte" --
        // real published hex values (base/surface0/text/mauve), not an invented
        // approximation, mirroring the exact same field choices "catppuccin"
        // above already makes for Mocha (accent=mauve, background=base,
        // surface=surface0, foreground=text). See theme.py's matching
        // BUILTIN_THEME_MAP entry -- Textual already ships this theme by name,
        // nothing custom to register.
        "catppuccin-latte": ThemeColors(accent: Color(hex: "#8839ef"), background: Color(hex: "#eff1f5"),
                                         surface: Color(hex: "#ccd0da"), foreground: Color(hex: "#4c4f69"), isDark: false),
        "gruvbox": ThemeColors(accent: Color(hex: "#fabd2f"), background: Color(hex: "#282828"),
                                surface: Color(hex: "#3c3836"), foreground: Color(hex: "#ebdbb2"), isDark: true),
        "tokyonight": ThemeColors(accent: Color(hex: "#7aa2f7"), background: Color(hex: "#1a1b26"),
                                   surface: Color(hex: "#24283b"), foreground: Color(hex: "#c0caf5"), isDark: true),
        "nord": ThemeColors(accent: Color(hex: "#88c0d0"), background: Color(hex: "#2e3440"),
                             surface: Color(hex: "#3b4252"), foreground: Color(hex: "#eceff4"), isDark: true),
        "dracula": ThemeColors(accent: Color(hex: "#bd93f9"), background: Color(hex: "#282a36"),
                                surface: Color(hex: "#44475a"), foreground: Color(hex: "#f8f8f2"), isDark: true),
        "solarized-dark": ThemeColors(accent: Color(hex: "#268bd2"), background: Color(hex: "#002b36"),
                                       surface: Color(hex: "#073642"), foreground: Color(hex: "#eee8d5"), isDark: true),
        "solarized-light": ThemeColors(accent: Color(hex: "#268bd2"), background: Color(hex: "#fdf6e3"),
                                        surface: Color(hex: "#eee8d5"), foreground: Color(hex: "#073642"), isDark: false),
        // --- Exact hex values from theme.py's own CUSTOM_THEMES ---
        "green": ThemeColors(accent: Color(hex: "#33ff66"), background: Color(hex: "#000000"),
                              surface: Color(hex: "#114422"), foreground: Color(hex: "#33ff66"), isDark: true),
        "amber": ThemeColors(accent: Color(hex: "#ffbf00"), background: Color(hex: "#000000"),
                              surface: Color(hex: "#4d3800"), foreground: Color(hex: "#ffbf00"), isDark: true),
        "red-sands": ThemeColors(accent: Color(hex: "#e7b000"), background: Color(hex: "#7a251e"),
                                  surface: Color(hex: "#6e6e6e"), foreground: Color(hex: "#d7c9a7"), isDark: true),
    ]

    static let names = ["catppuccin", "catppuccin-latte", "gruvbox", "tokyonight", "nord", "dracula",
                         "solarized-dark", "solarized-light", "green", "amber", "red-sands"]
}

extension Color {
    init(hex: String) {
        var s = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        var v: UInt64 = 0
        Scanner(string: s).scanHexInt64(&v)
        if s.count < 6 { s = "000000" }
        self.init(.sRGB, red: Double((v >> 16) & 0xFF) / 255, green: Double((v >> 8) & 0xFF) / 255,
                  blue: Double(v & 0xFF) / 255, opacity: 1)
    }
}

/// The running app's current theme -- a singleton, not per-view `@State`/`@Observable`
/// (see `Box.swift` for why those specifically are off the table here), observed by
/// `@ObservedObject` wherever it needs to redraw. Read from `THEME=` at launch;
/// `SettingsSheet` updates `.name` directly on Save, and every subscriber redraws
/// immediately -- no relaunch, because nothing here is re-reading a file, it's a
/// `@Published` property the whole app already observes.
final class AppTheme: ObservableObject {
    static let shared = AppTheme()

    @Published var name: String {
        didSet { colors = ThemeColors.all[name] ?? ThemeColors.all["catppuccin"]! }
    }
    @Published private(set) var colors: ThemeColors

    private init() {
        let loaded = UserConfig.value("THEME") ?? "catppuccin"
        name = loaded
        colors = ThemeColors.all[loaded] ?? ThemeColors.all["catppuccin"]!
    }
}
