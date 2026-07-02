"""Journalisation simple : console + fichier."""
from __future__ import annotations

import datetime as _dt
import os
import threading

from . import config

_lock = threading.Lock()
_fh = None


def _get_fh():
    global _fh
    if _fh is None:
        try:
            os.makedirs(config.LOGS_DIR, exist_ok=True)
            _fh = open(config.LOG_FILE, "a", encoding="utf-8", buffering=1)
        except OSError:
            pass
    return _fh


def _ts() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str, level: str = "INFO") -> None:
    line = f"[{_ts()}] [{level}] {msg}"
    with _lock:
        print(line, flush=True)
        try:
            fh = _get_fh()
            if fh:
                fh.write(line + "\n")
        except OSError:
            pass
