import SwiftUI

// WMO weather codes -> an icon, same mapping weather_icons.py uses.
func icon(for code: Int?) -> String {
    switch code ?? -1 {
    case 0: return "sun.max.fill"
    case 1, 2: return "cloud.sun.fill"
    case 3: return "cloud.fill"
    case 45, 48: return "cloud.fog.fill"
    case 51...57: return "cloud.drizzle.fill"
    case 61...67, 80...82: return "cloud.rain.fill"
    case 71...77, 85, 86: return "cloud.snow.fill"
    case 95...99: return "cloud.bolt.rain.fill"
    default: return "questionmark"
    }
}

func fillColor(_ ratio: Double) -> Color {
    ratio >= 1.0 ? .red : (ratio >= 0.5 ? .orange : .green)
}

func weekday(_ iso: String) -> String {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
    guard let d = f.date(from: iso) else { return iso }
    let o = DateFormatter(); o.dateFormat = "EEE d MMM"
    return o.string(from: d)
}

/// One wrapped line explaining every icon/figure the day list uses -- the exact
/// same role `tui.py`'s `OVERVIEW_LEGEND` plays under the TUI's own table, kept to
/// the subset this card-based view actually shows.
struct LegendLine: View {
    @ObservedObject private var units = AppUnits.shared

    // Computed, not a stored `let`: the temperature/wind labels state the current
    // unit, so they have to follow a Units change the same way the numbers do.
    private var entries: [(icon: String, text: String)] {
        [
            ("thermometer.medium", "hi/lo \(Units.temperatureSymbol(units.value))"),
            ("drop.fill", "rain % (🌧 ≥50%)"),
            ("wind", "wind \(Units.windSymbol(units.value)) (💨 ≥30)"),
            ("sunrise.fill", "sunrise"),
            ("sunset.fill", "sunset"),
            ("flag.fill", "your booking"),
        ]
    }

    var body: some View {
        // Horizontal scroll rather than a wrapping HStack (SwiftUI has no built-in
        // flow layout without iOS 16/macOS 13's Layout protocol boilerplate) -- at
        // the window's minimum width this doesn't all fit, and a silently
        // truncated legend defeats the point more than a scrollable one would.
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                ForEach(entries, id: \.text) { entry in
                    HStack(spacing: 3) {
                        Image(systemName: entry.icon)
                        Text(entry.text)
                    }
                }
            }
        }
        .font(scaledFont(.caption2)).foregroundStyle(.tertiary)
    }
}

struct HeatStrip: View {
    let buckets: [Double?]
    @ObservedObject private var scale = AppScale.shared
    var body: some View {
        HStack(spacing: 2) {
            ForEach(Array(buckets.enumerated()), id: \.offset) { _, value in
                RoundedRectangle(cornerRadius: 2)
                    .fill(value.map(fillColor) ?? Color.secondary.opacity(0.18))
                    .frame(width: scale.scaled(Metrics.heatBlockWidth),
                           height: scale.scaled(Metrics.heatBlockHeight))
            }
        }
    }
}

struct SlotRow: View {
    let slot: Slot
    let day: Day
    @ObservedObject var model: OverviewModel
    @ObservedObject private var scale = AppScale.shared
    @ObservedObject private var units = AppUnits.shared
    @StateObject private var showingConfirm = Box(false)

    var isMine: Bool { day.bookedTime == slot.time }
    var isPastSunset: Bool {
        guard let sunset = day.sunset else { return false }
        return slot.time > sunset
    }

    var body: some View {
        HStack(spacing: 10) {
            Text(slot.time)
                .font(scaledFont(.caption, design: .monospaced))
                .fontWeight(isMine ? .bold : .regular)
                .frame(width: scale.scaled(Metrics.slotTime), alignment: .leading)

            if slot.isBlocked {
                Text(slot.blockReason?.isEmpty == false ? slot.blockReason! : "not bookable")
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary).italic()
            } else {
                HStack(spacing: 3) {
                    ForEach(0..<max(slot.capacity, 1), id: \.self) { i in
                        RoundedRectangle(cornerRadius: 2)
                            .fill(i < slot.booked
                                  ? (isMine && i == 0 ? Color.accentColor : Color.secondary)
                                  : Color.secondary.opacity(0.18))
                            .frame(width: scale.scaled(Metrics.seatPip),
                                   height: scale.scaled(Metrics.seatPip))
                    }
                }
                Text("\(slot.capacity - slot.booked) free")
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary)
            }

