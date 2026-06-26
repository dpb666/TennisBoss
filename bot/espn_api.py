"""Source ESPN (non-officielle, gratuite, sans clé) — fixtures ATP + WTA.

Endpoints :
  GET https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard
  GET https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard
  GET https://site.api.espn.com/apis/site/v2/sports/tennis/atp/summary?event={id}

Retourne des matchs dans le même format que live_api.fetch_upcoming().
TTL 300 s pour éviter de surcharger l'API non officielle.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .log import log

BASE = "https://site.api.espn.com/apis/site/v2/sports/tennis"
TTL = 300  # 5 min

_CACHE: Dict[str, Tuple[float, Any]] = {}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

LIVE_STATUSES = {"STATUS_IN_PROGRESS"}
UPCOMING_STATUSES = {"STATUS_SCHEDULED"}
FINAL_STATUSES = {"STATUS_FINAL", "STATUS_RETIRED", "STATUS_WALKOVER"}


def _get(url: str) -> Optional[Any]:
    now = time.time()
    hit = _CACHE.get(url)
    if hit and hit[0] > now:
        return hit[1]
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        if r.status_code != 200:
            log(f"ESPN {url} -> {r.status_code}", "WARN")
            return hit[1] if hit else None
        data = r.json()
        _CACHE[url] = (now + TTL, data)
        return data
    except Exception as exc:
        log(f"ESPN réseau KO: {exc}", "WARN")
        return hit[1] if hit else None


def _parse_competition(comp: Dict, tournament: str, tour: str) -> Optional[Dict]:
    """Convertit un objet ESPN competition en fixture standard."""
    status_name = comp.get("status", {}).get("type", {}).get("name", "")
    comps = comp.get("competitors", [])
    if len(comps) < 2:
        return None

    p1_info = comps[0].get("athlete", {})
    p2_info = comps[1].get("athlete", {})
    p1 = p1_info.get("displayName", "").strip()
    p2 = p2_info.get("displayName", "").strip()

    if not p1 or not p2 or p1 == "TBD" or p2 == "TBD":
        return None

    raw_date = comp.get("date", "") or comp.get("startDate", "")
    try:
        import datetime as _dt
        from zoneinfo import ZoneInfo
        dt = _dt.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        dt = dt.astimezone(ZoneInfo("America/Toronto"))
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M")
    except Exception:
        date_str = raw_date[:10]
        time_str = raw_date[11:16]

    # Détection doubles : nom contient "/" ou catégorie contient "doubles"
    is_doubles = "/" in p1 or "/" in p2

    live = status_name in LIVE_STATUSES
    finished = status_name in FINAL_STATUSES

    return {
        "player1": p1,
        "player2": p2,
        "tournament": tournament,
        "round": _round_from_comp(comp),
        "date": date_str,
        "time": time_str,
        "live": live,
        "finished": finished,
        "status": status_name,
        "event_key": comp.get("id"),
        "is_doubles": is_doubles,
        "tour": tour,
        "source": "espn",
    }


def _round_from_comp(comp: Dict) -> str:
    """Extrait le round depuis les notes ESPN."""
    for note in comp.get("notes", []):
        h = note.get("headline", "")
        if h:
            return h
    return ""


def _fetch_tour(tour_slug: str, tour: str) -> List[Dict]:
    url = f"{BASE}/{tour_slug}/scoreboard"
    data = _get(url)
    if not data:
        return []

    out = []
    for event in data.get("events", []):
        tourn = event.get("name", "")
        for grouping in event.get("groupings", []):
            grp_name = grouping.get("grouping", {}).get("displayName", "")
            is_doubles_group = "Double" in grp_name or "Doubles" in grp_name
            for comp in grouping.get("competitions", []):
                fix = _parse_competition(comp, tourn, tour)
                if fix:
                    if is_doubles_group:
                        fix["is_doubles"] = True
                    out.append(fix)
    return out


def fetch_upcoming(days_ahead: int = 3) -> List[Dict]:
    """Retourne les matchs à venir (scheduled + live) ATP + WTA.

    Même format que live_api._parse_fixture().
    """
    import datetime as _dt
    cutoff = (_dt.datetime.utcnow() + _dt.timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    atp = _fetch_tour("atp", "atp")
    wta = _fetch_tour("wta", "wta")
    all_fixtures = atp + wta

    out = []
    for f in all_fixtures:
        status = f.get("status", "")
        if status not in LIVE_STATUSES and status not in UPCOMING_STATUSES:
            continue
        if f["date"] > cutoff:
            continue
        out.append(f)

    log(f"ESPN: {len(out)} matchs à venir (ATP+WTA).", "INFO")
    return out


def fetch_results(days_back: int = 3) -> List[Dict]:
    """Retourne les matchs terminés récents (pour le settlement)."""
    import datetime as _dt
    cutoff = (_dt.datetime.utcnow() - _dt.timedelta(days=days_back)).strftime("%Y-%m-%d")

    atp = _fetch_tour("atp", "atp")
    wta = _fetch_tour("wta", "wta")

    out = []
    for f in (atp + wta):
        if f.get("status") not in FINAL_STATUSES:
            continue
        if f["date"] < cutoff:
            continue
        out.append(f)
    return out


def clear_cache() -> None:
    _CACHE.clear()
