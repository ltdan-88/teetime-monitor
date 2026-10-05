import Foundation

/// One day's recommended pick -- mirrors `picks_cli.py`'s own per-date object shape
/// exactly (see that script's docstring for the contract). `reasons` are
/// `quality.py`'s reason KEYS ("dry", "room_around", ...; at most three, possibly none),
/// decoded to text only for display (`pickTooltip()`); `aiReasons` are the AI's own
/// sentences, present only with AI ranking on. Neither is ever interpreted here.
struct DayPick {
    let time: String
    let score: Double
    let reasons: [String]
    var aiReasons: [String] = []
}

/// Everything `picks_cli.py` says about one day beyond its pick (2026-09-27,
/// bundle C of the TUI/GUI consistency audit): your own availability window
/// for that date -- what out-of-window slots are dimmed by and an expanded day
/// scrolls to -- and, with no pick, why (`"daylight"`/`"weather"`). Decided in
/// Python (`recommend.window_for_date()`, `recommend.unplayable_reasons()`),
/// never re-derived here, so the two apps can't disagree about either.
///
/// Also the per-slot markers of an expanded day (2026-10-05): `recommended` the "HH:MM"
/// slots the TUI marks "★" (`pipeline._recommended_times_for()`), `tooLate` those it marks
/// "🌙" (`pipeline._too_late_for_daylight()`). They live here, not on `DayPick`, because a
/// day with no pick still has too-late slots; and being part of the verdict they are
/// cleared and replaced with it, so another course's markers can never show.
struct DayVerdict {
    let windowAfter: String?
    let windowBefore: String?
    let unplayable: [String]
    var recommended: Set<String> = []
    var tooLate: Set<String> = []

    /// What a slot row carries in front of its time. "★" wins over "🌙" when both are
    /// listed, exactly as `tui._compute_slot_rows()` decides (in practice a recommended
    /// slot is playable, so never too late).
    func marker(for time: String) -> SlotMarker? {
        if recommended.contains(time) { return .recommended }
        if tooLate.contains(time) { return .tooLate }
        return nil
    }

    func isOutsideWindow(_ time: String) -> Bool {
        if let after = windowAfter, time < after { return true }
        if let before = windowBefore, time > before { return true }
        return false
    }
}

/// The marker in a slot row's leading column -- see `DayVerdict.marker(for:)`.
enum SlotMarker: Equatable {
    case recommended
    case tooLate
}

/// A shorter round on another of the club's courses, for a day too dark to
/// finish the selected one (2026-10-05) -- `picks_cli.py`'s optional per-date
/// `"alternative"`, decided by `recommend.shorter_round_alternative()` and only
/// displayed here, never re-derived.
struct ShorterRound: Equatable {
    let course: String
    let time: String
    let holes: Int
}

/// A day that isn't bookable yet (2026-10-05) -- `picks_cli.py`'s optional per-date
/// `"locked"`, decided by `booking_window.day_booking_status()` and only worded here
/// (`lockWhenText()`), never re-derived. `opensAt` stays the ISO 8601 string with the
/// club's UTC offset; `hourKnown` false means the club names no hour (date-level
/// wording, no time).
struct LockedDay: Equatable {
    let opensAt: String
    let hourKnown: Bool
}

/// `recommend.window_too_late_hint()`'s own numbers -- your window opens after
/// the latest start that still finishes before dark, on several days running.
/// `alternativeCourses`: where a shorter round still fits on those days.
struct WindowHint {
    let windowAfter: String
    let latestStart: String
    let sunset: String
    let roundMinutes: Int
    var alternativeCourses: [String] = []
}

struct PicksResult {
    var picks: [String: DayPick] = [:]
    var verdicts: [String: DayVerdict] = [:]
    var alternatives: [String: ShorterRound] = [:]
    var locked: [String: LockedDay] = [:]
    var hint: WindowHint?
}