            Spacer()

            // Sunrise/sunset noted on whichever slot row is actually closest to it --
            // mirrors tui._closest_slot_time()'s placement exactly, not a single
            // summary line detached from any specific time (see Day.sunriseRowTime/
            // sunsetRowTime for the tie-break rule this shares with Python).
            if slot.time == day.sunriseRowTime {
                Label("sunrise \(day.sunrise ?? "")", systemImage: "sunrise.fill")
                    .font(scaledFont(.caption2)).foregroundStyle(.orange)
            }
            if slot.time == day.sunsetRowTime {
                Label("sunset \(day.sunset ?? "")", systemImage: "sunset.fill")
                    .font(scaledFont(.caption2)).foregroundStyle(.orange)
            }
            if isMine {
                Label("you", systemImage: "flag.fill")
                    .font(scaledFont(.caption2)).foregroundStyle(Color.accentColor)
            }
            if let w = day.weather(at: slot.time) {
                Image(systemName: icon(for: w.code)).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                    .help("Condition at \(slot.time)")
                if let t = w.temperatureC {
                    Text(String(format: "%.0f°", Units.temperature(t, units.value)))
                        .font(scaledFont(.caption2)).foregroundStyle(.secondary)
                        .frame(width: scale.scaled(Metrics.slotTemp), alignment: .trailing)
                        .help("Temperature (\(Units.temperatureSymbol(units.value)))")
                }
                if let p = w.precipitationProbability {
                    // 🌧 only above the threshold -- the real number always shows, same
                    // "worth noticing at a glance flag layered on the number, not a
                    // gate on it" rule tui._slot_precipitation_cell() documents.
                    HStack(spacing: 1) {
                        if p >= 50 { Text("🌧").font(.system(size: scale.scaled(9))) }
                        Text("\(Int(p))%")
                    }
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary).frame(width: scale.scaled(Metrics.slotPrecip), alignment: .trailing)
                    .help(p >= 50 ? "Rain chance -- ≥50%, flagged" : "Rain chance")
                }
                if let wd = w.windKPH {
                    HStack(spacing: 1) {
                        if wd >= 30 { Text("💨").font(.system(size: scale.scaled(9))) }
                        Text("\(Int(Units.windSpeed(wd, units.value)))")
                    }
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary).frame(width: scale.scaled(Metrics.slotWind), alignment: .trailing)
                    // The >= 30 test stays on the raw km/h value: it mirrors
                    // tui._SLOT_WIND_ICON_THRESHOLD_KPH, which is a fixed metric
                    // threshold regardless of display units (same rule units.py's
                    // own docstring gives for not converting stored thresholds).
                    .help(wd >= 30
                          ? "Wind, \(Units.windSymbol(units.value)) -- ≥30 km/h, flagged"
                          : "Wind, \(Units.windSymbol(units.value))")
                }
            }
        }
        .padding(.vertical, 2)
        .opacity(isPastSunset ? 0.4 : 1)
        .contentShape(Rectangle())
        .onTapGesture { if !slot.isBlocked { showingConfirm.value = true } }
        // A confirming dialog, not a silent write on tap -- matches the TUI's own
        // ConfirmBookingScreen/CancelBookingScreen, which exist specifically because
        // this marks a *local* record of what you already booked on pc caddie, not a
        // real booking action; a stray tap must not silently claim or drop one.
        .confirmationDialog(
            isMine ? "Cancel your \(slot.time) booking?" : "Mark \(slot.time) as your booking?",
            isPresented: $showingConfirm.value, titleVisibility: .visible
        ) {
            if isMine {
                Button("Cancel booking", role: .destructive) {
                    Store.cancelBooking(dbPath: model.clubPath, course: model.course, date: day.date)
                    model.reload()
                }
            } else {
                Button("Confirm") {
                    Store.confirmBooking(dbPath: model.clubPath, course: model.course, date: day.date, time: slot.time)
                    model.reload()
                }
            }
            Button("Not now", role: .cancel) {}
        }
    }
}

