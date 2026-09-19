import SwiftUI

// icon(for:)/fillColor(_:)/weekday(_:) moved to Formatting.swift so they can sit in
// the SPM test target -- see that file's own docstring.

/// One wrapped line explaining every icon/figure the day list uses -- the exact
/// same role `tui.py`'s `OVERVIEW_LEGEND` plays under the TUI's own table, kept to
/// the subset this card-based view actually shows.
struct LegendLine: View {
    @ObservedObject private var units = AppUnits.shared
    @ObservedObject private var language = AppLanguage.shared

    // Computed, not a stored `let`: the temperature/wind labels state the current
    // unit, so they have to follow a Units change the same way the numbers do.
    private var entries: [(icon: String, text: String)] {
        [
            ("thermometer.medium", t("legend.hilo", ["unit": Units.temperatureSymbol(units.value)])),
            ("drop.fill", t("legend.rain")),
            ("wind", t("legend.wind", ["unit": Units.windSymbol(units.value)])),
            ("sunrise.fill", t("legend.sunrise")),
            ("sunset.fill", t("legend.sunset")),
            ("flag.fill", t("legend.booking")),
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
    // theme.colors.faint, not Color.secondary.opacity(0.18) -- this *is* the
    // "occupancy bars" the user's 2026-09-19 report named directly as unreadable
    // under solarized-light, so it gets a theme-relative fill rather than relying
    // on `.preferredColorScheme` making the system gray merely adequate.
    @ObservedObject private var theme = AppTheme.shared
    var body: some View {
        HStack(spacing: 2) {
            ForEach(Array(buckets.enumerated()), id: \.offset) { _, value in
                RoundedRectangle(cornerRadius: 2)
                    .fill(value.map(fillColor) ?? theme.colors.faint)
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
    @ObservedObject private var language = AppLanguage.shared
    // Same reasoning as HeatStrip: these seat pips are the "occupancy bars in
    // detailed view" the user's report named as unreadable under a light theme.
    @ObservedObject private var theme = AppTheme.shared
    @StateObject private var showingConfirm = Box(false)
    // Same hover-feedback fix as DayCard's header, for the same tappable-row report.
    @StateObject private var isHovering = Box(false)

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
                Text(slot.blockReason?.isEmpty == false ? slot.blockReason! : t("overview.not_bookable"))
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary).italic()
            } else {
                HStack(spacing: 3) {
                    ForEach(0..<max(slot.capacity, 1), id: \.self) { i in
                        RoundedRectangle(cornerRadius: 2)
                            .fill(i < slot.booked
                                  ? (isMine && i == 0 ? Color.accentColor : theme.colors.muted)
                                  : theme.colors.faint)
                            .frame(width: scale.scaled(Metrics.seatPip),
                                   height: scale.scaled(Metrics.seatPip))
                    }
                }
                Text(t("overview.free", ["n": "\(slot.capacity - slot.booked)"]))
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary)
            }

            Spacer()

            // Sunrise/sunset noted on whichever slot row is actually closest to it --
            // mirrors tui._closest_slot_time()'s placement exactly, not a single
            // summary line detached from any specific time (see Day.sunriseRowTime/
            // sunsetRowTime for the tie-break rule this shares with Python).
            if slot.time == day.sunriseRowTime {
                Label(t("overview.sunrise_at", ["time": day.sunrise ?? ""]), systemImage: "sunrise.fill")
                    .font(scaledFont(.caption2)).foregroundStyle(.orange)
            }
            if slot.time == day.sunsetRowTime {
                Label(t("overview.sunset_at", ["time": day.sunset ?? ""]), systemImage: "sunset.fill")
                    .font(scaledFont(.caption2)).foregroundStyle(.orange)
            }
            if isMine {
                Label(t("overview.you"), systemImage: "flag.fill")
                    .font(scaledFont(.caption2)).foregroundStyle(Color.accentColor)
            }
            if let w = day.weather(at: slot.time) {
                Image(systemName: icon(for: w.code)).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                    .help(t("tip.condition_at", ["time": slot.time]))
                if let tempC = w.temperatureC {
                    Text(String(format: "%.0f°", Units.temperature(tempC, units.value)))
                        .font(scaledFont(.caption2)).foregroundStyle(.secondary)
                        .frame(width: scale.scaled(Metrics.slotTemp), alignment: .trailing)
                        .help(t("tip.temp", ["unit": Units.temperatureSymbol(units.value)]))
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
                    .help(p >= 50 ? t("tip.rain_flagged") : t("tip.rain"))
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
                          ? t("tip.wind_flagged", ["unit": Units.windSymbol(units.value)])
                          : t("tip.wind", ["unit": Units.windSymbol(units.value)]))
                }
            }
        }
        .padding(.vertical, 2).padding(.horizontal, 4)
        .opacity(isPastSunset ? 0.4 : 1)
        // Blocked slots aren't tappable (see the guard below), so they get no hover
        // highlight either -- a row that lit up on hover but did nothing on click
        // would be its own, subtler version of the same "no feedback" complaint.
        .background(isHovering.value && !slot.isBlocked ? theme.colors.surface : Color.clear,
                    in: RoundedRectangle(cornerRadius: 4))
        .contentShape(Rectangle())
        .onHover { isHovering.value = !slot.isBlocked && $0 }
        .onTapGesture { if !slot.isBlocked { showingConfirm.value = true } }
        // A confirming dialog, not a silent write on tap -- matches the TUI's own
        // ConfirmBookingScreen/CancelBookingScreen, which exist specifically because
        // this marks a *local* record of what you already booked on pc caddie, not a
        // real booking action; a stray tap must not silently claim or drop one.
        .confirmationDialog(
            isMine ? t("booking.cancel_title", ["time": slot.time])
                   : t("booking.mark_title", ["time": slot.time]),
            isPresented: $showingConfirm.value, titleVisibility: .visible
        ) {
            if isMine {
                Button(t("booking.cancel"), role: .destructive) {
                    Store.cancelBooking(dbPath: model.clubPath, course: model.course, date: day.date)
                    model.reload()
                }
            } else {
                Button(t("booking.confirm")) {
                    Store.confirmBooking(dbPath: model.clubPath, course: model.course, date: day.date, time: slot.time)
                    model.reload()
                }
            }
            Button(t("booking.not_now"), role: .cancel) {}
        }
    }
}

