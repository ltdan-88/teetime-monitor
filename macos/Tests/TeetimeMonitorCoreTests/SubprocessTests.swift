import Foundation
@testable import TeetimeMonitorCore

func runSubprocessTests() {
    Harness.group("Subprocess") {
        testLargeOutputDoesNotDeadlock()
        testStdinAndStderr()
        testJSONAfterLogLines()
        testPreviewParseIgnoresLogLines()
        testSearchParse()
        testTimeoutKillsTheChild()
        testSigtermIgnoringChildIsKilled()
        testFastRunUnderTimeoutIsUntouched()
        testCancelTerminatesTheChild()
        testCancelBeforeStartAndAfterFinish()
        testLargeOutputStillDrainedWithATimeout()
        testEarlyExitWithLargeStdinDoesNotCrash()
        testOrphanHoldingThePipesDoesNotHangTheRun()
        testCandidateDirectoryOrder()
        testLocateOrder()
        testResolveHonoursTheOverrideAndCaches()
        testBundledBinDirectory()
        testBundledHelpersComeFirst()
        testTimeoutMessages()
    }
}

/// Runs `body` off the main thread and returns its elapsed seconds, or nil if it did not
/// finish within `limit` (a hang -- the thing these tests exist to catch).
private func timed(limit: TimeInterval = 20, _ body: @escaping () -> Void) -> TimeInterval? {
    let done = DispatchSemaphore(value: 0)
    let start = Date()
    DispatchQueue.global().async { body(); done.signal() }
    return done.wait(timeout: .now() + limit) == .success ? Date().timeIntervalSince(start) : nil
}

private func errorOf(_ body: () throws -> Any) -> SubprocessError? {
    do { _ = try body(); return nil } catch { return error as? SubprocessError }
}

private func testTimeoutKillsTheChild() {
    var error: SubprocessError?
    let elapsed = timed { error = errorOf { try Subprocess.run("/bin/sleep", ["30"], timeout: 0.4) } }
    Harness.checkEqual("a sleeping child times out", error, .timedOut(after: 0.4))
    Harness.check("...promptly, not after the sleep", (elapsed ?? 99) < 8)
}

/// SIGTERM ignored (inherited across exec): only the SIGKILL after the grace ends it.
private func testSigtermIgnoringChildIsKilled() {
    var error: SubprocessError?
    let elapsed = timed {
        error = errorOf {
            try Subprocess.run("/bin/sh", ["-c", "trap '' TERM; exec /bin/sleep 30"], timeout: 0.4, killGrace: 0.3)
        }
    }
    Harness.checkEqual("a SIGTERM-proof child still times out", error, .timedOut(after: 0.4))
    Harness.check("...killed after the grace", (elapsed ?? 99) < 8)
}

private func testFastRunUnderTimeoutIsUntouched() {
    let result = try? Subprocess.run("/bin/sh", ["-c", "echo hi"], timeout: 10)
    Harness.checkEqual("a fast child is unaffected by its timeout", result.map { String(decoding: $0.stdout, as: UTF8.self) }, "hi\n")
}

private func testCancelTerminatesTheChild() {
    let handle = SubprocessHandle()
    var error: SubprocessError?
    DispatchQueue.global().asyncAfter(deadline: .now() + 0.4) { handle.cancel() }
    let elapsed = timed { error = errorOf { try Subprocess.run("/bin/sleep", ["30"], handle: handle) } }
    Harness.checkEqual("cancel ends a running child with .cancelled", error, .cancelled)
    Harness.check("...promptly", (elapsed ?? 99) < 8)
    Harness.check("the handle reports it", handle.isCancelled)
}

private func testCancelBeforeStartAndAfterFinish() {
    let early = SubprocessHandle()
    early.cancel()
    Harness.checkEqual("a handle cancelled before the run never starts the child",
                       errorOf { try Subprocess.run("/bin/sleep", ["30"], handle: early) }, .cancelled)
    let late = SubprocessHandle()
    let result = try? Subprocess.run("/bin/sh", ["-c", "exit 0"], handle: late)
    Harness.checkEqual("a finished run is a normal result", result?.status, 0)
    late.cancel()  // must not crash or signal a reaped pid
    Harness.check("cancel after the fact is a no-op", late.isCancelled)
}

