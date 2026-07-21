"""Performance blueprint — track record + logging observability (read-only)."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import db, track_record

bp = Blueprint("performance", __name__)


@bp.get("/api/logging/health")
def api_logging_health():
    """Santé du pipeline de logging de reproductibilité (clv_log) — lecture
    seule, ne touche à aucune décision de pari. Voir docs/LOGGING_SCHEMA.md.

    ?bucket=week|day (défaut week) — granularité du rapport de complétude.
    ?incomplete_limit=N (défaut 50) — nombre de picks incomplets à lister.
    """
    db.init()
    bucket = request.args.get("bucket", "week")
    if bucket not in ("week", "day"):
        bucket = "week"
    incomplete_limit = min(int(request.args.get("incomplete_limit", 50)), 500)
    since = request.args.get("since", db.CLV_REPRO_EPOCH)
    report = db.clv_logging_completeness_report(bucket=bucket, since=since)
    report_all = db.clv_logging_completeness_report(bucket=bucket)
    incomplete = db.find_incomplete_clv_picks(limit=incomplete_limit, since=since)
    return jsonify({
        "completeness": report,
        "completeness_all_time": report_all,
        "incomplete_picks": incomplete,
        "n_incomplete_listed": len(incomplete),
        "required_fields": list(db.CLV_REPRO_FIELDS),
        "repro_epoch": db.CLV_REPRO_EPOCH,
        "note": ("Un pick est 'complet' si tous les champs de reproductibilité "
                 "(hors opening_odds/closing_odds, légitimement absents avant "
                 "mouvement de marché/fin de match) sont renseignés. Les champs "
                 "ranking absents pour joueurs non classés ne comptent pas "
                 "comme incomplets. Gate ADR-013 : since=repro_epoch."),
    })


@bp.get("/api/track-record")
def api_track_record():
    """Historique paginé des picks réglés (Track Record).

    Query : ?days=365&surface=hard&result=win&page=1&limit=50
    """
    days = min(3650, max(1, int(request.args.get("days", 365))))
    page = max(1, int(request.args.get("page", 1)))
    limit = min(500, max(1, int(request.args.get("limit", 50))))
    surface = (request.args.get("surface") or "").strip().lower() or None
    result = (request.args.get("result") or "").strip().lower() or None
    if result and result not in ("win", "loss", "void"):
        return jsonify({"error": "result must be win, loss, or void"}), 400
    return jsonify(track_record.list_picks(
        days=days, surface=surface, result=result, page=page, limit=limit,
    ))


@bp.get("/api/track-record/summary")
def api_track_record_summary():
    """Statistiques agrégées Track Record (ROI, streaks, CLV, confidence).

    Query : ?days=365&surface=hard
    """
    days = min(3650, max(1, int(request.args.get("days", 365))))
    surface = (request.args.get("surface") or "").strip().lower() or None
    return jsonify(track_record.summary(days=days, surface=surface))


@bp.get("/api/track-record/monthly")
def api_track_record_monthly():
    """Performance mensuelle Track Record.

    Query : ?days=365
    """
    days = min(3650, max(1, int(request.args.get("days", 365))))
    return jsonify(track_record.monthly_breakdown(days=days))


@bp.get("/api/track-record/surfaces")
def api_track_record_surfaces():
    """Performance par surface (Track Record).

    Query : ?days=365
    """
    days = min(3650, max(1, int(request.args.get("days", 365))))
    return jsonify(track_record.surface_breakdown(days=days))
