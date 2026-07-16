"""Validation walk-forward de deux politiques de décision candidates —
AUCUNE des deux n'est déployée, ce module ne fait que mesurer (lecture
seule, zéro écriture DB, zéro modification de predictor.predict()/api.py).

Hypothèse A : relever le seuil d'EV minimum réduit les pertes long terme.
Testée sur le jeu de données RÉEL (bet_history × clv_log, n=97) — c'est le
seul jeu qui contient une vraie variation d'EV positive (le edge de
production vient du line-shopping entre bookmakers, pas d'un signal modèle ;
voir docs/MARKET_EFFICIENCY_AUDIT.md §1). Le seuil est appliqué de façon
purement rétrospective sur des décisions déjà prises — pas de fuite (l'EV
était déjà connue au moment du pick), mais le petit n limite fortement la
puissance statistique aux seuils élevés.

Hypothèse B : amortir la confiance du modèle quand il diverge fortement du
marché améliore la calibration. Testée sur le jeu de données proxy plus
large (settled_matches × bet_log, n≈687, même source que
market_efficiency_audit) à plusieurs poids modèle de base — nécessaire car
la production tourne aujourd'hui à market_blend_w=0.00 (aucun poids modèle
à amortir), donc le test porte sur "si on donnait un jour du poids au
modèle, l'amortissement le rendrait-il plus sûr qu'un poids fixe ?".
Réutilise les mêmes outils statistiques que
signal_backtest.backtest_clutch_blend_walkforward (courbe walk-forward,
z-test apparié, IC bootstrap, ECE) — pas de réimplémentation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import calibrate, db
from .market_efficiency_audit import _logloss_pt
from .signal_backtest import _bootstrap_ci, _brier, _ece, _logloss, _paired_ztest

_EPS = 1e-6


# ── Hypothèse A : seuil d'EV minimum ────────────────────────────────────────

def backtest_ev_threshold(thresholds: Optional[List[float]] = None,
                          n_folds: int = 2) -> Dict[str, Any]:
    """Walk-forward (découpage chronologique en `n_folds` blocs) sur les
    paris RÉELLEMENT décidés par la production (bet_history × clv_log) :
    si on avait exigé un EV minimum plus élevé, le ROI/win-rate se
    seraient-ils améliorés de façon consistante entre les blocs et
    statistiquement significative (IC bootstrap 95% sur le P&L moyen) ?

    Le seuil 0% correspond au baseline actuel de facto (tous les paris
    settled proviennent déjà d'un filtre de production ≥ un plancher EV) —
    ce n'est PAS "sans aucun filtre EV", juste le seuil actuel comme
    référence pour juger si MONTER encore le seuil aide.
    """
    thresholds = thresholds if thresholds is not None else [0.0, 0.02, 0.05, 0.075, 0.10, 0.125]
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT bh.date, bh.odds, bh.result, bh.profit_loss, cl.pick_prob "
            "FROM bet_history bh LEFT JOIN clv_log cl "
            "ON cl.player1=bh.player1 AND cl.player2=bh.player2 "
            "WHERE bh.result IS NOT NULL AND cl.pick_prob IS NOT NULL AND bh.odds IS NOT NULL"
        ).fetchall()]
    for r in rows:
        r["ev"] = r["pick_prob"] * r["odds"] - 1.0
    rows.sort(key=lambda r: (r["date"] or ""))
    n_total = len(rows)
    if n_total < 20:
        return {"n_total": n_total, "note": "Échantillon insuffisant (min 20) pour un walk-forward par seuil."}

    fold_size = max(1, n_total // n_folds)

    def fold_of(i: int) -> int:
        return min(i // fold_size, n_folds - 1)

    for i, r in enumerate(rows):
        r["_fold"] = fold_of(i)

    variants: Dict[str, Any] = {}
    baseline_roi = None
    for th in thresholds:
        sub = [r for r in rows if r["ev"] >= th]
        n = len(sub)
        key = f"{th:.3f}"
        if n == 0:
            variants[key] = {"threshold": th, "n": 0}
            continue

        by_fold = []
        for f in range(n_folds):
            fold_sub = [r for r in sub if r["_fold"] == f]
            nf = len(fold_sub)
            if nf == 0:
                by_fold.append({"n": 0})
                continue
            by_fold.append({
                "n": nf,
                "roi_flat": round(sum(r["profit_loss"] for r in fold_sub) / nf, 3),
                "win_rate": round(sum(r["result"] for r in fold_sub) / nf, 3),
            })

        roi_all = round(sum(r["profit_loss"] for r in sub) / n, 3)
        wr_all = round(sum(r["result"] for r in sub) / n, 3)
        pnl_values = [r["profit_loss"] for r in sub]
        ci_lo, ci_hi = _bootstrap_ci(pnl_values)
        pts = [(min(1 - _EPS, max(_EPS, r["pick_prob"])), float(r["result"])) for r in sub]
        ll = round(_logloss(pts), 4)
        br = round(_brier(pts), 4)

        filled_folds = [b for b in by_fold if b.get("n")]
        consistent_positive = bool(filled_folds) and all(b["roi_flat"] > 0 for b in filled_folds)
        significant_positive = ci_lo is not None and ci_lo > 0

        if th == 0.0:
            baseline_roi = roi_all

        variants[key] = {
            "threshold": th, "n": n, "coverage_pct": round(n / n_total * 100, 1),
            "win_rate": wr_all, "roi_flat": roi_all,
            "roi_bootstrap_ci95": [ci_lo, ci_hi],
            "logloss_of_pick_prob": ll, "brier_of_pick_prob": br,
            "by_fold": by_fold,
            "consistent_positive_roi_across_folds": consistent_positive,
            "statistically_significant_positive_roi": significant_positive,
        }

    filled = {k: v for k, v in variants.items() if v.get("n")}
    improving = [k for k, v in filled.items()
                if v["threshold"] > 0 and baseline_roi is not None
                and v["roi_flat"] > baseline_roi
                and v["consistent_positive_roi_across_folds"]
                and v["statistically_significant_positive_roi"]]

    recommendation = "GO" if improving else "NO-GO"
    return {
        "n_total": n_total,
        "n_folds": n_folds,
        "baseline_roi_threshold_0": baseline_roi,
        "variants": variants,
        "recommendation": recommendation,
        "verdict": (
            f"Seuils qui améliorent le ROI de façon consistante (tous les folds positifs) ET "
            f"statistiquement significative (IC bootstrap 95% > 0) : {improving or 'AUCUN'}. "
            + ("Aucun seuil testé ne satisfait les deux critères sur cet échantillon "
               f"(n={n_total}) — la plupart des seuils élevés laissent trop peu de paris "
               "(n<15) pour qu'un IC bootstrap exclue le hasard. REJET : ne pas relever le "
               "seuil de production sur cette base, accumuler plus de données d'abord."
               if not improving else
               "Preuve suffisante pour ces seuils — voir détail par variante.")
        ),
    }


# ── Hypothèse B : amortissement de confiance selon le désaccord marché ─────

def _load_model_market_samples_with_date(calib_k: float) -> List[Dict[str, Any]]:
    """Même appariement que settlement.market_blend_samples() (jointure
    settled_matches × bet_log), MAIS avec la date conservée pour permettre
    un découpage chronologique — settlement.py n'est pas modifié (code de
    production), cette fonction en duplique volontairement la logique de
    pairage minimale plutôt que d'y toucher."""
    bets = {frozenset((b["player1"], b["player2"])): b for b in db.list_bets()}
    out = []
    for r in db.list_settled(limit=100000):
        if r["correct"] is None or r["pred_prob1"] is None:
            continue
        b = bets.get(frozenset((r["player1"], r["player2"])))
        if not b or not b["fav_odds"] or b["fav_odds"] <= 1.0:
            continue
        p1 = r["pred_prob1"] / 100.0
        p_model = p1 if b["favorite"] == r["player1"] else 1.0 - p1
        p_model = calibrate.calibrated_prob(p_model, calib_k)
        p_market = min(0.99, 1.0 / float(b["fav_odds"]))
        y = 1.0 if r["winner"] == b["favorite"] else 0.0
        date = r["date"] or b["date"] or ""
        out.append({"date": date, "p_model": p_model, "p_market": p_market, "y": y})
    out.sort(key=lambda d: (d["date"] or "").replace("-", ""))
    return out


