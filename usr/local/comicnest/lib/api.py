"""HTTP API.

Handlers return response objects; errors travel as a stable code in the JSON
envelope so the frontend can localise them.
"""

import importlib.util
import json
import os
import re
import sqlite3
import urllib.parse

from . import __version__, cache, db, metadata, reader, scanner, secretstore as secrets, sevenzip, sources
from .auth import is_admin, require_admin, resolve_identity, verify
from .config import config
from .errors import (
    BadRequest,
    ComicNestError,
    Conflict,
    Forbidden,
    MethodNotAllowed,
    NotFound,
    PageNotFound,
)
from .http_util import ErrorResponse, FileResponse, JsonResponse, Response, format_size
from .logging_setup import get_logger

log = get_logger("api")

PUBLIC_PATHS = ("/api/health", "/api/options")
_ADMIN = "/api/admin"
_HIDDEN_DIRS = {".cache", "@eadir", "#recycle", "node_modules", "lost+found", "snapshot"}
_SERIES_RE = re.compile(r"^/api/series/(\d+)$")
_COVER_RE = re.compile(r"^/api/cover/(\d+)$")
_CHAPTER_RE = re.compile(r"^/api/chapter/(\d+)$")
_PAGES_RE = re.compile(r"^/api/chapter/(\d+)/pages$")
_PAGE_RE = re.compile(r"^/api/page/(\d+)/(\d+)$")
_PDF_RE = re.compile(r"^/api/pdf/(\d+)$")
_PROGRESS_RE = re.compile(r"^/api/progress/(\d+)$")
_SOURCE_ITEM_RE = re.compile(r"^/api/admin/sources/(\d+)$")
_SOURCE_SCAN_RE = re.compile(r"^/api/admin/sources/(\d+)/scan$")

_LANGUAGES = ("zh-CN", "zh-TW", "en", "ja", "ko", "de", "fr", "es", "ru")
_MODES = {"single", "double", "split"}
_DIRECTIONS = {"rtl", "ltr", "vertical"}
_ANIMATIONS = {"slide", "scroll", "flip"}


def normalize_path(raw_path):
    path = urllib.parse.urlsplit(raw_path or "/").path or "/"
    segments = [piece for piece in path.split("/") if piece]
    if len(segments) >= 2 and segments[0] == "v2" and segments[1] == "proxy":
        segments = segments[2:]
    if segments and segments[0] == config.app_id:
        segments = segments[1:]
    canonical = "/" + "/".join(segments)
    return canonical if canonical != "/" else "/"


def _param(query, name, default=""):
    values = query.get(name)
    return values[0] if values else default


def _as_int(value, name, default=0, minimum=None, maximum=None):
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise BadRequest("%s must be an integer" % name)
    if minimum is not None and number < minimum:
        raise BadRequest("%s must be at least %d" % (name, minimum))
    if maximum is not None and number > maximum:
        raise BadRequest("%s must be at most %d" % (name, maximum))
    return number


def _json_body(body):
    if not body:
        return {}
    if len(body) > config.max_json_bytes:
        raise BadRequest("the request body is too large")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BadRequest("the request body must be JSON")
    if not isinstance(value, dict):
        raise BadRequest("the request body must be a JSON object")
    return value


def _progress_percent(page, total):
    if not total or total <= 0:
        return 0
    return max(0, min(100, int(round((int(page) + 1) * 100.0 / int(total)))))


def _public_source(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "enabled": bool(row["enabled"]),
        "last_scan_at": row.get("last_scan_at") or "",
        "last_scan_status": row.get("last_scan_status") or "",
    }


def _admin_source(row):
    data = _public_source(row)
    data.update(
        {
            "root": row["root"],
            "username": row.get("username") or "",
            "has_password": bool(row.get("secret_ref")),
            "options": db.source_options(row),
            "last_scan_error": row.get("last_scan_error") or "",
        }
    )
    return data


