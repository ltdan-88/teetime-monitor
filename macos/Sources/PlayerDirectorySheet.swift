import SwiftUI

/// Which field the directory is currently ordered by -- mirrors
/// `known_players_screen.py`'s own `_SORT_KEYS` dict exactly (same five fields,
/// same meaning), so the two front ends behave identically rather than each
/// re-inventing their own idea of "sortable."
private enum PlayerSortField: String, CaseIterable, Identifiable {
    case name, gender, memberStatus, handicap, friend
    var id: String { rawValue }

    var label: String {
        switch self {
        case .name: return t("players.sort.name")
        case .gender: return t("players.sort.gender")
        case .memberStatus: return t("players.sort.member_status")
        case .handicap: return t("players.sort.handicap")
        case .friend: return t("players.sort.friend")
        }
    }

    /// Same tuple-key shape `known_players_screen.py`'s `_SORT_KEYS` uses: a real
    /// tiebreaker (family name) after the primary field, so two players sharing a
    /// gender/status/handicap still land in a stable, predictable order rather than
    /// whatever order `Array.sorted` happened to leave them in.
    func key(_ p: KnownPlayer) -> (Int, Double, String, String) {
        let tiebreak = familyName(p.name).lowercased()
        switch self {
        case .name: return (0, 0, tiebreak, p.name.lowercased())
        case .gender: return (0, 0, (p.gender ?? "") + tiebreak, tiebreak)
        case .memberStatus: return (0, 0, (p.memberStatus ?? "") + tiebreak, tiebreak)
        // `handicap == nil` sorts to the same end regardless of ascending/descending --
        // see known_players_screen.py's own _SORT_KEYS["handicap"] docstring for why
        // this needs to be baked into the key rather than left to plain reversal.
        case .handicap: return (p.handicap == nil ? 1 : 0, p.handicap ?? 0, tiebreak, tiebreak)
        case .friend: return (p.isFriend ? 0 : 1, 0, tiebreak, tiebreak)
        }
    }
}

/// Every real player name this club's own scrapes have ever seen (2026-09-27, only
/// possible from an authenticated scrape -- see `scraper.scrape_schedule()`'s own
/// `client` parameter), browsable here with the ability to mark some as friends.
/// Reached from `PreferencesSheet`'s own "Priorities" section and directly from
/// Overview's own toolbar/menu (see `AppCommands.onPlayerDirectory`).
///
/// Sortable and searchable (2026-09-27, direct follow-up: "i need the player
/// directory to be sorted alphabetically by family name. better: make the player
/// directory sortable and searchable") -- default order is alphabetical by family
/// name (`familyName(_:)`'s own last-whitespace-token rule), a search field filters
/// by substring on the full name, and a sort `Picker` plus a direction toggle
/// re-orders by any column, mirroring `KnownPlayersScreen`'s own TUI behavior
/// exactly (`PlayerSortField` above is this sheet's own copy of that screen's
/// `_SORT_KEYS`).
///
/// Gender/member-status/handicap columns (2026-09-27, direct follow-up: "are there
/// any further scrapable information... worth to display?" -- checked live against
/// the real authenticated tee sheet HTML) show whatever pc caddie's own markup
/// carried for that player's most recent sighting; any of the three can be blank.
///
/// Reads/writes go straight to SQLite via `Store.knownPlayers()`/`setPlayerFriend()`
/// -- no CLI script needed, same as `Store.confirmBooking()`/`cancelBooking()`
/// already do for simple writes elsewhere in this app. A friend toggle takes effect
/// immediately on tap, no separate Save step, matching the checkbox-like shape the
/// action itself implies.
struct PlayerDirectorySheet: View {
    @Environment(\.dismiss) private var dismiss
    let dbPath: String
    @ObservedObject private var language = AppLanguage.shared

    @StateObject private var players = Box<[KnownPlayer]>([])
    @StateObject private var query = Box("")
    @StateObject private var sortField = Box(PlayerSortField.name)
    @StateObject private var sortReversed = Box(false)

