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
    """Renvoie (initiale_prenom, nom_de_famille) normalisés.

    Gère les deux formats rencontrés :
      "Alexander Zverev" / "A. Zverev"   -> prénom d'abord
      "Zverev, Alexander"                -> nom de famille d'abord (virgule)
    """
    raw = name or ""
    if "," in raw:
        last_part, _, first_part = raw.partition(",")
        last = _norm(last_part).split()
        first = _norm(first_part).split()
        return (first[0][:1] if first else ""), (last[-1] if last else "")

    parts = _norm(raw).split()
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
    """Tente de retrouver le nom complet correspondant à un nom d'API.

    Format "Nom, Prénom" (odds-api.io) : on a le prénom complet → on
    compare prénom ET nom de famille pour éviter les faux positifs
    (ex. "Garcia, Jose" ≠ "Caroline Garcia").
    """
    init, last = split_name(api_name)
    candidates = index.get(last)
    if not candidates:
        return None
    if len(candidates) == 1:
        # Même si un seul candidat, vérifier cohérence de l'initiale
        if init:
            f_init, _ = split_name(candidates[0])
            if f_init and f_init != init:
                return None  # faux positif : même nom de famille, prénom incompatible
        return candidates[0]

    # Plusieurs candidats : priorité à l'initiale exacte
    matches_init = []
    for full in candidates:
        f_init, _ = split_name(full)
        if init and f_init == init:
            matches_init.append(full)

    if len(matches_init) == 1:
        return matches_init[0]
    if matches_init:
        return matches_init[0]  # plusieurs homonymes avec même initiale → le plus fiable

    # Aucune initiale commune — ne pas retourner un joueur au hasard
    if init:
        return None
    return candidates[0]
