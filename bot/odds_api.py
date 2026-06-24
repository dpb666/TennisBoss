"""Cotes via odds-api.io — pool de clés rotatif (ODDS_API_KEY, ODDS_API_KEY_2..5).

Doc : https://docs.odds-api.io/  — base https://api.odds-api.io/v3
  GET /sports
  GET /events?sport=tennis
  GET /odds?eventId={id}&bookmakers={liste}

Pool de clés : jusqu'à 5 clés (.env ODDS_API_KEY, ODDS_API_KEY_2..5).
Rotation automatique quand une clé atteint RL_SAFETY requêtes restantes.
Chaque clé = 100 req/h → 5 clés = 500 req/h.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests

from .live_api import load_env
from .log import log

BASE = "https://api.odds-api.io/v3"
DEFAULT_BOOKMAKERS = "MelBet,Betfair Exchange"

TTL_EVENTS = 900       # 15 min — économise le quota 100 req/h
TTL_ODDS = 300         # 5 min
TTL_LEAGUES = 3600
RL_SAFETY = 5          # seuil bas -> on passe à la clé suivante

_CACHE: Dict[str, tuple] = {}
_RL_WARN_AT: float = 0.0

# Pool de clés : {key_str -> {remaining, reset}}
_KEY_POOL: Dict[str, Dict[str, Any]] = {}
_KEY_ORDER: List[str] = []   # ordre stable de parcours
_CURRENT_KEY_IDX: int = 0    # index courant dans _KEY_ORDER


def _cache_key(path: str, params: Dict[str, Any]) -> str:
    items = sorted((k, str(v)) for k, v in params.items() if k != "apiKey")
    return path + "?" + "&".join(f"{k}={v}" for k, v in items)


def _parse_reset(rst: str) -> Optional[float]:
    """x-ratelimit-reset -> epoch (s). Gère 3 formats vus en pratique :
    epoch absolu, nb de secondes restantes, ou timestamp ISO 8601 (doc odds-api)."""
    rst = rst.strip()
    try:
        v = float(rst)
        return v if v > 1e6 else time.time() + v
    except ValueError:
        pass
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat(rst.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _load_key_pool() -> None:
    """Charge toutes les clés ODDS_API_KEY[_2..5] depuis l'environnement."""
    global _KEY_ORDER
    load_env()
    keys = []
    for suffix in ("", "_2", "_3", "_4", "_5", "_6", "_7", "_8", "_9", "_10", "_11", "_12"):
        k = (os.environ.get(f"ODDS_API_KEY{suffix}") or "").strip()
        if k and k not in keys:
            keys.append(k)
    for k in keys:
        if k not in _KEY_POOL:
            _KEY_POOL[k] = {"remaining": None, "reset": 0.0}
    _KEY_ORDER = keys


def _current_key() -> Optional[str]:
    """Round-robin strict : avance d'1 après chaque appel pour répartir uniformément."""
    global _CURRENT_KEY_IDX
    if not _KEY_ORDER:
        _load_key_pool()
    if not _KEY_ORDER:
        return None
    now = time.time()
    n = len(_KEY_ORDER)
    for i in range(n):
        idx = (_CURRENT_KEY_IDX + i) % n
        k = _KEY_ORDER[idx]
        rl = _KEY_POOL[k]
        rem = rl["remaining"]
        # Reset automatique si l'heure de reset est passée
        if rem is not None and rem < RL_SAFETY and rl["reset"] and now >= rl["reset"]:
            rl["remaining"] = None
            rem = None
        if rem is None or rem >= RL_SAFETY:
            # Avance d'1 pour le prochain appel (round-robin)
            _CURRENT_KEY_IDX = (idx + 1) % n
            return k
    # Toutes épuisées — attend la prochaine reset
    best = min(_KEY_ORDER, key=lambda k: _KEY_POOL[k]["reset"] or 0)
    reset_in = max(0, int((_KEY_POOL[best]["reset"] or 0) - now))
    log(f"odds-api: toutes les clés épuisées — reset dans {reset_in}s.", "WARN")
    return None


def _update_rl(resp: requests.Response, key: str) -> None:
    """Lit x-ratelimit-remaining / x-ratelimit-reset pour la clé donnée."""
    rl = _KEY_POOL.get(key)
    if rl is None:
        return
    rem = resp.headers.get("x-ratelimit-remaining")
    if rem is not None:
        try:
            rl["remaining"] = int(rem)
        except ValueError:
            pass
    rst = resp.headers.get("x-ratelimit-reset")
    if rst is not None:
        parsed = _parse_reset(rst)
        if parsed is not None:
            rl["reset"] = parsed


