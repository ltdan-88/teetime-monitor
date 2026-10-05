import Foundation

/// A YAML subset sufficient for `preferences.yaml`'s own shape — nested maps of
/// scalars, no lists, no anchors, no multi-line strings. Not a general YAML parser.
///
/// Written by hand rather than adding a dependency, matching this prototype's own
/// "Command Line Tools only, no SwiftUI Previews needed" build story (see README.md).
/// The schema is fixed and known — it's exactly `settings_screen.FIELDS`'s own shape
/// on the Python side — so a scoped codec is the right amount of machinery, not a
/// shortcut that will need generalizing later.
indirect enum YAMLValue {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case null
    case map([(String, YAMLValue)])  // ordered -- readable output, not required for correctness

    var asMap: [(String, YAMLValue)]? { if case let .map(m) = self { m } else { nil } }
    var asString: String? { if case let .string(s) = self { s } else { nil } }
    var asInt: Int? {
        switch self {
        case .int(let i): return i
        case .double(let d): return Int(d)
        default: return nil
        }
    }
    var asDouble: Double? {
        switch self {
        case .double(let d): return d
        case .int(let i): return Double(i)
        default: return nil
        }
    }
    var asBool: Bool? { if case let .bool(b) = self { b } else { nil } }

    subscript(_ key: String) -> YAMLValue? {
        asMap?.first { $0.0 == key }?.1
    }
}

enum YAML {
    /// Parses an indentation-based tree of `key:`/`key: value` lines. One quirk
    /// matched deliberately: `yaml.safe_load` treats a bare `16:00` as ambiguous (it
    /// could be a base-60 sexagesimal number), which is exactly why
    /// `global_preferences.py`'s own values are always single-quoted for anything
    /// time-shaped — the parser below only needs to strip that quoting, not guess.
    static func parse(_ text: String) -> YAMLValue {
        let rawLines = text.split(separator: "\n", omittingEmptySubsequences: false)
        var lines: [(indent: Int, key: String, inline: String?)] = []
        for raw in rawLines {
            guard let hashIndex = raw.firstIndex(where: { $0 != " " }) else { continue }
            if raw[hashIndex] == "#" { continue }  // a whole-line comment
            let indent = raw.distance(from: raw.startIndex, to: hashIndex)
            let content = raw[hashIndex...]
            guard let colon = content.firstIndex(of: ":") else { continue }
            let key = String(content[content.startIndex..<colon]).trimmingCharacters(in: .whitespaces)
            let rest = content[content.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            lines.append((indent, key, rest.isEmpty ? nil : rest))
        }
        var index = 0
        return .map(parseBlock(&index, in: lines, minIndent: 0))
    }

    private static func parseBlock(
        _ index: inout Int, in lines: [(indent: Int, key: String, inline: String?)], minIndent: Int
    ) -> [(String, YAMLValue)] {
        var result: [(String, YAMLValue)] = []
        guard index < lines.count else { return result }
        let blockIndent = lines[index].indent
        guard blockIndent >= minIndent else { return result }
        while index < lines.count, lines[index].indent == blockIndent {
            let line = lines[index]
            index += 1
            if let inline = line.inline {
                result.append((line.key, parseScalar(inline)))
            } else {
                let nested = parseBlock(&index, in: lines, minIndent: blockIndent + 1)
                result.append((line.key, .map(nested)))
            }
        }
        return result
    }

    private static func parseScalar(_ raw: String) -> YAMLValue {
        if raw == "null" || raw == "~" { return .null }
        if raw == "true" { return .bool(true) }
        if raw == "false" { return .bool(false) }
        if let quoted = unquoted(raw) { return .string(quoted) }
        if let i = Int(raw) { return .int(i) }
        if let d = Double(raw) { return .double(d) }
        return .string(raw)
    }

    /// One `key: value` line's value as the string `yaml.safe_load` would read --
    /// quotes removed and escapes decoded, a plain value just trimmed. For the
    /// line-scanned club-file keys (`name:`, `club_id:`, `default_course:`), which
    /// used to trim quote characters and keep escapes like `\xFC` as literal text.
    static func scalarText(_ raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespaces)
        return unquoted(trimmed) ?? trimmed
    }

    /// The contents of a single- or double-quoted scalar, or nil when `raw` isn't one.
    private static func unquoted(_ raw: String) -> String? {
        guard raw.count >= 2, let first = raw.first, first == "'" || first == "\"", raw.last == first else { return nil }
        let inner = String(raw.dropFirst().dropLast())
        return first == "'" ? inner.replacingOccurrences(of: "''", with: "'") : decodeDoubleQuotedEscapes(inner)
    }

