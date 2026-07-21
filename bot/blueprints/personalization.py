"""Personalization blueprint — player/match follow watchlists."""
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request

from .. import db

bp = Blueprint("personalization", __name__)


def _followed_match_payload(row: Any) -> Dict[str, Any]:
    """Sérialise une ligne followed_matches pour l'API."""
    key = row["event_key"]
    mv = db.line_movement(key)
    return {
        "event_key": key,
        "player1": row["player1"],
        "player2": row["player2"],
        "match_date": row["match_date"],
        "tournament": row["tournament"],
        "followed": True,
        "last_odds_home": row["last_odds_home"],
        "last_odds_away": row["last_odds_away"],
        "last_refresh_ts": row["last_refresh_ts"],
        "line_movement": mv,
    }


@bp.post("/api/player/follow")
def api_player_follow():
    """Suit un joueur — signal explicite de personnalisation (voir
    bot/recommendations.py::favorite_players, qui priorise les suivis
    explicites sur l'inférence par fréquence de recherche)."""
    from .. import api

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "paramètre requis: name"}), 400
    resolved = api._resolve(name) or name
    db.follow_player(resolved)
    return jsonify({"name": resolved, "followed": True})


@bp.post("/api/player/unfollow")
def api_player_unfollow():
    from .. import api

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "paramètre requis: name"}), 400
    resolved = api._resolve(name) or name
    db.unfollow_player(resolved)
    return jsonify({"name": resolved, "followed": False})


@bp.get("/api/players/followed")
def api_players_followed():
    """Liste des joueurs suivis, avec leur fiche complète (réutilise _player_payload)."""
    from .. import api

    names = db.list_followed_players()
    players = []
    for n in names:
        p = api._player_payload(n)
        p["followed"] = True
        players.append(p)
    return jsonify({"count": len(names), "players": players})


@bp.post("/api/match/follow")
def api_match_follow():
    """Suit un match — refresh odds prioritaire (watchlist parieur).

    Corps JSON : event_key (optionnel), player1, player2, match_date, tournament.
    """
    from .. import api

    body = request.get_json(silent=True) or {}
    p1 = (body.get("player1") or "").strip()
    p2 = (body.get("player2") or "").strip()
    if not p1 or not p2:
        return jsonify({"error": "paramètres requis: player1, player2"}), 400
    r1 = api._resolve(p1) or p1
    r2 = api._resolve(p2) or p2
    key = db.follow_match(
        body.get("event_key"),
        r1,
        r2,
        match_date=(body.get("match_date") or "").strip(),
        tournament=(body.get("tournament") or "").strip(),
    )
    return jsonify({
        "event_key": key,
        "player1": r1,
        "player2": r2,
        "followed": True,
    })


@bp.post("/api/match/unfollow")
def api_match_unfollow():
    from .. import api

    body = request.get_json(silent=True) or {}
    p1 = (body.get("player1") or "").strip()
    p2 = (body.get("player2") or "").strip()
    if not body.get("event_key") and (not p1 or not p2):
        return jsonify({"error": "paramètres requis: event_key ou player1+player2"}), 400
    db.unfollow_match(
        body.get("event_key"),
        api._resolve(p1) or p1 if p1 else "",
        api._resolve(p2) or p2 if p2 else "",
        match_date=(body.get("match_date") or "").strip(),
    )
    return jsonify({"followed": False})


@bp.get("/api/matches/followed")
def api_matches_followed():
    """Matchs suivis avec dernières cotes et mouvement de ligne."""
    rows = db.list_followed_matches()
    matches = [_followed_match_payload(r) for r in rows]
    return jsonify({"count": len(matches), "matches": matches})