struct DayCard: View {
    let day: Day
    @ObservedObject var model: OverviewModel
    @ObservedObject private var theme = AppTheme.shared
    @ObservedObject private var scale = AppScale.shared
    @ObservedObject private var units = AppUnits.shared
    var isOpen: Bool { model.expanded.contains(day.date) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: isOpen ? "chevron.down" : "chevron.right")
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary).frame(width: scale.scaled(Metrics.chevron))
                Text(weekday(day.date)).font(scaledFont(.headline))

                // Day-level summary -- worst condition, high/low, average rain chance,
                // peak wind, all across 08:00-20:00 -- mirrors tui._condition_cell()/
                // _temperature_cell()/_precipitation_cell()/_wind_cell() exactly (each
                // is a "worst/average across the window" figure, not one instant
                // reading), not just whatever the forecast happened to say at noon.
                //
                // Every value below is wrapped in its own icon (`Label`, not bare
                // text) and a `.help()` tooltip -- a bare "1%" or "17" reads as
                // meaningless without knowing which figure it is, same problem the
                // TUI itself solves with `OVERVIEW_LEGEND` (see the legend line under
                // the day list below for the full explanation of thresholds/markers).
                Image(systemName: icon(for: day.conditionCode)).foregroundStyle(.secondary)
                    .help("Condition (worst, 08:00–20:00)")
                if let (hi, lo) = day.tempHighLow {
                    Label("\(Int(Units.temperature(hi, units.value)))°/"
                          + "\(Int(Units.temperature(lo, units.value)))°",
                          systemImage: "thermometer.medium")
                        .font(scaledFont(.subheadline, design: .monospaced))
                        .help("High / low temperature (\(Units.temperatureSymbol(units.value))), daytime")
                }
                if let p = day.precipAvg {
                    Label("\(Int(p))%", systemImage: "drop.fill")
                        .font(scaledFont(.caption)).foregroundStyle(.secondary)
                        .help("Average rain chance, daytime")
                }
                if let wd = day.windPeak {
                    Label("\(Int(Units.windSpeed(wd, units.value)))", systemImage: "wind")
                        .font(scaledFont(.caption)).foregroundStyle(.secondary)
                        .help("Peak wind, \(Units.windSymbol(units.value)), daytime")
                }
                if let rise = day.sunrise, let set = day.sunset {
                    Text("↑\(rise) ↓\(set)").font(scaledFont(.caption2)).foregroundStyle(.tertiary)
                        .help("Sunrise / sunset")
                }

                Spacer()
                HeatStrip(buckets: day.heatStrip)

                if let t = day.bookedTime {
                    Label(t, systemImage: "flag.fill")
                        .font(scaledFont(.caption)).padding(.horizontal, 7).padding(.vertical, 3)
                        .background(Color.accentColor.opacity(0.15), in: Capsule())
                        .foregroundStyle(Color.accentColor)
                }
            }
            .contentShape(Rectangle())
            .onTapGesture {
                withAnimation(.snappy(duration: 0.18)) {
                    if isOpen { model.expanded.remove(day.date) } else { model.expanded.insert(day.date) }
                }
            }

            if !day.events.isEmpty {
                Text(day.events.joined(separator: " · "))
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary).padding(.leading, 20)
            }

            if isOpen {
                Divider()
                VStack(spacing: 0) {
                    // The 07:00-19:30 clip keeps this compact against a club's full
                    // 06:00-19:50 slot list, but sunrise runs earlier than 07:00 for
                    // real stretches of the year (06:51 as of 2026-09-08) -- explicitly
                    // keeping whichever row carries the marker means the sunrise/
                    // sunset note this screen exists to show can't silently vanish
                    // just because the season shifted.
                    ForEach(day.slots.filter {
                        ($0.time >= "07:00" && $0.time <= "19:30")
                            || $0.time == day.sunriseRowTime || $0.time == day.sunsetRowTime
                    }) { slot in
                        SlotRow(slot: slot, day: day, model: model)
                    }
                }
                .padding(.leading, 20)
            }
        }
        .padding(12)
        // theme.colors.surface, not the system-appearance-driven `.quaternary` this
        // used to be -- a card that ignores the chosen theme entirely would make a
        // theme switch look like it did nothing, since cards are most of the screen.
        .background(theme.colors.surface.opacity(0.55), in: RoundedRectangle(cornerRadius: 10))
    }
}