private func testLargeOutputStillDrainedWithATimeout() {
    var result: SubprocessResult?
    let elapsed = timed { result = try? Subprocess.run("/bin/sh", ["-c", "yes a | head -c 400000"], timeout: 15) }
    Harness.check("finishes", elapsed != nil)
    Harness.checkEqual("all 400 KB read under a timeout and a handle-less run", result?.stdout.count, 400_000)
}

/// A child that exits without reading 4 MB of stdin: the write gets EPIPE. Without a
/// non-signalling write that is a SIGPIPE, which kills the process -- this one included.
private func testEarlyExitWithLargeStdinDoesNotCrash() {
    var result: SubprocessResult?
    let payload = Data(repeating: 0x61, count: 4_000_000)
    let elapsed = timed { result = try? Subprocess.run("/bin/sh", ["-c", "exit 7"], stdin: payload, timeout: 15) }
    Harness.check("an early-exiting child neither hangs nor kills us", elapsed != nil)
    Harness.checkEqual("its status comes back", result?.status, 7)
    // And through the process-wide setting Main.swift installs.
    signal(SIGPIPE, SIG_IGN)
    result = nil
    _ = timed { result = try? Subprocess.run("/bin/sh", ["-c", "exit 0"], stdin: payload, timeout: 15) }
    Harness.checkEqual("still fine with SIGPIPE ignored", result?.status, 0)
}

/// `sh -c 'sleep 3 & exit 0'`: the orphan inherits stdout/stderr, so EOF only arrives
/// when it exits. The run must come back after the drain grace, not wait for it.
private func testOrphanHoldingThePipesDoesNotHangTheRun() {
    var result: SubprocessResult?
    let elapsed = timed { result = try? Subprocess.run("/bin/sh", ["-c", "echo out; sleep 3 & exit 0"], drainGrace: 0.3) }
    Harness.checkEqual("status of the wrapper", result?.status, 0)
    Harness.checkEqual("what it printed before", result.map { String(decoding: $0.stdout, as: UTF8.self) }, "out\n")
    Harness.check("returns before the orphan finishes", (elapsed ?? 99) < 2.5)
}

private func testCandidateDirectoryOrder() {
    Harness.checkEqual("override, Homebrew (arm, Intel), then uv's ~/.local/bin",
                       Subprocess.candidateDirectories(override: "/o", home: "/h"),
                       ["/o", "/opt/homebrew/bin", "/usr/local/bin", "/h/.local/bin"])
    Harness.checkEqual("no override",
                       Subprocess.candidateDirectories(override: nil, home: "/h"),
                       ["/opt/homebrew/bin", "/usr/local/bin", "/h/.local/bin"])
}

private func makeExecutable(_ dir: String, _ name: String) -> String {
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    let path = (dir as NSString).appendingPathComponent(name)
    FileManager.default.createFile(atPath: path, contents: Data("#!/bin/sh\n".utf8), attributes: [.posixPermissions: 0o755])
    return path
}

private func testLocateOrder() {
    let root = NSTemporaryDirectory() + "tm-locate-\(UUID().uuidString)"
    defer { try? FileManager.default.removeItem(atPath: root) }
    let a = root + "/a", b = root + "/b", c = root + "/c"
    let first = makeExecutable(b, "tm-fake"), second = makeExecutable(c, "tm-fake")
    var whichCalls = 0
    let which: (String) -> String? = { _ in whichCalls += 1; return "/from/which" }
    Harness.checkEqual("the earliest directory wins", Subprocess.locate("tm-fake", directories: [a, b, c], which: which), first)
    try? FileManager.default.removeItem(atPath: first)
    Harness.checkEqual("then the next", Subprocess.locate("tm-fake", directories: [a, b, c], which: which), second)
    Harness.checkEqual("which is not consulted on a hit", whichCalls, 0)
    Harness.checkEqual("which is the single fallback", Subprocess.locate("tm-other", directories: [a, b, c], which: which), "/from/which")
    Harness.checkEqual("...asked once", whichCalls, 1)
    // A non-executable file is not a hit.
    let plain = root + "/d/tm-plain"
    try? FileManager.default.createDirectory(atPath: root + "/d", withIntermediateDirectories: true)
    FileManager.default.createFile(atPath: plain, contents: Data(), attributes: [.posixPermissions: 0o644])
    Harness.check("a non-executable file is skipped", Subprocess.locate("tm-plain", directories: [root + "/d"], which: { _ in nil }) == nil)
}

