"""Superviseur : boucle autonome + self-healing.

Responsabilités :
  - battement de cœur régulier,
  - cycles d'apprentissage périodiques (récupération internet + self-learning),
  - sauvegarde de la mémoire après chaque cycle,
  - capture de TOUTE exception : on log, on sauvegarde, on attend (backoff
    exponentiel) puis on repart -> le bot ne meurt pas sur une erreur.
"""
from __future__ import annotations

import time
from typing import Any, Dict

from . import datasource, db, heartbeat, learner, memory
from .bootstrap import bootstrap
from .log import log


def run_forever() -> None:
    cfg = bootstrap()
    mem = memory.load()
    log("=== TennisBoss démarré (mode autonome) ===")
    log(f"Flux live accessible : {datasource.probe_live()} (sinon -> historique)")

    backoff = cfg["backoff_start"]
    last_learn = 0.0

    while True:
        try:
            heartbeat.tick(mem)

            now = time.time()
            if now - last_learn >= cfg["learn_interval"] or not mem["datasets_loaded"]:
                _learn_cycle(mem, cfg)
                last_learn = now

            memory.save(mem)
            backoff = cfg["backoff_start"]  # tout va bien -> on remet le backoff à zéro
            time.sleep(cfg["heartbeat_interval"])

        except KeyboardInterrupt:
            log("Arrêt demandé (Ctrl-C). Sauvegarde finale.")
            memory.save(mem)
            return
        except Exception as exc:  # noqa: BLE001  (self-healing volontaire)
            log(f"Erreur capturée : {exc!r} -> self-healing, backoff {backoff}s", "ERROR")
            try:
                memory.save(mem)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(backoff)
            backoff = min(backoff * 2, cfg["backoff_max"])


def _learn_cycle(mem: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    """Récupère les données manquantes puis lance un cycle de self-learning."""
    years = cfg["years"]
    tours = cfg.get("tours", ["atp"])
    to_load = [y for y in years if str(y) not in mem["datasets_loaded"]]
    if not to_load:
        # Déjà tout chargé : on réapprend sur les éventuels nouveaux matchs.
        matches = datasource.fetch_matches(years, tours)
    else:
        log(f"Récupération internet des années : {to_load} | tours {tours}")
        matches = datasource.fetch_matches(to_load, tours)

    learner.train(mem, matches, cfg)

    # Alimente la base solide : archive des matchs + dictionnaire joueurs.
    db.init()
    db.archive_matches(matches)
    db.sync_from_memory(mem)

    for y in to_load:
        if str(y) not in mem["datasets_loaded"]:
            mem["datasets_loaded"].append(str(y))
