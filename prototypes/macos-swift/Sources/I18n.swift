import SwiftUI

/// Translations for this app's own interface.
///
/// Until now the Language picker only ever wrote `LANG=` for the TUI to read --
/// every string here was an English literal, so switching to Deutsch changed
/// nothing on screen and read as broken. This is the table that makes it real.
///
/// **Shared vocabulary, not parallel wording.** Where `src/i18n.py` already has a
/// German term for the same domain concept, it is copied verbatim rather than
/// re-invented: "Zeit", "Wetter", "Spieler", "gebucht", "Suchen", "Einstellungen",
/// "Design", "Min. freie Plätze (Gruppengröße)", "Abstand zur Gruppe davor",
/// "Regen vermeiden", "Zeiten mit Freunden bevorzugen", "Auslastungs-Heatmap",
/// "Nach Wochentag", "Besondere Tage", "pc caddie Anmeldung", "Benutzername /
/// E-Mail", "Passwort", "Speichern", "Abbrechen". Someone switching between the two
/// front ends should meet one set of words for one set of ideas.
///
/// Same lookup rule as Python's own `t()`: the requested language, then English,
/// then the key itself -- a missing translation degrades to readable English rather
/// than to a blank control.
enum I18n {
    static let supported = ["en", "de"]

    static func label(_ code: String) -> String {
        code == "de" ? "Deutsch" : "English"
    }

    static let strings: [String: [String: String]] = [
        "en": englishStrings,
        "de": germanStrings,
    ]
}

/// The current interface language -- same singleton shape as `AppTheme`/`AppScale`/
/// `AppUnits`, so `SettingsSheet` assigning to it re-renders every visible string
/// immediately, with no relaunch.
final class AppLanguage: ObservableObject {
    static let shared = AppLanguage()

    @Published var code: String

    private init() {
        let saved = UserConfig.value("LANG") ?? "en"
        // Accept a full locale ("de_DE.UTF-8") the way `i18n.resolve_language_name()`
        // does, not just a bare code -- the TUI writes a bare code, but this file is
        // hand-editable and an environment-derived value can carry a region.
        let base = String(saved.prefix(2)).lowercased()
        code = I18n.supported.contains(base) ? base : "en"
    }
}

/// Look up one translated string. A free function so a call site stays short
/// (`t("action.refresh")`), matching `i18n.t()` on the Python side.
///
/// `args` fills `{name}` placeholders, same convention Python's own templates use
/// (`"Crowd heatmap — {course}"`), so a translator can reorder them within a
/// sentence instead of being pinned to positional order.
func t(_ key: String, _ args: [String: String] = [:]) -> String {
    let lang = AppLanguage.shared.code
    var text = I18n.strings[lang]?[key] ?? I18n.strings["en"]?[key] ?? key
    for (name, value) in args {
        text = text.replacingOccurrences(of: "{\(name)}", with: value)
    }
    return text
}

/// A `Locale` for the current language -- used for date formatting, so weekday and
/// month names follow the chosen language too rather than the system's.
func currentLocale() -> Locale {
    Locale(identifier: AppLanguage.shared.code == "de" ? "de_DE" : "en_US")
}

/// Mirrors `i18n.render_booking_change()` exactly: re-renders one
/// `booking_changes` row's `kind`+`params` (a JSON-encoded dict, e.g.
/// `{"count": 2, "time": "14:00"}` -- see `storage.py`'s own schema comment) in
/// the *current* language, rather than showing the row's own `message` column,
/// which is plain English rendered once at scrape time and kept "as a
/// fallback/for any non-TUI consumer" -- which is exactly what this app was
/// before this existed. Returns `nil` for a `kind` this doesn't recognize, the
/// same contract `render_booking_change()` has, so a caller falls back to the
/// row's own stored `message` rather than showing nothing -- matches `t()`'s
/// own "requested language, then English, then the key itself" degrade-
/// gracefully spirit, just one level up.
///
/// Added 2026-09-20, direct report ("why is the notification not translated?")
/// after a live screenshot showed an English banner in an otherwise-German
/// window.
func renderBookingChange(kind: String, paramsJSON: String) -> String? {
    guard let data = paramsJSON.data(using: .utf8),
          let params = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    else { return nil }

    func str(_ key: String) -> String { (params[key] as? String) ?? "" }

    switch kind {
    case "party_grew":
        // JSONSerialization hands back an NSNumber for any JSON number -- .intValue
        // works whether the original literal parsed as an Int or a Double.
        let count = (params["count"] as? NSNumber)?.intValue ?? 1
        let key = count == 1 ? "watch.party_grew.singular" : "watch.party_grew.plural"
        return t(key, ["count": "\(count)", "time": str("time")])
    case "buffer_shrunk":
        return t("watch.buffer_shrunk", ["time": str("time"), "neighbor_time": str("neighbor_time")])
    case "neighbor_crowded":
        return t("watch.neighbor_crowded", ["time": str("time"), "neighbor_time": str("neighbor_time")])
    case "weather_worsened":
        let reasonKeys = (params["reason_keys"] as? [String]) ?? []
        let reasons = reasonKeys.map { t("watch.reason.\($0)") }.joined(separator: ", ")
        return t("watch.weather_worsened", ["time": str("time"), "reasons": reasons])
    case "reservations_sync_failed":
        let reason = str("reason")
        return reason.isEmpty ? t("watch.reservations_sync_failed.other") : t("watch.reservations_sync_failed.\(reason)")
    default:
        return nil
    }
}

