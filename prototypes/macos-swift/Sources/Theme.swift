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

    static let all: [String: ThemeColors] = [
        // --- Textual built-ins: each palette's own standard published colors ---
        "catppuccin": ThemeColors(accent: Color(hex: "#cba6f7"), background: Color(hex: "#1e1e2e"),
                                   surface: Color(hex: "#313244"), foreground: Color(hex: "#cdd6f4")),
        "gruvbox": ThemeColors(accent: Color(hex: "#fabd2f"), background: Color(hex: "#282828"),
                                surface: Color(hex: "#3c3836"), foreground: Color(hex: "#ebdbb2")),
        "tokyonight": ThemeColors(accent: Color(hex: "#7aa2f7"), background: Color(hex: "#1a1b26"),
                                   surface: Color(hex: "#24283b"), foreground: Color(hex: "#c0caf5")),
        "nord": ThemeColors(accent: Color(hex: "#88c0d0"), background: Color(hex: "#2e3440"),
                             surface: Color(hex: "#3b4252"), foreground: Color(hex: "#eceff4")),
        "dracula": ThemeColors(accent: Color(hex: "#bd93f9"), background: Color(hex: "#282a36"),
                                surface: Color(hex: "#44475a"), foreground: Color(hex: "#f8f8f2")),
        "solarized-dark": ThemeColors(accent: Color(hex: "#268bd2"), background: Color(hex: "#002b36"),
                                       surface: Color(hex: "#073642"), foreground: Color(hex: "#eee8d5")),
        "solarized-light": ThemeColors(accent: Color(hex: "#268bd2"), background: Color(hex: "#fdf6e3"),
                                        surface: Color(hex: "#eee8d5"), foreground: Color(hex: "#073642")),
        // --- Exact hex values from theme.py's own CUSTOM_THEMES ---
        "green": ThemeColors(accent: Color(hex: "#33ff66"), background: Color(hex: "#000000"),
                              surface: Color(hex: "#114422"), foreground: Color(hex: "#33ff66")),
        "amber": ThemeColors(accent: Color(hex: "#ffbf00"), background: Color(hex: "#000000"),
                              surface: Color(hex: "#4d3800"), foreground: Color(hex: "#ffbf00")),
        "red-sands": ThemeColors(accent: Color(hex: "#e7b000"), background: Color(hex: "#7a251e"),
                                  surface: Color(hex: "#6e6e6e"), foreground: Color(hex: "#d7c9a7")),
    ]

    static let names = ["catppuccin", "gruvbox", "tokyonight", "nord", "dracula",
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
