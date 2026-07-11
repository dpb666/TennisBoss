"""Sentiment/actualités joueurs via NewsAPI.org (Sport Intelligence Layer Phase 3).

Doc : https://newsapi.org/docs/endpoints/everything
  GET /v2/everything?q=<joueur>&language=en&sortBy=publishedAt&pageSize=10

NewsAPI ne fournit aucun score de sentiment — on l'estime nous-mêmes par
comptage de mots-clés positifs/négatifs dans titre+description. C'est une
heuristique grossière (pas un modèle NLP), assumée comme telle : un signal
informatif de plus, pas une vérité. Voir la note Phase 2/3 en tête de
bot/intelligence_layer.py — aucun signal de cette famille n'influence
predictor.predict() tant qu'il n'a pas été backtesté.

Le plan gratuit NewsAPI (100 req/jour, usage dev/test selon leurs CGU) est
volontairement protégé par un cache long (6h/joueur) : à 100 req/jour, un
appel par prédiction épuiserait le quota en quelques minutes.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

import requests

from .log import log

BASE = "https://newsapi.org/v2/everything"
TTL_SECONDS = 6 * 3600  # 6h — quota 100 req/jour, pas du temps réel nécessaire
MIN_ARTICLES = 2        # sous ce seuil, trop peu d'échantillon pour un score fiable

_CACHE: Dict[str, tuple] = {}   # name -> (expiry_ts, result)
_CACHE_LOCK = threading.Lock()

_POSITIVE_WORDS = {
    "win", "wins", "won", "victory", "triumph", "dominant", "impressive",
    "comeback", "surge", "form", "confident", "unstoppable", "record",
    "title", "champion", "advances", "upset win", "breakthrough",
}
_NEGATIVE_WORDS = {
    "injury", "injured", "withdraw", "withdrawal", "retires", "retirement",
    "loss", "lose", "lost", "defeat", "struggle", "struggling", "slump",
    "controversy", "ban", "suspended", "criticized", "collapse", "eliminated",
}


def _key() -> Optional[str]:
    return (os.environ.get("NEWSAPI_KEY") or "").strip() or None


def is_enabled() -> bool:
    return _key() is not None


def _score_articles(articles: List[Dict[str, Any]]) -> tuple:
    pos = neg = 0
    for a in articles:
        text = f"{a.get('title', '')} {a.get('description', '')}".lower()
        pos += sum(1 for w in _POSITIVE_WORDS if w in text)
        neg += sum(1 for w in _NEGATIVE_WORDS if w in text)
    total = pos + neg
    score = (pos - neg) / total if total else 0.0
    return score, pos, neg


def _label(score: float) -> str:
    if score > 0.3:
        return "positif"
    if score < -0.3:
        return "négatif"
    return "neutre"


def player_sentiment(name: str) -> Optional[Dict[str, Any]]:
    """Sentiment récent (7 jours) autour d'un joueur, ou None si indisponible.

    Retourne un score dans [-1, 1] (heuristique par mots-clés, pas un NLP
    entraîné) + les titres des articles trouvés, pour que l'humain juge lui-même.
    """
    key = _key()
    if not key:
        return None

    with _CACHE_LOCK:
        cached = _CACHE.get(name)
        if cached and cached[0] > time.time():
            return cached[1]

    try:
        resp = requests.get(BASE, params={
            "q": f'"{name}" tennis',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,
            "apiKey": key,
        }, timeout=8)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log(f"NewsAPI erreur pour {name}: {exc}", "WARN")
        return None

    articles = data.get("articles") or []
    result: Optional[Dict[str, Any]]
    if len(articles) < MIN_ARTICLES:
        result = None
    else:
        score, pos, neg = _score_articles(articles)
        result = {
            "player": name,
            "n_articles": len(articles),
            "score": round(score, 3),
            "label": _label(score),
            "headlines": [a.get("title", "") for a in articles[:5] if a.get("title")],
        }

    with _CACHE_LOCK:
        _CACHE[name] = (time.time() + TTL_SECONDS, result)
    return result
