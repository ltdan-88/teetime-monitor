import SwiftUI

// icon(for:)/fillColor(_:)/weekday(_:) moved to Formatting.swift so they can sit in
// the SPM test target -- see that file's own docstring.

/// "Sat 4 Oct · 18 Loch" above a booking-change banner: which day (and course) it is
/// about. Either part is left out when blank (a club-wide notice has no course).
func bannerCaption(_ banner: Banner) -> String {
    [banner.date.isEmpty ? "" : weekday(banner.date), banner.course]
        .filter { !$0.isEmpty }.joined(separator: " · ")
}

/// `icon(for:)`, but nil (draw nothing) when there's no code or it isn't a known one --
/// the TUI leaves that cell blank (weather_icons.icon_for_code(): "blank, not a guess")
/// rather than showing a question mark.
func knownConditionIcon(_ code: Int?) -> String? {
    let name = icon(for: code)
    return name == "questionmark" ? nil : name
}

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

/// The day-row half of the legend (the figures and colours the day cards show) --
/// `tui.py`'s `OVERVIEW_LEGEND` plays the same role. Lives inside the "?" popover
/// (`LegendButton`) as of 2026-10-03; it used to be a permanent line under the day
/// list, which duplicated what the popover and the cell tooltips already say.
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
            ("lock.fill", t("legend.locked")),
        ]
    }

    // The heat strip's own green/orange/red meaning -- direct report,
    // 2026-09-19 ("color bars still don't say what they represent"). The
    // previous round only added the "08:00-20:00" *time window* to this line (a
    // different gap the same complaint's wording pointed at); the color *scale*
    // itself was never actually explained anywhere the day list shows it. Same
    // three colors, same thresholds as `fillColor()` as HeatmapSheet's own grid
    // cells use, but a genuinely different *fact* -- this is one real day's own
    // live booked/capacity fraction, not an average across scraped history the
    // way a heatmap cell is -- so as of 2026-09-28 this has its own wording
    // (`overview.crowd_legend.*`) instead of sharing `heatmap.legend.*`
    // verbatim: describing a live count as "usually quiet"/"usually full" (that
    // key's own post-2026-09-28 wording) would have been actively wrong here,
    // not just inconsistent copy for "the same three states" the way the
    // original version of this comment assumed.
    private var heatSwatches: [(color: Color, text: String)] {
        [(.green, t("overview.crowd_legend.open")), (.orange, t("overview.crowd_legend.mid")),
         (.red, t("overview.crowd_legend.full"))]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(t("legend.day_title")).font(.headline)
            ForEach(entries, id: \.text) { entry in
                HStack(spacing: 8) {
                    Image(systemName: entry.icon).frame(width: 22)
                    Text(entry.text)
                }
            }
            Divider()
            Text(t("legend.occupancy_title")).font(.headline)
            ForEach(heatSwatches, id: \.text) { swatch in
                HStack(spacing: 8) {
                    RoundedRectangle(cornerRadius: 2).fill(swatch.color)
                        .frame(width: scale.scaled(Metrics.legendSwatchWidth),
                               height: scale.scaled(Metrics.legendSwatchHeight))
                        .frame(width: 22)
                    Text(swatch.text)
                }
            }
        }
    }
}

/// The "?" next to the freshness status: the whole legend in one popover -- the day
/// row's figures, the occupancy colours, every weather icon and the player-name
/// colours (the TUI's `?` legend). Direct request, 2026-10-03: the permanent legend
/// line was redundant with it, so everything lives here now.
struct LegendButton: View {
    @ObservedObject private var language = AppLanguage.shared
    @ObservedObject private var commands = AppCommands.shared

    private let entries: [(code: Int, key: String)] = [
        (0, "legend.cond_clear"), (1, "legend.cond_cloudy"), (3, "legend.cond_overcast"),
        (45, "legend.cond_fog"), (51, "legend.cond_drizzle"), (61, "legend.cond_rain"),
        (71, "legend.cond_snow"), (95, "legend.cond_thunder"),
    ]

    var body: some View {
        Button { commands.legendShown.toggle() } label: {
            Label(t("tip.legend"), systemImage: "questionmark.circle")
                .font(scaledFont(.caption2))
        }
            .buttonStyle(.borderless)
            .foregroundStyle(.secondary)
            .help(t("tip.legend"))
            .popover(isPresented: $commands.legendShown, arrowEdge: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    LegendLine()
                    Divider()
                    Text(t("legend.cond_title")).font(.headline)
                    ForEach(entries, id: \.code) { entry in
                        HStack(spacing: 8) {
                            Image(systemName: icon(for: entry.code)).frame(width: 22)
                            Text(t(entry.key))
                        }
                    }
                    Divider()
                    Text(t("legend.players_title")).font(.headline)
                    HStack(spacing: 8) {
                        Text("Aa").bold().foregroundStyle(genderColor("male")).frame(width: 22)
                        Text(t("legend.player_male"))
                    }
                    HStack(spacing: 8) {
                        Text("Aa").bold().foregroundStyle(genderColor("female")).frame(width: 22)
                        Text(t("legend.player_female"))
                    }
                    HStack(spacing: 8) {
                        Text("\u{2605}").foregroundStyle(.yellow).frame(width: 22)
                        Text(t("legend.player_friend"))
                    }
                }
                .padding(12)
            }
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
    /// Briefly true right after a double-click-a-player jump lands here -- see
    /// `OverviewModel.highlightedSlot`'s own docstring.
    var isFocused: Bool { model.highlightedSlot == OverviewModel.ScrollTarget(date: day.date, time: slot.time) }

    /// Pip `i` is one of the friend seats -- as many pips as there are friends in
    /// this slot (the player list skips anonymised seats, so it can't be matched to
    /// pip positions one-to-one; the count is what's reliably known). Starts after
    /// the "you" pip. Direct request, 2026-10-02: highlight the squares too.
    private func isFriendSeat(_ i: Int) -> Bool {
        let friends = slot.players.filter { model.friendNames.contains($0) }.count
        let start = isMine ? 1 : 0
        return i >= start && i < start + friends
    }