// MARK: - English

private let englishStrings: [String: String] = [
    // Toolbar and menu
    "action.refresh": "Refresh",
    "action.search": "Search",
    "action.heatmap": "Heatmap",
    "action.add_club": "Add Club",
    "action.collapse_all": "Collapse All",
    "action.preferences": "Preferences",
    "action.settings": "Settings",
    "menu.actions": "Actions",
    "menu.refresh": "Refresh",
    "menu.search": "Search…",
    "menu.add_club": "Add a Club…",
    "menu.heatmap": "Crowd Heatmap…",
    "menu.collapse_all": "Collapse All",
    "menu.preferences": "Preferences…",
    "menu.settings": "Settings…",
    "tip.refresh": "Run the scraper now (⌘R)",
    "tip.search": "Ad hoc criteria for this one search (⌘F)",
    "tip.heatmap": "Crowd history by weekday and hour",
    "tip.add_club": "Search the platform directory and save a club",
    "tip.collapse_all": "Collapse every day (⌥⌘←)",
    "tip.preferences": "When you can play, weather limits (⌘,)",
    "tip.settings": "Display, login, scraping, AI",

    // Overview
    "overview.club": "Club",
    "overview.course": "Course",
    "overview.checking": "Checking pc caddie…",
    "overview.never_scraped": "never scraped",
    "overview.updated_never": "never scraped",
    "overview.updated_just_now": "updated just now",
    "overview.updated_minutes": "updated {n} min ago",
    "overview.updated_relative": "updated {when}",
    "overview.free": "{n} free",
    "overview.you": "you",
    "overview.not_bookable": "not bookable",
    "overview.sunrise_at": "sunrise {time}",
    "overview.sunset_at": "sunset {time}",
    "overview.empty_title": "Nothing scraped for this course yet",
    "overview.empty_no_clubs": "No club databases found in ~/.local/share/teetime-monitor.",
    "overview.empty_pick_another": "Pick another club or course above, or run teetime-monitor-scrape.",

    // Booking-change banners -- mirrors i18n.py's own watch.* keys verbatim.
    // Added 2026-09-20, direct report ("why is the notification not
    // translated?"): banners previously always showed booking_changes.message,
    // the plain-English fallback storage.py's own schema comment says exists
    // "for any non-TUI consumer" -- which is exactly what this app was, despite
    // the rest of its own UI already being in German. renderBookingChange()
    // now re-renders from the same kind+params the TUI's own
    // i18n.render_booking_change() uses, falling back to that English message
    // only for a kind this doesn't recognize (same fallback contract as the
    // Python side).
    "watch.party_grew.singular": "{count} more player joined your {time} tee time since you booked",
    "watch.party_grew.plural": "{count} more players joined your {time} tee time since you booked",
    "watch.buffer_shrunk": "The {neighbor_time} slot near your {time} tee time is no longer clear",
    "watch.neighbor_crowded": "The {neighbor_time} flight near your {time} tee time picked up more players",
    "watch.weather_worsened": "The forecast for your {time} tee time got worse ({reasons})",
    "watch.reason.rain_chance": "rain chance",
    "watch.reason.rain_amount": "rain amount",
    "watch.reason.wind": "wind",
    "watch.reservations_sync_failed.login": "Couldn't check your confirmed reservations — the pc caddie login failed. Check PCC_USER/PCC_PASS.",
    "watch.reservations_sync_failed.parsing": "Couldn't check your confirmed reservations — pc caddie's page changed in a way this app doesn't recognize yet.",
    "watch.reservations_sync_failed.other": "Couldn't check your confirmed reservations right now.",

    // Cell tooltips
    "tip.condition_day": "Condition (worst, 08:00–20:00)",
    "tip.condition_at": "Condition at {time}",
    "tip.temp_day": "High / low temperature ({unit}), 08:00–20:00",
    "tip.temp": "Temperature ({unit})",
    "tip.rain_day": "Average rain chance, 08:00–20:00",
    "tip.rain": "Rain chance (and amount, once measurable)",
    "tip.rain_flagged": "Rain chance — ≥50%, flagged (and amount, once measurable)",
    "tip.wind_day": "Peak wind, {unit}, 08:00–20:00",
    "tip.wind": "Wind, {unit}",
    "tip.wind_flagged": "Wind, {unit} — ≥30 km/h, flagged",
    "tip.sun": "Sunrise / sunset",
    // Added 2026-09-19, direct report ("search results and overview still
    // need explanation what percentage and number really mean") -- neither
    // had any explanation at all before, unlike every weather cell beside them.
    "tip.open_spots": "Open spots out of this slot's total capacity",
    "tip.seat_pips": "{booked} of {capacity} spots booked -- filled = booked, empty = open",

    // Legend
    "legend.hilo": "hi/lo {unit}, 08:00–20:00",
    "legend.rain": "rain %, 08:00–20:00 (🌧 ≥50%)",
    "legend.wind": "wind {unit}, 08:00–20:00 (💨 ≥30)",
    "legend.sunrise": "sunrise",
    "legend.sunset": "sunset",
    "legend.booking": "your booking",

    // Booking
    "booking.mark_title": "Mark {time} as your booking?",
    "booking.cancel_title": "Cancel your {time} booking?",
    "booking.confirm": "Confirm",
    "booking.cancel": "Cancel booking",
    "booking.not_now": "Not now",

    // Buttons
    "button.save": "Save",
    "button.cancel": "Cancel",
    "button.close": "Close",

    // Preferences
    "prefs.title": "Preferences",
    "prefs.live_note": "Applies immediately — a running terminal app picks this up on its next refresh, no restart needed.",
    "prefs.section.availability": "Availability",
    "prefs.section.weather": "Weather",
    "prefs.section.pace": "Pace & daylight",
    "prefs.section.priorities": "Priorities",
    // Plain labels, matching settings_screen.py's own Label+Select pairing exactly
    // (see its FIELDS list's label_key strings) now that these render as
    // IntChoicePicker dropdowns rather than a Stepper's single "Label: value"
    // string. Direct request, 2026-09-19: "can you please change the time entries
    // into dropdowns? other entries ... also would probably be quicker to
    // interact with if they were dropdowns instead."
    "prefs.min_open_spots_label": "Min open spots (party size)",
    "prefs.weekday": "Weekday",
    "prefs.weekend": "Weekend",
    "prefs.after": "after",
    "prefs.before": "before",
    "prefs.buffer_before_label": "Buffer to the group ahead (minutes)",
    "prefs.buffer_after_label": "Buffer to the group behind (minutes)",
    "prefs.avoid_rain": "Avoid rain",
    "prefs.avoid_wind": "Avoid wind",
    "prefs.above_percent": "…above {n}%",
    "prefs.above_mm": "…above {n} mm",
    "prefs.above_kph": "…above {n} km/h",
    "prefs.avoid_below": "Avoid below",
    "prefs.avoid_above": "Avoid above",
    "prefs.daylight_buffer_label": "Daylight safety buffer (minutes)",
    "prefs.nine_holes_label": "Round duration — 9 holes (minutes)",
    "prefs.eighteen_holes_label": "Round duration — 18 holes (minutes)",
    "prefs.prioritize_friends": "Prioritize friends' slots",
    "prefs.saved": "Saved",
    "prefs.save_failed": "Couldn't save: {error}",

    // Settings
    "settings.title": "Settings",
    "settings.section.login": "pc caddie login",
    "settings.username": "Username",
    "settings.password": "Password",
    "settings.password_unchanged": "Password (unchanged)",
    "settings.save_login": "Save login",
    "settings.login_footer_no_club": "Saved either way; pick a club above to also verify it against pc caddie on save.",
    "settings.login_footer_club": "Verified live against pc caddie for the selected club when you save.",
    // Added 2026-09-19, direct request ("integrate add/remove club into
    // settings"): club management used to only live behind the toolbar's own
    // "Add Club" button, with no way at all to remove one -- see this section's
    // own row/footer text below.
    "settings.section.clubs": "Clubs",
    "settings.remove_club": "Remove this club (its scrape history is kept)",
    "settings.clubs_footer": "Removing a club deletes its saved settings, not its scrape history -- adding it back later picks up right where it left off.",
    "settings.section.display": "Display",
    "settings.units": "Units",
    "settings.metric": "Metric",
    "settings.imperial": "Imperial",
    "settings.scale": "Scale",
    "settings.scale.small": "Small",
    "settings.scale.medium": "Medium",
    "settings.scale.large": "Large",
    "settings.language": "Language",
    "settings.theme": "Theme",
    "settings.display_footer": "Units, scale and language apply immediately, no restart.",
    "settings.section.terminal": "Terminal app",
    "settings.terminal_footer": "Theme applies here immediately. Theme and language reach the terminal app only on its next restart: it caches them at launch and won't notice a change while running, even if you reopen its own Settings screen.",
    "settings.applied": "Applied. Theme and language reach the terminal app on its next restart.",
    // Added 2026-09-19, direct request ("implement scrape-interval and ai
    // settings in GUI") -- wording mirrors settings_screen.py's own FIELDS
    // labels exactly (settings.field.scrape_interval_normal/booked,
    // settings.field.ai_assist_enabled/avoid_predicted_crowd,
    // settings.group.scraping/ai).
    "settings.group.scraping": "Scraping",
    "settings.field.scrape_interval_normal": "Scrape interval — normal (minutes)",
    "settings.field.scrape_interval_booked": "Scrape interval — once booked (minutes)",
    "settings.group.ai": "AI ranking",
    "settings.field.ai_assist_enabled": "AI-ranked recommendations",
    "settings.field.avoid_predicted_crowd": "Avoid predicted crowds",

    // Search
    "search.title": "Search",
    "search.prefill_note": "Pre-filled from your saved Preferences — edit for this one search.",
    "search.section.criteria": "Criteria",
    "search.button": "Search",
    "search.none_yet_title": "No search run yet",
    "search.none_yet_desc": "Adjust the criteria above and press Search.",
    "search.no_matches_title": "No matches",
    "search.no_matches_desc": "Nothing in the next {n} days matches these criteria.",
    "search.no_matches_status": "No matches.",
    "search.open_spots": "{n} open",
    "search.booked": "Booked {day} at {time}.",

    // Add a club
    "addclub.title": "Add a Club",
    "addclub.refresh": "Refresh directory",
    "addclub.search_placeholder": "Search by name, or paste a club id / booking link",
    "addclub.source_live": "Live directory, {n} clubs",
    "addclub.source_live_fetched": "Live directory, {n} clubs — fetched {when}",
    "addclub.source_seed": "Offline snapshot, {n} clubs — refresh for the live list",
    "addclub.source_none": "No directory yet — refresh, or type a club id / booking link",
    "addclub.empty_title": "Search for a club",
    "addclub.empty_desc": "Type a name, a club id, or paste a booking link.",
    "addclub.no_matches_title": "No matches",
    "addclub.no_matches_desc": "Nothing in the directory matches “{query}”.",
    "addclub.open_directly": "Open club {id} directly",
    "addclub.add": "Add",
    "addclub.added": "Added {name}.",
    "addclub.refreshed": "Refreshed — {n} clubs.",

    // Heatmap
    "heatmap.title": "Crowd heatmap — {course}",
    "heatmap.loading": "Crunching scrape history…",
    "heatmap.by_weekday": "By weekday",
    "heatmap.special_days": "Special days",
    "heatmap.no_data_yet": "No data yet",
    "heatmap.tournament": "Tournament",
    "heatmap.public_holiday": "Public holiday",
    "heatmap.vacation": "Vacation",
    "heatmap.cell_tip": "{pct}% average occupancy, {n} samples",
    "heatmap.legend.open": "under half booked",
    "heatmap.legend.mid": "half to full",
    "heatmap.legend.full": "fully booked",
    "heatmap.legend.thin": "thin sample (<3)",
    "heatmap.legend.no_data": "no data",
    // Updated 2026-09-19, direct follow-up ("why does heatmap still say no
    // country is set for club") right after new clubs started detecting this
    // automatically: geocode.find_club_country_code() only runs when a club is
    // first *added* (see that function's own docstring on why there's no
    // backfill pass), so an already-saved club from before that fix genuinely
    // still needs one of the two paths this message now spells out -- it
    // wasn't a bug, but the old wording only mentioned the manual one, which
    // read as the fix having silently done nothing.
    "heatmap.no_country": "No country set for this club — public holidays not shown. New clubs detect this automatically now; for one added before that, remove and re-add it under Settings → Clubs, or set calendar.country_code in its YAML by hand.",
    "weekday.short.sunday": "Sun",
    "weekday.short.monday": "Mon",
    "weekday.short.tuesday": "Tue",
    "weekday.short.wednesday": "Wed",
    "weekday.short.thursday": "Thu",
    "weekday.short.friday": "Fri",
    "weekday.short.saturday": "Sat",

    // Errors
    "error.generic": "Something went wrong.",
    "error.scraper_missing": "teetime-monitor-scrape not found — install it with Homebrew.",
    "error.login_missing": "teetime-monitor-login not found — install it with Homebrew.",
    "error.search_missing": "teetime-monitor-search not found — install it with Homebrew.",
    "error.directory_missing": "teetime-monitor-directory-refresh not found — install it with Homebrew.",
    "error.addclub_missing": "teetime-monitor-add-club not found — install it with Homebrew.",
    "error.needs_login": "No pc caddie login configured yet — add one in Settings first.",
    "error.needs_a_club": "Type a club id above, or save a club first, to authenticate with.",
    "error.refresh_failed": "Couldn't refresh: {error}",
    "error.add_failed": "Couldn't save this club.",

    // Login results
    "login.username_required": "Username is required.",
    "login.password_required": "Password is required.",
    "login.save_failed": "Couldn't save — check the fields and try again.",
    "login.verified": "Saved and verified — pc caddie accepted these credentials.",
    "login.rejected": "Saved, but pc caddie rejected these credentials.",
    "login.unverified": "Saved — couldn't verify right now (network issue).",
    "login.saved": "Saved.",
]

