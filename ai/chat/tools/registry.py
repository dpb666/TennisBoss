"""Outils de lecture seule pour l'assistant IA TennisBoss (Phase 1, Slice 1).

Voir docs/AI_ASSISTANT_ARCHITECTURE.md §3.4. Chaque outil est un simple
wrapper autour de fonctions bot/ DÉJÀ EXISTANTES (db, openapi_spec) — aucune
réimplémentation de logique métier, aucun accès en écriture.

Garde-fou : ce module ne doit JAMAIS importer bot.predictor, bot.calibrate
ou bot.learner (frontière figée, voir docs/AI_ASSISTANT_ARCHITECTURE.md §2)
— vérifié par tests/test_ai_tools.py::test_no_frozen_imports (lecture du
code source, pas seulement des imports actifs).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from bot import db, openapi_spec


@dataclass
class ToolResult:
    name: str
    data: Dict[str, Any]
    summary: str          # texte court, injectable directement dans le prompt
    source: str           # provenance (table/fichier/endpoint) pour l'attribution


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# Allowlist stricte : uniquement des documents connus à l'avance. L'orchestrateur
# choisit la clé via une classification par mots-clés sur le message — jamais un
# chemin arbitraire fourni par l'utilisateur final (défense en profondeur contre
# la traversée de répertoire, même si aucun appelant actuel ne le permettrait).
ALLOWED_DOCS: Dict[str, str] = {
    "ai_architecture": "docs/AI_ASSISTANT_ARCHITECTURE.md",
    "logging_schema": "docs/LOGGING_SCHEMA.md",
    "market_efficiency": "docs/MARKET_EFFICIENCY_AUDIT.md",
    "evidence_driven_optimization": "docs/EVIDENCE_DRIVEN_OPTIMIZATION.md",
    "clutch_backtest": "docs/CLUTCH_BLEND_WALKFORWARD_VALIDATION.md",
    "lead_engineer_audit": "docs/LEAD_ENGINEER_AUDIT.md",
    "surface_features": "docs/surface_features.md",
    "project_status": "PROJECT_STATUS.md",
    "master_todo": "MASTER_TODO.md",
    "agents": "AGENTS.md",
}

_DOC_EXCERPT_CHARS = 1500


def read_doc(key: str) -> ToolResult:
    """Lit un document connu (voir ALLOWED_DOCS) — jamais un chemin arbitraire."""
    rel_path = ALLOWED_DOCS.get(key)
    if not rel_path:
        return ToolResult("read_doc", {"error": f"document inconnu : {key}"}, "", key)
    abs_path = os.path.join(_REPO_ROOT, rel_path)
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return ToolResult("read_doc", {"error": str(exc)}, "", rel_path)
    excerpt = text[:_DOC_EXCERPT_CHARS]
    return ToolResult("read_doc", {"path": rel_path, "length": len(text)}, excerpt, rel_path)


def query_bet_history(days: int = 30) -> ToolResult:
    """Wrapper de db.bet_history_stats() — aucune requête SQL nouvelle."""
    stats = db.bet_history_stats(days=days)
    n = stats.get("n", 0) or 0
    sparse = " (échantillon limité, n<200 — conclusions indicatives)" if n < 200 else ""
    summary = (
        f"bet_history ({days}j) : n={n}, win_rate={stats.get('win_rate')}, "
        f"ROI={stats.get('roi')}, yield%={stats.get('yield_pct')}{sparse}"
    )
    return ToolResult("query_bet_history", stats, summary, "bet_history")


def get_calibration_summary(days: int = 90) -> ToolResult:
    """Wrapper de db.bet_history_calibration() — aucune requête SQL nouvelle."""
    calib = db.bet_history_calibration(days=days)
    bins = calib.get("calibration_bins") or []
    n_total = sum(int(b.get("n", 0) or 0) for b in bins)
    sparse = " (échantillon limité, n<200)" if n_total < 200 else ""
    summary = f"Calibration ({days}j) : {len(bins)} bin(s), n total={n_total}{sparse}"
    return ToolResult("get_calibration_summary", calib, summary, "bet_history_calibration")


def explain_pick(player1: str, player2: str) -> ToolResult:
    """Explique le dernier pick connu pour cette paire via les champs de
    reproductibilité clv_log (voir docs/LOGGING_SCHEMA.md)."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM clv_log WHERE (player1=? AND player2=?) OR (player1=? AND player2=?) "
            "ORDER BY pick_ts DESC LIMIT 1",
            (player1, player2, player2, player1),
        ).fetchone()
    if not row:
        return ToolResult("explain_pick", {}, f"Aucun pick trouvé pour {player1} vs {player2}.", "clv_log")
    d = dict(row)
    missing = db.validate_clv_pick_row(row)
    summary = (
        f"{d.get('pick_side')} @ {d.get('pick_odds')} — proba modèle "
        f"{d.get('model_prob_calibrated')}, marché {d.get('market_prob')}, "
        f"EV {d.get('ev_pct')}%, confiance {d.get('confidence')}, "
        f"tournoi {d.get('tournament') or '?'} ({d.get('surface') or '?'})."
    )
    if missing:
        summary += f" [Champs de reproductibilité manquants : {', '.join(missing)}]"
    return ToolResult("explain_pick", d, summary, "clv_log")


