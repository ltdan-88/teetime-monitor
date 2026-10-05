import Foundation

/// One finished child process: its exit status and everything it wrote.
struct SubprocessResult {
    let status: Int32
    let stdout: Data
    let stderr: Data

    var stderrText: String { String(data: stderr, encoding: .utf8) ?? "" }
}

/// Runs one of the `teetime-monitor-*` console scripts to completion -- the shared
/// shape every `*Client` here uses. stdout and stderr are both read *while* the
/// child runs: the clients used to call `waitUntilExit()` first and read after, and
/// a child that writes more than the ~64 KB pipe buffer (a "Reset filters" search
/// over a summer week is ~65-70 KB of JSON) blocked in write() while this side
/// blocked in wait, forever.
enum Subprocess {
    /// Blocking -- call it from a background queue. Throws only when the process
    /// can't be started at all.
    static func run(_ executable: String, _ arguments: [String], stdin: Data? = nil) throws -> SubprocessResult {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: executable)
        task.arguments = arguments
        let outPipe = Pipe(), errPipe = Pipe()
        task.standardOutput = outPipe
        task.standardError = errPipe
        let inPipe = stdin.map { _ in Pipe() }
        task.standardInput = inPipe ?? FileHandle.nullDevice
        try task.run()

        let group = DispatchGroup()
        var errData = Data()
        DispatchQueue.global(qos: .utility).async(group: group) {
            errData = errPipe.fileHandleForReading.readDataToEndOfFile()
        }
        if let stdin, let inPipe {
            // Written off this thread too, so a child that answers before it has
            // read all of its input can't wedge the two of us either.
            DispatchQueue.global(qos: .utility).async(group: group) {
                inPipe.fileHandleForWriting.write(stdin)
                try? inPipe.fileHandleForWriting.close()
            }
        }
        let outData = outPipe.fileHandleForReading.readDataToEndOfFile()
        group.wait()
        task.waitUntilExit()
        return SubprocessResult(status: task.terminationStatus, stdout: outData, stderr: errData)
    }

    /// The JSON object a script printed as its result: the whole of stdout, or
    /// else its last non-empty line. A script whose library code logs with a plain
    /// `print()` (scrape_once's `_log`) puts those lines ahead of the JSON, and
    /// parsing all of stdout then failed on a run that had worked.
    static func jsonObject(from stdout: Data) -> Any? {
        if let whole = try? JSONSerialization.jsonObject(with: stdout) { return whole }
        guard let text = String(data: stdout, encoding: .utf8),
              let last = text.split(whereSeparator: \.isNewline).last(where: {
                  !$0.trimmingCharacters(in: .whitespaces).isEmpty
              }),
              let data = String(last).data(using: .utf8) else { return nil }
        return try? JSONSerialization.jsonObject(with: data)
    }
}
