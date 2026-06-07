"""Adaptateur API live (pluggable) — prêt pour votre clé test puis l'abonnement.

La clé est lue par ordre de priorité :
  1. variable d'environnement  TENNISBOSS_API_KEY
  2. champ  live_api_key  dans state/config.json

Tant qu'aucune clé n'est fournie, l'adaptateur reste inactif (le bot continue
sur les données ouvertes Sackmann). Quand vous me donnez la doc de votre API,
je remplis `fetch_upcoming()` pour votre fournisseur précis.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

from . import config
from .log import log


def get_api_key(cfg: Dict[str, Any]) -> Optional[str]:
    key = os.environ.get("TENNISBOSS_API_KEY") or cfg.get("live_api_key") or ""
    return key.strip() or None


def is_enabled(cfg: Dict[str, Any]) -> bool:
    return get_api_key(cfg) is not None and cfg.get("live_api_provider", "none") != "none"


def fetch_upcoming(cfg: Dict[str, Any]) -> List[Dict]:
    """Récupère les matchs à venir via l'API du fournisseur configuré.

    Renvoie une liste de dicts {player1, player2, tournament, start}.
    Implémentation générique : à adapter à VOTRE fournisseur quand vous
    me donnez l'endpoint + le format (api-tennis, sportradar, etc.).
    """
    key = get_api_key(cfg)
    if not key:
        log("API live inactive (aucune clé). Utilisation des données ouvertes.", "INFO")
        return []

    provider = cfg.get("live_api_provider", "none")
    log(f"API live : interrogation du fournisseur '{provider}'.")
    try:
        # --- GABARIT générique (à personnaliser selon votre fournisseur) ----
        # url = "https://api.exemple-tennis.com/v1/fixtures"
        # resp = requests.get(url, params={"apikey": key, "status": "upcoming"},
        #                     headers={"User-Agent": config.BROWSER_UA}, timeout=15)
        # resp.raise_for_status()
        # return _parse_provider(provider, resp.json())
        log("fetch_upcoming() : gabarit non encore branché sur un fournisseur.", "WARN")
        return []
    except requests.RequestException as exc:
        log(f"API live indisponible ({exc}) -> on garde les données ouvertes.", "WARN")
        return []


def _parse_provider(provider: str, payload: Any) -> List[Dict]:
    """Normalise la réponse JSON du fournisseur en {player1, player2, ...}."""
    # À compléter par fournisseur. Laissé explicite pour brancher votre clé test.
    return []