    /// Decodes the handful of double-quoted-scalar escapes this schema's own
    /// writer (PyYAML, via `club_config.save_club_config()`/`global_preferences.
    /// save_preferences()`) can actually produce -- `\uXXXX` above all. Direct
    /// report, 2026-09-19 ("umlauts seem to be broken"): a real saved club.yaml
    /// held `name: "Doma\u0308ne"` (PyYAML's default `allow_unicode=False`
    /// backslash-escapes every non-ASCII character in a double-quoted scalar --
    /// note the *decomposed* combining-diaeresis escape, not even a single
    /// \u00e4), and this parser previously just stripped the surrounding quotes
    /// without decoding anything inside them, so that six-character escape
    /// showed up as literal text instead of combining with the "a" before it to
    /// render "ä". Both `save_*()` calls now pass `allow_unicode=True` so this
    /// shouldn't be produced going forward -- this half fixes reading a file an
    /// older version already wrote, without requiring a re-save to un-break it.
    /// `\xXX` matters too: without `allow_unicode`, PyYAML writes every Latin-1
    /// character (ä ö ü ß, U+0080-U+00FF) that way -- `"Golfclub W\xFCrzburg"` --
    /// and only characters above that as `\uXXXX`. `\UXXXXXXXX` and the named
    /// controls are decoded as well; anything else keeps its literal character.
    ///
    /// Decoded scalar by scalar, not Character by Character: a `̈` combining
    /// mark has to join the letter before it, which a String append does anyway.
    private static func decodeDoubleQuotedEscapes(_ s: String) -> String {
        guard s.contains("\\") else { return s }
        var result = ""
        var scalars = s.unicodeScalars.makeIterator()
        func hexEscape(_ letter: Character, _ digits: Int) {
            var hex = ""
            for _ in 0..<digits { if let h = scalars.next() { hex.unicodeScalars.append(h) } }
            if hex.count == digits, let value = UInt32(hex, radix: 16), let scalar = Unicode.Scalar(value) {
                result.unicodeScalars.append(scalar)
            } else {
                result += "\\\(letter)\(hex)"  // malformed -- keep it visible rather than dropping it
            }
        }
        while let c = scalars.next() {
            guard c == "\\", let next = scalars.next() else { result.unicodeScalars.append(c); continue }
            switch next {
            case "n": result.append("\n")
            case "t", "\t": result.append("\t")
            case "r": result.append("\r")
            case "0": result.append("\0")
            case "a": result.append("\u{07}")
            case "b": result.append("\u{08}")
            case "v": result.append("\u{0B}")
            case "f": result.append("\u{0C}")
            case "e": result.append("\u{1B}")
            case " ": result.append(" ")
            case "N": result.append("\u{85}")
            case "_": result.append("\u{A0}")
            case "L": result.append("\u{2028}")
            case "P": result.append("\u{2029}")
            case "x": hexEscape("x", 2)
            case "u": hexEscape("u", 4)
            case "U": hexEscape("U", 8)
            default:
                result.unicodeScalars.append(next)  // `\"`, `\\`, `\/`, or unknown -- the literal character
            }
        }
        return result
    }

    /// Mirrors `yaml.safe_dump(config, sort_keys=False)`'s own scalar formatting
    /// closely enough for round-tripping between the two -- not a byte-identical
    /// implementation of PyYAML's own emitter.
    static func dump(_ value: YAMLValue) -> String {
        guard let map = value.asMap else { return "" }
        return dumpBlock(map, indent: 0)
    }

    private static func dumpBlock(_ pairs: [(String, YAMLValue)], indent: Int) -> String {
        let pad = String(repeating: "  ", count: indent)
        var out = ""
        for (key, val) in pairs {
            switch val {
            case .map(let nested):
                if nested.isEmpty {
                    out += "\(pad)\(key): {}\n"
                } else {
                    out += "\(pad)\(key):\n"
                    out += dumpBlock(nested, indent: indent + 1)
                }
            default:
                out += "\(pad)\(key): \(dumpScalar(val))\n"
            }
        }
        return out
    }

    private static func dumpScalar(_ value: YAMLValue) -> String {
        switch value {
        case .string(let s):
            // Quoted whenever a bare word would parse back as something else -- a
            // time ("16:00"), a number, or a YAML keyword. Matches why
            // global_preferences.py's own saved file already quotes every time
            // string; anything else in this schema (e.g. "metric") stays bare, same
            // as PyYAML would leave it.
            // Rule: a bare string must start with a letter and contain none of YAML's
            // structural characters -- anything else could parse back as a number,
            // date, float (".inf", "1e3", "0x1F"), null or other non-string. The
            // YAML 1.1 keyword words (on/off/yes/no, true/false, null) are quoted too.
            let structural = CharacterSet(charactersIn: ":#'\"[]{},&*!|>%@`\\")
            let keywords: Set<String> = ["true", "false", "null", "on", "off", "yes", "no", "y", "n"]
            let needsQuoting = s.isEmpty
                || !(s.first?.isLetter ?? false)
                || s.rangeOfCharacter(from: structural) != nil
                || s.hasSuffix(" ")
                || keywords.contains(s.lowercased())
            return needsQuoting ? "'\(s.replacingOccurrences(of: "'", with: "''"))'" : s
        case .int(let i):
            return String(i)
        case .double(let d):
            // safe_dump always shows a float with a decimal point (30.0, not 30).
            return d == d.rounded() && abs(d) < 1e15 ? String(format: "%.1f", d) : String(d)
        case .bool(let b):
            return b ? "true" : "false"
        case .null:
            return "null"
        case .map:
            return ""  // handled by dumpBlock directly
        }
    }
}
