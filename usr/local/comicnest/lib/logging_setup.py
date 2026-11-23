"""Logging in the TOS 7 format.

``[YYYY-MM-DD HH:MM:SS] [LEVEL] [component] message``
"""

import logging
import os
import sys
import threading

_CONFIGURED = False
_LOCK = threading.Lock()

_FORMAT = "[%(asctime)s] [%(levelname)s] [%(component)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_ROOT = "comicnest"

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class _ComponentFilter(logging.Filter):
    def filter(self, record):
        name = record.name
        record.component = "main" if name == _ROOT else (name.split(".")[-1] or "main")
        return True


def setup_logging(level=None, log_dir=None, to_file=False):
    global _CONFIGURED
    with _LOCK:
        if _CONFIGURED:
            return logging.getLogger(_ROOT)

        level_name = (level or os.environ.get("COMICNEST_LOG_LEVEL") or "INFO").upper()
        root = logging.getLogger(_ROOT)
        root.setLevel(_LEVELS.get(level_name, logging.INFO))
        root.handlers.clear()
        root.propagate = False

        formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)
        component_filter = _ComponentFilter()

        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        stream.addFilter(component_filter)
        root.addHandler(stream)

        resolved_dir = log_dir or os.environ.get("COMICNEST_LOG_DIR")
        if to_file and resolved_dir:
            try:
                os.makedirs(resolved_dir, exist_ok=True)
                handler = logging.FileHandler(
                    os.path.join(resolved_dir, "server.log"), encoding="utf-8"
                )
                handler.setFormatter(formatter)
                handler.addFilter(component_filter)
                root.addHandler(handler)
            except OSError as exc:
                root.warning("cannot open log file in %s: %s", resolved_dir, exc)

        _CONFIGURED = True
        return root


def get_logger(component):
    return logging.getLogger(_ROOT).getChild(component)
