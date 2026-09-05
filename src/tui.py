"""Textual app entry point.

Per ROADMAP.md Phase 4, the multi-day overview is the intended home screen, with the
Phase 1 single-day detail table as a drill-down — but Phase 0 (club/course selection)
and Phase 1 (scraper + storage) have to exist first. This stub currently has no screens
implemented.

Startup (Phase 0): if more than one club exists under clubs/, show a picker (skipped if
there's only one); then, since courses rotate weekly, show a picker over
Schedule.available_courses for the chosen club (remembering the last pick as a
convenience default).

Phase 1 keybindings: `r` refresh, `c` confirm your tee time for the viewed day (writes
to storage.save_confirmed_booking — see ROADMAP.md "Known risks" for why this can't
wait), `q` quit. Phase 4 adds a search keybinding that opens a small form (party size,
time window, weekday/weekend windows, buffer from other flights) and shows results via
search.py. Phase 5 adds a keybinding for the crowd heatmap screen (analytics.py).

NOT YET IMPLEMENTED.
"""


def main() -> None:
    raise NotImplementedError(
        "tui.py is a stub — build order is Phase 0 (club/course selection) then "
        "Phase 1 (scraper/storage/day-detail) before Phase 4 (multi-day overview "
        "home screen). See ROADMAP.md."
    )


if __name__ == "__main__":
    main()
