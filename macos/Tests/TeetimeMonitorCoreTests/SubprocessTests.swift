import Foundation
@testable import TeetimeMonitorCore

func runSubprocessTests() {
    Harness.group("Subprocess") {
        testLargeOutputDoesNotDeadlock()
        testStdinAndStderr()
        testJSONAfterLogLines()
        testPreviewParseIgnoresLogLines()
        testSearchParse()
    }
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
