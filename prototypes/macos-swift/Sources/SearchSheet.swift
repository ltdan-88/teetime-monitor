import SwiftUI

/// Ad hoc search (Tier 2, 2026-09-18) -- mirrors `SearchScreen` in tui.py: criteria
/// pre-filled from your saved Preferences (edit for this one search, same "starts
/// from your saved defaults" UX that screen shares with its own Preferences
/// screen), run against the same days already visible in the day list, not a fresh
/// scrape. The actual filtering/ranking is `SearchClient` shelling out to
/// `teetime-monitor-search` -- see that file and `search_cli.py`'s own docstring.
///
/// Weather per result isn't part of the CLI's own JSON (that script stays a thin
/// "criteria in, matches out" boundary) -- this sheet cross-references each match's
/// date against `Store.days()`, which this app already reads directly elsewhere,
/// the same `schedule_by_key` lookup `SearchScreen._run_search()` does against its
/// own `self.schedules`.
struct SearchSheet: View {
    @Environment(\.dismiss) private var dismiss
    let dbPath: String
    let course: String
    let clubSlug: String?
    @ObservedObject var model: OverviewModel
    @ObservedObject private var language = AppLanguage.shared

    @StateObject private var criteria: Box<SearchCriteriaPayload>
    @StateObject private var isSearching = Box(false)
    @StateObject private var status = Box<String?>(nil)
    @StateObject private var results = Box<[SearchMatch]>([])
    @StateObject private var weatherByDate = Box<[String: Day]>([:])
    @StateObject private var confirming = Box<SearchMatch?>(nil)

    private let searchDays = 6  // same window Store.days() already shows on screen

    init(dbPath: String, course: String, clubSlug: String?, model: OverviewModel) {
        self.dbPath = dbPath
        self.course = course
        self.clubSlug = clubSlug
        self.model = model
        // Same seeding PreferencesSheet/SettingsSheet already use -- a snapshot to
        // edit here, not a live binding back to preferences.yaml.
        let p = Preferences.load()
        _criteria = StateObject(wrappedValue: Box(SearchCriteriaPayload(
            minOpenSpots: p.minOpenSpots,
            weekdayAfter: p.weekdayAfter, weekdayBefore: p.weekdayBefore,
            weekendAfter: p.weekendAfter, weekendBefore: p.weekendBefore,
            bufferBeforeMinutes: p.bufferBeforeMinutes, bufferAfterMinutes: p.bufferAfterMinutes
        )))
    }

    private var today: String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; return f.string(from: Date())
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(t("search.title")).font(scaledFont(.title2)).bold().padding([.top, .horizontal], 16)
            Text(t("search.prefill_note"))
                .font(scaledFont(.caption2)).foregroundStyle(.secondary).padding(.horizontal, 16).padding(.top, 2)

