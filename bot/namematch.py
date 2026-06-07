"""Résolution de noms : relie un nom d'API (ex. "A. Zverev") au nom complet
appris en base (ex. "Alexander Zverev").

Stratégie simple et robuste :
  - on compare sur le NOM DE FAMILLE (insensible à la casse/accents) ;
  - en cas d'homonymes, on départage par l'INITIALE du prénom ;
  - on privilégie le joueur ayant vu le plus de matchs (profil le plus fiable).
"""
from __future__ import annotations

import unicodedata
from typing import Dict, List, Optional, Tuple


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _norm(s: str) -> str:
    return _strip_accents(s or "").lower().replace(".", " ").strip()


def split_name(name: str) -> Tuple[str, str]:
    """Renvoie (initiale_prenom, nom_de_famille) normalisés."""
    parts = _norm(name).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return parts[0][:1], parts[-1]


def build_index(names: List[str], counts: Dict[str, int]) -> Dict[str, List[str]]:
    """Index nom_de_famille -> [noms complets], triés par fiabilité (n décroissant)."""
    index: Dict[str, List[str]] = {}
    for full in names:
        _, last = split_name(full)
        index.setdefault(last, []).append(full)
    for last, lst in index.items():
        lst.sort(key=lambda n: counts.get(n, 0), reverse=True)
    return index


def resolve(api_name: str, index: Dict[str, List[str]]) -> Optional[str]:
    """Tente de retrouver le nom complet correspondant à un nom d'API."""
    init, last = split_name(api_name)
    candidates = index.get(last)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    # Plusieurs joueurs avec ce nom de famille : départage par initiale du prénom.
    for full in candidates:
        f_init, _ = split_name(full)
        if init and f_init == init:
            return full
    return candidates[0]  # défaut : le plus fiable
