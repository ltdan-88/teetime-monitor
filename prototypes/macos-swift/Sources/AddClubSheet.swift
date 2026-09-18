import SwiftUI

/// Add-a-club (Tier 2, 2026-09-18) -- mirrors `ClubBrowserScreen`'s directory
/// search: type a name (matched against the cached/bundled directory locally, see
/// `ClubDirectoryStore`), a bare club id, or a pasted pc caddie booking link (the
/// same `/clubs/<id>/` recognition `looks_like_club_id()` does, for the same
/// reason -- a first-time user's actual starting point is their own club's link,
/// not a memorized 7-digit number). "Refresh directory" and "Add" are the two
/// pieces that shell out to Python (`DirectoryClient`/`AddClubClient`) -- a live
/// authenticated fetch and a best-effort geocoding lookup, respectively.
struct AddClubSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var model: OverviewModel

    @StateObject private var query = Box("")
    @StateObject private var directory = Box<[DirectoryEntry]>([])
    @StateObject private var source = Box(ClubDirectoryStore.Source.none)
    @StateObject private var fetchedAt = Box<String?>(nil)
    @StateObject private var isRefreshing = Box(false)
    @StateObject private var addingClubID = Box<String?>(nil)
    @StateObject private var status = Box<String?>(nil)

    private var trimmedQuery: String { query.value.trimmingCharacters(in: .whitespaces) }
    private var directIDMatch: String? { ClubDirectoryStore.looksLikeClubID(query.value) }
    private var searchResults: [DirectoryEntry] { ClubDirectoryStore.search(directory.value, query: query.value) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Add a Club").font(scaledFont(.title2)).bold().padding([.top, .horizontal], 16)

            HStack {
                sourceCaption
                Spacer()
                if isRefreshing.value { ProgressView().controlSize(.small) }
                Button("Refresh directory") { refresh() }.disabled(isRefreshing.value)
            }
            .padding(.horizontal, 16).padding(.top, 4)

            TextField("Search by name, or paste a club id / booking link", text: $query.value)
                .textFieldStyle(.roundedBorder)
                .padding(16)

            if let status = status.value {
                Text(status).font(scaledFont(.caption)).foregroundStyle(.secondary)
                    .padding(.horizontal, 16).padding(.bottom, 8)
            }

            if trimmedQuery.isEmpty {
                ContentUnavailableView("Search for a club", systemImage: "magnifyingglass",
                    description: Text("Type a name, a club id, or paste a booking link."))
                    .frame(maxHeight: .infinity)
            } else if directIDMatch == nil && searchResults.isEmpty {
                ContentUnavailableView("No matches", systemImage: "magnifyingglass",
                    description: Text("Nothing in the directory matches \u{201c}\(trimmedQuery)\u{201d}."))
                    .frame(maxHeight: .infinity)
            } else {
                List {
                    if let id = directIDMatch {
                        AddClubRow(clubID: id, name: "Open club \(id) directly",
                                   isAdding: addingClubID.value == id) { add(clubID: id, name: "") }
                    }
                    ForEach(searchResults) { entry in
                        AddClubRow(clubID: entry.clubID, name: entry.name,
                                   isAdding: addingClubID.value == entry.clubID) {
                            add(clubID: entry.clubID, name: entry.name)
                        }
                    }
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
        .sheetFrame(SheetSize.browser)
        .onAppear { load() }
    }

    private var sourceCaption: some View {
        Group {
            switch source.value {
            case .live:
                Text("Live directory, \(directory.value.count) clubs"
                     + (fetchedAt.value.map { " — fetched \($0)" } ?? ""))
            case .seed:
                Text("Offline snapshot, \(directory.value.count) clubs — refresh for the live list")
            case .none:
                Text("No directory yet — refresh, or type a club id / booking link")
            }
        }
        .font(scaledFont(.caption2)).foregroundStyle(.secondary)
    }

    private func load() {
        let (src, fetched, clubs) = ClubDirectoryStore.directory()
        source.value = src
        fetchedAt.value = fetched
        directory.value = clubs
    }

    private func refresh() {
        isRefreshing.value = true
        status.value = nil
        DirectoryClient.refresh(fallbackClubID: directIDMatch) { count, error in
            isRefreshing.value = false
            if let count {
                status.value = "Refreshed — \(count) clubs."
                load()
            } else {
                status.value = error ?? "Something went wrong."
            }
        }
    }

    private func add(clubID: String, name: String) {
        addingClubID.value = clubID
        status.value = nil
        AddClubClient.add(clubID: clubID, name: name) { slug, error in
            addingClubID.value = nil
            if slug != nil {
                // A new clubs/*.yaml just appeared -- Store.clubs() needs re-reading
                // for it to show up in the toolbar picker.
                model.load()
                status.value = "Added \(name.isEmpty ? clubID : name)."
            } else {
                status.value = error ?? "Something went wrong."
            }
        }
    }
}

private struct AddClubRow: View {
    let clubID: String
    let name: String
    let isAdding: Bool
    let onAdd: () -> Void

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 1) {
                Text(name).font(scaledFont(.body))
                Text(clubID).font(scaledFont(.caption)).foregroundStyle(.secondary)
            }
            Spacer()
            if isAdding { ProgressView().controlSize(.small) }
            Button("Add", action: onAdd).disabled(isAdding)
        }
        .padding(.vertical, 2)
    }
}
