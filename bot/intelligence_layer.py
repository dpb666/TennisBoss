"""Sport Intelligence Layer — façade Phase 1.

Ne calcule rien de nouveau : regroupe en un seul objet ce que
`intelligence.py` (drift/blacklist/surfaces), `db.line_movement`
(mouvement de cotes) et `api._explain` (décomposition exacte du logit,
facteur par facteur) exposent déjà séparément. Sert de source unique à
`/api/insight`, qui répond à "pourquoi ce pick ?" en un seul appel au
lieu de 3 (auparavant : /api/predict + /api/intelligence/stats +
/api/line-movement, recomposés manuellement côté client).

Ne recalcule pas les facteurs depuis les features brutes : ça dupliquerait
`api._explain`, qui fait déjà une décomposition exacte du logit (pas une
approximation) et connaît le poids réel de chaque feature. On lui passe
son résultat tel quel.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db, intelligence


def _h2h_factor(n1: str, n2: str) -> Optional[Dict[str, Any]]:
    h2h = db.head_to_head(n1, n2)
    w1 = sum(1 for row in h2h if row["winner"] == n1)
    w2 = sum(1 for row in h2h if row["winner"] == n2)
    if not w1 and not w2:
        return None
    return {
        "key": "h2h", "label": "Confrontations directes",
        "value1": w1, "value2": w2,
        "favors": n1 if w1 > w2 else (n2 if w2 > w1 else None),
    }


def _model_health(n1: str, n2: str, surface: Optional[str]) -> Dict[str, Any]:
    stats = intelligence.stats()
    blacklist = set(stats.get("blacklist") or [])
    surface_danger = set(stats.get("surface_danger") or [])
    return {
        "player1_blacklisted": n1 in blacklist,
        "player2_blacklisted": n2 in blacklist,
        "surface_danger": bool(surface) and surface in surface_danger,
        "accuracy_drift_pts": stats.get("accuracy_drift_pts", 0.0),
    }


def build_insight(
    n1: str,
    n2: str,
    explain: Dict[str, Any],
    confidence: float = 0.0,
    confidence_label: str = "?",
    surface: Optional[str] = None,
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Agrège facteurs de décision + santé du modèle + mouvement de marché.

    `explain` est le résultat de `api._explain(...)` (décomposition exacte
    du logit) — on ne relance aucun calcul de prédiction ici.
    `confidence`/`confidence_label` viennent du même résultat de prédiction
    déjà calculé par l'appelant.
    """
    factors: List[Dict[str, Any]] = list(explain.get("factors") or [])
    h2h = _h2h_factor(n1, n2)
    if h2h:
        factors.append(h2h)
    market = db.line_movement(str(event_id)) if event_id else None
    return {
        "player1": n1,
        "player2": n2,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "decisive_factor": explain.get("decisive"),
        "factors": factors,
        "market": market,
        "model_health": _model_health(n1, n2, surface),
    }
