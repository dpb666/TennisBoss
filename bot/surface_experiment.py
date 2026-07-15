"""Walk-forward surface feature benchmark (offline, not wired to production).

Compares baseline predictor (features + ELO surface) vs baseline + learned
surface feature logit on archived matches. Writes reports/surface_benchmark.md.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bot import calibrate, config, db, elo as elo_mod, features, memory, predictor
from bot.learner import _train_one
from bot.log import log
from bot.surface_features import (
    MatchHistoryIndex,
    SURFACE_FEATURE_NAMES,
    fit_surface_weights,
    impute_diffs,
    surface_feature_diffs,
    surface_logit_from_diffs,
)

_EPS = 1e-9
_REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "surface_benchmark.md"


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _logit(p: float) -> float:
    p = max(_EPS, min(1 - _EPS, p))
    return math.log(p / (1 - p))


def _safe_log(p: float) -> float:
    return math.log(max(_EPS, min(1.0, p)))


def _logloss(probs: Sequence[float], labels: Sequence[int]) -> float:
    if not probs:
        return float("nan")
    total = 0.0
    for p, y in zip(probs, labels):
        p = max(_EPS, min(1 - _EPS, p))
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(probs)


def _brier(probs: Sequence[float], labels: Sequence[int]) -> float:
    if not probs:
        return float("nan")
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(probs)


def _ece(probs: Sequence[float], labels: Sequence[int], n_bins: int = 10) -> float:
    """Expected Calibration Error (mean |observed - predicted| per bin)."""
    if not probs:
        return float("nan")
    bins: List[List[Tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, y in zip(probs, labels):
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, y))
    err = 0.0
    total = 0
    for bucket in bins:
        if not bucket:
            continue
        mean_p = sum(p for p, _ in bucket) / len(bucket)
        mean_y = sum(y for _, y in bucket) / len(bucket)
        err += abs(mean_p - mean_y) * len(bucket)
        total += len(bucket)
    return err / total if total else float("nan")


def _calibration_bins(
    probs: Sequence[float],
    labels: Sequence[int],
    n_bins: int = 5,
) -> List[Dict[str, Any]]:
    bins: List[Dict[str, Any]] = []
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        bucket_p, bucket_y = [], []
        for p, y in zip(probs, labels):
            if lo <= p < hi or (i == n_bins - 1 and p == 1.0):
                bucket_p.append(p)
                bucket_y.append(y)
        n = len(bucket_p)
        bins.append({
            "bin": f"{lo:.0%}-{hi:.0%}",
            "n": n,
            "pred": round(sum(bucket_p) / n, 3) if n else None,
            "obs": round(sum(bucket_y) / n, 3) if n else None,
            "gap": round(abs(sum(bucket_p) / n - sum(bucket_y) / n), 3) if n else None,
        })
    return bins


def _roi_simulated(
    probs: Sequence[float],
    labels: Sequence[int],
    odds_p1: Sequence[Optional[float]],
    *,
    min_edge: float = 0.03,
) -> Optional[float]:
    """Flat-stake ROI when model prob exceeds implied prob by min_edge."""
    stakes = 0
    pnl = 0.0
    for p, y, odds in zip(probs, labels, odds_p1):
        if odds is None or odds <= 1.0:
            continue
        implied = 1.0 / odds
        if p - implied < min_edge:
            continue
        stakes += 1
        pnl += (odds - 1.0) if y == 1 else -1.0
    if stakes == 0:
        return None
    return round(pnl / stakes, 4)


def _orient_players(winner: str, loser: str) -> Tuple[str, str, int]:
    p1, p2 = (winner, loser) if winner <= loser else (loser, winner)
    y = 1 if winner == p1 else 0
    return p1, p2, y


def _baseline_prob(
    mem: Dict[str, Any],
    p1: str,
    p2: str,
    surface: str,
) -> float:
    f1 = features.feature_vector(features.get_profile(mem, p1))
    f2 = features.feature_vector(features.get_profile(mem, p2))
    s1 = predictor.weighted_score(mem["weights"], f1)
    s2 = predictor.weighted_score(mem["weights"], f2)
    z = (s1 - s2) + float(mem["bias"]) + predictor.elo_logit(mem, p1, p2, surface)
    return _sigmoid(z)


def _build_elo(matches: List[Dict]) -> Tuple[Dict, Dict, Dict, Dict]:
    ratings: Dict[str, float] = {}
    n_played: Dict[str, int] = {}
    surf_ratings: Dict[str, Dict[str, float]] = {s: {} for s in ("hard", "clay", "grass")}
    surf_n: Dict[str, Dict[str, int]] = {s: {} for s in ("hard", "clay", "grass")}
    for m in matches:
        mult = elo_mod.mult_from_margin(m.get("margin") or 0)
        elo_mod.update_dynamic(ratings, n_played, m["winner_name"], m["loser_name"], mult=mult)
        surf = (m.get("surface") or "").lower()
        if surf in surf_ratings:
            elo_mod.update_dynamic(
                surf_ratings[surf], surf_n[surf],
                m["winner_name"], m["loser_name"], mult=mult,
            )
    return ratings, surf_ratings, n_played, surf_n


def run_benchmark(
    matches: Optional[List[Dict[str, Any]]] = None,
    *,
    test_fraction: float = 0.25,
    min_test: int = 500,
    min_surface_matches: int = 100,
    write_report: bool = True,
) -> Dict[str, Any]:
    """Walk-forward benchmark: baseline vs baseline + surface features."""
    if matches is None:
        db.init()
        matches = db.matches_for_backtest()

    surf_matches = [
        m for m in matches
        if (m.get("surface") or "").lower() in ("hard", "clay", "grass")
    ]
    if len(surf_matches) < min_surface_matches:
        return {
            "fitted": False,
            "note": f"Pas assez de matchs avec surface (min {min_surface_matches}).",
            "n_total": len(surf_matches),
        }

    frac = test_fraction
    split = int(len(surf_matches) * (1 - frac))
    train, test = surf_matches[:split], surf_matches[split:]
    if len(test) < min_test:
        return {
            "fitted": False,
            "note": f"Pas assez de matchs test (min {min_test}, got {len(test)}).",
            "n_train": len(train),
            "n_test": len(test),
        }

    mem = memory.default_memory()
    lr, reg, alpha = (
        config.DEFAULT_CONFIG["learning_rate"],
        config.DEFAULT_CONFIG["l2_reg"],
        config.DEFAULT_CONFIG["ema_alpha"],
    )
    for m in train:
        _train_one(mem, m, lr, reg, alpha)

    elo_ratings, elo_surface, elo_n, elo_surf_n = _build_elo(train)
    mem["elo"] = elo_ratings
    mem["elo_surface"] = elo_surface

    history_train = MatchHistoryIndex(train)
    surf_train_rows: List[Tuple[Dict[str, Optional[float]], float]] = []
    for m in train:
        surf = (m.get("surface") or "").lower()
        p1, p2, y = _orient_players(m["winner_name"], m["loser_name"])
        diffs = surface_feature_diffs(
            p1, p2, surf, history_train, m["date"],
        )
        surf_train_rows.append((diffs, float(y)))

    surf_weights = fit_surface_weights(surf_train_rows, SURFACE_FEATURE_NAMES)

    history_all = MatchHistoryIndex(train)
    odds_index = db.historical_odds_index()

    base_probs: List[float] = []
    enh_probs: List[float] = []
    labels: List[int] = []
    odds_p1: List[Optional[float]] = []

    for m in test:
        surf = (m.get("surface") or "").lower()
        p1, p2, y = _orient_players(m["winner_name"], m["loser_name"])
        p_base = _baseline_prob(mem, p1, p2, surf)
        diffs = surface_feature_diffs(p1, p2, surf, history_all, m["date"])
        z_extra = surface_logit_from_diffs(diffs, surf_weights)
        p_enh = _sigmoid(_logit(p_base) + z_extra)

        base_probs.append(p_base)
        enh_probs.append(p_enh)
        labels.append(y)

        date_key = str(m.get("date") or "").replace("-", "")
        row = odds_index.get((date_key, m["winner_name"], m["loser_name"]))
        if row is None:
            row = odds_index.get((date_key, m["loser_name"], m["winner_name"]))
        if row and y == 1:
            odds_p1.append(row.get("avgw") or row.get("psw"))
        elif row:
            odds_p1.append(row.get("avgl") or row.get("psl"))
        else:
            odds_p1.append(None)

        tour = m.get("tour")
        features.update_profile(mem, m["winner_name"], m["winner"], True, alpha, tour)
        features.update_profile(mem, m["loser_name"], m["loser"], False, alpha, tour)
        mult = elo_mod.mult_from_margin(m.get("margin") or 0)
        elo_mod.update_dynamic(elo_ratings, elo_n, m["winner_name"], m["loser_name"], mult=mult)
        if surf in elo_surface:
            elo_mod.update_dynamic(
                elo_surface[surf], elo_surf_n[surf],
                m["winner_name"], m["loser_name"], mult=mult,
            )
        mem["elo"] = elo_ratings
        mem["elo_surface"] = elo_surface
        history_all.add_match(m)

    base_ll = _logloss(base_probs, labels)
    enh_ll = _logloss(enh_probs, labels)
    base_brier = _brier(base_probs, labels)
    enh_brier = _brier(enh_probs, labels)
    base_ece = _ece(base_probs, labels)
    enh_ece = _ece(enh_probs, labels)

    brier_rel_improve = (base_brier - enh_brier) / base_brier if base_brier else 0.0
    ll_rel_improve = (base_ll - enh_ll) / base_ll if base_ll else 0.0

    threshold = 0.01
    significant = brier_rel_improve >= threshold or ll_rel_improve >= threshold

    report: Dict[str, Any] = {
        "fitted": True,
        "span_train": f"{train[0]['date']}..{train[-1]['date']}",
        "span_test": f"{test[0]['date']}..{test[-1]['date']}",
        "n_train": len(train),
        "n_test": len(test),
        "surface_weights": surf_weights,
        "baseline": {
            "logloss": round(base_ll, 4),
            "brier": round(base_brier, 4),
            "ece": round(base_ece, 4),
            "roi_sim": _roi_simulated(base_probs, labels, odds_p1),
            "calibration_bins": _calibration_bins(base_probs, labels),
        },
        "enhanced": {
            "logloss": round(enh_ll, 4),
            "brier": round(enh_brier, 4),
            "ece": round(enh_ece, 4),
            "roi_sim": _roi_simulated(enh_probs, labels, odds_p1),
            "calibration_bins": _calibration_bins(enh_probs, labels),
        },
        "delta": {
            "logloss": round(enh_ll - base_ll, 4),
            "brier": round(enh_brier - base_brier, 4),
            "ece": round(enh_ece - base_ece, 4),
            "brier_rel_improve_pct": round(brier_rel_improve * 100, 2),
            "logloss_rel_improve_pct": round(ll_rel_improve * 100, 2),
        },
        "significant": significant,
        "production_recommendation": (
            "INTEGRATE — surface features improve calibration beyond 1% threshold."
            if significant else
            "REJECT — surface features do not meaningfully improve baseline metrics."
        ),
    }

    log(
        f"Surface benchmark: baseline brier={base_brier:.4f} "
        f"enhanced={enh_brier:.4f} ({report['delta']['brier_rel_improve_pct']:+.2f}%)"
    )

    if write_report:
        _write_markdown_report(report)
        report["report_path"] = str(_REPORT_PATH)

    return report


def _write_markdown_report(report: Dict[str, Any]) -> None:
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not report.get("fitted"):
        _REPORT_PATH.write_text(
            f"# Surface Benchmark\n\nNot enough data: {report.get('note', '')}\n",
            encoding="utf-8",
        )
        return

    b, e, d = report["baseline"], report["enhanced"], report["delta"]
    lines = [
        "# Surface Feature Benchmark",
        "",
        f"**Train:** {report['n_train']} matches ({report['span_train']})  ",
        f"**Test:** {report['n_test']} matches ({report['span_test']})  ",
        f"**Verdict:** {report['production_recommendation']}",
        "",
        "## Metrics comparison",
        "",
        "| Metric | Baseline | + Surface features | Delta |",
        "|--------|----------|-------------------|-------|",
        f"| Log loss | {b['logloss']} | {e['logloss']} | {d['logloss']:+.4f} |",
        f"| Brier | {b['brier']} | {e['brier']} | {d['brier']:+.4f} |",
        f"| ECE | {b['ece']} | {e['ece']} | {d['ece']:+.4f} |",
        f"| ROI sim | {b.get('roi_sim')} | {e.get('roi_sim')} | — |",
        "",
        f"**Relative Brier improvement:** {d['brier_rel_improve_pct']}%  ",
        f"**Relative log-loss improvement:** {d['logloss_rel_improve_pct']}%",
        "",
        "## Learned surface weights",
        "",
        "| Feature | Weight |",
        "|---------|--------|",
    ]
    for name, w in report.get("surface_weights", {}).items():
        lines.append(f"| {name} | {w} |")

    lines.extend(["", "## Baseline calibration bins", ""])
    lines.append("| Bin | n | Pred | Obs | Gap |")
    lines.append("|-----|---|------|-----|-----|")
    for row in b["calibration_bins"]:
        lines.append(
            f"| {row['bin']} | {row['n']} | {row['pred']} | {row['obs']} | {row['gap']} |"
        )

    lines.extend(["", "## Enhanced calibration bins", ""])
    lines.append("| Bin | n | Pred | Obs | Gap |")
    lines.append("|-----|---|------|-----|-----|")
    for row in e["calibration_bins"]:
        lines.append(
            f"| {row['bin']} | {row['n']} | {row['pred']} | {row['obs']} | {row['gap']} |"
        )

    _REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
