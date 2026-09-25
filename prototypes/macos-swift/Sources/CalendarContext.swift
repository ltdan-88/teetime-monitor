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

    /// A club's `calendar.vacation_ranges`, read directly from its own YAML.
    ///
    /// Previously always `[]` -- a flagged, known gap: `YAML.swift`'s parser is
    /// deliberately scoped to nested maps of scalars, no lists (see its own
    /// docstring), so it can't represent this field's own list-of-maps shape.
    /// Rather than widen that shared parser (used everywhere `preferences.yaml`'s
    /// own byte-for-byte round-trip already depends on -- real risk of disturbing
    /// something already verified, for a field neither of this install's own
    /// saved clubs uses yet), this is a second, narrow, purpose-built scanner for
    /// exactly this one field's own *documented* shape -- the flow-style list
    /// `clubs/club.example.yaml` itself shows and comments as the intended way to
    /// fill this in:
    ///
    /// ```yaml
    /// vacation_ranges:
    ///   - { start: "2026-07-04", end: "2026-09-15", label: "summer break" }
    /// ```
    ///
    /// Confirmed against a real `yaml.safe_load()` of that exact shape before
    /// writing this, not assumed. **Also recognizes block-style items** (`- start:
    /// ...` on its own line, `end:`/`label:` indented on the lines under it, at
    /// either of the two indents `yaml.safe_load()` itself accepts for this shape
    /// -- the dash lined up with `vacation_ranges:` itself, or indented under it),
    /// confirmed against real `yaml.safe_load()` output for both forms before
    /// writing this rather than assumed. A one-line "unquote" pass handles a bare,
    /// single-quoted, or double-quoted scalar; nothing more exotic (folded/literal
    /// block scalars, flow sequences as a value) -- this scanner's whole scope is
    /// this one field's own two documented shapes, not general YAML.
    static func vacationRanges(clubYAMLPath: String) -> [VacationRange] {
        guard let text = try? String(contentsOfFile: clubYAMLPath, encoding: .utf8) else { return [] }
        let lines = text.components(separatedBy: "\n")
        guard let headerIndex = lines.firstIndex(where: {
            $0.trimmingCharacters(in: .whitespaces).hasPrefix("vacation_ranges:")
        }) else { return [] }

        let flowPattern = try! NSRegularExpression(pattern: #"^\s*-\s*\{(.*)\}\s*$"#)
        let dashPattern = try! NSRegularExpression(pattern: #"^(\s*)-\s*(.*)$"#)
        let fieldPattern = try! NSRegularExpression(pattern: #"^\s*([A-Za-z_]+):\s*(.*)$"#)

        func unquote(_ raw: String) -> String {
            var value = raw.trimmingCharacters(in: .whitespaces)
            let quotes: [Character] = ["\"", "'"]
            if let first = value.first, let last = value.last, first == last, quotes.contains(first),
               value.count >= 2 {
                value = String(value.dropFirst().dropLast())
            }
            return value
        }

        func field(_ line: Substring) -> (key: String, value: String)? {
            let line = String(line)
            let searchRange = NSRange(line.startIndex..., in: line)
            guard let match = fieldPattern.firstMatch(in: line, range: searchRange),
                  let keyRange = Range(match.range(at: 1), in: line),
                  let valueRange = Range(match.range(at: 2), in: line) else { return nil }
            return (String(line[keyRange]), unquote(String(line[valueRange])))
        }

        var ranges: [VacationRange] = []
        var index = lines.index(after: headerIndex)
        while index < lines.count {
            let line = lines[index]
            let searchRange = NSRange(line.startIndex..., in: line)

            if let match = flowPattern.firstMatch(in: line, range: searchRange),
               let innerRange = Range(match.range(at: 1), in: line) {
                var fields: [String: String] = [:]
                for pair in line[innerRange].split(separator: ",") {
                    let parts = pair.split(separator: ":", maxSplits: 1)
                    guard parts.count == 2 else { continue }
                    fields[parts[0].trimmingCharacters(in: .whitespaces)] = unquote(String(parts[1]))
                }
                if let start = fields["start"], let end = fields["end"] {
                    ranges.append(VacationRange(start: start, end: end, label: fields["label"] ?? ""))
                }
                index += 1
                continue
            }

            guard let dashMatch = dashPattern.firstMatch(in: line, range: searchRange),
                  let dashIndentRange = Range(dashMatch.range(at: 1), in: line),
                  let afterDashRange = Range(dashMatch.range(at: 2), in: line) else {
                // Not a `-`-led line at all -- either the list ended (dedented
                // back to a sibling key) or it's a shape this scanner doesn't
                // recognize. Either way, stop rather than guess.
                break
            }
            let dashIndent = line.distance(from: line.startIndex, to: dashIndentRange.upperBound)
            var fields: [String: String] = [:]
            let afterDash = line[afterDashRange]
            if !afterDash.isEmpty, let (key, value) = field(afterDash) {
                fields[key] = value
            }
            index += 1
            // Sibling fields are indented past the dash itself -- e.g. "  - start:
            // ..." (indent 2) then "    end: ..." (indent 4, past the dash at 2).
            while index < lines.count {
                let next = lines[index]
                guard let leadIndex = next.firstIndex(where: { $0 != " " }) else { index += 1; continue }
                let leadIndent = next.distance(from: next.startIndex, to: leadIndex)
                guard leadIndent > dashIndent, next[leadIndex] != "-",
                      let (key, value) = field(next[leadIndex...]) else { break }
                fields[key] = value
                index += 1
            }
            guard let start = fields["start"], let end = fields["end"] else { continue }
            ranges.append(VacationRange(start: start, end: end, label: fields["label"] ?? ""))
        }
        return ranges
    }
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
