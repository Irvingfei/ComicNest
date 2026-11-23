"""Library scanning.

The scanner walks one source at a time, turns archives, image folders and PDFs
into chapters, and writes the result into SQLite. It is deliberately boring:
the filesystem is the source of truth, the database is rebuilt from it.
"""

import os
import posixpath
import threading
import time

from . import archives, config as config_module, db, metadata, sources
from .config import config
from .errors import ComicNestError
from .logging_setup import get_logger

log = get_logger("scanner")

_IGNORED_DIRS = {
    ".git", ".svn", ".hg", "__macosx", "@eadir", "#recycle", "$recycle.bin",
    "system volume information", "lost+found", ".trash", ".cache", "node_modules",
    ".thumbnails", ".stfolder",
}
_IGNORED_FILES = {"thumbs.db", "desktop.ini", ".ds_store"}
_COVER_NAMES = {"cover", "folder", "poster", "banner", "thumb", "thumbnail", "封面"}


class ScanState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.source_id = None
        self.source_name = ""
        self.phase = "idle"
        self.message = ""
        self.directories = 0
        self.chapters = 0
        self.started_at = ""
        self.finished_at = ""
        self.error = ""

    def snapshot(self):
        with self.lock:
            return {
                "running": self.running,
                "source_id": self.source_id,
                "source_name": self.source_name,
                "phase": self.phase,
                "message": self.message,
                "directories": self.directories,
                "chapters": self.chapters,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
            }

    def update(self, **fields):
        with self.lock:
            for key, value in fields.items():
                setattr(self, key, value)


class ScanManager:
    def __init__(self):
        self.state = ScanState()
        self._threads = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def start(self, source_id=None):
        with self._lock:
            if source_id is None:
                rows = db.list_sources(include_disabled=False)
            else:
                row = db.get_source(source_id)
                rows = [row] if row else []
            started = []
            for row in rows:
                if not row or not row.get("enabled"):
                    continue
                thread = self._threads.get(row["id"])
                if thread and thread.is_alive():
                    continue
                thread = threading.Thread(
                    target=self._scan_row, args=(row,), daemon=True, name="scan-%s" % row["id"]
                )
                self._threads[row["id"]] = thread
                thread.start()
                started.append(row["id"])
            return started

    def start_all(self):
        return self.start(None)

    def _scan_row(self, row):
        self.state.update(
            running=True,
            source_id=row["id"],
            source_name=row["name"],
            phase="walking",
            message="",
            directories=0,
            chapters=0,
            error="",
            started_at=db.now_iso(),
            finished_at="",
        )
        try:
            backend = sources.backend_for(row)
            _scan_source(row, backend, self.state)
            db.mark_scan(row["id"], "ok")
            self.state.update(phase="done", finished_at=db.now_iso())
        except ComicNestError as exc:
            log.warning("scan of %s failed: %s", row["name"], exc)
            db.mark_scan(row["id"], "error", exc.message)
            self.state.update(phase="error", error=exc.message, finished_at=db.now_iso())
        except Exception as exc:  # noqa: BLE001 - a scan must never kill the service
            log.exception("scan of %s crashed", row["name"])
            db.mark_scan(row["id"], "error", str(exc))
            self.state.update(phase="error", error=str(exc), finished_at=db.now_iso())
        finally:
            self.state.update(running=False)

    def status(self):
        snapshot = self.state.snapshot()
        snapshot["threads"] = sum(
            1 for thread in self._threads.values() if thread.is_alive()
        )
        return snapshot


manager = ScanManager()


def ensure_default_source():
    if db.list_sources(include_disabled=False):
        return None
    root = config.library_root()
    if not root or not os.path.isdir(root):
        return None
    existing = db.one("SELECT id FROM sources WHERE kind = 'local' AND root = ?", (root,))
    if existing:
        return existing["id"]
    row = db.create_source("ComicNest Library", "local", root)
    log.info("created the default comic source at %s", root)
    return row["id"]


