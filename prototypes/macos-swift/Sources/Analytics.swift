import Foundation

/// One grid cell's worth of history: average occupancy (0-1) and how many samples
/// it's built from -- mirrors `crowd_heatmap()`'s own `{"average": ..., "samples":
/// ...}` shape exactly, since `HeatmapGrid` needs both (the sample count decides
/// whether a cell is shown full-confidence or dimmed).
struct HeatmapBucket {
    let average: Double
    let samples: Int
}

/// key (a weekday name, or a special day type) -> hour ("09") -> bucket.
typealias HeatmapGroup = [String: [String: HeatmapBucket]]

struct CrowdHeatmap {
    let byWeekday: HeatmapGroup
    let specialDays: HeatmapGroup
}

/// Ports `analytics.py`'s own crowd-heatmap aggregation directly -- plain
/// SQL-shaped grouping/averaging over already-scraped occupancy, "no AI involved"
/// by that module's own docstring, and simple/stable enough (like the day-card
/// weather formulas) to verify against Python output rather than shell out for.
/// The one thing this can't do locally -- fetching public holidays -- is a plain
/// unauthenticated API call, not Python logic, so `HolidaysCache` calls it
/// directly too (see `CalendarContext.swift`).
enum Analytics {
    /// Mirrors `analytics.MIN_SAMPLES_FOR_PREDICTION` -- a bucket under this many
    /// samples is a real signal, just not a confident one yet (dimmed, not hidden).
    static let minSamplesForPrediction = 3

    private static func occupancy(_ slot: Slot) -> Double? {
        if slot.isBlocked { return nil }  // not real occupancy, same as recommend.py excludes it
        guard slot.capacity > 0 else { return nil }
        return Double(slot.booked) / Double(slot.capacity)
    }

    private static func averageBuckets(_ buckets: [String: [String: [Double]]]) -> HeatmapGroup {
        buckets.mapValues { hours in
            hours.mapValues { values in
                HeatmapBucket(average: values.reduce(0, +) / Double(values.count), samples: values.count)
            }
        }
    }

    /// Walks every historical date this course has been scraped for
    /// (`Store.distinctScrapedDates()`), classifies each one (tournament / public
    /// holiday / vacation / weekend / workday -- `CalendarContext.classifyDay()`),
    /// and buckets its slots' occupancy by hour into either `byWeekday` (ordinary
    /// days, keyed by weekday name) or `specialDays` (keyed by day type) -- mirrors
    /// `crowd_heatmap()`/`_crowd_buckets()`/`_average_buckets()` exactly, including
    /// the 2026-09-09 rework's own rule that an ordinary day's weekday average is
    /// never diluted by a special day, and vice versa.
    static func crowdHeatmap(dbPath: String, course: String, holidays: [String],
                              vacationRanges: [VacationRange]) -> CrowdHeatmap {
        var byWeekday: [String: [String: [Double]]] = [:]
        var specialDays: [String: [String: [Double]]] = [:]
        let dateFormatter = DateFormatter(); dateFormatter.dateFormat = "yyyy-MM-dd"
        dateFormatter.locale = Locale(identifier: "en_US_POSIX")
        let weekdayFormatter = DateFormatter(); weekdayFormatter.dateFormat = "EEEE"
        weekdayFormatter.locale = Locale(identifier: "en_US_POSIX")  // fixed English
        // names regardless of system locale, matching Python's strftime("%A") here.

        for date in Store.distinctScrapedDates(dbPath: dbPath, course: course) {
            guard let sample = Store.occupancySample(dbPath: dbPath, course: course, date: date),
                  !sample.slots.isEmpty else { continue }
            let dayType = CalendarContext.classifyDay(date: date, holidays: holidays,
                                                        vacationRanges: vacationRanges,
                                                        hasTournament: sample.hasTournament)
            let isSpecial = CalendarContext.specialDayTypes.contains(dayType)
            guard let parsedDate = dateFormatter.date(from: date) else { continue }
            let weekday = weekdayFormatter.string(from: parsedDate)
            for slot in sample.slots {
                guard let occ = occupancy(slot) else { continue }
                let hour = String(slot.time.prefix(2))
                if isSpecial {
                    specialDays[dayType, default: [:]][hour, default: []].append(occ)
                } else {
                    byWeekday[weekday, default: [:]][hour, default: []].append(occ)
                }
            }
        }
        return CrowdHeatmap(byWeekday: averageBuckets(byWeekday), specialDays: averageBuckets(specialDays))
    }
}
