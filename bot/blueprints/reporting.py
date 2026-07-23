"""Reporting blueprint — calibration/CLV/history/line-movement (read-only,
D-1 phase 2f). ``_fmt_date``/``_clean_tournament`` and the calibration-state
globals (``_CALIB_K`` etc.) stay defined in ``api.py`` (used elsewhere too) —
accessed here via ``from .. import api`` and live attribute lookup, same
pattern as ``bot/blueprints/matches.py``.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import clv, db, predictor, settlement

bp = Blueprint("reporting", __name__)


@bp.get("/api/calibration")
def api_calibration():
    """Métriques de performance du modèle sur les matchs réglés + facteur appris."""
    from .. import api

    metrics = settlement.calibration_metrics()
    recent = [{
        "date": api._fmt_date(r["date"]), "tour": r["tour"],
        "player1": r["player1"], "player2": r["player2"],
        "winner": r["winner"], "score": r["final_score"],
        "pred_favorite": r["pred_favorite"], "correct": r["correct"],
    } for r in db.list_settled(limit=25)]
    return jsonify({"metrics": metrics, "calibration_k": round(api._CALIB_K, 3),
                    "platt_a": round(api._PLATT_A, 4), "platt_b": round(api._PLATT_B, 4),
                    "market_blend_w": round(api._MKT_W, 2),
                    "elo_blend": round(float(api._MEM.get("elo_blend", predictor.ELO_BLEND)), 2),
                    "recent": recent})


@bp.get("/api/history")
def api_history():
    """Historique des matchs réglés par date + liste des dates disponibles.

    ?date=YYYY-MM-DD  -> matchs de ce jour
    ?dates=1          -> liste des dates avec matchs (calendrier)
    """
    from .. import api

    if request.args.get("dates"):
        dates = db.settled_available_dates(limit=90)
        return jsonify({"dates": dates})

    date_str = request.args.get("date", "")
    if not date_str:
        import datetime as _dt
        date_str = _dt.date.today().isoformat()

    rows = db.list_settled_by_date(date_str, limit=100)
    matches = []
    for r in rows:
        is_doubles = "/" in str(r["player1"]) or "/" in str(r["player2"])
        matches.append({
            "date": api._fmt_date(r["date"]),
            "tour": r["tour"],
            "tournament": api._clean_tournament(r["tournament"]),
            "player1": r["player1"],
            "player2": r["player2"],
            "winner": r["winner"],
            "score": r["final_score"],
            "pred_favorite": r["pred_favorite"],
            "correct": r["correct"],
            "is_doubles": is_doubles,
        })

    judged = [m for m in matches if m["correct"] is not None]
    accuracy = round(sum(m["correct"] for m in judged) / len(judged), 3) if judged else None
    return jsonify({
        "date": date_str,
        "count": len(matches),
        "n_predicted": len(judged),
        "accuracy_day": accuracy,
        "matches": matches,
    })


@bp.get("/api/clv")
def api_clv():
    """Closing Line Value — la preuve d'edge (indicateur avancé de profitabilité).

    Renvoie : CLV% moyen, % de picks qui battent la clôture (± IC95), ROI flat,
    P&L Kelly, le tout global + par palier de confiance, et un verdict honnête.
    """
    from .. import api

    stats = clv.stats()
    recent = [{
        "date": api._fmt_date(r["date"]),
        "player1": r["player1"], "player2": r["player2"],
        "side": r["pick_side"], "pick_odds": r["pick_odds"],
        "closing_odds": r["closing_odds"], "closing_src": r["closing_src"],
        "clv_pct": r["clv_pct"], "beat_closing": r["beat_closing"],
        "result": r["result"], "pnl_flat": r["pnl_flat"],
        "honeypot": ({
            "flag": True, "beneficiary": r["honeypot_beneficiary"],
            "player": r["honeypot_player"], "edge_pct": r["honeypot_edge_pct"],
        } if r["honeypot_flag"] else None),
    } for r in db.list_clv(limit=30)]
    return jsonify({**stats, "recent": recent})


@bp.get("/api/clv/weekly")
def api_clv_weekly():
    """Rapport CLV sur les 7 derniers jours (validation paper trading).

    Query : ?days=7 (défaut), max 90.
    """
    days = min(90, max(1, int(request.args.get("days", 7))))
    return jsonify(clv.weekly_stats(days=days))


@bp.get("/api/line-movement")
def api_line_movement():
    """Diagnostic : mouvement de ligne capté par le scanner pour un match.

    `event_id` = id odds-api du match (visible dans /api/value). Sans
    paramètre, renvoie le nombre total de snapshots captés à ce jour.
    """
    eid = request.args.get("event_id", "")
    if eid:
        mv = db.line_movement(eid)
        return jsonify(mv or {"error": "moins de 2 snapshots pour ce match"})
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
        distinct = conn.execute("SELECT COUNT(DISTINCT event_key) FROM market_snapshots").fetchone()[0]
    return jsonify({"total_snapshots": total, "matchs_distincts": distinct,
                    "note": "passer ?event_id=XXX pour le détail d'un match"})