def _scan_source(source_row, backend, state):
    source_id = source_row["id"]
    root_entry = sources.Entry("", True, 0, time.time())
    found = []
    _walk(backend, "", root_entry, found, state, depth=0)
    state.update(phase="indexing", message="%d items found" % len(found))

    # series_key -> {"title": str, "chapters": [...]}
    groups = {}

    for item in found:
        state.update(chapters=state.snapshot()["chapters"] + 1)
        try:
            group = _group_for(source_row, item)
        except (ValueError, IndexError):
            continue
        entry = groups.setdefault(
            group["key"],
            {"key": group["key"], "title": group["title"], "chapters": []},
        )
        item["series_title"] = group["title"]
        entry["chapters"].append(item)

    seen_keys = set()
    for key, group in groups.items():
        seen_keys.add(key)
        series_id = db.upsert_series(source_id, key, group["title"], sort_title=group["title"])
        kept_paths = []
        chapter_rows = []
        for item in group["chapters"]:
            kept_paths.append(item["rel"])
            chapter_id, parsed_info = _upsert_item(
                series_id, item, source_row, backend, group["title"]
            )
            chapter_rows.append((chapter_id, item, parsed_info))
            info_series = (item.get("info") or {}).get("Series")
            if info_series and group["title"] in (source_row["name"], parsed_info["title"]):
                db.execute(
                    "UPDATE series SET title = ?, sort_title = ? WHERE id = ?",
                    (info_series, info_series, series_id),
                )
        db.delete_chapters_except(series_id, kept_paths)
        db.refresh_chapter_count(series_id)
        _choose_cover(series_id, chapter_rows)

    db.delete_series_except(source_id, seen_keys)
    _clear_covers(source_id)
    log.info(
        "source %s: %d series, %d chapters",
        source_row["name"],
        len(seen_keys),
        len(found),
    )


def _walk(backend, rel, entry, found, state, depth):
    if depth > 32:
        return
    try:
        children = backend.list_dir(rel)
    except ComicNestError:
        raise
    state.update(directories=state.snapshot()["directories"] + 1)

    visible = []
    image_files = []
    for child in children:
        name = child.name
        folded = name.casefold()
        if name.startswith(".") or folded in _IGNORED_FILES:
            continue
        if child.is_dir:
            if folded in _IGNORED_DIRS:
                continue
            visible.append(child)
            continue
        extension = os.path.splitext(name)[1].lower()
        if extension in config.page_extensions:
            image_files.append(child)
        elif extension in config.archive_extensions:
            found.append(_item_for_archive(rel, child))
        elif extension in config.pdf_extensions:
            found.append(_item_for_pdf(rel, child))

    if image_files:
        subdirs = [child for child in visible if child.is_dir]
        if not _is_cover_only(rel, image_files, subdirs):
            pages = []
            for child in sorted(image_files, key=lambda item: metadata.natural_key(item.name)):
                width = height = None
                if backend.kind == "local":
                    try:
                        data = backend.read_bytes(_join(rel, child.name), length=65536)
                        width, height = metadata.image_size(data) or (None, None)
                    except ComicNestError:
                        width, height = None, None
                pages.append(
                    {"name": child.name, "size": child.size, "w": width, "h": height}
                )
            max_mtime = max((child.mtime for child in image_files), default=0)
            total_size = sum(child.size for child in image_files)
            found.append(
                {
                    "rel": rel,
                    "kind": "folder",
                    "format": "folder",
                    "name": posixpath.basename(rel) or os.path.basename(backend.root or "") or "Comic",
                    "size": total_size,
                    "mtime": max_mtime,
                    "pages": pages,
                }
            )

    for child in visible:
        if child.is_dir:
            _walk(backend, _join(rel, child.name), child, found, state, depth + 1)


def _is_cover_only(rel, images, subdirs):
    if not subdirs or len(images) != 1:
        return False
    stem = os.path.splitext(images[0].name)[0].casefold()
    return stem in _COVER_NAMES


def _item_for_archive(rel, child):
    extension = os.path.splitext(child.name)[1].lower()
    return {
        "rel": _join(rel, child.name),
        "kind": "archive",
        "format": extension,
        "name": os.path.splitext(child.name)[0],
        "size": child.size,
        "mtime": child.mtime,
        "pages": None,
    }


def _item_for_pdf(rel, child):
    return {
        "rel": _join(rel, child.name),
        "kind": "pdf",
        "format": ".pdf",
        "name": os.path.splitext(child.name)[0],
        "size": child.size,
        "mtime": child.mtime,
        "pages": None,
    }


def _join(parent, name):
    return posixpath.join(parent, name) if parent else name


def _series_hint(stem):
    parsed = metadata.parse_release(stem)
    if parsed["series_hint"]:
        return parsed["series_hint"]
    raw = parsed["raw"]
    cleaned = metadata._BRACKET_RE.sub(" ", raw) if hasattr(metadata, "_BRACKET_RE") else raw
    cut = len(cleaned)
    for pattern in metadata._VOLUME_RES + metadata._CHAPTER_RES:
        match = pattern.search(cleaned)
        if match and match.start() < cut:
            cut = match.start()
    prefix = metadata.clean_title(cleaned[:cut])
    if prefix and not metadata.looks_like_chapter(stem):
        return prefix
    return metadata.clean_title(raw) or stem


