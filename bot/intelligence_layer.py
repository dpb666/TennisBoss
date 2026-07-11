"""Sport Intelligence Layer — façade Phase 1 + Pattern Detection Phase 2 + Phase 3.

Ne calcule rien de nouveau pour la partie Phase 1 : regroupe en un seul
objet ce que `intelligence.py` (drift/blacklist/surfaces), `db.line_movement`
(mouvement de cotes) et `api._explain` (décomposition exacte du logit,
facteur par facteur) exposent déjà séparément. Sert de source unique à
`/api/insight`, qui répond à "pourquoi ce pick ?" en un seul appel au
lieu de 3 (auparavant : /api/predict + /api/intelligence/stats +
/api/line-movement, recomposés manuellement côté client).

Ne recalcule pas les facteurs depuis les features brutes : ça dupliquerait
`api._explain`, qui fait déjà une décomposition exacte du logit (pas une
approximation) et connaît le poids réel de chaque feature. On lui passe
son résultat tel quel.

Phase 2 ajoute deux signaux réellement nouveaux (form_signal, steam_move),
mais volontairement INFORMATIFS UNIQUEMENT : ni l'un ni l'autre n'entre
dans predictor.predict() ni dans le filtre is_value de /api/value. Le
memory du projet est explicite là-dessus (modèle déjà surconfiant, calib_k
figé à 1.0 faute de recul) — un signal non backtesté qui influencerait une
probabilité répéterait cette erreur. Une fois assez de picks avec/sans ces
signaux réglés (voir bot/clv.py), un backtest décidera s'ils méritent de
peser sur le modèle.

Phase 3 ajoute le sentiment/actualités (bot/sentiment.py, NewsAPI.org) —
même prudence : informatif uniquement. Contrainte supplémentaire propre à
cette source : le plan gratuit NewsAPI est à 100 requêtes/jour (bien plus
serré que le pool ODDS_API). Le signal est donc désactivé par défaut dans
/api/insight (paramètre `sentiment=true` explicite) plutôt qu'appelé à
chaque ouverture de "Pourquoi ce pick ?" côté app — un signal qui grille le
quota en quelques minutes d'usage normal serait pire qu'utile.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db, intelligence, sentiment

# Écart (points de %) entre forme récente (EMA) et bilan carrière pour
# déclencher un signal de bascule de forme. En dessous, c'est du bruit normal
# d'échantillonnage, pas un vrai changement de niveau.
FORM_SWING_THRESHOLD_PTS = 15.0
FORM_SWING_MIN_MATCHES = 10

# Mouvement de cote (%) entre ouverture et dernier relevé pour parler de
# "steam move" (argent qui bouge la ligne) plutôt que du bruit de marché normal.
STEAM_MOVE_THRESHOLD_PCT = 15.0


def _form_signal(name: str, prof: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Compare la forme récente (EMA `recent`) au bilan carrière du joueur.

    Un écart important suggère une bascule de niveau que l'EMA seule (déjà
    lissée) peut sous-représenter — utile à l'œil humain, pas injecté dans
    le modèle (voir note Phase 2 en tête de fichier).
    """
    n = int(prof.get("n", 0))
    if n < FORM_SWING_MIN_MATCHES:
        return None
    record = db.player_record(name)
    total = record["wins"] + record["losses"]
    if total < FORM_SWING_MIN_MATCHES:
        return None
    recent = float(prof.get("recent", 0.5))
    baseline = record["wins"] / total
    diff_pts = (recent - baseline) * 100
    if abs(diff_pts) < FORM_SWING_THRESHOLD_PTS:
        return None
    return {
        "player": name,
        "direction": "surperformance" if diff_pts > 0 else "méforme",
        "recent_form_pct": round(recent * 100, 1),
        "career_baseline_pct": round(baseline * 100, 1),
        "diff_pts": round(diff_pts, 1),
    }


def form_signals(mem: Dict[str, Any], n1: str, n2: str) -> List[Dict[str, Any]]:
    from . import features
    out = []
    for name in (n1, n2):
        sig = _form_signal(name, features.get_profile(mem, name))
        if sig:
            out.append(sig)
    return out


def steam_move_signal(event_id: Optional[Any]) -> Optional[Dict[str, Any]]:
    """Mouvement de cote anormal capté par le scanner, si suivi pour ce match.

    Purement diagnostique : n'affecte ni le calcul d'EV ni le filtre
    `is_value` de /api/value (voir note Phase 2 en tête de fichier).
    """
    if not event_id:
        return None
    mv = db.line_movement(str(event_id))
    if not mv or mv.get("n_snapshots", 0) < 2:
        return None
    move_home, move_away = mv["move_home_pct"], mv["move_away_pct"]
    biggest = move_home if abs(move_home) >= abs(move_away) else move_away
    if abs(biggest) < STEAM_MOVE_THRESHOLD_PCT:
        return None
    return {
        "side": "home" if biggest == move_home else "away",
        "move_pct": biggest,
        "n_snapshots": mv["n_snapshots"],
    }


def sentiment_signals(n1: str, n2: str) -> List[Dict[str, Any]]:
    """Sentiment récent (NewsAPI) pour les 2 joueurs, si NEWSAPI_KEY configurée.

    Appelant responsable d'activer ceci explicitement (voir note Phase 3 en
    tête de fichier) — pas de coût caché.
    """
    if not sentiment.is_enabled():
        return []
    out = []
    for name in (n1, n2):
        sig = sentiment.player_sentiment(name)
        if sig:
            out.append(sig)
    return out


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
    mem: Dict[str, Any],
    n1: str,
    n2: str,
    explain: Dict[str, Any],
    confidence: float = 0.0,
    confidence_label: str = "?",
    surface: Optional[str] = None,
    event_id: Optional[str] = None,
    include_sentiment: bool = False,
) -> Dict[str, Any]:
    """Agrège facteurs de décision + santé du modèle + mouvement de marché.

    `explain` est le résultat de `api._explain(...)` (décomposition exacte
    du logit) — on ne relance aucun calcul de prédiction ici.
    `confidence`/`confidence_label` viennent du même résultat de prédiction
    déjà calculé par l'appelant. `mem` sert uniquement à lire les profils
    joueurs pour `form_signals` (EMA déjà en mémoire, pas de recalcul).
    `include_sentiment` : opt-in explicite (voir note Phase 3, quota NewsAPI).
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
        "form_signals": form_signals(mem, n1, n2),
        "sentiment_signals": sentiment_signals(n1, n2) if include_sentiment else [],
        "market": market,
        "model_health": _model_health(n1, n2, surface),
    }
