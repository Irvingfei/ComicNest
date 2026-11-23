"""Reading image pages out of ZIP, TAR, RAR and 7z containers."""

import os
import posixpath
import tarfile
import zipfile
import xml.etree.ElementTree as ElementTree

from . import metadata, sevenzip
from .errors import ArchiveUnsupported, BadRequest, PageNotFound
from .logging_setup import get_logger

log = get_logger("archives")

_CB7 = {".cb7", ".7z"}
_RAR = {".cbr", ".rar"}
_TAR = {".tar"}


def supports(fmt):
    return fmt in (".zip", ".cbz") or fmt in _CB7 or fmt in _RAR or fmt in _TAR


def needs_sevenzip(fmt):
    return fmt in _CB7 or fmt in _RAR


def _normalise(name):
    return name.replace("\\", "/").lstrip("/")


def _is_page(name, extensions):
    cleaned = _normalise(name)
    if not cleaned or cleaned.endswith("/"):
        return False
    parts = cleaned.split("/")
    if any(part.startswith(".") or part.lower() in ("__macosx", "__MACOSX") for part in parts):
        return False
    base = posixpath.basename(cleaned)
    if base.casefold() == "comicinfo.xml":
        return False
    return os.path.splitext(base)[1].lower() in extensions


def _read_header(handle, size=65536):
    try:
        return handle.read(size)
    except (OSError, RuntimeError, zipfile.BadZipFile, tarfile.TarError):
        return b""


def list_pages(path, fmt, extensions):
    """Return ordered page descriptors with dimensions when they are readable."""
    fmt = fmt.lower()
    if fmt in (".zip", ".cbz"):
        return _list_zip(path, extensions)
    if fmt in _TAR:
        return _list_tar(path, extensions)
    if fmt in _RAR or fmt in _CB7:
        return _list_sevenzip(path, extensions)
    raise ArchiveUnsupported("unsupported archive format: %s" % fmt)


def _list_zip(path, extensions):
    try:
        with zipfile.ZipFile(path) as archive:
            entries = []
            for info in archive.infolist():
                if info.is_dir() or not _is_page(info.filename, extensions):
                    continue
                name = _normalise(info.filename)
                data = _read_header(archive.open(info))
                width, height = metadata.image_size(data) or (None, None)
                entries.append(
                    {"name": name, "size": info.file_size, "w": width, "h": height}
                )
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchiveUnsupported("the ZIP archive could not be read: %s" % exc)
    entries.sort(key=lambda item: metadata.natural_key(item["name"]))
    return entries


def _list_tar(path, extensions):
    try:
        with tarfile.open(path, "r:*") as archive:
            entries = []
            for info in archive.getmembers():
                if not info.isfile() or not _is_page(info.name, extensions):
                    continue
                name = _normalise(info.name)
                handle = archive.extractfile(info)
                data = _read_header(handle) if handle else b""
                width, height = metadata.image_size(data) or (None, None)
                entries.append(
                    {"name": name, "size": info.size, "w": width, "h": height}
                )
    except (tarfile.TarError, OSError) as exc:
        raise ArchiveUnsupported("the TAR archive could not be read: %s" % exc)
    entries.sort(key=lambda item: metadata.natural_key(item["name"]))
    return entries


def _list_sevenzip(path, extensions):
    entries = []
    for name, size, is_dir in sevenzip.list_archive(path):
        if is_dir or not _is_page(name, extensions):
            continue
        cleaned = _normalise(name)
        data = sevenzip.read_entry(path, name, limit=65536)
        width, height = metadata.image_size(data) or (None, None)
        entries.append({"name": cleaned, "size": size, "w": width, "h": height})
    entries.sort(key=lambda item: metadata.natural_key(item["name"]))
    return entries


def read_page(path, fmt, member, extensions, limit=128 * 1024 * 1024):
    fmt = fmt.lower()
    member = _normalise(member)
    if not _is_page(member, extensions):
        raise BadRequest("that entry is not a readable image")
    if fmt in (".zip", ".cbz"):
        try:
            with zipfile.ZipFile(path) as archive:
                info = archive.getinfo(member)
                if info.file_size > limit:
                    raise ArchiveUnsupported("the page is larger than the safety limit")
                with archive.open(info) as handle:
                    return handle.read()
        except KeyError:
            raise PageNotFound("the page is no longer in the archive")
        except (zipfile.BadZipFile, OSError) as exc:
            raise ArchiveUnsupported("the ZIP archive could not be read: %s" % exc)
    if fmt in _TAR:
        try:
            with tarfile.open(path, "r:*") as archive:
                for info in archive.getmembers():
                    if _normalise(info.name) == member and info.isfile():
                        handle = archive.extractfile(info)
                        if handle is None:
                            break
                        return handle.read(limit)
        except (tarfile.TarError, OSError) as exc:
            raise ArchiveUnsupported("the TAR archive could not be read: %s" % exc)
        raise PageNotFound("the page is no longer in the archive")
    if fmt in _RAR or fmt in _CB7:
        return sevenzip.read_entry(path, member, limit=limit)
    raise ArchiveUnsupported("unsupported archive format: %s" % fmt)


def read_comicinfo(path, fmt):
    """Return parsed ComicInfo.xml fields, or an empty dictionary."""
    raw = None
    fmt = fmt.lower()
    try:
        if fmt in (".zip", ".cbz"):
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    if posixpath.basename(_normalise(info.filename)).casefold() == "comicinfo.xml":
                        raw = archive.open(info).read(1024 * 1024)
                        break
        elif fmt in _TAR:
            with tarfile.open(path, "r:*") as archive:
                for info in archive.getmembers():
                    if posixpath.basename(_normalise(info.name)).casefold() == "comicinfo.xml":
                        handle = archive.extractfile(info)
                        raw = handle.read(1024 * 1024) if handle else None
                        break
        elif fmt in _RAR or fmt in _CB7:
            for name, _size, is_dir in sevenzip.list_archive(path):
                if not is_dir and posixpath.basename(_normalise(name)).casefold() == "comicinfo.xml":
                    raw = sevenzip.read_entry(path, name, limit=1024 * 1024)
                    break
    except (OSError, ArchiveUnsupported, zipfile.BadZipFile, tarfile.TarError):
        return {}
    if not raw:
        return {}
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return {}
    fields = {}
    for child in root:
        name = child.tag.split("}")[-1]
        value = (child.text or "").strip()
        if value:
            fields[name] = value
    return fields
