"""Compare moteur heuristique (predictor) vs ML offline — Phase 12.

Ne modifie PAS le prédicteur de production.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from . import db, memory, predictor, features

REPORT_DIR = "reports"
REPORT_FILE = "engine_comparison.md"


def _heuristic_prob(mem: Dict[str, Any], p1: str, p2: str) -> float:
    f1 = features.feature_vector(features.get_profile(mem, p1))
    f2 = features.feature_vector(features.get_profile(mem, p2))
    r = predictor.predict(mem, p1, f1, p2, f2)
    return predictor.set_to_match_prob(float(r["prob1"]) / 100.0)


def compare_engines() -> Dict[str, Any]:
    db.init()
    mem = memory.load()
    result: Dict[str, Any] = {
        "heuristic": {"available": True},
        "ml": {"available": False},
        "note": "Offline only — aucun changement production.",
    }

    try:
        from .ml_prep import build_dataset, train_offline
        from .ml_prep.evaluate import evaluate_holdout
    except ImportError as exc:
        result["ml"]["error"] = str(exc)
        result["verdict"] = "ml_prep indisponible."
        return result

    try:
        ds = build_dataset(min_matches=50)
    except ValueError as exc:
        result["verdict"] = str(exc)
        return result

    if ds.n_test < 20:
        result["verdict"] = f"Hold-out trop petit (n={ds.n_test})."
        result["dataset"] = ds.meta
        return result

    y_true: List[int] = []
    y_proba_heur: List[float] = []
    odds_implied: List[Optional[float]] = []
    for row in ds.test_rows:
        p1, p2 = row["player1"], row["player2"]
        y_true.append(int(row["y"]))
        try:
            y_proba_heur.append(_heuristic_prob(mem, p1, p2))
        except Exception:
            y_proba_heur.append(0.5)
        oi = row.get("odds_implied_p1")
        odds_implied.append(float(oi) if oi is not None else None)

    y_pred_heur = [1 if p >= 0.5 else 0 for p in y_proba_heur]
    heur_eval = evaluate_holdout(y_true, y_pred_heur, y_proba_heur, odds_implied)
    result["heuristic"]["metrics"] = heur_eval

    try:
        train_report = train_offline(dataset=ds)
    except ImportError as exc:
        result["ml"]["error"] = str(exc)
        result["verdict"] = "scikit-learn requis : pip install scikit-learn xgboost"
        result["dataset"] = ds.meta
        return result

    result["ml"]["available"] = True
    result["ml"]["train_report"] = {
        k: train_report[k] for k in ("best_by_auc", "n_train", "n_test", "models")
        if k in train_report
    }
    best = train_report.get("best_by_auc")
    if best and best in (train_report.get("models") or {}):
        result["ml"]["metrics"] = train_report["models"][best].get("metrics")
        result["ml"]["model"] = best

    result["dataset"] = ds.meta
    result["verdict"] = _pick_verdict(
        heur_eval, result["ml"].get("metrics") or {},
    )
    return result


def _pick_verdict(heur: Dict[str, Any], ml: Dict[str, Any]) -> str:
    if not ml:
        return "ML non entraîné — installer scikit-learn ou attendre plus de données."
    h_brier = heur.get("brier")
    m_brier = ml.get("brier")
    h_roi = (heur.get("roi_simulation") or {}).get("roi_pct")
    m_roi = (ml.get("roi_simulation") or {}).get("roi_pct")
    if h_brier is None or m_brier is None:
        return "Enrichir historical_odds et rankings avant comparaison fiable."
    if m_brier < h_brier - 0.01 and (m_roi or -999) >= (h_roi or -999):
        return "ML meilleur sur hold-out — validation offline seulement, ne pas déployer."
    if h_brier <= m_brier:
        return "Heuristique compétitive — garder predictor.py en production."
    return "Résultats mixtes — voir DATA_PIPELINE_AUDIT.md pour combler les gaps."


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Comparaison moteur heuristique vs ML (offline)",
        "",
        f"**Verdict** : {report.get('verdict')}",
        "",
        report.get("note", ""),
        "",
    ]
    for name in ("heuristic", "ml"):
        block = report.get(name) or {}
        lines.append(f"## {name.upper()}")
        metrics = block.get("metrics") or {}
        if not metrics:
            lines.append(f"- Indisponible : {block.get('error', '—')}")
        else:
            lines.append(f"- Accuracy : {metrics.get('accuracy')}")
            lines.append(f"- AUC : {metrics.get('auc')}")
            lines.append(f"- Brier : {metrics.get('brier')}")
            roi = metrics.get("roi_simulation") or {}
            lines.append(f"- ROI simulé : {roi.get('roi_pct')}% ({roi.get('n_bets')} paris)")
        if block.get("model"):
            lines.append(f"- Modèle retenu : {block['model']}")
        lines.append("")
    ds = report.get("dataset") or {}
    if ds:
        lines.append(
            f"Dataset : train={ds.get('n_train')} test={ds.get('n_test')} | "
            f"odds={ds.get('odds_coverage_pct')}% rank={ds.get('ranking_coverage_pct')}%"
        )
        gaps = ds.get("needs_from_agent4") or []
        if gaps:
            lines.append("")
            lines.append("Gaps données :")
            for g in gaps:
                lines.append(f"- {g}")
    lines.append("")
    return "\n".join(lines)


def generate(*, write_file: bool = True) -> tuple:
    report = compare_engines()
    path = None
    if write_file:
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = os.path.join(REPORT_DIR, REPORT_FILE)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(report))
        report["report_path"] = path
    return path, report
