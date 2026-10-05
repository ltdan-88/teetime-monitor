import Foundation
@testable import TeetimeMonitorCore

func runClubDefaultsTests() {
    Harness.group("ClubDefaults") {
        let yaml = "club_id: '0497758'\\ndefault_course: ''\\ncalendar:\\n  vacation_ranges:\\n  - [2026-07-01, 2026-07-31]\\n"
            .replacingOccurrences(of: "\\n", with: "\n")

        Harness.checkEqual("an empty default_course reads as nil", ClubDefaults.parseDefaultCourse(in: yaml), nil)
        Harness.checkEqual("a missing key reads as nil", ClubDefaults.parseDefaultCourse(in: "club_id: x\n"), nil)
        Harness.checkEqual("quoted value", ClubDefaults.parseDefaultCourse(in: "default_course: '9 Loch Tee 1'\n"), "9 Loch Tee 1")
        Harness.checkEqual("bare value", ClubDefaults.parseDefaultCourse(in: "default_course: Platz A\n"), "Platz A")

        let set = ClubDefaults.replacingDefaultCourse("9 Loch Tee 1", in: yaml)
        Harness.checkEqual("replaced line round-trips", ClubDefaults.parseDefaultCourse(in: set), "9 Loch Tee 1")
        Harness.check("every other line (incl. the list) is untouched",
                      set.contains("  - [2026-07-01, 2026-07-31]") && set.contains("club_id: '0497758'"))

        let appended = ClubDefaults.replacingDefaultCourse("A'B", in: "club_id: x\n")
        Harness.checkEqual("an absent key is appended, apostrophes escaped",
                           ClubDefaults.parseDefaultCourse(in: appended), "A'B")

        // course_holes (2026-10-05): a mapping the YAML codec can't round-trip, edited as text.
        let withList = "club_id: '0497712'\ndefault_course: ''\ncalendar:\n  vacation_ranges:\n"
            + "  - { start: \"2026-07-04\", end: \"2026-09-15\", label: \"summer\" }\noverview_days: 5\n"
        func entries(_ text: String) -> [String] { ClubDefaults.parseCourseHoles(in: text).map { "\($0.0)=\($0.1)" } }

        Harness.checkEqual("no key reads as empty", entries(withList), [])
        let added = ClubDefaults.replacingCourseHoles("Kurzplatz", holes: 9, in: withList)
        Harness.checkEqual("an added entry reads back", entries(added), ["Kurzplatz=9"])
        Harness.check("adding keeps every other line, list included",
                      added.hasPrefix(withList) && added.hasSuffix("course_holes:\n  'Kurzplatz': 9\n"))
        Harness.checkEqual("no trailing newline is handled",
                           entries(ClubDefaults.replacingCourseHoles("Kurzplatz", holes: 9, in: "club_id: x")), ["Kurzplatz=9"])

        let two = ClubDefaults.replacingCourseHoles("Kinder's Platz", holes: 6, in: added)
        Harness.checkEqual("a second entry, apostrophe escaped", entries(two), ["Kurzplatz=9", "Kinder's Platz=6"])
        let changed = ClubDefaults.replacingCourseHoles("kurzplatz ", holes: 18, in: two)
        Harness.checkEqual("same label (any case/space) replaces in place", entries(changed), ["kurzplatz =18", "Kinder's Platz=6"])
        Harness.check("one key only", changed.components(separatedBy: "course_holes:").count == 2)

        let cleared = ClubDefaults.replacingCourseHoles("Kurzplatz", holes: nil, in: two)
        Harness.checkEqual("Auto removes just that entry", entries(cleared), ["Kinder's Platz=6"])
        let none = ClubDefaults.replacingCourseHoles("Kinder's Platz", holes: nil, in: cleared)
        Harness.checkEqual("removing the last entry removes the key and restores the file", none, withList)
        Harness.checkEqual("clearing a missing entry is a no-op", ClubDefaults.replacingCourseHoles("X", holes: nil, in: withList), withList)

        // Keys after the block survive; so do comments and a hand-written flow mapping.
        let middle = "club_id: x\ncourse_holes:\n  Kurzplatz: 9  # short\n  \"Bahn 2\": 18\n# overview\noverview_days: 3\n"
        Harness.checkEqual("bare, quoted and commented entries parse", entries(middle), ["Kurzplatz=9", "Bahn 2=18"])
        let middleSet = ClubDefaults.replacingCourseHoles("Platz C", holes: 6, in: middle)
        Harness.checkEqual("rewriting a block in the middle keeps the tail",
                           middleSet, "club_id: x\ncourse_holes:\n  'Kurzplatz': 9\n  'Bahn 2': 18\n  'Platz C': 6\n# overview\noverview_days: 3\n")
        let flow = "course_holes: {\"Kurzplatz\": 9, 'A, B': 6, bad: nine}  # note\ndefault_course: ''\n"
        Harness.checkEqual("a flow mapping parses, bad values skipped", entries(flow), ["Kurzplatz=9", "A, B=6"])
        Harness.checkEqual("a flow mapping is rewritten as a block",
                           ClubDefaults.replacingCourseHoles("Kurzplatz", holes: nil, in: flow),
                           "course_holes:\n  'A, B': 6\ndefault_course: ''\n")
        Harness.checkEqual("an empty flow mapping is just removed",
                           ClubDefaults.replacingCourseHoles("X", holes: nil, in: "course_holes: {}\nclub_id: x\n"), "club_id: x\n")
        Harness.checkEqual("zero/negative values are ignored", entries("course_holes:\n  A: 0\n  B: -9\n  C: 9\n"), ["C=9"])

        // Python's yaml.safe_dump shapes (club_config.save_club_config()).
        Harness.checkEqual("PyYAML quoted key with a colon", entries("course_holes:\n  'Kurzplatz: 6 Loch': 9\n"), ["Kurzplatz: 6 Loch=9"])
        Harness.checkEqual("PyYAML double-quoted escapes", entries("course_holes:\n  \"Gr\\xFCn\": 9\n"), ["Grün=9"])

        // Resolution: override (exact, case-insensitive, trimmed) -> heuristic -> unknown.
        let overrides = [("Kurzplatz", 9), ("18 Loch Tee 1", 9)]
        Harness.checkEqual("override on a nameless course", Store.holes(from: "  kurzplatz", overrides: overrides), 9)
        Harness.checkEqual("override beats the label", Store.holes(from: "18 Loch Tee 1", overrides: overrides), 9)
        Harness.checkEqual("no override falls back to the label", Store.holes(from: "6 Loch Platz", overrides: overrides), 6)
        Harness.check("neither -> unknown", Store.holes(from: "Meisterschaftsplatz", overrides: overrides) == nil)
        Harness.check("no overrides -> heuristic only", Store.holes(from: "Kurzplatz", overrides: []) == nil)
        // Two labels that normalise alike: the first in file order wins, like Python.
        let dup = [("Kurzplatz", 9), ("kurzplatz", 18)]
        Harness.checkEqual("duplicate labels: first wins", Store.holes(from: "KURZPLATZ", overrides: dup), 9)

        // Hand-edited blocks (2026-10-05): a blank or comment line inside the block must not
        // end it, or a rewrite orphans the entries below.
        let gappy = "club_id: x\ncourse_holes:\n  Kurz: 9\n# note\n  Lang: 18\n\n  Mid: 6\nx: 1\n"
        Harness.checkEqual("entries after a blank/comment line parse", entries(gappy), ["Kurz=9", "Lang=18", "Mid=6"])
        Harness.checkEqual("Auto on the first entry leaves no orphans",
                           ClubDefaults.replacingCourseHoles("Kurz", holes: nil, in: gappy),
                           "club_id: x\ncourse_holes:\n  'Lang': 18\n  'Mid': 6\nx: 1\n")
        Harness.checkEqual("removing every entry removes the whole block",
                           ClubDefaults.replacingCourseHoles("Mid", holes: nil, in:
                               ClubDefaults.replacingCourseHoles("Lang", holes: nil, in:
                                   ClubDefaults.replacingCourseHoles("Kurz", holes: nil, in: gappy))),
                           "club_id: x\nx: 1\n")
        let trailing = "course_holes:\n  Kurz: 9\n\n# tail\nx: 1\n"
        Harness.checkEqual("blank/comment lines after the last entry are kept",
                           ClubDefaults.replacingCourseHoles("Kurz", holes: 18, in: trailing),
                           "course_holes:\n  'Kurz': 18\n\n# tail\nx: 1\n")
        let crlf = "club_id: x\r\ncourse_holes:\r\n  Kurz: 9\r\n  Lang: 18\r\nx: 1\r\n"
        Harness.checkEqual("CRLF files parse", entries(crlf), ["Kurz=9", "Lang=18"])
        Harness.checkEqual("CRLF rewrite keeps the other lines",
                           ClubDefaults.replacingCourseHoles("Kurz", holes: nil, in: crlf),
                           "club_id: x\r\ncourse_holes:\r\n  'Lang': 18\r\nx: 1\r\n")
    }
}
