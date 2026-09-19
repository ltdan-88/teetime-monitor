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
    @ObservedObject private var language = AppLanguage.shared

    @StateObject private var heatmap = Box<CrowdHeatmap?>(nil)
    @StateObject private var isLoading = Box(true)
    @StateObject private var status = Box<String?>(nil)

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(t("heatmap.title", ["course": course])).font(scaledFont(.title2)).bold().padding([.top, .horizontal], 16)

            if isLoading.value {
                ProgressView(t("heatmap.loading")).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let heatmap = heatmap.value {
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        HeatmapGridView(title: t("heatmap.by_weekday"), keys: CalendarContext.weekdays,
                                        labels: CalendarContext.weekdays.map {
                                            t("weekday.short.\($0.lowercased())")
                                        },
                                        group: heatmap.byWeekday)
                        HeatmapGridView(title: t("heatmap.special_days"), keys: CalendarContext.specialDayTypes,
                                        labels: CalendarContext.specialDayTypes.map { t("heatmap.\($0)") },
                                        group: heatmap.specialDays)
                        HeatmapLegendView()
                    }
                    .padding(16)
                }
            }

            if let status = status.value {
                Text(status).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                    .padding(.horizontal, 16).padding(.bottom, 8)
            }

            HStack {
                Spacer()
                Button(t("button.close")) { dismiss() }
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
                status.value = countryCode == nil ? t("heatmap.no_country") : nil
            }
        }
    }
}

private struct HeatmapGridView: View {
    @ObservedObject private var scale = AppScale.shared
    @ObservedObject private var language = AppLanguage.shared
    let title: String
    let keys: [String]
    let labels: [String]
    let group: HeatmapGroup

    private var hours: [String] {
        Array(Set(group.values.flatMap { $0.keys })).sorted()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(scaledFont(.headline))
            if hours.isEmpty {
                Text(t("heatmap.no_data_yet")).font(scaledFont(.caption)).foregroundStyle(.secondary)
            } else {
                Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 4) {
                    GridRow {
                        Text("").frame(width: scale.scaled(Metrics.heatHourLabel))
                        ForEach(Array(labels.enumerated()), id: \.offset) { _, label in
                            Text(label).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                        }
                    }
                    ForEach(hours, id: \.self) { hour in
                        GridRow {
                            Text("\(hour):00")
                                .font(scaledFont(.caption2, design: .monospaced))
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
    @ObservedObject private var language = AppLanguage.shared
    let bucket: HeatmapBucket?

    var body: some View {
        if let bucket {
            RoundedRectangle(cornerRadius: 2)
                .fill(fillColor(bucket.average))
                .opacity(bucket.samples < Analytics.minSamplesForPrediction ? 0.35 : 1.0)
                .frame(width: scale.scaled(Metrics.heatCellWidth),
                       height: scale.scaled(Metrics.heatCellHeight))
                .help(t("heatmap.cell_tip", ["pct": "\(Int((bucket.average * 100).rounded()))",
                                            "n": "\(bucket.samples)"]))
        } else {
            Text("–").font(scaledFont(.caption2)).foregroundStyle(.tertiary).frame(width: scale.scaled(Metrics.heatCellWidth),
                                        height: scale.scaled(Metrics.heatCellHeight))
        }
    }
}

private struct HeatmapLegendView: View {
    @ObservedObject private var scale = AppScale.shared
    @ObservedObject private var language = AppLanguage.shared

    var body: some View {
        HStack(spacing: 16) {
            swatch(.green, t("heatmap.legend.open"))
            swatch(.orange, t("heatmap.legend.mid"))
            swatch(.red, t("heatmap.legend.full"))
            HStack(spacing: 4) {
                RoundedRectangle(cornerRadius: 2).fill(Color.secondary).opacity(0.35)
                    .frame(width: scale.scaled(Metrics.legendSwatchWidth),
                           height: scale.scaled(Metrics.legendSwatchHeight))
                Text(t("heatmap.legend.thin"))
            }
            HStack(spacing: 4) {
                Text("–").foregroundStyle(.tertiary)
                Text(t("heatmap.legend.no_data"))
            }
        }
        .font(scaledFont(.caption2)).foregroundStyle(.secondary)
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
