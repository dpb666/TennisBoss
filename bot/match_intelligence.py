"""Tennis Intelligence Score (TIS) — Phase 12 (statistical model, no ML).

Agrège les signaux existants de intelligence_layer + prédiction modèle en un
score 0-100 et une recommandation de pari. Ne duplique aucune requête SQL :
réutilise form_signals, fatigue_signals, opponent_quality_signals, clutch_signals,
steam_move_signal, build_insight et weather_profile.surface_win_rate.

Poids des catégories (total = 100) :
  - player  40 % — confiance modèle, ELO, forme, fatigue, H2H, clutch
  - surface 25 % — win rate surface via weather_profile.surface_win_rate
  - market  35 % — EV, steam move, santé modèle (blacklist, drift)

Recommandations :
  - STRONG_BET : TIS >= 85 et EV >= 8 %
  - VALUE_BET  : TIS >= 75 et EV >= 3 %
  - WATCH      : TIS >= 60 et (EV > 0 ou pas de cotes)
  - NO_BET     : sinon

API — GET /api/match/intelligence
  Paramètres : p1, p2 (requis), surface (optionnel), event_key (optionnel)

Réponse JSON (forme pour Agent 2 / app Android) ::
  {
    "player1": str,
    "player2": str,
    "tis": float,              # 0-100, Tennis Intelligence Score
    "recommendation": str,     # STRONG_BET | VALUE_BET | WATCH | NO_BET
    "favorite": str,           # joueur favori selon le modèle
    "model_prob": float,       # probabilité match du favori (0-1)
    "ev_pct": float,           # EV estimée du favori en % (0 si pas de cotes)
    "edge_pct": float,         # écart modèle vs probabilité implicite marché en %
    "fair_odds": float|null,   # cote juste = 1 / model_prob
    "market_odds": float|null, # cote marché du favori
    "risk_score": float,       # 0-100, plus élevé = plus risqué
    "categories": {
      "player": float,         # sous-score 0-40
      "surface": float,        # sous-score 0-25
      "market": float,         # sous-score 0-35
    },
    "why": [str],              # bullets FR — raisons favorables (max 6)
    "risks": [str],            # bullets FR — risques identifiés (max 6)
    "confidence": float,       # confiance modèle 0-1
    "confidence_label": str,
    "surface": str|null,
  }
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import config, elo, features, intelligence_layer, predictor, weather_profile

_FEATURE_LABELS = {
    "serve": "Service",
    "return1": "Retour (1er service adverse)",
    "return2": "Retour (2e service adverse)",
    "recent": "Forme récente",
}


def _build_explain(
    mem: Dict[str, Any],
    name1: str,
    feat1: Dict[str, float],
    name2: str,
    feat2: Dict[str, float],
) -> Dict[str, Any]:
    """Décomposition logit (copie de api._explain, sans import circulaire)."""
    weights = mem["weights"]
    bias = float(mem["bias"])
    factors: List[Dict[str, Any]] = []
    z = bias
    for k in config.FEATURE_ORDER:
        w = float(weights.get(k, 0.0))
        v1 = float(feat1.get(k, 0.5))
        v2 = float(feat2.get(k, 0.5))
        contrib = w * (v1 - v2)
        z += contrib
        favors = name1 if contrib > 1e-9 else (name2 if contrib < -1e-9 else None)
        factors.append({
            "key": k,
            "label": _FEATURE_LABELS.get(k, k),
            "value1": round(v1, 4),
            "value2": round(v2, 4),
            "weight": round(w, 4),
            "contribution": round(contrib, 4),
            "favors": favors,
        })
    elo_ratings = mem.get("elo") or {}
    if elo_ratings:
        ra = elo_ratings.get(name1, predictor.ELO_BASE)
        rb = elo_ratings.get(name2, predictor.ELO_BASE)
        elo_contrib = predictor.elo_logit(mem, name1, name2)
        z += elo_contrib
        favors = name1 if elo_contrib > 1e-9 else (name2 if elo_contrib < -1e-9 else None)
        factors.append({
            "key": "elo",
            "label": "Niveau ELO (historique)",
            "value1": round(elo.expected(ra, rb), 4),
            "value2": round(elo.expected(rb, ra), 4),
            "weight": round(float(mem.get("elo_blend", predictor.ELO_BLEND)), 4),
            "contribution": round(elo_contrib, 4),
            "favors": favors,
        })
    decisive = max(factors, key=lambda f: abs(f["contribution"]))
    return {
        "bias": round(bias, 4),
        "logit": round(z, 4),
        "factors": factors,
        "decisive": decisive["key"],
        "model_accuracy": round(float(mem["metrics"].get("accuracy", 0.0)), 4),
    }

# Poids des trois catégories (total = 100).
WEIGHT_PLAYER = 40.0
WEIGHT_SURFACE = 25.0
WEIGHT_MARKET = 35.0

# Seuils de recommandation.
TIER_STRONG_TIS = 85.0
TIER_STRONG_EV = 8.0
TIER_VALUE_TIS = 75.0
TIER_VALUE_EV = 3.0
TIER_WATCH_TIS = 60.0


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _favorite_side(p1: str, p2: str, prob1_pct: float) -> Tuple[str, str]:
    if prob1_pct > 50.0:
        return p1, p2
    if prob1_pct < 50.0:
        return p2, p1
    return p1, p2


def _player_score(
    mem: Dict[str, Any],
    p1: str,
    p2: str,
    favorite: str,
    confidence: float,
    explain: Dict[str, Any],
) -> Tuple[float, List[str], List[str]]:
    """Score joueur (0-40) à partir de confiance modèle + signaux informatifs."""
    why: List[str] = []
    risks: List[str] = []
    score = confidence * WEIGHT_PLAYER

    # Contribution ELO / features (normalisée sur le logit).
    factors = explain.get("factors") or []
    elo_f = next((f for f in factors if f.get("key") == "elo"), None)
    if elo_f:
        contrib = abs(float(elo_f.get("contribution", 0.0)))
        elo_bonus = min(contrib * 4.0, 8.0)
        score += elo_bonus
        fav = elo_f.get("favors")
        if fav:
            why.append(f"Écart ELO en faveur de {fav.split()[-1]}")
        elif contrib < 0.05:
            risks.append("Écart ELO quasi nul — match serré")

    form_sigs = intelligence_layer.form_signals(mem, p1, p2)
    for sig in form_sigs:
        player = sig["player"]
        direction = sig["direction"]
        if player == favorite and direction == "surperformance":
            score += 4.0
            why.append(
                f"{player.split()[-1]} en surperformance "
                f"({sig['recent_form_pct']}% récent vs {sig['career_baseline_pct']}% carrière)"
            )
        elif player == favorite and direction == "méforme":
            score -= 5.0
            risks.append(
                f"{player.split()[-1]} en méforme "
                f"({sig['recent_form_pct']}% récent vs {sig['career_baseline_pct']}% carrière)"
            )
        elif player != favorite and direction == "surperformance":
            risks.append(f"{player.split()[-1]} monte en puissance récemment")

    for sig in intelligence_layer.fatigue_signals(p1, p2):
        if sig["player"] == favorite:
            score -= 4.0
            risks.append(
                f"{sig['player'].split()[-1]} fatigué "
                f"({sig['matches_recent']} matchs en {sig['window_days']} jours)"
            )

    for sig in intelligence_layer.rest_days_signals(p1, p2):
        if sig["player"] == favorite:
            if sig["flag"] == "enchainement_rapide":
                score -= 3.0
                risks.append(
                    f"{sig['player'].split()[-1]} joue après seulement {sig['rest_days']} jours de repos"
                )
            else:
                score -= 2.0
                risks.append(
                    f"{sig['player'].split()[-1]} revient après {sig['rest_days']} jours d'absence"
                )

    for sig in intelligence_layer.opponent_quality_signals(mem, p1, p2):
        if sig["player"] == favorite:
            if "plus forts" in sig["direction"]:
                score += 3.0
                why.append(
                    f"{sig['player'].split()[-1]} a affronté des adversaires plus forts récemment "
                    f"(ELO moy. {sig['avg_opponent_elo']})"
                )
            else:
                score -= 2.0
                risks.append(
                    f"Forme récente de {sig['player'].split()[-1]} gonflée par un calendrier facile"
                )

    for sig in intelligence_layer.clutch_signals(p1, p2):
        if sig["player"] == favorite:
            score += 2.0
            why.append(f"{sig['player'].split()[-1]} solide sous pression ({sig['direction']})")
        elif "fragile" in sig.get("direction", ""):
            risks.append(f"{sig['player'].split()[-1]} fragile sous pression")

    h2h = intelligence_layer._h2h_factor(p1, p2)  # noqa: SLF001 — réutilise la logique existante
    if h2h and h2h.get("favors"):
        if h2h["favors"] == favorite:
            score += 4.0
            why.append(
                f"H2H favorable à {favorite.split()[-1]} "
                f"({h2h['value1']}-{h2h['value2']})"
            )
        else:
            risks.append(
                f"H2H défavorable ({h2h['value1']}-{h2h['value2']})"
            )

    if confidence < 0.4:
        risks.append("Confiance modèle faible — profils incomplets ou match serré")
    elif confidence >= 0.75:
        why.append(f"Confiance modèle {int(confidence * 100)}%")

    return _clamp(score, 0.0, WEIGHT_PLAYER), why, risks


def _surface_score(
    mem: Dict[str, Any],
    p1: str,
    p2: str,
    favorite: str,
    surface: Optional[str],
) -> Tuple[float, List[str], List[str]]:
    """Score surface (0-25) via ELO surface / win rate approximé."""
    why: List[str] = []
    risks: List[str] = []
    if not surface:
        return WEIGHT_SURFACE * 0.5, [], ["Surface inconnue — score surface neutre"]

    surf1 = weather_profile.surface_win_rate(mem, p1)
    surf2 = weather_profile.surface_win_rate(mem, p2)
    s1 = surf1.get(surface)
    s2 = surf2.get(surface)

    if s1 is None and s2 is None:
        return WEIGHT_SURFACE * 0.5, [], [f"Peu de données sur {surface} pour ces joueurs"]

    v1 = s1 if s1 is not None else 0.5
    v2 = s2 if s2 is not None else 0.5
    delta = v1 - v2
    # delta typique 0.04-0.15 -> map vers 0-25
    magnitude = min(abs(delta) / 0.15, 1.0)
    base = WEIGHT_SURFACE * 0.5
    bonus = magnitude * (WEIGHT_SURFACE * 0.5)

    if delta > 0.02:
        score = base + bonus
        if favorite == p1:
            score += bonus * 0.3
            why.append(
                f"{p1.split()[-1]} performe mieux sur {surface} "
                f"({round(v1 * 100)}% vs {round(v2 * 100)}%)"
            )
        else:
            risks.append(
                f"{p1.split()[-1]} est plus à l'aise sur {surface} que le favori modèle"
            )
    elif delta < -0.02:
        score = base + bonus
        if favorite == p2:
            score += bonus * 0.3
            why.append(
                f"{p2.split()[-1]} performe mieux sur {surface} "
                f"({round(v2 * 100)}% vs {round(v1 * 100)}%)"
            )
        else:
            risks.append(
                f"{p2.split()[-1]} est plus à l'aise sur {surface} que le favori modèle"
            )
    else:
        score = base
        why.append(f"Pas d'avantage surface net sur {surface}")

    return _clamp(score, 0.0, WEIGHT_SURFACE), why, risks


def _market_score(
    favorite: str,
    p1: str,
    p2: str,
    odds_data: Optional[Dict[str, Any]],
    event_key: Optional[str],
    model_prob_fav: float,
    model_health: Dict[str, Any],
) -> Tuple[float, float, List[str], List[str]]:
    """Score marché (0-35) + EV (%) du côté favori modèle."""
    why: List[str] = []
    risks: List[str] = []
    ev_pct = 0.0
    score = WEIGHT_MARKET * 0.4  # neutre sans cotes

    if odds_data:
        fav_is_p1 = favorite == p1
        odds = float(odds_data.get("home_odds" if fav_is_p1 else "away_odds") or 0.0)
        if odds > 1.0:
            ev = model_prob_fav * odds - 1.0
            ev_pct = round(ev * 100.0, 1)
            if ev_pct >= TIER_STRONG_EV:
                score += 18.0
                why.append(f"EV estimée +{ev_pct}% sur {favorite.split()[-1]} (cote {odds})")
            elif ev_pct >= TIER_VALUE_EV:
                score += 12.0
                why.append(f"Value modérée +{ev_pct}% (cote {odds})")
            elif ev_pct > 0:
                score += 6.0
                why.append(f"Léger edge marché +{ev_pct}%")
            else:
                score -= 6.0
                risks.append(f"Pas de value marché (EV {ev_pct}%)")
        else:
            risks.append("Cotes indisponibles pour le calcul d'EV")

    steam = intelligence_layer.steam_move_signal(event_key)
    if steam:
        steam_fav = (steam["side"] == "home" and favorite == p1) or (
            steam["side"] == "away" and favorite == p2
        )
        if steam_fav:
            score += 8.0
            why.append(
                f"Steam move sur {favorite.split()[-1]} ({steam['move_pct']:.1f}%)"
            )
        else:
            score -= 4.0
            risks.append(
                f"Argent du marché va dans l'autre sens ({steam['move_pct']:.1f}%)"
            )

    if model_health.get("player1_blacklisted") and favorite == p1:
        score -= 8.0
        risks.append(f"{p1.split()[-1]} sur-listé par l'intelligence autonome")
    if model_health.get("player2_blacklisted") and favorite == p2:
        score -= 8.0
        risks.append(f"{p2.split()[-1]} sur-listé par l'intelligence autonome")
    if model_health.get("surface_danger"):
        score -= 5.0
        risks.append("Surface historiquement défavorable au modèle")

    drift = float(model_health.get("accuracy_drift_pts") or 0.0)
    if drift < -5.0:
        risks.append(f"Dérive de précision modèle ({drift:+.1f} pts)")

    return _clamp(score, 0.0, WEIGHT_MARKET), ev_pct, why, risks


def _edge_pct(model_prob_fav: float, market_odds: Optional[float]) -> float:
    """Écart modèle vs probabilité implicite du marché (points de %)."""
    if not market_odds or market_odds <= 1.0:
        return 0.0
    implied = 1.0 / market_odds
    return round((model_prob_fav - implied) * 100.0, 1)


def _risk_score(
    tis: float,
    risks: List[str],
    confidence: float,
    ev_pct: float,
    has_odds: bool,
    model_health: Dict[str, Any],
) -> float:
    """Score de risque 0-100 (plus élevé = plus risqué)."""
    score = len(risks) * 7.0
    score += max(0.0, (1.0 - confidence)) * 20.0
    if has_odds and ev_pct < 0:
        score += min(abs(ev_pct), 15.0)
    if model_health.get("player1_blacklisted") or model_health.get("player2_blacklisted"):
        score += 12.0
    if model_health.get("surface_danger"):
        score += 8.0
    drift = float(model_health.get("accuracy_drift_pts") or 0.0)
    if drift < -5.0:
        score += min(abs(drift), 10.0)
    score += (100.0 - tis) * 0.25
    return round(_clamp(score, 0.0, 100.0), 1)


def _recommendation(tis: float, ev_pct: float, has_odds: bool) -> str:
    if tis >= TIER_STRONG_TIS and ev_pct >= TIER_STRONG_EV:
        return "STRONG_BET"
    if tis >= TIER_VALUE_TIS and ev_pct >= TIER_VALUE_EV:
        return "VALUE_BET"
    if tis >= TIER_WATCH_TIS and (ev_pct > 0 or not has_odds):
        return "WATCH"
    return "NO_BET"


def compute_tis(
    p1: str,
    p2: str,
    surface: Optional[str] = None,
    odds_data: Optional[Dict[str, Any]] = None,
    *,
    mem: Dict[str, Any],
    event_key: Optional[str] = None,
    explain: Optional[Dict[str, Any]] = None,
    prediction: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Calcule le Tennis Intelligence Score (0-100) et la recommandation.

    `odds_data` : dict avec home_odds, away_odds (optionnel home_prob/away_prob).
    `mem` : état mémoire (profils, ELO, poids) — requis.
    `event_key` : id odds-api pour steam move / line movement.
    `explain` / `prediction` : optionnels, recalculés si absents.
    """
    f1 = features.feature_vector(features.get_profile(mem, p1))
    f2 = features.feature_vector(features.get_profile(mem, p2))
    if prediction is None:
        prediction = predictor.predict(mem, p1, f1, p2, f2, surface=surface)
    if explain is None:
        explain = _build_explain(mem, p1, f1, p2, f2)

    prob1_pct = float(prediction["prob1"])
    favorite, _underdog = _favorite_side(p1, p2, prob1_pct)
    confidence = float(prediction.get("confidence", 0.0))
    p_set = prob1_pct / 100.0
    p_match_p1 = predictor.set_to_match_prob(p_set)
    model_prob_fav = p_match_p1 if favorite == p1 else (1.0 - p_match_p1)

    model_health = intelligence_layer._model_health(p1, p2, surface)  # noqa: SLF001

    p_score, p_why, p_risks = _player_score(mem, p1, p2, favorite, confidence, explain)
    s_score, s_why, s_risks = _surface_score(mem, p1, p2, favorite, surface)
    m_score, ev_pct, m_why, m_risks = _market_score(
        favorite, p1, p2, odds_data, event_key, model_prob_fav, model_health,
    )

    tis = round(_clamp(p_score + s_score + m_score), 1)
    why = (p_why + s_why + m_why)[:6]
    risks = (p_risks + s_risks + m_risks)[:6]
    tier = _recommendation(tis, ev_pct, has_odds=bool(odds_data))

    fav_odds = None
    if odds_data:
        fav_odds = odds_data.get("home_odds" if favorite == p1 else "away_odds")
    edge = _edge_pct(model_prob_fav, float(fav_odds) if fav_odds else None)
    risk = _risk_score(tis, risks, confidence, ev_pct, bool(odds_data), model_health)

    return {
        "tis": tis,
        "recommendation": tier,
        "favorite": favorite,
        "model_prob": round(model_prob_fav, 4),
        "ev_pct": ev_pct,
        "edge_pct": edge,
        "fair_odds": round(1.0 / model_prob_fav, 2) if model_prob_fav > 0 else None,
        "market_odds": fav_odds,
        "risk_score": risk,
        "categories": {
            "player": round(p_score, 1),
            "surface": round(s_score, 1),
            "market": round(m_score, 1),
        },
        "why": why,
        "risks": risks,
        "confidence": confidence,
        "confidence_label": prediction.get("confidence_label", ""),
        "surface": surface or prediction.get("surface"),
    }
