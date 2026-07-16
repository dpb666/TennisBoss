"""Orchestrateur d'intentions pour l'assistant IA TennisBoss (Phase 1, Slice 1).

Classification par mots-clés (pas de function-calling LLM dans ce slice,
voir docs/AI_ASSISTANT_ARCHITECTURE.md §3.3) : détecte l'intention d'un
message, exécute les outils de lecture seule pertinents
(ai/chat/tools/registry.py), et construit un bloc de contexte texte destiné
à bot/chat.py::chat()'s `extra_context` — s'ajoute à build_match_context(),
ne le remplace jamais (bot/api.py n'appelle ceci QUE quand
build_match_context() n'a rien trouvé, cf. api_chat()).

Garde-fou : n'importe JAMAIS bot.predictor / bot.calibrate / bot.learner —
vérifié par tests/test_ai_tools.py::test_no_frozen_imports.
"""
from __future__ import annotations

import re
from typing import Dict, List, Pattern, Tuple

from .tools import registry

_INTENT_PATTERNS: Dict[str, Pattern] = {
    "bet_history": re.compile(
        r"\broi\b|bet.?history|historique.*pari|win.?rate|taux de r[ée]ussite|performance", re.I),
    "calibration": re.compile(
        r"calibrat|brier|log.?loss|surconf|overconf|bien calibr", re.I),
    "logging_health": re.compile(
        r"logging|compl[ée]tude|completeness|donn[ée]es manquantes", re.I),
    "api_endpoints": re.compile(r"endpoint|\bapi\b|route\b", re.I),
    "architecture": re.compile(
        r"architecture|comment (ça|ca) marche|structure du projet|comment (le|ce) syst[èe]me", re.I),
}

# Ordre d'exécution stable — utilisé pour construire le bloc de contexte
# dans un ordre déterministe (important pour les tests et la lisibilité).
_INTENT_ORDER = ("bet_history", "calibration", "logging_health", "api_endpoints", "architecture")


def classify_intents(message: str) -> List[str]:
    """Renvoie les intentions détectées (0, 1 ou plusieurs), ordre stable."""
    return [name for name in _INTENT_ORDER if _INTENT_PATTERNS[name].search(message or "")]


def run_tools_for_message(message: str, days: int = 30) -> Tuple[str, List[str], List[str]]:
    """Exécute les outils pertinents pour `message`.

    Renvoie (bloc de contexte texte, noms d'outils appelés, sources).
    Renvoie ("", [], []) si aucune intention n'est détectée — dans ce cas
    l'appelant (bot/api.py) garde son comportement inchangé (`extra`
    reste vide, exactement comme avant l'existence de ce module).
    """
    intents = classify_intents(message)
    if not intents:
        return "", [], []

    blocks: List[str] = []
    tools_called: List[str] = []
    sources: List[str] = []

    def _emit(result: registry.ToolResult) -> None:
        if result.summary:
            blocks.append(result.summary)
            tools_called.append(result.name)
            sources.append(result.source)

    if "bet_history" in intents:
        _emit(registry.query_bet_history(days=days))
    if "calibration" in intents:
        _emit(registry.get_calibration_summary(days=max(days, 90)))
    if "logging_health" in intents:
        _emit(registry.get_logging_health())
    if "api_endpoints" in intents:
        _emit(registry.list_api_endpoints())
    if "architecture" in intents:
        _emit(registry.read_doc("ai_architecture"))

    return "\n".join(blocks), tools_called, sources
