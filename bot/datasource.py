"""Récupération des données depuis internet (sans clé API).

Source principale : dataset ATP de Jeff Sackmann (CSV par année) qui contient
les statistiques détaillées de chaque match (points au service, returns...).
À partir de ces données réelles, le bot calcule les profils joueurs et apprend.

Une tentative "live" (Sofascore) est faite mais souvent bloquée (403) : dans ce
cas on bascule proprement sur l'historique — c'est le rôle du self-healing.
"""
from __future__ import annotations

import csv
import io
from typing import Dict, List, Optional

import requests

from . import config
from .log import log


def _http_get(url: str, timeout: int = 20) -> Optional[str]:
    """GET robuste avec user-agent navigateur. Renvoie None en cas d'échec."""
    try:
        resp = requests.get(
            url, headers={"User-Agent": config.BROWSER_UA}, timeout=timeout
        )
        if resp.status_code == 200:
            return resp.text
        log(f"GET {url} -> HTTP {resp.status_code}", "WARN")
    except requests.RequestException as exc:
        log(f"GET {url} a échoué : {exc}", "WARN")
    return None


def _f(row: Dict[str, str], key: str) -> Optional[float]:
    """Lecture tolérante d'un champ numérique."""
    val = row.get(key, "")
    if val is None or val == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _match_features(row: Dict[str, str]) -> Optional[Dict]:
    """Transforme une ligne brute en stats normalisées [0,1] pour les 2 joueurs.

    serve   = % de points gagnés au service
    return1 = % de points gagnés au retour sur 1re balle adverse
    return2 = % de points gagnés au retour sur 2e balle adverse
    """
    w_svpt, l_svpt = _f(row, "w_svpt"), _f(row, "l_svpt")
    w_1stIn, l_1stIn = _f(row, "w_1stIn"), _f(row, "l_1stIn")
    w_1stW, l_1stW = _f(row, "w_1stWon"), _f(row, "l_1stWon")
    w_2ndW, l_2ndW = _f(row, "w_2ndWon"), _f(row, "l_2ndWon")

    needed = [w_svpt, l_svpt, w_1stIn, l_1stIn, w_1stW, l_1stW, w_2ndW, l_2ndW]
    if any(v is None or v <= 0 for v in (w_svpt, l_svpt, w_1stIn, l_1stIn)):
        return None
    if any(v is None for v in needed):
        return None

    w_2ndpts = w_svpt - w_1stIn
    l_2ndpts = l_svpt - l_1stIn
    if w_2ndpts <= 0 or l_2ndpts <= 0:
        return None

    def ratio(num: float, den: float) -> float:
        return max(0.0, min(1.0, num / den)) if den > 0 else 0.5

    winner = {
        "serve": ratio(w_1stW + w_2ndW, w_svpt),
        "return1": ratio(l_1stIn - l_1stW, l_1stIn),     # retour sur 1re balle adverse
        "return2": ratio(l_2ndpts - l_2ndW, l_2ndpts),   # retour sur 2e balle adverse
    }
    loser = {
        "serve": ratio(l_1stW + l_2ndW, l_svpt),
        "return1": ratio(w_1stIn - w_1stW, w_1stIn),
        "return2": ratio(w_2ndpts - w_2ndW, w_2ndpts),
    }

    return {
        "id": f"{row.get('tourney_id','?')}-{row.get('match_num','?')}",
        "date": row.get("tourney_date", "00000000"),
        "winner_name": (row.get("winner_name") or "").strip(),
        "loser_name": (row.get("loser_name") or "").strip(),
        "winner": winner,
        "loser": loser,
    }


def fetch_year(year: int) -> List[Dict]:
    """Télécharge et parse une année ATP. Renvoie une liste de matchs exploitables."""
    url = config.SACKMANN_URL.format(year=year)
    text = _http_get(url)
    if not text:
        return []
    matches: List[Dict] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        feat = _match_features(row)
        if feat and feat["winner_name"] and feat["loser_name"]:
            matches.append(feat)
    log(f"Année {year}: {len(matches)} matchs exploitables récupérés.")
    return matches


def fetch_matches(years: List[int]) -> List[Dict]:
    """Récupère plusieurs années et trie chronologiquement (sans fuite de données)."""
    all_matches: List[Dict] = []
    for year in years:
        all_matches.extend(fetch_year(year))
    all_matches.sort(key=lambda m: (m["date"], m["id"]))
    return all_matches


def probe_live() -> bool:
    """Teste l'accès au flux live. Renvoie False si bloqué (déclenche le fallback)."""
    try:
        resp = requests.get(
            config.SOFASCORE_LIVE_URL,
            headers={"User-Agent": config.BROWSER_UA},
            timeout=10,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False
