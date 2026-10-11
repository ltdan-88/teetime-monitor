"""`teetime-monitor-web --serve` (2026-10-11): the password, the login cookie, and what is open without
one. The server runs on the loopback address here; only what it is bound to differs from a real Pi."""

import http.client
import json
import threading
import time

import pytest

from src import club_config, scrape_once
from src.webui import auth, data, server

PASSWORD = "correct horse"


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "web_auth.json")
    monkeypatch.setattr(auth, "PBKDF2_ROUNDS", 1000)  # the real 600 000 would only slow the tests down
    monkeypatch.setattr(data, "bootstrap", lambda: {"version": "test", "clubs": []})
    auth.set_password(PASSWORD)
    srv = server.WebServer(port=0, serve=True, host="127.0.0.1")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _request(srv, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    payload = json.dumps(body) if body is not None else None
    connection.request(method, path, body=payload, headers={"Content-Type": "application/json", **(headers or {})})
    response = connection.getresponse()
    text = response.read().decode("utf-8")
    connection.close()
    return response, text


def _login(srv, password=PASSWORD, headers=None):
    return _request(srv, "POST", "/api/auth/login", {"password": password}, headers)


def _cookie(response):
    return response.getheader("Set-Cookie").split(";")[0]


# ---- the password ------------------------------------------------------------------------------


def test_a_password_is_stored_hashed_and_only_it_is_accepted(tmp_path):
    file = tmp_path / "auth.json"
    assert not auth.is_configured(file)
    auth.set_password(PASSWORD, file)
    assert auth.is_configured(file)
    assert PASSWORD not in file.read_text()  # never stored itself
    assert file.stat().st_mode & 0o777 == 0o600
    assert auth.check_password(PASSWORD, file)
    assert not auth.check_password("correct horse!", file) and not auth.check_password("", file)
    with pytest.raises(ValueError):
        auth.set_password("short", file)


def test_a_session_is_signed_expires_and_ends_with_a_new_password(tmp_path):
    file = tmp_path / "auth.json"
    assert auth.make_session(file) is None  # no password, no session
    auth.set_password(PASSWORD, file)
    value = auth.make_session(file, now=1_000_000)
    assert auth.valid_session(value, file, now=1_000_000 + 60)
    assert not auth.valid_session(value, file, now=1_000_000 + auth.SESSION_SECONDS + 1)  # expired
    forged = value.rsplit(".", 1)[0] + ".AAAA"
    assert not auth.valid_session(forged, file, now=1_000_100)
    moved = f"v1.{int(value.split('.')[1]) + 99999}.{value.split('.')[2]}"  # a later expiry with the old signature
    assert not auth.valid_session(moved, file, now=1_000_100)
    assert not auth.valid_session("", file) and not auth.valid_session("garbage", file)
    auth.set_password("another password", file)
    assert not auth.valid_session(value, file, now=1_000_100)  # everyone is logged out


def test_wrong_guesses_lock_an_address_out_for_longer_each_time():
    throttle = auth.LoginThrottle()
    for _ in range(auth.FREE_MISSES - 1):
        throttle.miss("1.2.3.4", now=0)
    assert throttle.retry_after("1.2.3.4", now=0) == 0  # four misses: still free
    throttle.miss("1.2.3.4", now=0)
    assert throttle.retry_after("1.2.3.4", now=0) == auth.LOCK_BASE_SECONDS
    assert throttle.retry_after("1.2.3.4", now=auth.LOCK_BASE_SECONDS + 1) == 0
    throttle.miss("1.2.3.4", now=100)
    assert throttle.retry_after("1.2.3.4", now=100) == auth.LOCK_BASE_SECONDS * 2
    for _ in range(20):
        throttle.miss("1.2.3.4", now=1000)
    assert throttle.retry_after("1.2.3.4", now=1000) == auth.LOCK_MAX_SECONDS
    assert throttle.retry_after("5.6.7.8", now=1000) == 0  # other addresses are not affected
    throttle.success("1.2.3.4")
    assert throttle.retry_after("1.2.3.4", now=1000) == 0


# ---- the server -----------------------------------------------------------------------------------


def test_without_the_password_only_the_login_page_is_open(served):
    response, _ = _request(served, "GET", "/")
    assert response.status == 302 and response.getheader("Location") == "/login"
    for page in ("/app.js", "/lib.js", "/strings.json"):
        assert _request(served, "GET", page)[0].status == 302
    response, body = _request(served, "GET", "/api/bootstrap")
    assert response.status == 401 and json.loads(body) == {"error": "auth"}
    assert _request(served, "POST", "/api/settings", {"values": {}})[0].status == 401
    for page, kind in (("/login", "text/html"), ("/login.js", "javascript"), ("/style.css", "text/css")):
        response, _ = _request(served, "GET", page)
        assert response.status == 200 and kind in response.getheader("Content-Type"), page


def test_the_right_password_opens_everything_and_a_wrong_one_nothing(served):
    response, body = _login(served, "wrong password")
    assert response.status == 401 and json.loads(body) == {"error": "bad_password"} and response.getheader("Set-Cookie") is None
    response, _ = _login(served)
    assert response.status == 200
    cookie_header = response.getheader("Set-Cookie")
    assert "HttpOnly" in cookie_header and "SameSite=Lax" in cookie_header and "Max-Age=" in cookie_header
    headers = {"Cookie": _cookie(response)}
    response, body = _request(served, "GET", "/api/bootstrap", headers=headers)
    assert response.status == 200 and json.loads(body)["serve"] is True  # the page learns it may offer "Log out"
    assert _request(served, "GET", "/", headers=headers)[0].status == 200
    assert _request(served, "GET", "/login", headers=headers)[0].getheader("Location") == "/"  # already in
    assert _request(served, "GET", "/api/bootstrap", headers={"Cookie": "tm_auth=v1.1.forged"})[0].status == 401


def test_logging_out_ends_the_session_in_the_browser(served):
    headers = {"Cookie": _cookie(_login(served)[0])}
    response, _ = _request(served, "POST", "/api/auth/logout", {}, headers)
    assert response.status == 200 and "Max-Age=0" in response.getheader("Set-Cookie")


def test_too_many_wrong_passwords_lock_even_the_right_one_out(served):
    for _ in range(auth.FREE_MISSES):
        assert _login(served, "nope nope nope")[0].status == 401
    response, body = _login(served)  # the right password, but this address has to wait
    assert response.status == 429 and json.loads(body)["retry_after"] > 0


def test_a_page_from_another_site_cannot_post_but_any_host_name_works(served):
    cookie = _cookie(_login(served)[0])
    host = f"raspberrypi.local:{served.port}"  # the Pi is reached by name, not by loopback
    ok, _ = _request(served, "GET", "/api/bootstrap", headers={"Cookie": cookie, "Host": host})
    assert ok.status == 200
    same, _ = _request(served, "POST", "/api/auth/logout", {}, {"Cookie": cookie, "Host": host, "Origin": f"http://{host}"})
    assert same.status == 200
    other, _ = _request(served, "POST", "/api/settings", {"values": {}}, {"Cookie": cookie, "Host": host, "Origin": "http://evil.example"})
    assert other.status == 403


def test_it_never_stops_on_its_own_when_nobody_is_watching(served):
    served.started -= 10_000  # nobody has pinged for hours
    assert served.should_exit() is False


# ---- starting it ------------------------------------------------------------------------------------


def test_serve_refuses_to_start_without_a_password(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "web_auth.json")
    with pytest.raises(SystemExit) as stop:
        server.main(["--serve"])
    assert stop.value.code == 2
    assert "--set-password" in capsys.readouterr().out


def test_the_password_is_set_from_the_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "web_auth.json")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("a long enough password\n"))
    server.main(["--set-password", "--password-stdin"])
    assert auth.check_password("a long enough password")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("short\n"))
    with pytest.raises(SystemExit):
        server.main(["--set-password", "--password-stdin"])
    assert auth.check_password("a long enough password")  # a refused password changes nothing


def test_the_server_scrapes_every_saved_club_on_its_own_schedule(monkeypatch):
    seen = []
    monkeypatch.setattr(club_config, "list_clubs", lambda: ["one", "two"])
    monkeypatch.setattr(club_config, "load_club_config", lambda slug: {"club_id": slug})
    monkeypatch.setattr(scrape_once, "scrape_due_for_club", lambda slug, config, force=False, source="": seen.append((slug, force, source)))
    srv = server.WebServer(port=0, serve=True, host="127.0.0.1")
    try:
        server._scrape_pass(srv)
        deadline = time.time() + 5
        while len(seen) < 2 and time.time() < deadline:
            time.sleep(0.05)
    finally:
        srv.server_close()
    assert sorted(seen) == [("one", False, "agent"), ("two", False, "agent")]  # not forced: the clubs' own intervals decide


def test_the_raspberry_pi_installer_is_valid_shell():
    import shutil
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "deploy" / "raspberry-pi" / "install.sh"
    assert script.is_file()
    if shutil.which("bash"):
        assert subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True).returncode == 0
