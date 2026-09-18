import SwiftUI

/// The crowd heatmap (Tier 2's last piece, 2026-09-18) -- but turned out to need no
/// new console script at all. `analytics.crowd_heatmap()` is "plain SQL/code, no AI
/// involved" by its own module docstring, and its one real dependency (public
/// holidays) is a plain unauthenticated API call, not Python-specific logic -- so
/// both port directly to Swift (`Analytics.swift`/`CalendarContext.swift`) the same
/// way the day-card weather formulas already did, verified against Python rather
/// than reimplemented from a guess.
///
/// Mirrors `HeatmapScreen`: two grids (by weekday, and special days compared only
/// against others of their own kind), hour-of-day as rows, only the hours actually
/// scraped (a club's real operating hours aren't assumed), a legend explaining the
/// four cell states once.
struct HeatmapSheet: View {
    @Environment(\.dismiss) private var dismiss
    let dbPath: String
    let course: String
    let clubYAMLPath: String?

    @StateObject private var heatmap = Box<CrowdHeatmap?>(nil)
    @StateObject private var isLoading = Box(true)
    @StateObject private var status = Box<String?>(nil)

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Crowd Heatmap — \(course)").font(.title2).bold().padding([.top, .horizontal], 16)

            if isLoading.value {
                ProgressView("Crunching scrape history…").frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let heatmap = heatmap.value {
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        HeatmapGridView(title: "By weekday", keys: CalendarContext.weekdays,
                                        labels: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
                                        group: heatmap.byWeekday)
                        HeatmapGridView(title: "Special days", keys: CalendarContext.specialDayTypes,
                                        labels: ["Tournament", "Public holiday", "Vacation"],
                                        group: heatmap.specialDays)
                        HeatmapLegendView()
                    }
                    .padding(16)
                }
            }

            if let status = status.value {
                Text(status).font(.caption2).foregroundStyle(.secondary)
                    .padding(.horizontal, 16).padding(.bottom, 8)
            }

            HStack {
                Spacer()
                Button("Close") { dismiss() }
            }
            .padding(16)
        }
        .sheetFrame(SheetSize.wide)
        .onAppear { load() }
    }

    private func load() {
        isLoading.value = true
        status.value = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let countryCode = clubYAMLPath.flatMap { CalendarContext.countryCode(clubYAMLPath: $0) }
            let vacationRanges = clubYAMLPath.map { CalendarContext.vacationRanges(clubYAMLPath: $0) } ?? []

            var holidays: [String] = []
            if let countryCode {
                let group = DispatchGroup()
                group.enter()
                let year = Calendar(identifier: .gregorian).component(.year, from: Date())
                HolidaysCache.shared.holidays(countryCode: countryCode, year: year) { result in
                    holidays = result
                    group.leave()
                }
                group.wait()
            }

            let result = Analytics.crowdHeatmap(dbPath: dbPath, course: course, holidays: holidays,
                                                 vacationRanges: vacationRanges)
            DispatchQueue.main.async {
                heatmap.value = result
                isLoading.value = false
                status.value = countryCode == nil
                    ? "No country set for this club — public holidays not shown. Set calendar.country_code in its YAML to enable that."
                    : nil
            }
        }
    }
}

private struct HeatmapGridView: View {
    @ObservedObject private var scale = AppScale.shared
    let title: String
    let keys: [String]
    let labels: [String]
    let group: HeatmapGroup

    private var hours: [String] {
        Array(Set(group.values.flatMap { $0.keys })).sorted()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.headline)
            if hours.isEmpty {
                Text("No data yet").font(.caption).foregroundStyle(.secondary)
            } else {
                Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 4) {
                    GridRow {
                        Text("").frame(width: scale.scaled(Metrics.heatHourLabel))
                        ForEach(Array(labels.enumerated()), id: \.offset) { _, label in
                            Text(label).font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                    ForEach(hours, id: \.self) { hour in
                        GridRow {
                            Text("\(hour):00")
                                .font(.system(.caption2, design: .monospaced))
                                .frame(width: scale.scaled(Metrics.heatHourLabel), alignment: .leading)
                            ForEach(Array(keys.enumerated()), id: \.offset) { _, key in
                                HeatmapCell(bucket: group[key]?[hour])
                            }
                        }
                    }
                }
            }
        }
    }
}

private struct HeatmapCell: View {
    @ObservedObject private var scale = AppScale.shared
    let bucket: HeatmapBucket?

    var body: some View {
        if let bucket {
            RoundedRectangle(cornerRadius: 2)
                .fill(fillColor(bucket.average))
                .opacity(bucket.samples < Analytics.minSamplesForPrediction ? 0.35 : 1.0)
                .frame(width: scale.scaled(Metrics.heatCellWidth),
                       height: scale.scaled(Metrics.heatCellHeight))
                .help("\(Int((bucket.average * 100).rounded()))% average occupancy, "
                      + "\(bucket.samples) sample\(bucket.samples == 1 ? "" : "s")")
        } else {
            Text("–").font(.caption2).foregroundStyle(.tertiary).frame(width: scale.scaled(Metrics.heatCellWidth),
                                        height: scale.scaled(Metrics.heatCellHeight))
        }
    }
}

private struct HeatmapLegendView: View {
    @ObservedObject private var scale = AppScale.shared

    var body: some View {
        HStack(spacing: 16) {
            swatch(.green, "under half booked")
            swatch(.orange, "half to full")
            swatch(.red, "fully booked")
            HStack(spacing: 4) {
                RoundedRectangle(cornerRadius: 2).fill(Color.secondary).opacity(0.35)
                    .frame(width: scale.scaled(Metrics.legendSwatchWidth),
                           height: scale.scaled(Metrics.legendSwatchHeight))
                Text("thin sample (<3)")
            }
            HStack(spacing: 4) {
                Text("–").foregroundStyle(.tertiary)
                Text("no data")
            }
        }
        .font(.caption2).foregroundStyle(.secondary)
    }

    private func swatch(_ color: Color, _ label: String) -> some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 2).fill(color)
                .frame(width: scale.scaled(Metrics.legendSwatchWidth),
                       height: scale.scaled(Metrics.legendSwatchHeight))
            Text(label)
        }
    }
}