    private var playersText: Text {
        var result = AttributedString()
        for (i, name) in slot.players.enumerated() {
            if i > 0 {
                var comma = AttributedString(", "); comma.foregroundColor = .secondary
                result += comma
            }
            // A friend: gold ★ in front and a bold name (the ★ matches the gold friend
            // pips); the name itself is coloured by gender -- blue / magenta, neutral
            // when unknown (direct request, 2026-10-03).
            if model.friendNames.contains(name) {
                var star = AttributedString("\u{2605} "); star.foregroundColor = .yellow
                result += star
            }
            var part = AttributedString(name)
            part.foregroundColor = genderColor(model.playerGenders[name])
            if model.friendNames.contains(name) { part.inlinePresentationIntent = .stronglyEmphasized }
            result += part
        }
        let anonymous = anonymousPlayersText(booked: slot.booked, namedCount: slot.players.count)
        if !anonymous.isEmpty {
            var part = AttributedString((slot.players.isEmpty ? "" : ", ") + anonymous)
            part.foregroundColor = .secondary
            part.inlinePresentationIntent = .emphasized
            result += part
        }
        return Text(result)
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
                                  ? (isMine && i == 0 ? Color.accentColor
                                     : isFriendSeat(i) ? Color.yellow : theme.colors.muted)
                                  : theme.colors.faint)
                            .frame(width: scale.scaled(Metrics.seatPip),
                                   height: scale.scaled(Metrics.seatPip))
                    }
                }
                .help(t("tip.seat_pips", ["booked": "\(slot.booked)", "capacity": "\(slot.capacity)"]))
                Text(t("overview.free", ["n": "\(slot.capacity - slot.booked)"]))
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary)
                    .help(t("tip.open_spots"))
                if !slot.players.isEmpty || slot.booked > 0 {
                    // Only ever non-empty from an authenticated scrape (2026-09-27) --
                    // pc caddie shows real names only to a logged-in member who's
                    // opted into its own reciprocal name-sharing. Never sent to any
                    // AI provider (see ai_assist.py's `_describe_candidate()`), local
                    // display only, same truncated-with-tooltip treatment as
                    // SearchSheet's own players cell.
                    let names = ([slot.players.joined(separator: ", "),
                                  anonymousPlayersText(booked: slot.booked, namedCount: slot.players.count)]
                                 .filter { !$0.isEmpty }).joined(separator: ", ")
                    // Friends in bold gold, same gold the player directory's own ★ uses
                    // (direct request, 2026-10-02: "highlight friends when uncollapsing").
                    playersText.font(scaledFont(.caption2)).lineLimit(1)
                        .help(names)
                }
            }

            Spacer()

            // Sunrise/sunset noted on whichever slot row is actually closest to it --
            // mirrors tui._closest_slot_time()'s placement exactly, not a single
            // summary line detached from any specific time (see Day.sunriseRowTime/
            // sunsetRowTime for the tie-break rule this shares with Python).
            if slot.time == day.sunriseRowTime {
                Label(t("overview.sunrise_at", ["time": day.sunrise ?? ""]), systemImage: "sunrise.fill")
                    .font(scaledFont(.caption2)).foregroundStyle(.orange).lineLimit(1).fixedSize()
            }
            if slot.time == day.sunsetRowTime {
                Label(t("overview.sunset_at", ["time": day.sunset ?? ""]), systemImage: "sunset.fill")
                    .font(scaledFont(.caption2)).foregroundStyle(.orange).lineLimit(1).fixedSize()
            }
            if isMine {
                Label(t("overview.you"), systemImage: "flag.fill")
                    .font(scaledFont(.caption2)).foregroundStyle(Color.accentColor).lineLimit(1).fixedSize()
            }
            if let w = day.weather(at: slot.time) {
                // ZStack, not Group: an empty Group drops its frame, and the column must stay.
                ZStack {
                    if let name = knownConditionIcon(w.code) {
                        Image(systemName: name).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                    }
                }
                    .help(weatherTooltip(w, units: units.value))
                    .frame(width: scale.scaled(Metrics.slotCondition))
                if let tempC = w.temperatureC {
                    Text(String(format: "%.0f°", Units.temperature(tempC, units.value)))
                        .font(scaledFont(.caption2)).foregroundStyle(.secondary)
                        .frame(width: scale.scaled(Metrics.slotTemp), alignment: .trailing)
                        .help(t("tip.temp", ["unit": Units.temperatureSymbol(units.value)]))
                }
                // A point with no probability still shows "0%" (and any amount),
                // as tui._slot_precipitation_cell() does -- it used to vanish.
                let p = w.precipitationProbability ?? 0
                Group {
                    // 🌧 only above the threshold -- the real number always shows, same
                    // "worth noticing at a glance flag layered on the number, not a
                    // gate on it" rule tui._slot_precipitation_cell() documents.
                    // "70%/1.5mm", not just "70%" -- direct report, 2026-09-19
                    // ("precipitation amount in mm seems to still be missing"),
                    // mirroring that same function's own probability+amount cell.
                    HStack(spacing: 1) {
                        if p >= 50 { Text("🌧").font(.system(size: scale.scaled(9))) }
                        Text(precipitationCellText(probability: p, mm: w.precipitationMM, units: units.value)).lineLimit(1)
                    }
                    .font(scaledFont(.caption2)).foregroundStyle(.secondary).frame(width: scale.scaled(Metrics.slotPrecip), alignment: .trailing)
                    .help(p >= 50 ? t("tip.rain_flagged") : t("tip.rain"))
                }
                if let wd = w.windKPH {
                    HStack(spacing: 1) {
                        if wd >= 30 { Text("💨").font(.system(size: scale.scaled(9))) }
                        Text(wholeNumber(Units.windSpeed(wd, units.value)))
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
        .opacity(isPastSunset && !isFocused ? 0.4 : 1)
        .onAppear { if isFocused { model.focusedRowAppeared = true } }
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
        // isFocused takes the same accent color as the hover state (same
        // "visible contrast in every theme" reasoning right above) but at full
        // opacity, not 0.15 -- a row that only ever looked like a hover would
        // read as "your mouse happens to be here," not "this is the one you
        // jumped to." `withAnimation` at both ends (set and clear, in the
        // `.onChange` that owns this state) is what turns the opacity jump into
        // an actual flash instead of an instant on/off.
        .background(
            isFocused ? theme.colors.accent.opacity(0.7)
                : (isHovering.value && !slot.isBlocked ? theme.colors.accent.opacity(0.15) : Color.clear),
            in: RoundedRectangle(cornerRadius: 4)
        )
        // A solid accent outline on top of the fill (direct follow-up, 2026-09-29:
        // "make the row highlight more visible") -- a translucent fill alone can sit
        // close to a theme's own background; an opaque border reads in every theme.
        .overlay(
            RoundedRectangle(cornerRadius: 4)
                .stroke(theme.colors.accent, lineWidth: 2)
                .opacity(isFocused ? 1 : 0)
        )
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
                    if !Store.cancelBooking(dbPath: model.clubPath, course: model.course, date: day.date) {
                        model.problem = t("error.save_failed")
                    }
                    model.reload()
                }
            } else {
                Button(t("booking.confirm")) {
                    if !Store.confirmBooking(dbPath: model.clubPath, course: model.course, date: day.date, time: slot.time) {
                        model.problem = t("error.save_failed")
                    }
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
                        // Accordion: opening a day closes the others (direct request, 2026-10-02).
                        if isOpen { model.expanded.remove(day.date) } else { model.expanded = [day.date] }
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
            // Blank, not "?", with no daytime forecast (tui._condition_cell()).
            ZStack {
                if let name = knownConditionIcon(day.conditionCode) {
                    Image(systemName: name).foregroundStyle(.secondary)
                }
            }
                .help(conditionName(for: day.conditionCode).map { t("tip.condition_day_named", ["condition": $0]) }
                      ?? t("tip.condition_day"))
                .frame(width: scale.scaled(Metrics.dayCondition))
            Group {
                if let (hi, lo) = day.tempHighLow {
                    Label("\(wholeNumber(Units.temperature(hi, units.value)))°/"
                          + "\(wholeNumber(Units.temperature(lo, units.value)))°",
                          systemImage: "thermometer.medium")
                        .font(scaledFont(.subheadline, design: .monospaced))
                        .help(t("tip.temp_day", ["unit": Units.temperatureSymbol(units.value)]))
                }
            }
            .frame(width: scale.scaled(Metrics.dayTemp), alignment: .leading)
            Group {
                if let p = day.precipAvg {
                    // The tooltip carries the TUI's whole cell (total mm, "rain all
                    // day") -- the 46pt column only fits the average.
                    Label("\(wholeNumber(p))%", systemImage: "drop.fill")
                        .font(scaledFont(.caption)).foregroundStyle(.secondary)
                        .help(t("tip.rain_day") + " — " + day.precipitationCellText(units: units.value))
                }
            }
            .frame(width: scale.scaled(Metrics.dayRain), alignment: .leading)
            Group {
                if let wd = day.windPeak {
                    Label(wholeNumber(Units.windSpeed(wd, units.value)), systemImage: "wind")
                        .font(scaledFont(.caption)).foregroundStyle(.secondary)
                        .help(t("tip.wind_day", ["unit": Units.windSymbol(units.value)])
                              + " — " + day.windCellText(units: units.value))
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
                } else if let lock = model.locked[day.date] {
                    // A day that isn't bookable yet (2026-10-05) -- the TUI's "🔒 Wed 21:00" Pick
                    // cell. Ahead of the pick like there: nothing to pick on a locked day anyway.
                    LockBadge(lock: lock, now: model.now())
                } else if let pick = model.picks[day.date] {
                    // The recommended pick, once there's no real booking to show
                    // instead -- mirrors tui.py's own _day_pick_text() priority
                    // exactly (confirmed booking beats the pick). Reasons (empty
                    // unless AI ranking is on) go in a hover tooltip rather than
                    // inline text, same "real AI text can be longer than a badge
                    // has room for" reasoning just applied to SearchSheet's own
                    // reasons cell -- there's no natural place for a multi-line
                    // caption inside this fixed-height pinned header.
                    Label(pick.time, systemImage: "star.fill")
                        .font(scaledFont(.caption)).padding(.horizontal, 7).padding(.vertical, 3)
                        .background(Color.yellow.opacity(0.15), in: Capsule())
                        .foregroundStyle(Color.yellow)
                        .help(pick.reasons.isEmpty ? t("tip.pick") : pick.reasons.joined(separator: ", "))
                } else if let alternative = model.alternatives[day.date] {
                    // Too dark for this course, but a shorter round on another one
                    // still fits (2026-10-05) -- the TUI's "★ 16:10 · 9H" Pick cell.
                    // Secondary tint, not the pick's yellow, so it never reads as this
                    // course's own pick; the tooltip names the course. A click
                    // switches to that course and jumps to the slot.
                    ShorterRoundBadge(alternative: alternative) {
                        model.jumpToShorterRound(on: day.date, alternative)
                    }
                } else if let reasons = model.verdicts[day.date]?.unplayable, !reasons.isEmpty {
                    // Why there's no pick (2026-09-27, bundle C of the TUI/GUI
                    // consistency audit) -- the TUI has always said "too dark to
                    // finish"/"no dry picks" here; this used to show nothing at
                    // all. A compact icon capsule in the badge's own fixed width
                    // (full sentence on hover), not the sentence itself, so the
                    // column still lines up on every row.
                    let tooDark = reasons == ["daylight"]
                    Image(systemName: tooDark ? "moon.fill" : "cloud.rain.fill")
                        .font(scaledFont(.caption)).padding(.horizontal, 9).padding(.vertical, 3)
                        .background(Color.secondary.opacity(0.12), in: Capsule())
                        .foregroundStyle(.secondary)
                        .help(t(tooDark ? "tip.no_pick_daylight" : reasons == ["weather"] ? "tip.no_pick_weather" : "tip.no_pick_both"))
                }
            }
            .frame(width: scale.scaled(Metrics.bookingBadge), alignment: .trailing)
            HeatStrip(buckets: day.heatStrip)
        }
    }
}

