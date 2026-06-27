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
    include_challengers = cfg.get("include_challengers", False)
    challenger_years = cfg.get("challenger_years", years)
    to_load = [y for y in years if str(y) not in mem["datasets_loaded"]]
    if not to_load:
        matches = datasource.fetch_matches(years, tours)
    else:
        log(f"Récupération internet des années : {to_load} | tours {tours}")
        matches = datasource.fetch_matches(to_load, tours)

    if include_challengers:
        chall = datasource.fetch_challengers(challenger_years, list(tours))
        existing_ids = {m["id"] for m in matches}
        new_chall = [m for m in chall if m["id"] not in existing_ids]
        if new_chall:
            log(f"Challengers/ITF : +{len(new_chall)} matchs chargés.")
            matches = matches + new_chall
            matches.sort(key=lambda m: (m["date"], m["id"]))

    learner.train(mem, matches, cfg)

    # Alimente la base solide : archive des matchs + dictionnaire joueurs.
    db.init()
    db.archive_matches(matches)
    db.sync_from_memory(mem)

    for y in to_load:
        if str(y) not in mem["datasets_loaded"]:
            mem["datasets_loaded"].append(str(y))