/// The tappable summary row for one day -- split out from the slot list (see
/// `DayCardBody`) so the day list can pin it in place while its own slots scroll
/// underneath. Direct report, 2026-09-19: "can you fixate overview row, when it
/// is uncollapsed and you scroll down?" -- previously the whole day, header and
/// slots together, was one scrolling unit, so an open day's own heading scrolled
/// away with everything else the moment you scrolled its slot list. `ContentView`
/// wraps this pair in a `LazyVStack(pinnedViews: [.sectionHeaders])` `Section`
/// per day, the same primitive a `List` uses for its own sticky section headers.
struct DayCardHeader: View {
    let day: Day
    @ObservedObject var model: OverviewModel
    @ObservedObject private var theme = AppTheme.shared
    @ObservedObject private var scale = AppScale.shared
    @ObservedObject private var units = AppUnits.shared
    @ObservedObject private var language = AppLanguage.shared
    // Direct report, 2026-09-19: "clicking on a row in the overview doesn't
    // provide enough feedback, since it doesn't highlight the row." Hover state
    // rather than a tap-flash -- macOS's own outline/table rows highlight on
    // hover before the click even lands, and that's the feedback the report
    // asked for (something visible *while* pointing at the row, not just a
    // blink after).
    @StateObject private var isHovering = Box(false)
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
                    .help(t("tip.condition_day"))
                if let (hi, lo) = day.tempHighLow {
                    Label("\(Int(Units.temperature(hi, units.value)))°/"
                          + "\(Int(Units.temperature(lo, units.value)))°",
                          systemImage: "thermometer.medium")
                        .font(scaledFont(.subheadline, design: .monospaced))
                        .help(t("tip.temp_day", ["unit": Units.temperatureSymbol(units.value)]))
                }
                if let p = day.precipAvg {
                    Label("\(Int(p))%", systemImage: "drop.fill")
                        .font(scaledFont(.caption)).foregroundStyle(.secondary)
                        .help(t("tip.rain_day"))
                }
                if let wd = day.windPeak {
                    Label("\(Int(Units.windSpeed(wd, units.value)))", systemImage: "wind")
                        .font(scaledFont(.caption)).foregroundStyle(.secondary)
                        .help(t("tip.wind_day", ["unit": Units.windSymbol(units.value)]))
                }
                if let rise = day.sunrise, let set = day.sunset {
                    Text("↑\(rise) ↓\(set)").font(scaledFont(.caption2)).foregroundStyle(.tertiary)
                        .help(t("tip.sun"))
                }

