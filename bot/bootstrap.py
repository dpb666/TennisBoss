"""Amorçage (bootstrap) : prépare l'environnement au premier démarrage."""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from . import config
from .log import log


def bootstrap() -> Dict[str, Any]:
    """Crée les dossiers et le fichier de config s'ils n'existent pas.

    Renvoie la configuration effective (fusion défauts + fichier).
    """
    os.makedirs(config.STATE_DIR, exist_ok=True)
    os.makedirs(config.LOGS_DIR, exist_ok=True)

    cfg = dict(config.DEFAULT_CONFIG)
    if os.path.exists(config.CONFIG_FILE):
        try:
            with open(config.CONFIG_FILE, "r", encoding="utf-8") as fh:
                cfg.update(json.load(fh))
        except (json.JSONDecodeError, OSError) as exc:
            log(f"config.json illisible ({exc}); valeurs par défaut.", "WARN")
    else:
        with open(config.CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(config.DEFAULT_CONFIG, fh, ensure_ascii=False, indent=2)
        log("Bootstrap : config.json créé avec les valeurs par défaut.")

    return cfg
