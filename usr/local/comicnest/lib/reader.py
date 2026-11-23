"""Turning index rows into bytes: page lists, pages, covers and PDFs."""

import io
import json
import os
import posixpath
import html

from . import archives, cache, config as _config, db, metadata, sources
from .config import config
from .errors import ChapterNotFound, NotFound, PageNotFound, SourceUnavailable, UnsupportedMedia
from .logging_setup import get_logger

log = get_logger("reader")

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".avif": "image/avif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".pdf": "application/pdf",
}


def _extension(name):
    return os.path.splitext(name or "")[1].lower()


def parse_pages(chapter_row):
    raw = chapter_row.get("pages_json") or ""
    if not raw:
        return []
    try:
        pages = json.loads(raw)
    except ValueError:
        return []
    return pages if isinstance(pages, list) else []


def _with_context(chapter_row):
    if chapter_row and "source_id" not in chapter_row:
        full = db.get_chapter(chapter_row["id"])
        if full:
            return full
    return chapter_row


def backend_for_chapter(chapter_row):
    chapter_row = _with_context(chapter_row)
    source = db.get_source(chapter_row["source_id"])
    if not source:
        raise SourceUnavailable("the source for this chapter no longer exists")
    return source, sources.backend_for(source)


def resolve_pages(chapter_row, force=False):
    """Return the page list, materialising a remote archive when needed."""
    chapter_row = _with_context(chapter_row)
    kind = chapter_row.get("kind")
    if kind == "pdf":
        return []
    pages = parse_pages(chapter_row)
    if pages and not force:
        return pages

    source, backend = backend_for_chapter(chapter_row)
    if kind == "folder":
        entries = backend.list_dir(chapter_row["rel_path"])
        images = [
            entry
            for entry in entries
            if not entry.is_dir and _extension(entry.name) in config.page_extensions
        ]
        images.sort(key=lambda entry: metadata.natural_key(entry.name))
        pages = []
        for entry in images:
            name = entry.name
            width = height = None
            parent = chapter_row["rel_path"]
            rel = posixpath.join(parent, name) if parent else name
            try:
                header = backend.read_bytes(rel, length=65536)
                width, height = metadata.image_size(header) or (None, None)
            except Exception:
                width, height = None, None
            pages.append({"name": name, "size": entry.size, "w": width, "h": height})
        db.update_chapter_pages(chapter_row["id"], pages)
        return pages

    if kind == "archive":
        if backend.kind != "local" and not archives.needs_sevenzip(chapter_row["format"]):
            pass
        local = cache.ensure(
            backend,
            source["id"],
            chapter_row["rel_path"],
            expected_size=chapter_row.get("size_bytes") or None,
            extension=chapter_row.get("format") or _extension(chapter_row["rel_path"]),
        )
        pages = archives.list_pages(local, chapter_row["format"], config.page_extensions)
        db.update_chapter_pages(chapter_row["id"], pages)
        return pages

    return []


def page_bytes(chapter_row, index):
    chapter_row = _with_context(chapter_row)
    pages = resolve_pages(chapter_row)
    try:
        page = pages[int(index)]
    except (IndexError, ValueError):
        raise PageNotFound("that page does not exist")
    source, backend = backend_for_chapter(chapter_row)

    if chapter_row["kind"] == "folder":
        parent = chapter_row["rel_path"]
        rel = posixpath.join(parent, page["name"]) if parent else page["name"]
        data = cache.read(backend, source["id"], rel, extension=_extension(page["name"]))
    elif chapter_row["kind"] == "archive":
        local = cache.ensure(
            backend,
            source["id"],
            chapter_row["rel_path"],
            expected_size=chapter_row.get("size_bytes") or None,
            extension=chapter_row.get("format") or _extension(chapter_row["rel_path"]),
        )
        data = archives.read_page(
            local, chapter_row["format"], page["name"], config.page_extensions
        )
    else:
        raise PageNotFound("this chapter does not have image pages")

    data, mime = _convert_for_browser(data, page.get("name") or "")
    return data, mime