                Spacer()
                HeatStrip(buckets: day.heatStrip)

                // Fixed-width regardless of whether this day has a booking -- reported
                // live (2026-09-19): with the badge only taking space when present,
                // HeatStrip landed at a different x on a row with a reservation than on
                // one without, since the Spacer above packs everything after it as one
                // trailing group. Reserving this slot's width unconditionally keeps
                // HeatStrip at the same offset on every row.
                Group {
                    if let bookedTime = day.bookedTime {
                        Label(bookedTime, systemImage: "flag.fill")
                            .font(scaledFont(.caption)).padding(.horizontal, 7).padding(.vertical, 3)
                            .background(Color.accentColor.opacity(0.15), in: Capsule())
                            .foregroundStyle(Color.accentColor)
                    }
                }
                .frame(width: scale.scaled(Metrics.bookingBadge), alignment: .trailing)
            }
            .padding(.horizontal, 6).padding(.vertical, 3)
            .background(isHovering.value ? theme.colors.surface : Color.clear,
                        in: RoundedRectangle(cornerRadius: 6))
            .contentShape(Rectangle())
            .onHover { isHovering.value = $0 }
            .onTapGesture {
                withAnimation(.snappy(duration: 0.18)) {
                    if isOpen { model.expanded.remove(day.date) } else { model.expanded.insert(day.date) }
                }
            }

            if !day.events.isEmpty {
                Text(day.events.joined(separator: " · "))
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary).padding(.leading, 20)
            }
        }
        .padding(12)
        // Stretches to the full row width offered by the day list -- without this,
        // each header sized itself to fit only its own content (the weekday text
        // plus whichever weather labels that day happens to have), so a day with a
        // shorter summary had a *narrower* header than one with more labels, and
        // the trailing Spacer above packed HeatStrip+the booking badge flush to
        // that narrower header's own right edge instead of a shared one -- the
        // real cause of the heat strip still visibly shifting row to row after the
        // earlier fixed-width-badge fix alone, confirmed live (2026-09-19) against
        // a fresh screenshot.
        .frame(maxWidth: .infinity, alignment: .leading)
        // theme.colors.surface, not the system-appearance-driven `.quaternary` this
        // used to be -- a card that ignores the chosen theme entirely would make a
        // theme switch look like it did nothing, since cards are most of the screen.
        // Higher opacity while open -- a second, lasting piece of the same feedback
        // the hover highlight above gives only momentarily, so an expanded day
        // still reads as "this one's open" after the pointer has moved away. Both
        // values raised from the original 0.85/0.55 now that this header can be
        // *pinned* on screen while its own slots scroll underneath -- a pinned
        // header needs a solid-reading background so scrolled rows don't show
        // through it, not just enough contrast for a card that never overlaps
        // anything else.
        //
        // Only the top corners round while open: DayCardBody sits flush beneath
        // with the bottom corners instead, so together they still read as one
        // continuous card even though they're now two separately-pinnable pieces.
        .background(
            UnevenRoundedRectangle(topLeadingRadius: 10, bottomLeadingRadius: isOpen ? 0 : 10,
                                    bottomTrailingRadius: isOpen ? 0 : 10, topTrailingRadius: 10)
                .fill(theme.colors.surface.opacity(isOpen ? 0.94 : 0.8))
        )
    }
}

/// The slot list for one *open* day -- see `DayCardHeader`'s own docstring for why
/// this is a separate view. Rendered as this day's `Section` content in
/// `ContentView`'s pinned-header `LazyVStack`; omitted entirely (not just hidden)
/// while the day is collapsed, so a collapsed day's `Section` has no content to
/// scroll through and its header hands off to the next day's immediately.
struct DayCardBody: View {
    let day: Day
    @ObservedObject var model: OverviewModel
    @ObservedObject private var theme = AppTheme.shared

