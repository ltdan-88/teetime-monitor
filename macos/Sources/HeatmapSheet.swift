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
                // Side by side, not stacked -- direct follow-up, 2026-09-19, on
                // the same visit that reported the Search sheet's clipping bug
                // ("would a two-column layout work for heatmap with a fixated
                // legend"): both grids share the same hour-of-day rows (see
                // sharedHours below), so putting them beside each other makes
                // "same hour, does a holiday look different from a normal
                // Wednesday" a glance instead of a scroll. Neither grid gets an
                // explicit width -- same lesson the Search sheet's own bug just
                // taught (a guessed fixed width can silently be too narrow for
                // content that doesn't wrap gracefully); each sizes itself to
                // its own natural content instead, which is also correct here
                // since the two grids are genuinely different widths (7 weekday
                // columns vs. 3 special-day ones).
                //
                // maxHeight: .infinity on the ScrollView -- without it this
                // reported its own *content* height as its ideal size, which
                // could push what comes after it below the fixed-height sheet
                // entirely (this exact failure hit the status line/Close button
                // here before, and the Search sheet's results List independently
                // needed the same fix).
                let sharedHours = Array(Set(heatmap.byWeekday.values.flatMap(\.keys))
                    .union(heatmap.specialDays.values.flatMap(\.keys))).sorted()
                ScrollView {
                    HStack(alignment: .top, spacing: 24) {
                        HeatmapGridView(title: t("heatmap.by_weekday"), keys: CalendarContext.weekdays,
                                        labels: CalendarContext.weekdays.map {
                                            t("weekday.short.\($0.lowercased())")
                                        },
                                        group: heatmap.byWeekday, hours: sharedHours)
                            .fixedSize(horizontal: true, vertical: false)
                        Divider()
                        HeatmapGridView(title: t("heatmap.special_days"), keys: CalendarContext.specialDayTypes,
                                        labels: CalendarContext.specialDayTypes.map { t("heatmap.\($0)") },
                                        group: heatmap.specialDays, hours: sharedHours)
                            .fixedSize(horizontal: true, vertical: false)
                    }
                    .padding(16)
                }
                .frame(maxHeight: .infinity)

                // The legend, fixed below the scrolling grids rather than
                // scrolling away with them -- the other half of the same
                // request ("...with a fixated legend in the bottom"). Simpler
                // than the day list's own pinned Section header: this isn't a
                // lazy collection, so moving it below the ScrollView (instead
                // of inside its content) is the whole fix.
                Divider()
                HeatmapLegendView()
                    .padding(.horizontal, 16).padding(.vertical, 10)
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
    // The *union* of both grids' own hours, computed once by HeatmapSheet and
    // passed to both -- not each grid's own `group.values.flatMap { $0.keys }`
    // anymore. Side by side (see HeatmapSheet's own layout, 2026-09-19), row N
    // has to mean the same hour in both grids for the alignment to be honest;
    // the by-weekday and special-days groups don't necessarily cover the same
    // hours on their own (a tournament has never started at 06:00, say), so
    // each computing its own row set independently could silently misalign
    // what looks like a shared axis. A row this grid has no data for still
    // renders (as the existing "no data" dash), which is the correct way to
    // show "no data at this hour", not a missing row that shifts everything
    // below it out of sync with the grid beside it.
    let hours: [String]

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
    // Same fix as HeatStrip/the seat pips: this swatch illustrates the grid's own
    // occupancy fill, so it gets the theme-relative tone too rather than a plain
    // Color.secondary that can go nearly invisible under a light theme.
    @ObservedObject private var theme = AppTheme.shared

    var body: some View {
        // FlowLayout, not a plain HStack -- now that the legend is a fixed
        // footer rather than free to scroll with the grids above it, it has to
        // hold up at any width the sheet can be resized to, the same "wrap
        // instead of silently overflow" reasoning LegendLine's own move to
        // FlowLayout already covers (see App.swift).
        FlowLayout(hSpacing: 16, vSpacing: 4) {
            swatch(.green, t("heatmap.legend.open"))
            swatch(.orange, t("heatmap.legend.mid"))
            swatch(.red, t("heatmap.legend.full"))
            HStack(spacing: 4) {
                RoundedRectangle(cornerRadius: 2).fill(theme.colors.muted).opacity(0.35)
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