def _group_for(source_row, item):
    rel = item["rel"]
    if not rel:
        return {"key": "root:@source", "title": source_row["name"]}
    parent = posixpath.dirname(rel)
    name = posixpath.basename(rel) if item["kind"] == "folder" else item["name"]

    if not parent:
        hint = _series_hint(name)
        title = metadata.clean_title(hint) or source_row["name"]
        return {"key": "root:" + title.casefold(), "title": title}

    parent_name = posixpath.basename(parent)
    grand = posixpath.dirname(parent)
    parent_parsed = metadata.parse_release(parent_name)
    parent_is_chapter = metadata.looks_like_chapter(parent_name)
    if parent_is_chapter and grand:
        series_dir = grand
        title = metadata.clean_title(posixpath.basename(grand)) or source_row["name"]
    else:
        series_dir = parent
        title = metadata.clean_title(parent_name) or source_row["name"]
        if parent_parsed["series_hint"] and not parent_is_chapter:
            title = metadata.clean_title(parent_parsed["series_hint"]) or title
    return {"key": "dir:" + series_dir.casefold(), "title": title}


def _upsert_item(series_id, item, source_row, backend, series_title):
    existing = db.one(
        "SELECT * FROM chapters WHERE series_id = ? AND rel_path = ?",
        (series_id, item["rel"]),
    )
    parsed = metadata.parse_release(item["name"])
    chapter_title = metadata.clean_title(parsed["title"]) or item["name"]
    chapter_title = metadata.strip_series_prefix(chapter_title, series_title)
    number = parsed["number"]
    volume = parsed["volume"]
    pages = item.get("pages")
    info = {}

    unchanged = bool(
        existing
        and existing.get("mtime_ns")
        and abs(float(existing["mtime_ns"]) / 1e9 - float(item["mtime"])) < 1.0
        and int(existing.get("size_bytes") or 0) == int(item.get("size") or 0)
        and existing.get("pages_json")
    )

    if not unchanged:
        if item["kind"] == "archive":
            if backend.kind == "local":
                pages = _load_archive_pages(item, source_row, backend)
                if pages:
                    info = item.get("info") or {}
            else:
                # Remote archives are downloaded when they are first opened,
                # not during a library scan.
                pages = []
        elif item["kind"] == "folder":
            pages = item.get("pages") or []
        elif item["kind"] == "pdf":
            pages = []

    if info:
        if info.get("Title"):
            chapter_title = metadata.strip_series_prefix(info["Title"], series_title)
        try:
            if info.get("Number"):
                number = float(info["Number"])
            if info.get("Volume"):
                volume = float(info["Volume"])
        except ValueError:
            pass

    item["volume"] = volume
    item["number"] = number
    chapter_id = db.upsert_chapter(
        series_id,
        item["rel"],
        item["kind"],
        item["format"],
        chapter_title,
        number=number,
        volume=volume,
        size_bytes=item.get("size") or 0,
        mtime_ns=int(float(item.get("mtime") or 0) * 1e9),
        pages=pages if not unchanged else None,
    )
    item["info"] = info
    if info.get("Summary"):
        db.execute(
            "UPDATE series SET description = ? WHERE id = ? AND description = ''",
            (info["Summary"], series_id),
        )
    if info.get("Writer"):
        db.execute(
            "UPDATE series SET author = ? WHERE id = ? AND author = ''",
            (info["Writer"], series_id),
        )
    if info.get("Year"):
        db.execute(
            "UPDATE series SET year = ? WHERE id = ? AND year = ''",
            (str(info["Year"]), series_id),
        )
    return chapter_id, {"title": chapter_title}


def _load_archive_pages(item, source_row, backend):
    try:
        local = _ensure_archive(item, source_row, backend)
        pages = archives.list_pages(local, item["format"], config.page_extensions)
        info = archives.read_comicinfo(local, item["format"])
        item["info"] = info
        return pages
    except ComicNestError as exc:
        log.info("skipping archive %s: %s", item["rel"], exc)
        return []


def _ensure_archive(item, source_row, backend):
    from . import cache

    return cache.ensure(
        backend,
        source_row["id"],
        item["rel"],
        expected_size=item.get("size") or None,
        extension=item["format"],
    )


def _choose_cover(series_id, chapter_rows):
    if not chapter_rows:
        db.set_series_cover(series_id, None, 0)
        return
    ordered = sorted(
        chapter_rows,
        key=lambda row: metadata.chapter_sort_key(
            {
                "volume": row[1].get("volume"),
                "number": row[1].get("number"),
                "title": row[2].get("title") or "",
            }
        ),
    )
    chapter_id, _item, _info = ordered[0]
    db.set_series_cover(series_id, chapter_id, 0)


def _clear_covers(source_id):
    """Drop cached covers for a source after its index changed."""
    try:
        rows = db.query("SELECT id FROM series WHERE source_id = ?", (int(source_id),))
        for row in rows:
            for name in os.listdir(config.covers_dir):
                if name.startswith("%d." % row["id"]):
                    try:
                        os.remove(os.path.join(config.covers_dir, name))
                    except OSError:
                        pass
    except OSError:
        pass
