@testable import TeetimeMonitorCore

func runI18nTests() {
    Harness.group("I18n") {
        testTableParity()
        testPlaceholdersMatchBetweenLanguages()
        testLookupAndInterpolation()
        testFallbackChain()
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