private func testResolveHonoursTheOverrideAndCaches() {
    let dir = NSTemporaryDirectory() + "tm-resolve-\(UUID().uuidString)"
    defer { unsetenv(Subprocess.binDirVariable); try? FileManager.default.removeItem(atPath: dir) }
    let name = "tm-resolve-\(UUID().uuidString.prefix(8))"
    Subprocess.resetResolveCache()
    Harness.check("unknown before the override", Subprocess.resolve(name) == nil)
    let path = makeExecutable(dir, name)
    setenv(Subprocess.binDirVariable, dir, 1)
    Harness.checkEqual("TEETIME_MONITOR_BIN_DIR is looked in first", Subprocess.resolve(name), path)
    // A real helper name the override dir doesn't have still resolves the normal way (or nil).
    unsetenv(Subprocess.binDirVariable)
    // The directory part of the cache: a binary found by the normal search is remembered.
    let tool = Subprocess.resolve("sh")
    Harness.check("which finds a PATH tool as the last fallback", tool != nil)
    Harness.checkEqual("and the answer is stable (cached)", Subprocess.resolve("sh"), tool)
}

/// The standalone app (2026-10-10): `<Resources>/bin` is looked in right after the developer
/// override and before Homebrew; a bundle without one changes nothing.
private func testBundledBinDirectory() {
    Harness.checkEqual("the bundled bin comes after the override, before Homebrew",
                       Subprocess.candidateDirectories(override: "/o", bundledBin: "/b", home: "/h"),
                       ["/o", "/b", "/opt/homebrew/bin", "/usr/local/bin", "/h/.local/bin"])
    Harness.checkEqual("no bundled bin: the old order",
                       Subprocess.candidateDirectories(override: nil, bundledBin: nil, home: "/h"),
                       ["/opt/homebrew/bin", "/usr/local/bin", "/h/.local/bin"])
    let root = NSTemporaryDirectory() + "tm-bundle-\(UUID().uuidString)"
    defer { try? FileManager.default.removeItem(atPath: root) }
    try? FileManager.default.createDirectory(atPath: root, withIntermediateDirectories: true)
    Harness.check("no nil resource URL, no bundled bin", Subprocess.bundledBinDirectory(resourceURL: nil) == nil)
    Harness.check("a Resources without bin has none", Subprocess.bundledBinDirectory(resourceURL: URL(fileURLWithPath: root)) == nil)
    FileManager.default.createFile(atPath: root + "/bin", contents: Data(), attributes: nil)
    Harness.check("a plain file named bin is not a directory", Subprocess.bundledBinDirectory(resourceURL: URL(fileURLWithPath: root)) == nil)
    try? FileManager.default.removeItem(atPath: root + "/bin")
    try? FileManager.default.createDirectory(atPath: root + "/bin", withIntermediateDirectories: true)
    Harness.checkEqual("a Resources with bin/ names it", Subprocess.bundledBinDirectory(resourceURL: URL(fileURLWithPath: root)),
                       URL(fileURLWithPath: root).appendingPathComponent("bin").path)
}

private func testBundledHelpersComeFirst() {
    let root = NSTemporaryDirectory() + "tm-bundled-\(UUID().uuidString)"
    let override = root + "/override"
    let resources = URL(fileURLWithPath: root + "/App.app/Contents/Resources")
    defer { unsetenv(Subprocess.binDirVariable); Subprocess.resetResolveCache(); try? FileManager.default.removeItem(atPath: root) }
    // A name nothing else on this machine has, so a Homebrew/PATH hit cannot confuse the order.
    let name = "tm-bundled-\(UUID().uuidString.prefix(8))"
    unsetenv(Subprocess.binDirVariable)
    Subprocess.resetResolveCache()
    Harness.check("no bundle, nothing installed: unresolved", Subprocess.resolve(name, resourceURL: nil) == nil)
    Harness.check("an absent bundle bin falls back (still unresolved here)", Subprocess.resolve(name, resourceURL: resources) == nil)

    let bundled = makeExecutable(resources.path + "/bin", name)
    Subprocess.resetResolveCache()
    Harness.checkEqual("the bundled launcher is found", Subprocess.resolve(name, resourceURL: resources), bundled)
    Subprocess.resetResolveCache()
    Harness.check("another bundle's launcher is not", Subprocess.resolve(name, resourceURL: URL(fileURLWithPath: root + "/Other")) == nil)

    let overridden = makeExecutable(override, name)
    setenv(Subprocess.binDirVariable, override, 1)
    Harness.checkEqual("TEETIME_MONITOR_BIN_DIR beats the bundled one", Subprocess.resolve(name, resourceURL: resources), overridden)
    // An override directory without the helper does not hide the bundled one.
    setenv(Subprocess.binDirVariable, root + "/empty", 1)
    Subprocess.resetResolveCache()
    Harness.checkEqual("an override lacking the name falls through to the bundle", Subprocess.resolve(name, resourceURL: resources), bundled)
    // A bundled bin directory that lacks this script still falls back to the old search (`which`).
    unsetenv(Subprocess.binDirVariable)
    Subprocess.resetResolveCache()
    Harness.checkEqual("bundled bin without the script: the PATH fallback", Subprocess.resolve("sh", resourceURL: resources) != nil, true)
}

