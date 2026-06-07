"""Mémoire persistante du bot (écriture atomique sur disque)."""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict

from . import config
from .log import log


def default_memory() -> Dict[str, Any]:
    """État initial de la mémoire (créé au premier démarrage)."""
    return {
        "version": 1,
        # Poids appris (initialisés avec le prior de votre script).
        "weights": dict(config.PRIOR_WEIGHTS),
        "bias": 0.0,
        # Profils joueurs : nom -> {serve, return1, return2, recent, n}.
        "players": {},
        # Matchs déjà appris (pour ne pas réapprendre deux fois).
        "processed": [],
        # Indicateurs de performance.
        "metrics": {
            "predictions": 0,
            "correct": 0,
            "accuracy": 0.0,
            "last_loss": None,
        },
        # Battement de cœur.
        "heartbeat": {"count": 0, "last_iso": None},
        # Jeux de données déjà chargés depuis internet.
        "datasets_loaded": [],
    }


def load() -> Dict[str, Any]:
    """Charge la mémoire ; reconstruit en cas de fichier corrompu (self-healing)."""
    if not os.path.exists(config.MEMORY_FILE):
        return default_memory()
    try:
        with open(config.MEMORY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Complète les clés manquantes si le schéma a évolué.
        base = default_memory()
        for key, val in base.items():
            data.setdefault(key, val)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log(f"Mémoire illisible ({exc}); réinitialisation.", "WARN")
        _backup_corrupt()
        return default_memory()


def save(mem: Dict[str, Any]) -> None:
    """Écriture atomique : tmp -> os.replace (évite la corruption si crash)."""
    os.makedirs(config.STATE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=config.STATE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(mem, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, config.MEMORY_FILE)
    except OSError as exc:
        log(f"Échec de sauvegarde mémoire : {exc}", "ERROR")
        if os.path.exists(tmp):
            os.remove(tmp)


def _backup_corrupt() -> None:
    try:
        if os.path.exists(config.MEMORY_FILE):
            os.replace(config.MEMORY_FILE, config.MEMORY_FILE + ".corrupt")
    except OSError:
        pass
