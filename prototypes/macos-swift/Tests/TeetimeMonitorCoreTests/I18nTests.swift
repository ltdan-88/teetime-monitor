@testable import TeetimeMonitorCore

func runI18nTests() {
    Harness.group("I18n") {
        testTableParity()
        testPlaceholdersMatchBetweenLanguages()
        testLookupAndInterpolation()
        testFallbackChain()
        testRenderBookingChange()
    }
}

private func placeholders(_ s: String) -> Set<String> {
    var out = Set<String>()
    var rest = Substring(s)
    while let o = rest.firstIndex(of: "{"), let c = rest[o...].firstIndex(of: "}") {
        out.insert(String(rest[rest.index(after: o)..<c]))
        rest = rest[rest.index(after: c)...]
    }
    return out
}

/// The real risk this table carries: a string added to one language and forgotten
/// in the other degrades silently to English (by design, for a genuinely missing
/// translation) -- which means a *forgotten* one is indistinguishable from a
/// deliberate choice unless something actually checks parity. This is that check.
private func testTableParity() {
    let en = I18n.strings["en"] ?? [:]
    let de = I18n.strings["de"] ?? [:]
    Harness.check("English table is non-trivial", en.count > 100)
    let missingInDE = en.keys.filter { de[$0] == nil }.sorted()
    let extraInDE = de.keys.filter { en[$0] == nil }.sorted()
    Harness.checkEqual("every English key has a German translation", missingInDE, [])
    Harness.checkEqual("no German-only keys with no English counterpart", extraInDE, [])
}

private func testPlaceholdersMatchBetweenLanguages() {
    let en = I18n.strings["en"] ?? [:]
    let de = I18n.strings["de"] ?? [:]
    var mismatched: [String] = []
    for (key, value) in en {
        guard let german = de[key] else { continue }
        if placeholders(value) != placeholders(german) { mismatched.append(key) }
    }
    // A missing {placeholder} in one language means an interpolated value silently
    // vanishes from that language's rendering instead of erroring.
    Harness.checkEqual("no key has different {placeholders} between en and de", mismatched.sorted(), [])
}

private func testLookupAndInterpolation() {
    AppLanguage.shared.code = "de"
    Harness.checkEqual("German lookup", t("action.refresh"), "Aktualisieren")
    Harness.checkEqual("German interpolation", t("overview.free", ["n": "3"]), "3 frei")

    AppLanguage.shared.code = "en"
    Harness.checkEqual("English lookup", t("action.refresh"), "Refresh")
    Harness.checkEqual("English interpolation", t("overview.free", ["n": "3"]), "3 free")
}

private func testFallbackChain() {
    AppLanguage.shared.code = "en"
    Harness.checkEqual("an unknown key falls back to the key itself", t("does.not.exist"), "does.not.exist")
}

/// Direct report, 2026-09-20 ("why is the notification not translated?"): banners
/// used to always show `booking_changes.message`, English rendered once at scrape
/// time. `renderBookingChange()` re-renders from `kind`+`params` in the current
/// language instead -- mirrors `i18n.render_booking_change()` exactly, one case per
/// `kind`, in both languages, matching that function's own real behavior (its own
/// docstring, and this text copied verbatim from `src/i18n.py`'s own `watch.*`
/// strings) rather than reimplemented from a guess.
private func testRenderBookingChange() {
    AppLanguage.shared.code = "en"
    Harness.checkEqual("party_grew, singular (en)",
                        renderBookingChange(kind: "party_grew", paramsJSON: #"{"count":1,"time":"14:20"}"#),
                        "1 more player joined your 14:20 tee time since you booked")
    Harness.checkEqual("party_grew, plural (en)",
                        renderBookingChange(kind: "party_grew", paramsJSON: #"{"count":2,"time":"14:20"}"#),
                        "2 more players joined your 14:20 tee time since you booked")
    Harness.checkEqual("buffer_shrunk (en)",
                        renderBookingChange(kind: "buffer_shrunk", paramsJSON: #"{"time":"14:20","neighbor_time":"14:00"}"#),
                        "The 14:00 slot near your 14:20 tee time is no longer clear")
    Harness.checkEqual("neighbor_crowded (en)",
                        renderBookingChange(kind: "neighbor_crowded", paramsJSON: #"{"time":"14:20","neighbor_time":"14:40"}"#),
                        "The 14:40 flight near your 14:20 tee time picked up more players")
    Harness.checkEqual("weather_worsened, multiple reasons (en)",
                        renderBookingChange(kind: "weather_worsened",
                                             paramsJSON: #"{"time":"14:20","reason_keys":["rain_chance","wind"]}"#),
                        "The forecast for your 14:20 tee time got worse (rain chance, wind)")
    Harness.checkEqual("reservations_sync_failed, a known reason (en)",
                        renderBookingChange(kind: "reservations_sync_failed", paramsJSON: #"{"reason":"login"}"#),
                        "Couldn't check your confirmed reservations — the pc caddie login failed. Check PCC_USER/PCC_PASS.")
    Harness.checkEqual("reservations_sync_failed, no reason falls back to \"other\" (en)",
                        renderBookingChange(kind: "reservations_sync_failed", paramsJSON: "{}"),
                        "Couldn't check your confirmed reservations right now.")
    Harness.check("an unrecognized kind returns nil, same as Python's own None fallback",
                   renderBookingChange(kind: "something_new", paramsJSON: "{}") == nil)

    AppLanguage.shared.code = "de"
    Harness.checkEqual("party_grew, singular (de)",
                        renderBookingChange(kind: "party_grew", paramsJSON: #"{"count":1,"time":"14:20"}"#),
                        "Seit deiner Buchung ist 1 Spieler zu deiner Tee-Zeit um 14:20 Uhr dazugekommen")
    Harness.checkEqual("party_grew, plural (de)",
                        renderBookingChange(kind: "party_grew", paramsJSON: #"{"count":2,"time":"14:20"}"#),
                        "Seit deiner Buchung sind 2 Spieler zu deiner Tee-Zeit um 14:20 Uhr dazugekommen")
    Harness.checkEqual("weather_worsened, multiple reasons (de)",
                        renderBookingChange(kind: "weather_worsened",
                                             paramsJSON: #"{"time":"14:20","reason_keys":["rain_chance","wind"]}"#),
                        "Die Vorhersage für deine Tee-Zeit um 14:20 Uhr hat sich verschlechtert (Regenwahrscheinlichkeit, Wind)")
    AppLanguage.shared.code = "en"
}
