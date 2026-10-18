"""The newer-version notice and the Raspberry Pi update (2026-10-11)."""

import threading
import time

import httpx
import pytest

from src import paths, user_config
from src.webui import auth, data, server, updates


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.delenv("TEETIME_MONITOR_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(data, "version", lambda: "0.78.0")
    monkeypatch.setattr(user_config, "CONFIG_FILE", tmp_path / "config")
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    updates.reset_for_tests()
    yield
    updates.reset_for_tests()


class _Response:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=None)

    def json(self):
        return self._payload


def _release(monkeypatch, tag="v0.79.0", status=200):
    seen = []

    def get(url, **kwargs):
        seen.append((url, kwargs))
        return _Response({"tag_name": tag, "html_url": f"https://github.com/ltdan-88/teetime-monitor/releases/tag/{tag}"}, status)

    monkeypatch.setattr(httpx, "get", get)
    return seen


def test_versions_compare_by_number_not_by_text():
    assert updates.is_newer("v0.79.0", "0.78.0") and updates.is_newer("0.100.0", "0.99.9")
    assert not updates.is_newer("0.78.0", "0.78.0") and not updates.is_newer("0.77.9", "0.78.0")
    assert not updates.is_newer("garbage", "0.78.0") and not updates.is_newer("0.79.0", "dev")


def test_a_newer_release_is_found_and_reported(monkeypatch):
    seen = _release(monkeypatch)
    assert updates.status()["newer"] is False  # nothing known yet
    assert updates.check_now()["tag"] == "v0.79.0"
    assert seen[0][0] == updates.LATEST_URL and "teetime-monitor" in seen[0][1]["headers"]["User-Agent"]
    info = updates.status()
    assert info["newer"] is True and info["latest"] == "0.79.0" and info["current"] == "0.78.0"
    assert info["url"].endswith("/releases/tag/v0.79.0")


def test_no_newer_release_means_no_notice(monkeypatch):
    _release(monkeypatch, tag="v0.78.0")
    updates.check_now()
    assert updates.status()["newer"] is False


