import Foundation

/// One finished child process: its exit status and everything it wrote.
struct SubprocessResult {
    let status: Int32
    let stdout: Data
    let stderr: Data

    var stderrText: String { String(data: stderr, encoding: .utf8) ?? "" }
}

/// Why a run ended without a result (2026-10-05). Distinct from "the child failed" (a
/// `SubprocessResult` with a non-zero status) and from "couldn't start" (the launch error).
enum SubprocessError: Error, Equatable, LocalizedError {
    /// The per-call timeout elapsed; the child was sent SIGTERM, then SIGKILL after a grace.
    case timedOut(after: TimeInterval)
    /// `SubprocessHandle.cancel()` was called: a newer request superseded this one.
    case cancelled

    var errorDescription: String? {
        switch self {
        case .timedOut(let seconds): return t("error.timed_out", ["seconds": String(Int(seconds.rounded()))])
        case .cancelled: return t("error.cancelled")
        }
    }
}

/// Cooperative cancellation for one `Subprocess.run`: a newer request for the same purpose
/// cancels the in-flight one, which terminates the child (SIGTERM, then SIGKILL after the
/// grace) instead of letting a stale run finish. One handle per run; cancel() is safe from
/// any thread, at any time (before the child starts, while it runs, after it finished).
final class SubprocessHandle {
    private let lock = NSLock()
    private var task: Process?
    private var grace: TimeInterval = Subprocess.defaultKillGrace
    private var cancelledFlag = false

    var isCancelled: Bool { lock.lock(); defer { lock.unlock() }; return cancelledFlag }

    func cancel() {
        lock.lock(); cancelledFlag = true; let running = task; let grace = grace; lock.unlock()
        if let running { Subprocess.terminate(running, grace: grace) }
    }

    fileprivate func attach(_ process: Process, grace: TimeInterval) {
        lock.lock(); task = process; self.grace = grace; let already = cancelledFlag; lock.unlock()
        if already { Subprocess.terminate(process, grace: grace) }
    }
}

/// Runs one of the `teetime-monitor-*` console scripts to completion -- the shared
/// shape every `*Client` here uses. stdout and stderr are both read *while* the
/// child runs: the clients used to call `waitUntilExit()` first and read after, and
/// a child that writes more than the ~64 KB pipe buffer (a "Reset filters" search
/// over a summer week is ~65-70 KB of JSON) blocked in write() while this side
/// blocked in wait, forever.
enum Subprocess {
    /// Per-caller timeouts (2026-10-05): generous for the real work, short enough that a
    /// wedged helper (a stalled pc caddie fetch) frees its button/spinner.
    enum Timeout {
        static let picks: TimeInterval = 60
        static let search: TimeInterval = 90
        static let preview: TimeInterval = 120
        static let login: TimeInterval = 30
        static let aiVerify: TimeInterval = 30
        static let scrape: TimeInterval = 300
        /// Not in the original list: a live authenticated directory fetch / a geocoding lookup.
        static let directory: TimeInterval = 60
        static let addClub: TimeInterval = 60
    }

    /// SIGTERM, then SIGKILL this long after if the child is still alive.
    static let defaultKillGrace: TimeInterval = 2
    /// After the child exited, how long to wait for its pipes to reach EOF. A grandchild
    /// that inherited them (a shell wrapper's orphan) can hold them open long after the
    /// child is gone; the output read so far is used and the readers are left to finish.
    static let defaultDrainGrace: TimeInterval = 2

    /// Blocking -- call it from a background queue. Throws when the process can't be
    /// started at all, or `SubprocessError` for a timeout/cancel.
    /// `timeout` nil means no limit. A SIGPIPE from a child that exits without reading its
    /// stdin can't kill this process: the stdin write end is set not to signal (macOS
    /// F_SETNOSIGPIPE) and the write's EPIPE is simply ignored -- see also Main.swift.
    static func run(_ executable: String, _ arguments: [String], stdin: Data? = nil,
                    timeout: TimeInterval? = nil, handle: SubprocessHandle? = nil,
                    killGrace: TimeInterval = defaultKillGrace,
                    drainGrace: TimeInterval = defaultDrainGrace) throws -> SubprocessResult {
        if handle?.isCancelled == true { throw SubprocessError.cancelled }
        let task = Process()
        task.executableURL = URL(fileURLWithPath: executable)
        task.arguments = arguments
        let outPipe = Pipe(), errPipe = Pipe()
        task.standardOutput = outPipe
        task.standardError = errPipe
        let inPipe = stdin.map { _ in Pipe() }
        if let inPipe { _ = fcntl(inPipe.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1) }
        task.standardInput = inPipe ?? FileHandle.nullDevice
        let exited = DispatchSemaphore(value: 0)
        task.terminationHandler = { _ in exited.signal() }
        try task.run()
        // Our copy of the child's stdin read end must go, or a child that exits without
        // reading never gives the writer an EPIPE and a large write blocks forever.
        if let inPipe { try? inPipe.fileHandleForReading.close() }
        handle?.attach(task, grace: killGrace)

        let group = DispatchGroup()
        let out = Sink(), err = Sink()
        DispatchQueue.global(qos: .utility).async(group: group) {
            err.drain(errPipe.fileHandleForReading)
        }
        DispatchQueue.global(qos: .utility).async(group: group) {
            out.drain(outPipe.fileHandleForReading)
        }
        if let stdin, let inPipe {
            // Written off this thread too, so a child that answers before it has
            // read all of its input can't wedge the two of us either.
            DispatchQueue.global(qos: .utility).async(group: group) {
                try? inPipe.fileHandleForWriting.write(contentsOf: stdin)
                try? inPipe.fileHandleForWriting.close()
            }
        }

        var timedOut = false
        if let timeout {
            if exited.wait(timeout: .now() + timeout) == .timedOut {
                timedOut = true
                terminate(task, grace: killGrace)
                exited.wait()
            }
        } else {
            exited.wait()
        }
        _ = group.wait(timeout: .now() + drainGrace)

        if timedOut { throw SubprocessError.timedOut(after: timeout ?? 0) }
        if handle?.isCancelled == true { throw SubprocessError.cancelled }
        return SubprocessResult(status: task.terminationStatus, stdout: out.get(), stderr: err.get())
    }