    // The 07:00-19:30 clip keeps this compact against a club's full 06:00-19:50
    // slot list, but sunrise runs earlier than 07:00 for real stretches of the
    // year (06:51 as of 2026-09-08) -- explicitly keeping whichever row carries
    // the marker means the sunrise/sunset note this screen exists to show can't
    // silently vanish just because the season shifted.
    private var visibleSlots: [Slot] {
        day.slots.filter {
            ($0.time >= "07:00" && $0.time <= "19:30")
                || $0.time == day.sunriseRowTime || $0.time == day.sunsetRowTime
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            Divider()
            VStack(spacing: 0) {
                ForEach(visibleSlots) { slot in
                    SlotRow(slot: slot, day: day, model: model)
                }
            }
            .padding(.leading, 20)
        }
        .padding(.horizontal, 12).padding(.bottom, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            UnevenRoundedRectangle(topLeadingRadius: 0, bottomLeadingRadius: 10,
                                    bottomTrailingRadius: 10, topTrailingRadius: 0)
                .fill(theme.colors.surface.opacity(0.94))
        )
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
            done(t("error.scraper_missing"))
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
    @Published var lastScrape: Date?
    @Published var banners: [Banner] = []

    private var watcher: Timer?
    private var seenModification: Date?

    /// Green while the background agent's own cadence would have refreshed by now,
    /// amber once it's clearly overdue -- so a stopped launchd agent is visible rather
    /// than silently serving old data. Takes `now` as a parameter rather than reading
    /// a `@Published var now` this class used to own -- direct report, 2026-09-19,
    /// with a measured RSS climbing roughly 1MB/s at idle, past 200MB within a
    /// couple of minutes. Root cause: DayCardHeader/DayCardBody/SlotRow all hold
    /// `@ObservedObject var model: OverviewModel` (they need it for real reasons --
    /// `expanded`, booking actions), so a `now` tick living *on this class* fired
    /// `objectWillChange` for the whole day list every 2 seconds regardless of
    /// whether any actual schedule data had changed, forcing every visible row
    /// (including native NSPopUpButton-backed Pickers, once item 2 added several
    /// per settings row) to fully re-render on a clock, forever. See
    /// `FreshnessClock`/`FreshnessRow` below: the ticking `now` now lives in its own
    /// small `ObservableObject` that only that one small view observes, so the tick
    /// no longer touches `OverviewModel`'s own `objectWillChange` at all.
    func freshnessColor(now: Date) -> Color {
        guard let lastScrape else { return .secondary }
        return now.timeIntervalSince(lastScrape) < 45 * 60 ? .green : .orange
    }

    func freshnessText(now: Date) -> String {
        guard let lastScrape else { return t("overview.updated_never") }
        let minutes = Int(now.timeIntervalSince(lastScrape) / 60)
        if minutes < 1 { return t("overview.updated_just_now") }
        if minutes < 60 { return t("overview.updated_minutes", ["n": "\(minutes)"]) }
        let f = RelativeDateTimeFormatter(); f.unitsStyle = .full
        f.locale = currentLocale()
        return t("overview.updated_relative",
                 ["when": f.localizedString(for: lastScrape, relativeTo: now)])
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
    var onCollapseAll: (() -> Void)?
    var onPreferences: (() -> Void)?
    var onSettings: (() -> Void)?
}

/// A one-second clock for exactly one job: aging the "updated N minutes ago" line
/// in place. Deliberately its own small `ObservableObject`, not a `now` field on
/// `OverviewModel` (that used to be the design -- see `OverviewModel.freshnessColor`'s
/// own docstring for the real, measured memory/CPU cost that had: every visible row
/// re-rendering on a clock tick, forever, because everything shares one `model`).
/// Owned by `FreshnessRow` alone, so the tick only ever invalidates that one small
/// view.
final class FreshnessClock: ObservableObject {
    @Published var now = Date()
    private var timer: Timer?

    func start() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            self?.now = Date()
        }
    }
}

