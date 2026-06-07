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
from typing import Any, Dict, List, Optional

import requests

from . import config
from .log import log

API_TENNIS_URL = "https://api.api-tennis.com/tennis/"


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
    try:
        resp = requests.get(
            API_TENNIS_URL,
            params={"method": "get_fixtures", "APIkey": key,
                    "date_start": start, "date_stop": stop},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log(f"API-Tennis indisponible ({exc}) -> on garde les données ouvertes.", "WARN")
        return []

    if not payload.get("success"):
        log(f"API-Tennis: réponse sans succès ({str(payload)[:120]}).", "WARN")
        return []

    return [_parse_fixture(m) for m in (payload.get("result") or [])]


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
