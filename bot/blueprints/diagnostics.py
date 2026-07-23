"""Diagnostics blueprint — intelligence/learner/scanner/monitor introspection
(read-only except /api/intelligence/cycle, which is admin-gated by path via
api.py's before_request hook — unaffected by which blueprint owns the route).
"""
from __future__ import annotations

import json

from flask import Blueprint, jsonify

from .. import db, intelligence, mistake_learner

bp = Blueprint("diagnostics", __name__)


@bp.get("/api/intelligence/stats")
def api_intelligence_stats():
    """Auto-diagnostic: drift, surfaces en danger, blacklist joueurs."""
    return jsonify({**intelligence.stats(), "ok": True})


@bp.post("/api/intelligence/cycle")
def api_intelligence_cycle():
    """Force un cycle d'intelligence immédiat (sans attendre les 6h)."""
    result = intelligence.run_cycle(send_telegram=False)
    return jsonify({**result, "ok": True})


@bp.get("/api/learner/stats")
def api_learner_stats():
    """Zones dangereuses apprises automatiquement depuis les résultats réels.

    Retourne les segments (EV bucket × cote × surface) où le ROI est
    systématiquement négatif et que le scanner bloque automatiquement.
    """
    return jsonify({**mistake_learner.stats(), "ok": True})


@bp.get("/api/scanner/status")
def api_scanner_status():
    """État temps réel du scanner : cycle, rejets, near-misses, picks actifs."""
    from ..workers.value_scanner import get_status
    return jsonify({**get_status(), "ok": True})


@bp.get("/api/monitor/status")
def api_monitor_status():
    """Dernier résultat du health check système (bot/monitor.py::SystemMonitor).

    Calculé toutes les 5 min par le job "worker" (bot/scheduler.py::job_monitor,
    conteneur séparé en déploiement Docker — voir docker-compose.yml), persisté
    via db.set_meta("last_monitor_check"). Jusqu'ici jamais exposé : ce check
    tournait déjà, mais son résultat n'était visible que dans les logs.
    """
    raw = db.get_meta("last_monitor_check")
    if not raw:
        return jsonify({"available": False,
                        "note": "Aucun check monitor n'a encore tourné (worker pas démarré ?)."})
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return jsonify({"available": False, "note": "Dernier check illisible."})
    try:
        endpoint_timings = json.loads(db.get_meta("endpoint_timings") or "{}")
    except (json.JSONDecodeError, TypeError):
        endpoint_timings = {}
    return jsonify({"available": True, "endpoint_timings": endpoint_timings, **result})
