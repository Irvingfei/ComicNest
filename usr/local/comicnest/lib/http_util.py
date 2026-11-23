"""Small HTTP response primitives shared by the API and the server."""

import json
import mimetypes
import os

from .errors import ComicNestError

mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("image/avif", ".avif")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/woff2", ".woff2")


class Response:
    status = 200

    def __init__(self, status=200, body=b"", headers=None, content_type=None):
        self.status = int(status)
        self.body = body
        self.headers = dict(headers or {})
        if content_type:
            self.headers.setdefault("Content-Type", content_type)

    @property
    def length(self):
        return len(self.body)


class JsonResponse(Response):
    def __init__(self, data, status=200, headers=None):
        payload = json.dumps(
            {"code": 0, "message": "ok", "data": data}, ensure_ascii=False
        ).encode("utf-8")
        super().__init__(status, payload, headers, "application/json; charset=utf-8")


class ErrorResponse(Response):
    def __init__(self, error):
        payload = json.dumps(error.to_payload(), ensure_ascii=False).encode("utf-8")
        super().__init__(
            error.status, payload, None, "application/json; charset=utf-8"
        )


class FileResponse:
    """A file served with conditional and range support (used for PDFs)."""

    status = 200

    def __init__(self, path, content_type=None, cache_control="private, max-age=3600"):
        self.path = path
        self.content_type = content_type or "application/octet-stream"
        self.cache_control = cache_control


def error_response(exc):
    return ErrorResponse(exc)


def internal_error():
    return ErrorResponse(ComicNestError())


def parse_range(value, size):
    """Return ``(start, end)`` for a single byte range, or ``None``."""
    if not value or not value.startswith("bytes=") or size <= 0:
        return None
    spec = value[6:].split(",")[0].strip()
    if "-" not in spec:
        return None
    first, _, last = spec.partition("-")
    try:
        if first:
            start = int(first)
            end = int(last) if last else size - 1
        else:
            length = int(last)
            if length <= 0:
                return None
            start = max(0, size - length)
            end = size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return None
    return start, min(end, size - 1)


def guess_type(path):
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def static_path(root, request_path):
    """Resolve a request path under ``root``, refusing traversal."""
    relative = request_path.lstrip("/")
    candidate = os.path.realpath(os.path.join(root, relative))
    root_real = os.path.realpath(root)
    try:
        if os.path.commonpath([root_real, candidate]) != root_real:
            return None
    except ValueError:
        return None
    return candidate


def format_size(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return "%.0f %s" % (value, unit) if unit == "B" else "%.1f %s" % (value, unit)
        value /= 1024
    return "%.1f TB" % value
