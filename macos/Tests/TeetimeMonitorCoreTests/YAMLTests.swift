@testable import TeetimeMonitorCore

func runYAMLTests() {
    Harness.group("YAML") {
        testScalarTypes()
        testNestedMap()
        testQuotedStringsRoundTrip()
        testTimeLikeStringStaysQuoted()
        testCommentsAndBlankLinesIgnored()
        testDoubleQuotedUnicodeEscapeDecodes()
        testDoubleQuotedBasicEscapesDecode()
    }
}

private func testScalarTypes() {
    let parsed = YAML.parse("""
    name: hello
    count: 3
    ratio: 1.5
    enabled: true
    disabled: false
    nothing: null
    tilde: ~
    """)
    Harness.checkEqual("string", parsed["name"]?.asString, "hello")
    Harness.checkEqual("int", parsed["count"]?.asInt, 3)
    Harness.checkClose("double", parsed["ratio"]?.asDouble ?? -1, 1.5, tolerance: 1e-9)
    Harness.checkEqual("bool true", parsed["enabled"]?.asBool, true)
    Harness.checkEqual("bool false", parsed["disabled"]?.asBool, false)
    Harness.check("null keyword", { if case .null? = parsed["nothing"] { return true }; return false }())
    Harness.check("tilde null", { if case .null? = parsed["tilde"] { return true }; return false }())
}

private func testNestedMap() {
    let parsed = YAML.parse("""
    calendar:
      country_code: DE
      vacation_ranges: []
    """)
    Harness.checkEqual("nested scalar", parsed["calendar"]?["country_code"]?.asString, "DE")
}

private func testQuotedStringsRoundTrip() {
    let value = YAMLValue.map([
        ("plain", .string("hello")),
        ("colon", .string("a: b")),
        ("apostrophe", .string("it's")),
    ])
    let dumped = YAML.dump(value)
    let reparsed = YAML.parse(dumped)
    Harness.checkEqual("plain string round-trips", reparsed["plain"]?.asString, "hello")
    Harness.checkEqual("string containing a colon round-trips", reparsed["colon"]?.asString, "a: b")
    Harness.checkEqual("string containing an apostrophe round-trips", reparsed["apostrophe"]?.asString, "it's")
}

/// `yaml.safe_load` treats a bare `16:00` as ambiguous (sexagesimal), which is why
/// `global_preferences.py`'s own saved values are always single-quoted for anything
/// time-shaped -- `YAML.dump()` has to reproduce that quoting, not just happen to
/// parse it back correctly on the Swift side alone.
private func testTimeLikeStringStaysQuoted() {
    let dumped = YAML.dump(.map([("after", .string("16:00"))]))
    Harness.check("a time-shaped string is quoted in the dumped output",
                   dumped.contains("'16:00'") || dumped.contains("\"16:00\""))
    let reparsed = YAML.parse(dumped)
    Harness.checkEqual("round-trips back to the same string, not an Int/Double", reparsed["after"]?.asString, "16:00")
}

/// Direct report, 2026-09-19 ("umlauts seem to be broken"): a real saved
/// club.yaml (written before club_config.save_club_config() started passing
/// allow_unicode=True) held exactly this -- PyYAML's default backslash-escaped
/// the combining diaeresis as ̈ (note: decomposed, "a" + combining mark,
/// not a single precomposed ä), and this parser used to hand that escape
/// back as six literal characters instead of the actual combining character,
/// which macOS's own text rendering (same NFD handling HFS+ filenames have
/// used for decades) still renders correctly once decoded.
private func testDoubleQuotedUnicodeEscapeDecodes() {
    let parsed = YAML.parse(#"name: "Domäne""#)
    Harness.checkEqual("decomposed \\u escape decodes and combines visually",
                        parsed["name"]?.asString, "Domäne")
}

private func testDoubleQuotedBasicEscapesDecode() {
    let parsed = YAML.parse(#"note: "line one\nline two\ttabbed\\backslash\"quote""#)
    Harness.checkEqual("\\n/\\t/\\\\/\\\" all decode",
                        parsed["note"]?.asString, "line one\nline two\ttabbed\\backslash\"quote")
}

private func testCommentsAndBlankLinesIgnored() {
    let parsed = YAML.parse("""
    # a whole-line comment
    name: hello

    # another comment
    count: 3
    """)
    Harness.checkEqual("value after a comment line", parsed["name"]?.asString, "hello")
    Harness.checkEqual("value after a blank line", parsed["count"]?.asInt, 3)
}
