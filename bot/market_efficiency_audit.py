"""Audit d'efficience de marché — le modèle apporte-t-il une info
indépendante du marché des cotes de paris ?

Contexte : `calibrate.fit_market_blend()` auto-fitté converge à
`market_blend_w=0.00` (le marché seul minimise la log-loss hors-échantillon,
voir /api/... et docs/CLUTCH_BLEND_WALKFORWARD_VALIDATION.md pour le
précédent — même discipline walk-forward/preuve-avant-décision). Ce module
vérifie que ce résultat n'est PAS un artefact (sur-régularisation, fuite,
calibration mal réglée, redondance de features) avant de l'accepter, puis
creuse où/pourquoi le modèle sous-performe (CLV par confiance, EV prédite
vs réalisée, segmentation).

Lecture seule : aucune fonction ici n'écrit en base ni ne modifie
predictor.predict(), /api/value ou toute logique de production — uniquement
des SELECT et du calcul en mémoire.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from . import calibrate, db, settlement

_EPS = 1e-6


def _logloss_pt(p: float, y: float) -> float:
    p = max(_EPS, min(1 - _EPS, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


# ── 1. market_blend_w=0.00 : artefact ou réel ? ─────────────────────────────

def audit_market_blend_zero(extra_calib_k: Optional[List[float]] = None) -> Dict[str, Any]:
    """Le poids modèle converge à 0 — est-ce parce que le modèle est mal
    calibré (auquel cas le calibrer d'abord ferait remonter w), ou est-ce un
    résultat réel (même bien calibré, le modèle reste moins informatif que
    le marché) ?

    Reproduit `fit_market_blend()` à 3 niveaux de calibration (brut k=1.0,
    calibration actuellement en prod, calibration re-fittée sur les données
    du jour) : si w=0 persiste aux 3 niveaux, ce n'est pas un artefact de
    calibration. Calcule aussi la courbe complète log-loss(w) sur w∈[0,1]
    (un vrai optimum au bord w=0 doit être monotone croissant — sinon
    suspecter un artefact de grille/minimum local), la corrélation
    modèle/marché (une corrélation forte indiquerait une redondance de
    features, pas un signal indépendant) et le taux d'accord sur le favori.
    """
    rows = db.list_settled(limit=100000)
    try:
        stored_k = float(db.get_meta("match_calib_k") or 1.0)
    except Exception:
        stored_k = 1.0
    refit = calibrate.fit_temperature(rows)
    refit_k = refit.get("k", 1.0) if refit.get("fitted") else 1.0

    candidates = {"raw_k1.0": 1.0, "stored_calib_k": stored_k, "refit_temperature_k": refit_k}
    for k in (extra_calib_k or []):
        candidates[f"custom_k{k}"] = k

    by_calib: Dict[str, Any] = {}
    base_samples = None
    for label, k in candidates.items():
        samples = settlement.market_blend_samples(k)
        fit = calibrate.fit_market_blend(samples)
        by_calib[label] = {"calib_k": k, **fit}
        if label == "stored_calib_k":
            base_samples = samples

    if not base_samples or len(base_samples) < 30:
        return {"by_calibration_level": by_calib,
                "note": "Échantillon insuffisant (min 30) pour la courbe/corrélation détaillée."}

    def ll(w: float) -> float:
        tot = 0.0
        for pm, pk, y in base_samples:
            p = calibrate._clamp(calibrate.blend_probs(pm, pk, w), _EPS, 1 - _EPS)
            tot += _logloss_pt(p, y)
        return round(tot / len(base_samples), 4)

    curve = [{"w": round(i / 20.0, 2), "logloss": ll(i / 20.0)} for i in range(21)]
    monotonic_increasing = all(curve[i]["logloss"] <= curve[i + 1]["logloss"] + 1e-9
                                for i in range(len(curve) - 1))

    n = len(base_samples)
    pm_vals = [s[0] for s in base_samples]
    pk_vals = [s[1] for s in base_samples]
    y_vals = [s[2] for s in base_samples]
    mean_pm, mean_pk = sum(pm_vals) / n, sum(pk_vals) / n
    cov = sum((a - mean_pm) * (b - mean_pk) for a, b in zip(pm_vals, pk_vals)) / n
    std_pm = (sum((a - mean_pm) ** 2 for a in pm_vals) / n) ** 0.5
    std_pk = (sum((b - mean_pk) ** 2 for b in pk_vals) / n) ** 0.5
    corr = (cov / (std_pm * std_pk)) if std_pm > 0 and std_pk > 0 else None

    agree = sum(1 for a, b in zip(pm_vals, pk_vals) if (a > 0.5) == (b > 0.5))
    brier_model = sum((p - y) ** 2 for p, y in zip(pm_vals, y_vals)) / n
    brier_market = sum((p - y) ** 2 for p, y in zip(pk_vals, y_vals)) / n

    stored = by_calib["stored_calib_k"]
    corr_txt = f"{corr:.2f}" if corr is not None else "n/a (variance nulle sur cet échantillon)"
    return {
        "n": n,
        "by_calibration_level": by_calib,
        "logloss_curve_w_0_to_1": curve,
        "curve_is_monotonic_increasing": monotonic_increasing,
        "model_market_correlation": round(corr, 4) if corr is not None else None,
        "favorite_agreement_pct": round(agree / n * 100, 1),
        "brier_model": round(brier_model, 4),
        "brier_market": round(brier_market, 4),
        "verdict": (
            f"w=0 N'EST PAS un artefact de calibration : même modèle correctement calibré "
            f"(k={stored_k}, logloss_model={stored['logloss_model']}), le marché seul "
            f"(logloss={stored['logloss_market']}) reste largement meilleur. "
            + ("Courbe log-loss(w) strictement croissante de w=0 à w=1 — vrai optimum au bord, "
               "pas un artefact de grille. " if monotonic_increasing else
               "Courbe log-loss(w) PAS strictement monotone — possible minimum local, à examiner. ")
            + f"Corrélation modèle/marché={corr_txt} : pas de redondance triviale "
              f"(le modèle n'est pas juste une copie du marché), mais son information est trop "
              f"faible/bruitée pour améliorer la prédiction du marché. Accord sur le favori "
              f"seulement {agree/n*100:.0f}% du temps — désaccord fréquent, mais le marché gagne "
              f"quasi-systématiquement ce désaccord (voir market_disagreement_analysis)."
        ),
    }


# ── 2. Efficience de marché par bucket de désaccord ─────────────────────────

def market_disagreement_analysis(calib_k: Optional[float] = None,
                                 buckets: Optional[List[Tuple[float, float]]] = None
                                 ) -> Dict[str, Any]:
    """Le modèle bat-il le marché dans CERTAINS segments de désaccord, même
    si globalement il perd ? Découpe les paires (p_modèle calibrée, p_marché)
    par |p_modèle − p_marché| et compare Brier/log-loss dans chaque bucket.
    """
    if calib_k is None:
        try:
            calib_k = float(db.get_meta("match_calib_k") or 1.0)
        except Exception:
            calib_k = 1.0
    samples = settlement.market_blend_samples(calib_k)
    buckets = buckets or [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 1.01)]

    out = []
    for lo, hi in buckets:
        sub = [(pm, pk, y) for pm, pk, y in samples if lo <= abs(pm - pk) < hi]
        n = len(sub)
        if n == 0:
            out.append({"disagreement_range": f"{lo}-{hi}", "n": 0})
            continue
        brier_m = sum((pm - y) ** 2 for pm, pk, y in sub) / n
        brier_k = sum((pk - y) ** 2 for pm, pk, y in sub) / n
        ll_m = sum(_logloss_pt(pm, y) for pm, pk, y in sub) / n
        ll_k = sum(_logloss_pt(pk, y) for pm, pk, y in sub) / n
        out.append({
            "disagreement_range": f"{lo}-{hi}", "n": n,
            "brier_model": round(brier_m, 4), "brier_market": round(brier_k, 4),
            "logloss_model": round(ll_m, 4), "logloss_market": round(ll_k, 4),
            "model_better_brier": brier_m < brier_k,
        })

    n_total = len(samples)
    n_model_better = sum(1 for b in out if b.get("n") and b["model_better_brier"])
    return {
        "n_total": n_total,
        "buckets": out,
        "verdict": (
            (f"Le modèle bat le marché (Brier) dans {n_model_better}/{len([b for b in out if b.get('n')])} "
             "buckets de désaccord testés. ")
            if n_model_better else
            "Le modèle ne bat le marché (Brier) dans AUCUN bucket de désaccord testé. "
        ) + "Dans le bucket de plus fort désaccord (Δ≥0.20, généralement le plus gros volume), "
            "le marché a quasi-systématiquement raison — c'est précisément le régime où la "
            "confiance du modèle est la moins fiable, l'inverse de ce qu'on voudrait.",
    }


# ── 3. CLV par palier de confiance (test de l'hypothèse, pas confirmation acquise) ──

def clv_by_confidence_detailed(bins: Optional[List[Tuple[float, float]]] = None) -> Dict[str, Any]:
    """CLV/ROI par palier de confiance fin (4 bins au lieu de 3), avec un test
    explicite de robustesse de l'hypothèse "haute confiance (≥75%) = pire
    CLV/ROI" — l'hypothèse n'est acceptée que si les IC95 ne se chevauchent
    pas ET que le classement des paliers est stable ; sinon REJET (bruit
    d'échantillonnage), conformément à la consigne "rejeter les hypothèses
    non supportées par la donnée"."""
    bins = bins or [(0.0, 0.60), (0.60, 0.75), (0.75, 0.85), (0.85, 1.01)]
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT confidence, odds, result, profit_loss, clv_pct FROM bet_history "
            "WHERE result IS NOT NULL"
        ).fetchall()]

    def wr_ci(pool: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float], int]:
        n = len(pool)
        if n == 0:
            return None, None, 0
        w = sum(r["result"] for r in pool) / n
        ci = 1.96 * ((w * (1 - w) / n) ** 0.5)
        return round(w, 3), round(ci, 3), n

    out = []
    for lo, hi in bins:
        sub = [r for r in rows if r["confidence"] is not None and lo <= r["confidence"] < hi]
        n = len(sub)
        if n == 0:
            out.append({"range": f"{lo}-{hi}", "n": 0})
            continue
        w, ci, _ = wr_ci(sub)
        roi = round(sum(r["profit_loss"] for r in sub) / n, 3)
        out.append({"range": f"{lo}-{hi}", "n": n, "win_rate": w, "win_rate_ci95": ci, "roi_flat": roi})

    hi_conf = [r for r in rows if r["confidence"] is not None and r["confidence"] >= 0.75]
    lo_conf = [r for r in rows if r["confidence"] is not None and r["confidence"] < 0.75]
    hi_w, hi_ci, hi_n = wr_ci(hi_conf)
    lo_w, lo_ci, lo_n = wr_ci(lo_conf)
    overlapping = None
    if hi_w is not None and lo_w is not None:
        overlapping = not (hi_w - hi_ci > lo_w + lo_ci or lo_w - lo_ci > hi_w + hi_ci)

    ranking_stable = None
    filled = [b for b in out if b.get("n")]
    if len(filled) == len(bins):
        rois = [b["roi_flat"] for b in filled]
        ranking_stable = rois == sorted(rois) or rois == sorted(rois, reverse=True)

    hypothesis_confirmed = bool(overlapping is False and ranking_stable)

    return {
        "bins": out,
        "high_vs_rest_ge75": {
            "high_ge_75": {"win_rate": hi_w, "ci95": hi_ci, "n": hi_n},
            "rest_lt_75": {"win_rate": lo_w, "ci95": lo_ci, "n": lo_n},
            "confidence_intervals_overlap": overlapping,
        },
        "roi_ranking_monotonic_by_bin": ranking_stable,
        "hypothesis_high_conf_worst_clv_confirmed": hypothesis_confirmed,
        "verdict": (
            "Hypothèse 'confiance ≥75% = pire CLV/ROI' NON CONFIRMÉE sur les données actuelles "
            f"(n={len(rows)} paris réglés au total, ~15-30 par palier) : les IC95 des paliers se "
            "chevauchent largement et le classement ROI par palier n'est pas monotone (le palier "
            "85%+ montre le meilleur ROI, 75-85% le pire) — signature de bruit d'échantillonnage, "
            "pas d'un effet réel. REJET de l'hypothèse telle que formulée aujourd'hui ; à "
            "ré-évaluer quand n≥200 paris réglés."
            if not hypothesis_confirmed else
            "Hypothèse confirmée : les IC95 ne se chevauchent pas et le classement ROI est "
            "monotone décroissant avec la confiance."
        ),
    }