def list_api_endpoints(tag: Optional[str] = None) -> ToolResult:
    """Wrapper d'openapi_spec.build_spec() — aucune duplication de la spec."""
    spec = openapi_spec.build_spec()
    out: List[Dict[str, Any]] = []
    for path, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            tags = op.get("tags") or []
            if tag and tag not in tags:
                continue
            out.append({"path": path, "method": method.upper(),
                       "summary": op.get("summary", ""), "tags": tags})
    label = f" tag={tag}" if tag else ""
    preview = "; ".join(f"{e['method']} {e['path']}" for e in out[:8])
    summary = f"{len(out)} endpoint(s){label} : {preview}"
    return ToolResult("list_api_endpoints", {"endpoints": out}, summary, "openapi_spec")


def get_logging_health(bucket: str = "week") -> ToolResult:
    """Wrapper de db.clv_logging_completeness_report() — voir LOGGING_SCHEMA.md."""
    report = db.clv_logging_completeness_report(bucket=bucket)
    summary = (f"Complétude du logging : {report.get('completeness_pct_overall')}% "
               f"sur {report.get('n_total')} picks ({bucket}).")
    return ToolResult("get_logging_health", report, summary, "clv_logging_completeness_report")


def get_learning_report() -> ToolResult:
    """Dernier rapport Phase 3 (ai/learning/analyzer.py) — suggestions
    d'apprentissage, jamais de changement automatique. Génère à la volée si
    aucun rapport n'a encore été écrit cette semaine (idempotent, lecture seule)."""
    from ai.learning import analyzer
    report = analyzer.generate_weekly_report(write_files=False)
    n_sugg = len(report.get("suggestions", []))
    if n_sugg:
        preview = "; ".join(
            f"[{s['dimension']}] {s['segment']} (n={s['n']})" for s in report["suggestions"][:5]
        )
        summary = f"{n_sugg} suggestion(s) Phase 3 : {preview}"
    else:
        summary = (f"Aucune suggestion actionnable actuellement "
                   f"({report.get('n_insufficient', 0)} observation(s) à échantillon insuffisant).")
    return ToolResult("get_learning_report", report, summary, "ai/learning/analyzer")


# Registre nommé — utilisé par l'orchestrateur et par les tests pour vérifier
# qu'aucun outil "à risque" (write) n'est jamais enregistré ici.
ALL_TOOLS = {
    "read_doc": read_doc,
    "query_bet_history": query_bet_history,
    "get_calibration_summary": get_calibration_summary,
    "explain_pick": explain_pick,
    "list_api_endpoints": list_api_endpoints,
    "get_logging_health": get_logging_health,
    "get_learning_report": get_learning_report,
}