    private var visiblePlayers: [KnownPlayer] {
        var visible = players.value
        let trimmed = query.value.trimmingCharacters(in: .whitespaces)
        if !trimmed.isEmpty {
            visible = visible.filter { $0.name.localizedCaseInsensitiveContains(trimmed) }
        }
        let field = sortField.value
        visible.sort { field.key($0) < field.key($1) }
        if sortReversed.value { visible.reverse() }
        return visible
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(t("players.title")).font(scaledFont(.title2)).bold().padding([.top, .horizontal], 16)
            Text(t("players.intro"))
                .font(scaledFont(.caption2)).foregroundStyle(.secondary)
                .padding(.horizontal, 16).padding(.top, 2)

            HStack {
                TextField(t("players.search_placeholder"), text: $query.value)
                    .textFieldStyle(.roundedBorder)
                Spacer(minLength: 12)
                Picker("", selection: $sortField.value) {
                    ForEach(PlayerSortField.allCases) { Text($0.label).tag($0) }
                }
                .labelsHidden()
                .fixedSize()
                Button {
                    sortReversed.value.toggle()
                } label: {
                    Image(systemName: sortReversed.value ? "arrow.down" : "arrow.up")
                }
                .help(t(sortReversed.value ? "players.sort.descending" : "players.sort.ascending"))
            }
            .padding(.horizontal, 16).padding(.top, 8)

            if players.value.isEmpty {
                Spacer()
                Text(t("players.empty")).font(scaledFont(.body)).foregroundStyle(.secondary)
                Spacer()
            } else if visiblePlayers.isEmpty {
                Spacer()
                Text(t("players.no_matches")).font(scaledFont(.body)).foregroundStyle(.secondary)
                Spacer()
            } else {
                List(visiblePlayers) { player in
                    PlayerRow(player: player) { toggleFriend(player) }
                }
                .padding(.top, 4)
            }

            HStack {
                Spacer()
                Button(t("button.cancel")) { dismiss() }.keyboardShortcut(.defaultAction)
            }
            .padding(16)
        }
        .sheetFrame(SheetSize.directory)
        .onAppear { reload() }
    }

    private func reload() {
        players.value = Store.knownPlayers(dbPath: dbPath)
    }

    private func toggleFriend(_ player: KnownPlayer) {
        Store.setPlayerFriend(dbPath: dbPath, name: player.name, isFriend: !player.isFriend)
        reload()
    }
}

struct PlayerRow: View {
    let player: KnownPlayer
    let onToggle: () -> Void

    var body: some View {
        HStack {
            PlayerRowColumns(player: player)
            Spacer(minLength: 8)
            Button(player.isFriend ? t("players.unmark_friend") : t("players.mark_friend"), action: onToggle)
        }
        .padding(.vertical, 2)
    }
}

/// The four fixed-width data columns, split out from `PlayerRow` itself so
/// `VisualRegressionRunner`'s own fixture can render exactly these -- and not the
/// trailing `Button` -- since that runner's own docstring already states its scope
/// as "pure-SwiftUI views... no AppKit-bridged control": a `Button` is backed by a
/// real `NSButton`, and rendering one through `ImageRenderer` off-screen isn't
/// confirmed to be reliable or OS-version-stable the way `Text`/`Image` are (see
/// that file's "Scope, stated plainly" section for the identical reasoning already
/// applied to the course `Picker`). Testing the four `Text` columns here is exactly
/// what would catch a real column-alignment regression; testing the button's own
/// pixels would risk a flaky failure for a reason that has nothing to do with this
/// row's actual layout.
struct PlayerRowColumns: View {
    @ObservedObject private var language = AppLanguage.shared
    let player: KnownPlayer

    private var genderLabel: String {
        guard let gender = player.gender else { return "" }
        return t("players.gender.\(gender)")
    }

    private var memberStatusLabel: String {
        guard let memberStatus = player.memberStatus else { return "" }
        return t("players.member_status.\(memberStatus)")
    }

    private var handicapLabel: String {
        guard let handicap = player.handicap else { return "" }
        return String(format: "%.1f", handicap)
    }

    var body: some View {
        Group {
            Text(player.name).font(scaledFont(.body)).lineLimit(1)
                .frame(width: AppScale.shared.scaled(Metrics.playerName), alignment: .leading)
            Text(genderLabel).font(scaledFont(.caption)).foregroundStyle(.secondary).lineLimit(1)
                .frame(width: AppScale.shared.scaled(Metrics.playerGender), alignment: .leading)
            Text(memberStatusLabel).font(scaledFont(.caption)).foregroundStyle(.secondary).lineLimit(1)
                .frame(width: AppScale.shared.scaled(Metrics.playerMemberStatus), alignment: .leading)
            Text(handicapLabel).font(scaledFont(.caption)).foregroundStyle(.secondary).lineLimit(1)
                .frame(width: AppScale.shared.scaled(Metrics.playerHandicap), alignment: .trailing)
        }
    }
}
