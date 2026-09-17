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

struct HeatStrip: View {
    let buckets: [Double?]
    var body: some View {
        HStack(spacing: 2) {
            ForEach(Array(buckets.enumerated()), id: \.offset) { _, value in
                RoundedRectangle(cornerRadius: 2)
                    .fill(value.map(fillColor) ?? Color.secondary.opacity(0.18))
                    .frame(width: 13, height: 7)
            }
        }
    }
}

struct SlotRow: View {
    let slot: Slot
    let day: Day
    var isMine: Bool { day.bookedTime == slot.time }
    var isPastSunset: Bool {
        guard let sunset = day.sunset else { return false }
        return slot.time > sunset
    }

    var body: some View {
        HStack(spacing: 10) {
            Text(slot.time)
                .font(.system(.caption, design: .monospaced))
                .fontWeight(isMine ? .bold : .regular)
                .frame(width: 42, alignment: .leading)

            if slot.isBlocked {
                Text(slot.blockReason?.isEmpty == false ? slot.blockReason! : "not bookable")
                    .font(.caption2).foregroundStyle(.secondary).italic()
            } else {
                HStack(spacing: 3) {
                    ForEach(0..<max(slot.capacity, 1), id: \.self) { i in
                        RoundedRectangle(cornerRadius: 2)
                            .fill(i < slot.booked
                                  ? (isMine && i == 0 ? Color.accentColor : Color.secondary)
                                  : Color.secondary.opacity(0.18))
                            .frame(width: 9, height: 9)
                    }
                }
                Text("\(slot.capacity - slot.booked) free")
                    .font(.caption2).foregroundStyle(.secondary)
            }

            Spacer()

            if isMine {
                Label("you", systemImage: "flag.fill")
                    .font(.caption2).foregroundStyle(Color.accentColor)
            }
            if let w = day.weather(at: slot.time), let t = w.temperatureC {
                Image(systemName: icon(for: w.code)).font(.caption2).foregroundStyle(.secondary)
                Text(String(format: "%.0f°", t)).font(.caption2).foregroundStyle(.secondary)
                    .frame(width: 26, alignment: .trailing)
            }
        }
        .padding(.vertical, 2)
        .opacity(isPastSunset ? 0.4 : 1)
    }
}

struct DayCard: View {
    let day: Day
    @ObservedObject var model: OverviewModel
    var isOpen: Bool { model.expanded.contains(day.date) }

    private var noon: WeatherPoint? { day.weather(at: "12:00") }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: isOpen ? "chevron.down" : "chevron.right")
                    .font(.caption2).foregroundStyle(.secondary).frame(width: 10)
                Text(weekday(day.date)).font(.headline)

                if let w = noon {
                    Image(systemName: icon(for: w.code)).foregroundStyle(.secondary)
                    if let t = w.temperatureC {
                        Text(String(format: "%.0f°", t))
                            .font(.system(.subheadline, design: .monospaced))
                    }
                    if let p = w.precipitationProbability, p > 0 {
                        Text("\(Int(p))%").font(.caption).foregroundStyle(.secondary)
                    }
                }

                Spacer()
                HeatStrip(buckets: day.heatStrip)

                if let t = day.bookedTime {
                    Label(t, systemImage: "flag.fill")
                        .font(.caption).padding(.horizontal, 7).padding(.vertical, 3)
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
                    .font(.caption2).foregroundStyle(.secondary).padding(.leading, 20)
            }

            if isOpen {
                Divider()
                VStack(spacing: 0) {
                    ForEach(day.slots.filter { $0.time >= "07:00" && $0.time <= "19:30" }) { slot in
                        SlotRow(slot: slot, day: day)
                    }
                }
                .padding(.leading, 20)
                if let rise = day.sunrise, let set = day.sunset {
                    Text("sunrise \(rise) · sunset \(set)")
                        .font(.caption2).foregroundStyle(.tertiary).padding(.leading, 20)
                }
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.25), in: RoundedRectangle(cornerRadius: 10))
    }
}

/// `@State` is a *macro* in current SwiftUI, and its plugin ships with Xcode rather
/// than the Command Line Tools -- so this prototype uses the older, macro-free
/// `ObservableObject`/`@Published`/`@StateObject` trio instead. Identical behaviour,
/// and it builds with nothing but `swiftc`. See README.md.
final class OverviewModel: ObservableObject {
    @Published var clubs: [(path: String, id: String, name: String, lastScrape: String)] = []
    @Published var clubPath: String = ""
    @Published var courses: [String] = []
    @Published var course: String = ""
    @Published var days: [Day] = []
    @Published var expanded: Set<String> = []

    var clubName: String {
        clubs.first { $0.path == clubPath }?.name ?? "teetime-monitor"
    }

    private var today: String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
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
        days = Store.days(dbPath: clubPath, course: course, from: today)
        expanded = []
    }
}

struct ContentView: View {
    @StateObject var model: OverviewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 1) {
                    Text(model.clubName).font(.title2).bold()
                    Text("reading the scraper's own database — nothing is fetched here")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 5) {
                    Picker("", selection: $model.clubPath) {
                        ForEach(model.clubs, id: \.path) { club in
                            Text(club.lastScrape.isEmpty ? "\(club.name) — never scraped" : club.name)
                                .tag(club.path)
                        }
                    }
                    .labelsHidden().frame(width: 230)
                    .onChange(of: model.clubPath) { _, _ in model.loadCourses() }

                    Picker("", selection: $model.course) {
                        ForEach(model.courses, id: \.self) { Text($0).tag($0) }
                    }
                    .labelsHidden().frame(width: 230)
                    .onChange(of: model.course) { _, _ in model.reload() }
                }
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
        }
        .padding(16)
        .frame(minWidth: 600, minHeight: 540)
        .onAppear { model.load() }
    }
}

@main
struct TeetimeMonitorPrototype: App {
    var body: some Scene {
        WindowGroup("teetime-monitor") {
            ContentView(model: OverviewModel())
        }
        .defaultSize(width: 660, height: 680)
    }
}
