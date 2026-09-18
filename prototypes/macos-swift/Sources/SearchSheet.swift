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

            Form {
                Section(t("search.section.criteria")) {
                    Stepper(t("prefs.min_open_spots", ["n": "\(criteria.value.minOpenSpots)"]),
                            value: $criteria.value.minOpenSpots, in: 1...4)
                    TimeWindowRow(label: t("prefs.weekday"), after: $criteria.value.weekdayAfter,
                                  before: $criteria.value.weekdayBefore)
                    TimeWindowRow(label: t("prefs.weekend"), after: $criteria.value.weekendAfter,
                                  before: $criteria.value.weekendBefore)
                    Stepper(t("prefs.buffer_before", ["n": "\(criteria.value.bufferBeforeMinutes)"]),
                            value: $criteria.value.bufferBeforeMinutes, in: 0...60, step: 5)
                    Stepper(t("prefs.buffer_after", ["n": "\(criteria.value.bufferAfterMinutes)"]),
                            value: $criteria.value.bufferAfterMinutes, in: 0...60, step: 5)
                }
            }
            .formStyle(.grouped)

            HStack {
                if let status = status.value { Text(status).font(scaledFont(.caption)).foregroundStyle(.secondary) }
                Spacer()
                if isSearching.value { ProgressView().controlSize(.small) }
                Button(t("search.button")) { runSearch() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(isSearching.value)
            }
            .padding(.horizontal, 16).padding(.top, 4)

            Divider().padding(.top, 8)

            if results.value.isEmpty {
                ContentUnavailableView(
                    status.value == nil ? t("search.none_yet_title") : t("search.no_matches_title"),
                    systemImage: "magnifyingglass",
                    description: Text(status.value == nil
                        ? t("search.none_yet_desc")
                        : t("search.no_matches_desc", ["n": "\(searchDays)"])))
                    .frame(maxHeight: .infinity)
            } else {
                List(results.value) { match in
                    SearchResultRow(match: match, weather: weatherByDate.value[match.date])
                        .contentShape(Rectangle())
                        .onTapGesture { confirming.value = match }
                }
                .listStyle(.plain)
                .frame(maxHeight: .infinity)
            }

            HStack {
                Spacer()
                Button(t("button.close")) { dismiss() }
            }
            .padding(16)
        }
        .sheetFrame(SheetSize.browser)
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
    let match: SearchMatch
    let weather: Day?

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(weekday(match.date)).font(scaledFont(.caption)).bold()
                Text(match.time).font(scaledFont(.caption, design: .monospaced)).foregroundStyle(.secondary)
            }
            .frame(width: 100, alignment: .leading)

            if let w = weather?.weather(at: match.time) {
                Image(systemName: icon(for: w.code)).font(scaledFont(.caption)).foregroundStyle(.secondary)
                if let tempC = w.temperatureC {
                    Text(String(format: "%.0f°", Units.temperature(tempC, units.value)))
                        .font(scaledFont(.caption2)).foregroundStyle(.secondary)
                        .frame(width: 28, alignment: .leading)
                }
            }

            Text(t("search.open_spots", ["n": "\(match.capacity - match.booked)"])).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                .frame(width: 56, alignment: .leading)

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
