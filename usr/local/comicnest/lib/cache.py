"""On-demand cache for remote files.

A remote archive has to be present locally before its entries can be listed or
read. Downloads happen once, atomically, and are evicted oldest-first when the
configured budget is exceeded.
"""

import hashlib
import os
import shutil
import threading
import time

from .config import config
from .logging_setup import get_logger

log = get_logger("cache")

_LOCKS = {}
_LOCKS_LOCK = threading.Lock()


def _lock_for(key):
    with _LOCKS_LOCK:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def path_for(source_id, rel, extension=""):
    digest = hashlib.sha1(rel.encode("utf-8", "surrogatepass")).hexdigest()
    directory = os.path.join(config.cache_dir, str(int(source_id)))
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, digest + extension)


def touch(path):
    try:
        os.utime(path, None)
    except OSError:
        pass


def ensure(backend, source_id, rel, expected_size=None, extension="", progress=None):
    """Return a local path for ``rel``, downloading it when necessary."""
    local = backend.local_path(rel)
    if local:
        return local

    target = path_for(source_id, rel, extension)
    lock = _lock_for(target)
    with lock:
        if os.path.isfile(target):
            if expected_size is None or os.path.getsize(target) == expected_size:
                touch(target)
                return target
            try:
                os.remove(target)
            except OSError:
                pass

        temporary = target + ".part"
        try:
            backend.download(rel, temporary, progress=progress)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                try:
                    os.remove(temporary)
                except OSError:
                    pass
    touch(target)
    evict()
    return target


def read(backend, source_id, rel, extension="", limit=None):
    local = backend.local_path(rel)
    if local:
        with open(local, "rb") as handle:
            return handle.read(limit) if limit else handle.read()
    path = ensure(backend, source_id, rel, extension=extension)
    with open(path, "rb") as handle:
        return handle.read(limit) if limit else handle.read()


def evict(max_bytes=None):
    budget = max_bytes or config.max_cache_bytes
    files = []
    total = 0
    for base, _dirs, names in os.walk(config.cache_dir):
        for name in names:
            if name.endswith(".part") or name.endswith(".meta"):
                continue
            path = os.path.join(base, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            files.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size

    if total <= budget:
        return 0

    files.sort()
    removed = 0
    for _mtime, size, path in files:
        try:
            os.remove(path)
            total -= size
            removed += 1
        except OSError:
            continue
        if total <= budget:
            break
    if removed:
        log.info("evicted %d cached files, %d bytes remain", removed, total)
    return removed


def clear():
    shutil.rmtree(config.cache_dir, ignore_errors=True)
    os.makedirs(config.cache_dir, exist_ok=True)


def size():
    total = 0
    for base, _dirs, names in os.walk(config.cache_dir):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total
