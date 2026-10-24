"""Your scorecard for a course (1.3.0, 2026-10-24): per hole the par, the stroke index, the shots your handicap gives
you there, what "par for you" is and where to pick up; and in total how many Stableford points beat your handicap.

The course data comes from the club's own "Online Scorecard" page on pc caddie (`cat=scorecard`, logged in), which
carries every loop and tee of the club as JSON for its calculator: par per hole (`pl1..18`), stroke index (`vl1..18`),
Course Rating and Slope Rating. Public club facts that rarely change, so they are read at most every RATINGS_DAYS and
kept in DATA_DIR. Your Handicap Index is the one the reservation sync already reads (storage.load_my_handicap()).

What it cannot say: whether a round lowers your Handicap Index. That depends on your last 20 Score Differentials, and
pc caddie no longer has them ("since the switch to the World Handicap System only via DGV"). So the total is "better
than your handicap", which lowers it in most cases but not always (a good old round may drop out at the same time).

The arithmetic (World Handicap System, as the DGV applies it):
- Course Handicap = HI x Slope / 113 + (Course Rating - Par), rounded; for nine holes half the HI. Its shots go to the
  holes by stroke index: every hole gets the same share, the lowest indexes one more.
- Playing to it is 2 Stableford points a hole (36 over 18); a round better than the HI is one stroke more.
- A nine-hole round counts by adding an "expected" score for the other nine, from the HI. The WHS keeps that formula to
  itself; EXPECTED_NINE is the published approximation (HI x 0.52 + 1.2), so the nine-hole total is "about".
"""

import json
import math
import re
import time
from dataclasses import asdict, dataclass

from . import paths, scraper

RATINGS_DAYS = 30
SCORECARD_CATEGORY = "scorecard"


def EXPECTED_NINE(hi: float) -> float:  # noqa: N802 -- a published constant-like formula, named as such
    return hi * 0.52 + 1.2


@dataclass
class Tee:
    round: str  # "Runde A+B": a loop or a combination of loops
    color: str  # "gelb", "rot", ...
    gender: str  # "M" | "W"
    holes: int  # 9 | 18
    par: int
    course_rating: float
    slope: int
    pars: list[int]
    stroke_index: list[int]

    @property
    def key(self) -> str:
        return f"{self.round}|{self.color}|{self.gender}"


def parse_tees(html: str) -> tuple[list[Tee], str | None]:
    """The tees in the page's calculator data, and your gender as the page has it ("M"/"W", None if not found)."""
    found = re.search(r"rawCourseData:\s*\$\.parseJSON\('(.*?)'\)", html, re.S)
    gender = re.search(r"gender:\s*'(male|female)'", html)
    tees = []
    for row in json.loads(found.group(1)) if found else []:
        try:
            holes = 18 if str(row.get("numholes", "")).startswith("18") else 9
            pars = [int(row[f"pl{i}"]) for i in range(1, holes + 1)]
            index = [int(row[f"vl{i}"]) for i in range(1, holes + 1)]
            if str(row.get("active", "1")) != "1" or 0 in pars or sorted(index) != list(range(1, holes + 1)):
                continue
            tees.append(Tee(row["name"], row["color"], row["gender"], holes, int(row["par"]), float(row["cr"]), int(row["slope"]), pars, index))
        except (KeyError, TypeError, ValueError):
            continue
    return tees, ({"male": "M", "female": "W"}[gender.group(1)] if gender else None)


def _cache_file(club_id: str):
    return paths.DATA_DIR / f"ratings-{club_id}.json"


def load_tees(club_id: str, username: str, password: str, now: float | None = None) -> tuple[list[Tee], str | None]:
    """The club's tees: from DATA_DIR when read within RATINGS_DAYS, else read from pc caddie (one page) and kept."""
    now = time.time() if now is None else now
    cache = _cache_file(club_id)
    try:
        kept = json.loads(cache.read_text(encoding="utf-8"))
        if now - kept["fetched_at"] < RATINGS_DAYS * 86400 and kept["tees"]:
            return [Tee(**tee) for tee in kept["tees"]], kept.get("gender")
    except (OSError, ValueError, KeyError, TypeError):
        pass

    def read(client, reused):
        page = client.get(scraper.club_url(club_id, SCORECARD_CATEGORY)).text
        if reused and scraper.logged_out(page):
            raise scraper.SessionExpired("the session ran out")
        return page

    tees, gender = parse_tees(scraper.read_logged_in(club_id, username, password, read))
    if tees:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"fetched_at": now, "gender": gender, "tees": [asdict(tee) for tee in tees]}), encoding="utf-8")
    return tees, gender


def guess_tee(tees: list[Tee], holes: int | None, gender: str | None) -> Tee | None:
    """A first choice before you pick one: the club's first loop (or combination) with this many holes, from the tee a
    player of your gender most often plays (yellow for men, red for women), else its first tee."""
    if holes not in (9, 18):
        return None
    fitting = [tee for tee in tees if tee.holes == holes and (gender is None or tee.gender == gender)]
    if not fitting:
        return None
    first_round = fitting[0].round
    on_round = [tee for tee in fitting if tee.round == first_round]
    usual = "rot" if gender == "W" else "gelb"
    return next((tee for tee in on_round if tee.color == usual), on_round[0])


def course_handicap(hi: float, tee: Tee) -> int:
    share = hi / 2 if tee.holes == 9 else hi
    return math.floor(share * tee.slope / 113 + (tee.course_rating - tee.par) + 0.5)


def shots_per_hole(handicap: int, tee: Tee) -> list[int]:
    """`handicap` shots spread by stroke index (a plus handicap takes them back from the highest indexes first)."""
    base, extra = divmod(abs(handicap), tee.holes)
    sign = 1 if handicap >= 0 else -1
    if handicap >= 0:
        return [base + (1 if index <= extra else 0) for index in tee.stroke_index]
    return [sign * (base + (1 if index > tee.holes - extra else 0)) for index in tee.stroke_index]


def points(strokes: int | None, hole: dict) -> int | None:
    """Stableford points for `strokes` on `hole` (from card()): 2 for par for you, one more or less per stroke, never
    below 0; None for a hole not filled in."""
    return None if strokes is None else max(0, 2 + hole["aim"] - strokes)


def card(hi: float, tee: Tee) -> dict:
    """Everything the page shows for a round from `tee` with Handicap Index `hi`."""
    handicap = course_handicap(hi, tee)
    shots = shots_per_hole(handicap, tee)
    holes = [
        {"hole": number, "par": par, "index": index, "shots": given, "aim": par + given, "max": par + given + 2}
        for number, (par, index, given) in enumerate(zip(tee.pars, tee.stroke_index, shots, strict=True), start=1)
    ]
    # the highest gross score whose Score Differential is below the HI: on nine holes after adding the expected nine
    target = hi if tee.holes == 18 else hi - EXPECTED_NINE(hi)
    best_gross = math.ceil(target * tee.slope / 113 + tee.course_rating) - 1
    to_handicap = 2 * tee.holes
    return {
        "round": tee.round, "color": tee.color, "gender": tee.gender, "holes": holes, "par": tee.par,
        "course_rating": tee.course_rating, "slope": tee.slope, "handicap_index": hi, "course_handicap": handicap,
        "points_to_handicap": to_handicap, "points_better": to_handicap + tee.par + handicap - best_gross,
        "approximate": tee.holes == 9,
    }  # fmt: skip
