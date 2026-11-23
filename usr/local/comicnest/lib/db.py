"""SQLite index for the comic library.

The database is a derived cache: every fact in it can be rebuilt by scanning
the configured sources. It is never placed inside a shared folder, so the
operator's file listings stay clean.
"""

import contextlib
import json
import sqlite3
import threading
import time

from .config import config
from .logging_setup import get_logger

log = get_logger("db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    root            TEXT NOT NULL,
    username        TEXT NOT NULL DEFAULT '',
    secret_ref      TEXT NOT NULL DEFAULT '',
    options         TEXT NOT NULL DEFAULT '{}',
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    last_scan_at    TEXT,
    last_scan_status TEXT NOT NULL DEFAULT '',
    last_scan_error TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS sources_kind_root ON sources(kind, root);

CREATE TABLE IF NOT EXISTS series (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id        INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    key              TEXT NOT NULL,
    title            TEXT NOT NULL,
    sort_title       TEXT NOT NULL DEFAULT '',
    author           TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    year             TEXT NOT NULL DEFAULT '',
    cover_chapter_id INTEGER,
    cover_page       INTEGER NOT NULL DEFAULT 0,
    chapter_count    INTEGER NOT NULL DEFAULT 0,
    updated_at       TEXT NOT NULL,
    UNIQUE(source_id, key)
);
CREATE INDEX IF NOT EXISTS series_title ON series(sort_title, title);

CREATE TABLE IF NOT EXISTS chapters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id   INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    rel_path    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    format      TEXT NOT NULL,
    title       TEXT NOT NULL,
    number      REAL,
    volume      REAL,
    page_count  INTEGER,
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    mtime_ns    INTEGER NOT NULL DEFAULT 0,
    pages_json  TEXT NOT NULL DEFAULT '',
    scanned_at  TEXT NOT NULL,
    UNIQUE(series_id, rel_path)
);
CREATE INDEX IF NOT EXISTS chapters_series ON chapters(series_id);

