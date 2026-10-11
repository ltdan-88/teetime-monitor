"""`teetime-monitor-web`: the local web UI's server (2026-10-10).

A small HTTP server from the standard library, bound to 127.0.0.1 only, that serves the
page in `static/` and the JSON behind it (`data.py`). It exists so Windows and Linux --
where the Mac app does not run -- get the same Overview in a browser window, and it adds no
dependency: the page is plain HTML/CSS/JS with a vendored Preact (see static/vendor/).

Security (your pc caddie login sits behind this):
- It listens on the loopback address only, never on the network, on a random port.
- Every request needs the random session token, handed over once in the URL the program
  prints/opens (`/?t=...`), which sets an HttpOnly, SameSite=Strict cookie and redirects to a
  clean URL. Other programs on this PC, and other web pages in your browser, do not have it.
- The Host header must name this server (DNS-rebinding protection), and a request that
  carries an Origin must come from this same origin.
- A strict Content-Security-Policy: the page loads nothing from anywhere else.

`--serve` (2026-10-11) turns it into a home-network server, for a Raspberry Pi: it listens on the
network, keeps running, scrapes on its own schedule, and every request needs a password (auth.py)
instead of the one-time link. Everything else above (Origin check, CSP) still applies; the Host
header is not checked there, since the Pi is reached by name or address and a rebinding page cannot
get the password cookie anyway.

Lifecycle: the page pings `/api/ping` every few seconds; once it has been seen and then stays
silent (the window was closed) the server exits, so a friend closing the browser window does
not leave a program running. `--keep-running` turns that off. Ctrl+C always works.
"""

import argparse
import hmac
import json
import mimetypes
import secrets
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .. import club_config, global_preferences, i18n, net, paths, scrape_once
from . import auth, clubs_api, data, settings_api, tools_api, updates

STATIC_DIR = Path(__file__).resolve().parent / "static"
COOKIE_NAME = "tm_session"
AUTH_COOKIE_NAME = "tm_auth"
DEFAULT_SERVE_PORT = 8765
SCRAPE_CHECK_SECONDS = 300  # how often the server looks for a club that is due (the clubs' own intervals decide)
# Reachable without logging in: the login page and what it needs.
PUBLIC_PAGES = {"/login": "login.html", "/login.js": "login.js", "/style.css": "style.css"}
PING_INTERVAL_HINT_SECONDS = 5
IDLE_EXIT_AFTER_FIRST_PING_SECONDS = 120  # background tabs throttle timers to about one a minute
IDLE_EXIT_WITHOUT_ANY_PING_SECONDS = 600  # the window never opened, or was closed at once

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")