            // Criteria on the left, results on the right -- direct follow-up,
            // 2026-09-19, on top of this same sheet's own width already having
            // just been trimmed ("would it make sense to place search results
            // on the right instead? ... the results don't need that much
            // width"): each result row really is narrow, and stacking meant
            // results were only ever visible after scrolling past the whole
            // criteria form -- keeping both on screen at once means adjusting
            // a criterion and re-running the search doesn't lose sight of
            // what's being compared against.
            //
            // The criteria column has *no* explicit width here -- a first cut
            // hardcoded one (340, "measured" from the longest German label plus
            // its control), and shipped broken: reported live with a
            // screenshot showing every label in that column missing its own
            // *leading* characters ("Kriterien" -> "erien", "Abstand zur
            // Gruppe davor..." -> "and zur Gruppe davor..."), values and
            // controls unaffected. That's `Form`'s own grouped style favoring
            // a row's trailing content when the row doesn't fit the width it's
            // given, not a simple wrap/truncate -- 340 was a razor-thin,
            // wrong-by-a-few-points guess at Form's real per-row overhead
            // (indentation, grouped-style insets) on top of the label/control
            // measurements themselves. Letting the Form size itself to its own
            // natural content width removes that guess entirely: it always
            // requests exactly what its longest un-wrapped row needs. The
            // results column's own `.frame(maxWidth: .infinity)` still soaks
            // up whatever's left.
            HStack(alignment: .top, spacing: 16) {
                VStack(alignment: .leading, spacing: 0) {
                    Form {
                        Section(t("search.section.criteria")) {
                            HStack {
                                Text(t("prefs.min_open_spots_label"))
                                Spacer()
                                IntChoicePicker(choices: [1, 2, 3, 4], value: $criteria.value.minOpenSpots)
                            }
                            TimeWindowRow(label: t("prefs.weekday"), after: $criteria.value.weekdayAfter,
                                          before: $criteria.value.weekdayBefore)
                            TimeWindowRow(label: t("prefs.weekend"), after: $criteria.value.weekendAfter,
                                          before: $criteria.value.weekendBefore)
                            HStack {
                                Text(t("prefs.buffer_before_label"))
                                Spacer()
                                IntChoicePicker(choices: [0, 10, 20, 30, 40, 50, 60], value: $criteria.value.bufferBeforeMinutes, suffix: " min")
                            }
                            HStack {
                                Text(t("prefs.buffer_after_label"))
                                Spacer()
                                IntChoicePicker(choices: [0, 10, 20, 30, 40, 50, 60], value: $criteria.value.bufferAfterMinutes, suffix: " min")
                            }
                        }
                    }
                    .formStyle(.grouped)

                    VStack(alignment: .leading, spacing: 4) {
                        if let status = status.value {
                            Text(status).font(scaledFont(.caption)).foregroundStyle(.secondary)
                        }
                        HStack {
                            if isSearching.value { ProgressView().controlSize(.small) }
                            Button(t("search.button")) { runSearch() }
                                .keyboardShortcut(.defaultAction)
                                .disabled(isSearching.value)
                        }
                    }
                    .padding(.horizontal, 16).padding(.top, 4)
                }
                .fixedSize(horizontal: true, vertical: false)

                Divider()

                if results.value.isEmpty {
                    // maxWidth: .infinity too -- see AddClubSheet's identical fix
                    // for the same direct report; without it this hugged the
                    // left edge of its own column instead of centering.
                    ContentUnavailableView(
                        status.value == nil ? t("search.none_yet_title") : t("search.no_matches_title"),
                        systemImage: "magnifyingglass",
                        description: Text(status.value == nil
                            ? t("search.none_yet_desc")
                            : t("search.no_matches_desc", ["n": "\(searchDays)"])))
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    List(results.value) { match in
                        SearchResultRow(match: match, weather: weatherByDate.value[match.date])
                            .contentShape(Rectangle())
                            .onTapGesture { confirming.value = match }
                    }
                    .listStyle(.plain)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .padding(.top, 8)

            HStack {
                Spacer()
                Button(t("button.close")) { dismiss() }
            }
            .padding(16)
        }
        .sheetFrame(SheetSize.split)
        // Same interaction as SlotRow -- a confirming dialog, not a silent write on
        // tap, since this marks a local record of what you booked, not a real
        // pc caddie action.
        .confirmationDialog(
            confirming.value.map { t("booking.mark_title", ["time": "\(weekday($0.date)) \($0.time)"]) } ?? "",
            isPresented: Binding(get: { confirming.value != nil }, set: { if !$0 { confirming.value = nil } }),
            titleVisibility: .visible
        ) {
            if let match = confirming.value {
                Button(t("booking.confirm")) {
                    Store.confirmBooking(dbPath: dbPath, course: match.course, date: match.date, time: match.time)
                    model.reload()
                    status.value = t("search.booked", ["day": weekday(match.date), "time": match.time])
                }
            }
            Button(t("booking.not_now"), role: .cancel) {}
        }
    }

    private func runSearch() {
        isSearching.value = true
        status.value = nil
        let fromDate = today
        weatherByDate.value = Dictionary(
            uniqueKeysWithValues: Store.days(dbPath: dbPath, course: course, from: fromDate, limit: searchDays)
                .map { ($0.date, $0) })
        SearchClient.run(dbPath: dbPath, course: course, clubSlug: clubSlug, from: fromDate, days: searchDays,
                          criteria: criteria.value) { matches, error in
            isSearching.value = false
            if let matches {
                results.value = matches
                status.value = matches.isEmpty ? t("search.no_matches_status") : nil
            } else {
                results.value = []
                status.value = error ?? t("error.generic")
            }
        }
    }
}

private struct SearchResultRow: View {
    @ObservedObject private var units = AppUnits.shared
    @ObservedObject private var language = AppLanguage.shared
    let match: SearchMatch
    let weather: Day?

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(weekday(match.date)).font(scaledFont(.caption)).bold()
                Text(match.time).font(scaledFont(.caption, design: .monospaced)).foregroundStyle(.secondary)
            }
            // Trimmed from 100 -- this row now lives in Search's own narrower
            // results column (see SheetSize.split), and every real weekday
            // label this shows ("Sa. 19 Sept.") fits comfortably under 90.
            .frame(width: 90, alignment: .leading)

            if let w = weather?.weather(at: match.time) {
                Image(systemName: icon(for: w.code)).font(scaledFont(.caption)).foregroundStyle(.secondary)
                if let tempC = w.temperatureC {
                    Text(String(format: "%.0f°", Units.temperature(tempC, units.value)))
                        .font(scaledFont(.caption2)).foregroundStyle(.secondary)
                        .frame(width: 28, alignment: .leading)
                }
            }

            Text(t("search.open_spots", ["n": "\(match.capacity - match.booked)"])).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                .frame(width: 48, alignment: .leading)

            if !match.reasons.isEmpty {
                Text(match.reasons.joined(separator: ", "))
                    .font(scaledFont(.caption2)).foregroundStyle(.tertiary).lineLimit(1)
            }

            Spacer()
            Image(systemName: "chevron.right").font(scaledFont(.caption2)).foregroundStyle(.tertiary)
        }
        .padding(.vertical, 3)
    }
}
