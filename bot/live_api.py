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
TTL_FIXTURES = 300     # matchs à venir / live (5 min — API-Tennis quota)
TTL_RESULTS = 600      # résultats terminés (changent peu)
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
        resp = requests.get(API_TENNIS_URL, params=params, timeout=8)
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
    """Récupère les matchs à venir via API-Tennis (primaire) ou odds-api.io (fallback).

    Renvoie une liste de dicts normalisés :
      {player1, player2, tournament, round, date, time, live, event_key, tour}
    """
    load_env()
    key = _key("AT_API_KEY", cfg)
    if key:
        start = _dt.date.today().isoformat()
        stop = (_dt.date.today() + _dt.timedelta(days=days_ahead)).isoformat()
        payload = _cached_request(
            {"method": "get_fixtures", "APIkey": key,
             "date_start": start, "date_stop": stop},
            ttl=TTL_FIXTURES,
        )
        if isinstance(payload, dict) and payload.get("success"):
            results = payload.get("result") or []
            if results and not (isinstance(results[0], dict) and results[0].get("cod") == 1006):
                return [_parse_fixture(m) for m in results]
        log("API-Tennis inactive ou expirée — fallback odds-api.io.", "WARN")

    # Fallback : odds-api.io par date (live + upcoming)
    return _fetch_upcoming_oddsapi(days_ahead)


def fetch_results(cfg: Dict[str, Any], days_back: int = 2) -> List[Dict[str, Any]]:
    """Récupère les matchs TERMINÉS récents via API-Tennis (primaire) ou odds-api.io (fallback).

    Renvoie une liste de dicts normalisés avec vainqueur + score + sets.
    """
    load_env()
    key = _key("AT_API_KEY", cfg)
    if key:
        stop = _dt.date.today().isoformat()
        start = (_dt.date.today() - _dt.timedelta(days=days_back)).isoformat()
        payload = _cached_request(
            {"method": "get_fixtures", "APIkey": key,
             "date_start": start, "date_stop": stop},
            ttl=TTL_RESULTS,
        )
        if isinstance(payload, dict) and payload.get("success"):
            results = payload.get("result") or []
            if results and not (isinstance(results[0], dict) and results[0].get("cod") == 1006):
                out = [_parse_result(m) for m in results]
                return [r for r in out if r["finished"] and not r["is_doubles"]]
        log("API-Tennis inactive ou expirée — fallback odds-api.io pour résultats.", "WARN")

    # Fallback : odds-api.io settled events
    return _fetch_results_oddsapi()


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