def _dampened_weight(w_base: float, delta: float, strategy: str) -> float:
    if strategy == "flat":
        return w_base
    if strategy == "linear_decay":
        cap = 0.30  # au-delà d'un désaccord de 30pt, poids modèle -> 0
        return w_base * max(0.0, 1.0 - delta / cap)
    if strategy == "hard_cutoff":
        thresh = 0.20  # même seuil que le bucket "fort désaccord" de l'audit d'efficience
        return w_base if delta < thresh else 0.0
    raise ValueError(f"stratégie inconnue: {strategy}")


def backtest_disagreement_dampening(
    w_bases: Tuple[float, ...] = (0.05, 0.10, 0.15, 0.20),
    strategies: Tuple[str, ...] = ("flat", "linear_decay", "hard_cutoff"),
    n_folds: int = 4,
    calib_k: Optional[float] = None,
) -> Dict[str, Any]:
    """Pour chaque poids modèle de base candidat (0.05-0.20, la même grille
    que le blend clutch rejeté et le market_blend_w testé), compare 3
    stratégies : `flat` (poids constant, la façon actuelle dont un poids
    serait appliqué), `linear_decay` (le poids décroît linéairement avec le
    désaccord jusqu'à 0 à Δ=30pt) et `hard_cutoff` (poids nul dès que
    Δ≥20pt, le seuil où market_efficiency_audit a mesuré le pire Brier du
    modèle).

    Walk-forward : n_folds blocs CHRONOLOGIQUES (pas de shuffle). Pas
    d'accumulateur à réchauffer ici (p_modèle et p_marché sont déjà fixés
    par ligne, aucun état à reconstruire) — le découpage sert uniquement à
    vérifier la CONSISTANCE temporelle de l'effet, pas à éviter une fuite.

    Deux comparaisons appariées par variante : vs le marché pur (w=0,
    référence de production actuelle) et vs le même poids de base SANS
    amortissement (`flat`) — pour isoler l'effet spécifique de
    l'amortissement du simple effet du niveau de poids.
    """
    if calib_k is None:
        try:
            calib_k = float(db.get_meta("match_calib_k") or 1.0)
        except Exception:
            calib_k = 1.0

    samples = _load_model_market_samples_with_date(calib_k)
    n = len(samples)
    if n < 200:
        return {"n": n, "note": "Échantillon insuffisant (min 200) pour un walk-forward multi-blocs fiable."}

    fold_size = max(1, n // n_folds)

    def fold_of(i: int) -> int:
        return min(i // fold_size, n_folds - 1)

    market_by_fold: List[List[Tuple[float, float]]] = [[] for _ in range(n_folds)]
    for i, s in enumerate(samples):
        market_by_fold[fold_of(i)].append((s["p_market"], s["y"]))
    market_all = [pt for f in market_by_fold for pt in f]
    market_ll_by_fold = [round(_logloss(f), 4) for f in market_by_fold]
    market_ece, _ = _ece(market_all)

    result: Dict[str, Any] = {
        "n": n, "n_folds": n_folds, "calib_k": calib_k,
        "market_baseline": {
            "logloss": round(_logloss(market_all), 4),
            "logloss_by_fold": market_ll_by_fold,
            "brier": round(_brier(market_all), 4),
            "ece": market_ece,
        },
        "variants": {},
    }

    flat_cache: Dict[float, Tuple[List[List[Tuple[float, float]]], List[float]]] = {}

    for w_base in w_bases:
        for strat in strategies:
            rows_by_fold: List[List[Tuple[float, float]]] = [[] for _ in range(n_folds)]
            for i, s in enumerate(samples):
                delta = abs(s["p_model"] - s["p_market"])
                w_eff = _dampened_weight(w_base, delta, strat)
                p_blend = calibrate.blend_probs(s["p_model"], s["p_market"], w_eff)
                rows_by_fold[fold_of(i)].append((p_blend, s["y"]))
            all_rows = [pt for f in rows_by_fold for pt in f]
            ll_by_fold = [round(_logloss(f), 4) for f in rows_by_fold]
            ece_val, curve = _ece(all_rows)

            if strat == "flat":
                flat_cache[w_base] = (rows_by_fold, ll_by_fold)

            diffs_vs_market = []
            for f in range(n_folds):
                for (pb, yb), (pv, yv) in zip(market_by_fold[f], rows_by_fold[f]):
                    diffs_vs_market.append(_logloss_pt(pb, yb) - _logloss_pt(pv, yv))
            z_m, p_m = _paired_ztest(diffs_vs_market)
            ci_m_lo, ci_m_hi = _bootstrap_ci(diffs_vs_market)
            consistent_vs_market = all(market_ll_by_fold[f] - ll_by_fold[f] > 0 for f in range(n_folds))
            significant_vs_market = p_m is not None and p_m < 0.05 and ci_m_lo is not None and ci_m_lo > 0

            entry: Dict[str, Any] = {
                "w_base": w_base, "strategy": strat,
                "logloss": round(_logloss(all_rows), 4), "logloss_by_fold": ll_by_fold,
                "brier": round(_brier(all_rows), 4), "ece": ece_val,
                "vs_market": {
                    "mean_delta_logloss": round(sum(diffs_vs_market) / len(diffs_vs_market), 5) if diffs_vs_market else None,
                    "z": z_m, "p": p_m, "bootstrap_ci95": [ci_m_lo, ci_m_hi],
                    "consistent_across_folds": consistent_vs_market,
                    "statistically_significant": significant_vs_market,
                },
            }

            if strat != "flat" and w_base in flat_cache:
                flat_rows_by_fold, flat_ll_by_fold = flat_cache[w_base]
                diffs_vs_flat = []
                for f in range(n_folds):
                    for (pf, yf), (pv, yv) in zip(flat_rows_by_fold[f], rows_by_fold[f]):
                        diffs_vs_flat.append(_logloss_pt(pf, yf) - _logloss_pt(pv, yv))
                z_f, p_f = _paired_ztest(diffs_vs_flat)
                ci_f_lo, ci_f_hi = _bootstrap_ci(diffs_vs_flat)
                consistent_vs_flat = all(flat_ll_by_fold[f] - ll_by_fold[f] > 0 for f in range(n_folds))
                significant_vs_flat = p_f is not None and p_f < 0.05 and ci_f_lo is not None and ci_f_lo > 0
                entry["vs_flat_same_weight"] = {
                    "mean_delta_logloss": round(sum(diffs_vs_flat) / len(diffs_vs_flat), 5) if diffs_vs_flat else None,
                    "z": z_f, "p": p_f, "bootstrap_ci95": [ci_f_lo, ci_f_hi],
                    "consistent_across_folds": consistent_vs_flat,
                    "statistically_significant": significant_vs_flat,
                }

            result["variants"][f"w{w_base:.2f}_{strat}"] = entry

    winners = [k for k, v in result["variants"].items()
              if v["strategy"] != "flat"
              and v.get("vs_flat_same_weight", {}).get("statistically_significant")
              and v.get("vs_flat_same_weight", {}).get("consistent_across_folds")]

    recommendation = "GO_EXPERIMENTAL" if winners else "NO-GO"
    result["recommendation"] = recommendation
    result["verdict"] = (
        f"Stratégies d'amortissement qui battent le poids FIXE de même niveau, de façon "
        f"consistante et significative : {winners or 'AUCUNE'}. "
        + ("Aucune ne satisfait les deux critères — l'amortissement n'apporte pas de gain "
           "démontrable au-delà d'un simple choix de poids plus faible. REJET de l'hypothèse "
           "B telle que formulée : mieux vaut, SI un poids modèle non nul était un jour "
           "envisagé, choisir directement un poids bas plutôt que d'ajouter une logique "
           "d'amortissement plus complexe. À noter : la production tourne aujourd'hui à "
           "market_blend_w=0.00, donc cette question est pour l'instant contre-factuelle."
           if not winners else
           "Au moins une stratégie d'amortissement montre un gain robuste — voir détail.")
    )
    return result


def run_full_validation() -> Dict[str, Any]:
    return {
        "hypothesis_a_ev_threshold": backtest_ev_threshold(),
        "hypothesis_b_disagreement_dampening": backtest_disagreement_dampening(),
    }