private func testTimeoutMessages() {
    AppLanguage.shared.code = "en"
    Harness.checkEqual("timeout message", SubprocessError.timedOut(after: 60).errorDescription, "Timed out after 60 s — try again.")
    Harness.check("cancel message", SubprocessError.cancelled.errorDescription?.isEmpty == false)
}

/// More than the ~64 KB pipe buffer on stdout *and* stderr: waiting for exit before
/// reading hung forever here (a "Reset filters" search over a summer week).
private func testLargeOutputDoesNotDeadlock() {
    let done = DispatchSemaphore(value: 0)
    var result: SubprocessResult?
    DispatchQueue.global().async {
        result = try? Subprocess.run("/bin/sh", ["-c", "yes a | head -c 300000; yes b | head -c 200000 >&2"])
        done.signal()
    }
    let finished = done.wait(timeout: .now() + 20) == .success
    Harness.check("finishes instead of hanging", finished)
    Harness.checkEqual("all of stdout read", result?.stdout.count, 300_000)
    Harness.checkEqual("all of stderr read", result?.stderr.count, 200_000)
    Harness.checkEqual("exit status", result?.status, 0)
}

private func testStdinAndStderr() {
    let result = try? Subprocess.run("/bin/sh", ["-c", "cat; echo oops >&2; exit 3"], stdin: Data("{\"a\": 1}".utf8))
    Harness.checkEqual("stdin reaches the child", result.map { String(decoding: $0.stdout, as: UTF8.self) }, "{\"a\": 1}")
    Harness.checkEqual("stderr captured", result?.stderrText, "oops\n")
    Harness.checkEqual("exit status kept", result?.status, 3)
    Harness.check("a missing executable throws", (try? Subprocess.run("/nonexistent/x", [])) == nil)
}

private func testJSONAfterLogLines() {
    let out = Data("[2026-10-04T10:00:00] [scrape_once] weather fetch failed: timeout\n{\"ok\": true}\n\n".utf8)
    Harness.checkEqual("the last line is the result", (Subprocess.jsonObject(from: out) as? [String: Any])?["ok"] as? Bool, true)
    Harness.check("whole-stdout JSON still parses", Subprocess.jsonObject(from: Data("[1, 2]".utf8)) is [Any])
    Harness.check("no JSON at all", Subprocess.jsonObject(from: Data("just a log line\n".utf8)) == nil)
}

/// scrape_once's `_log()` prints best-effort failures to stdout ahead of the
/// result; the preview worked and must not be reported as "preview failed (exit 0)".
private func testPreviewParseIgnoresLogLines() {
    let ok = SubprocessResult(status: 0, stdout: Data("[ts] [scrape_once] None/A/2026-10-05 failed: timeout\n{\"ok\": true}\n".utf8),
                              stderr: Data())
    Harness.check("a logged warning doesn't fail the preview", PreviewClient.parse(ok) == nil)
    let broken = SubprocessResult(status: 1, stdout: Data(), stderr: Data("Traceback".utf8))
    Harness.checkEqual("stderr surfaces on a real failure", PreviewClient.parse(broken), "Traceback")
}

private func testSearchParse() {
    let rows = SubprocessResult(status: 0, stdout: Data(#"[{"date": "2026-10-05", "course": "A", "time": "09:10", "booked": 1, "capacity": 4, "players": [], "score": 0.5, "reasons": []}]"#.utf8), stderr: Data())
    let (matches, error) = SearchClient.parse(rows)
    Harness.checkEqual("one match", matches?.count, 1)
    Harness.check("no error", error == nil)
    let failed = SubprocessResult(status: 0, stdout: Data(#"{"error": "no such course"}"#.utf8), stderr: Data())
    Harness.checkEqual("error object", SearchClient.parse(failed).1, "no such course")
}