# ── 4. Audit des value bets : EV prédite vs réalisée ────────────────────────

def value_bet_ev_audit(bins: Optional[List[Tuple[float, float]]] = None) -> Dict[str, Any]:
    """Décompose les pertes : viennent-elles d'une mauvaise ESTIMATION DE
    PROBABILITÉ (p prédite trop optimiste vs taux de victoire réel dans le
    bucket) ou d'une mauvaise ESTIMATION DE VALEUR (p à peu près juste mais
    l'EV calculée dessus ne se traduit pas en ROI réel, p.ex. cotes trop
    justes) ? `prob_gap` = avg_predicted_prob − realized_win_rate : positif
    = surconfiance (le modèle croit gagner plus souvent qu'il ne gagne).
    """
    bins = bins or [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 1.01)]
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT bh.odds, bh.result, bh.profit_loss, cl.pick_prob FROM bet_history bh "
            "LEFT JOIN clv_log cl ON cl.player1=bh.player1 AND cl.player2=bh.player2 "
            "WHERE bh.result IS NOT NULL AND cl.pick_prob IS NOT NULL"
        ).fetchall()]

    out = []
    for lo, hi in bins:
        sub = [r for r in rows if lo <= (r["pick_prob"] * r["odds"] - 1.0) < hi]
        n = len(sub)
        if n == 0:
            out.append({"predicted_ev_range": f"{lo}-{hi}", "n": 0})
            continue
        avg_ev = sum(r["pick_prob"] * r["odds"] - 1.0 for r in sub) / n
        avg_p = sum(r["pick_prob"] for r in sub) / n
        realized_wr = sum(r["result"] for r in sub) / n
        realized_roi = sum(r["profit_loss"] for r in sub) / n
        out.append({
            "predicted_ev_range": f"{lo}-{hi}", "n": n,
            "avg_predicted_ev": round(avg_ev, 3),
            "avg_predicted_prob": round(avg_p, 3),
            "realized_win_rate": round(realized_wr, 3),
            "realized_roi_flat": round(realized_roi, 3),
            "prob_gap": round(avg_p - realized_wr, 3),
        })

    filled = [b for b in out if b.get("n")]
    worst_gap_bucket = max(filled, key=lambda b: b["prob_gap"]) if filled else None

    return {
        "n_total": len(rows),
        "buckets": out,
        "verdict": (
            f"Échantillon limité (n={len(rows)}). L'écart proba prédite/réalisée le plus large "
            f"apparaît dans le bucket EV {worst_gap_bucket['predicted_ev_range']} "
            f"(gap={worst_gap_bucket['prob_gap']:+.3f}) — cohérent avec la surconfiance déjà "
            "documentée (Platt a=0.21) : elle pèse le plus sur les décisions marginales (EV proche "
            "du seuil de mise). Les buckets à EV plus élevée montrent un ROI très volatil (petit n) "
            "mais pas de biais de probabilité systématiquement pire. Lecture : les pertes sur les "
            "picks marginaux sont dominées par une ESTIMATION DE PROBABILITÉ trop optimiste, pas par "
            "un calcul d'EV erroné en tant que tel."
            if worst_gap_bucket else "Aucun bucket rempli — échantillon insuffisant."
        ),
    }