/// A locked day in `DayCardHeader`'s pick badge slot: "🔒 Wed 21:00" in the same capsule,
/// font and padding as the pick and the alternative, secondary tint (2026-10-05). The
/// tooltip is the TUI's #row-detail sentence ("Booking opens Wed 21:00"), same i18n keys.
/// Capped at the slot's width like `ShorterRoundBadge`, so a longer value truncates
/// instead of moving the HeatStrip.
struct LockBadge: View {
    let lock: LockedDay
    let now: Date
    @ObservedObject private var scale = AppScale.shared
    @ObservedObject private var language = AppLanguage.shared

    var body: some View {
        if let when = lockWhenText(opensAt: lock.opensAt, hourKnown: lock.hourKnown, now: now) {
            // The sentence ("Booking opens Wed 21:00") is the tooltip and, for VoiceOver, the
            // label -- the visible text alone ("Wed 21:00") never says what the time is.
            let sentence = lockSentence(opensAt: lock.opensAt, hourKnown: lock.hourKnown, now: now) ?? when
            Label(when, systemImage: "lock.fill")
                .font(scaledFont(.caption)).lineLimit(1)
                .padding(.horizontal, 7).padding(.vertical, 3)
                .background(Color.secondary.opacity(0.12), in: Capsule())
                .foregroundStyle(.secondary)
                .frame(maxWidth: scale.scaled(Metrics.bookingBadge), alignment: .trailing)
                .help(sentence)
                .accessibilityLabel(sentence)
        }
    }
}

