#!/usr/bin/env python3
"""Seeds a throwaway config/data folder with a fake club and a few days of tee sheets, so the web
UI (and its screenshots) can be looked at without any pc caddie login or network (2026-10-10).

  python scripts/webui_demo.py DIR              # write the demo data into DIR
  python scripts/webui_demo.py DIR --serve      # ... and start `teetime-monitor-web` on it

Nothing here touches your real settings: it sets TEETIME_MONITOR_CONFIG_DIR / TEETIME_MONITOR_DATA_DIR
to DIR/config and DIR/data before anything from `src` is imported. Names are the fixtures the
test-suite uses ("Max Mustermann"...); the weather is invented.
"""

import argparse
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def seed(directory: Path, second_club: bool = False) -> None:
    config_dir, data_dir = directory / "config", directory / "data"
    os.environ["TEETIME_MONITOR_CONFIG_DIR"] = str(config_dir)
    os.environ["TEETIME_MONITOR_DATA_DIR"] = str(data_dir)
    sys.path.insert(0, str(REPO))
    import yaml

    from src import club_config, paths, storage
    from src.models import ConfirmedBooking, PlayerSighting, Schedule, Slot, SunTimes, WeatherPoint

    paths.ensure_dirs()
    club_id, course = "0000001", "18 Loch Tee 1"
    club_config.save_club_config(
        "golfclub-beispiel",
        {
            "club_id": club_id,
            "name": "Golfclub Beispiel",
            "default_course": course,
            "overview_days": 5,
            "location": {"lat": 49.79, "lon": 9.95},
        },
    )
    (config_dir / "preferences.yaml").write_text(
        yaml.safe_dump(
            {
                "units": "metric",
                "availability": {
                    "min_open_spots": 2,
                    "weekday_window": {"after": "14:00", "before": "17:00"},
                    "weekend_window": {"after": "10:00", "before": "14:00"},
                },
            }
        ),
        encoding="utf-8",
    )
    db = data_dir / f"{club_id}.db"
    rng = random.Random(7)
    men = ["Max Mustermann", "Hans Beispiel", "Jonas Mustermann", "Uwe Mustermann", "Peter Probe", "Karl Musterfrau-Test"]
    women = ["Erika Musterfrau", "Greta Probe", "Anna Beispiel", "Lena Musterfrau"]
    sightings = [PlayerSighting(name=n, gender="male", member_status="member", handicap=18.4) for n in men] + [
        PlayerSighting(name=n, gender="female", member_status="member", handicap=22.1) for n in women
    ]
    now = datetime.now(UTC)
    storage.init_db(db)
    storage.record_seen_players(sightings, now.isoformat(), path=db)
    storage.set_player_friend("Max Mustermann", True, path=db)
    storage.set_player_friend("Erika Musterfrau", True, path=db)

    today = datetime.now().date()
    codes = [1, 61, 3, 0, 80]
    for offset in range(-28, 5):  # four weeks of history (the heatmap needs finished days) and the coming five
        date = (today + timedelta(days=offset)).isoformat()
        slots = []
        minute = 7 * 60 + 10
        while minute <= 19 * 60 + 30:
            time = f"{minute // 60:02d}:{minute % 60:02d}"
            busy = 0.55 if 9 <= minute // 60 <= 12 else 0.25
            booked = sum(1 for _ in range(4) if rng.random() < busy)
            names = rng.sample(men + women, k=min(booked, rng.choice([0, 1, 1, 2, 3]))) if booked else []
            event_names = [[], ["Vierer-Clubmeisterschaften AB"], [], ["AK 65 Herren"], []][max(offset, 0)] if offset >= 0 else []
            if event_names and 12 * 60 + 10 <= minute <= 12 * 60 + 50:  # a tournament block at midday: bookable slots become "blocked"
                slots.append(Slot(time=time, booked=0, capacity=4, players=[], block_reason=event_names[0]))
            else:
                slots.append(Slot(time=time, booked=booked, capacity=4, players=names))
            minute += 10
        weather = [
            WeatherPoint(
                time=f"{hour:02d}:00",
                precipitation_probability=[3, 70, 15, 3, 40][max(offset, 0)],
                precipitation_mm=[0.0, 1.8, 0.0, 0.0, 0.4][max(offset, 0)],
                wind_speed_kph=[16, 24, 16, 12, 22][max(offset, 0)] + (hour % 3) * 2,
                temperature_c=[19, 13, 21, 19, 17][max(offset, 0)] + (hour - 8) * 0.3,
                weather_code=codes[max(offset, 0)],
            )
            for hour in range(6, 22)
        ]
        events = [[], ["Vierer-Clubmeisterschaften AB"], [], ["AK 65 Herren"], []][max(offset, 0)]
        storage.save_schedule(
            Schedule(date=date, course=course, slots=slots, weather=weather, sun_times=SunTimes("07:12", "19:08"), events=events),
            path=db,
            authenticated=True,
        )
    storage.save_confirmed_booking(
        ConfirmedBooking(date=today.isoformat(), course=course, time="11:00", holes=18, source="manual"), path=db
    )
    storage.save_confirmed_booking(  # a round played three days ago: its scorecard is under "Past rounds"
        ConfirmedBooking(date=(today - timedelta(days=3)).isoformat(), course=course, time="14:20", holes=18, source="my_reservations"), path=db
    )
    storage.save_my_handicap(24.3, path=db)  # your own Handicap Index, as the reservation sync reads it
    finished = (now - timedelta(minutes=12)).isoformat()
    storage.record_scrape_run(
        started_at=finished, finished_at=finished, source="agent", attempted=5, saved=5, failed=0, authenticated=True, path=db
    )
    if second_club:  # a neighbouring club, with a member of it booked there tomorrow (the shared player directory)
        other_id, other_course = "0000002", "9 Loch Platz"
        club_config.save_club_config("golfclub-nachbar", {"club_id": other_id, "name": "Golfclub Nachbar e.V.", "default_course": other_course, "overview_days": 5, "location": {"lat": 49.8, "lon": 9.9}})
        other_db = data_dir / f"{other_id}.db"
        storage.init_db(other_db)
        storage.record_seen_players([PlayerSighting(name="Nina Nachbar", gender="female", member_status="member", handicap=15.2)], now.isoformat(), path=other_db)
        for offset in range(0, 3):
            date = (today + timedelta(days=offset)).isoformat()
            slots = [Slot(time=f"{h:02d}:{m:02d}", booked=1 if (h, m) == (10, 0) and offset == 1 else 0, capacity=4,
                          players=["Nina Nachbar"] if (h, m) == (10, 0) and offset == 1 else []) for h in range(8, 18) for m in (0, 30)]
            storage.save_schedule(Schedule(date=date, course=other_course, slots=slots, weather=[], sun_times=SunTimes("07:12", "19:08"), events=[]), path=other_db, authenticated=True)
        storage.record_scrape_run(started_at=finished, finished_at=finished, source="agent", attempted=3, saved=3, failed=0, authenticated=True, path=other_db)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--serve", action="store_true", help="start teetime-monitor-web on the demo data")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--at", metavar="HH:MM", help="pretend it is this time of day (the demo's slots are all by day: late in the evening today's card would be gone)")
    parser.add_argument("--offline", action="store_true", help="never touch the network: scrapes and previews do nothing")
    parser.add_argument("--second-club", action="store_true", help="add a second saved club with a member booked there")
    parser.add_argument("--password", help="run it as `teetime-monitor-web --serve` (on the loopback address) with this password")
    args = parser.parse_args()
    os.environ["TEETIME_MONITOR_NO_UPDATE_CHECK"] = "1"  # a demo never calls out
    seed(args.directory.resolve(), second_club=args.second_club)
    if args.at:
        from src import clock

        clock.now_hhmm = lambda: args.at
    import tomllib

    from src.webui import data

    data.version = lambda: tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]  # not a stale installed copy's
    print(f"Demo data written to {args.directory.resolve()}")
    if args.serve:
        from src import scrape_once, scraper
        from src.webui import clubs_api, server

        if args.offline:

            def rejected(*_args, **_kwargs):
                raise scraper.LoginError("offline demo")

            scrape_once.scrape_due_for_club = lambda *a, **k: []
            clubs_api.preview = lambda club_id, name: {"ok": False, "reason": "no_tee_sheet"}
            scraper.login = rejected

            # nothing reaches pc caddie: a booking or a cancellation just succeeds (the page then shows it)
            from src import booking, club_config

            class _Session:
                def close(self):
                    pass

            booking.open_session = lambda club_id, username, password: _Session()

            # The booking form's friends list (who can be booked with you), invented like every name here.
            form = (
                '<form id="frm_book_data"><select name="rq[players][2][friend][bd_id]"><option value="">-</option>'
                '<option value="101">Mustermann, Max</option><option value="102">Musterfrau, Erika</option>'
                '<option value="103">Beispiel, Anna</option></select></form>'
            )

            def read_ahead(kind):  # a moment, like the real pages
                def read(client, club_id, course, date, time):
                    import time as clock_time

                    clock_time.sleep(0.4)
                    return booking.Prepared(kind, "", form if kind == "book" else "")

                return read

            def commit(client, club_id, course, date, time, prepared, progress=None, partners=()):
                import time as clock_time

                clock_time.sleep(0.4)
                if progress:
                    progress("confirm")
                clock_time.sleep(0.3)

            booking.prepare_book, booking.prepare_cancel = read_ahead("book"), read_ahead("cancel")
            booking.commit_book = booking.commit_cancel = commit
            club_config.resolve_credentials = lambda key: ("demo", "demo")

            from src import scorecard  # an invented club's tees: two loops of nine, played alone or together

            def tees(club_id, username, password, now=None):
                front, back = [4, 4, 3, 5, 4, 4, 3, 5, 4], [4, 5, 3, 4, 4, 5, 4, 3, 4]
                nine = [5, 3, 8, 4, 1, 6, 9, 7, 2]
                both = [9, 5, 15, 7, 1, 11, 17, 13, 3, 10, 2, 16, 6, 4, 12, 14, 18, 8]
                return [
                    scorecard.Tee("Runde A", "gelb", "M", 9, 36, 36.2, 128, front, nine),
                    scorecard.Tee("Runde A", "rot", "M", 9, 36, 34.6, 120, front, nine),
                    scorecard.Tee("Runde A+B", "gelb", "M", 18, 72, 72.4, 131, front + back, both),
                    scorecard.Tee("Runde A+B", "rot", "M", 18, 72, 69.5, 123, front + back, both),
                ], "M"

            scorecard.load_tees = tees

            invented_clubs = [  # what pc caddie's own home-club list answers, invented
                {"number": "0490001", "name": "0001 - Golfclub Beispiel-Nord e.V.", "label": "Golfclub Beispiel-Nord e.V. (Deutschland)"},
                {"number": "0490002", "name": "0002 - Golfpark Musterstadt", "label": "Golfpark Musterstadt (Deutschland)"},
            ]
            booking.search_home_clubs = lambda club, text: {
                "clubs": [c for c in invented_clubs if len(text.strip()) >= 3 and text.strip().lower() in c["name"].lower()]
            }

            def tournaments(club_id, username, password):  # an invented calendar, relative to today
                from datetime import date, timedelta

                from src.models import Tournament

                def day(n):
                    return (date.today() + timedelta(days=n)).isoformat()

                return [
                    Tournament("9000", day(1), "12:10", "Vierer-Clubmeisterschaften AB", "Round A", 18, False, f"{day(-1)} 10:00", False),
                    Tournament("9001", day(2), "09:30", "Autumn Trophy", "Round A+B", 18, True, f"{day(0)} 10:00", True),
                    Tournament("9002", day(2), "14:00", "Twilight Scramble", "Round C", 9, False, f"{day(1)} 12:00", True),
                    Tournament("9003", day(9), "10:00", "Ladies Coffee Cup", "Clubhouse", 18, True, f"{day(7)} 10:00", False),
                    Tournament("9004", day(16), None, "Winter Opener", "", None, True, None, False),
                    Tournament("9005", day(40), "15:00", "Rules Evening", "Clubhouse", None, True, f"{day(38)} 10:00", False),
                ]

            scraper.scrape_tournaments = tournaments
            scrape_once._sync_my_reservations = lambda *args, **kwargs: "ok"

        if args.password:
            from src.webui import auth

            auth.set_password(args.password)
            server.main(["--serve", "--host", "127.0.0.1", "--port", str(args.port)])
        else:
            server.main(["--keep-running", "--port", str(args.port), "--no-browser"])


if __name__ == "__main__":
    main()
