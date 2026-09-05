"""Textual app entry point.

Per ROADMAP.md Phase 4, the multi-day overview is the intended home screen, with the
Phase 1 single-day detail table as a drill-down — but Phase 1 (scraper + storage) has to
exist first. This stub currently has neither screen implemented.

Phase 1 keybindings: `r` refresh, `c` confirm your tee time for the viewed day (writes
to storage.save_confirmed_booking — see ROADMAP.md "Known risks" for why this can't
wait), `q` quit.

NOT YET IMPLEMENTED.
"""


def main() -> None:
    raise NotImplementedError(
        "tui.py is a stub — build order is Phase 1 (scraper/storage/day-detail) "
        "before Phase 4 (multi-day overview home screen). See ROADMAP.md."
    )


if __name__ == "__main__":
    main()
