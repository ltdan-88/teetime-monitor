from src import geocode
from src.geocode import _normalize_query, find_club_location


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


# --- _normalize_query --------------------------------------------------------------
# pc caddie's own club names broke Nominatim's search outright until normalized --
# confirmed live against three real clubs before this existed (see module
# docstring). Each case here is a real club name actually seen in this project.


def test_normalize_query_strips_e_v_suffix():
    assert _normalize_query("Golf Club Sonnenberg e.V.") == "Golfclub Sonnenberg"


def test_normalize_query_strips_gmbh_suffix():
    assert _normalize_query("Nippenburg Golfclub GmbH") == "Nippenburg Golfclub"


def test_normalize_query_strips_gmbh_and_co_kg_suffix():
    assert _normalize_query("Some Golf Club GmbH & Co. KG") == "Some Golfclub"


def test_normalize_query_merges_golf_club_into_one_word():
    assert _normalize_query("Golfclub Domäne Musterhausen e.V.") == "Golfclub Domäne Musterhausen"


def test_normalize_query_merges_hyphenated_golf_club():
    assert _normalize_query("Golf-Club Beispiel e.V.") == "Golfclub Beispiel"


def test_normalize_query_leaves_a_name_with_no_suffix_alone():
    assert _normalize_query("Golfclub Sonnenberg") == "Golfclub Sonnenberg"


def test_normalize_query_blank_name_stays_blank():
    assert _normalize_query("   ") == ""


# --- find_club_location (Nominatim call, mocked) ------------------------------------


def test_find_club_location_parses_the_first_result(monkeypatch):
    payload = [{"lat": "50.1234567", "lon": "8.1234567", "display_name": "Golfclub Sonnenberg"}]
    monkeypatch.setattr(geocode.httpx, "get", lambda url, params, headers, timeout: _FakeResponse(payload))

    assert find_club_location("Golf Club Sonnenberg e.V.") == (50.1234567, 8.1234567)


def test_find_club_location_sends_the_normalized_name_and_a_real_user_agent(monkeypatch):
    captured = {}

    def fake_get(url, params, headers, timeout):
        captured["params"] = params
        captured["headers"] = headers
        return _FakeResponse([])

    monkeypatch.setattr(geocode.httpx, "get", fake_get)

    find_club_location("Golf Club Sonnenberg e.V.")

    # Sent normalized ("Golfclub", no "e.V.") -- see the _normalize_query tests
    # above for why the raw pc caddie name wouldn't have matched anything.
    assert captured["params"]["q"] == "Golfclub Sonnenberg"
    # Nominatim's own usage policy requires a real, identifying User-Agent -- not a
    # browser-spoofing one (see module docstring).
    assert "teetime-monitor" in captured["headers"]["User-Agent"]


def test_find_club_location_returns_none_on_no_results(monkeypatch):
    monkeypatch.setattr(geocode.httpx, "get", lambda url, params, headers, timeout: _FakeResponse([]))

    assert find_club_location("A club that doesn't exist anywhere") is None


def test_find_club_location_returns_none_on_request_failure(monkeypatch):
    def fake_get(url, params, headers, timeout):
        raise ConnectionError("no network")

    monkeypatch.setattr(geocode.httpx, "get", fake_get)

    # Never raises -- same "don't fabricate, don't crash" contract as weather.py's
    # own best-effort lookups.
    assert find_club_location("Golf Club Sonnenberg e.V.") is None


def test_find_club_location_returns_none_on_malformed_result_shape(monkeypatch):
    # A result missing "lat"/"lon" entirely, or holding something unparseable --
    # shouldn't crash the caller either.
    monkeypatch.setattr(geocode.httpx, "get", lambda url, params, headers, timeout: _FakeResponse([{}]))

    assert find_club_location("Golf Club Sonnenberg e.V.") is None


def test_find_club_location_returns_none_for_a_blank_name(monkeypatch):
    def fake_get(*a, **k):
        raise AssertionError("should never even make a request for a blank name")

    monkeypatch.setattr(geocode.httpx, "get", fake_get)

    assert find_club_location("   ") is None