CREATE TABLE IF NOT EXISTS progress (
    user       TEXT NOT NULL,
    series_id  INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    page       INTEGER NOT NULL DEFAULT 0,
    total_pages INTEGER,
    mode       TEXT NOT NULL DEFAULT 'single',
    direction  TEXT NOT NULL DEFAULT 'rtl',
    animation  TEXT NOT NULL DEFAULT 'slide',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user, chapter_id)
);
CREATE INDEX IF NOT EXISTS progress_recent ON progress(user, updated_at DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_LOCK = threading.RLock()
_INITIALISED = False


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def connect():
    config.ensure_directories()
    connection = sqlite3.connect(config.db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def _rows(cursor):
    return [dict(row) for row in cursor.fetchall()]


def initialise():
    global _INITIALISED
    with _LOCK:
        if _INITIALISED:
            return
        with contextlib.closing(connect()) as connection:
            connection.executescript(_SCHEMA)
            connection.commit()
        _INITIALISED = True


@contextlib.contextmanager
def transaction():
    initialise()
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def query(sql, params=()):
    initialise()
    with contextlib.closing(connect()) as connection:
        return _rows(connection.execute(sql, params))


def one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    with transaction() as connection:
        cursor = connection.execute(sql, params)
        return cursor.lastrowid, cursor.rowcount


# ------------------------------------------------------------------ sources


def list_sources(include_disabled=True):
    clause = "" if include_disabled else " WHERE enabled = 1"
    return query("SELECT * FROM sources%s ORDER BY name COLLATE NOCASE" % clause)


def get_source(source_id):
    return one("SELECT * FROM sources WHERE id = ?", (int(source_id),))


def source_options(row):
    try:
        value = json.loads(row.get("options") or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def create_source(name, kind, root, username="", secret_ref="", options=None, enabled=True):
    source_id, _ = execute(
        """INSERT INTO sources (name, kind, root, username, secret_ref, options, enabled, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            name,
            kind,
            root,
            username,
            secret_ref,
            json.dumps(options or {}, ensure_ascii=False),
            1 if enabled else 0,
            now_iso(),
        ),
    )
    return get_source(source_id)


def update_source(source_id, **fields):
    allowed = {
        "name",
        "kind",
        "root",
        "username",
        "secret_ref",
        "options",
        "enabled",
        "last_scan_at",
        "last_scan_status",
        "last_scan_error",
    }
    assignments = []
    params = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "options" and not isinstance(value, str):
            value = json.dumps(value or {}, ensure_ascii=False)
        if key == "enabled":
            value = 1 if value else 0
        assignments.append("%s = ?" % key)
        params.append(value)
    if not assignments:
        return get_source(source_id)
    params.append(int(source_id))
    execute("UPDATE sources SET %s WHERE id = ?" % ", ".join(assignments), params)
    return get_source(source_id)


def delete_source(source_id):
    execute("DELETE FROM sources WHERE id = ?", (int(source_id),))


def mark_scan(source_id, status, error=""):
    execute(
        "UPDATE sources SET last_scan_at = ?, last_scan_status = ?, last_scan_error = ? WHERE id = ?",
        (now_iso(), status, (error or "")[:2000], int(source_id)),
    )


# ------------------------------------------------------------------- series


def get_series(series_id):
    return one("SELECT * FROM series WHERE id = ?", (int(series_id),))


def get_series_by_key(source_id, key):
    return one(
        "SELECT * FROM series WHERE source_id = ? AND key = ?", (int(source_id), key)
    )


def upsert_series(source_id, key, title, sort_title="", author="", description="", year=""):
    existing = get_series_by_key(source_id, key)
    stamp = now_iso()
    if existing:
        execute(
            """UPDATE series SET title = ?, sort_title = ?, author = ?, description = ?,
               year = ?, updated_at = ? WHERE id = ?""",
            (
                title,
                sort_title or title,
                author or "",
                description or "",
                year or "",
                stamp,
                existing["id"],
            ),
        )
        return existing["id"]
    series_id, _ = execute(
        """INSERT INTO series (source_id, key, title, sort_title, author, description,
           year, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(source_id),
            key,
            title,
            sort_title or title,
            author or "",
            description or "",
            year or "",
            stamp,
        ),
    )
    return series_id


def list_series(source_id=None, search="", limit=500, offset=0):
    params = []
    where = ["s.enabled = 1"] if False else []
    sql = """SELECT s.*, src.name AS source_name, src.kind AS source_kind
             FROM series s JOIN sources src ON src.id = s.source_id
             WHERE src.enabled = 1"""
    if source_id:
        sql += " AND s.source_id = ?"
        params.append(int(source_id))
    if search:
        sql += " AND (s.title LIKE ? OR s.author LIKE ?)"
        needle = "%" + search.strip() + "%"
        params.extend([needle, needle])
    sql += " ORDER BY s.sort_title COLLATE NOCASE, s.id LIMIT ? OFFSET ?"
    params.extend([int(limit), int(offset)])
    return query(sql, params)


def set_series_cover(series_id, chapter_id, page):
    execute(
        "UPDATE series SET cover_chapter_id = ?, cover_page = ? WHERE id = ?",
        (chapter_id, int(page or 0), int(series_id)),
    )


def refresh_chapter_count(series_id):
    row = one(
        "SELECT COUNT(*) AS count FROM chapters WHERE series_id = ?", (int(series_id),)
    )
    execute(
        "UPDATE series SET chapter_count = ? WHERE id = ?",
        (int(row["count"] if row else 0), int(series_id)),
    )


def delete_series_except(source_id, keys):
    initialise()
    keys = set(keys)
    removed = []
    with transaction() as connection:
        rows = _rows(
            connection.execute(
                "SELECT id, key FROM series WHERE source_id = ?", (int(source_id),)
            )
        )
        for row in rows:
            if row["key"] not in keys:
                connection.execute("DELETE FROM series WHERE id = ?", (row["id"],))
                removed.append(row["id"])
    return removed


# ----------------------------------------------------------------- chapters


def get_chapter(chapter_id):
    return one(
        """SELECT c.*, s.title AS series_title, s.source_id, s.key AS series_key,
                  src.kind AS source_kind, src.name AS source_name
           FROM chapters c
           JOIN series s ON s.id = c.series_id
           JOIN sources src ON src.id = s.source_id
           WHERE c.id = ?""",
        (int(chapter_id),),
    )


def list_chapters(series_id):
    return query(
        "SELECT * FROM chapters WHERE series_id = ? ORDER BY volume, number, title COLLATE NOCASE",
        (int(series_id),),
    )


def upsert_chapter(series_id, rel_path, kind, fmt, title, number=None, volume=None,
                   size_bytes=0, mtime_ns=0, pages=None):
    existing = one(
        "SELECT * FROM chapters WHERE series_id = ? AND rel_path = ?",
        (int(series_id), rel_path),
    )
    stamp = now_iso()
    pages_json = json.dumps(pages, ensure_ascii=False) if pages is not None else None
    if existing:
        fields = [
            "kind = ?", "format = ?", "title = ?", "number = ?", "volume = ?",
            "size_bytes = ?", "mtime_ns = ?", "scanned_at = ?",
        ]
        params = [kind, fmt, title, number, volume, int(size_bytes), int(mtime_ns), stamp]
        if pages_json is not None:
            fields.extend(["pages_json = ?", "page_count = ?"])
            params.extend([pages_json, len(pages)])
        params.append(existing["id"])
        execute("UPDATE chapters SET %s WHERE id = ?" % ", ".join(fields), params)
        return existing["id"]
    chapter_id, _ = execute(
        """INSERT INTO chapters (series_id, rel_path, kind, format, title, number,
           volume, page_count, size_bytes, mtime_ns, pages_json, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(series_id),
            rel_path,
            kind,
            fmt,
            title,
            number,
            volume,
            len(pages) if pages is not None else None,
            int(size_bytes),
            int(mtime_ns),
            pages_json if pages_json is not None else "",
            stamp,
        ),
    )
    return chapter_id


def delete_chapters_except(series_id, rel_paths):
    initialise()
    keep = set(rel_paths)
    with transaction() as connection:
        rows = _rows(
            connection.execute(
                "SELECT id, rel_path FROM chapters WHERE series_id = ?", (int(series_id),)
            )
        )
        for row in rows:
            if row["rel_path"] not in keep:
                connection.execute("DELETE FROM chapters WHERE id = ?", (row["id"],))


def update_chapter_pages(chapter_id, pages):
    execute(
        "UPDATE chapters SET pages_json = ?, page_count = ? WHERE id = ?",
        (json.dumps(pages, ensure_ascii=False), len(pages), int(chapter_id)),
    )


# ----------------------------------------------------------------- progress


def save_progress(user, series_id, chapter_id, page, total_pages, mode, direction, animation):
    execute(
        """INSERT INTO progress (user, series_id, chapter_id, page, total_pages, mode,
           direction, animation, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user, chapter_id) DO UPDATE SET
             page = excluded.page,
             total_pages = excluded.total_pages,
             mode = excluded.mode,
             direction = excluded.direction,
             animation = excluded.animation,
             updated_at = excluded.updated_at""",
        (
            user,
            int(series_id),
            int(chapter_id),
            max(0, int(page)),
            int(total_pages) if total_pages is not None else None,
            mode or "single",
            direction or "rtl",
            animation or "slide",
            now_iso(),
        ),
    )


def get_progress(user, chapter_id):
    return one(
        "SELECT * FROM progress WHERE user = ? AND chapter_id = ?",
        (user, int(chapter_id)),
    )


def list_progress(user, limit=100):
    return query(
        """SELECT p.*, c.title AS chapter_title, c.rel_path, s.title AS series_title
           FROM progress p
           JOIN chapters c ON c.id = p.chapter_id
           JOIN series s ON s.id = p.series_id
           WHERE p.user = ?
           ORDER BY p.updated_at DESC LIMIT ?""",
        (user, int(limit)),
    )


def series_progress(user, series_id):
    return query(
        """SELECT p.*, c.title AS chapter_title
           FROM progress p JOIN chapters c ON c.id = p.chapter_id
           WHERE p.user = ? AND p.series_id = ? ORDER BY p.updated_at DESC""",
        (user, int(series_id)),
    )


# --------------------------------------------------------------------- meta


def get_meta(key, default=""):
    row = one("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else default


def set_meta(key, value):
    execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def stats():
    return {
        "sources": one("SELECT COUNT(*) AS n FROM sources")["n"],
        "series": one("SELECT COUNT(*) AS n FROM series")["n"],
        "chapters": one("SELECT COUNT(*) AS n FROM chapters")["n"],
        "pages": one("SELECT COALESCE(SUM(page_count), 0) AS n FROM chapters")["n"],
    }
