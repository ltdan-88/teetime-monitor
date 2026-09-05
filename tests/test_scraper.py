from src.scraper import club_url, parse_seats_free


def test_parse_seats_free_extracts_count():
    assert parse_seats_free("seats-free-2 tt-grau") == 2


def test_parse_seats_free_full_empty_slot():
    assert parse_seats_free("seats-free-4 tt-grau") == 4


def test_parse_seats_free_blocked_row():
    assert parse_seats_free("seats-free-4 tt-rot pcco-tt-filter-display") == 4


def test_parse_seats_free_no_match_returns_none():
    assert parse_seats_free("some-other-class") is None


def test_club_url_bare():
    assert club_url("0000001", "tt_timetable_course") == (
        "https://www.pccaddie.net/clubs/0000001/app.php?cat=tt_timetable_course"
    )


def test_club_url_with_date_and_alias():
    url = club_url("0000001", "tt_timetable_course", date="2026-09-05", alias="COUB")
    assert url == (
        "https://www.pccaddie.net/clubs/0000001/app.php?cat=tt_timetable_course"
        "&date=DAY|2026-09-05&alias=ALIAS|COUB"
    )