/// The "● updated N minutes ago" line, split out of `ContentView`'s own body for
/// the same reason `FreshnessClock` exists: isolate the 2-second tick to the one
/// small view that actually needs it, instead of `ContentView`'s (and thereby the
/// whole visible day list's) body re-running every tick.
private struct FreshnessRow: View {
    @ObservedObject var model: OverviewModel
    @ObservedObject private var scale = AppScale.shared
    @StateObject private var clock = FreshnessClock()

    var body: some View {
        HStack(spacing: 6) {
            if model.isScraping {
                ProgressView().controlSize(.small).scaleEffect(0.7)
                Text(t("overview.checking")).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                    .lineLimit(1)
            } else {
                Circle().fill(model.freshnessColor(now: clock.now))
                    .frame(width: scale.scaled(Metrics.freshnessDot),
                           height: scale.scaled(Metrics.freshnessDot))
                Text(model.freshnessText(now: clock.now)).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .onAppear { clock.start() }
    }
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
    @ObservedObject private var language = AppLanguage.shared

    private var appVersionString: String {
        "v" + (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?")
    }

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
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(model.clubName).font(scaledFont(.title2)).bold()
                            .lineLimit(1).truncationMode(.tail)
                        // Mirrors the TUI's own Header, which sets its subtitle to
                        // "v{version}" from the same package metadata -- direct
                        // request, 2026-09-19 ("I want to see the version ... It
                        // should match with the version of the TUI."). The Info.plist
                        // value this reads comes from pyproject.toml at build time
                        // (see build.sh), the same file tui.py's own _version() reads,
                        // so there is one number and both apps show it. The standard
                        // "About TeetimeMonitor" panel reads this same Info.plist key
                        // automatically -- nothing else to wire up for that half.
                        Text(appVersionString).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                    }
                    FreshnessRow(model: model)
                }
                Spacer(minLength: 12)
                // Labeled, so it's clear which picker is the club and which is the
                // course -- they were two unlabeled dropdowns stacked in a corner.
                Grid(alignment: .trailing, horizontalSpacing: 6, verticalSpacing: 5) {
                    GridRow {
                        Text(t("overview.club")).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                        Picker("", selection: $model.clubPath) {
                            // Alphabetical here, in the dropdown only -- direct
                            // question, 2026-09-19 ("are entries in club dropdown
                            // sorted alphabetically?"). `model.clubs` itself stays
                            // newest-scraped-first (see Store.clubs' own docstring
                            // for the real bug that ordering fixed: picking
                            // alphabetically for the *default selection* landed on
                            // an empty leftover test database), so only the list
                            // this Picker renders is re-sorted, not which club
                            // loads when the app opens.
                            ForEach(model.clubs.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending },
                                    id: \.path) { club in
                                Text(club.lastScrape.isEmpty ? "\(club.name) — \(t("overview.never_scraped"))" : club.name)
                                    .tag(club.path)
                            }
                        }
                        .labelsHidden().frame(width: scale.scaled(Metrics.picker))
                        .onChange(of: model.clubPath) { _, _ in model.loadCourses() }
                    }
                    GridRow {
                        Text(t("overview.course")).font(scaledFont(.caption2)).foregroundStyle(.secondary)
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
                Button { model.refreshNow() } label: { Label(t("action.refresh"), systemImage: "arrow.clockwise") }
                    .help(t("tip.refresh"))
                    .disabled(model.isScraping)
                Button { showingSearch.value = true } label: { Label(t("action.search"), systemImage: "magnifyingglass") }
                    .help(t("tip.search"))
                    .disabled(model.clubPath.isEmpty || model.course.isEmpty)
                Button { showingHeatmap.value = true } label: {
                    Label(t("action.heatmap"), systemImage: "square.grid.3x3.fill")
                }
                .help(t("tip.heatmap"))
                .disabled(model.clubPath.isEmpty || model.course.isEmpty)

                Divider().frame(height: scale.scaled(16))

                Button { showingAddClub.value = true } label: { Label(t("action.add_club"), systemImage: "plus.circle") }
                    .help(t("tip.add_club"))

                Spacer()

                Button { showingPreferences.value = true } label: {
                    Label(t("action.preferences"), systemImage: "slider.horizontal.3")
                }
                .help(t("tip.preferences"))
                Button { showingSettings.value = true } label: { Label(t("action.settings"), systemImage: "gearshape") }
                    .help(t("tip.settings"))
            }

            if model.days.isEmpty {
                ContentUnavailableView(
                    t("overview.empty_title"),
                    systemImage: "calendar.badge.exclamationmark",
                    description: Text(model.clubs.isEmpty
                        ? t("overview.empty_no_clubs")
                        : t("overview.empty_pick_another")))
                    .frame(maxHeight: .infinity)
            } else {
                // Placed beside the list it acts on, not in the already-full
                // 6-button toolbar above -- direct request, 2026-09-19 ("I'd like a
                // button to collapse all incl. a keybind"). Hidden once nothing is
                // open rather than merely disabled: with every card already
                // collapsed there is nothing left for it to say.
                if !model.expanded.isEmpty {
                    HStack {
                        Spacer()
                        // No .keyboardShortcut() here -- same reason AppCommands'
                        // own docstring gives for every other toolbar action: it
                        // would work but wouldn't be *discoverable*. The real
                        // shortcut lives on the Actions-menu item below, routed
                        // through the same AppCommands.onCollapseAll closure this
                        // button calls directly.
                        Button { model.expanded.removeAll() } label: {
                            Label(t("action.collapse_all"), systemImage: "arrow.up.to.line.compact")
                        }
                        .help(t("tip.collapse_all"))
                    }
                }
                // LazyVStack + Section, not the plain VStack this used to be --
                // `pinnedViews: [.sectionHeaders]` is what actually pins each open
                // day's own header while its slots scroll underneath (direct
                // report, 2026-09-19: "can you fixate overview row, when it is
                // uncollapsed and you scroll down?"), the same primitive a List's
                // own sticky section headers use. A collapsed day still renders
                // correctly: its Section simply has no body, so its header hands
                // off to the next day's immediately rather than lingering pinned
                // with nothing under it.
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 7, pinnedViews: [.sectionHeaders]) {
                        ForEach(model.days) { day in
                            Section {
                                if model.expanded.contains(day.date) {
                                    DayCardBody(day: day, model: model)
                                }
                            } header: {
                                DayCardHeader(day: day, model: model)
                            }
                        }
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
        // Forces this window's own color scheme to match the chosen theme rather
        // than the system's -- see sheetFrame()'s own docstring in Scale.swift for
        // the real visibility bug (unreadable dropdowns/pips under a light theme
        // while macOS itself is in Dark Mode, or vice versa) this fixes. `theme`
        // is already `@ObservedObject`, so this updates live on a theme change,
        // unlike each sheet's own one-shot version.
        .preferredColorScheme(theme.colors.isDark ? .dark : .light)
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
            AppCommands.shared.onCollapseAll = { model.expanded.removeAll() }
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
    // The Actions menu's own titles go through t() too, and `.commands` is
    // evaluated as part of this scene's body -- so without observing the language
    // here, the menu would keep its launch-time wording after a change while the
    // window content re-rendered around it.
    @ObservedObject private var language = AppLanguage.shared

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
            CommandMenu(t("menu.actions")) {
                Button(t("menu.refresh")) { AppCommands.shared.onRefresh?() }
                    .keyboardShortcut("r", modifiers: .command)
                Button(t("menu.search")) { AppCommands.shared.onSearch?() }
                    .keyboardShortcut("f", modifiers: .command)
                Button(t("menu.add_club")) { AppCommands.shared.onAddClub?() }
                Button(t("menu.heatmap")) { AppCommands.shared.onHeatmap?() }
                // ⌥⌘← -- Finder's and Xcode's own shortcut for "collapse everything
                // in this outline", reused rather than picked arbitrarily.
                Button(t("menu.collapse_all")) { AppCommands.shared.onCollapseAll?() }
                    .keyboardShortcut(.leftArrow, modifiers: [.command, .option])
                Divider()
                Button(t("menu.preferences")) { AppCommands.shared.onPreferences?() }
                    .keyboardShortcut(",", modifiers: .command)
                Button(t("menu.settings")) { AppCommands.shared.onSettings?() }
            }
        }
    }
}
