"""Credentials for remote sources.

Passwords never go into SQLite and are never returned by the API. The database
stores only an opaque reference; the value lives in a 0600 JSON file under the
application data directory.
"""

import json
import os
import secrets
import threading

from .config import config

_LOCK = threading.RLock()


def _read():
    try:
        with open(config.secrets_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data):
    os.makedirs(os.path.dirname(config.secrets_path), exist_ok=True)
    temporary = config.secrets_path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, config.secrets_path)
    try:
        os.chmod(config.secrets_path, 0o600)
    except OSError:
        pass


def put(value):
    with _LOCK:
        data = _read()
        ref = secrets.token_hex(12)
        data[ref] = value
        _write(data)
        return ref


def get(ref):
    if not ref:
        return ""
    with _LOCK:
        return _read().get(ref, "")


def delete(ref):
    if not ref:
        return
    with _LOCK:
        data = _read()
        if data.pop(ref, None) is not None:
            _write(data)


def rotate(ref, value):
    with _LOCK:
        data = _read()
        if ref:
            data[ref] = value
        else:
            ref = secrets.token_hex(12)
            data[ref] = value
        _write(data)
        return ref