    /// SIGTERM now, SIGKILL after `grace` if it is still running. Returns immediately.
    static func terminate(_ task: Process, grace: TimeInterval = defaultKillGrace) {
        guard task.isRunning else { return }
        task.terminate()
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + grace) {
            if task.isRunning { kill(task.processIdentifier, SIGKILL) }
        }
    }

    /// One pipe's bytes, written by its reader thread and read by the supervisor; a reader
    /// abandoned after the drain grace may still be writing, so access is locked.
    private final class Sink: @unchecked Sendable {
        private let lock = NSLock()
        private var data = Data()
        /// Appends as it reads, so a reader abandoned at the drain grace has still delivered
        /// everything the child wrote before.
        func drain(_ handle: FileHandle) {
            // availableData is one read(2): what the pipe holds now, empty at EOF
            // (read(upToCount:) would block until it had the whole count).
            while true {
                let chunk = handle.availableData
                if chunk.isEmpty { break }
                lock.lock(); data.append(chunk); lock.unlock()
            }
        }
        func get() -> Data { lock.lock(); defer { lock.unlock() }; return data }
    }

    // MARK: - Executable resolution (2026-10-05)

    /// Set to a directory to make it the first place helpers are looked for (tests, a
    /// source checkout's venv bin).
    static let binDirVariable = "TEETIME_MONITOR_BIN_DIR"
    /// A `which` miss is remembered this long so a missing install doesn't spawn `which` on
    /// the main thread for every call, yet a fresh `brew install` is noticed without a restart.
    static let missCacheSeconds: TimeInterval = 30
    static let whichTimeout: TimeInterval = 3

    /// The search order, one place: the override, Homebrew (Apple Silicon, then Intel),
    /// then ~/.local/bin (where `uv tool install` puts console scripts).
    static func candidateDirectories(override: String?, home: String) -> [String] {
        var dirs: [String] = []
        if let override, !override.isEmpty { dirs.append(override) }
        dirs += ["/opt/homebrew/bin", "/usr/local/bin", (home as NSString).appendingPathComponent(".local/bin")]
        return dirs
    }

    /// First executable `name` in `directories`, else whatever `which` finds. Uncached;
    /// `resolve(_:)` is the app-facing entry.
    static func locate(_ name: String, directories: [String], which: (String) -> String?) -> String? {
        for dir in directories {
            let path = (dir as NSString).appendingPathComponent(name)
            if FileManager.default.isExecutableFile(atPath: path) { return path }
        }
        return which(name)
    }

    /// `/usr/bin/which name` with a timeout -- the single PATH fallback.
    static func whichLookup(_ name: String) -> String? {
        guard let result = try? run("/usr/bin/which", [name], timeout: whichTimeout, killGrace: 0.5, drainGrace: 0.5),
              result.status == 0 else { return nil }
        let found = String(data: result.stdout, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return !found.isEmpty && FileManager.default.isExecutableFile(atPath: found) ? found : nil
    }

    /// The path of the `teetime-monitor-*` console script `name`, or nil. A hit is cached
    /// for the app's lifetime (re-checked on use, so a removed binary is looked up again).
    static func resolve(_ name: String) -> String? {
        let override = getenv(binDirVariable).map { String(cString: $0) }
        if let override, !override.isEmpty {
            let path = (override as NSString).appendingPathComponent(name)
            if FileManager.default.isExecutableFile(atPath: path) { return path }
        }
        return resolveCache.lookup(name) {
            locate(name, directories: candidateDirectories(override: nil, home: NSHomeDirectory()),
                   which: whichLookup)
        }
    }

    /// For tests: forget every cached resolution.
    static func resetResolveCache() { resolveCache.reset() }

    private static let resolveCache = ResolveCache()

    private final class ResolveCache: @unchecked Sendable {
        private let lock = NSLock()
        private var hits: [String: String] = [:]
        private var misses: [String: Date] = [:]

        func lookup(_ name: String, compute: () -> String?) -> String? {
            lock.lock()
            if let hit = hits[name] {
                if FileManager.default.isExecutableFile(atPath: hit) { lock.unlock(); return hit }
                hits[name] = nil
            }
            if let missedAt = misses[name], Date().timeIntervalSince(missedAt) < Subprocess.missCacheSeconds {
                lock.unlock(); return nil
            }
            lock.unlock()
            // Computed outside the lock: `which` can take seconds, and resolve() is called
            // from several threads. Two racing misses just both look.
            let found = compute()
            lock.lock()
            if let found { hits[name] = found; misses[name] = nil } else { misses[name] = Date() }
            lock.unlock()
            return found
        }

        func reset() { lock.lock(); hits = [:]; misses = [:]; lock.unlock() }
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
