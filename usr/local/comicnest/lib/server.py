"""HTTP transport for ComicNest.

The packaged service listens on a Unix socket because that is what the TOS
proxy expects. A loopback TCP mode exists for development on machines without
``AF_UNIX``.
"""

import json
import os
import signal
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, api as api_module, db, scanner
from .auth import cors_headers
from .config import config
from .errors import BadRequest, PayloadTooLarge
from .http_util import FileResponse, Response, error_response, guess_type, parse_range, static_path
from .logging_setup import get_logger, setup_logging

log = get_logger("server")

_WEBUI = config.webui_dir
_MAX_BODY = 8 * 1024 * 1024
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ComicNest/" + __version__

    def do_OPTIONS(self):
        self._dispatch("OPTIONS")

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    # ------------------------------------------------------------------ plumbing

    def log_message(self, format, *args):
        log.debug("%s - %s", self.address_string(), format % args)

    def _read_body(self):
        raw = self.headers.get("Content-Length")
        if raw is None:
            return b""
        try:
            length = int(raw)
        except ValueError:
            raise BadRequest("invalid Content-Length")
        if length < 0 or length > _MAX_BODY:
            raise PayloadTooLarge("the request body is too large")
        return self.rfile.read(length) if length else b""

    def _dispatch(self, method):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path or "/"
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        try:
            if path == "/api" or path.startswith("/api/") or "/v2/proxy/" in path or path.startswith("/%s/" % config.app_id):
                body = self._read_body() if method in ("POST", "PUT", "PATCH") else b""
                result = api_module.api.dispatch(
                    method if method != "HEAD" else "GET", self.path, query, self.headers, body
                )
                self._send(result, head_only=(method == "HEAD"))
                return
            if method in ("GET", "HEAD"):
                self._serve_static(method == "HEAD")
                return
            self._send(
                Response(405, b"method not allowed", {"Content-Type": "text/plain; charset=utf-8"}),
                head_only=False,
            )
        except (BadRequest, PayloadTooLarge) as exc:
            self._send(error_response(exc), head_only=(method == "HEAD"))
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception:  # noqa: BLE001
            log.exception("request failed: %s %s", method, self.path)
            try:
                self._send(
                    Response(500, b"internal error", {"Content-Type": "text/plain; charset=utf-8"}),
                    head_only=(method == "HEAD"),
                )
            except OSError:
                pass

    # -------------------------------------------------------------------- static

    def _serve_static(self, head_only):
        canonical = api_module.normalize_path(self.path)
        if canonical == "/":
            relative = "index.html"
        else:
            relative = canonical.lstrip("/")
        path = static_path(_WEBUI, relative)
        if not path or not os.path.isfile(path):
            if canonical != "/" and not os.path.splitext(canonical)[1]:
                path = os.path.join(_WEBUI, "index.html")
            else:
                path = None
        if not path or not os.path.isfile(path):
            self._send(
                Response(404, b"not found", {"Content-Type": "text/plain; charset=utf-8"}),
                head_only=head_only,
            )
            return
        extension = os.path.splitext(path)[1].lower()
        content_type = _STATIC_TYPES.get(extension) or guess_type(path)
        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            self._send(
                Response(500, b"cannot read asset", {"Content-Type": "text/plain; charset=utf-8"}),
                head_only=head_only,
            )
            return
        headers = {
            "Content-Type": content_type,
            "Cache-Control": "no-cache" if extension in (".html", ".js", ".css", ".mjs") else "public, max-age=86400",
        }
        self._send(Response(200, body, headers), head_only=head_only)

    # ----------------------------------------------------------------- responses

    def _send(self, result, head_only=False):
        if isinstance(result, FileResponse):
            self._send_file(result, head_only)
            return
        if not isinstance(result, Response):
            result = Response(500, b"internal error", {"Content-Type": "text/plain; charset=utf-8"})
        body = result.body if not head_only else b""
        self.send_response(result.status)
        for key, value in result.headers.items():
            self.send_header(key, value)
        for key, value in cors_headers().items():
            self.send_header(key, value)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Length", str(result.length))
        if not result.headers.get("Cache-Control") and result.headers.get("Content-Type", "").startswith("application/json"):
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _send_file(self, result, head_only=False):
        path = result.path
        try:
            stat = os.stat(path)
        except OSError:
            self._send(
                Response(404, b"file not found", {"Content-Type": "text/plain; charset=utf-8"}),
                head_only=head_only,
            )
            return
        size = stat.st_size
        etag = '"%x-%x"' % (size, int(stat.st_mtime))
        if (self.headers.get("If-None-Match") or "") == etag:
            self.send_response(304)
            for key, value in cors_headers().items():
                self.send_header(key, value)
            self.send_header("ETag", etag)
            self.end_headers()
            return

        byte_range = parse_range(self.headers.get("Range"), size)
        status = 206 if byte_range else 200
        start, end = byte_range if byte_range else (0, max(0, size - 1))
        length = max(0, end - start + 1) if size else 0

        self.send_response(status)
        self.send_header("Content-Type", result.content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", result.cache_control)
        if byte_range:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        for key, value in cors_headers().items():
            self.send_header(key, value)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if head_only or not length:
            return
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


if hasattr(socketserver, "UnixStreamServer"):
    class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

        def get_request(self):
            request, _address = super().get_request()
            return request, ("unix", 0)
else:  # pragma: no cover - Windows development builds
    UnixHTTPServer = None


def _prepare():
    setup_logging(config.log_level, config.log_dir, config.log_to_file)
    config.ensure_directories()
    db.initialise()
    scanner.ensure_default_source()


def _start_scan():
    if config.scan_on_start:
        scanner.manager.start(None)


def serve_forever():
    _prepare()
    _start_scan()
    if config.dev_tcp:
        port = int(config.dev_tcp)
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        server.daemon_threads = True
        log.info("ComicNest %s listening on http://127.0.0.1:%d", __version__, port)
        _install_signals(server, "tcp")
        server.serve_forever(poll_interval=0.5)
        return

    if UnixHTTPServer is None:
        raise SystemExit("this Python build has no AF_UNIX support; use --dev for TCP")
    path = config.socket_path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.settimeout(0.3)
            probe.connect(path)
            probe.close()
            raise SystemExit("another ComicNest instance is already listening on %s" % path)
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            try:
                os.remove(path)
            except OSError:
                pass
    server = UnixHTTPServer(path, Handler)
    server.server_name = config.app_id
    server.server_port = 0
    try:
        os.chmod(path, config.socket_mode)
    except OSError:
        pass
    log.info("ComicNest %s listening on %s", __version__, path)
    _install_signals(server, path)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _install_signals(server, path):
    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    try:
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
    except (ValueError, OSError):
        pass


def check_environment():
    _prepare()
    problems = []
    if not os.path.isdir(_WEBUI):
        problems.append("webui directory is missing: %s" % _WEBUI)
    try:
        db.stats()
    except Exception as exc:  # noqa: BLE001
        problems.append("database is not usable: %s" % exc)
    info = {
        "version": __version__,
        "root": config.app_root,
        "webui": _WEBUI,
        "share_root": config.share_root(),
        "library_root": config.library_root(),
        "socket": config.socket_path,
        "problems": problems,
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0 if not problems else 1