class Refresher:
    """Runs scrapes in the background, one per key at a time, and reports their state -- what the
    Refresh button and the 'Updating...' indicator poll. The key is a saved club's slug, or
    `club:<id>` for a club that is only being looked at. A non-forced run honours the per-course
    scrape interval (nothing is fetched while the data is fresh), exactly like the terminal app's
    own timer; a forced one is the Refresh button."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}

    def status(self, key: str) -> dict:
        with self._lock:
            return dict(self._state.get(key, {"running": False, "finished_at": None, "error": None, "result": None}))

    def start(self, key: str, work) -> dict:
        """Run `work()` in a thread unless this key is already running. A dict it returns with
        `ok: False` (a club preview's rejection) is reported as the error."""
        with self._lock:
            current = self._state.get(key)
            if current and current["running"]:
                return dict(current)
            self._state[key] = {"running": True, "finished_at": None, "error": None, "result": None}
        threading.Thread(target=self._run, args=(key, work), daemon=True, name=f"refresh-{key}").start()
        return self.status(key)

    def _run(self, key: str, work) -> None:
        error, result = None, None
        try:
            result = work()
            if isinstance(result, dict) and result.get("ok") is False:
                error = result.get("reason", "failed")
        except Exception as exc:  # noqa: BLE001 -- surfaced to the page, never fatal
            error = f"{type(exc).__name__}: {exc}"
            print(f"[webui] refresh of {key} failed: {error}", file=sys.stderr)
        with self._lock:
            self._state[key] = {"running": False, "finished_at": time.time(), "error": error, "result": result}


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # A page load opens a dozen connections at once (the modules, the strings, the bootstrap). The default
    # backlog of 5 dropped one of them now and then, and a page missing one module stays blank.
    request_queue_size = 128

    def server_bind(self) -> None:
        # HTTPServer.server_bind() asks for this machine's fully qualified name (a DNS lookup that
        # can take half a minute behind a corporate resolver) only to fill in a name nothing reads.
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]

    def __init__(
        self, port: int = 0, token: str | None = None, keep_running: bool = False, serve: bool = False, host: str | None = None
    ) -> None:
        # Local: loopback only, on a random port. Served: the network (or the one interface `host` names).
        super().__init__((host or ("0.0.0.0" if serve else "127.0.0.1"), port), Handler)  # noqa: S104 -- the point of --serve
        self.serve = serve
        self.restart_requested = False
        self.login_throttle = auth.LoginThrottle()
        self.token = token or secrets.token_urlsafe(24)
        self.port = self.server_address[1]
        self.keep_running = keep_running
        self.refresher = Refresher()
        self.started = time.monotonic()
        self.last_ping: float | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def allowed_origins(self) -> set[str]:
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    def idle_for(self) -> float:
        """Seconds since the page was last heard from, once it has been; else None-like."""
        reference = self.last_ping if self.last_ping is not None else self.started
        return time.monotonic() - reference

    def restart(self) -> None:
        """Stop serving and let `main()` exit with the restart code: systemd starts the program again, now
        the newer version (`updates.apply()` has just installed it)."""
        self.restart_requested = True
        self.shutdown()

    def should_exit(self) -> bool:
        if self.keep_running or self.serve:
            return False
        limit = IDLE_EXIT_WITHOUT_ANY_PING_SECONDS if self.last_ping is None else IDLE_EXIT_AFTER_FIRST_PING_SECONDS
        return self.idle_for() > limit