/// The shorter-round alternative in `DayCardHeader`'s pick badge slot -- "★ 16:10 · 9H"
/// in the pick's own capsule, font and padding, only the tint differs (2026-10-05).
/// Full-size text, not shrunk to fit: `Metrics.bookingBadge` was widened for it
/// instead, on every row alike, so the grid stays aligned.
struct ShorterRoundBadge: View {
    let alternative: ShorterRound
    let action: () -> Void
    @ObservedObject private var scale = AppScale.shared
    @ObservedObject private var language = AppLanguage.shared

    var body: some View {
        Button(action: action) {
            Label("\(alternative.time) · \(t("overview.pick_holes", ["n": "\(alternative.holes)"]))",
                  systemImage: "star.fill")
                .font(scaledFont(.caption)).lineLimit(1)
                .padding(.horizontal, 7).padding(.vertical, 3)
                .background(Color.secondary.opacity(0.12), in: Capsule())
                .foregroundStyle(.secondary)
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        // Capped at the slot's width, so a longer value truncates rather than spill.
        .frame(maxWidth: scale.scaled(Metrics.bookingBadge), alignment: .trailing)
        .help(t("overview.pick_alternative", ["time": alternative.time, "course": alternative.course,
                                              "holes": "\(alternative.holes)"])
              + " " + t("tip.pick_alternative_click"))
    }
}

/// The slot list for one *open* day -- see `DayCardHeader`'s own docstring for why
/// this is a separate view. Rendered as this day's `Section` content in
/// `ContentView`'s pinned-header `LazyVStack`; omitted entirely (not just hidden)
/// while the day is collapsed, so a collapsed day's `Section` has no content to
/// scroll through and its header hands off to the next day's immediately.
/// The `.id` an expanded day's slot row carries, so ContentView's
/// ScrollViewReader can scroll straight to it (see `OverviewModel.focusTime`).
func slotAnchor(_ date: String, _ time: String) -> String { "\(date) \(time)" }

struct DayCardBody: View {
    let day: Day
    @ObservedObject var model: OverviewModel
    @ObservedObject private var theme = AppTheme.shared

    // Sunrise row through sunset row -- see `Day.visibleSlots`.
    private var visibleSlots: [Slot] { day.visibleSlots }