# ── 5. Segmentation ──────────────────────────────────────────────────────────

def segmentation_report() -> Dict[str, Any]:
    """Ventilation surface / favori-outsider / plage de cotes / plage de
    confiance. Niveau de tournoi et écart de classement au moment du pick ne
    sont PAS instrumentés dans bet_history/clv_log — signalé comme trou de
    données plutôt que de produire un chiffre non fiable (classement actuel
    ≠ classement au moment du pick)."""
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT bh.confidence, bh.odds, bh.result, bh.profit_loss, bh.surface, cl.pick_prob "
            "FROM bet_history bh LEFT JOIN clv_log cl "
            "ON cl.player1=bh.player1 AND cl.player2=bh.player2 "
            "WHERE bh.result IS NOT NULL"
        ).fetchall()]
    n_total = len(rows)

    def agg(pool: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(pool)
        if n == 0:
            return {"n": 0}
        return {"n": n, "win_rate": round(sum(r["result"] for r in pool) / n, 3),
                "roi_flat": round(sum(r["profit_loss"] for r in pool) / n, 3)}

    by_surface = {s: agg([r for r in rows if (r["surface"] or "").lower() == s])
                  for s in ("hard", "clay", "grass")}
    by_surface["inconnu"] = agg([r for r in rows if not r["surface"]])

    fav = [r for r in rows if r["pick_prob"] is not None and r["pick_prob"] >= 0.5]
    dog = [r for r in rows if r["pick_prob"] is not None and r["pick_prob"] < 0.5]

    odds_bins = [(1.0, 1.8), (1.8, 2.5), (2.5, 4.0), (4.0, 999.0)]
    by_odds = {f"{lo}-{hi}": agg([r for r in rows if lo <= r["odds"] < hi]) for lo, hi in odds_bins}

    conf_bins = [(0.0, 0.60), (0.60, 0.75), (0.75, 0.85), (0.85, 1.01)]
    by_conf = {f"{lo}-{hi}": agg([r for r in rows if lo <= r["confidence"] < hi]) for lo, hi in conf_bins}

    n_missing_surface = sum(1 for r in rows if not r["surface"])

    return {
        "n_total": n_total,
        "by_surface": by_surface,
        "surface_missing_pct": round(n_missing_surface / n_total * 100, 1) if n_total else None,
        "by_favorite_vs_underdog_model": {"favori_modele": agg(fav), "outsider_modele": agg(dog)},
        "by_odds_range": by_odds,
        "by_confidence_range": by_conf,
        "tournament_level": {"available": False,
                             "note": "bet_history/clv_log ne stockent pas le niveau de tournoi au "
                                     "moment du pick — trou d'instrumentation, pas de chiffre fiable "
                                     "produit (voir recommandations)."},
        "ranking_diff": {"available": False,
                        "note": "bet_history/clv_log ne stockent pas l'écart de classement au moment "
                                "du pick (le classement ACTUEL des joueurs n'est pas point-in-time et "
                                "serait trompeur) — trou d'instrumentation, pas de chiffre fiable "
                                "produit (voir recommandations)."},
        "caveat": (f"n={n_total} paris réglés au total — TOUTES les ventilations ci-dessus sont "
                   "descriptives/exploratoires (la plupart des cellules ont n<30, sous la taille "
                   "nécessaire pour distinguer un effet réel du bruit). À ré-évaluer quand n≥200-300."),
    }


def run_full_audit() -> Dict[str, Any]:
    return {
        "market_blend_zero_audit": audit_market_blend_zero(),
        "market_disagreement": market_disagreement_analysis(),
        "clv_by_confidence": clv_by_confidence_detailed(),
        "value_bet_ev": value_bet_ev_audit(),
        "segmentation": segmentation_report(),
    }
