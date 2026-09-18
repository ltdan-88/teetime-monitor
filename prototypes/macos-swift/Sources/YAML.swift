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
        if raw.hasPrefix("'") && raw.hasSuffix("'") && raw.count >= 2 {
            return .string(String(raw.dropFirst().dropLast()).replacingOccurrences(of: "''", with: "'"))
        }
        if raw.hasPrefix("\"") && raw.hasSuffix("\"") && raw.count >= 2 {
            return .string(String(raw.dropFirst().dropLast()))
        }
        if let i = Int(raw) { return .int(i) }
        if let d = Double(raw) { return .double(d) }
        return .string(raw)
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
            let needsQuoting = s.contains(":") || s.isEmpty
                || Int(s) != nil || Double(s) != nil
                || ["true", "false", "null", "~"].contains(s)
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
