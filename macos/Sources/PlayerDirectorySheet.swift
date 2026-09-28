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

/// Groups `players` (already sorted the way the caller wants) into adjacent runs
/// sharing the same first letter of `familyName(_:)`, uppercased -- one entry per
/// letter, in first-seen order, so this reflects whatever order `players` already
/// came in rather than re-sorting. "#" collects anything whose family name starts
/// with something that isn't a letter (a name is never actually empty, but this is
/// the same non-letter fallback bucket a real Contacts app uses). A free function,
/// not a `PlayerDirectorySheet` method, so `TeetimeMonitorCoreTests` can exercise
/// the grouping itself directly, without a live sheet or its private state.
func groupPlayersByFamilyNameLetter(_ players: [KnownPlayer]) -> [(letter: String, players: [KnownPlayer])] {
    var groups: [(letter: String, players: [KnownPlayer])] = []
    for player in players {
        let initial = familyName(player.name).uppercased().first
        let letter = (initial != nil && initial!.isLetter) ? String(initial!) : "#"
        if groups.last?.letter == letter {
            groups[groups.count - 1].players.append(player)
        } else {
            groups.append((letter: letter, players: [player]))
        }
    }
    return groups
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

    /// A-Z section headers plus a jump strip down the trailing edge, the same shape
    /// every contacts-style directory uses -- direct request (2026-09-28): "make the
    /// player directory a feature[sic] similar features like in common contact
    /// directories (e.g. alphabet letters as separators)". Only meaningful sorted by
    /// name (grouping a handicap- or gender-sorted list by family-name letter would
    /// scatter one contact's own initial across the whole list instead of collecting
    /// it) -- `sectionsShown` below is what actually gates showing headers/strip;
    /// the grouping itself (`groupPlayersByFamilyNameLetter`, a free function so
    /// `TeetimeMonitorCoreTests` can exercise it directly without a live sheet) just
    /// collects whatever's currently visible into adjacent same-letter runs, which
    /// only forms real letter-blocks when the list is already name-sorted.
    private var groupedPlayers: [(letter: String, players: [KnownPlayer])] {
        groupPlayersByFamilyNameLetter(visiblePlayers)
    }

    /// Section headers/jump strip only show for the sort order they're actually
    /// correct for -- see `groupedPlayers`' own docstring.
    private var sectionsShown: Bool { sortField.value == .name }

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
                ScrollViewReader { proxy in
                    HStack(spacing: 0) {
                        List {
                            ForEach(groupedPlayers, id: \.letter) { group in
                                if sectionsShown {
                                    Section(header: Text(group.letter)) {
                                        ForEach(group.players) { player in
                                            PlayerRow(player: player) { toggleFriend(player) }
                                        }
                                    }
                                    .id(group.letter)
                                } else {
                                    ForEach(group.players) { player in
                                        PlayerRow(player: player) { toggleFriend(player) }
                                    }
                                }
                            }
                        }
                        if sectionsShown {
                            AlphabetIndexStrip(letters: groupedPlayers.map(\.letter)) { letter in
                                withAnimation { proxy.scrollTo(letter, anchor: .top) }
                            }
                        }
                    }
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

/// The tappable A-Z jump column down the trailing edge of the directory --
/// Contacts.app's own "index" strip. Only the letters actually present
/// (`groupedPlayers`' own keys), not the full alphabet padded with dead entries --
/// with a real, if small, directory this is already every letter that matters, and
/// a tap that does nothing (an empty letter) is worse than a slightly shorter strip.
private struct AlphabetIndexStrip: View {
    let letters: [String]
    let onTap: (String) -> Void

    var body: some View {
        VStack(spacing: 2) {
            ForEach(letters, id: \.self) { letter in
                Text(letter)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 16)
                    .contentShape(Rectangle())
                    .onTapGesture { onTap(letter) }
            }
        }
        .padding(.vertical, 8)
        .padding(.trailing, 6)
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
