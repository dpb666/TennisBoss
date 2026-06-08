"""Cotes via odds-api.io (clé ODDS_API_KEY, lue depuis .env).

Doc : https://docs.odds-api.io/  — base https://api.odds-api.io/v3
  GET /sports
  GET /events?sport=tennis
  GET /odds?eventId={id}&bookmakers={liste}

NOTE plan : la clé fournie autorise 2 bookmakers (MelBet, Betfair Exchange),
qui exposent le marché "ML" = vainqueur du MATCH (pas le 1er set). On s'en sert
donc comme signal marché du vainqueur de match, clairement étiqueté comme tel.
Le marché "First Set Winner" nécessiterait un plan/bookmaker le proposant.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

from .live_api import load_env
from .log import log

BASE = "https://api.odds-api.io/v3"
# Bookmakers autorisés par le plan actuel (modifiable si vous montez de palier).
DEFAULT_BOOKMAKERS = "MelBet,Betfair Exchange"


def _key() -> Optional[str]:
    load_env()
    v = (os.environ.get("ODDS_API_KEY") or "").strip()
    return v or None


def is_enabled() -> bool:
    return _key() is not None


def fetch_tennis_events(upcoming_only: bool = True) -> List[Dict[str, Any]]:
    """Liste des événements tennis (id, home, away, date, league, status)."""
    key = _key()
    if not key:
        return []
    try:
        r = requests.get(f"{BASE}/events", params={"sport": "tennis", "apiKey": key},
                         timeout=20)
        r.raise_for_status()
        events = r.json()
    except (requests.RequestException, ValueError) as exc:
        log(f"odds-api.io /events indisponible ({exc}).", "WARN")
        return []
    if not isinstance(events, list):
        return []
    if upcoming_only:
        events = [e for e in events
                  if e.get("status") in ("pending", "live", "inplay", "not_started")]
    return events


def build_event_index(events: List[Dict[str, Any]]) -> Dict[frozenset, Dict[str, Any]]:
    """Index { {nom_famille_1, nom_famille_2} -> event } pour apparier 2 fournisseurs."""
    from .namematch import split_name

    idx: Dict[frozenset, Dict[str, Any]] = {}
    for e in events:
        _, l1 = split_name(e.get("home", ""))
        _, l2 = split_name(e.get("away", ""))
        if l1 and l2 and l1 != l2:
            idx[frozenset((l1, l2))] = e
    return idx


def find_event(index: Dict[frozenset, Dict[str, Any]],
               name1: str, name2: str) -> Optional[Dict[str, Any]]:
    """Retrouve l'événement odds-api.io pour deux joueurs (par noms de famille)."""
    from .namematch import split_name

    _, l1 = split_name(name1)
    _, l2 = split_name(name2)
    if not l1 or not l2:
        return None
    return index.get(frozenset((l1, l2)))


def fetch_match_winner(event_id: Any,
                       bookmakers: str = DEFAULT_BOOKMAKERS) -> Optional[Dict[str, Any]]:
    """Cotes "ML" (vainqueur de match) -> probabilités implicites SANS vig.

    Renvoie {home_prob, away_prob, home_odds, away_odds, books} ou None.
    """
    key = _key()
    if not key:
        return None
    try:
        r = requests.get(f"{BASE}/odds", params={
            "eventId": event_id, "bookmakers": bookmakers, "apiKey": key}, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json()
    except (requests.RequestException, ValueError):
        return None

    books = data.get("bookmakers") or {}
    homes, aways, used = [], [], []
    for bname, markets in books.items():
        if not isinstance(markets, list):
            continue
        for mk in markets:
            if (mk.get("name") or "").upper() != "ML":
                continue
            for line in mk.get("odds", []):
                try:
                    ho, ao = float(line["home"]), float(line["away"])
                except (KeyError, ValueError, TypeError):
                    continue
                if ho > 1 and ao > 1:
                    homes.append(ho)
                    aways.append(ao)
                    used.append(bname)
    if not homes:
        return None

    # Moyenne des cotes puis retrait de la marge (no-vig).
    ho = sum(homes) / len(homes)
    ao = sum(aways) / len(aways)
    inv_h, inv_a = 1.0 / ho, 1.0 / ao
    total = inv_h + inv_a
    return {
        "home_prob": round(inv_h / total, 4),
        "away_prob": round(inv_a / total, 4),
        "home_odds": round(ho, 2),
        "away_odds": round(ao, 2),
        "books": sorted(set(used)),
    }
