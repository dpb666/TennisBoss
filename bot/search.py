"""Recherche de données fraîches pour le chat — API-Tennis en priorité, DDG en fallback."""
from __future__ import annotations

import re
from typing import Optional

from .log import log

_TRIGGER_FR = re.compile(
    r"\b(aujourd['']?hui|demain|hier|cette semaine|ce soir|"
    r"prochain|prochains|résultat|résultats|score|scores|live|"
    r"classement atp|classement wta|tournoi|draw|tableau|finale|"
    r"demi.finale|quart|programme|calendrier|bless[eé]|forfait|"
    r"retraite|wild.?card|tête de série)\b",
    re.IGNORECASE,
)
_TRIGGER_EN = re.compile(
    r"\b(today|tomorrow|yesterday|this week|tonight|"
    r"next|upcoming|result|results|score|scores|live|"
    r"atp ranking|wta ranking|tournament|draw|final|"
    r"semi.?final|quarter|schedule|calendar|injured|injury|"
    r"withdraw|retirement|wild.?card|seeding)\b",
    re.IGNORECASE,
)

_SNIPPET_LEN = 200


def needs_search(message: str) -> bool:
    return bool(_TRIGGER_FR.search(message) or _TRIGGER_EN.search(message))


def web_search(query: str) -> Optional[str]:
    """Retourne un bloc texte avec données fraîches, ou None."""
    result = _search_api_tennis(query)
    if result:
        return result
    return _search_ddg(query)


def _search_api_tennis(query: str) -> Optional[str]:
    """Utilise l'API-Tennis pour résultats récents + matchs à venir."""
    try:
        from . import config
        from .live_api import fetch_results, fetch_upcoming, load_env
        load_env()
        cfg = config.DEFAULT_CONFIG
        lines = []

        results = fetch_results(cfg, days_back=2)
        if results:
            lines.append("Résultats récents :")
            for m in results[:8]:
                winner_name = m["player1"] if m["winner"] == "p1" else m["player2"]
                lines.append(
                    f"  {m['player1']} vs {m['player2']} — {m['final_score']} "
                    f"(vainqueur: {winner_name}) [{m['tournament']} {m['round']}]"
                )

        upcoming = fetch_upcoming(cfg, days_ahead=2)
        if upcoming:
            lines.append("Matchs à venir :")
            for m in upcoming[:6]:
                lines.append(
                    f"  {m['player1']} vs {m['player2']} — {m.get('date','')} "
                    f"[{m.get('tournament','')}]"
                )

        return "\n".join(lines) if lines else None
    except Exception as exc:
        log(f"API-Tennis search échoué : {exc}", "WARN")
        return None


def _search_ddg(query: str) -> Optional[str]:
    """Fallback DuckDuckGo si API-Tennis ne répond pas."""
    try:
        from ddgs import DDGS
        results = DDGS().text(f"tennis {query}", max_results=3, safesearch="off")
        if not results:
            return None
        lines = [
            f"- {(r.get('body') or '').strip()[:_SNIPPET_LEN]}"
            for r in results
            if r.get("body")
        ]
        return "\n".join(lines) if lines else None
    except Exception as exc:
        log(f"DDG search échoué : {exc}", "WARN")
        return None
