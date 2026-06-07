"""Journalisation simple : console + fichier."""
from __future__ import annotations

import datetime as _dt
import os

from . import config


def _ts() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str, level: str = "INFO") -> None:
    line = f"[{_ts()}] [{level}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(config.LOGS_DIR, exist_ok=True)
        with open(config.LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        # On ne fait jamais planter le bot à cause du log.
        pass
