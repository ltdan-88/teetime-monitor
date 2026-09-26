import SwiftUI

// icon(for:)/fillColor(_:)/weekday(_:) moved to Formatting.swift so they can sit in
// the SPM test target -- see that file's own docstring.

/// One wrapped line explaining every icon/figure the day list uses -- the exact
/// same role `tui.py`'s `OVERVIEW_LEGEND` plays under the TUI's own table, kept to
/// the subset this card-based view actually shows.
/// A left-to-right layout that wraps to a new line instead of overflowing --
/// direct report, 2026-09-19 ("bottom info bar should wrap up when window is not
/// wide enough"). `LegendLine` used to handle overflow with a horizontal
/// `ScrollView` instead; with no scrollbar shown and no other affordance hinting
/// more content existed, its later entries just looked cut off at the window's
/// minimum width, which is exactly what a live screenshot showed. `Layout` itself
/// (macOS 13+) has been safe to use since this prototype's `LSMinimumSystemVersion`
/// was set to 14.0.
struct FlowLayout: Layout {
    var hSpacing: CGFloat = 12
    var vSpacing: CGFloat = 4

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, widest: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0, x + size.width > maxWidth {
                widest = max(widest, x - hSpacing)
                x = 0
                y += rowHeight + vSpacing
                rowHeight = 0
            }
            x += size.width + hSpacing
            rowHeight = max(rowHeight, size.height)
        }
        widest = max(widest, x - hSpacing)
        y += rowHeight
        return CGSize(width: maxWidth.isFinite ? maxWidth : widest, height: y)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x: CGFloat = bounds.minX, y: CGFloat = bounds.minY, rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + vSpacing
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + hSpacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

struct LegendLine: View {
    @ObservedObject private var units = AppUnits.shared
    @ObservedObject private var language = AppLanguage.shared
    @ObservedObject private var scale = AppScale.shared

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

    // The heat strip's own green/orange/red meaning -- direct report,
    // 2026-09-19 ("color bars still don't say what they represent"). The
    // previous round only added the "08:00-20:00" *time window* to this line (a
    // different gap the same complaint's wording pointed at); the color *scale*
    // itself was never actually explained anywhere the day list shows it. Same
    // three colors, same thresholds as `fillColor()`, and reuses HeatmapSheet's
    // own legend wording verbatim (heatmap.legend.open/mid/full) rather than
    // inventing separate copy for the same three states.
    private var heatSwatches: [(color: Color, text: String)] {
        [(.green, t("heatmap.legend.open")), (.orange, t("heatmap.legend.mid")), (.red, t("heatmap.legend.full"))]
    }