class Handler(BaseHTTPRequestHandler):
    server: WebServer
    server_version = "teetime-monitor-web"
    sys_version = ""
    timeout = 60  # a connection that goes quiet does not hold a thread for ever

    def log_message(self, format: str, *args) -> None:  # noqa: A002 -- BaseHTTPRequestHandler's signature
        pass  # one line per request would bury the one URL the terminal has to show

    # ---- plumbing ---------------------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _text(self, status: int, message: str) -> None:
        page = (
            "<!doctype html><meta charset=utf-8><title>Teetime Monitor</title>"
            "<body style='font:16px system-ui;margin:3rem;max-width:34rem'>"
            f"<h1 style='font-size:1.3rem'>Teetime Monitor</h1><p>{message}</p>"
        )
        self._send(status, page.encode("utf-8"), "text/html; charset=utf-8", {"Cache-Control": "no-store"})

    def _cookie_ok(self) -> bool:
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME and hmac.compare_digest(value.encode(), self.server.token.encode()):
                return True
        return False

    def _host_ok(self) -> bool:
        if self.server.serve:
            return bool(self.headers.get("Host"))
        return self.headers.get("Host", "") in self.server.allowed_hosts()

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        if self.server.serve:  # whatever name the Pi is reached by, a page may only call the server it came from
            return urlsplit(origin).netloc == self.headers.get("Host")
        return origin in self.server.allowed_origins()

    def _cookie(self, name: str) -> str:
        for part in self.headers.get("Cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return ""

    def _logged_in(self) -> bool:
        return auth.valid_session(self._cookie(AUTH_COOKIE_NAME))

    def _client(self) -> str:
        return self.client_address[0]

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1_000_000:
            return {}
        try:
            parsed = json.loads(self.rfile.read(length))
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    # ---- routing ----------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        try:
            if not self._host_ok():
                return self._text(HTTPStatus.FORBIDDEN, "This address is not allowed.")
            if not self._origin_ok():
                return self._text(HTTPStatus.FORBIDDEN, "Cross-site request refused.")
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            if self.server.serve:
                return self._dispatch_served(method, url, query)
            # The one unauthenticated door: the URL with the token, once, to set the cookie.
            if method == "GET" and url.path == "/" and "t" in query:
                if hmac.compare_digest(query["t"][0].encode(), self.server.token.encode()):
                    cookie = f"{COOKIE_NAME}={self.server.token}; Path=/; HttpOnly; SameSite=Strict"
                    return self._send(HTTPStatus.FOUND, b"", "text/plain", {"Location": "/", "Set-Cookie": cookie, "Cache-Control": "no-store"})
                return self._text(HTTPStatus.FORBIDDEN, "That link is not valid any more. Open the one printed in the terminal.")
            if not self._cookie_ok():
                return self._text(
                    HTTPStatus.FORBIDDEN,
                    "Open Teetime Monitor with the link it printed in the terminal (or start it again).",
                )
            if url.path.startswith("/api/"):
                return self._api(method, url.path, query)
            if method != "GET":
                return self._text(HTTPStatus.METHOD_NOT_ALLOWED, "Not allowed.")
            return self._static(url.path)
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception:  # noqa: BLE001 -- a handler bug must not take the server down
            traceback.print_exc()
            try:
                self._json({"error": "internal"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            except OSError:
                pass
            return None

    def _dispatch_served(self, method: str, url, query: dict[str, list[str]]) -> None:
        """`--serve`: the login page and its own files are open; everything else needs the password cookie."""
        if method == "POST" and url.path == "/api/auth/login":
            return self._login()
        if method == "GET" and url.path in PUBLIC_PAGES:
            if url.path == "/login" and self._logged_in():
                return self._redirect("/")
            return self._static("/" + PUBLIC_PAGES[url.path])
        if not self._logged_in():
            if url.path.startswith("/api/"):
                return self._json({"error": "auth"}, HTTPStatus.UNAUTHORIZED)
            return self._redirect("/login")
        if method == "POST" and url.path == "/api/auth/logout":
            return self._send(
                HTTPStatus.OK, b"{}", "application/json", {"Set-Cookie": f"{AUTH_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"}
            )
        if method == "POST" and url.path == "/api/auth/password":
            return self._change_password()
        if url.path.startswith("/api/"):
            return self._api(method, url.path, query)
        if method != "GET":
            return self._text(HTTPStatus.METHOD_NOT_ALLOWED, "Not allowed.")
        return self._static(url.path)

    def _redirect(self, location: str) -> None:
        self._send(HTTPStatus.FOUND, b"", "text/plain", {"Location": location, "Cache-Control": "no-store"})

    def _change_password(self) -> None:
        """Settings > Server password: the current password again (a left-open browser must not be able to
        lock you out), then the new one. Everyone else is logged out (the session secret changes with the
        password); this browser gets a fresh cookie and stays in. Wrong "current" guesses count towards
        the same lockout as wrong logins."""
        address = self._client()
        wait = self.server.login_throttle.retry_after(address)
        if wait:
            return self._json({"error": "too_many", "retry_after": wait}, HTTPStatus.TOO_MANY_REQUESTS)
        body = self._read_json()
        current, new = body.get("current"), body.get("new")
        if not (isinstance(current, str) and auth.check_password(current)):
            self.server.login_throttle.miss(address)
            return self._json({"error": "bad_password"}, HTTPStatus.UNAUTHORIZED)
        self.server.login_throttle.success(address)
        try:
            auth.set_password(new if isinstance(new, str) else "")
        except ValueError:
            return self._json({"error": "too_short", "min": auth.MIN_PASSWORD_LENGTH}, HTTPStatus.BAD_REQUEST)
        cookie = f"{AUTH_COOKIE_NAME}={auth.make_session()}; Path=/; HttpOnly; SameSite=Lax; Max-Age={auth.SESSION_SECONDS}"
        self._send(HTTPStatus.OK, b'{"ok":true}', "application/json", {"Set-Cookie": cookie, "Cache-Control": "no-store"})

    def _login(self) -> None:
        address = self._client()
        wait = self.server.login_throttle.retry_after(address)
        if wait:
            return self._json({"error": "too_many", "retry_after": wait}, HTTPStatus.TOO_MANY_REQUESTS)
        password = self._read_json().get("password")
        if isinstance(password, str) and auth.check_password(password):
            self.server.login_throttle.success(address)
            value = auth.make_session()
            cookie = f"{AUTH_COOKIE_NAME}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={auth.SESSION_SECONDS}"
            return self._send(HTTPStatus.OK, b'{"ok":true}', "application/json", {"Set-Cookie": cookie, "Cache-Control": "no-store"})
        self.server.login_throttle.miss(address)
        return self._json({"error": "bad_password"}, HTTPStatus.UNAUTHORIZED)

    def _static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents or not target.is_file():
            return self._text(HTTPStatus.NOT_FOUND, "Not found.")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/json", "image/svg+xml"):
            content_type += "; charset=utf-8"
        self._send(HTTPStatus.OK, target.read_bytes(), content_type, {"Cache-Control": "no-cache"})

    def _api(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        body = self._read_json() if method == "POST" else {}

        def arg(name: str) -> str | None:
            if name in body and isinstance(body[name], str):
                return body[name]
            return query.get(name, [None])[0]

        def ref() -> dict:
            """Which club a request is about: a saved club's slug, or the id (and name) of one that is
            only open for a look."""
            return {"slug": arg("slug") or None, "club_id": arg("club_id") or None}

        def reply(result: dict, error_status: int = HTTPStatus.NOT_FOUND) -> None:
            return self._json(result, error_status if result.get("error") else 200)

        route = (method, path)
        if route == ("GET", "/api/bootstrap"):
            return self._json({**data.bootstrap(), "serve": self.server.serve})
        if route == ("GET", "/api/strings"):
            return self._json({"language": i18n.get_language(), "strings": i18n._STRINGS.get(i18n.get_language(), {})})
        if route == ("GET", "/api/overview"):
            if not (arg("slug") or arg("club_id")):
                return self._json({"error": "missing_club"}, HTTPStatus.BAD_REQUEST)
            return reply(data.overview(arg("slug"), arg("course"), arg("club_id"), arg("name"), picks=arg("picks") != "0"))
        if route == ("GET", "/api/refresh/status"):
            return self._json(self.server.refresher.status(arg("key") or ""))
        if route == ("POST", "/api/refresh"):
            club = data.resolve_club(arg("slug"), arg("club_id"), arg("name"))
            if club is None:
                return self._json({"error": "unknown_club"}, HTTPStatus.NOT_FOUND)
            if club["slug"] is not None:
                slug, force = club["slug"], bool(body.get("force"))

                def work(slug=slug, force=force):
                    scrape_once.scrape_due_for_club(slug, club_config.load_club_config(slug), force=force, source="gui")

                return self._json(self.server.refresher.start(slug, work))
            club_id, name = club["id"], club["name"]
            return self._json(self.server.refresher.start(f"club:{club_id}", lambda: clubs_api.preview(club_id, name)))
        if route == ("POST", "/api/last"):
            club = data.club_by_slug(str(body.get("slug", "")))
            course = body.get("course")
            if club is None or not isinstance(course, str) or not course:
                return self._json({"error": "bad_request"}, HTTPStatus.BAD_REQUEST)
            global_preferences.save_last_active_club(club["id"], club["slug"], course)
            return self._json({"ok": True})
        if route == ("GET", "/api/update"):
            updates.refresh_if_stale()
            return self._json(updates.status(serving=self.server.serve))
        if route == ("POST", "/api/update/check"):
            looked = updates.check_now() is not None  # the "Check for updates" button: look now, and say if it worked
            return self._json({**updates.status(serving=self.server.serve), "check_ok": looked})
        if route == ("POST", "/api/update/apply"):
            return reply(updates.apply(self.server.serve, self.server.restart), HTTPStatus.CONFLICT)
        if route == ("POST", "/api/ping"):
            self.server.last_ping = time.monotonic()
            return self._json({"ok": True})

        # bookings and notices
        if route == ("POST", "/api/booking"):
            return reply(data.confirm_booking(**ref(), course=arg("course") or "", date=arg("date") or "", time=arg("time") or ""))
        if route == ("POST", "/api/booking/cancel"):
            return reply(data.cancel_booking(**ref(), course=arg("course") or "", date=arg("date") or ""))
        if route == ("POST", "/api/banners/ack"):
            ids = body.get("ids") if isinstance(body.get("ids"), list) else []
            return reply(data.acknowledge_banners(**ref(), ids=ids))

        # settings, preferences, account
        if route == ("GET", "/api/settings"):
            return self._json(settings_api.settings_payload(arg("club_id")))
        if route == ("GET", "/api/preferences"):
            return self._json(settings_api.schema("preferences", arg("club_id")))
        if route in (("POST", "/api/settings"), ("POST", "/api/preferences")):
            kind = "settings" if path.endswith("settings") else "preferences"
            values = body.get("values") if isinstance(body.get("values"), dict) else {}
            return reply(settings_api.save(kind, values), HTTPStatus.BAD_REQUEST)
        if route == ("POST", "/api/theme"):
            return reply(settings_api.set_theme(arg("name") or ""), HTTPStatus.BAD_REQUEST)
        if route == ("POST", "/api/login"):
            return self._json(settings_api.login(arg("username") or "", body.get("password") or "", arg("club_id")))
        if route == ("POST", "/api/ai-key"):
            return self._json(settings_api.ai_key(arg("provider") or "", body.get("api_key") or ""))
        if route == ("POST", "/api/club/default-course"):
            return reply(settings_api.set_default_course(arg("slug") or "", arg("course") or ""))
        if route == ("POST", "/api/club/holes"):
            holes = body.get("holes")
            return reply(settings_api.set_course_holes(arg("slug") or "", arg("course") or "", holes if isinstance(holes, int) else None))
        if route == ("POST", "/api/club/add"):
            return reply(clubs_api.add(arg("club_id") or "", arg("name") or ""), HTTPStatus.BAD_REQUEST)
        if route == ("POST", "/api/club/remove"):
            return reply(clubs_api.remove(arg("club_id") or ""))
        if route == ("GET", "/api/directory"):
            return self._json(clubs_api.search(arg("q") or ""))
        if route == ("POST", "/api/directory/refresh"):
            return self._json(clubs_api.refresh_directory())

        # search, heatmap, players
        if route == ("GET", "/api/search/defaults"):
            return reply(tools_api.search_defaults(**ref()))
        if route == ("POST", "/api/search"):
            criteria = body.get("criteria") if isinstance(body.get("criteria"), dict) else {}
            return reply(tools_api.run_search(**ref(), course=arg("course") or "", criteria=criteria, ai=body.get("ai") is not False))
        if route == ("GET", "/api/heatmap"):
            return reply(tools_api.heatmap(**ref(), course=arg("course")))
        if route == ("GET", "/api/players"):
            return reply(tools_api.players(**ref()))
        if route == ("POST", "/api/players/friend"):
            return reply(tools_api.set_friend(**ref(), name=arg("name") or "", is_friend=bool(body.get("friend"))))
        return self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)


# ---- starting it ---------------------------------------------------------------------------


def _app_window_command(url: str) -> list[str] | None:
    """A browser command that opens `url` as a plain app window (no tabs, no address bar), if
    Edge or Chrome is installed; otherwise None and the default browser is used. Edge ships with
    every Windows 10/11, which is why this matters most there."""
    candidates: list[str] = []
    if sys.platform == "win32":
        import os  # noqa: PLC0415

        for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LocalAppData")):
            if root:
                candidates.append(str(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
                candidates.append(str(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    else:
        for name in ("microsoft-edge", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
    for exe in candidates:
        if Path(exe).is_file():
            return [exe, f"--app={url}"]
    return None


def open_window(url: str) -> None:
    command = _app_window_command(url)
    if command is not None:
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
            return
        except OSError:
            pass
    webbrowser.open(url)


def _watch_idle(server: WebServer) -> None:
    while True:
        time.sleep(PING_INTERVAL_HINT_SECONDS)
        if server.should_exit():
            print("The window was closed; Teetime Monitor is stopping.")
            server.shutdown()
            return


def _scrape_pass(server: WebServer) -> None:
    """One look at every saved club: `scrape_due_for_club()` fetches only what its own scrape intervals say
    is due (and takes the day's backup), so most passes do nothing. Goes through the same `Refresher` as the
    Refresh button, so the two never scrape one club at once and the page shows the update running."""
    for slug in club_config.list_clubs():
        try:
            config = club_config.load_club_config(slug)
        except Exception:  # noqa: BLE001 -- one broken club file must not stop the others
            traceback.print_exc()
            continue

        def work(slug=slug, config=config):
            scrape_once.scrape_due_for_club(slug, config, force=False, source="agent")

        server.refresher.start(slug, work)


def _schedule_scrapes(server: WebServer) -> None:
    """`--serve`: what the launchd agent / scheduled task does on a computer, in the server itself."""
    time.sleep(10)  # let the server come up first
    while True:
        _scrape_pass(server)
        time.sleep(SCRAPE_CHECK_SECONDS)


def _addresses(port: int) -> list[str]:
    """The ways to reach this server from another device: its name (`raspberrypi.local` with mDNS) and
    the addresses of this machine's network interfaces."""
    import socket  # noqa: PLC0415

    found = [f"http://{socket.gethostname()}.local:{port}" if "." not in socket.gethostname() else f"http://{socket.gethostname()}:{port}"]
    try:  # the address the machine would use to reach the local network: no packet is sent
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("10.255.255.255", 1))
        found.append(f"http://{probe.getsockname()[0]}:{port}")
        probe.close()
    except OSError:
        pass
    return found


def _ask_password(from_stdin: bool) -> str | None:
    import getpass  # noqa: PLC0415

    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass(f"New password for the web UI (at least {auth.MIN_PASSWORD_LENGTH} characters): ")
    if getpass.getpass("Once more: ") != first:
        print("The two entries differ; nothing was changed.")
        return None
    return first


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="teetime-monitor-web", description="Teetime Monitor in a browser window.")
    parser.add_argument("--port", type=int, default=None, help=f"port to listen on (default: a free one; {DEFAULT_SERVE_PORT} with --serve)")
    parser.add_argument("--no-browser", action="store_true", help="only print the link, do not open a window")
    parser.add_argument("--keep-running", action="store_true", help="do not stop when the window is closed")
    parser.add_argument("--serve", action="store_true", help="run as a server for the whole home network (password, runs until stopped, scrapes on its own)")
    parser.add_argument("--host", default=None, help="with --serve: the address to listen on (default: every interface)")
    parser.add_argument("--set-password", action="store_true", help="set (or change) the password for --serve, then exit")
    parser.add_argument("--password-stdin", action="store_true", help="with --set-password: read the password from one line of standard input")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    args = parser.parse_args(argv)
    if args.version:
        print(f"teetime-monitor {data.version()}")
        return
    paths.force_utf8_stdio()
    if args.set_password:
        paths.ensure_dirs()
        password = _ask_password(args.password_stdin)
        if password is None:
            sys.exit(1)
        try:
            auth.set_password(password)
        except ValueError as error:
            print(error)
            sys.exit(1)
        print("The password is set. Everyone who was logged in has to log in again.")
        return
    net.use_system_trust_store()
    if paths.needs_migration():
        paths.migrate_from()
    paths.ensure_dirs()
    if args.serve and not auth.is_configured():
        print("No password set yet. Set one first:\n\n  teetime-monitor-web --set-password\n")
        sys.exit(2)
    port = args.port if args.port is not None else (DEFAULT_SERVE_PORT if args.serve else 0)
    server = WebServer(port=port, keep_running=args.keep_running, serve=args.serve, host=args.host)
    threading.Thread(target=settings_api._screen, daemon=True, name="warm-up").start()
    if args.serve:
        print(f"Teetime Monitor {data.version()} is serving on port {server.port}. Open it from any device on this network:\n", flush=True)
        for address in _addresses(server.port):
            print(f"  {address}", flush=True)
        print("\nLog in with the password you set. Press Ctrl+C to stop it.", flush=True)
        threading.Thread(target=_schedule_scrapes, args=(server,), daemon=True, name="scrape-schedule").start()
    else:
        print(f"Teetime Monitor {data.version()} is running. If no window opened, open this link:\n\n  {server.url}\n", flush=True)
        print("Close the window to stop it, or press Ctrl+C here." if not args.keep_running else "Press Ctrl+C to stop it.", flush=True)
        if not args.no_browser:
            open_window(server.url)
        threading.Thread(target=_watch_idle, args=(server,), daemon=True, name="idle-watch").start()
    if not updates.disabled():
        threading.Thread(target=updates.watch, daemon=True, name="update-check").start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()
    if server.restart_requested:
        print("Restarting into the new version.", flush=True)
        sys.exit(updates.RESTART_EXIT_CODE)


if __name__ == "__main__":
    main()
