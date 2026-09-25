// The regression suite for TeetimeMonitorCore -- run with `swift run
// TeetimeMonitorCoreTests` (or `swift test`, which SPM maps onto this since there's
// no real `.testTarget`; see Package.swift for why). Exits 1 on any failure, so it
// can gate CI the same way `pytest` already gates the Python side.

runUnitsTests()
runYAMLTests()
runCalendarContextTests()
runAnalyticsTests()
runPreferencesStoreTests()
runUserConfigStoreTests()
runStoreTests()
runClubDirectoryStoreTests()
runI18nTests()
runScaleTests()
runLoginClientTests()
runSearchClientTests()
runFormattingTests()

Harness.summarizeAndExit()