def parse_odds_events_as_fixtures(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convertit les événements odds-api.io en format fixture standard.

    Filtre les matchs non terminés (pending/live).
    Utilisé comme fallback quand API-Tennis n'est pas disponible.
    """
    out = []
    for e in events:
        status = (e.get("status") or "").lower()
        if status not in ("pending", "live", "not_started", "inplay"):
            continue
        home = (e.get("home") or "").strip()
        away = (e.get("away") or "").strip()
        if not home or not away:
            continue
        league_name = (e.get("league") or {}).get("name", "")
        league_slug = (e.get("league") or {}).get("slug", "")
        combined = (league_name + " " + league_slug).lower()
        is_doubles = " / " in home or " / " in away or "double" in combined
        tour = "wta" if "wta" in combined else ("atp" if "atp" in combined else "")
        # Parse ISO date -> date + time
        raw_date = e.get("date", "")
        try:
            import datetime as _dt2
            dt = _dt2.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H:%M")
        except Exception:
            date_str = raw_date[:10]
            time_str = raw_date[11:16]
        out.append({
            "player1": home,
            "player2": away,
            "tournament": league_name,
            "round": "",
            "date": date_str,
            "time": time_str,
            "live": status in ("live", "inplay"),
            "event_key": e.get("id"),
            "is_doubles": is_doubles,
            "tour": tour,
        })
    return out


def _fetch_upcoming_oddsapi(days_ahead: int = 2) -> List[Dict]:
    """Fallback fixtures : odds-api.io par date (live + matchs du jour/demain)."""
    try:
        from . import odds_api as _oa
        if not _oa.is_enabled():
            return []
        out: List[Dict] = []
        # Live d'abord
        live_events = _oa._get("/events", {"sport": "tennis", "status": "live"}, ttl=30) or []
        for e in (live_events if isinstance(live_events, list) else []):
            f = _parse_oddsapi_fixture(e, live=True)
            if f:
                out.append(f)
        # Matchs par date (aujourd'hui + N jours)
        today_str = _dt.date.today().isoformat()
        for d in range(days_ahead + 1):
            date = (_dt.date.today() + _dt.timedelta(days=d)).isoformat()
            events = _oa._get("/events", {"sport": "tennis", "date": date}, ttl=TTL_FIXTURES) or []
            for e in (events if isinstance(events, list) else []):
                if e.get("status") in ("settled", "canceled"):
                    continue
                f = _parse_oddsapi_fixture(e, live=False)
                if not f:
                    continue
                # Le paramètre `date` envoyé à odds-api.io ne garantit pas que
                # l'event renvoyé a bien cette date une fois son propre
                # commence_time reparsé (cf. _parse_oddsapi_fixture) — constaté
                # en prod : des matchs de la veille (déjà joués) remontaient
                # dans "à venir" alors qu'on ne demandait que today/today+N.
                if f["date"] < today_str:
                    continue
                out.append(f)
        seen: set = set()
        deduped = []
        for f in out:
            k = (f["player1"], f["player2"], f["date"])
            if k not in seen:
                seen.add(k)
                deduped.append(f)
        log(f"fetch_upcoming fallback odds-api.io: {len(deduped)} fixtures")
        return deduped
    except Exception as exc:
        log(f"_fetch_upcoming_oddsapi erreur: {exc}", "WARN")
        return []


def _fetch_results_oddsapi() -> List[Dict[str, Any]]:
    """Fallback résultats : odds-api.io settled events (dernières 24h)."""
    try:
        from . import odds_api as _oa
        if not _oa.is_enabled():
            return []
        events = _oa._get("/events", {"sport": "tennis", "status": "settled"}, ttl=300) or []
        out = []
        for e in (events if isinstance(events, list) else []):
            sc = e.get("scores") or {}
            home_sets = sc.get("home", 0)
            away_sets = sc.get("away", 0)
            if home_sets == away_sets:
                continue
            winner = "p1" if home_sets > away_sets else "p2"
            # Sets détaillés
            periods = sc.get("periods", {})
            sets = []
            for pk in sorted(periods.keys()):
                p = periods[pk]
                if isinstance(p, dict) and "home" in p and "away" in p:
                    sets.append({"set": pk, "first": p["home"], "second": p["away"]})
            league = (e.get("league") or {}).get("name", "")
            combined = league.lower()
            is_doubles = ("doubles" in combined or " / " in (e.get("home") or "")
                          or " / " in (e.get("away") or ""))
            tour = "wta" if "wta" in combined else ("atp" if "atp" in combined else "")
            out.append({
                "event_key": str(e.get("id") or ""),
                "player1": (e.get("home") or "").strip(),
                "player2": (e.get("away") or "").strip(),
                "winner": winner,
                "final_score": f"{home_sets} - {away_sets}",
                "sets": sets,
                "status": "finished",
                "tournament": league,
                "round": "",
                "date": (e.get("date") or "")[:10],
                "tour": tour,
                "is_doubles": is_doubles,
                "finished": True,
            })
        log(f"fetch_results fallback odds-api.io: {len(out)} résultats")
        return out
    except Exception as exc:
        log(f"_fetch_results_oddsapi erreur: {exc}", "WARN")
        return []


def _parse_oddsapi_fixture(e: Dict[str, Any], live: bool = False) -> Optional[Dict]:
    """Convertit un event odds-api.io en format fixture standard."""
    home = (e.get("home") or "").strip()
    away = (e.get("away") or "").strip()
    if not home or not away:
        return None
    league = (e.get("league") or {}).get("name", "")
    combined = ((league or "") + " " + (e.get("league") or {}).get("slug", "")).lower()
    is_doubles = " / " in home or " / " in away or "double" in combined
    tour = "wta" if "wta" in combined else ("atp" if "atp" in combined else "")
    raw_date = e.get("date", "")
    try:
        dt = _dt.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M")
    except Exception:
        date_str = raw_date[:10]
        time_str = raw_date[11:16]
    return {
        "player1": home,
        "player2": away,
        "tournament": league,
        "round": "",
        "date": date_str,
        "time": time_str,
        "live": live or e.get("status") in ("live", "inplay"),
        "event_key": e.get("id"),
        "is_doubles": is_doubles,
        "tour": tour,
        "source": "odds-api.io",
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
