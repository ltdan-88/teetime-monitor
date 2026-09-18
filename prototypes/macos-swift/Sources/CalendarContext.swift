import Foundation

/// A hand-entered "this makes the course busier" span -- `calendar.vacation_ranges`
/// in a club's own YAML. See `CalendarContext.vacationRanges()` for why this
/// prototype can't actually read that field yet.
struct VacationRange {
    let start: String
    let end: String
    let label: String
}

/// Ports `calendar_context.py`'s day-classification logic directly -- small, pure,
/// and stable enough to verify against Python output the same way the day-card
/// weather aggregation formulas already were, rather than shelling out for
/// something this simple.
enum CalendarContext {
    /// Sunday-first, matching `calendar_context.WEEKDAYS` exactly (the mockup's own
    /// column order).
    static let weekdays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    static let specialDayTypes = ["tournament", "public_holiday", "vacation"]

    private static func inVacation(_ date: String, _ ranges: [VacationRange]) -> Bool {
        ranges.contains { $0.start <= date && date <= $0.end }
    }

    /// One of the day types above, most-specific first -- mirrors `classify_day()`
    /// exactly.
    static func classifyDay(date: String, holidays: [String], vacationRanges: [VacationRange],
                             hasTournament: Bool) -> String {
        if hasTournament { return "tournament" }
        if holidays.contains(date) { return "public_holiday" }
        if inVacation(date, vacationRanges) { return "vacation" }
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX")
        guard let d = f.date(from: date) else { return "workday" }
        // Gregorian .weekday is 1=Sunday...7=Saturday, matching Python's
        // date.weekday() >= 5 (Sat=5, Sun=6) check by a different numbering.
        let weekday = Calendar(identifier: .gregorian).component(.weekday, from: d)
        return (weekday == 1 || weekday == 7) ? "weekend" : "workday"
    }

    /// A club's `calendar.country_code`, read directly from its own `clubs/*.yaml`
    /// -- reuses `YAML.swift`'s existing map-of-scalars parser, which handles a
    /// plain scalar sibling fine even though it can't represent the list next to it
    /// (see `vacationRanges()` below).
    static func countryCode(clubYAMLPath: String) -> String? {
        guard let text = try? String(contentsOfFile: clubYAMLPath, encoding: .utf8) else { return nil }
        let code = YAML.parse(text)["calendar"]?["country_code"]?.asString
        return (code?.isEmpty ?? true) ? nil : code
    }

    /// **Known, flagged gap** (same "flagged rather than silently assumed"
    /// convention `search_cli.py`'s own `crowd_estimates` gap uses) -- a club's
    /// `calendar.vacation_ranges` is a YAML *list* of `{start, end, label}` maps,
    /// and `YAML.swift`'s parser is deliberately scoped to nested maps of scalars
    /// only (see its own docstring: "no lists, no anchors"). A vacation day here
    /// classifies as an ordinary weekend/workday instead of its own "vacation"
    /// bucket until this is worth a real list parser -- narrower than it sounds:
    /// neither of this install's own two saved clubs has a `calendar:` block
    /// configured at all yet, so today this changes nothing real, only what a
    /// future hand-entered vacation range would do.
    static func vacationRanges(clubYAMLPath: String) -> [VacationRange] { [] }
}

/// A plain, unauthenticated GET against Nager.Date -- not Python-owned logic at
/// all, just a third-party JSON API passthrough with nothing to interpret, so
/// there's no drift risk in calling it directly from Swift instead of shelling
/// out. Caches only successful fetches for the process's lifetime, same rule
/// `tui.py`'s own `_HOLIDAY_CACHE`/`_holidays_for_club()` follow -- a transient
/// network failure stays retryable next time rather than becoming a sticky "no
/// holidays" for the rest of the session.
final class HolidaysCache {
    static let shared = HolidaysCache()
    private var cache: [String: [String]] = [:]
    private let lock = NSLock()

    func holidays(countryCode: String, year: Int, done: @escaping ([String]) -> Void) {
        let key = "\(countryCode)-\(year)"
        lock.lock()
        if let cached = cache[key] { lock.unlock(); done(cached); return }
        lock.unlock()
        guard let url = URL(string: "https://date.nager.at/api/v3/PublicHolidays/\(year)/\(countryCode)") else {
            done([]); return
        }
        URLSession.shared.dataTask(with: url) { [weak self] data, _, error in
            guard let data, error == nil,
                  let rows = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
                done([]); return
            }
            let dates = rows.compactMap { $0["date"] as? String }
            self?.lock.lock(); self?.cache[key] = dates; self?.lock.unlock()
            done(dates)
        }.resume()
    }
}
