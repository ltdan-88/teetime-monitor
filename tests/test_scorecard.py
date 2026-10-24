import json

import pytest

from src import scorecard, scraper


def _row(name, color, gender, holes, pars, index, cr, slope, active="1"):
    row = {"name": name, "color": color, "gender": gender, "numholes": "18" if holes == 18 else "9A", "par": str(sum(pars)),
           "cr": str(cr), "slope": str(slope), "active": active}
    for i in range(1, 19):
        row[f"pl{i}"] = str(pars[i - 1]) if i <= len(pars) else "0"
        row[f"vl{i}"] = index[i - 1] if i <= len(index) else i - len(index)
    return row


FRONT, BACK = [4, 4, 3, 5, 4, 4, 3, 5, 4], [4, 5, 3, 4, 4, 5, 4, 3, 4]
NINE = [6, 3, 8, 4, 1, 5, 9, 7, 2]
BOTH = [11, 5, 15, 7, 1, 9, 17, 13, 3, 16, 2, 18, 6, 4, 12, 14, 10, 8]
ROWS = [
    _row("Runde A", "weiss", "M", 9, FRONT, NINE, 36.5, 136),
    _row("Runde A", "gelb", "M", 9, FRONT, NINE, 36.2, 128),
    _row("Runde A+B", "gelb", "M", 18, FRONT + BACK, BOTH, 72.9, 132),
    _row("Runde A+B", "rot", "W", 18, FRONT + BACK, BOTH, 74.7, 128),
    _row("Runde X", "gelb", "M", 9, FRONT, NINE, 36.0, 120, active="0"),  # not in use: left out
]
PAGE = f"""<script>let data = {{ rawCourseData: $.parseJSON('{json.dumps(ROWS)}'), }};
let player = {{ hcp: parseFloat('20.0'), newHcp: null, gender: 'male' }};</script>"""


def test_the_scorecard_page_gives_every_tee_with_par_stroke_index_and_rating():
    tees, gender = scorecard.parse_tees(PAGE)
    assert gender == "M" and [tee.key for tee in tees] == ["Runde A|weiss|M", "Runde A|gelb|M", "Runde A+B|gelb|M", "Runde A+B|rot|W"]
    both = tees[2]
    assert (both.holes, both.par, both.course_rating, both.slope) == (18, 72, 72.9, 132)
    assert both.pars == FRONT + BACK and both.stroke_index == BOTH and tees[1].pars == FRONT
    assert scorecard.parse_tees("<p>no calculator</p>") == ([], None)


def test_the_course_handicap_and_its_shots_follow_the_world_handicap_system():
    tees, _ = scorecard.parse_tees(PAGE)
    both, nine = tees[2], tees[1]
    assert scorecard.course_handicap(20.0, both) == 24  # 20 x 132/113 + (72.9 - 72) = 24.26
    assert scorecard.course_handicap(20.0, nine) == 12  # half the index on nine holes: 10 x 128/113 + 0.2
    shots = scorecard.shots_per_hole(24, both)
    assert sum(shots) == 24 and [s for s, i in zip(shots, BOTH, strict=True) if i <= 5] == [2] * 5  # the five hardest get two
    assert scorecard.shots_per_hole(-2, both).count(-1) == 2 and sum(scorecard.shots_per_hole(-2, both)) == -2  # a plus handicap gives back
    assert sum(scorecard.shots_per_hole(42, both)) == 42 and max(scorecard.shots_per_hole(42, both)) == 3


def test_the_card_says_par_for_you_where_to_pick_up_and_what_beats_your_handicap():
    tees, _ = scorecard.parse_tees(PAGE)
    card = scorecard.card(20.0, tees[2])
    first = card["holes"][0]
    assert first == {"hole": 1, "par": 4, "index": 11, "shots": 1, "aim": 5, "max": 7}
    assert card["points_to_handicap"] == 36 and card["points_better"] == 36 and card["approximate"] is False  # rounding was kind
    assert scorecard.card(10.0, tees[2])["points_better"] == 37
    nine = scorecard.card(20.0, tees[1])
    assert nine["points_to_handicap"] == 18 and nine["points_better"] > 19 and nine["approximate"] is True  # the expected nine is worse than half the index


def test_a_first_guess_is_the_clubs_first_loop_from_the_usual_tee():
    tees, _ = scorecard.parse_tees(PAGE)
    assert scorecard.guess_tee(tees, 18, "M").key == "Runde A+B|gelb|M"
    assert scorecard.guess_tee(tees, 9, "M").key == "Runde A|gelb|M"
    assert scorecard.guess_tee(tees, 18, "W").key == "Runde A+B|rot|W"
    assert scorecard.guess_tee(tees, 6, "M") is None and scorecard.guess_tee(tees, 9, "W") is None


def test_the_course_data_is_read_once_a_month(tmp_path, monkeypatch):
    monkeypatch.setattr(scorecard.paths, "DATA_DIR", tmp_path)
    reads = []
    monkeypatch.setattr(scraper, "read_logged_in", lambda club_id, u, p, read: reads.append(club_id) or PAGE)
    tees, gender = scorecard.load_tees("0000001", "me", "secret", now=1000.0)
    assert len(tees) == 4 and gender == "M" and reads == ["0000001"]
    assert scorecard.load_tees("0000001", "me", "secret", now=1000.0 + 29 * 86400)[0] == tees and reads == ["0000001"]
    scorecard.load_tees("0000001", "me", "secret", now=1000.0 + 31 * 86400)
    assert reads == ["0000001", "0000001"]
    assert "secret" not in (tmp_path / "ratings-0000001.json").read_text()


@pytest.mark.parametrize("page", ["<p>login form</p>", ""])
def test_a_page_without_course_data_is_not_kept(tmp_path, monkeypatch, page):
    monkeypatch.setattr(scorecard.paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scraper, "read_logged_in", lambda *a: page)
    assert scorecard.load_tees("0000001", "me", "secret") == ([], None) and not (tmp_path / "ratings-0000001.json").exists()
