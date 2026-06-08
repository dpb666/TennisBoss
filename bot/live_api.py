"""Adaptateur API live — branché sur API-Tennis (clé AT_API_KEY).

Les clés sont lues depuis le fichier local `.env` (exclu de git) ou
l'environnement. Fournisseurs gérés :
  - "api-tennis"  : fixtures à venir + live  (AT_API_KEY)            [ACTIF]
  - "sportradar"  : gabarit prêt             (SR_KEY)                [secondaire]

Aucune protection anti-bot n'est contournée : ce sont des API officielles
auxquelles vous êtes abonné via votre clé.
"""
from __future__ import annotations

import datetime as _dt
import os
import time
from typing import Any, Dict, List, Optional

import requests

from . import config
from .log import log

API_TENNIS_URL = "https://api.api-tennis.com/tennis/"

# API-Tennis n'expose pas d'en-tête rate-limit -> on protège le quota par un
# simple cache TTL (mono-utilisateur, tennis uniquement).
TTL_FIXTURES = 60      # matchs à venir / live
TTL_RESULTS = 300      # résultats terminés (changent peu)
_CACHE: Dict[str, tuple] = {}


def clear_cache() -> None:
    _CACHE.clear()


def _cached_request(params: Dict[str, Any], ttl: float) -> Optional[Any]:
    """GET API-Tennis avec cache TTL. Renvoie le payload JSON brut, le cache
    périmé en secours, ou None. Ne fait jamais d'appel inutile sous le TTL."""
    key = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "APIkey")
    now = time.time()
    hit = _CACHE.get(key)
    if hit and hit[0] > now:
        return hit[1]
    try:
        resp = requests.get(API_TENNIS_URL, params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log(f"API-Tennis indisponible ({exc}).", "WARN")
        return hit[1] if hit else None
    _CACHE[key] = (now + ttl, payload)
    return payload


def load_env() -> None:
    """Charge les paires CLE=VALEUR du fichier .env dans l'environnement."""
    path = os.path.join(config.ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def _key(name: str, cfg: Dict[str, Any]) -> Optional[str]:
    val = os.environ.get(name) or cfg.get("live_api_key") or ""
    return val.strip() or None


def is_enabled(cfg: Dict[str, Any]) -> bool:
    load_env()
    return _key("AT_API_KEY", cfg) is not None


def fetch_upcoming(cfg: Dict[str, Any], days_ahead: int = 2) -> List[Dict]:
    """Récupère les matchs à venir (et live) via API-Tennis.

    Renvoie une liste de dicts normalisés :
      {player1, player2, tournament, round, date, time, live, event_key, tour}
    """
    load_env()
    key = _key("AT_API_KEY", cfg)
    if not key:
        log("API live inactive (AT_API_KEY absente). Données ouvertes conservées.", "INFO")
        return []

    start = _dt.date.today().isoformat()
    stop = (_dt.date.today() + _dt.timedelta(days=days_ahead)).isoformat()
    payload = _cached_request(
        {"method": "get_fixtures", "APIkey": key,
         "date_start": start, "date_stop": stop},
        ttl=TTL_FIXTURES,
    )
    if not isinstance(payload, dict) or not payload.get("success"):
        return []
    return [_parse_fixture(m) for m in (payload.get("result") or [])]


def fetch_results(cfg: Dict[str, Any], days_back: int = 2) -> List[Dict[str, Any]]:
    """Récupère les matchs TERMINÉS récents (pour le settlement).

    Renvoie une liste de dicts normalisés avec vainqueur + score + sets.
    """
    load_env()
    key = _key("AT_API_KEY", cfg)
    if not key:
        return []
    stop = _dt.date.today().isoformat()
    start = (_dt.date.today() - _dt.timedelta(days=days_back)).isoformat()
    payload = _cached_request(
        {"method": "get_fixtures", "APIkey": key,
         "date_start": start, "date_stop": stop},
        ttl=TTL_RESULTS,
    )
    if not isinstance(payload, dict) or not payload.get("success"):
        return []
    out = [_parse_result(m) for m in (payload.get("result") or [])]
    return [r for r in out if r["finished"] and not r["is_doubles"]]


def _parse_result(m: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise un match potentiellement terminé (winner + score + sets)."""
    etype = (m.get("event_type_type") or "").lower()
    tour = "atp" if "atp" in etype else ("wta" if "wta" in etype else "")
    status = str(m.get("event_status") or "")
    winner_raw = (m.get("event_winner") or "").strip()  # "First Player"/"Second Player"
    winner = None
    if winner_raw == "First Player":
        winner = "p1"
    elif winner_raw == "Second Player":
        winner = "p2"
    sets = []
    for s in (m.get("scores") or []):
        sets.append({
            "set": s.get("score_set"),
            "first": s.get("score_first"),
            "second": s.get("score_second"),
        })
    finished = (status.lower() == "finished") or (winner is not None and bool(sets))
    return {
        "event_key": m.get("event_key"),
        "player1": (m.get("event_first_player") or "").strip(),
        "player2": (m.get("event_second_player") or "").strip(),
        "winner": winner,
        "final_score": (m.get("event_final_result") or "").strip(),
        "sets": sets,
        "status": status,
        "tournament": m.get("tournament_name", ""),
        "round": m.get("tournament_round", ""),
        "date": m.get("event_date", ""),
        "tour": tour,
        "is_doubles": "doubles" in etype,
        "finished": finished,
    }


def _parse_fixture(m: Dict[str, Any]) -> Dict[str, Any]:
    etype = (m.get("event_type_type") or "").lower()  # ex: "Atp Singles"
    tour = "atp" if "atp" in etype else ("wta" if "wta" in etype else "")
    return {
        "player1": m.get("event_first_player", "").strip(),
        "player2": m.get("event_second_player", "").strip(),
        "tournament": m.get("tournament_name", ""),
        "round": m.get("tournament_round", ""),
        "date": m.get("event_date", ""),
        "time": m.get("event_time", ""),
        "live": str(m.get("event_live", "0")) == "1",
        "event_key": m.get("event_key"),
        "is_doubles": "doubles" in etype,
        "tour": tour,
    }