/// `@State` is a *macro* in current SwiftUI, and its plugin ships with Xcode rather
/// than the Command Line Tools -- so this prototype uses the older, macro-free
/// `ObservableObject`/`@Published`/`@StateObject` trio instead. Identical behaviour,
/// and it builds with nothing but `swiftc`. See README.md.
/// Runs the scraper and watches for its results.
///
/// The app never scrapes anything itself -- it shells out to the same
/// `teetime-monitor-scrape` console script the launchd agent runs, so there is exactly
/// one implementation of scraping and it stays in Python. See `prototypes/macos-swift/
/// README.md` on why that split is the whole point of the hybrid.
enum Scraper {
    /// Homebrew's symlink first, then the Cellar-independent PATH lookup, so this keeps
    /// working for a source checkout or a non-standard prefix.
    static func executable() -> String? {
        for candidate in ["/opt/homebrew/bin/teetime-monitor-scrape",
                          "/usr/local/bin/teetime-monitor-scrape"]
        where FileManager.default.isExecutableFile(atPath: candidate) {
            return candidate
        }
        let which = Process()
        which.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        which.arguments = ["which", "teetime-monitor-scrape"]
        let pipe = Pipe(); which.standardOutput = pipe; which.standardError = Pipe()
        try? which.run(); which.waitUntilExit()
        let found = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return found.isEmpty ? nil : found
    }

    /// A full pass takes roughly 20 seconds against a real club (and much longer if
    /// requests hit their timeouts), so this never blocks the UI -- the caller shows
    /// progress and `done` fires back on the main queue.
    static func run(done: @escaping (String?) -> Void) {
        guard let exe = executable() else {
            done("teetime-monitor-scrape not found — install it with Homebrew.")
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: exe)
            // --force: an explicit Refresh must actually do something. Without it the
            // scraper's own per-course/date interval usually decides nothing is due,
            // and the button looks broken (see scrape_once.main()'s docstring).
            task.arguments = ["--force"]
            let err = Pipe(); task.standardError = err; task.standardOutput = Pipe()
            do { try task.run() } catch {
                DispatchQueue.main.async { done(error.localizedDescription) }
                return
            }
            task.waitUntilExit()
            let stderr = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            DispatchQueue.main.async {
                done(task.terminationStatus == 0 ? nil
                     : (stderr.isEmpty ? "scrape failed (exit \(task.terminationStatus))" : stderr))
            }
        }
    }
}

final class OverviewModel: ObservableObject {
    @Published var clubs: [(path: String, id: String, slug: String, name: String, lastScrape: String)] = []
    @Published var clubPath: String = ""
    @Published var courses: [String] = []
    @Published var course: String = ""
    @Published var days: [Day] = []
    @Published var expanded: Set<String> = []
    @Published var isScraping = false
    @Published var problem: String?
    /// Drives the "updated N minutes ago" line; republished on a timer so it ages in
    /// place rather than going stale the moment the window stops being touched.
    @Published var lastScrape: Date?
    @Published var now = Date()
    @Published var banners: [Banner] = []

    private var watcher: Timer?
    private var seenModification: Date?

    /// Green while the background agent's own cadence would have refreshed by now,
    /// amber once it's clearly overdue -- so a stopped launchd agent is visible rather
    /// than silently serving old data.
    var freshnessColor: Color {
        guard let lastScrape else { return .secondary }
        return now.timeIntervalSince(lastScrape) < 45 * 60 ? .green : .orange
    }

    var freshnessText: String {
        guard let lastScrape else { return "never scraped" }
        let minutes = Int(now.timeIntervalSince(lastScrape) / 60)
        if minutes < 1 { return "updated just now" }
        if minutes < 60 { return "updated \(minutes) min ago" }
        let f = RelativeDateTimeFormatter(); f.unitsStyle = .full
        return "updated " + f.localizedString(for: lastScrape, relativeTo: now)
    }

    var clubName: String {
        clubs.first { $0.path == clubPath }?.name ?? "teetime-monitor"
    }

