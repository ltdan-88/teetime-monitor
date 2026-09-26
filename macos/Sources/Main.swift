import SwiftUI

// The actual @main entry point, split out of App.swift (2026-09-26) so
// TeetimeMonitorCore -- the library target VisualRegressionRunner links
// against -- can include the rest of App.swift's real view code (DayCardHeader,
// SlotRow, ContentView, ...) without a second @main colliding with the test
// executable's own entry point. Everything in this file is layout-free (a
// Scene, not a View) -- nothing here is what visual regression checks.
@main
struct TeetimeMonitorApp: App {
    // The Actions menu's own titles go through t() too, and `.commands` is
    // evaluated as part of this scene's body -- so without observing the language
    // here, the menu would keep its launch-time wording after a change while the
    // window content re-rendered around it.
    @ObservedObject private var language = AppLanguage.shared

    var body: some Scene {
        WindowGroup("teetime-monitor") {
            ContentView(model: OverviewModel())
        }
        .defaultSize(width: 860, height: 680)
        .commands {
            // A real menu, not just a working shortcut -- see AppCommands' own
            // docstring for why this exists. A new top-level "Actions" menu (not
            // folded into an existing one) so these four are easy to find as a
            // group, next to the automatic View/Window menus SwiftUI already adds.
            CommandMenu(t("menu.actions")) {
                Button(t("menu.refresh")) { AppCommands.shared.onRefresh?() }
                    .keyboardShortcut("r", modifiers: .command)
                Button(t("menu.search")) { AppCommands.shared.onSearch?() }
                    .keyboardShortcut("f", modifiers: .command)
                Button(t("menu.add_club")) { AppCommands.shared.onAddClub?() }
                Button(t("menu.heatmap")) { AppCommands.shared.onHeatmap?() }
                // ⌥⌘← -- Finder's and Xcode's own shortcut for "collapse everything
                // in this outline", reused rather than picked arbitrarily.
                Button(t("menu.collapse_all")) { AppCommands.shared.onCollapseAll?() }
                    .keyboardShortcut(.leftArrow, modifiers: [.command, .option])
                Divider()
                Button(t("menu.preferences")) { AppCommands.shared.onPreferences?() }
                    .keyboardShortcut(",", modifiers: .command)
                Button(t("menu.settings")) { AppCommands.shared.onSettings?() }
            }
        }
    }
}
