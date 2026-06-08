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
import time
from typing import Any, Dict, List, Optional

import requests

from .live_api import load_env
from .log import log

BASE = "https://api.odds-api.io/v3"
# Bookmakers autorisés par le plan actuel (modifiable si vous montez de palier).
DEFAULT_BOOKMAKERS = "MelBet,Betfair Exchange"

# Durées de cache (s) — pensées pour rester sous 100 req/h (plan gratuit).
TTL_EVENTS = 60
TTL_ODDS = 60
TTL_LEAGUES = 3600
# Marge de sécurité : on suspend les appels en dessous de ce budget restant.
RL_SAFETY = 5

# Cache mémoire : clé -> (expire_at, payload). Persiste tant que le serveur tourne.
_CACHE: Dict[str, tuple] = {}
# Budget rate-limit connu d'après les en-têtes des dernières réponses.
_RL: Dict[str, Any] = {"remaining": None, "reset": 0.0}


def _cache_key(path: str, params: Dict[str, Any]) -> str:
    items = sorted((k, str(v)) for k, v in params.items() if k != "apiKey")
    return path + "?" + "&".join(f"{k}={v}" for k, v in items)


def _update_rl(resp: requests.Response) -> None:
    """Lit x-ratelimit-remaining / x-ratelimit-reset dans la réponse."""
    rem = resp.headers.get("x-ratelimit-remaining")
    if rem is not None:
        try:
            _RL["remaining"] = int(rem)
        except ValueError:
            pass
    rst = resp.headers.get("x-ratelimit-reset")
    if rst is not None:
        try:
            v = float(rst)
            # reset peut être un epoch absolu OU un nombre de secondes restantes.
            _RL["reset"] = v if v > 1e6 else time.time() + v
        except ValueError:
            pass


def _budget_ok() -> bool:
    """False si le budget est trop bas et que le reset n'est pas encore passé."""
    if _RL["remaining"] is None or _RL["remaining"] >= RL_SAFETY:
        return True
    if _RL["reset"] and time.time() >= _RL["reset"]:
        _RL["remaining"] = None   # fenêtre repassée : on retente
        return True
    return False


def rate_limit_status() -> Dict[str, Any]:
    """État du budget rate-limit (pour /api/status / diagnostic)."""
    reset_in = int(_RL["reset"] - time.time()) if _RL["reset"] else None
    return {"remaining": _RL["remaining"],
            "reset_in_s": max(0, reset_in) if reset_in is not None else None}


def clear_cache() -> None:
    """Vide le cache (utile en tests)."""
    _CACHE.clear()
    _RL.update(remaining=None, reset=0.0)


def _get(path: str, params: Dict[str, Any], ttl: float) -> Optional[Any]:
    """GET caché + conscient du rate-limit. Renvoie le JSON, le cache (même périmé)
    si on est suspendu, ou None. Ne bloque jamais longtemps (sert un serveur web)."""
    key = _cache_key(path, params)
    now = time.time()
    hit = _CACHE.get(key)
    if hit and hit[0] > now:
        return hit[1]                       # cache frais

    if not _budget_ok():
        log(f"odds-api: budget bas (reste {_RL['remaining']}, reset "
            f"{rate_limit_status()['reset_in_s']}s) — on sert le cache.", "WARN")
        return hit[1] if hit else None      # stale plutôt que rien

    try:
        r = requests.get(f"{BASE}{path}", params=params, timeout=20)
    except requests.RequestException as exc:
        log(f"odds-api {path} réseau KO ({exc}).", "WARN")
        return hit[1] if hit else None

    _update_rl(r)

    if r.status_code == 429:
        if not _RL["reset"] or _RL["reset"] < now:
            _RL["reset"] = now + 60
        _RL["remaining"] = 0
        log(f"odds-api 429 — appels suspendus ~"
            f"{rate_limit_status()['reset_in_s']}s.", "WARN")
        return hit[1] if hit else None
    if r.status_code != 200:
        return hit[1] if hit else None
    try:
        payload = r.json()
    except ValueError:
        return hit[1] if hit else None

    _CACHE[key] = (now + ttl, payload)
    return payload


def _key() -> Optional[str]:
    load_env()
    v = (os.environ.get("ODDS_API_KEY") or "").strip()
    return v or None


def is_enabled() -> bool:
    return _key() is not None


def fetch_tennis_events(upcoming_only: bool = True) -> List[Dict[str, Any]]:
    """Liste des événements tennis (id, home, away, date, league, status). Caché 60 s."""
    key = _key()
    if not key:
        return []
    events = _get("/events", {"sport": "tennis", "apiKey": key}, ttl=TTL_EVENTS)
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
    data = _get("/odds", {"eventId": event_id, "bookmakers": bookmakers, "apiKey": key},
                ttl=TTL_ODDS)
    if not isinstance(data, dict):
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
