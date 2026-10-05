import Foundation

/// Mirrors `storage.scrape_health()`'s dict (2026-10-05): a summary of the club's
/// recent `scrape_runs`, read straight from SQLite by `Store.scrapeHealth()`. Timestamps
/// stay the ISO strings Python wrote, so `CrossCheckRunner` can compare field by field.
/// See storage.py's module docstring for why this exists: a ~20-hour silent login
/// rejection nobody noticed, because both apps kept saying "updated N min ago".
struct ScrapeHealth: Equatable {
    var lastRunAt: String?
    var lastSuccessAt: String?
    var lastErrorKind: String?
    var lastErrorMessage: String?
    var consecutiveFailedRuns = 0
    var failingSince: String?
    var loginRejectedSince: String?

    static let empty = ScrapeHealth()

    /// `storage.scrape_run_succeeded()`: something saved, or nothing due and no error
    /// other than a rejected login (2026-10-05 -- otherwise the agent's idle no-op
    /// passes during a login outage turned "login rejected" into "scrapes failing").
    static func runSucceeded(saved: Int, attempted: Int, errorKind: String?) -> Bool {
        saved > 0 || (attempted == 0 && (errorKind == nil || errorKind == "login_rejected"))
    }

    /// One `scrape_runs` row, newest first -- the input `summarize` walks.
    struct Run {
        let startedAt: String
        let finishedAt: String
        let attempted: Int
        let saved: Int
        let authenticated: Int?
        let errorKind: String?
        let errorMessage: String?
    }

    /// The streak logic of `storage.scrape_health()`, line for line -- see its
    /// docstring for why a run with an unknown login outcome (authenticated = 0 with
    /// some other error) neither extends nor breaks the login-rejected streak.
    static func summarize(_ runs: [Run]) -> ScrapeHealth {
        guard let newest = runs.first else { return .empty }
        var health = ScrapeHealth(lastRunAt: newest.finishedAt, lastErrorKind: newest.errorKind,
                                  lastErrorMessage: newest.errorMessage)
        var failureStreakOpen = true
        var loginStreakOpen = true
        for run in runs {
            let succeeded = runSucceeded(saved: run.saved, attempted: run.attempted, errorKind: run.errorKind)
            if succeeded && health.lastSuccessAt == nil { health.lastSuccessAt = run.finishedAt }
            if failureStreakOpen {
                if succeeded {
                    failureStreakOpen = false
                } else {
                    health.consecutiveFailedRuns += 1
                    health.failingSince = run.startedAt
                }
            }
            if loginStreakOpen {
                if run.errorKind == "login_rejected" {
                    health.loginRejectedSince = run.startedAt
                } else if !(run.authenticated == 0 && run.errorKind != nil) {
                    loginStreakOpen = false
                }
            }
            if !failureStreakOpen && !loginStreakOpen && health.lastSuccessAt != nil { break }
        }
        return health
    }
}

/// Mirrors `scrape_health.py`: the one-line warning beside the footer's freshness
/// readout, or nothing while healthy. Failing (red) outranks a rejected login (amber).
enum ScrapeHealthStatus: String {
    case failing
    case loginRejected = "login_rejected"
}

struct ScrapeHealthWarning: Equatable {
    let status: ScrapeHealthStatus
    /// The visible one-liner -- the same text the TUI shows under its `#status`.
    let text: String
    /// For `.help()`: the line plus the raw error the last run recorded, which the
    /// footer has no room for.
    let detail: String
}

enum ScrapeHealthRules {
    static let failingRunThreshold = 3
    static let staleIntervalMultiplier = 3
    /// A "since" older than this also shows its date -- a bare weekday is ambiguous.
    static let weekdayOnlyWithin: TimeInterval = 6 * 24 * 3600

    static func parse(_ iso: String?) -> Date? {
        guard let iso, !iso.isEmpty else { return nil }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: iso) ?? ISO8601DateFormatter().date(from: iso)
    }

    /// `scrape_health.health_status()`.
    static func status(_ health: ScrapeHealth, intervalMinutes: Int, now: Date) -> (ScrapeHealthStatus, String)? {
        guard let lastRun = health.lastRunAt, !lastRun.isEmpty else { return nil }
        var stale = false
        if let lastSuccess = parse(health.lastSuccessAt) {
            stale = now.timeIntervalSince(lastSuccess) > Double(intervalMinutes * staleIntervalMultiplier) * 60
        }
        if health.consecutiveFailedRuns >= failingRunThreshold || stale {
            let streakStart = health.consecutiveFailedRuns > 0 ? health.failingSince : nil
            if let since = (streakStart?.isEmpty == false ? streakStart : nil) ?? health.lastSuccessAt,
               !since.isEmpty {
                return (.failing, since)
            }
        }
        if let since = health.loginRejectedSince, !since.isEmpty { return (.loginRejected, since) }
        return nil
    }

    /// `scrape_health.since_text()`: "Sat 18:45" local time, "Sat 09-28 18:45" past six days.
    static func sinceText(_ iso: String, now: Date) -> String {
        guard let moment = parse(iso) else { return iso }
        let parts = Calendar.current.dateComponents([.weekday, .month, .day, .hour, .minute], from: moment)
        let names = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
        let weekday = t("weekday.short.\(names[((parts.weekday ?? 1) - 1) % 7])")
        let clock = String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0)
        if now.timeIntervalSince(moment) > weekdayOnlyWithin {
            return "\(weekday) \(String(format: "%02d-%02d", parts.month ?? 0, parts.day ?? 0)) \(clock)"
        }
        return "\(weekday) \(clock)"
    }

    /// `scrape_health.health_warning()`, plus the tooltip detail.
    static func warning(_ health: ScrapeHealth, intervalMinutes: Int, now: Date) -> ScrapeHealthWarning? {
        guard let (status, since) = status(health, intervalMinutes: intervalMinutes, now: now) else { return nil }
        let text: String
        switch status {
        case .loginRejected:
            text = t("health.login_rejected", ["since": sinceText(since, now: now)])
        case .failing:
            let kind = (health.lastErrorKind?.isEmpty == false ? health.lastErrorKind : nil) ?? "none"
            text = t("health.failing", ["since": sinceText(since, now: now), "reason": t("health.reason.\(kind)")])
        }
        let message = health.lastErrorMessage?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return ScrapeHealthWarning(status: status, text: text, detail: message.isEmpty ? text : "\(text)\n\(message)")
    }
}