def _chapter_payload(row, progress=None):
    data = {
        "id": row["id"],
        "title": row.get("title") or "",
        "number": row.get("number"),
        "volume": row.get("volume"),
        "kind": row.get("kind"),
        "format": row.get("format"),
        "page_count": row.get("page_count"),
        "size_bytes": row.get("size_bytes") or 0,
    }
    if progress:
        data["progress"] = progress
    return data


def _progress_payload(row):
    if not row:
        return None
    return {
        "chapter_id": row["chapter_id"],
        "page": int(row.get("page") or 0),
        "total_pages": row.get("total_pages"),
        "percent": _progress_percent(row.get("page") or 0, row.get("total_pages")),
        "mode": row.get("mode") or "single",
        "direction": row.get("direction") or "rtl",
        "animation": row.get("animation") or "slide",
        "updated_at": row.get("updated_at") or "",
        "chapter_title": row.get("chapter_title") or "",
        "series_title": row.get("series_title") or "",
    }


def _sorted_chapters(rows):
    return sorted(
        rows,
        key=lambda row: metadata.chapter_sort_key(
            {
                "volume": row.get("volume"),
                "number": row.get("number"),
                "title": row.get("title") or "",
            }
        ),
    )


class Api:
    def dispatch(self, method, raw_path, query, headers, body):
        path = normalize_path(raw_path)
        try:
            if method == "OPTIONS":
                return Response(204)
            if path == "/api/health" and method == "GET":
                return JsonResponse(self._health())
            if path == "/api/options" and method == "GET":
                return JsonResponse(self._options())

            verify(headers)
            user = resolve_identity(headers)
            admin = is_admin(user)
            return self._route(method, path, query, headers, body, user, admin)
        except ComicNestError as exc:
            return ErrorResponse(exc)
        except sqlite3.IntegrityError as exc:
            log.info("integrity conflict: %s", exc)
            return ErrorResponse(Conflict("that entry already exists"))
        except Exception as exc:  # noqa: BLE001 - never leak a traceback to the browser
            log.exception("unhandled API error on %s %s", method, path)
            return ErrorResponse(ComicNestError("internal error"))

    # ------------------------------------------------------------------ routes

    def _route(self, method, path, query, headers, body, user, admin):
        if path == "/api/me" and method == "GET":
            return JsonResponse(
                {"user": user, "is_admin": admin, "auth": config.require_auth}
            )
        if path == "/api/sources" and method == "GET":
            return JsonResponse([_public_source(row) for row in db.list_sources(include_disabled=False)])
        if path == "/api/library" and method == "GET":
            return JsonResponse(self._library(query, user))
        if path == "/api/progress" and method == "GET":
            rows = db.list_progress(user, limit=500)
            return JsonResponse([_progress_payload(row) for row in rows])

        match = _SERIES_RE.match(path)
        if match and method == "GET":
            return JsonResponse(self._series(int(match.group(1)), user))
        match = _COVER_RE.match(path)
        if match and method == "GET":
            return self._cover(int(match.group(1)), headers)
        match = _CHAPTER_RE.match(path)
        if match and method == "GET":
            return JsonResponse(self._chapter(int(match.group(1)), user))
        match = _PAGES_RE.match(path)
        if match and method == "GET":
            return JsonResponse(self._pages(int(match.group(1)), user))
        match = _PAGE_RE.match(path)
        if match and method == "GET":
            return self._page(int(match.group(1)), int(match.group(2)), headers)
        match = _PDF_RE.match(path)
        if match and method == "GET":
            return self._pdf(int(match.group(1)))
        match = _PROGRESS_RE.match(path)
        if match and method == "PUT":
            return JsonResponse(self._save_progress(int(match.group(1)), body, user))
        if match and method == "DELETE":
            db.execute("DELETE FROM progress WHERE user = ? AND chapter_id = ?", (user, int(match.group(1))))
            return JsonResponse({"ok": True})

        if path.startswith(_ADMIN):
            return self._admin(method, path, query, body, admin)

        known = (
            _SERIES_RE.match(path)
            or _COVER_RE.match(path)
            or _CHAPTER_RE.match(path)
            or _PAGES_RE.match(path)
            or _PAGE_RE.match(path)
            or _PDF_RE.match(path)
            or _PROGRESS_RE.match(path)
            or path in ("/api/me", "/api/sources", "/api/library", "/api/progress")
        )
        if known:
            raise MethodNotAllowed("that method is not allowed here")
        raise NotFound("endpoint not found")

    # ------------------------------------------------------------------ public

    def _health(self):
        scanning = scanner.manager.status()
        try:
            ready = bool(db.list_sources(include_disabled=False)) or bool(config.library_root())
        except Exception:
            ready = False
        return {
            "ok": True,
            "version": __version__,
            "library_ready": ready,
            "scanning": scanning["running"],
            "share_root": config.share_root() or "",
        }

    def _options(self):
        return {
            "version": __version__,
            "languages": list(_LANGUAGES),
            "formats": {
                "image": [ext.lstrip(".") for ext in config.page_extensions],
                "archive": [ext.lstrip(".") for ext in config.archive_extensions],
                "document": ["pdf"],
            },
            "capabilities": {
                "sevenzip": sevenzip.available(),
                "smb": importlib.util.find_spec("smbclient") is not None,
                "tiff": importlib.util.find_spec("PIL") is not None,
                "pdf": True,
            },
            "max_cache_bytes": config.max_cache_bytes,
            "require_auth": config.require_auth,
        }

    # ----------------------------------------------------------------- library

    def _library(self, query, user):
        source_id = _as_int(_param(query, "source"), "source", 0)
        search = _param(query, "q").strip()
        limit = _as_int(_param(query, "limit"), "limit", 200, 1, 1000)
        rows = db.list_series(source_id or None, search=search, limit=limit)
        progress_rows = db.list_progress(user, limit=2000)
        latest = {}
        for row in progress_rows:
            latest.setdefault(row["series_id"], row)

        cards = []
        for row in rows:
            progress = latest.get(row["id"])
            cards.append(self._series_card(row, progress))

        continue_items = []
        for row in progress_rows[:12]:
            series_row = db.get_series(row["series_id"])
            if not series_row:
                continue
            continue_items.append(
                {
                    "series": self._series_card(series_row, row),
                    "progress": _progress_payload(row),
                }
            )

        return {
            "series": cards,
            "continue": continue_items,
            "sources": [_public_source(row) for row in db.list_sources(include_disabled=False)],
            "total": len(cards),
            "scanning": scanner.manager.status(),
            "storage": {"cache_bytes": cache.size(), "cache_limit": config.max_cache_bytes},
        }

    def _series_card(self, row, progress):
        stamp = urllib.parse.quote(str(row.get("updated_at") or row.get("chapter_count") or ""))
        return {
            "id": row["id"],
            "title": row.get("title") or "",
            "sort_title": row.get("sort_title") or "",
            "author": row.get("author") or "",
            "year": row.get("year") or "",
            "description": row.get("description") or "",
            "chapter_count": int(row.get("chapter_count") or 0),
            "updated_at": row.get("updated_at") or "",
            "source": {
                "id": row.get("source_id"),
                "name": row.get("source_name") or "",
                "kind": row.get("source_kind") or "",
            },
            "cover_url": "api/cover/%d?v=%s" % (row["id"], stamp),
            "progress": _progress_payload(progress) if progress else None,
        }

    def _series(self, series_id, user):
        row = db.get_series(series_id)
        if not row:
            raise NotFound("series not found")
        source = db.get_source(row["source_id"])
        if not source or not source.get("enabled"):
            raise NotFound("the source for this series is disabled")
        rows = _sorted_chapters(db.list_chapters(series_id))
        progress_rows = db.series_progress(user, series_id)
        progress_map = {item["chapter_id"]: item for item in progress_rows}

        chapters = [_chapter_payload(item, _progress_payload(progress_map.get(item["id"]))) for item in rows]
        target = None
        for item in rows:
            progress = progress_map.get(item["id"])
            if not progress:
                target = item["id"]
                break
            total = progress.get("total_pages") or item.get("page_count") or 0
            if total and int(progress.get("page") or 0) + 1 < int(total):
                target = item["id"]
                break
        if target is None and rows:
            target = rows[-1]["id"]

        card = self._series_card(
            {
                **row,
                "source_name": source["name"],
                "source_kind": source["kind"],
            },
            progress_rows[0] if progress_rows else None,
        )
        card["chapters"] = chapters
        card["continue_chapter_id"] = target
        return card

    def _cover(self, series_id, headers):
        row = db.get_series(series_id)
        if not row:
            raise NotFound("series not found")
        etag = '"cover-%d-%s"' % (series_id, row.get("updated_at") or "0")
        if (headers.get("If-None-Match") or "") == etag:
            return Response(304, b"", {"ETag": etag})
        try:
            data, mime = reader.cover_bytes(row)
        except ComicNestError:
            data, mime = reader.cover_placeholder(row)
        return Response(
            200,
            data,
            {
                "Content-Type": mime,
                "ETag": etag,
                "Cache-Control": "private, max-age=86400",
            },
        )

    def _chapter(self, chapter_id, user):
        row = db.get_chapter(chapter_id)
        if not row:
            raise NotFound("chapter not found")
        chapters = _sorted_chapters(db.list_chapters(row["series_id"]))
        index = next((i for i, item in enumerate(chapters) if item["id"] == chapter_id), None)
        prev_id = chapters[index - 1]["id"] if index not in (None, 0) else None
        next_id = chapters[index + 1]["id"] if index is not None and index + 1 < len(chapters) else None
        progress = db.get_progress(user, chapter_id)
        return {
            "chapter": _chapter_payload(row, _progress_payload(progress)),
            "series": {
                "id": row["series_id"],
                "title": row["series_title"],
            },
            "source": {"name": row.get("source_name"), "kind": row.get("source_kind")},
            "prev_chapter_id": prev_id,
            "next_chapter_id": next_id,
        }

    def _pages(self, chapter_id, user):
        row = db.get_chapter(chapter_id)
        if not row:
            raise NotFound("chapter not found")
        if row["kind"] == "pdf":
            progress = db.get_progress(user, chapter_id)
            return {
                "format": "pdf",
                "page_count": row.get("page_count"),
                "pdf_url": "api/pdf/%d?v=%d" % (chapter_id, int(row.get("mtime_ns") or 0)),
                "pages": [],
                "progress": _progress_payload(progress),
                "title": row.get("title") or "",
            }
        pages = reader.resolve_pages(row)
        stamp = int(row.get("mtime_ns") or 0)
        data = [
            {
                "index": index,
                "w": page.get("w"),
                "h": page.get("h"),
                "url": "api/page/%d/%d?v=%d" % (chapter_id, index, stamp),
            }
            for index, page in enumerate(pages)
        ]
        progress = db.get_progress(user, chapter_id)
        return {
            "format": "images",
            "page_count": len(data),
            "pages": data,
            "progress": _progress_payload(progress),
            "title": row.get("title") or "",
            "kind": row.get("kind"),
        }

    def _page(self, chapter_id, index, headers):
        row = db.get_chapter(chapter_id)
        if not row:
            raise PageNotFound("chapter not found")
        etag = '"p-%d-%d-%d"' % (chapter_id, index, int(row.get("mtime_ns") or 0))
        if (headers.get("If-None-Match") or "") == etag:
            return Response(304, b"", {"ETag": etag})
        data, mime = reader.page_bytes(row, index)
        return Response(
            200,
            data,
            {
                "Content-Type": mime,
                "ETag": etag,
                "Cache-Control": "private, max-age=86400",
            },
        )

    def _pdf(self, chapter_id):
        row = db.get_chapter(chapter_id)
        if not row or row["kind"] != "pdf":
            raise NotFound("PDF not found")
        path = reader.pdf_path(row)
        return FileResponse(path, "application/pdf")

    def _save_progress(self, chapter_id, body, user):
        row = db.get_chapter(chapter_id)
        if not row:
            raise NotFound("chapter not found")
        payload = _json_body(body)
        page = _as_int(payload.get("page"), "page", 0, 0, 1_000_000)
        total = payload.get("total_pages")
        if total is not None and total != "":
            total = _as_int(total, "total_pages", 0, 0, 1_000_000)
        else:
            total = None
        mode = str(payload.get("mode") or "single")
        direction = str(payload.get("direction") or "rtl")
        animation = str(payload.get("animation") or "slide")
        if mode not in _MODES:
            mode = "single"
        if direction not in _DIRECTIONS:
            direction = "rtl"
        if animation not in _ANIMATIONS:
            animation = "slide"
        db.save_progress(user, row["series_id"], chapter_id, page, total, mode, direction, animation)
        saved = db.get_progress(user, chapter_id)
        return _progress_payload(saved)

    # ------------------------------------------------------------------- admin

    def _admin(self, method, path, query, body, admin):
        if not admin:
            raise Forbidden("only a TOS administrator can manage sources")
        if path == _ADMIN + "/sources" and method == "GET":
            return JsonResponse([_admin_source(row) for row in db.list_sources()])
        if path == _ADMIN + "/sources" and method == "POST":
            return JsonResponse(self._create_source(_json_body(body)), status=201)
        if path == _ADMIN + "/scan" and method == "POST":
            return JsonResponse({"started": scanner.manager.start(None)})
        if path == _ADMIN + "/scan" and method == "GET":
            return JsonResponse(self._scan_status())
        if path == _ADMIN + "/cache/clear" and method == "POST":
            cache.clear()
            for name in os.listdir(config.covers_dir):
                try:
                    os.remove(os.path.join(config.covers_dir, name))
                except OSError:
                    pass
            return JsonResponse({"ok": True, "cache_bytes": cache.size()})
        if path == _ADMIN + "/stats" and method == "GET":
            return JsonResponse(
                {
                    **db.stats(),
                    "cache_bytes": cache.size(),
                    "cache_limit": config.max_cache_bytes,
                    "sevenzip": sevenzip.available(),
                    "smb": importlib.util.find_spec("smbclient") is not None,
                    "tiff": importlib.util.find_spec("PIL") is not None,
                }
            )
        if path == _ADMIN + "/browse" and method == "GET":
            return JsonResponse(self._browse(_param(query, "path")))

        match = _SOURCE_ITEM_RE.match(path)
        if match:
            source_id = int(match.group(1))
            if method == "PATCH":
                return JsonResponse(self._update_source(source_id, _json_body(body)))
            if method == "DELETE":
                return JsonResponse(self._delete_source(source_id))
        match = _SOURCE_SCAN_RE.match(path)
        if match and method == "POST":
            return JsonResponse({"started": scanner.manager.start(int(match.group(1)))})
        raise NotFound("admin endpoint not found")

    def _create_source(self, payload):
        kind = str(payload.get("kind") or "local").lower()
        root = str(payload.get("root") or "").strip()
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        name = str(payload.get("name") or "").strip()
        enabled = bool(payload.get("enabled", True))

        normalized = sources.validate(kind, root, username, password, options)
        if not name:
            name = _default_source_name(kind, normalized)
        secret_ref = secrets.put(password) if password else ""
        try:
            row = db.create_source(name, kind, normalized, username, secret_ref, options, enabled)
        except sqlite3.IntegrityError:
            secrets.delete(secret_ref)
            raise Conflict("a source with that location already exists")
        if enabled:
            scanner.manager.start(row["id"])
        return _admin_source(row)

    def _update_source(self, source_id, payload):
        row = db.get_source(source_id)
        if not row:
            raise NotFound("source not found")
        kind = str(payload.get("kind") or row["kind"]).lower()
        root = str(payload.get("root") if "root" in payload else row["root"]).strip()
        username = str(payload.get("username") if "username" in payload else row["username"]).strip()
        options = payload.get("options") if isinstance(payload.get("options"), dict) else db.source_options(row)
        enabled = bool(payload.get("enabled", row["enabled"]))
        name = str(payload.get("name") or row["name"]).strip()

        password = secrets.get(row.get("secret_ref") or "")
        secret_ref = row.get("secret_ref") or ""
        if "password" in payload:
            candidate = str(payload.get("password") or "")
            if candidate:
                secret_ref = secrets.rotate(secret_ref, candidate)
                password = candidate
            else:
                secrets.delete(secret_ref)
                secret_ref = ""
                password = ""

        connection_changed = (
            kind != row["kind"]
            or root != row["root"]
            or username != row["username"]
            or options != db.source_options(row)
            or "password" in payload
        )
        normalized = sources.validate(kind, root, username, password, options) if connection_changed else root
        try:
            updated = db.update_source(
                source_id,
                name=name,
                kind=kind,
                root=normalized,
                username=username,
                secret_ref=secret_ref,
                options=options,
                enabled=enabled,
            )
        except sqlite3.IntegrityError:
            raise Conflict("a source with that location already exists")
        if connection_changed:
            db.update_source(source_id, last_scan_at=None, last_scan_status="", last_scan_error="")
        if enabled and (connection_changed or not row["enabled"]):
            scanner.manager.start(source_id)
        return _admin_source(updated)

    def _delete_source(self, source_id):
        row = db.get_source(source_id)
        if not row:
            raise NotFound("source not found")
        for series in db.query("SELECT id FROM series WHERE source_id = ?", (source_id,)):
            for name in os.listdir(config.covers_dir):
                if name.startswith("%d." % series["id"]):
                    try:
                        os.remove(os.path.join(config.covers_dir, name))
                    except OSError:
                        pass
        secrets.delete(row.get("secret_ref") or "")
        db.delete_source(source_id)
        return {"ok": True}

    def _scan_status(self):
        return {
            "state": scanner.manager.status(),
            "sources": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "last_scan_at": row.get("last_scan_at") or "",
                    "last_scan_status": row.get("last_scan_status") or "",
                    "last_scan_error": row.get("last_scan_error") or "",
                }
                for row in db.list_sources()
            ],
        }

    def _browse(self, raw_path):
        path = (raw_path or "").strip()
        if not path:
            roots = []
            if os.name == "nt":
                for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    candidate = letter + ":\\"
                    if os.path.isdir(candidate):
                        roots.append({"name": candidate, "path": candidate})
            else:
                import glob

                for volume in sorted(glob.glob(config.volume_glob)):
                    roots.append({"name": os.path.basename(volume), "path": volume})
                if not roots:
                    roots = [{"name": "/", "path": "/"}]
            return {"path": "", "parent": "", "entries": roots}

        real = os.path.realpath(path)
        if not os.path.isdir(real):
            raise BadRequest("that path is not a directory")
        try:
            with os.scandir(real) as iterator:
                entries = []
                for entry in iterator:
                    if entry.name.startswith(".") or entry.name.startswith("@"):
                        continue
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if entry.name.casefold() in _HIDDEN_DIRS:
                        continue
                    entries.append({"name": entry.name, "path": os.path.join(real, entry.name)})
                    if len(entries) >= 1000:
                        break
        except PermissionError:
            raise Forbidden("that folder cannot be read by the application")
        entries.sort(key=lambda item: item["name"].casefold())
        parent = os.path.dirname(real)
        if parent == real:
            parent = ""
        return {"path": real, "parent": parent, "entries": entries}


def _default_source_name(kind, root):
    if kind == "local":
        return os.path.basename(os.path.normpath(root)) or "Comics"
    if kind == "webdav":
        parsed = urllib.parse.urlsplit(root)
        return os.path.basename(parsed.path) or parsed.hostname or "WebDAV"
    if kind == "smb":
        return root.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or "SMB"
    return "Comics"


api = Api()