    var body: some View {
        FlowLayout(hSpacing: 12, vSpacing: 4) {
            ForEach(entries, id: \.text) { entry in
                HStack(spacing: 3) {
                    Image(systemName: entry.icon)
                    Text(entry.text)
                }
            }
            ForEach(heatSwatches, id: \.text) { swatch in
                HStack(spacing: 4) {
                    RoundedRectangle(cornerRadius: 2).fill(swatch.color)
                        .frame(width: scale.scaled(Metrics.legendSwatchWidth),
                               height: scale.scaled(Metrics.legendSwatchHeight))
                    Text(swatch.text)
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
                // Direct report, 2026-09-19 ("search results and overview still
                // need explanation what percentage and number really mean") --
                // neither of these had any explanation at all before, unlike
                // every weather cell beside them.
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
                .help(t("tip.seat_pips", ["booked": "\(slot.booked)", "capacity": "\(slot.capacity)"]))
                Text(t("overview.free", ["n": "\(slot.capacity - slot.booked)"]))
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary)
                    .help(t("tip.open_spots"))
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
                    .frame(width: scale.scaled(Metrics.slotCondition))
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
                    // "70%/1.5mm", not just "70%" -- direct report, 2026-09-19
                    // ("precipitation amount in mm seems to still be missing"),
                    // mirroring that same function's own probability+amount cell.
                    HStack(spacing: 1) {
                        if p >= 50 { Text("🌧").font(.system(size: scale.scaled(9))) }
                        Text(precipitationCellText(probability: p, mm: w.precipitationMM, units: units.value))
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
        //
        // theme.colors.accent, not .surface -- direct report, 2026-09-19 ("row
        // highlighting in many themes almost invisible"): a theme's surface tone
        // is chosen to sit close to its background (that's what makes a card
        // read as "part of the page," see DayCardHeader's own background
        // comment), which is exactly what made it a bad choice for a highlight
        // that has to stand out *against* that same background. accent is
        // chosen for the opposite reason -- visible contrast against the
        // background by construction, in every theme -- so it's what a hover
        // state actually needs.
        .background(isHovering.value && !slot.isBlocked ? theme.colors.accent.opacity(0.15) : Color.clear,
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
            // Leading content and the trailing HeatStrip+badge group used to share
            // one HStack with a Spacer between them -- reported still shifting
            // live (2026-09-19) even after the earlier fixed-width-badge and
            // maxWidth:.infinity fixes, with a screenshot showing the same
            // symptom. Root cause: this header is a *pinned* Section header (see
            // ContentView's LazyVStack), and a Spacer only expands to fill
            // whatever width its own immediate container is actually offered --
            // that propagating correctly from an ancestor several levels up,
            // through a VStack, through a pinned header's own special layout
            // pass, turned out not to be reliable. `.overlay(alignment: .trailing)`
            // sidesteps that path entirely: it positions the trailing group
            // relative to the *leading* HStack's own resolved frame, which is
            // forced to the header's full width right here, one level away from
            // where it's read -- no Spacer, no multi-level propagation to trust.
            leadingSummary
                .overlay(alignment: .trailing) { trailingHeatAndBadge }
                .padding(.horizontal, 6).padding(.vertical, 3)
                // theme.colors.accent, not .surface -- same fix as SlotRow's own
                // hover highlight, and the same direct report ("row highlighting
                // in many themes almost invisible"): surface is deliberately
                // close to background (see this header's own background comment
                // below), which reads fine for "this card is part of the page"
                // but made a hover state that's supposed to stand out against
                // that same background nearly disappear in several themes.
                .background(isHovering.value ? theme.colors.accent.opacity(0.15) : Color.clear,
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
        // Stretches this whole header (not just leadingSummary above) to the full
        // row width the day list offers -- keeps the card's own background/corner
        // radius spanning the full width regardless of content.
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

    /// The chevron/weekday/condition/weather-label group -- everything to the
    /// *left* of HeatStrip. Its own `.frame(maxWidth: .infinity, alignment: .leading)`
    /// is what `trailingHeatAndBadge`'s overlay aligns against; naturally-sized
    /// content (a day with fewer weather labels) still leaves this view's own
    /// *resolved frame* at the header's full width, which is the property the
    /// previous Spacer-based layout couldn't reliably guarantee here.
    private var leadingSummary: some View {
        HStack(spacing: 10) {
            Image(systemName: isOpen ? "chevron.down" : "chevron.right")
                .font(scaledFont(.caption2)).foregroundStyle(.secondary).frame(width: scale.scaled(Metrics.chevron))
            Text(weekday(day.date)).font(scaledFont(.headline))
                .frame(width: scale.scaled(Metrics.dayWeekday), alignment: .leading)

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
            //
            // Every field below now sits in its own fixed-width column
            // (Metrics.dayCondition/dayTemp/dayRain/dayWind/daySun) and renders
            // an empty placeholder rather than disappearing when its own optional
            // is nil -- direct report, 2026-09-26 ("icons, temperatures, wind,
            // sunrise/sunset times etc. are not always aligned between the
            // different days"). A day with a wider condition icon, an extra
            // temperature digit, or (previously) no weather at all for a given
            // field used to shove everything after it sideways relative to the
            // row above and below; same fixed-column fix `SlotRow` already uses
            // for its own time/temp/precip/wind cells.
            Image(systemName: icon(for: day.conditionCode)).foregroundStyle(.secondary)
                .help(t("tip.condition_day"))
                .frame(width: scale.scaled(Metrics.dayCondition))
            Group {
                if let (hi, lo) = day.tempHighLow {
                    Label("\(Int(Units.temperature(hi, units.value)))°/"
                          + "\(Int(Units.temperature(lo, units.value)))°",
                          systemImage: "thermometer.medium")
                        .font(scaledFont(.subheadline, design: .monospaced))
                        .help(t("tip.temp_day", ["unit": Units.temperatureSymbol(units.value)]))
                }
            }
            .frame(width: scale.scaled(Metrics.dayTemp), alignment: .leading)
            Group {
                if let p = day.precipAvg {
                    Label("\(Int(p))%", systemImage: "drop.fill")
                        .font(scaledFont(.caption)).foregroundStyle(.secondary)
                        .help(t("tip.rain_day"))
                }
            }
            .frame(width: scale.scaled(Metrics.dayRain), alignment: .leading)
            Group {
                if let wd = day.windPeak {
                    Label("\(Int(Units.windSpeed(wd, units.value)))", systemImage: "wind")
                        .font(scaledFont(.caption)).foregroundStyle(.secondary)
                        .help(t("tip.wind_day", ["unit": Units.windSymbol(units.value)]))
                }
            }
            .frame(width: scale.scaled(Metrics.dayWind), alignment: .leading)
            Group {
                if let rise = day.sunrise, let set = day.sunset {
                    Text("↑\(rise) ↓\(set)").font(scaledFont(.caption2)).foregroundStyle(.tertiary)
                        .help(t("tip.sun"))
                }
            }
            .frame(width: scale.scaled(Metrics.daySun), alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// The booking-flag badge plus HeatStrip, positioned by `leadingSummary`'s own
    /// `.overlay(alignment: .trailing)` rather than packed after a Spacer -- see
    /// that property's docstring. The badge still reserves its own fixed-width
    /// slot regardless of whether this day has a booking (unchanged from the
    /// original fix), so HeatStrip itself lands at the same offset whether or not
    /// the badge beside it is actually showing anything.
    ///
    /// Badge before HeatStrip, not after -- direct request, 2026-09-19 ("swap
    /// position of booking marking with occupancy indicator"): "you've booked
    /// this" reads as the more important of the two to see first, occupancy
    /// second.
    private var trailingHeatAndBadge: some View {
        HStack(spacing: 10) {
            Group {
                if let bookedTime = day.bookedTime {
                    Label(bookedTime, systemImage: "flag.fill")
                        .font(scaledFont(.caption)).padding(.horizontal, 7).padding(.vertical, 3)
                        .background(Color.accentColor.opacity(0.15), in: Capsule())
                        .foregroundStyle(Color.accentColor)
                }
            }
            .frame(width: scale.scaled(Metrics.bookingBadge), alignment: .trailing)
            HeatStrip(buckets: day.heatStrip)
        }
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
/// one implementation of scraping and it stays in Python. See `macos/README.md`
/// on why that split is the whole point of the hybrid.
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
    /// Set only while browsing a club that has no `clubs/*.yaml` -- "browse
    /// before saving," the one Tier 2 gap this prototype's own README flagged
    /// as still open. See `startPreview()` below.
    @Published var previewClub: (id: String, name: String)?
    @Published var isPreviewLoading = false

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

    var isPreviewing: Bool { previewClub != nil }

    var clubName: String {
        if let previewClub { return previewClub.name.isEmpty ? previewClub.id : previewClub.name }
        return clubs.first { $0.path == clubPath }?.name ?? "teetime-monitor"
    }

    /// `days`, minus any day with no scraped tee-time slots at all -- direct
    /// report, 2026-09-19 ("hide days that don't contain details yet"). `days`
    /// itself attempts a fixed window regardless (mirrors tui.py's own
    /// `_display_dates()`, which does the same and shows every attempted date --
    /// there's no existing TUI precedent for hiding these, since its table has
    /// no equivalent "nothing to show yet" affordance), so a day this far out
    /// commonly has weather (a separate, always-available forecast) but no real
    /// slots yet -- a heat strip that's entirely grey with nothing to expand
    /// into, all cost and no use. Filtered here, not at `Store.days()`, so the
    /// underlying fetch window is unaffected and this is purely a display
    /// choice.
    var visibleDays: [Day] { days.filter { !$0.slots.isEmpty } }

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
        // A previewed club has no clubs/*.yaml, so it's invisible to
        // Scraper.run()'s own script (teetime-monitor-scrape iterates saved
        // favorites only) -- the same script startPreview() itself already
        // used to get that first scrape keeps working here for a repeat one.
        if let previewClub {
            PreviewClient.run(clubID: previewClub.id, clubName: previewClub.name) { [weak self] error in
                guard let self else { return }
                self.isScraping = false
                self.problem = error
                self.load()
            }
            return
        }
        Scraper.run { [weak self] error in
            guard let self else { return }
            self.isScraping = false
            self.problem = error
            self.load()
        }
    }

    /// Opens a live-scraped overview for `clubID` without saving it as a
    /// favorite -- the GUI's own version of `ClubBrowserScreen`'s "enter just
    /// opens it, `f` favorites separately" split. `PreviewClient` is the only
    /// new piece this needs: `clubPath` pointed at `Store.dbPath(clubID:)` is
    /// already a database every other reader here (`loadCourses()`/`reload()`,
    /// Search, the heatmap, confirm/cancel) treats exactly like a favorited
    /// club's, since none of them actually check `clubs/*.yaml` themselves.
    func startPreview(clubID: String, name: String, done: @escaping (String?) -> Void) {
        isPreviewLoading = true
        problem = nil
        PreviewClient.run(clubID: clubID, clubName: name) { [weak self] error in
            guard let self else { return }
            self.isPreviewLoading = false
            if let error {
                done(error)
                return
            }
            self.previewClub = (id: clubID, name: name)
            self.clubPath = Store.dbPath(clubID: clubID)
            self.loadCourses()
            done(nil)
        }
    }

    /// Back to the favorites list -- clearing `clubPath` first is what makes
    /// `load()` pick a real favorite (or none) instead of keeping the just-
    /// closed preview's own path, which `load()` otherwise leaves alone
    /// whenever it isn't already empty.
    func closePreview() {
        previewClub = nil
        clubPath = ""
        load()
    }

    /// Saves the currently previewed club as a real favorite (the same
    /// `teetime-monitor-add-club` script `AddClubSheet`'s own "Add" button
    /// uses) and folds it into the ordinary favorited-club state -- `clubPath`
    /// already points at the right database, so nothing about what's on
    /// screen needs to change, only that it now also appears in the toolbar's
    /// own Club picker and survives a relaunch.
    func favoritePreviewedClub(done: @escaping (String?) -> Void) {
        guard let previewClub else { done(nil); return }
        AddClubClient.add(clubID: previewClub.id, name: previewClub.name) { [weak self] slug, error in
            guard let self else { return }
            if slug != nil {
                self.previewClub = nil
                self.load()
                done(nil)
            } else {
                done(error ?? t("error.generic"))
            }
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

/// Routes the menu bar's Actions commands (see `TeetimeMonitorApp.body`'s
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
    @StateObject private var isFavoritingPreview = Box(false)
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
                            VStack(alignment: .leading, spacing: 1) {
                                // `course` is blank for a club-wide notice (e.g.
                                // reservations_sync_failed, which has no single slot to
                                // name) -- only shown when there's an actual course to
                                // name. Direct report 2026-09-20: the banner alone
                                // ("...your 14:20 tee time...") didn't say which course,
                                // easy to misread when a club has more than one.
                                if !banner.course.isEmpty {
                                    Text(banner.course).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                                }
                                Text(banner.text).font(scaledFont(.caption))
                            }
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
            // "Browse before saving" -- picking a club from Add a Club opens it
            // straight away, same as ClubBrowserScreen's own `enter`, with no
            // clubs/*.yaml written. This is the one place that isn't true, so
            // it says so plainly rather than leaving it to be assumed from the
            // Club row's own name (which looks identical to a saved club's).
            if model.isPreviewing {
                HStack(spacing: 8) {
                    Image(systemName: "eye").font(scaledFont(.caption)).foregroundStyle(.secondary)
                    Text(t("preview.banner")).font(scaledFont(.caption)).foregroundStyle(.secondary)
                    Spacer()
                    if isFavoritingPreview.value { ProgressView().controlSize(.small) }
                    Button(t("preview.add")) {
                        isFavoritingPreview.value = true
                        model.favoritePreviewedClub { error in
                            isFavoritingPreview.value = false
                            if let error { model.problem = error }
                        }
                    }
                    .disabled(isFavoritingPreview.value)
                    Button(t("preview.close")) { model.closePreview() }
                }
                .padding(8)
                .background(.secondary.opacity(0.12), in: RoundedRectangle(cornerRadius: 6))
            }
            // Two rows, not one. Six actions, two pickers and the club identity all
            // competing for a single row is what squeezed the title into wrapping
            // one word per line (fixed once with .lineLimit(1), but the real cause
            // was the row being overloaded). Splitting "what am I looking at" from
            // "what can I do about it" gives both room, and lets the actions carry
            // real text labels instead of six bare icons explained only by tooltip.
            // One row, not two -- direct follow-up, 2026-09-20 ("what if both
            // labels and dropdowns were all on the same row?"): the previous
            // label-above-control layout (Club/Platz each in their own two-line
            // VStack) put both labels at a shared baseline, but still cost a full
            // caption-line of height per column, and needed the club dropdown
            // blown up to .title2 bold just to read as *a* title -- a size the
            // course dropdown never matched, which is what actually looked "not
            // under its label" despite both being geometrically aligned. A single
            // "Club: X   Platz: Y" row fixes both at once: same font for every
            // label and every control, one line total instead of two.
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(t("overview.club")).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                if model.isPreviewing || model.clubs.isEmpty {
                    // A Picker lists favorited clubs only (see Store.clubs()'s
                    // own docstring) -- a previewed club was deliberately never
                    // added to that list, so it can't be one of this Picker's
                    // own choices either. Same plain-label fallback a fresh
                    // install with nothing saved yet already used.
                    Text(model.clubName).font(scaledFont(.body)).fontWeight(.semibold)
                        .lineLimit(1).truncationMode(.tail)
                } else {
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
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .font(scaledFont(.body)).fontWeight(.semibold)
                    .onChange(of: model.clubPath) { _, _ in model.loadCourses() }
                }
                Spacer(minLength: 12)
                Text(t("overview.course")).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                Picker("", selection: $model.course) {
                    ForEach(model.courses, id: \.self) { Text($0).tag($0) }
                }
                .labelsHidden().pickerStyle(.menu).font(scaledFont(.body)).fontWeight(.semibold)
                // No `.frame(width:)`/`.frame(minWidth:)` here any more --
                // direct report, 2026-09-26 ("dropdowns and buttons should be
                // better aligned, like on a grid"): giving this Picker *any*
                // width constraint (exact `width:` or even `minWidth:`, with
                // `alignment: .leading`) silently made this whole row's own
                // trailing Spacer stop expanding into the window's real width
                // -- confirmed by toggling just this one modifier with
                // everything else held constant, across several different
                // outer-layout attempts (a plain Spacer, ZStack + `.overlay`,
                // an explicitly `GeometryReader`-measured width + `.offset`),
                // all still broken identically whenever this frame was
                // present. Removing it entirely is what actually fixed the
                // misalignment; the previously-intended "don't shrink below
                // 230pt for a short course name" nicety is the one thing lost
                // -- this Picker now sizes to its own selected course name,
                // same as the Club picker beside it already does.
                .onChange(of: model.course) { _, _ in model.reload() }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // Grouped by what each action is *for* -- act on this course's data,
            // change how the app behaves -- rather than a row of equally-spaced
            // icons implying every one is unrelated to its neighbors. "Add Club"
            // used to sit here as its own group; moved into Settings' new Clubs
            // section (2026-09-19, direct request, "integrate add/remove club
            // into settings"), the one place club management -- add *and*
            // remove -- now lives together, rather than add being the one club-
            // management action stranded in the toolbar. Still reachable without
            // opening Settings via the Actions menu (⌘-hold discoverable, see
            // AppCommands' own docstring).
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

                Spacer()

                Button { showingPreferences.value = true } label: {
                    Label(t("action.preferences"), systemImage: "slider.horizontal.3")
                }
                .help(t("tip.preferences"))
                Button { showingSettings.value = true } label: { Label(t("action.settings"), systemImage: "gearshape") }
                    .help(t("tip.settings"))
            }

            if model.isPreviewLoading {
                VStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(t("preview.loading")).font(scaledFont(.caption)).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.visibleDays.isEmpty {
                // maxWidth: .infinity too -- same off-center bug as Search/Add a
                // Club's own empty states (this VStack is alignment: .leading too).
                ContentUnavailableView(
                    t("overview.empty_title"),
                    systemImage: "calendar.badge.exclamationmark",
                    description: Text(model.clubs.isEmpty && !model.isPreviewing
                        ? t("overview.empty_no_clubs")
                        : t("overview.empty_pick_another")))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
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
                        ForEach(model.visibleDays) { day in
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
            //
            // Freshness/version sit to its right, not up by the title any more --
            // direct request, 2026-09-19 ("place refresh status and version to
            // bottom right of window (legend area)"). Both rows are the same
            // kind of thing -- quiet status text about the app/data, not the
            // club identity the title conveys -- so this also finishes what
            // moving version down off the title started two rounds ago. Always
            // shown (not gated on `!model.visibleDays.isEmpty` the way LegendLine
            // itself is) so freshness/version don't disappear along with the
            // legend on a genuinely empty day list.
            HStack(alignment: .top) {
                if !model.visibleDays.isEmpty {
                    LegendLine()
                }
                Spacer(minLength: 12)
                VStack(alignment: .trailing, spacing: 2) {
                    FreshnessRow(model: model)
                    // Mirrors the TUI's own Header, which sets its subtitle to
                    // "v{version}" from the same package metadata -- direct
                    // request, 2026-09-19 ("I want to see the version ... It
                    // should match with the version of the TUI."). The
                    // Info.plist value this reads comes from pyproject.toml at
                    // build time (see build.sh), the same file tui.py's own
                    // _version() reads, so there is one number and both apps
                    // show it. The standard "About TeetimeMonitor" panel reads
                    // this same Info.plist key automatically -- nothing else
                    // to wire up for that half.
                    Text(appVersionString).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                }
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
            SettingsSheet(verifyClubID: model.clubs.first { $0.path == model.clubPath }?.id, model: model)
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
struct TeetimeMonitorApp: App {
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
