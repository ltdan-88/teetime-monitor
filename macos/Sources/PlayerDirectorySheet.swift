import SwiftUI

/// Every real player name this club's own scrapes have ever seen (2026-09-27, only
/// possible from an authenticated scrape -- see `scraper.scrape_schedule()`'s own
/// `client` parameter), browsable here with the ability to mark some as friends.
/// Reached from `PreferencesSheet`'s own "Priorities" section, right next to the
/// `prioritize_friends` toggle it finally gives real effect to (see
/// `recommend.ranked_matches()`'s own `friend_names` parameter for the deterministic
/// sort, and `ai_assist._describe_candidate()`'s own docstring for why only a
/// *count*, never a name, ever reaches an AI prompt).
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

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(t("players.title")).font(scaledFont(.title2)).bold().padding([.top, .horizontal], 16)
            Text(t("players.intro"))
                .font(scaledFont(.caption2)).foregroundStyle(.secondary)
                .padding(.horizontal, 16).padding(.top, 2)

            if players.value.isEmpty {
                Spacer()
                Text(t("players.empty")).font(scaledFont(.body)).foregroundStyle(.secondary)
                Spacer()
            } else {
                List(players.value) { player in
                    PlayerRow(player: player) { toggleFriend(player) }
                }
            }

            HStack {
                Spacer()
                Button(t("button.cancel")) { dismiss() }.keyboardShortcut(.defaultAction)
            }
            .padding(16)
        }
        .sheetFrame(SheetSize.browser)
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

private struct PlayerRow: View {
    @ObservedObject private var language = AppLanguage.shared
    let player: KnownPlayer
    let onToggle: () -> Void

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 1) {
                Text(player.name).font(scaledFont(.body))
                Text(String(player.lastSeen.prefix(10))) // ISO timestamp -> just the date
                    .font(scaledFont(.caption)).foregroundStyle(.secondary)
            }
            Spacer()
            Button(player.isFriend ? t("players.unmark_friend") : t("players.mark_friend"), action: onToggle)
        }
        .padding(.vertical, 2)
    }
}
