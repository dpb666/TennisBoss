"""Analyseur hebdomadaire d'apprentissage — Phase 3 (docs/ARCHITECTURE_BLUEPRINT.md §6.5).

Synthétise des modules d'analyse DÉJÀ EXISTANTS (bot/calibration_report.py,
bot/track_record.py, bot/market_efficiency_audit.py) en un rapport unique de
SUGGESTIONS — jamais de changement automatique. Chaque finding porte son n ;
en dessous de MIN_N_SUGGESTION il est classé "insuffisant" (observation notée,
aucune conclusion tirée), jamais présenté comme une suggestion actionnable.

Garde-fou : ce module ne doit JAMAIS importer bot.predictor, bot.calibrate ou
bot.learner (frontière figée, ADR-005) — vérifié par
tests/test_learning_analyzer.py::test_no_frozen_imports.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any, Dict, List

from bot import calibration_report, db, market_efficiency_audit, track_record

MIN_N_SUGGESTION = 15
REPORT_DIR = os.path.join("reports", "learning")


def _calibration_findings(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """`report` : shape de calibration_report.build_calibration_report() —
    la liste de bins vit sous la clé `calibration_bins`, pas `bins`."""
    findings: List[Dict[str, Any]] = []
    for b in report.get("calibration_bins", []):
        n = b.get("n") or 0
        if n == 0:
            continue
        gap = b.get("gap")
        item: Dict[str, Any] = {
            "dimension": "calibration", "segment": b["bin"], "n": n,
            "observation": (
                f"prédit {b.get('predicted')}, observé {b.get('observed')} (écart {gap:+.3f})"
                if gap is not None else "n/a"
            ),
        }
        if n < MIN_N_SUGGESTION:
            item["status"] = "insuffisant"
        elif gap is not None and abs(gap) >= 0.08:
            item["status"] = "à investiguer"
            direction = "sur-confiant" if gap < 0 else "sous-confiant"
            item["suggestion"] = (
                f"Bin {b['bin']} : le modèle semble {direction} de {abs(gap) * 100:.1f} pts "
                f"(n={n}). Hypothèse à confirmer à plus grand n avant tout changement — "
                "ne modifie pas la calibration en production (ADR-005)."
            )
        else:
            item["status"] = "ok"
        findings.append(item)
    return findings


def _surface_findings(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for r in rows:
        n = r.get("n") or 0
        if n == 0 or r.get("label") == "unknown":
            continue
        item: Dict[str, Any] = {
            "dimension": "surface", "segment": r["label"], "n": n,
            "observation": (
                f"yield={r.get('yield_pct')}%, win_rate={r.get('win_rate')}, "
                f"CLV moy={r.get('avg_clv_pct')}%"
            ),
        }
        if n < MIN_N_SUGGESTION:
            item["status"] = "insuffisant"
        elif r.get("roi") is not None and r["roi"] < -0.15:
            item["status"] = "à investiguer"
            item["suggestion"] = (
                f"Surface {r['label']} : yield {r.get('yield_pct')}% sur n={n} — "
                "à surveiller, échantillon encore trop petit pour agir (cible n≥200 global)."
            )
        else:
            item["status"] = "ok"
        findings.append(item)
    return findings


def _tournament_findings(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for r in rows[:10]:
        n = r.get("n") or 0
        if n == 0:
            continue
        findings.append({
            "dimension": "tournoi", "segment": r["label"], "n": n,
            "observation": f"yield={r.get('yield_pct')}%, win_rate={r.get('win_rate')}",
            "status": "insuffisant" if n < MIN_N_SUGGESTION else "ok",
        })
    return findings


def _market_disagreement_findings(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for b in report.get("buckets", []):
        n = b.get("n") or 0
        if n == 0:
            continue
        item: Dict[str, Any] = {
            "dimension": "désaccord marché", "segment": b["disagreement_range"], "n": n,
            "observation": (
                f"Brier modèle={b.get('brier_model')} vs marché={b.get('brier_market')} "
                f"({'modèle meilleur' if b.get('model_better_brier') else 'marché meilleur'})"
            ),
        }
        if n < MIN_N_SUGGESTION:
            item["status"] = "insuffisant"
        elif b.get("model_better_brier"):
            item["status"] = "à investiguer"
            item["suggestion"] = (
                f"Désaccord Δ{b['disagreement_range']} : le modèle bat le marché (Brier) "
                f"sur n={n} — segment potentiellement intéressant, à confirmer à plus grand n."
            )
        else:
            item["status"] = "ok"
        findings.append(item)
    return findings


def generate_weekly_report(*, write_files: bool = True) -> Dict[str, Any]:
    """Point d'entrée. Agrège calibration/surface/tournoi/désaccord marché en
    un rapport de suggestions — aucun changement automatique, jamais.

    Analyse une fenêtre large (365j, toutes les données accumulées) plutôt
    que les 7 derniers jours seuls : à n=72 (juillet 2026), une semaine de
    picks est presque toujours trop courte pour dire quoi que ce soit — la
    CADENCE d'exécution reste hebdomadaire, la fenêtre d'analyse non.
    """
    db.init()

    calib = calibration_report.build_calibration_report(days=365)
    surfaces = track_record.surface_breakdown(days=365)
    tournaments = track_record.tournament_breakdown(days=365)
    try:
        disagreement = market_efficiency_audit.market_disagreement_analysis()
    except Exception:  # noqa: BLE001 — analyse optionnelle, jamais bloquante
        disagreement = {"buckets": [], "n_total": 0}

    findings: List[Dict[str, Any]] = []
    findings += _calibration_findings(calib)
    findings += _surface_findings(surfaces.get("surfaces", []))
    findings += _tournament_findings(tournaments.get("tournaments", []))
    findings += _market_disagreement_findings(disagreement)

    suggestions = [f for f in findings if f.get("status") == "à investiguer"]
    insufficient = [f for f in findings if f.get("status") == "insuffisant"]

    report: Dict[str, Any] = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "n_calibration": calib.get("n_settled") or 0,
        "n_surfaces_total": sum(r.get("n") or 0 for r in surfaces.get("surfaces", [])),
        "findings": findings,
        "suggestions": suggestions,
        "n_insufficient": len(insufficient),
        "footer": (
            "Suggestions générées automatiquement à partir des patterns observés — "
            "AUCUNE n'a été appliquée. Toute modification du prédicteur/calibration/"
            "seuils reste gelée (ADR-005) et nécessite une décision humaine + une ADR dédiée."
        ),
    }

    if write_files:
        os.makedirs(REPORT_DIR, exist_ok=True)
        stamp = _dt.date.today().isoformat()
        md_path = os.path.join(REPORT_DIR, f"{stamp}.md")
        json_path = os.path.join(REPORT_DIR, f"{stamp}.json")
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(report))
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False, default=str)
        report["report_path"] = md_path

    return report


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        f"# Rapport d'apprentissage hebdomadaire — {report['generated_at'][:10]}",
        "",
        f"**{report['footer']}**",
        "",
        f"## Suggestions ({len(report['suggestions'])})",
        "",
    ]
    if not report["suggestions"]:
        lines.append(
            "Aucune suggestion actionnable cette semaine (rien de notable, ou "
            "échantillon insuffisant partout — voir la section ci-dessous).")
    for s in report["suggestions"]:
        lines.append(f"- **[{s['dimension']}] {s['segment']}** (n={s['n']}) : {s['suggestion']}")
    lines.append("")
    lines.append(f"## Observations à échantillon insuffisant ({report['n_insufficient']})")
    lines.append("")
    for f in report["findings"]:
        if f.get("status") == "insuffisant":
            lines.append(f"- [{f['dimension']}] {f['segment']} (n={f['n']}) : {f['observation']}")
    lines.append("")
    return "\n".join(lines)