def rate_limit_status() -> Dict[str, Any]:
    """État du pool de clés (pour /api/status / diagnostic)."""
    if not _KEY_ORDER:
        _load_key_pool()
    pool = []
    for k in _KEY_ORDER:
        rl = _KEY_POOL[k]
        reset_in = int(rl["reset"] - time.time()) if rl["reset"] else None
        pool.append({
            "key_suffix": k[-6:],
            "remaining": rl["remaining"],
            "reset_in_s": max(0, reset_in) if reset_in is not None else None,
        })
    total_rem = sum(p["remaining"] or 0 for p in pool)
    # Compat avec l'ancien format (premier champ "remaining")
    first = pool[0] if pool else {}
    return {
        "remaining": first.get("remaining"),
        "reset_in_s": first.get("reset_in_s"),
        "pool": pool,
        "total_remaining": total_rem,
        "keys_count": len(_KEY_ORDER),
    }


def clear_cache() -> None:
    """Vide le cache et reset le pool (utile en tests)."""
    _CACHE.clear()
    for rl in _KEY_POOL.values():
        rl.update(remaining=None, reset=0.0)


def _get(path: str, params: Dict[str, Any], ttl: float) -> Optional[Any]:
    """GET caché + pool de clés rotatif. Ne bloque jamais longtemps."""
    cache_key_str = _cache_key(path, params)
    now = time.time()
    hit = _CACHE.get(cache_key_str)
    if hit and hit[0] > now:
        return hit[1]

    api_key = _current_key()
    if not api_key:
        global _RL_WARN_AT
        if time.time() - _RL_WARN_AT > 60:
            log(f"odds-api: toutes les clés épuisées ({len(_KEY_ORDER)} clés).", "WARN")
            _RL_WARN_AT = time.time()
        return hit[1] if hit else None

    call_params = {**params, "apiKey": api_key}
    try:
        r = requests.get(f"{BASE}{path}", params=call_params, timeout=20)
    except requests.RequestException as exc:
        log(f"odds-api {path} réseau KO ({exc}).", "WARN")
        return hit[1] if hit else None

    _update_rl(r, api_key)

    if r.status_code == 429:
        rl = _KEY_POOL[api_key]
        reset_at = rl["reset"] if (rl["reset"] and rl["reset"] > now) else now + 10
        rl["remaining"] = 0
        rl["reset"] = reset_at
        # Essai immédiat avec la clé suivante du pool
        next_key = _current_key()
        if next_key and next_key != api_key:
            log(f"odds-api 429 sur clé ...{api_key[-6:]} — bascule sur ...{next_key[-6:]}.", "WARN")
            call_params["apiKey"] = next_key
            try:
                r = requests.get(f"{BASE}{path}", params=call_params, timeout=20)
                _update_rl(r, next_key)
                api_key = next_key
            except requests.RequestException:
                return hit[1] if hit else None
        else:
            log(f"odds-api 429 — pool épuisé.", "WARN")
            return hit[1] if hit else None

    if r.status_code != 200:
        return hit[1] if hit else None
    try:
        payload = r.json()
    except ValueError:
        return hit[1] if hit else None

    _CACHE[cache_key_str] = (now + ttl, payload)
    return payload


def _key() -> Optional[str]:
    """Compatibilité : retourne la clé active courante du pool."""
    if not _KEY_ORDER:
        _load_key_pool()
    return _KEY_ORDER[0] if _KEY_ORDER else None


def is_enabled() -> bool:
    if not _KEY_ORDER:
        _load_key_pool()
    return bool(_KEY_ORDER)


def fetch_tennis_events(upcoming_only: bool = True) -> List[Dict[str, Any]]:
    """Liste des événements tennis (id, home, away, date, league, status).

    v3 update: /events renvoie les 14 prochains jours par défaut (jusqu'à 5000 events).
    Le pool de clés est utilisé automatiquement via _get().
    """
    if not is_enabled():
        return []
    events = _get("/events", {"sport": "tennis"}, ttl=TTL_EVENTS)
    if not isinstance(events, list):
        return []
    if upcoming_only:
        events = [e for e in events
                  if e.get("status") in ("pending", "live", "inplay", "not_started")]
    return events


def fetch_settled_events() -> List[Dict[str, Any]]:
    """Résultats terminés des dernières 24h."""
    if not is_enabled():
        return []
    events = _get("/events", {"sport": "tennis", "status": "settled"}, ttl=300)
    if not isinstance(events, list):
        return []
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
    if not is_enabled():
        return None
    data = _get("/odds", {"eventId": event_id, "bookmakers": bookmakers},
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