    private var today: String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }

    /// Polls the database's modification time rather than using a filesystem event
    /// source: SQLite writes through journal/WAL files and can replace the main file,
    /// which makes watch descriptors go stale, whereas an mtime check is a single stat
    /// and cannot miss a completed write. Two seconds is far below the scrape interval
    /// and costs nothing.
    func startWatching() {
        watcher?.invalidate()
        watcher = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            guard let self else { return }
            self.now = Date()
            guard !self.clubPath.isEmpty,
                  let attrs = try? FileManager.default.attributesOfItem(atPath: self.clubPath),
                  let modified = attrs[.modificationDate] as? Date else { return }
            if self.seenModification == nil { self.seenModification = modified; return }
            if modified > self.seenModification! {
                // The background agent (or our own Refresh) just wrote -- pick it up
                // without the user having to reopen anything.
                self.seenModification = modified
                self.reload()
            }
        }
    }

    func refreshNow() {
        guard !isScraping else { return }
        isScraping = true
        problem = nil
        Scraper.run { [weak self] error in
            guard let self else { return }
            self.isScraping = false
            self.problem = error
            self.load()
        }
    }

    func load() {
        clubs = Store.clubs()
        // Newest-scraped first (see Store.clubs) -- picking alphabetically landed on
        // an empty leftover test database and showed "no scraped days" forever.
        if clubPath.isEmpty { clubPath = clubs.first?.path ?? "" }
        loadCourses()
    }

    func loadCourses() {
        guard !clubPath.isEmpty else { courses = []; days = []; return }
        courses = Store.courses(dbPath: clubPath)
        if !courses.contains(course) { course = courses.first ?? "" }
        reload()
    }

    func reload() {
        guard !clubPath.isEmpty, !course.isEmpty else { days = []; return }
        let keepOpen = expanded          // a background refresh must not collapse what
        days = Store.days(dbPath: clubPath, course: course, from: today)
        expanded = keepOpen              // you were reading -- same rule as the TUI's
                                         // own keep_cursor fix (v0.30.0).
        lastScrape = Store.lastScrape(dbPath: clubPath)
        banners = clubPath.isEmpty ? [] : Store.banners(dbPath: clubPath)
    }

    func dismiss(_ banner: Banner) {
        Store.acknowledgeBanners(dbPath: clubPath, ids: [banner.id])
        banners.removeAll { $0.id == banner.id }
    }
}

/// Routes the menu bar's Actions commands (see `TeetimeMonitorPrototype.body`'s
/// `.commands` block) to whichever `ContentView` is actually on screen -- a plain
/// closure-holding singleton, same "one shared instance the whole app reaches
/// through" shape `AppTheme` already uses in `Theme.swift`, chosen for the same
/// reason: `.commands` lives on the `App` scene, outside `ContentView`'s own state,
/// so there's no direct binding path from a menu item down to `model.refreshNow()`
/// without routing through something both sides can see.
///
/// Added 2026-09-18, direct question: "are available key binds shown somewhere in
/// the GUI?" -- they weren't. Each toolbar button already carried its own
/// `.keyboardShortcut()`, which makes the shortcut *work*, but does nothing to make
/// it *discoverable*: nothing on macOS surfaces a shortcut attached to a plain
/// `Button` unless it also appears in the menu bar (where the OS itself renders the
/// key equivalent next to the item, and where the system's own "hold ⌘ to see
/// shortcuts" overlay and Accessibility Inspector both read it from). Moving the
/// shortcuts here — and removing them from the toolbar buttons below, so each one
/// has exactly one definition — is what actually answers the question, not a label
/// added next to a button.
final class AppCommands: ObservableObject {
    static let shared = AppCommands()
    var onRefresh: (() -> Void)?
    var onSearch: (() -> Void)?
    var onAddClub: (() -> Void)?
    var onHeatmap: (() -> Void)?
    var onPreferences: (() -> Void)?
    var onSettings: (() -> Void)?
}

