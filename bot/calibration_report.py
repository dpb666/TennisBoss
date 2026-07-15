"""Rapport de calibration modèle — Phase 12 consolidation.

Mesure si les probabilités annoncées correspondent aux résultats réels
(reliability diagram, Brier score, bins 50-55% … 75%+).

Sources : bet_history, clv_log, table predictions.
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Dict, List, Optional

from . import db

REPORT_DIR = "reports"
REPORT_FILE = "calibration_report.md"

# Bins de probabilité modèle (match winner).
CALIBRATION_BINS = [
    (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70),
    (0.70, 0.75), (0.75, 1.01),
]


def _brier_score(rows: List[Any]) -> Optional[float]:
    scored = [r for r in rows if r["prediction"] is not None and r["result"] in (0, 1)]
    if not scored:
        return None
    return sum(
        (float(r["prediction"]) - int(r["result"])) ** 2 for r in scored
    ) / len(scored)


def _calibration_bins(rows: List[Any]) -> List[Dict[str, Any]]:
    """Bins predicted vs observed win rate (sur le pick_side)."""
    out: List[Dict[str, Any]] = []
    for lo, hi in CALIBRATION_BINS:
        pool = [
            r for r in rows
            if r["prediction"] is not None and r["result"] in (0, 1)
            and lo <= float(r["prediction"]) < hi
        ]
        if not pool:
            out.append({
                "bin": f"{int(lo*100)}-{int(min(hi, 1)*100)}%",
                "n": 0, "predicted": None, "observed": None, "gap": None,
            })
            continue
        pred_mean = sum(float(r["prediction"]) for r in pool) / len(pool)
        # result=1 si le pick_side a gagné (déjà encodé dans bet_history)
        obs = sum(int(r["result"]) for r in pool) / len(pool)
        out.append({
            "bin": f"{int(lo*100)}-{int(min(hi, 1)*100)}%",
            "n": len(pool),
            "predicted": round(pred_mean, 3),
            "observed": round(obs, 3),
            "gap": round(obs - pred_mean, 3),
        })
    return out


def build_calibration_report(days: int = 90) -> Dict[str, Any]:
    """Agrège calibration depuis bet_history (+ fallback clv_log si vide)."""
    db.init()
    days = max(1, min(365, int(days)))
    rows = list(db.list_bet_history(limit=100000, days=days))

    if not rows:
        with db.connect() as c:
            since = (_dt.date.today() - _dt.timedelta(days=days - 1)).isoformat()
            clv_rows = c.execute(
                "SELECT pick_prob AS prediction, result, pick_side, player1, player2, "
                "date, confidence, clv_pct "
                "FROM clv_log WHERE result IS NOT NULL AND pick_ts >= ?",
                (since,),
            ).fetchall()
        source = "clv_log"
        pool = list(clv_rows)
    else:
        source = "bet_history"
        pool = [r for r in rows if r["result"] in (0, 1)]

    n = len(pool)
    brier = _brier_score(pool)
    bins = _calibration_bins(pool)
    stats = db.bet_history_stats(days=days) if source == "bet_history" else {}

    return {
        "days": days,
        "source": source,
        "n_settled": n,
        "brier_score": round(brier, 4) if brier is not None else None,
        "calibration_bins": bins,
        "bet_history_stats": stats,
        "verdict": _verdict(bins, n, brier),
    }


def _verdict(bins: List[Dict[str, Any]], n: int, brier: Optional[float]) -> str:
    if n < 30:
        return "Échantillon insuffisant (<30 paris) — continuer à enregistrer via bet_history."
    active = [b for b in bins if b.get("n", 0) >= 5]
    if not active:
        return "Pas assez de paris par bin pour conclure."
    max_gap = max(abs(b["gap"]) for b in active if b["gap"] is not None)
    if max_gap <= 0.08:
        return "Calibration acceptable (écart max bin ≤ 8 pts)."
    if max_gap <= 0.15:
        return "Calibration modérée — surveiller les bins extrêmes (>70%)."
    return "Calibration faible — ajuster calib_k / Platt avant de promouvoir le modèle."


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Rapport de calibration TennisBoss",
        "",
        f"Période : **{report['days']} jours** | Source : `{report['source']}` | "
        f"Paris réglés : **{report['n_settled']}**",
        "",
        f"**Brier score** : {report.get('brier_score')} (plus bas = mieux, 0.25 = coin flip)",
        "",
        f"**Verdict** : {report.get('verdict')}",
        "",
        "## Reliability diagram (bins probabilité modèle)",
        "",
        "| Bin | n | Prédit | Observé | Écart |",
        "|-----|---|--------|---------|-------|",
    ]
    for b in report.get("calibration_bins") or []:
        pred = b.get("predicted")
        obs = b.get("observed")
        gap = b.get("gap")
        lines.append(
            f"| {b['bin']} | {b['n']} | "
            f"{pred if pred is not None else '—'} | "
            f"{obs if obs is not None else '—'} | "
            f"{gap if gap is not None else '—'} |"
        )
    bh = report.get("bet_history_stats") or {}
    if bh.get("n"):
        lines.extend([
            "",
            "## Performance agrégée (bet_history)",
            "",
            f"- ROI : {bh.get('roi')}",
            f"- Yield : {bh.get('yield_pct')}%",
            f"- Win rate : {bh.get('win_rate')}",
            f"- CLV moyen : {bh.get('avg_clv_pct')}%",
        ])
    lines.append("")
    return "\n".join(lines)


def generate(days: int = 90, *, write_file: bool = True) -> tuple:
    """Construit le rapport et écrit reports/calibration_report.md."""
    report = build_calibration_report(days=days)
    path = None
    if write_file:
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = os.path.join(REPORT_DIR, REPORT_FILE)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(report))
        report["report_path"] = path
    return path, report