/// Shells out to `teetime-monitor-picks`, the Tier 2 console script wrapping
/// `pipeline._availability_pipeline()` -- same hybrid split `SearchClient` already
/// follows, for the same reason: the pick selection (hard filters, weather/daylight
/// playability, AI ranking) is real, non-trivial business logic this app doesn't
/// reimplement, and reusing the exact function `_day_pick_text()` itself calls means
/// this can never disagree with what the TUI would show for the same data.
///
/// Added 2026-09-27, direct follow-up to the GUI's Overview never showing an
/// AI-ranked pick at all (only the ad hoc Search sheet did) -- see `App.swift`'s
/// `OverviewModel.reload()` (where this is called, fire-and-forget, alongside the
/// synchronous SQLite reload) and `DayCardHeader`'s pick badge.
enum PicksClient {
    static func executable() -> String? { Subprocess.resolve("teetime-monitor-picks") }

    /// `clubSlug` is optional, same reason `SearchClient.run()`'s own is: an
    /// unsaved/browsed club still gets a pick, just without that club's own
    /// availability/AI-ranking overrides layered in. Silently does nothing on
    /// failure (no executable, bad exit, unparseable output) -- this is a
    /// best-effort enhancement over the core Overview, which already rendered
    /// correctly before this existed and must keep doing so if the call fails for
    /// any reason (same stance `_availability_pipeline()` itself takes).
    ///
    /// Returns a handle: `cancel()` terminates the child, and `done` is then never called
    /// (the canceller superseded this run). A timeout (`Subprocess.Timeout.picks`) is a
    /// failure like any other: silent, an empty result.
    @discardableResult
    static func run(dbPath: String, course: String, clubSlug: String?, from: String, days: Int,
                    timeout: TimeInterval = Subprocess.Timeout.picks,
                    done: @escaping (PicksResult) -> Void) -> SubprocessHandle {
        let handle = SubprocessHandle()
        guard let exe = executable() else { done(PicksResult()); return handle }
        DispatchQueue.global(qos: .utility).async {
            var args = ["--db-path", dbPath, "--course", course, "--from", from, "--days", String(days)]
            if let clubSlug { args += ["--club-slug", clubSlug] }
            let result: SubprocessResult
            do { result = try Subprocess.run(exe, args, timeout: timeout, handle: handle) } catch SubprocessError.cancelled {
                return
            } catch {
                DispatchQueue.main.async { done(PicksResult()) }
                return
            }
            DispatchQueue.main.async {
                guard let obj = Subprocess.jsonObject(from: result.stdout) as? [String: Any] else {
                    done(PicksResult())
                    return
                }
                done(parse(obj))
            }
        }
        return handle
    }

    /// Split out of `run()` so it's testable without a subprocess.
    static func parse(_ obj: [String: Any]) -> PicksResult {
        var result = PicksResult()
        if let hint = obj["_hint"] as? [String: Any],
           let after = hint["window_after"] as? String, let latest = hint["latest_start"] as? String,
           let sunset = hint["sunset"] as? String {
            result.hint = WindowHint(windowAfter: after, latestStart: latest, sunset: sunset,
                                     roundMinutes: hint["round_minutes"] as? Int ?? 0,
                                     alternativeCourses: hint["alternative_courses"] as? [String] ?? [])
        }
        for (date, value) in obj where date != "_hint" {
            guard let row = value as? [String: Any] else { continue }
            let window = row["window"] as? [String: Any]
            result.verdicts[date] = DayVerdict(
                windowAfter: window?["after"] as? String,
                windowBefore: window?["before"] as? String,
                unplayable: row["unplayable"] as? [String] ?? [],
                recommended: Set(row["recommended"] as? [String] ?? []),
                tooLate: Set(row["too_late"] as? [String] ?? [])
            )
            if let alternative = row["alternative"] as? [String: Any],
               let course = alternative["course"] as? String, let time = alternative["time"] as? String,
               let holes = alternative["holes"] as? Int {
                result.alternatives[date] = ShorterRound(course: course, time: time, holes: holes)
            }
            if let locked = row["locked"] as? [String: Any], let opensAt = locked["opens_at"] as? String {
                result.locked[date] = LockedDay(opensAt: opensAt, hourKnown: locked["hour_known"] as? Bool ?? false)
            }
            if let time = row["time"] as? String {
                result.picks[date] = DayPick(
                    time: time,
                    score: row["score"] as? Double ?? 0,
                    reasons: row["reasons"] as? [String] ?? [],
                    aiReasons: row["ai_reasons"] as? [String] ?? []
                )
            }
        }
        return result
    }
}
