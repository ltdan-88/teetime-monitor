"""Detects when a confirmed booking's situation has changed since you booked it
(ROADMAP.md Phase 1, added 2026-09-06).

A confirmed booking isn't fire-and-forget — someone can join your flight, or a
neighboring slot that was empty at booking time can fill in and erode your buffer.
Since every scrape is kept forever, not overwritten (the whole reason for that design
choice — see storage.py), comparing a booking's slot in the latest scrape against an
earlier one is pure deterministic diffing. No AI, no new scraping.

Runs as part of the scheduled scrape (scrape_once.py); the TUI's home screen shows the
result as a plain banner next time you open the app — **not** a push notification.
Explicitly decided 2026-09-06: different from the "notify me of a new opportunity"
alerts already ruled out — this protects something you already committed to — but a
passive in-app banner still respects the same "no active pings" preference. An active
notification (e.g. a Mac notification) remains a possible later upgrade, not this.

NOT YET IMPLEMENTED.
"""

from dataclasses import dataclass

from .models import ConfirmedBooking, Schedule

# Kinds of change this watches for.
PARTY_GREW = "party_grew"  # your own slot's player count went up
BUFFER_SHRUNK = "buffer_shrunk"  # a neighboring slot that was open is now booked
NEIGHBOR_CROWDED = "neighbor_crowded"  # general crowding nearby, not just the buffer edge


@dataclass
class BookingChange:
    """One detected change for a confirmed booking, ready to show as an in-app banner."""

    booking: ConfirmedBooking
    kind: str  # one of the constants above
    message: str  # plain language, e.g. "1 more player joined your 14:00 since you booked"


def check_for_changes(
    booking: ConfirmedBooking, baseline: Schedule, latest: Schedule, buffer_minutes: int
) -> list[BookingChange]:
    """Compare `baseline` (the schedule as scraped around when `booking` was confirmed,
    or as of the last check) against `latest`, and report anything that changed for the
    worse. Only ever compares two already-scraped Schedules — no live site access here.
    """
    raise NotImplementedError("booking_watch.py is a stub — see ROADMAP.md Phase 1")