// MARK: - Deutsch

private let germanStrings: [String: String] = [
    // Toolbar and menu
    "action.refresh": "Aktualisieren",
    "action.search": "Suchen",
    "action.heatmap": "Heatmap",
    "action.add_club": "Club hinzufügen",
    "action.collapse_all": "Alle einklappen",
    "action.preferences": "Präferenzen",
    "action.settings": "Einstellungen",
    "menu.actions": "Aktionen",
    "menu.refresh": "Aktualisieren",
    "menu.search": "Suchen…",
    "menu.add_club": "Club hinzufügen…",
    "menu.heatmap": "Auslastungs-Heatmap…",
    "menu.collapse_all": "Alle einklappen",
    "menu.preferences": "Präferenzen…",
    "menu.settings": "Einstellungen…",
    "tip.refresh": "Scraper jetzt ausführen (⌘R)",
    "tip.search": "Kriterien nur für diese eine Suche (⌘F)",
    "tip.heatmap": "Auslastungsverlauf nach Wochentag und Stunde",
    "tip.add_club": "Im Club-Verzeichnis suchen und Club speichern",
    "tip.collapse_all": "Jeden Tag einklappen (⌥⌘←)",
    "tip.preferences": "Wann du spielen kannst, Wettergrenzen (⌘,)",
    "tip.settings": "Anzeige, Anmeldung, Scraping, KI",

    // Overview
    "overview.club": "Club",
    "overview.course": "Platz",
    "overview.checking": "pc caddie wird abgefragt…",
    "overview.never_scraped": "noch nie abgerufen",
    "overview.updated_never": "noch nie abgerufen",
    "overview.updated_just_now": "gerade aktualisiert",
    "overview.updated_minutes": "vor {n} Min. aktualisiert",
    "overview.updated_relative": "aktualisiert {when}",
    "overview.free": "{n} frei",
    "overview.you": "du",
    "overview.not_bookable": "nicht buchbar",
    "overview.sunrise_at": "Sonnenaufgang {time}",
    "overview.sunset_at": "Sonnenuntergang {time}",
    "overview.empty_title": "Für diesen Platz wurde noch nichts abgerufen",
    "overview.empty_no_clubs": "Keine Club-Datenbanken in ~/.local/share/teetime-monitor gefunden.",
    "overview.empty_pick_another": "Wähle oben einen anderen Club oder Platz, oder führe teetime-monitor-scrape aus.",

    "watch.party_grew.singular": "Seit deiner Buchung ist {count} Spieler zu deiner Tee-Zeit um {time} Uhr dazugekommen",
    "watch.party_grew.plural": "Seit deiner Buchung sind {count} Spieler zu deiner Tee-Zeit um {time} Uhr dazugekommen",
    "watch.buffer_shrunk": "Die Zeit {neighbor_time} direkt neben deiner Tee-Zeit um {time} Uhr ist inzwischen belegt",
    "watch.neighbor_crowded": "Im Flight um {neighbor_time} neben deiner Tee-Zeit um {time} Uhr sind weitere Spieler dazugekommen",
    "watch.weather_worsened": "Die Vorhersage für deine Tee-Zeit um {time} Uhr hat sich verschlechtert ({reasons})",
    "watch.reason.rain_chance": "Regenwahrscheinlichkeit",
    "watch.reason.rain_amount": "Regenmenge",
    "watch.reason.wind": "Wind",
    "watch.reservations_sync_failed.login": "Deine Buchungen konnten nicht geprüft werden — der pc-caddie-Login ist fehlgeschlagen. PCC_USER/PCC_PASS prüfen.",
    "watch.reservations_sync_failed.parsing": "Deine Buchungen konnten nicht geprüft werden — pc caddie hat seine Seite geändert, diese App kann sie so noch nicht lesen.",
    "watch.reservations_sync_failed.other": "Deine Buchungen konnten gerade nicht geprüft werden.",

    // Cell tooltips
    "tip.condition_day": "Wetter (schlechtestes, 08:00–20:00)",
    "tip.condition_at": "Wetter um {time}",
    "tip.temp_day": "Höchst-/Tiefsttemperatur ({unit}), 08:00–20:00",
    "tip.temp": "Temperatur ({unit})",
    "tip.rain_day": "Durchschnittliche Regenwahrscheinlichkeit, 08:00–20:00",
    "tip.rain": "Regenwahrscheinlichkeit (und Menge, sobald messbar)",
    "tip.rain_flagged": "Regenwahrscheinlichkeit — ≥50 %, markiert (und Menge, sobald messbar)",
    "tip.wind_day": "Stärkster Wind, {unit}, 08:00–20:00",
    "tip.wind": "Wind, {unit}",
    "tip.wind_flagged": "Wind, {unit} — ≥30 km/h, markiert",
    "tip.sun": "Sonnenaufgang / Sonnenuntergang",
    "tip.open_spots": "Freie Plätze von der Gesamtkapazität dieser Zeit",
    "tip.seat_pips": "{booked} von {capacity} Plätzen gebucht -- ausgefüllt = gebucht, leer = frei",

    // Legend
    "legend.hilo": "Höchst/Tief {unit}, 08:00–20:00",
    "legend.rain": "Regen %, 08:00–20:00 (🌧 ≥50 %)",
    "legend.wind": "Wind {unit}, 08:00–20:00 (💨 ≥30)",
    "legend.sunrise": "Sonnenaufgang",
    "legend.sunset": "Sonnenuntergang",
    "legend.booking": "deine Buchung",

    // Booking
    "booking.mark_title": "{time} als deine Buchung markieren?",
    "booking.cancel_title": "Deine Buchung um {time} stornieren?",
    "booking.confirm": "Bestätigen",
    "booking.cancel": "Buchung stornieren",
    "booking.not_now": "Jetzt nicht",

    // Buttons
    "button.save": "Speichern",
    "button.cancel": "Abbrechen",
    "button.close": "Schließen",

    // Preferences
    "prefs.title": "Präferenzen",
    "prefs.live_note": "Wird sofort übernommen — eine laufende Terminal-App liest es beim nächsten Aktualisieren, kein Neustart nötig.",
    "prefs.section.availability": "Verfügbarkeit",
    "prefs.section.weather": "Wetter",
    "prefs.section.pace": "Tempo & Tageslicht",
    "prefs.section.priorities": "Prioritäten",
    "prefs.min_open_spots_label": "Min. freie Plätze (Gruppengröße)",
    "prefs.weekday": "Unter der Woche",
    "prefs.weekend": "Am Wochenende",
    "prefs.after": "ab",
    "prefs.before": "bis",
    "prefs.buffer_before_label": "Abstand zur Gruppe davor (Minuten)",
    "prefs.buffer_after_label": "Abstand zur Gruppe danach (Minuten)",
    "prefs.avoid_rain": "Regen vermeiden",
    "prefs.avoid_wind": "Wind vermeiden",
    "prefs.above_percent": "…über {n} %",
    "prefs.above_mm": "…über {n} mm",
    "prefs.above_kph": "…über {n} km/h",
    "prefs.avoid_below": "Vermeiden unter",
    "prefs.avoid_above": "Vermeiden über",
    "prefs.daylight_buffer_label": "Sicherheitspuffer Tageslicht (Minuten)",
    "prefs.nine_holes_label": "Rundendauer — 9 Loch (Minuten)",
    "prefs.eighteen_holes_label": "Rundendauer — 18 Loch (Minuten)",
    "prefs.prioritize_friends": "Zeiten mit Freunden bevorzugen",
    "prefs.saved": "Gespeichert",
    "prefs.save_failed": "Speichern fehlgeschlagen: {error}",

    // Settings
    "settings.title": "Einstellungen",
    "settings.section.login": "pc caddie Anmeldung",
    "settings.username": "Benutzername / E-Mail",
    "settings.password": "Passwort",
    "settings.password_unchanged": "Passwort (unverändert)",
    "settings.save_login": "Anmeldung speichern",
    "settings.login_footer_no_club": "Wird so oder so gespeichert; wähle oben einen Club, um sie beim Speichern auch bei pc caddie zu prüfen.",
    "settings.login_footer_club": "Wird beim Speichern live bei pc caddie für den gewählten Club geprüft.",
    "settings.section.clubs": "Clubs",
    "settings.remove_club": "Diesen Club entfernen (Scraping-Verlauf bleibt erhalten)",
    "settings.clubs_footer": "Beim Entfernen eines Clubs werden nur seine gespeicherten Einstellungen gelöscht, nicht sein Scraping-Verlauf — beim erneuten Hinzufügen geht es genau dort weiter.",
    "settings.section.display": "Anzeige",
    "settings.units": "Einheiten",
    "settings.metric": "Metrisch",
    "settings.imperial": "Imperial",
    "settings.scale": "Größe",
    "settings.scale.small": "Klein",
    "settings.scale.medium": "Mittel",
    "settings.scale.large": "Groß",
    "settings.language": "Sprache",
    "settings.theme": "Design",
    "settings.display_footer": "Einheiten, Größe und Sprache werden sofort übernommen, kein Neustart nötig.",
    "settings.section.terminal": "Terminal-App",
    "settings.terminal_footer": "Das Design wird hier sofort übernommen. Design und Sprache erreichen die Terminal-App erst bei deren nächstem Neustart: sie liest beide einmal beim Start und bemerkt eine Änderung im laufenden Betrieb nicht, auch nicht beim erneuten Öffnen ihrer eigenen Einstellungen.",
    "settings.applied": "Übernommen. Design und Sprache erreichen die Terminal-App beim nächsten Neustart.",
    "settings.group.scraping": "Abruf",
    "settings.field.scrape_interval_normal": "Abrufintervall — normal (Minuten)",
    "settings.field.scrape_interval_booked": "Abrufintervall — nach Buchung (Minuten)",
    "settings.group.ai": "KI-Bewertung",
    "settings.field.ai_assist_enabled": "KI-bewertete Empfehlungen",
    "settings.field.avoid_predicted_crowd": "Vorhergesagten Andrang vermeiden",

    // Search
    "search.title": "Suchen",
    "search.prefill_note": "Aus deinen gespeicherten Präferenzen vorbelegt — nur für diese eine Suche anpassen.",
    "search.section.criteria": "Kriterien",
    "search.button": "Suchen",
    "search.none_yet_title": "Noch keine Suche ausgeführt",
    "search.none_yet_desc": "Passe oben die Kriterien an und klicke auf Suchen.",
    "search.no_matches_title": "Keine Treffer",
    "search.no_matches_desc": "In den nächsten {n} Tagen passt nichts zu diesen Kriterien.",
    "search.no_matches_status": "Keine Treffer für diese Kriterien.",
    "search.open_spots": "{n} frei",
    "search.booked": "Gebucht: {day} um {time}.",

    // Add a club
    "addclub.title": "Club hinzufügen",
    "addclub.refresh": "Verzeichnis aktualisieren",
    "addclub.search_placeholder": "Nach Name suchen, oder Club-ID / Buchungslink einfügen",
    "addclub.source_live": "Live-Verzeichnis, {n} Clubs",
    "addclub.source_live_fetched": "Live-Verzeichnis, {n} Clubs — abgerufen {when}",
    "addclub.source_seed": "Offline-Kopie, {n} Clubs — für die aktuelle Liste aktualisieren",
    "addclub.source_none": "Noch kein Verzeichnis — aktualisiere, oder gib eine Club-ID / einen Buchungslink ein",
    "addclub.empty_title": "Nach einem Club suchen",
    "addclub.empty_desc": "Gib einen Namen oder eine Club-ID ein, oder füge einen Buchungslink ein.",
    "addclub.no_matches_title": "Keine Treffer",
    "addclub.no_matches_desc": "Im Verzeichnis passt nichts zu „{query}“.",
    "addclub.open_directly": "Club {id} direkt öffnen",
    "addclub.add": "Hinzufügen",
    "addclub.added": "{name} hinzugefügt.",
    "addclub.refreshed": "Aktualisiert — {n} Clubs.",

    // Heatmap
    "heatmap.title": "Auslastungs-Heatmap — {course}",
    "heatmap.loading": "Verlauf wird ausgewertet…",
    "heatmap.by_weekday": "Nach Wochentag",
    "heatmap.special_days": "Besondere Tage (separat verglichen)",
    "heatmap.no_data_yet": "Noch keine Daten",
    "heatmap.tournament": "Turnier",
    "heatmap.public_holiday": "Feiertag",
    "heatmap.vacation": "Ferien",
    "heatmap.cell_tip": "{pct} % durchschnittliche Belegung, {n} Messwerte",
    "heatmap.legend.open": "weniger als halb belegt",
    "heatmap.legend.mid": "halb bis voll",
    "heatmap.legend.full": "ausgebucht",
    "heatmap.legend.thin": "wenige Daten (<3)",
    "heatmap.legend.no_data": "keine Daten",
    "heatmap.no_country": "Für diesen Club ist kein Land gesetzt — Feiertage werden nicht berücksichtigt. Neue Clubs erkennen das jetzt automatisch; entferne diesen Club unter Einstellungen → Clubs und füge ihn erneut hinzu, oder setze calendar.country_code manuell in seiner YAML-Datei.",
    "weekday.short.sunday": "So",
    "weekday.short.monday": "Mo",
    "weekday.short.tuesday": "Di",
    "weekday.short.wednesday": "Mi",
    "weekday.short.thursday": "Do",
    "weekday.short.friday": "Fr",
    "weekday.short.saturday": "Sa",

    // Errors
    "error.generic": "Etwas ist schiefgelaufen.",
    "error.scraper_missing": "teetime-monitor-scrape nicht gefunden — mit Homebrew installieren.",
    "error.login_missing": "teetime-monitor-login nicht gefunden — mit Homebrew installieren.",
    "error.search_missing": "teetime-monitor-search nicht gefunden — mit Homebrew installieren.",
    "error.directory_missing": "teetime-monitor-directory-refresh nicht gefunden — mit Homebrew installieren.",
    "error.addclub_missing": "teetime-monitor-add-club nicht gefunden — mit Homebrew installieren.",
    "error.needs_login": "Noch keine pc caddie Anmeldung eingerichtet — lege sie zuerst in den Einstellungen an.",
    "error.needs_a_club": "Gib oben eine Club-ID ein, oder speichere zuerst einen Club, um dich anzumelden.",
    "error.refresh_failed": "Aktualisieren fehlgeschlagen: {error}",
    "error.add_failed": "Dieser Club konnte nicht gespeichert werden.",

    // Login results
    "login.username_required": "Benutzername ist erforderlich.",
    "login.password_required": "Passwort ist erforderlich.",
    "login.save_failed": "Speichern fehlgeschlagen — prüfe die Felder und versuche es erneut.",
    "login.verified": "Gespeichert und geprüft — pc caddie hat diese Zugangsdaten akzeptiert.",
    "login.rejected": "Gespeichert, aber pc caddie hat diese Zugangsdaten abgelehnt.",
    "login.unverified": "Gespeichert — konnte gerade nicht geprüft werden (Netzwerkproblem).",
    "login.saved": "Gespeichert.",
]