    var body: some View {
        VStack(spacing: 0) {
            Divider()
            VStack(spacing: 0) {
                ForEach(visibleSlots) { slot in
                    // Outside your own window: dimmed, same as the TUI's own
                    // expanded rows (2026-09-27, bundle C) -- still there to
                    // read, just not competing with the ones you'd book.
                    SlotRow(slot: slot, day: day, model: model)
                        .opacity(model.verdicts[day.date]?.isOutsideWindow(slot.time) == true
                                 && model.highlightedSlot != OverviewModel.ScrollTarget(date: day.date, time: slot.time) ? 0.4 : 1)
                        .id(slotAnchor(day.date, slot.time))
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
            // --source gui tags this pass's scrape_runs row (2026-10-05, scrape health).
            task.arguments = ["--force", "--source", "gui"]
            // stdout (scrape_once's _log lines) is never read, so it goes nowhere rather
            // than into a pipe: an unread pipe fills at ~64 KB and blocks the scraper.
            // stderr is drained to EOF *before* waiting for the same reason.
            let err = Pipe(); task.standardError = err; task.standardOutput = FileHandle.nullDevice
            do { try task.run() } catch {
                DispatchQueue.main.async { done(error.localizedDescription) }
                return
            }
            let errData = err.fileHandleForReading.readDataToEndOfFile()
            task.waitUntilExit()
            let stderr = String(data: errData, encoding: .utf8) ?? ""
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
    /// Names marked as friends in the player directory -- highlighted in expanded slot rows.
    @Published var friendNames: Set<String> = []
    /// Name -> "male"/"female", colours names in expanded slot rows.
    @Published var playerGenders: [String: String] = [:]
    @Published var expanded: Set<String> = []
    @Published var isScraping = false
    @Published var problem: String?
    @Published var lastScrape: Date?
    /// The club's recent `scrape_runs`, summarized (2026-10-05, see ScrapeHealth.swift)
    /// -- drives the footer's health warning and the freshness dot's red/amber.
    @Published var scrapeHealth: ScrapeHealth = .empty
    @Published var banners: [Banner] = []
    /// Set only while browsing a club that has no `clubs/*.yaml` -- "browse
    /// before saving," the one Tier 2 gap this prototype's own README flagged
    /// as still open. See `startPreview()` below.
    @Published var previewClub: (id: String, name: String)?
    @Published var isPreviewLoading = false
    /// Recommended pick per date, keyed the same way `Day.date` is -- see
    /// `PicksClient.swift`'s own docstring. Fetched fire-and-forget at the end of
    /// `reload()` below; starts (and on failure, stays) empty, same "the core
    /// Overview must render correctly with or without this" stance
    /// `_availability_pipeline()` itself takes.
    @Published var picks: [String: DayPick] = [:]
    /// Per date: your window and, with no pick, why -- see `DayVerdict`.
    @Published var verdicts: [String: DayVerdict] = [:]
    /// Per date: a shorter round on another course for a day too dark to finish
    /// this one (2026-10-05) -- see `ShorterRound`.
    @Published var alternatives: [String: ShorterRound] = [:]
    /// Per date: a day that isn't bookable yet and when it opens (2026-10-05) -- see `LockedDay`.
    @Published var locked: [String: LockedDay] = [:]
    /// Set when your window opens too late to finish before dark, several days
    /// running -- see `WindowHint` and ContentView's own hint row.
    @Published var windowHint: WindowHint?

    /// A specific (date, time) to expand and scroll to right now -- distinct from
    /// the automatic "which slot does a newly-expanded day scroll to"
    /// (`focusTime(for:)` below), which only ever runs off a *change* to
    /// `expanded` and only ever picks the day's own ★ pick or window-open time.
    /// Set by `PlayerDirectorySheet`'s own double-click-a-player feature
    /// (2026-09-28, direct request: "would it be possible to double click a
    /// player in the directory and focus on their booked tee time or tee
    /// times?") -- that needs to jump to one *specific* slot a chosen player is
    /// actually in, which `focusTime(for:)`'s own heuristic has no way to know
    /// about, and needs to work even when the target day is *already* expanded
    /// (inserting an already-present date into `expanded` fires no change at
    /// all, so reusing that mechanism alone would silently do nothing the
    /// second time you focus the same day). `ContentView`'s own
    /// `.onChange(of: model.scrollRequest)` clears this back to `nil` once
    /// handled, so setting it to the *same* target again still triggers a
    /// fresh scroll (nil -> value is always a real change, even when the
    /// previous value would have compared equal).
    struct ScrollTarget: Equatable { let date: String; let time: String }
    @Published var scrollRequest: ScrollTarget?

    /// The slot `scrollRequest` last landed on, briefly -- direct follow-up,
    /// 2026-09-28: "double-clicking a player and focusing doesn't select a row,
    /// so it is still a bit difficult to pinpoint a player." Scrolling alone gets
    /// you to roughly the right place in a day that can hold 40+ slot rows, but
    /// says nothing about *which* row is the one you actually asked for.
    /// `ContentView`'s own `.onChange(of: model.scrollRequest)` sets this
    /// alongside the scroll itself and clears it a couple seconds later --
    /// `SlotRow.isFocused` reads it to flash, not permanently mark, the target
    /// row, the same "confirms you landed on the right one, then gets out of the
    /// way" convention jump-to-definition/jump-to-file UIs already use elsewhere.
    @Published var highlightedSlot: ScrollTarget?

    /// The day a `scrollRequest` jump is currently expanding, so the generic
    /// expand-driven scroll to that day's ★ pick doesn't race the jump.
    var jumpingToDate: String?

    /// Set by the focused `SlotRow` when it is actually realized on screen (it lives in
    /// a lazy stack, so this is the only reliable "the scroll landed" signal), read by
    /// the jump's retry loop and its highlight timer in `ContentView`.
    var focusedRowAppeared = false

    /// The slot an expanded `date` should scroll to: its ★ pick, otherwise the
    /// first visible slot at or after your window opens -- mirrors
    /// `tui.OverviewScreen._focus_row_for()` (2026-09-27, bundle C).
    func focusTime(for date: String) -> String? {
        guard let day = days.first(where: { $0.date == date }) else { return nil }
        let wanted = picks[date]?.time ?? verdicts[date]?.windowAfter
        guard let wanted else { return nil }
        return day.visibleSlots.first { $0.time >= wanted }?.time
    }

    /// The `scrollRequest` waiting for `course`'s days to load -- set by
    /// `jumpToShorterRound`, applied by `applyPendingJump()` once `reload()` has
    /// the new course's days on screen (the jump can't scroll to a day that
    /// isn't loaded yet).
    var pendingJump: (course: String, target: ScrollTarget)?

    /// Clicking a shorter-round badge (2026-10-05): switch the course picker to
    /// that course -- the same path a manual switch takes (ContentView's
    /// `onChange(of: model.course)` collapses and reloads) -- then jump to the
    /// slot through the usual `scrollRequest`/`highlightedSlot` mechanism.
    func jumpToShorterRound(on date: String, _ alternative: ShorterRound) {
        guard courses.contains(alternative.course) else { return }
        let target = ScrollTarget(date: date, time: alternative.time)
        if course == alternative.course { scrollRequest = target; return }
        pendingJump = (alternative.course, target)
        expanded = []
        course = alternative.course
    }

    /// Hands a `pendingJump` to `scrollRequest` once its course is the one
    /// loaded; dropped if the course moved on to something else meanwhile.
    func applyPendingJump() {
        guard let pending = pendingJump else { return }
        pendingJump = nil
        if pending.course == course { scrollRequest = pending.target }
    }

    private var watcher: Timer?
    private var seenModification: Date?
    /// The (clubPath, course) `picks`/`verdicts`/`windowHint` currently on screen
    /// were actually fetched for -- see `reload()`'s own comment on why this exists.
    /// Not `private`: `TeetimeMonitorCoreTests` seeds it directly to simulate "a
    /// real prior fetch already landed for this course" without needing a live
    /// subprocess round trip.
    var picksRequestKey: (path: String, course: String)?

    /// Whether a fetch for `request` should blank the currently-shown picks/verdicts/
    /// windowHint first -- true the moment `current` (whatever the on-screen state
    /// actually belongs to) names a different club/course than `request`, false for
    /// a same-club/course reload. Pulled out of `reload()` itself as a pure static
    /// function, not because `reload()` needed the indirection, but because
    /// `reload()`'s own async completion runs through a real `PicksClient.run()`
    /// subprocess call whose *timing* differs by environment in a way that matters
    /// for testing this exact decision: on a machine with `teetime-monitor-picks`
    /// actually installed (any real dev machine), `PicksClient.run()` dispatches
    /// genuinely asynchronously and reload() returns before it completes; on a
    /// clean CI runner with no such binary, `PicksClient.executable()` finds
    /// nothing and its completion fires *synchronously*, inside `reload()` itself,
    /// with an empty result -- found live, 2026-09-28: a first version of this
    /// fix's own test (asserting a *same*-course reload leaves picks/windowHint
    /// alone) passed locally and failed in CI for exactly this reason, testing an
    /// accidental timing artifact rather than the actual clearing decision. Testing
    /// this predicate directly sidesteps the subprocess entirely, so the test is
    /// deterministic in both environments.
    static func picksRequestChanged(from current: (path: String, course: String)?,
                                     to request: (path: String, course: String)) -> Bool {
        current?.path != request.path || current?.course != request.course
    }

    /// Green while the background agent's own cadence (see `freshnessThreshold`) would have refreshed by now,
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
        // Health first (2026-10-05): a rejected login or failing scrapes colour the dot
        // even while the last saved schedule still looks recent enough to be green.
        if let warning = healthWarning(now: now) {
            return warning.status == .failing ? .red : .orange
        }
        guard let lastScrape else { return .secondary }
        let threshold = Self.freshnessThreshold(intervalMinutes: scrapeIntervals.normal,
                                                bookedIntervalMinutes: scrapeIntervals.booked,
                                                anyBooked: days.contains { $0.bookedTime != nil })
        return now.timeIntervalSince(lastScrape) < threshold ? .green : .orange
    }

    /// The scraper's own cadence (`scrape_interval_minutes[_booked]`), re-read in
    /// `load()` -- `_should_scrape()` only writes a row once a course/date is due, so
    /// MAX(scraped_at) is routinely hours old while the agent is perfectly healthy.
    var scrapeIntervals: (normal: Int, booked: Int) = (360, 60)

    /// Seconds after the last scrape before the dot turns amber: the applicable
    /// interval (the booked one if any shown day is booked) ×1.25 plus 15 minutes for
    /// the launchd agent's own 15-minute tick.
    static func freshnessThreshold(intervalMinutes: Int, bookedIntervalMinutes: Int, anyBooked: Bool) -> TimeInterval {
        let minutes = anyBooked ? min(intervalMinutes, bookedIntervalMinutes) : intervalMinutes
        return (Double(minutes) * 1.25 + 15) * 60
    }

    /// The footer's scrape-health warning, nil while healthy -- same text and thresholds
    /// as the TUI's `#status` line (scrape_health.py), against the same interval the
    /// scraper itself uses.
    func healthWarning(now: Date) -> ScrapeHealthWarning? {
        ScrapeHealthRules.warning(scrapeHealth, intervalMinutes: scrapeIntervals.normal, now: now)
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

    private var today: String { ISODate.today() }

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
                self.reload(picksDelay: 4)
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
        let prefs = Preferences.load()
        scrapeIntervals = (prefs.scrapeIntervalMinutes, prefs.scrapeIntervalMinutesBooked)
        // Newest-scraped first (see Store.clubs) -- picking alphabetically landed on
        // an empty leftover test database and showed "no scraped days" forever.
        // Also re-picks when the shown club was just removed in Settings (its DB
        // survives the removal, so nothing else would notice); a previewed club is
        // never in `clubs` by design.
        if Self.needsClubRepick(clubPath: clubPath, clubs: clubs.map(\.path), isPreviewing: isPreviewing) {
            let wasSet = !clubPath.isEmpty
            clubPath = clubs.first?.path ?? ""
            if wasSet { expanded = []; loadCourses(preferDefault: true); return }
        }
        loadCourses(preferDefault: course.isEmpty)  // a launch, not a later reload
    }

    /// Whether `load()` must pick a different club: none chosen yet, or the chosen
    /// one is no longer a saved club (and isn't a preview).
    static func needsClubRepick(clubPath: String, clubs: [String], isPreviewing: Bool) -> Bool {
        clubPath.isEmpty || (!isPreviewing && !clubs.contains(clubPath))
    }

    /// The club's saved `default_course` (clubs/<slug>.yaml, shared with the TUI), if any.
    func defaultCourse() -> String? {
        guard let slug = clubs.first(where: { $0.path == clubPath })?.slug else { return nil }
        return ClubDefaults.defaultCourse(slug: slug)
    }

    /// The club's `overview_days` (default 5) -- the same calendar window the TUI's
    /// overview lists, used for the day list and the picks/search runs alike.
    func overviewDays() -> Int {
        ClubDefaults.overviewDays(slug: clubs.first(where: { $0.path == clubPath })?.slug)
    }

    /// `preferDefault`: launch / club switch -- start on the club's default course
    /// (direct request, 2026-10-03: a 9-hole member wants to open on the 9-hole course).
    /// Any other reload keeps the course you're on while it still exists.
    func loadCourses(preferDefault: Bool = false) {
        guard !clubPath.isEmpty else { courses = []; clearClubState(); return }
        courses = Store.courses(dbPath: clubPath)
        if preferDefault, let preferred = defaultCourse(), courses.contains(preferred) {
            course = preferred
        } else if !courses.contains(course) {
            course = courses.first ?? ""
        }
        reload()
    }

    /// Everything shown for one club/course, blanked when there's no club or course
    /// to show -- otherwise the previous club's banners, hint and "updated N min ago"
    /// stayed on screen under a never-scraped club.
    func clearClubState() {
        days = []; picks = [:]; verdicts = [:]; alternatives = [:]; locked = [:]; windowHint = nil; banners = []
        pendingJump = nil
        lastScrape = nil; scrapeHealth = .empty; friendNames = []; playerGenders = [:]; picksRequestKey = nil
        picksGeneration += 1  // a fetch still running for the old club must not land
    }

    /// `picksDelay`: seconds to wait before fetching picks -- the DB watcher passes a
    /// few, so a scrape's burst of per-course/date commits (one every ~2 s) ends in
    /// one picks_cli run instead of one per commit (each can make several paid AI
    /// ranking calls). Everything else fetches straight away.
    func reload(offMain: Bool = false, picksDelay: TimeInterval = 0) {
        guard !clubPath.isEmpty, !course.isEmpty else { clearClubState(); return }
        let keepOpen = expanded          // a background refresh must not collapse what
        if offMain {
            // Course switch: the SQLite reads (6 days of slots + weather) ran on the
            // main thread, so the collapse repaint waited on them -- the visible lag
            // when switching with a day open (report 2026-10-03). Read on a worker
            // and apply only if the selection is still the one asked for.
            let path = clubPath, course = course, today = today, window = overviewDays()
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                let loaded = Store.days(dbPath: path, course: course, from: today, days: window)
                let friends = Store.friendNames(dbPath: path)
                let genders = Store.playerGenders(dbPath: path)
                let scrape = Store.lastScrape(dbPath: path)
                let health = Store.scrapeHealth(dbPath: path)
                let bans = Store.banners(dbPath: path)
                DispatchQueue.main.async {
                    guard let self, self.clubPath == path, self.course == course else { return }
                    self.days = loaded
                    self.friendNames = friends
                    self.playerGenders = genders
                    self.lastScrape = scrape
                    self.scrapeHealth = health
                    self.banners = bans
                    self.bannersPath = path
                    self.applyPendingJump()
                }
            }
        } else {
            days = Store.days(dbPath: clubPath, course: course, from: today, days: overviewDays())
            friendNames = Store.friendNames(dbPath: clubPath)
            playerGenders = Store.playerGenders(dbPath: clubPath)
            expanded = keepOpen          // you were reading -- same rule as the TUI's
                                         // own keep_cursor fix (v0.30.0).
            lastScrape = Store.lastScrape(dbPath: clubPath)
            scrapeHealth = Store.scrapeHealth(dbPath: clubPath)
            banners = Store.banners(dbPath: clubPath)
            bannersPath = clubPath
            applyPendingJump()
        }

        // Cleared synchronously the moment club/course actually changes, not left to
        // the async fetch below to overwrite once it eventually lands -- direct
        // report 2026-09-28: switching from an 18-hole course to a 9-hole one kept
        // showing the 18-hole course's own "window opens too late" hint (a real ~4h-
        // round number) attached to the 9-hole day list, for as long as the new
        // course's own picks subprocess took to return. Keyed off `picksRequestKey`
        // (not just "always clear") specifically so this *doesn't* also fire on
        // every routine reload() -- the 2-second DB-mtime watcher and a confirm/
        // cancel both call this for the *same* club/course, and clearing on those
        // too would flash the pick badges/hint to empty and back on every single
        // background refresh, a real regression of its own. The decision itself is
        // `Self.picksRequestChanged`, a pure function, specifically so it can be
        // tested without going through a real (and environment-dependent -- see
        // that function's own docstring) `PicksClient.run()` subprocess call.
        let requestPath = clubPath, requestCourse = course
        if Self.picksRequestChanged(from: picksRequestKey, to: (requestPath, requestCourse)) {
            picks = [:]
            verdicts = [:]
            alternatives = [:]
            locked = [:]
            windowHint = nil
        }

        if picksDelay > 0 {
            picksDebounce?.cancel()
            let item = DispatchWorkItem { [weak self] in self?.fetchPicks() }
            picksDebounce = item
            DispatchQueue.main.asyncAfter(deadline: .now() + picksDelay, execute: item)
        } else {
            fetchPicks()
        }
    }

    /// Bumped per picks request (and by `clearClubState()`); a result is applied only
    /// while it is still the latest, so a slow older run can't overwrite a newer one.
    var picksGeneration = 0
    /// "Now" for wording a locked day's opening ("today 20:00" vs "Wed 21:00"); a seam so
    /// the visual-regression fixtures render the same text on every day they run.
    var now: () -> Date = { Date() }
    /// The picks_cli run currently going, if any -- at most one per club/course.
    private var picksInFlight: (path: String, course: String, generation: Int)?
    /// A same-club/course request arrived while one was running: run once more after.
    private var picksRerunQueued = false
    private var picksDebounce: DispatchWorkItem?

    /// Fire-and-forget, async -- reload() itself stays synchronous/fast (plain SQLite
    /// reads); this rides the cadence reload() already runs on (the DB-mtime watcher,
    /// manual Refresh, confirm/cancel). A stale clubPath/course by the time this
    /// returns (the user switched mid-fetch) is caught below rather than clobbering
    /// the new selection's own picks.
    func fetchPicks() {
        picksDebounce?.cancel(); picksDebounce = nil
        guard !clubPath.isEmpty, !course.isEmpty else { return }
        let requestPath = clubPath, requestCourse = course
        // Same club/course already running: let it finish, then fetch once more for
        // whatever changed since -- never a second overlapping process.
        if let running = picksInFlight, running.path == requestPath, running.course == requestCourse {
            picksRerunQueued = true
            return
        }
        picksGeneration += 1
        let generation = picksGeneration
        picksInFlight = (requestPath, requestCourse, generation)
        picksRerunQueued = false
        let requestSlug = clubs.first { $0.path == clubPath }?.slug
        PicksClient.run(dbPath: requestPath, course: requestCourse, clubSlug: requestSlug, from: today,
                        days: overviewDays()) { [weak self] result in
            guard let self else { return }
            if self.picksInFlight?.generation == generation { self.picksInFlight = nil }
            if generation == self.picksGeneration, self.clubPath == requestPath, self.course == requestCourse {
                self.picksRequestKey = (requestPath, requestCourse)
                self.picks = result.picks
                self.verdicts = result.verdicts
                self.alternatives = result.alternatives
                self.locked = result.locked
                self.windowHint = result.hint
            }
            if self.picksInFlight == nil, self.picksRerunQueued {
                self.picksRerunQueued = false
                self.fetchPicks()
            }
        }
    }

    /// The database `banners` were read from -- a dismiss acknowledges against that
    /// one, never against whatever club happens to be selected now.
    private var bannersPath: String?

    func dismiss(_ banner: Banner) {
        if let bannersPath { Store.acknowledgeBanners(dbPath: bannersPath, ids: [banner.id]) }
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
    /// The legend popover's state lives here so the menu's ⌘/ can toggle it.
    @Published var legendShown = false
    var onRefresh: (() -> Void)?
    var onSearch: (() -> Void)?
    var onAddClub: (() -> Void)?
    var onHeatmap: (() -> Void)?
    var onPlayerDirectory: (() -> Void)?
    /// ⌘/ -- toggles `legendShown` only while the legend button is on screen.
    var onLegend: (() -> Void)?
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
///
/// Internal rather than private (2026-10-05) so `VisualRegressionRunner` can render it
/// with `fixedNow` -- a real clock would make every reference image a moving target.
struct FreshnessRow: View {
    @ObservedObject var model: OverviewModel
    var fixedNow: Date?
    @ObservedObject private var scale = AppScale.shared
    @StateObject private var clock = FreshnessClock()

    var body: some View {
        let now = fixedNow ?? clock.now
        let warning = model.healthWarning(now: now)
        HStack(spacing: 6) {
            // Scrape health (2026-10-05), only while unhealthy. Left of the dot, so the
            // dot, the freshness text and the version keep their right-anchored spots;
            // the footer's Spacer absorbs the width, and at a narrow window this line
            // truncates (layoutPriority -1) rather than pushing anything else. The
            // tooltip carries the whole line plus the raw error.
            if let warning {
                Text(warning.text).font(scaledFont(.caption2))
                    .foregroundStyle(warning.status == .failing ? Color.red : Color.orange)
                    .lineLimit(1).truncationMode(.tail)
                    .layoutPriority(-1)
            }
            if model.isScraping {
                ProgressView().controlSize(.small).scaleEffect(0.7)
                Text(t("overview.checking")).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                    .lineLimit(1)
            } else {
                Circle().fill(model.freshnessColor(now: now))
                    .frame(width: scale.scaled(Metrics.freshnessDot),
                           height: scale.scaled(Metrics.freshnessDot))
                Text(model.freshnessText(now: now)).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .help(warning?.detail ?? "")
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
    @StateObject private var showingPlayerDirectory = Box(false)
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
                                // The day too: banners span every date and the text names
                                // only the time (the TUI prefixes weekday + date the same way).
                                if !bannerCaption(banner).isEmpty {
                                    Text(bannerCaption(banner)).font(scaledFont(.caption2)).foregroundStyle(.secondary)
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
            // Your window opens too late to finish before dark, several days
            // running (2026-09-27, bundle C of the TUI/GUI consistency audit):
            // said once, with the numbers and a way straight to the setting,
            // instead of a moon icon on day after day. Same hint, same numbers
            // as the TUI's own #hint line -- both from
            // recommend.window_too_late_hint().
            if let hint = model.windowHint {
                HStack(spacing: 8) {
                    Image(systemName: "lightbulb.fill").font(scaledFont(.caption)).foregroundStyle(.yellow)
                    Text(windowHintText(hint))
                    .font(scaledFont(.caption))
                    Spacer()
                    Button(t("action.preferences")) { showingPreferences.value = true }
                        .font(scaledFont(.caption))
                }
                .padding(8)
                .background(.yellow.opacity(0.10), in: RoundedRectangle(cornerRadius: 6))
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
                    Picker("", selection: Binding(get: { model.clubPath },
                                                  set: { model.expanded = []; model.clubPath = $0 })) {
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
                    .onChange(of: model.clubPath) { _, _ in
                        // A different club is a different dataset: nothing expanded from the old
                        // one means anything here (the TUI's _reload() does the same).
                        model.expanded = []
                        model.loadCourses(preferDefault: true)
                    }
                }
                Spacer(minLength: 12)
                Text(t("overview.course")).font(scaledFont(.caption2)).foregroundStyle(.secondary)
                // Collapse in the same mutation as the course change: with a day open the
                // first render after the switch still laid out and hover-tracked its ~60
                // rows (each with several tooltips) before onChange could collapse it --
                // a ~10 s freeze inside the open menu (sampled 2026-10-03:
                // NSHostingView.didRequestHoverUpdate was half the main thread).
                Picker("", selection: Binding(get: { model.course },
                                              set: { model.expanded = []; model.course = $0 })) {
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
                .onChange(of: model.course) { _, _ in
                    model.expanded = []  // switching course collapses every day (direct request, 2026-10-03)
                    model.reload(offMain: true)
                }
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
                // Added 2026-09-27, direct request: previously only reachable via
                // Preferences -> Priorities, several taps away from the Overview
                // it's actually useful from -- same "browse/interact with data"
                // grouping as Search/Heatmap beside it, not the app-configuration
                // grouping Preferences/Settings have after the Spacer below.
                Button { showingPlayerDirectory.value = true } label: {
                    Label(t("action.player_directory"), systemImage: "person.2.fill")
                }
                .help(t("tip.player_directory"))
                .disabled(model.clubPath.isEmpty)

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
                // LazyVStack + Section, not the plain VStack this used to be --
                // `pinnedViews: [.sectionHeaders]` is what actually pins each open
                // day's own header while its slots scroll underneath (direct
                // report, 2026-09-19: "can you fixate overview row, when it is
                // uncollapsed and you scroll down?"), the same primitive a List's
                // own sticky section headers use. A collapsed day still renders
                // correctly: its Section simply has no body, so its header hands
                // off to the next day's immediately rather than lingering pinned
                // with nothing under it.
                ScrollViewReader { proxy in
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
                    // A newly expanded day scrolls straight to its ★ pick, or to
                    // where your window opens (2026-09-27, bundle C) -- the TUI's
                    // own expand moves its cursor to the same slot. Centered,
                    // not top-anchored: the day's own pinned header covers the top.
                    .onChange(of: model.expanded) { old, new in
                        guard let date = new.subtracting(old).first,
                              date != model.jumpingToDate,
                              let time = model.focusTime(for: date) else { return }
                        DispatchQueue.main.async {
                            withAnimation { proxy.scrollTo(slotAnchor(date, time), anchor: .center) }
                        }
                    }
                    // A specific slot to jump to right now, regardless of whether
                    // its day is already expanded -- see `OverviewModel.scrollRequest`'s
                    // own docstring for why this needs to be separate from the
                    // expand-driven scroll right above. `expanded.insert` here is a
                    // no-op (and fires no change of its own) when the day was
                    // already open, which is exactly the case this exists to still
                    // handle correctly.
                    .onChange(of: model.scrollRequest) { (_: OverviewModel.ScrollTarget?, new: OverviewModel.ScrollTarget?) in
                        guard let target: OverviewModel.ScrollTarget = new else { return }
                        let date: String = target.date
                        let time: String = target.time
                        // Marks this day so the expand-driven scroll above doesn't also
                        // fire for it and drag the view to the day's ★ pick instead.
                        model.jumpingToDate = date
                        // Collapses every other day first (direct request, 2026-09-29):
                        // with earlier jumps' days left open, the target can sit
                        // below a screenful of unrelated rows and never fit on screen.
                        model.expanded = [date]
                        // The day body is a lazy section that only exists after the expand
                        // renders, and the sheet is still animating away, so a single
                        // scrollTo can silently do nothing.
                        // Keep re-issuing the scroll until the focused row has actually
                        // been realized on screen (SlotRow.onAppear), then a couple more
                        // times to settle -- the highlight is only started once it is
                        // really visible, so a late scroll can't spend its 4 seconds
                        // off-screen (found 2026-09-29: "expands day but no highlight").
                        model.focusedRowAppeared = false
                        withAnimation { model.highlightedSlot = target }
                        func attempt(_ n: Int, settled: Int) {
                            DispatchQueue.main.asyncAfter(deadline: .now() + (n == 0 ? 0.05 : 0.25)) {
                                guard model.highlightedSlot == target else { return }
                                withAnimation { proxy.scrollTo(slotAnchor(date, time), anchor: .center) }
                                let seen = settled + (model.focusedRowAppeared ? 1 : 0)
                                if seen >= 3 || n >= 16 {
                                    if model.jumpingToDate == date { model.jumpingToDate = nil }
                                    DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
                                        if model.highlightedSlot == target {
                                            withAnimation { model.highlightedSlot = nil }
                                        }
                                    }
                                } else {
                                    attempt(n + 1, settled: seen)
                                }
                            }
                        }
                        attempt(0, settled: 0)
                        model.scrollRequest = nil
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
            // One footer row on the same container padding as the toolbar and the cards
            // above, so its two ends sit on the same left/right edges as they do: the
            // legend button anchors the left, status and version share one baseline on
            // the right (2026-10-03: previously a tiny "?" hung off the status line and
            // the version stacked beneath it, leaving the left of the footer empty).
            HStack(alignment: .firstTextBaseline) {
                if !model.visibleDays.isEmpty { LegendButton() }
                Spacer(minLength: 12)
                    // The button going away mid-popover mustn't leave the flag set.
                    .onChange(of: model.visibleDays.isEmpty) { _, empty in
                        if empty { AppCommands.shared.legendShown = false }
                    }
                HStack(spacing: 6) {
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
                    Text("·").font(scaledFont(.caption2)).foregroundStyle(.tertiary)
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
            AppCommands.shared.onPlayerDirectory = {
                guard !model.clubPath.isEmpty else { return }
                showingPlayerDirectory.value = true
            }
            AppCommands.shared.onLegend = {
                // Same guard as the footer's LegendButton: with no days shown there's
                // no popover to open, and a flag set now would pop it open later.
                guard !model.visibleDays.isEmpty else { return }
                AppCommands.shared.legendShown.toggle()
            }
            AppCommands.shared.onPreferences = { showingPreferences.value = true }
            AppCommands.shared.onSettings = { showingSettings.value = true }
        }
        .sheet(isPresented: $showingPreferences.value) { PreferencesSheet(dbPath: model.clubPath) }
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
        .sheet(isPresented: $showingPlayerDirectory.value) { PlayerDirectorySheet(dbPath: model.clubPath, model: model) }
    }
}
