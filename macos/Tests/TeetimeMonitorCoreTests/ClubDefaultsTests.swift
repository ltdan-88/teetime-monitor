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
    }
}
