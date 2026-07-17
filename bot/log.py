"""Journalisation simple : console + fichier (rotation par taille)."""
from __future__ import annotations

import datetime as _dt
import os
import threading

from . import config

_lock = threading.Lock()
_fh = None

# Rotation par taille : tennisboss.log -> .1 -> .2 -> .3 (le plus ancien écrasé).
# Le fichier croissait sans limite avant (docs/ARCHITECTURE_BLUEPRINT.md D-18).
_MAX_BYTES = int(os.environ.get("TENNISBOSS_LOG_MAX_MB", "10")) * 1024 * 1024
_KEEP = int(os.environ.get("TENNISBOSS_LOG_KEEP", "3"))


def _get_fh():
    global _fh
    if _fh is None:
        try:
            os.makedirs(config.LOGS_DIR, exist_ok=True)
            _fh = open(config.LOG_FILE, "a", encoding="utf-8", buffering=1)
        except OSError:
            pass
    return _fh


def _rotate_if_needed() -> None:
    """Rotation si le fichier dépasse _MAX_BYTES. Appelée sous _lock uniquement."""
    global _fh
    try:
        if _fh is None or _fh.tell() < _MAX_BYTES:
            return
        _fh.close()
        _fh = None
        for i in range(_KEEP - 1, 0, -1):
            src = f"{config.LOG_FILE}.{i}"
            if os.path.exists(src):
                os.replace(src, f"{config.LOG_FILE}.{i + 1}")
        os.replace(config.LOG_FILE, f"{config.LOG_FILE}.1")
        _get_fh()  # réouvre immédiatement : le fichier courant existe toujours
    except (OSError, ValueError):
        # Rotation ratée (fichier verrouillé, etc.) : on continue d'écrire
        # dans le fichier courant plutôt que de perdre des lignes.
        pass


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
                _rotate_if_needed()
        except OSError:
            pass
