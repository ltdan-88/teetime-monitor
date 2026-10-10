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

from .. import club_config, global_preferences, net, paths, scrape_once
from . import data

STATIC_DIR = Path(__file__).resolve().parent / "static"
COOKIE_NAME = "tm_session"
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
    """Runs scrapes in the background, one per club at a time, and reports their state --
    what the Refresh button and the 'Updating...' indicator poll. A non-forced run honours
    the per-course scrape interval (nothing is fetched while the data is fresh), exactly like
    the terminal app's own timer; a forced one is the Refresh button."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}

    def status(self, slug: str) -> dict:
        with self._lock:
            return dict(self._state.get(slug, {"running": False, "finished_at": None, "error": None}))

    def start(self, slug: str, force: bool) -> dict:
        with self._lock:
            current = self._state.get(slug)
            if current and current["running"]:
                return dict(current)
            self._state[slug] = {"running": True, "finished_at": None, "error": None}
        threading.Thread(target=self._run, args=(slug, force), daemon=True, name=f"refresh-{slug}").start()
        return self.status(slug)

    def _run(self, slug: str, force: bool) -> None:
        error = None
        try:
            config = club_config.load_club_config(slug)
            scrape_once.scrape_due_for_club(slug, config, force=force, source="gui")
        except Exception as exc:  # noqa: BLE001 -- surfaced to the page, never fatal
            error = f"{type(exc).__name__}: {exc}"
            print(f"[webui] refresh of {slug} failed: {error}", file=sys.stderr)
        with self._lock:
            self._state[slug] = {"running": False, "finished_at": time.time(), "error": error}


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind() asks for this machine's fully qualified name (a DNS lookup that
        # can take half a minute behind a corporate resolver) only to fill in a name nothing reads.
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]

    def __init__(self, port: int = 0, token: str | None = None, keep_running: bool = False) -> None:
        super().__init__(("127.0.0.1", port), Handler)
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

    def should_exit(self) -> bool:
        if self.keep_running:
            return False
        limit = IDLE_EXIT_WITHOUT_ANY_PING_SECONDS if self.last_ping is None else IDLE_EXIT_AFTER_FIRST_PING_SECONDS
        return self.idle_for() > limit


class Handler(BaseHTTPRequestHandler):
    server: WebServer
    server_version = "teetime-monitor-web"
    sys_version = ""

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
        return self.headers.get("Host", "") in self.server.allowed_hosts()

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in self.server.allowed_origins()

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
        def arg(name: str) -> str | None:
            return query.get(name, [None])[0]

        if method == "GET" and path == "/api/bootstrap":
            return self._json(data.bootstrap())
        if method == "GET" and path == "/api/overview":
            slug = arg("slug")
            if not slug:
                return self._json({"error": "missing_slug"}, HTTPStatus.BAD_REQUEST)
            result = data.overview(slug, arg("course"))
            return self._json(result, HTTPStatus.NOT_FOUND if result.get("error") else 200)
        if method == "GET" and path == "/api/refresh/status":
            return self._json(self.server.refresher.status(arg("slug") or ""))
        if method == "POST" and path == "/api/refresh":
            body = self._read_json()
            slug = body.get("slug")
            if not isinstance(slug, str) or data.club_by_slug(slug) is None:
                return self._json({"error": "unknown_club"}, HTTPStatus.NOT_FOUND)
            return self._json(self.server.refresher.start(slug, force=bool(body.get("force"))))
        if method == "POST" and path == "/api/last":
            body = self._read_json()
            club = data.club_by_slug(str(body.get("slug", "")))
            course = body.get("course")
            if club is None or not isinstance(course, str) or not course:
                return self._json({"error": "bad_request"}, HTTPStatus.BAD_REQUEST)
            global_preferences.save_last_active_club(club["id"], club["slug"], course)
            return self._json({"ok": True})
        if method == "POST" and path == "/api/ping":
            self.server.last_ping = time.monotonic()
            return self._json({"ok": True})
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="teetime-monitor-web", description="Teetime Monitor in a browser window.")
    parser.add_argument("--port", type=int, default=0, help="port to listen on (default: a free one)")
    parser.add_argument("--no-browser", action="store_true", help="only print the link, do not open a window")
    parser.add_argument("--keep-running", action="store_true", help="do not stop when the window is closed")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    args = parser.parse_args(argv)
    if args.version:
        print(f"teetime-monitor {data.version()}")
        return
    paths.force_utf8_stdio()
    net.use_system_trust_store()
    if paths.needs_migration():
        paths.migrate_from()
    paths.ensure_dirs()
    server = WebServer(port=args.port, keep_running=args.keep_running)
    print(f"Teetime Monitor {data.version()} is running. If no window opened, open this link:\n\n  {server.url}\n", flush=True)
    print("Close the window to stop it, or press Ctrl+C here." if not args.keep_running else "Press Ctrl+C to stop it.", flush=True)
    if not args.no_browser:
        open_window(server.url)
    threading.Thread(target=_watch_idle, args=(server,), daemon=True, name="idle-watch").start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
