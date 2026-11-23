"""7-Zip adapter for RAR and 7z archives.

The binary is not assumed to exist. The caller can bundle one under
``vendor/7zip/`` or point ``COMICNEST_SEVEN_ZIP`` at it; otherwise the usual
command names are searched on PATH.
"""

import os
import shutil
import subprocess
import threading

from .config import config
from .errors import ArchiveUnsupported
from .logging_setup import get_logger

log = get_logger("7zip")

_CACHE = {"path": None, "checked": False}
_LOCK = threading.Lock()
_NAMES = ("7zz", "7z", "7za", "7zr")


def find_binary():
    with _LOCK:
        if _CACHE["checked"]:
            return _CACHE["path"]
        candidates = []
        if config.seven_zip:
            candidates.append(config.seven_zip)
        vendor = os.path.join(config.app_root, "vendor", "7zip")
        for name in _NAMES:
            candidates.append(os.path.join(vendor, name))
            candidates.append(os.path.join(vendor, name + ".exe"))
        for directory in ("x86_64", "aarch64", "arm64", "amd64"):
            for name in _NAMES:
                candidates.append(os.path.join(vendor, directory, name))
                candidates.append(os.path.join(vendor, directory, name + ".exe"))
        for name in _NAMES:
            found = shutil.which(name)
            if found:
                candidates.append(found)
        for candidate in candidates:
            if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                _CACHE["path"] = candidate
                break
        _CACHE["checked"] = True
        return _CACHE["path"]


def available():
    return find_binary() is not None


def _run(args, timeout=120):
    binary = find_binary()
    if not binary:
        raise ArchiveUnsupported(
            "7-Zip is required for RAR and 7z archives and was not found"
        )
    environment = dict(os.environ)
    environment.setdefault("LANG", "C.UTF-8")
    try:
        return subprocess.run(
            [binary] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        raise ArchiveUnsupported("the archive tool timed out")
    except OSError as exc:
        raise ArchiveUnsupported("the archive tool could not be started: %s" % exc)


def list_archive(path):
    """Return ``[(name, size, is_dir)]`` for every entry in the archive."""
    result = _run(["l", "-slt", "-sccUTF-8", "--", path])
    if result.returncode != 0:
        message = (result.stderr or b"").decode("utf-8", "replace").strip()
        raise ArchiveUnsupported(message or "the archive could not be read")

    entries = []
    block = {}
    for raw in (result.stdout or b"").decode("utf-8", "replace").splitlines():
        line = raw.rstrip()
        if not line:
            _append_block(entries, block)
            block = {}
            continue
        if " = " in line:
            key, _, value = line.partition(" = ")
            block[key.strip()] = value.strip()
    _append_block(entries, block)
    return entries


def _append_block(entries, block):
    name = block.get("Path")
    if not name:
        return
    if block.get("Folder") == "+" or block.get("Attributes", "").startswith("D"):
        entries.append((name, 0, True))
        return
    try:
        size = int(block.get("Size") or 0)
    except ValueError:
        size = 0
    entries.append((name, size, False))


def read_entry(path, member, limit=64 * 1024 * 1024):
    result = _run(["e", "-so", "-y", "-sccUTF-8", "--", path, member], timeout=120)
    if result.returncode != 0:
        message = (result.stderr or b"").decode("utf-8", "replace").strip()
        raise ArchiveUnsupported(message or "the archive entry could not be read")
    data = result.stdout or b""
    if len(data) > limit:
        raise ArchiveUnsupported("the archive entry is larger than the safety limit")
    return data
