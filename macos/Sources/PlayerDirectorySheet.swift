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

/// One (date, time) a double-clicked player is actually booked into, within the
/// currently-loaded window -- see `PlayerDirectorySheet.handleDoubleClick(_:)`.
/// Not `private`: `TeetimeMonitorCoreTests` constructs these directly to check
/// `playerSlotHits(for:in:)`'s own output.
struct PlayerSlotHit: Identifiable, Hashable {
    let date: String
    let time: String
    var id: String { date + time }
}

/// Every (date, time) `playerName` is actually booked into, across `days` -- the
/// currently-loaded window only (`OverviewModel.visibleDays`), not full scrape
/// history, matching direct scope confirmed 2026-09-28: "scope: only currently
/// loaded window." A free function, not a `PlayerDirectorySheet` method, for the
/// same reason `groupPlayersByFamilyNameLetter` above is one -- so
/// `TeetimeMonitorCoreTests` can exercise it directly against plain `Day`/`Slot`
/// fixtures, no live sheet or `OverviewModel` needed.
func playerSlotHits(for playerName: String, in days: [Day]) -> [PlayerSlotHit] {
    days.flatMap { day in
        day.slots.filter { $0.players.contains(playerName) }
            .map { PlayerSlotHit(date: day.date, time: $0.time) }
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
    // Optional, not required -- this sheet is reachable two ways (Overview's own
    // toolbar/Actions menu, and PreferencesSheet's "Priorities" section), and only
    // the first hands over a live `OverviewModel` to jump through. Double-click-to-
    // focus (below) is scoped to that one: opened from Preferences, a match has
    // nowhere to scroll to anyway (Preferences isn't looking at the day list), so
    // it quietly does nothing there rather than needing Preferences to also carry
    // a model just to dismiss itself out of the way for a nested sheet's jump.
    // Plain reference, not @ObservedObject -- SwiftUI's property wrapper requires
    // its wrapped type itself to conform to ObservableObject, which an Optional
    // never does even when what it wraps does. No live re-render off this sheet's
    // own body needs it anyway: `handleDoubleClick(_:)` below only ever reads
    // `model.visibleDays` once per click and writes `model.scrollRequest` once.
    let model: OverviewModel?
    // Picker mode (2026-09-28, direct follow-up: "the player dropdown in the
    // search screen is a bit too long to use... any better alternatives?"): this
    // same searchable/sortable/A-Z-indexed browser, reused as a picker for
    // SearchSheet's own "Player" field instead of one flat `Picker` over
    // potentially hundreds of names. Non-nil switches every row from "tap toggles
    // friend" to "tap picks this name and dismisses" -- see `PlayerRow`'s own
    // `onSelect` docstring for why that's a single tap here (not the double-click
    // `onFocus` uses), and `body`'s own title/intro swap for the rest of what
    // changes in this mode.
    let onSelect: ((String) -> Void)?
    @ObservedObject private var language = AppLanguage.shared

    // Explicit, not relying on the synthesized memberwise init -- this struct mixes
    // plain stored properties (dbPath, model, onSelect) with several
    // @StateObject-wrapped ones further down, and letting a property default via
    // `= nil` on its own declaration didn't reliably produce a callable parameter
    // alongside them (found live: "extra argument 'model' in call" at the one
    // real call site that passed it, before this same fix). Spelling the real
    // inputs out here is also just clearer than trusting synthesis to guess which
    // stored properties are "the API."
    init(dbPath: String, model: OverviewModel? = nil, onSelect: ((String) -> Void)? = nil) {
        self.dbPath = dbPath
        self.model = model
        self.onSelect = onSelect
    }

    @StateObject private var players = Box<[KnownPlayer]>([])
    @StateObject private var query = Box("")
    @StateObject private var sortField = Box(PlayerSortField.name)
    @StateObject private var sortReversed = Box(false)
    @StateObject private var focusChoices = Box<[PlayerSlotHit]>([])
    @StateObject private var focusNoneNotice = Box(false)
    @StateObject private var selectedName = Box<String?>(nil)

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
            Text(t(onSelect == nil ? "players.title" : "players.picker_title"))
                .font(scaledFont(.title2)).bold().padding([.top, .horizontal], 16)
            Text(t(onSelect == nil ? "players.intro" : "players.picker_intro"))
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
                        // ScrollView + LazyVStack, not List: the List's NSOutlineView backing
                        // crashed inside SwiftUI (ViewListTree.visitItem assertion, crash
                        // report 2026-09-29) while scrolling this conditional
                        // Section/ForEach structure. The Overview already uses this shape
                        // for its pinned day headers.
                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: 0, pinnedViews: [.sectionHeaders]) {
                                ForEach(groupedPlayers, id: \.letter) { group in
                                    if sectionsShown {
                                        Section {
                                            playerRows(group.players)
                                        } header: {
                                            Text(group.letter)
                                                .font(scaledFont(.caption)).bold()
                                                .foregroundStyle(.secondary)
                                                .padding(.horizontal, 16).padding(.vertical, 3)
                                                .frame(maxWidth: .infinity, alignment: .leading)
                                                .background(Color(nsColor: .windowBackgroundColor))
                                                .id(group.letter)
                                        }
                                    } else {
                                        playerRows(group.players)
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
        // Direct request, 2026-09-28: "would it be possible to double click a
        // player in the directory and focus on their booked tee time or tee
        // times?" -- scoped to the currently-loaded window only (model.days),
        // same reasoning `groupPlayersByFamilyNameLetter` already documents for
        // other per-session-state features here: this is about what you'd act
        // on right now, not a full-history search. Multiple hits get a small
        // picker; one hit jumps straight there.
        .confirmationDialog(t("players.focus_title"),
                             isPresented: Binding(get: { !focusChoices.value.isEmpty },
                                                   set: { if !$0 { focusChoices.value = [] } })) {
            ForEach(focusChoices.value) { hit in
                Button("\(weekday(hit.date)) \(hit.time)") { jump(to: hit) }
            }
            Button(t("button.cancel"), role: .cancel) { focusChoices.value = [] }
        }
        .alert(t("players.focus_none"), isPresented: $focusNoneNotice.value) {
            Button(t("button.close"), role: .cancel) {}
        }
    }

    @ViewBuilder
    private func playerRows(_ rows: [KnownPlayer]) -> some View {
        ForEach(rows) { player in
            PlayerRow(player: player, onToggle: { toggleFriend(player) },
                      onFocus: model == nil ? nil : { handleDoubleClick(player) },
                      onSelect: onSelect == nil ? nil : { selectAndDismiss(player) },
                      isSelected: selectedName.value == player.name,
                      onClick: { selectedName.value = player.name })
                .padding(.horizontal, 12)
            Divider().padding(.leading, 16)
        }
    }

    private func handleDoubleClick(_ player: KnownPlayer) {
        guard let model else { return }
        let hits = playerSlotHits(for: player.name, in: model.visibleDays)
        if hits.isEmpty {
            focusNoneNotice.value = true
        } else if hits.count == 1 {
            jump(to: hits[0])
        } else {
            focusChoices.value = hits
        }
    }

    private func jump(to hit: PlayerSlotHit) {
        focusChoices.value = []
        model?.scrollRequest = OverviewModel.ScrollTarget(date: hit.date, time: hit.time)
        dismiss()
    }

    private func selectAndDismiss(_ player: KnownPlayer) {
        // Brief pause so the selection highlight is actually seen before the sheet
        // closes -- an instant dismiss reads as "nothing happened, it just vanished."
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            onSelect?(player.name)
            dismiss()
        }
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
    /// Double-click-to-focus (2026-09-28) -- `nil` when there's nowhere to jump to
    /// (opened from Preferences rather than the Overview, see
    /// `PlayerDirectorySheet`'s own `model` docstring), in which case this row
    /// behaves exactly as it always did. Attached to `PlayerRowColumns` alone, not
    /// this whole row -- putting it on the row would put a tap recognizer directly
    /// over the trailing friend-toggle `Button` too, and a double-click landing on
    /// that button is a real, physically-plausible way to trigger *this* gesture
    /// by accident while trying to toggle a friend twice in quick succession.
    var onFocus: (() -> Void)?
    /// Picker mode (2026-09-28) -- a *single* tap, not a double-click, since this
    /// sheet is standing in for a whole dropdown here (see `PlayerDirectorySheet`'s
    /// own `onSelect` docstring): the entire point is picking a name in one click,
    /// not two. Mutually exclusive with `onFocus` in practice (a call site sets at
    /// most one -- `PlayerDirectorySheet` never hands over a live `model` when it's
    /// also given an `onSelect`), so there's no real double-vs-single tap conflict
    /// to resolve here, just two different reasons a row can be tappable.
    var onSelect: (() -> Void)?
    /// Single click marks the row as selected (highlight) in either mode -- direct
    /// follow-up, 2026-09-29: "the player picker or player directory does not
    /// provide any feedback when selecting a row."
    var isSelected: Bool = false
    var onClick: (() -> Void)?

    @ObservedObject private var theme = AppTheme.shared
    @StateObject private var isHovering = Box(false)

    var body: some View {
        HStack {
            HStack {
                PlayerRowColumns(player: player)
                Spacer(minLength: 8)
            }
            .contentShape(Rectangle())
            .onTapGesture(count: 2) { onFocus?() }
            .onTapGesture {
                onClick?()
                onSelect?()
            }
            // Hidden entirely in picker mode, not just inert -- this sheet's whole
            // reason for being open is "pick a name," and a second, unrelated
            // action sitting right next to that choice is exactly the kind of
            // clutter the original report ("a bit too long to use") was about.
            if onSelect == nil {
                Button(player.isFriend ? t("players.unmark_friend") : t("players.mark_friend"), action: onToggle)
            }
        }
        .padding(.vertical, 2)
        .padding(.horizontal, 4)
        .background(
            isSelected ? theme.colors.accent.opacity(0.4)
                : (isHovering.value ? theme.colors.accent.opacity(0.12) : Color.clear),
            in: RoundedRectangle(cornerRadius: 4)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 4).stroke(theme.colors.accent, lineWidth: 1.5)
                .opacity(isSelected ? 1 : 0)
        )
        .onHover { isHovering.value = $0 }
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