def test_an_unreachable_or_odd_answer_changes_nothing(monkeypatch):
    _release(monkeypatch)
    updates.check_now()

    def down(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", down)
    assert updates.check_now() is None and updates.status()["latest"] == "0.79.0"  # the old answer stays
    _release(monkeypatch, tag="not-a-version")
    assert updates.check_now() is None
    _release(monkeypatch, status=403)  # rate limited
    assert updates.check_now() is None


def test_the_check_can_be_switched_off(monkeypatch):
    seen = _release(monkeypatch)
    monkeypatch.setenv("TEETIME_MONITOR_NO_UPDATE_CHECK", "1")
    assert updates.check_now() is None and seen == []


def test_the_install_kind_is_told_from_where_the_program_lives(monkeypatch, tmp_path):
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    for prefix, kind in (
        ("/opt/homebrew/Cellar/teetime-monitor/0.78.0/libexec", "brew"),
        ("C:\\Users\\me\\scoop\\apps\\teetime-monitor\\current", "scoop"),
        ("/home/me/somewhere", "other"),
    ):
        monkeypatch.setattr("sys.prefix", prefix)
        assert updates.install_kind() == kind
    pi = tmp_path / updates.SERVER_DIR_NAME / "venv"
    monkeypatch.setattr("sys.prefix", str(pi))
    assert updates.install_kind() == "other"  # the installer's folder, but not run by systemd
    monkeypatch.setenv("INVOCATION_ID", "abc")
    assert updates.install_kind() == "pi"


def test_the_notice_names_the_command_for_homebrew(monkeypatch):
    _release(monkeypatch)
    updates.check_now()
    monkeypatch.setattr(updates, "install_kind", lambda: "brew")
    info = updates.status(serving=False)
    assert info["command"] == "brew upgrade teetime-monitor" and info["can_update"] is False


def test_only_a_pi_server_can_update_itself(monkeypatch):
    _release(monkeypatch)
    updates.check_now()
    assert updates.apply(True, lambda: None) == {"error": "not_supported"}  # a normal install
    monkeypatch.setattr(updates, "install_kind", lambda: "pi")
    assert updates.apply(False, lambda: None) == {"error": "not_supported"}  # a Pi, but not serving
    updates.reset_for_tests()
    monkeypatch.setattr(updates, "install_kind", lambda: "pi")
    assert updates.apply(True, lambda: None) == {"error": "nothing_to_install"}  # nothing newer known


def test_the_update_installs_the_release_the_server_found_then_restarts(monkeypatch):
    _release(monkeypatch, tag="v0.79.0")
    updates.check_now()
    monkeypatch.setattr(updates, "install_kind", lambda: "pi")
    monkeypatch.setattr(updates.time, "sleep", lambda seconds: None)
    commands, restarted = [], threading.Event()

    monkeypatch.setattr(updates.subprocess, "run", _runs(commands, [(0, ""), (0, "ok 0.79.0\n")]))
    assert updates.apply(True, restarted.set) == {"state": "running", "error": None}
    assert restarted.wait(5)
    assert commands[0][-1] == "https://github.com/ltdan-88/teetime-monitor/archive/refs/tags/v0.79.0.tar.gz"
    assert "pip" in commands[0] and "--upgrade" in commands[0]
    assert commands[1][1:] == ["-I", "-m", "src.webui.server", "--self-test"]  # the new version started once first
    assert updates.status(True)["install"]["state"] == "restarting"
    assert updates.status(True)["auto_result"] is None  # a manual update leaves no morning note


def _runs(commands, answers):
    """A stand-in for subprocess.run that answers (returncode, stdout) in turn and records each command."""
    answers = list(answers)

    def run(command, **kwargs):
        commands.append(command)
        code, out = answers.pop(0)
        return type("Result", (), {"returncode": code, "stdout": out, "stderr": "" if code == 0 else "Traceback\nImportError: broken\n"})()

    return run


def _settle():
    deadline = time.time() + 5
    while updates.status(True)["install"]["state"] == "running" and time.time() < deadline:
        time.sleep(0.05)
    return updates.status(True)["install"]


def test_a_new_version_that_does_not_start_is_rolled_back_and_nothing_restarts(monkeypatch):
    _release(monkeypatch, tag="v0.79.0")
    updates.check_now()
    monkeypatch.setattr(updates, "install_kind", lambda: "pi")
    commands, restarted = [], []
    monkeypatch.setattr(updates.subprocess, "run", _runs(commands, [(0, ""), (1, ""), (0, "")]))
    updates.apply(True, lambda: restarted.append(1))
    state = _settle()
    assert state["state"] == "failed" and "ImportError: broken" in state["error"] and "v0.78.0 restored" in state["error"]
    assert commands[2][-1].endswith("/tags/v0.78.0.tar.gz")  # the version that ran is installed back
    assert restarted == []


def test_a_self_test_that_reports_another_version_counts_as_failed(monkeypatch):
    _release(monkeypatch, tag="v0.79.0")
    updates.check_now()
    monkeypatch.setattr(updates, "install_kind", lambda: "pi")
    commands = []
    monkeypatch.setattr(updates.subprocess, "run", _runs(commands, [(0, ""), (0, "ok 0.78.0\n"), (1, "")]))
    updates.apply(True, lambda: None)
    state = _settle()
    assert state["state"] == "failed" and "restoring v0.78.0 failed too" in state["error"]  # and says so when that fails as well


def test_a_failed_install_is_reported_and_nothing_restarts(monkeypatch):
    _release(monkeypatch)
    updates.check_now()
    monkeypatch.setattr(updates, "install_kind", lambda: "pi")

    class Failed:
        returncode, stdout, stderr = 1, "", "Collecting\nERROR: no matching distribution\n"

    monkeypatch.setattr(updates.subprocess, "run", lambda *a, **k: Failed())
    restarted = []
    updates.apply(True, lambda: restarted.append(1))
    deadline = time.time() + 5
    while updates.status(True)["install"]["state"] == "running" and time.time() < deadline:
        time.sleep(0.05)
    state = updates.status(True)["install"]
    assert state["state"] == "failed" and "no matching distribution" in state["error"] and restarted == []


# ---- through the server -------------------------------------------------------------------------------------


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "web_auth.json")
    monkeypatch.setattr(auth, "PBKDF2_ROUNDS", 1000)
    auth.set_password("correct horse")
    srv = server.WebServer(port=0, serve=True, host="127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _call(srv, method, path, cookie=None):
    import http.client
    import json

    connection = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    headers = {"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})}
    connection.request(method, path, body="{}" if method == "POST" else None, headers=headers)
    response = connection.getresponse()
    body = json.loads(response.read().decode() or "null")
    connection.close()
    return response, body


def test_the_update_routes_need_the_password_and_say_what_they_cannot_do(served, monkeypatch):
    assert _call(served, "GET", "/api/update")[0].status == 401
    assert _call(served, "POST", "/api/update/apply")[0].status == 401
    _release(monkeypatch)
    monkeypatch.setattr(updates, "_last_attempt", time.time())  # just looked: a page asking does not trigger another look
    login = _call(served, "POST", "/api/auth/login")  # no password in the body: refused
    assert login[0].status == 401
    cookie = f"tm_auth={auth.make_session()}"
    response, body = _call(served, "GET", "/api/update", cookie)
    assert response.status == 200 and body["newer"] is False and body["current"] == "0.78.0"
    response, body = _call(served, "POST", "/api/update/check", cookie)
    assert body["newer"] is True and body["latest"] == "0.79.0" and body["can_update"] is False  # not a Pi under systemd
    response, body = _call(served, "POST", "/api/update/apply", cookie)
    assert response.status == 409 and body["error"] == "not_supported"


def test_restart_stops_the_server_and_asks_for_the_restart_exit_code(tmp_path, monkeypatch):
    srv = server.WebServer(port=0, serve=True, host="127.0.0.1")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    srv.restart()
    thread.join(5)
    srv.server_close()
    assert srv.restart_requested is True and not thread.is_alive()


def test_main_exits_with_the_restart_code_after_an_update(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "web_auth.json")
    monkeypatch.setattr(auth, "PBKDF2_ROUNDS", 1000)
    auth.set_password("correct horse")
    monkeypatch.setenv("TEETIME_MONITOR_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr(server.WebServer, "serve_forever", lambda self: setattr(self, "restart_requested", True))
    with pytest.raises(SystemExit) as stop:
        server.main(["--serve", "--host", "127.0.0.1", "--port", "0"])
    assert stop.value.code == updates.RESTART_EXIT_CODE == 75


def test_a_page_asking_after_a_long_quiet_spell_makes_the_server_look_again(monkeypatch):
    """The server may have been running for days since its last look: a status request older than an hour
    triggers a new look in the background (once), and a release published meanwhile shows on the next ask."""
    _release(monkeypatch, tag="v0.78.0")
    updates.check_now()  # the look at start-up: nothing newer yet
    assert updates.status()["newer"] is False
    _release(monkeypatch, tag="v0.79.0")  # published later
    base = time.time()
    assert updates.refresh_if_stale(now=base) is True  # never looked "by a page" before: look now
    deadline = time.time() + 5
    while updates.status()["latest"] != "0.79.0" and time.time() < deadline:
        time.sleep(0.05)
    assert updates.status()["newer"] is True
    assert updates.refresh_if_stale(now=base + 60) is False  # asked again a minute later: no second look
    assert updates.refresh_if_stale(now=base + updates.STALE_AFTER_SECONDS + 1) is True  # an hour on: look again


def test_the_stale_look_respects_the_switch_that_turns_the_check_off(monkeypatch):
    monkeypatch.setenv("TEETIME_MONITOR_NO_UPDATE_CHECK", "1")
    assert updates.refresh_if_stale() is False


def test_the_check_button_looks_now_and_says_whether_it_worked(served, monkeypatch):
    cookie = f"tm_auth={auth.make_session()}"
    _release(monkeypatch, tag="v0.79.0")
    response, body = _call(served, "POST", "/api/update/check", cookie)
    assert response.status == 200 and body["check_ok"] is True and body["newer"] is True and body["latest"] == "0.79.0"

    def down(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", down)
    response, body = _call(served, "POST", "/api/update/check", cookie)
    assert response.status == 200 and body["check_ok"] is False and body["newer"] is True  # the old answer stays, the failure is told
    monkeypatch.setenv("TEETIME_MONITOR_NO_UPDATE_CHECK", "1")
    response, body = _call(served, "POST", "/api/update/check", cookie)
    assert body["check_ok"] is False and body["check_disabled"] is True


# ---- automatic updates at night (a Pi server, 2026-10-18) ---------------------------------------------------


class _Server:
    """What auto_due() asks of the running server."""

    def __init__(self, quiet=3600.0, busy=False, serve=True):
        self.serve, self._quiet, self._busy = serve, quiet, busy
        self.refresher = type("R", (), {"busy": lambda _self: self._busy})()

    def quiet_for(self):
        return self._quiet


def _pi_with_release(monkeypatch, tag="v0.79.0"):
    _release(monkeypatch, tag=tag)
    updates.check_now()
    monkeypatch.setattr(updates, "install_kind", lambda: "pi")


def test_the_switch_is_off_until_turned_on_and_is_saved(monkeypatch):
    assert updates.auto_enabled() is False
    assert updates.set_auto(True) == {"ok": True, "auto": True}
    assert user_config.load_value("AUTO_UPDATE", user_config.CONFIG_FILE) == "1" and updates.auto_enabled()
    updates.set_auto(False)
    assert updates.auto_enabled() is False


def test_an_automatic_update_waits_for_the_night_and_a_quiet_server(monkeypatch):
    _pi_with_release(monkeypatch)
    assert not updates.auto_due(_Server(), "03:30")  # switched off
    updates.set_auto(True)
    assert updates.auto_due(_Server(), "03:30")
    assert updates.auto_due(_Server(), "03:00") and not updates.auto_due(_Server(), "05:00")  # 03:00 to before 05:00
    assert not updates.auto_due(_Server(), "14:00") and not updates.auto_due(_Server(), "02:59")
    assert not updates.auto_due(_Server(quiet=60), "03:30")  # something was just done on the page
    assert not updates.auto_due(_Server(busy=True), "03:30")  # a club is being fetched
    assert not updates.auto_due(_Server(serve=False), "03:30")
    monkeypatch.setattr(updates, "install_kind", lambda: "brew")
    assert not updates.auto_due(_Server(), "03:30")  # only a Pi server installs by itself


def test_nothing_newer_means_nothing_to_do_at_night(monkeypatch):
    _pi_with_release(monkeypatch, tag="v0.78.0")
    updates.set_auto(True)
    assert not updates.auto_due(_Server(), "03:30")


def test_an_automatic_update_installs_restarts_and_leaves_a_note_for_the_morning(monkeypatch):
    _pi_with_release(monkeypatch)
    monkeypatch.setattr(updates.time, "sleep", lambda seconds: None)
    commands, restarted = [], threading.Event()
    monkeypatch.setattr(updates.subprocess, "run", _runs(commands, [(0, ""), (0, "ok 0.79.0\n")]))
    updates.apply(True, restarted.set, auto=True)
    assert restarted.wait(5)
    assert updates.status(True)["auto_result"] == {"from": "0.78.0", "to": "0.79.0", "ok": True}
    assert updates.status(False)["auto_result"] is None  # only a served Pi tells
    updates.auto_seen()  # dismissed: gone for every device
    assert updates.status(True)["auto_result"] is None


def test_a_release_that_failed_at_night_is_not_tried_again_by_itself(monkeypatch):
    _pi_with_release(monkeypatch)
    updates.set_auto(True)
    commands = []
    monkeypatch.setattr(updates.subprocess, "run", _runs(commands, [(0, ""), (1, ""), (0, "")]))
    updates.apply(True, lambda: None, auto=True)
    _settle()
    assert updates.status(True)["auto_result"] == {"from": "0.78.0", "to": "0.79.0", "ok": False}
    updates.reset_for_tests()
    _pi_with_release(monkeypatch)
    assert not updates.auto_due(_Server(), "03:30")  # the same release: the button still can, the night does not
    updates.auto_seen()
    assert not updates.auto_due(_Server(), "03:30")  # dismissing the note does not change that
    updates.reset_for_tests()
    _pi_with_release(monkeypatch, tag="v0.79.1")
    assert updates.auto_due(_Server(), "03:30")  # a newer release is tried


def test_an_old_note_is_not_shown_any_more(monkeypatch):
    _pi_with_release(monkeypatch)
    paths.DATA_DIR.mkdir(parents=True)
    (paths.DATA_DIR / updates.MARKER_FILE).write_text('{"from": "0.77.0", "to": "0.78.0", "ok": true, "at": 1}')
    assert updates.status(True)["auto_result"] is None


def test_the_switch_route_works_only_on_a_pi_server(served, monkeypatch):
    cookie = f"tm_auth={auth.make_session()}"
    response, body = _call(served, "POST", "/api/update/auto", cookie)
    assert response.status == 409 and body["error"] == "not_supported"
    monkeypatch.setattr(updates, "install_kind", lambda: "pi")
    _, body = _call(served, "GET", "/api/update", cookie)
    assert body["auto_available"] is True and body["auto"] is False
    import http.client
    import json

    connection = http.client.HTTPConnection("127.0.0.1", served.port, timeout=10)
    connection.request("POST", "/api/update/auto", body=json.dumps({"on": True}), headers={"Content-Type": "application/json", "Cookie": cookie})
    assert json.loads(connection.getresponse().read()) == {"ok": True, "auto": True}
    connection.close()
    assert updates.auto_enabled() is True


def test_a_page_action_makes_the_server_wait_but_its_pings_do_not(served):
    cookie = f"tm_auth={auth.make_session()}"
    served.started -= 3600
    assert served.quiet_for() > 3000
    _call(served, "POST", "/api/ping", cookie)
    assert served.quiet_for() > 3000  # an open page pings all the time: that is not doing anything
    _call(served, "POST", "/api/update/seen", cookie)
    assert served.quiet_for() < 5


def test_the_self_test_starts_the_server_once_and_says_ok(capsys):
    assert server.self_test() == 0
    assert capsys.readouterr().out.strip() == "ok 0.78.0"


def test_a_self_test_that_cannot_start_says_why(monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise OSError("no port")

    monkeypatch.setattr(server.WebServer, "__init__", broken)
    assert server.self_test() == 1
    assert "no port" in capsys.readouterr().err


def test_main_runs_the_self_test_and_exits_with_its_result(monkeypatch):
    monkeypatch.setattr(server, "self_test", lambda: 0)
    with pytest.raises(SystemExit) as stop:
        server.main(["--self-test"])
    assert stop.value.code == 0