struct ContentView: View {
    @StateObject var model: OverviewModel
    @StateObject private var showingPreferences = Box(false)
    @StateObject private var showingSettings = Box(false)
    @StateObject private var showingSearch = Box(false)
    @StateObject private var showingAddClub = Box(false)
    @StateObject private var showingHeatmap = Box(false)
    // Observing the shared singleton (not creating a new one) is what makes a theme
    // change in SettingsSheet redraw this view immediately -- both hold the exact
    // same AppTheme instance, so its @Published change notification reaches here too.
    @ObservedObject private var theme = AppTheme.shared
    @ObservedObject private var scale = AppScale.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if !model.banners.isEmpty {
                VStack(spacing: 4) {
                    ForEach(model.banners) { banner in
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "bell.fill").font(scaledFont(.caption)).foregroundStyle(.orange)
                            Text(banner.message).font(scaledFont(.caption))
                            Spacer()
                            Button {
                                model.dismiss(banner)
                            } label: {
                                Image(systemName: "xmark").font(scaledFont(.caption2))
                            }
                            .buttonStyle(.plain)
                        }
                        .padding(8)
                        .background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 6))
                    }
                }
            }
            // Two rows, not one. Six actions, two pickers and the club identity all
            // competing for a single row is what squeezed the title into wrapping
            // one word per line (fixed once with .lineLimit(1), but the real cause
            // was the row being overloaded). Splitting "what am I looking at" from
            // "what can I do about it" gives both room, and lets the actions carry
            // real text labels instead of six bare icons explained only by tooltip.
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.clubName).font(scaledFont(.title2)).bold()
                        .lineLimit(1).truncationMode(.tail)
                    HStack(spacing: 6) {
                        if model.isScraping {
                            ProgressView().controlSize(.small).scaleEffect(0.7)
                            Text("Checking pc caddie…").font(scaledFont(.caption2)).foregroundStyle(.secondary)
                                .lineLimit(1)
                        } else {
                            Circle().fill(model.freshnessColor)
                                .frame(width: scale.scaled(Metrics.freshnessDot),
                                       height: scale.scaled(Metrics.freshnessDot))
                            Text(model.freshnessText).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                }
                Spacer(minLength: 12)
                // Labeled, so it's clear which picker is the club and which is the
                // course -- they were two unlabeled dropdowns stacked in a corner.
                Grid(alignment: .trailing, horizontalSpacing: 6, verticalSpacing: 5) {
                    GridRow {
                        Text("Club").font(scaledFont(.caption2)).foregroundStyle(.secondary)
                        Picker("", selection: $model.clubPath) {
                            ForEach(model.clubs, id: \.path) { club in
                                Text(club.lastScrape.isEmpty ? "\(club.name) — never scraped" : club.name)
                                    .tag(club.path)
                            }
                        }
                        .labelsHidden().frame(width: scale.scaled(Metrics.picker))
                        .onChange(of: model.clubPath) { _, _ in model.loadCourses() }
                    }
                    GridRow {
                        Text("Course").font(scaledFont(.caption2)).foregroundStyle(.secondary)
                        Picker("", selection: $model.course) {
                            ForEach(model.courses, id: \.self) { Text($0).tag($0) }
                        }
                        .labelsHidden().frame(width: scale.scaled(Metrics.picker))
                        .onChange(of: model.course) { _, _ in model.reload() }
                    }
                }
            }

            // Grouped by what each action is *for* -- act on this course's data,
            // manage which clubs exist, change how the app behaves -- with dividers
            // making those three groups visible rather than six equally-spaced
            // icons implying six unrelated things.
            HStack(spacing: 8) {
                Button { model.refreshNow() } label: { Label("Refresh", systemImage: "arrow.clockwise") }
                    .help("Run the scraper now (⌘R)")
                    .disabled(model.isScraping)
                Button { showingSearch.value = true } label: { Label("Search", systemImage: "magnifyingglass") }
                    .help("Ad hoc criteria for this one search (⌘F)")
                    .disabled(model.clubPath.isEmpty || model.course.isEmpty)
                Button { showingHeatmap.value = true } label: {
                    Label("Heatmap", systemImage: "square.grid.3x3.fill")
                }
                .help("Crowd history by weekday and hour")
                .disabled(model.clubPath.isEmpty || model.course.isEmpty)

                Divider().frame(height: scale.scaled(16))

                Button { showingAddClub.value = true } label: { Label("Add Club", systemImage: "plus.circle") }
                    .help("Search the platform directory and save a club")

                Spacer()

                Button { showingPreferences.value = true } label: {
                    Label("Preferences", systemImage: "slider.horizontal.3")
                }
                .help("When you can play, weather limits (⌘,)")
                Button { showingSettings.value = true } label: { Label("Settings", systemImage: "gearshape") }
                    .help("Display, login, scraping, AI")
            }

            if model.days.isEmpty {
                ContentUnavailableView(
                    "Nothing scraped for this course yet",
                    systemImage: "calendar.badge.exclamationmark",
                    description: Text(model.clubs.isEmpty
                        ? "No club databases found in ~/.local/share/teetime-monitor."
                        : "Pick another club or course above, or run teetime-monitor-scrape."))
                    .frame(maxHeight: .infinity)
            } else {
                ScrollView {
                    VStack(spacing: 7) {
                        ForEach(model.days) { DayCard(day: $0, model: model) }
                    }
                }
            }

            if let problem = model.problem {
                Label(problem.trimmingCharacters(in: .whitespacesAndNewlines),
                      systemImage: "exclamationmark.triangle.fill")
                    .font(scaledFont(.caption)).foregroundStyle(.orange).lineLimit(2)
            }

            // Mirrors tui.py's own OVERVIEW_LEGEND, placed the same way (one line
            // under the list, not repeated per card/row) -- the TUI's own answer to
            // "these icons aren't self-explanatory" for the same figures shown here
            // (temp, rain%, wind, sunrise/sunset, the rain/wind flag thresholds).
            if !model.days.isEmpty {
                LegendLine()
            }
        }
        .padding(16)
        // 600 was sized for the original 3-button toolbar (Refresh/Preferences/
        // Settings) -- Search, Add a Club, and the heatmap grew it to six icons
        // sharing the row with two 230pt pickers (460pt on their own), which no
        // longer fits at 600 (see the .lineLimit(1) comment above for the actual
        // bug that produced live). 860 (matching .defaultSize below, so the
        // window can never actually be dragged into the cramped zone) is a
        // deliberately generous estimate from summing the row's known component
        // widths, not a verified pixel-exact minimum -- this environment couldn't
        // drag-resize the real window to confirm the exact floor, so err wide
        // rather than risk shipping a number that still clips under some system
        // font/Dynamic Type setting.
        .frame(minWidth: 860, minHeight: 540)
        .padding(4)
        .background(theme.colors.background)
        .tint(theme.colors.accent)
        .foregroundStyle(theme.colors.foreground)
        .onAppear {
            model.load()
            model.startWatching()
            AppCommands.shared.onRefresh = { model.refreshNow() }
            AppCommands.shared.onSearch = {
                // Mirrors the toolbar button's own .disabled() guard -- the menu
                // command has no direct view of model state to grey itself out
                // with, so it stays enabled but inert instead of opening a sheet
                // with no club/course to search.
                guard !model.clubPath.isEmpty, !model.course.isEmpty else { return }
                showingSearch.value = true
            }
            AppCommands.shared.onAddClub = { showingAddClub.value = true }
            AppCommands.shared.onHeatmap = {
                guard !model.clubPath.isEmpty, !model.course.isEmpty else { return }
                showingHeatmap.value = true
            }
            AppCommands.shared.onPreferences = { showingPreferences.value = true }
            AppCommands.shared.onSettings = { showingSettings.value = true }
        }
        .sheet(isPresented: $showingPreferences.value) { PreferencesSheet() }
        .sheet(isPresented: $showingSettings.value) {
            SettingsSheet(verifyClubID: model.clubs.first { $0.path == model.clubPath }?.id)
        }
        .sheet(isPresented: $showingSearch.value) {
            SearchSheet(dbPath: model.clubPath, course: model.course,
                        clubSlug: model.clubs.first { $0.path == model.clubPath }?.slug, model: model)
        }
        .sheet(isPresented: $showingAddClub.value) { AddClubSheet(model: model) }
        .sheet(isPresented: $showingHeatmap.value) {
            HeatmapSheet(dbPath: model.clubPath, course: model.course,
                         clubYAMLPath: model.clubs.first { $0.path == model.clubPath }.map { Store.clubYAMLPath(slug: $0.slug) })
        }
    }
}

@main
struct TeetimeMonitorPrototype: App {
    var body: some Scene {
        WindowGroup("teetime-monitor") {
            ContentView(model: OverviewModel())
        }
        .defaultSize(width: 860, height: 680)
        .commands {
            // A real menu, not just a working shortcut -- see AppCommands' own
            // docstring for why this exists. A new top-level "Actions" menu (not
            // folded into an existing one) so these four are easy to find as a
            // group, next to the automatic View/Window menus SwiftUI already adds.
            CommandMenu("Actions") {
                Button("Refresh") { AppCommands.shared.onRefresh?() }
                    .keyboardShortcut("r", modifiers: .command)
                Button("Search…") { AppCommands.shared.onSearch?() }
                    .keyboardShortcut("f", modifiers: .command)
                Button("Add a Club…") { AppCommands.shared.onAddClub?() }
                Button("Crowd Heatmap…") { AppCommands.shared.onHeatmap?() }
                Divider()
                Button("Preferences…") { AppCommands.shared.onPreferences?() }
                    .keyboardShortcut(",", modifiers: .command)
                Button("Settings…") { AppCommands.shared.onSettings?() }
            }
        }
    }
}
