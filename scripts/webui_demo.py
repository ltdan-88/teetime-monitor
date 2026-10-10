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


def seed(directory: Path) -> None:
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
    for offset in range(5):
        date = (today + timedelta(days=offset)).isoformat()
        slots = []
        minute = 7 * 60 + 10
        while minute <= 19 * 60 + 30:
            time = f"{minute // 60:02d}:{minute % 60:02d}"
            busy = 0.55 if 9 <= minute // 60 <= 12 else 0.25
            booked = sum(1 for _ in range(4) if rng.random() < busy)
            names = rng.sample(men + women, k=min(booked, rng.choice([0, 1, 1, 2, 3]))) if booked else []
            slots.append(Slot(time=time, booked=booked, capacity=4, players=names))
            minute += 10
        weather = [
            WeatherPoint(
                time=f"{hour:02d}:00",
                precipitation_probability=[3, 70, 15, 3, 40][offset],
                precipitation_mm=[0.0, 1.8, 0.0, 0.0, 0.4][offset],
                wind_speed_kph=[16, 24, 16, 12, 22][offset] + (hour % 3) * 2,
                temperature_c=[19, 13, 21, 19, 17][offset] + (hour - 8) * 0.3,
                weather_code=codes[offset],
            )
            for hour in range(6, 22)
        ]
        events = [[], ["Vierer-Clubmeisterschaften AB"], [], ["AK 65 Herren"], []][offset]
        storage.save_schedule(
            Schedule(date=date, course=course, slots=slots, weather=weather, sun_times=SunTimes("07:12", "19:08"), events=events),
            path=db,
            authenticated=True,
        )
    storage.save_confirmed_booking(
        ConfirmedBooking(date=today.isoformat(), course=course, time="11:00", holes=18, source="manual"), path=db
    )
    finished = (now - timedelta(minutes=12)).isoformat()
    storage.record_scrape_run(
        started_at=finished, finished_at=finished, source="agent", attempted=5, saved=5, failed=0, authenticated=True, path=db
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--serve", action="store_true", help="start teetime-monitor-web on the demo data")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    seed(args.directory.resolve())
    print(f"Demo data written to {args.directory.resolve()}")
    if args.serve:
        from src.webui import server

        server.main(["--keep-running", "--port", str(args.port), "--no-browser"])


if __name__ == "__main__":
    main()
