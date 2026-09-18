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
            Text("Search").font(.title2).bold().padding([.top, .horizontal], 16)
            Text("Pre-filled from your saved Preferences — edit for this one search.")
                .font(.caption2).foregroundStyle(.secondary).padding(.horizontal, 16).padding(.top, 2)

            Form {
                Section("Criteria") {
                    Stepper("Min open spots: \(criteria.value.minOpenSpots)",
                            value: $criteria.value.minOpenSpots, in: 1...4)
                    TimeWindowRow(label: "Weekday", after: $criteria.value.weekdayAfter,
                                  before: $criteria.value.weekdayBefore)
                    TimeWindowRow(label: "Weekend", after: $criteria.value.weekendAfter,
                                  before: $criteria.value.weekendBefore)
                    Stepper("Buffer before: \(criteria.value.bufferBeforeMinutes) min",
                            value: $criteria.value.bufferBeforeMinutes, in: 0...60, step: 5)
                    Stepper("Buffer after: \(criteria.value.bufferAfterMinutes) min",
                            value: $criteria.value.bufferAfterMinutes, in: 0...60, step: 5)
                }
            }
            .formStyle(.grouped)

            HStack {
                if let status = status.value { Text(status).font(.caption).foregroundStyle(.secondary) }
                Spacer()
                if isSearching.value { ProgressView().controlSize(.small) }
                Button("Search") { runSearch() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(isSearching.value)
            }
            .padding(.horizontal, 16).padding(.top, 4)

            Divider().padding(.top, 8)

            if results.value.isEmpty {
                ContentUnavailableView(
                    status.value == nil ? "No search run yet" : "No matches",
                    systemImage: "magnifyingglass",
                    description: Text(status.value == nil
                        ? "Adjust the criteria above and press Search."
                        : "Nothing in the next \(searchDays) days matches these criteria."))
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
                Button("Close") { dismiss() }
            }
            .padding(16)
        }
        .frame(width: 640, height: 680)
        // Same interaction as SlotRow -- a confirming dialog, not a silent write on
        // tap, since this marks a local record of what you booked, not a real
        // pc caddie action.
        .confirmationDialog(
            confirming.value.map { "Mark \($0.date) \($0.time) as your booking?" } ?? "",
            isPresented: Binding(get: { confirming.value != nil }, set: { if !$0 { confirming.value = nil } }),
            titleVisibility: .visible
        ) {
            if let match = confirming.value {
                Button("Confirm") {
                    Store.confirmBooking(dbPath: dbPath, course: match.course, date: match.date, time: match.time)
                    model.reload()
                    status.value = "Booked \(weekday(match.date)) at \(match.time)."
                }
            }
            Button("Not now", role: .cancel) {}
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
                status.value = matches.isEmpty ? "No matches." : nil
            } else {
                results.value = []
                status.value = error ?? "Something went wrong."
            }
        }
    }
}

private struct SearchResultRow: View {
    let match: SearchMatch
    let weather: Day?

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(weekday(match.date)).font(.caption).bold()
                Text(match.time).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary)
            }
            .frame(width: 100, alignment: .leading)

            if let w = weather?.weather(at: match.time) {
                Image(systemName: icon(for: w.code)).font(.caption).foregroundStyle(.secondary)
                if let t = w.temperatureC {
                    Text(String(format: "%.0f°", t)).font(.caption2).foregroundStyle(.secondary)
                        .frame(width: 28, alignment: .leading)
                }
            }

            Text("\(match.capacity - match.booked) open").font(.caption2).foregroundStyle(.secondary)
                .frame(width: 56, alignment: .leading)

            if !match.reasons.isEmpty {
                Text(match.reasons.joined(separator: ", "))
                    .font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
            }

            Spacer()
            Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
        }
        .padding(.vertical, 3)
    }
}
