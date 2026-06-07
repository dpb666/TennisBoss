"""Profils joueurs : mémoire glissante (EMA) des forces individuelles.

Chaque joueur est résumé par un vecteur dans [0,1] :
  serve, return1, return2  -> moyennes exponentielles des perfs match après match
  recent                   -> forme récente (EMA des victoires : 1=gagné, 0=perdu)
  n                        -> nombre de matchs vus

L'EMA borne la taille de la mémoire (pas de listes qui grossissent) tout en
donnant plus de poids aux matchs récents.
"""
from __future__ import annotations

from typing import Any, Dict

from . import config

_NEUTRAL = {"serve": 0.5, "return1": 0.5, "return2": 0.5, "recent": 0.5, "n": 0}


def get_profile(mem: Dict[str, Any], name: str) -> Dict[str, float]:
    """Renvoie le profil d'un joueur (neutre s'il est inconnu)."""
    return mem["players"].get(name, dict(_NEUTRAL))


def feature_vector(profile: Dict[str, float]) -> Dict[str, float]:
    """Extrait le vecteur de features ordonné utilisé par le modèle."""
    return {k: float(profile.get(k, 0.5)) for k in config.FEATURE_ORDER}


def update_profile(
    mem: Dict[str, Any], name: str, perf: Dict[str, float], won: bool, alpha: float
) -> None:
    """Met à jour le profil d'un joueur après un match (EMA)."""
    prof = mem["players"].get(name)
    if prof is None:
        # Premier match observé : on initialise directement avec la perf.
        prof = {
            "serve": perf["serve"],
            "return1": perf["return1"],
            "return2": perf["return2"],
            "recent": 1.0 if won else 0.0,
            "n": 0,
        }
    else:
        for k in ("serve", "return1", "return2"):
            prof[k] = (1 - alpha) * prof[k] + alpha * perf[k]
        prof["recent"] = (1 - alpha) * prof["recent"] + alpha * (1.0 if won else 0.0)
    prof["n"] = int(prof.get("n", 0)) + 1
    mem["players"][name] = prof


def is_confident(profile: Dict[str, float]) -> bool:
    return int(profile.get("n", 0)) >= config.DEFAULT_CONFIG["min_matches_confident"]