def pdf_path(chapter_row):
    chapter_row = _with_context(chapter_row)
    source, backend = backend_for_chapter(chapter_row)
    return cache.ensure(
        backend,
        source["id"],
        chapter_row["rel_path"],
        expected_size=chapter_row.get("size_bytes") or None,
        extension=".pdf",
    )


def pdf_url_date(chapter_row):
    return float(chapter_row.get("mtime_ns") or 0) / 1e9


def _convert_for_browser(data, name):
    extension = _extension(name)
    mime = _MIME.get(extension, "application/octet-stream")
    if extension not in (".tif", ".tiff"):
        return data, mime
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        raise UnsupportedMedia(
            "TIFF pages need the optional Pillow component, which is not installed"
        )
    with Image.open(io.BytesIO(data)) as image:
        output = io.BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=90)
        return output.getvalue(), "image/jpeg"


def cover_bytes(series_row):
    series_id = series_row["id"]
    cached = _cover_cache_path(series_id)
    if cached and os.path.isfile(cached):
        with open(cached, "rb") as handle:
            return handle.read(), _mime_for_file(cached)

    chapters = db.list_chapters(series_id)
    if not chapters:
        raise NotFound("this series has no chapters")
    chapter = None
    if series_row.get("cover_chapter_id"):
        for row in chapters:
            if row["id"] == series_row["cover_chapter_id"]:
                chapter = row
                break
    chapter = chapter or chapters[0]

    if chapter.get("kind") == "pdf":
        data, mime = _pdf_placeholder(series_row, chapter)
        _write_cover_cache(series_id, data, ".svg")
        return data, mime

    pages = resolve_pages(chapter)
    if not pages:
        raise NotFound("this chapter has no readable pages")
    data, mime = page_bytes(chapter, int(series_row.get("cover_page") or 0))
    data, extension = _thumbnail(data, mime)
    _write_cover_cache(series_id, data, extension)
    return data, _mime_for_file("cover" + extension)


def _thumbnail(data, mime, width=640):
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return data, _extension_for_mime(mime)
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.thumbnail((width, width * 2))
            output = io.BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=82)
            return output.getvalue(), ".jpg"
    except Exception:
        return data, _extension_for_mime(mime)


def _extension_for_mime(mime):
    for extension, value in _MIME.items():
        if value == mime:
            return extension
    return ".bin"


def _cover_cache_path(series_id):
    for extension in (".jpg", ".png", ".webp", ".gif", ".bmp", ".svg", ".bin"):
        path = os.path.join(config.covers_dir, "%d%s" % (series_id, extension))
        if os.path.isfile(path):
            return path
    return None


def _write_cover_cache(series_id, data, extension):
    try:
        for extension_name in (".jpg", ".png", ".webp", ".gif", ".bmp", ".svg", ".bin"):
            path = os.path.join(config.covers_dir, "%d%s" % (series_id, extension_name))
            if os.path.exists(path):
                os.remove(path)
        with open(os.path.join(config.covers_dir, "%d%s" % (series_id, extension)), "wb") as handle:
            handle.write(data)
    except OSError:
        pass


def _mime_for_file(path):
    return _MIME.get(_extension(path), "image/svg+xml" if path.endswith(".svg") else "application/octet-stream")


def cover_placeholder(series_row):
    return _pdf_placeholder(series_row, {})


def _pdf_placeholder(series_row, chapter_row):
    title = html.escape(series_row.get("title") or chapter_row.get("title") or "Comic")
    subtitle = html.escape(chapter_row.get("title") or "")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900" viewBox="0 0 600 900">'
        '<rect width="600" height="900" fill="#17181c"/>'
        '<rect x="56" y="56" width="488" height="788" rx="10" fill="none" stroke="#34363d" stroke-width="2"/>'
        '<text x="300" y="420" text-anchor="middle" fill="#e9e6df" font-family="Georgia,serif" font-size="42">%s</text>'
        '<text x="300" y="474" text-anchor="middle" fill="#8f9096" font-family="sans-serif" font-size="20">%s</text>'
        "</svg>"
    ) % (title, subtitle)
    return svg.encode("utf-8"), "image/svg+xml"
