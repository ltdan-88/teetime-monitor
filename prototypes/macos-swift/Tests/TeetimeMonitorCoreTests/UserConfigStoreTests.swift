import Foundation
@testable import TeetimeMonitorCore

func runUserConfigStoreTests() {
    Harness.group("UserConfig") {
        testSetAndGet()
        testUnrelatedKeysUntouched()
        testNoBlankLineGrowth()
    }
}

private func testSetAndGet() {
    let dir = TempDir()
    setenv("TEETIME_MONITOR_CONFIG_DIR", dir.path, 1)
    defer { unsetenv("TEETIME_MONITOR_CONFIG_DIR") }

    try! UserConfig.setValue("THEME", "catppuccin")
    Harness.checkEqual("value reads back", UserConfig.value("THEME"), "catppuccin")

    try! UserConfig.setValue("THEME", "gruvbox")
    Harness.checkEqual("value updates in place", UserConfig.value("THEME"), "gruvbox")
    Harness.checkEqual("missing key returns nil", UserConfig.value("NOPE"), nil)
}

private func testUnrelatedKeysUntouched() {
    let dir = TempDir()
    setenv("TEETIME_MONITOR_CONFIG_DIR", dir.path, 1)
    defer { unsetenv("TEETIME_MONITOR_CONFIG_DIR") }

    try! "THEME=catppuccin\nLANG=en\nLAST_CLUB_ID=0497758\n".write(
        toFile: UserConfig.path(), atomically: true, encoding: .utf8)
    try! UserConfig.setValue("GUI_SCALE", "large")

    Harness.checkEqual("THEME survives", UserConfig.value("THEME"), "catppuccin")
    Harness.checkEqual("LANG survives", UserConfig.value("LANG"), "en")
    Harness.checkEqual("a key this app never reads survives", UserConfig.value("LAST_CLUB_ID"), "0497758")
    Harness.checkEqual("new key was actually added", UserConfig.value("GUI_SCALE"), "large")
}

/// The real bug: splitting a trailing-newline-terminated string with
/// `omittingEmptySubsequences: false` produces a trailing empty element Python's own
/// `splitlines()` never does -- missing that grew the file by one blank line on
/// every single write. Caught originally by writing the same key 5 times and
/// diffing the byte count; pinned here the same way so it can't come back silently.
private func testNoBlankLineGrowth() {
    let dir = TempDir()
    setenv("TEETIME_MONITOR_CONFIG_DIR", dir.path, 1)
    defer { unsetenv("TEETIME_MONITOR_CONFIG_DIR") }

    try! UserConfig.setValue("THEME", "catppuccin")
    let firstSize = (try! FileManager.default.attributesOfItem(atPath: UserConfig.path())[.size] as! Int)

    for i in 0..<5 {
        try! UserConfig.setValue("THEME", i % 2 == 0 ? "gruvbox" : "nord")
    }
    let laterSize = (try! FileManager.default.attributesOfItem(atPath: UserConfig.path())[.size] as! Int)

    // Both values are 7 characters ("gruvbox"/"catppuccin" differ in length, so
    // compare against a fixed final value instead of the first write's size).
    try! UserConfig.setValue("THEME", "catppuccin")
    let finalSize = (try! FileManager.default.attributesOfItem(atPath: UserConfig.path())[.size] as! Int)
    Harness.checkEqual("file size stable across repeated writes of the same value",
                        finalSize, firstSize)
    _ = laterSize

    let text = try! String(contentsOfFile: UserConfig.path(), encoding: .utf8)
    let lineCount = text.split(separator: "\n", omittingEmptySubsequences: false).count
    Harness.checkEqual("exactly one line plus the trailing empty split artifact", lineCount, 2)
}
