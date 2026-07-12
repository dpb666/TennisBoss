"""Feeder OddsPapi (oddspapi.io) — pool de clés rotatif (ODDSPAPI_KEY, ODDSPAPI_KEY_2..12).

Doc : https://oddspapi.io/en/docs — base https://api.oddspapi.io/v4
  GET /fixtures?sportId=12&from=...&to=...&apiKey=... (tennis, couvre ATP/WTA/
      Challenger/ITF d'après la doc publique)
  GET /account?apiKey=... -> {request_limit, request_count} (quota restant)

Ajouté pour compléter/remplacer API-Tennis (bot/live_api.py) dont l'abonnement
est expiré (impayé, cod=1006) — voir docs/AUDIT.md. Free tier : 250 req/mois
par compte, sans CB. Plusieurs comptes = pool de clés, même principe que
odds_api.py (odds-api.io) : rotation automatique vers la clé suivante quand
une clé approche de son quota.

Vérifié en conditions réelles le 2026-07-12 avec un vrai compte (plan free,
250 req/mois) : sportId=12 confirmé via GET /v4/sports, couverture réelle
constatée sur 4 jours = 574 fixtures dont 65 ATP + 58 WTA (pas seulement
Challenger/ITF/UTR) — comble bien le trou laissé par API-Tennis expiré.
"""
from __future__ import annotations

import datetime as _dt
import os
import threading
import time
from typing import Any, Dict, List, Optional

import requests

from .live_api import load_env
from .log import log

BASE = "https://api.oddspapi.io/v4"
SPORT_ID_TENNIS = 12  # confirmé via GET /v4/sports (2026-07-12)

# Confirmés contre l'API réelle (2026-07-12) — la doc publique se trompait
# sur ce point (indiquait 3=Live) : 0=Pre-Game, 1=Live, 2=Finished, 3=Cancelled.
STATUS_PRE_GAME = 0
STATUS_LIVE = 1
STATUS_FINISHED = 2
STATUS_CANCELLED = 3

TTL_FIXTURES = 900     # 15 min
TTL_ACCOUNT = 3600     # 1h — ne pas gaspiller le quota juste pour vérifier le quota
RL_SAFETY = 5          # requêtes restantes minimum avant de passer à la clé suivante

_CACHE: Dict[str, tuple] = {}
_CACHE_LOCK = threading.Lock()

_KEY_POOL: Dict[str, Dict[str, Any]] = {}   # {clé -> {remaining, checked_at}}
_KEY_ORDER: List[str] = []


def _load_key_pool() -> None:
    """Charge toutes les clés ODDSPAPI_KEY[_2..12] depuis l'environnement."""
    global _KEY_ORDER
    load_env()
    keys = []
    for suffix in ("", "_2", "_3", "_4", "_5", "_6", "_7", "_8", "_9", "_10", "_11", "_12"):
        k = (os.environ.get(f"ODDSPAPI_KEY{suffix}") or "").strip()
        if k and k not in keys:
            keys.append(k)
    _KEY_ORDER = keys
    for k in keys:
        _KEY_POOL.setdefault(k, {"remaining": None, "checked_at": 0.0})


def is_enabled() -> bool:
    if not _KEY_ORDER:
        _load_key_pool()
    return bool(_KEY_ORDER)


def _check_quota(key: str) -> Optional[int]:
    """Quota restant pour une clé, via /account (caché TTL_ACCOUNT : on ne veut
    pas consommer une requête juste pour vérifier le quota)."""
    info = _KEY_POOL.get(key, {})
    now = time.time()
    if info.get("checked_at", 0) + TTL_ACCOUNT > now and info.get("remaining") is not None:
        return info["remaining"]
    try:
        resp = requests.get(f"{BASE}/account", params={"apiKey": key}, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        remaining = int(data.get("request_limit", 0)) - int(data.get("request_count", 0))
        _KEY_POOL[key] = {"remaining": remaining, "checked_at": now}
        return remaining
    except Exception as exc:
        log(f"oddspapi: échec vérification quota ({exc}).", "WARN")
        return None


def _pick_key() -> Optional[str]:
    """Première clé du pool avec assez de quota restant, sinon None (pool
    épuisé ou vide -> l'appelant doit se rabattre sur une autre source)."""
    if not _KEY_ORDER:
        _load_key_pool()
    for key in _KEY_ORDER:
        remaining = _check_quota(key)
        if remaining is None or remaining > RL_SAFETY:
            return key
    return None


def _get(path: str, params: Dict[str, Any], ttl: float) -> Optional[Any]:
    key = _pick_key()
    if not key:
        log("oddspapi: pool de clés épuisé ou vide.", "WARN")
        return None
    cache_key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(cache_key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        resp = requests.get(f"{BASE}{path}", params={**params, "apiKey": key}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log(f"oddspapi: requête {path} en échec ({exc}).", "WARN")
        return None
    with _CACHE_LOCK:
        _CACHE[cache_key] = (now + ttl, data)
    # Décrémente le quota connu en mémoire -> pas besoin d'un appel /account
    # supplémentaire pour chaque requête faite via _get().
    info = _KEY_POOL.get(key)
    if info and info.get("remaining") is not None:
        info["remaining"] -= 1
    return data


def fetch_tennis_fixtures(days_ahead: int = 2) -> List[Dict[str, Any]]:
    """Fixtures tennis brutes (format API OddsPapi) sur la fenêtre demandée."""
    if not is_enabled():
        return []
    start = _dt.date.today().isoformat()
    stop = (_dt.date.today() + _dt.timedelta(days=days_ahead)).isoformat()
    data = _get("/fixtures", {"sportId": SPORT_ID_TENNIS, "from": start, "to": stop},
                ttl=TTL_FIXTURES)
    return data if isinstance(data, list) else []


def parse_fixtures(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convertit les fixtures OddsPapi vers le format fixture standard interne
    ({player1, player2, tournament, round, date, time, live, event_key,
    is_doubles, tour}) — même forme que live_api.parse_odds_events_as_fixtures,
    pour pouvoir être fusionné dans bot/api.py::api_upcoming() comme ESPN/
    odds-api.io. Fonction pure -> testable sans réseau."""
    out = []
    for f in raw:
        # statusId vérifié contre l'API réelle (pas juste la doc, qui se
        # trompait) : 0=Pre-Game, 1=Live, 2=Finished, 3=Cancelled. On exclut
        # les matchs déjà terminés/annulés — seuls upcoming (0) et live (1)
        # nous intéressent pour /api/upcoming.
        status_id = f.get("statusId")
        if status_id not in (STATUS_PRE_GAME, STATUS_LIVE):
            continue
        p1 = (f.get("participant1Name") or "").strip()
        p2 = (f.get("participant2Name") or "").strip()
        if not p1 or not p2:
            continue
        tournament = f.get("tournamentName") or ""
        category = (f.get("categoryName") or "").lower()
        combined = (tournament + " " + category).lower()
        is_doubles = "/" in p1 or "/" in p2 or "double" in combined
        tour = "wta" if "wta" in combined else ("atp" if "atp" in combined else "")
        raw_start = f.get("startTime") or ""
        try:
            dt = _dt.datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H:%M")
        except Exception:
            date_str = raw_start[:10]
            time_str = raw_start[11:16] if len(raw_start) >= 16 else ""
        out.append({
            "player1": p1,
            "player2": p2,
            "tournament": tournament,
            "round": "",
            "date": date_str,
            "time": time_str,
            "live": status_id == STATUS_LIVE,
            "event_key": f.get("fixtureId"),
            "is_doubles": is_doubles,
            "tour": tour,
        })
    return out
