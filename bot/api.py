"""API REST de TennisBoss — backend JSON pour l'app Android.

Lancement :  python3 run.py serve --host 0.0.0.0 --port 8000

Endpoints (tous en JSON) :
  GET /health                      -> état du service
  GET /api/status                  -> métriques modèle + base
  GET /api/players?q=&tour=&limit= -> recherche joueurs (autocomplete) + proba
  GET /api/predict?p1=&p2=         -> prédiction du 1er set entre 2 joueurs
  GET /api/upcoming?days=&limit=&odds=true  -> matchs à venir + prédictions (+cotes)
  GET /api/value?limit=            -> modèle (1er set) vs marché (vainqueur match)

Sécurité : si la variable d'env TENNISBOSS_API_TOKEN est définie, chaque requête
/api/* doit présenter l'en-tête  X-API-Token: <token>  (sinon accès libre, utile
en réseau local pour le développement de l'app).
CORS ouvert (Access-Control-Allow-Origin: *) pour permettre l'appel depuis l'app.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

from . import (config, db, features, live_api, memory, namematch, odds_api,
               predictor)
from . import __version__
from .bootstrap import bootstrap

app = Flask(__name__)

# Mémoire chargée une fois au démarrage (modèle + profils joueurs).
_MEM: Dict[str, Any] = {}
_INDEX: Dict[str, Any] = {}


def _load_state() -> None:
    global _MEM, _INDEX
    bootstrap()
    db.init()
    _MEM = memory.load()
    counts = {n: int(p.get("n", 0)) for n, p in _MEM["players"].items()}
    _INDEX = namematch.build_index(list(_MEM["players"]), counts)


# --- CORS + auth -----------------------------------------------------------
@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Token"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return resp


@app.before_request
def _auth():
    if request.method == "OPTIONS" or request.path == "/health":
        return None
    token = os.environ.get("TENNISBOSS_API_TOKEN", "").strip()
    if token and request.headers.get("X-API-Token", "") != token:
        return jsonify({"error": "unauthorized"}), 401
    return None


# --- Helpers ---------------------------------------------------------------
def _resolve(name: str) -> Optional[str]:
    """Nom exact si connu, sinon tentative d'appariement (abrégé / accents)."""
    if name in _MEM["players"]:
        return name
    return namematch.resolve(name, _INDEX)


def _player_payload(name: str) -> Dict[str, Any]:
    prof = features.get_profile(_MEM, name)
    neutral = {k: 0.5 for k in config.FEATURE_ORDER}
    feat = features.feature_vector(prof)
    win_prob, _, _, _ = predictor.probability(
        _MEM["weights"], _MEM["bias"], feat, neutral)
    return {
        "name": name,
        "tour": prof.get("tour", ""),
        "matches": int(prof.get("n", 0)),
        "serve": round(feat["serve"], 4),
        "return1": round(feat["return1"], 4),
        "return2": round(feat["return2"], 4),
        "recent": round(feat["recent"], 4),
        "win_prob_vs_avg": round(win_prob, 4),
        "confident": features.is_confident(prof),
    }


# --- Endpoints -------------------------------------------------------------
@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "TennisBoss",
                    "version": __version__,
                    "players_loaded": len(_MEM.get("players", {}))})


@app.get("/api/status")
def api_status():
    m = _MEM["metrics"]
    return jsonify({
        "metrics": m,
        "weights": _MEM["weights"],
        "bias": _MEM["bias"],
        "datasets_loaded": _MEM["datasets_loaded"],
        "db": db.counts(),
    })


@app.get("/api/players")
def api_players():
    q = (request.args.get("q") or "").strip().lower()
    tour = request.args.get("tour")
    limit = min(int(request.args.get("limit", 20)), 200)
    results = []
    for name in _MEM["players"]:
        if q and q not in name.lower():
            continue
        if tour and (_MEM["players"][name].get("tour") != tour):
            continue
        results.append(_player_payload(name))
    results.sort(key=lambda p: p["win_prob_vs_avg"], reverse=True)
    return jsonify({"count": len(results), "players": results[:limit]})


@app.get("/api/predict")
def api_predict():
    p1, p2 = request.args.get("p1"), request.args.get("p2")
    if not p1 or not p2:
        return jsonify({"error": "paramètres requis: p1, p2"}), 400
    n1, n2 = _resolve(p1), _resolve(p2)
    if not n1 or not n2:
        return jsonify({"error": "joueur inconnu",
                        "unresolved": p1 if not n1 else p2}), 404
    f1 = features.feature_vector(features.get_profile(_MEM, n1))
    f2 = features.feature_vector(features.get_profile(_MEM, n2))
    r = predictor.predict(_MEM, n1, f1, n2, f2)
    try:
        db.log_prediction(n1, n2, r["prob1"] / 100.0, r["favorite"], source="api")
    except Exception:  # noqa: BLE001
        pass
    return jsonify({
        "player1": _player_payload(n1),
        "player2": _player_payload(n2),
        "first_set": {
            "prob1": r["prob1"], "prob2": r["prob2"],
            "favorite": r["favorite"], "verdict": r["verdict"],
        },
    })


@app.get("/api/upcoming")
def api_upcoming():
    days = min(int(request.args.get("days", 2)), 7)
    limit = min(int(request.args.get("limit", 25)), 100)
    want_odds = request.args.get("odds", "false").lower() == "true"

    fixtures = live_api.fetch_upcoming({"live_api_provider": "api-tennis"}, days_ahead=days)
    odds_index = None
    if want_odds and odds_api.is_enabled():
        odds_index = odds_api.build_event_index(
            odds_api.fetch_tennis_events(upcoming_only=True))

    out = []
    for f in fixtures:
        if f["is_doubles"]:
            continue
        n1, n2 = _resolve(f["player1"]), _resolve(f["player2"])
        item = {
            "player1_raw": f["player1"], "player2_raw": f["player2"],
            "tournament": f["tournament"], "round": f["round"],
            "date": f["date"], "time": f["time"], "live": f["live"],
            "tour": f["tour"], "predictable": bool(n1 and n2),
        }
        if n1 and n2:
            f1 = features.feature_vector(features.get_profile(_MEM, n1))
            f2 = features.feature_vector(features.get_profile(_MEM, n2))
            r = predictor.predict(_MEM, n1, f1, n2, f2)
            item["prediction"] = {
                "player1": n1, "player2": n2,
                "prob1": r["prob1"], "prob2": r["prob2"],
                "favorite": r["favorite"],
            }
            if odds_index is not None:
                item["odds"] = _odds_for(odds_index, f["player1"], f["player2"])
        out.append(item)
        if len(out) >= limit:
            break
    return jsonify({"count": len(out), "matches": out})


@app.get("/api/value")
def api_value():
    limit = min(int(request.args.get("limit", 10)), 30)
    if not odds_api.is_enabled():
        return jsonify({"error": "ODDS_API_KEY absente"}), 503
    events = odds_api.fetch_tennis_events(upcoming_only=True)
    out = []
    for e in events:
        n1, n2 = _resolve(e.get("home", "")), _resolve(e.get("away", ""))
        if not n1 or not n2:
            continue
        mw = odds_api.fetch_match_winner(e["id"])
        if not mw:
            continue
        f1 = features.feature_vector(features.get_profile(_MEM, n1))
        f2 = features.feature_vector(features.get_profile(_MEM, n2))
        r = predictor.predict(_MEM, n1, f1, n2, f2)
        out.append({
            "player1": n1, "player2": n2,
            "league": (e.get("league") or {}).get("name", ""),
            "model_first_set_prob1": r["prob1"],
            "market_match_prob1": round(mw["home_prob"] * 100, 1),
            "odds": {"home": mw["home_odds"], "away": mw["away_odds"],
                     "books": mw["books"]},
        })
        if len(out) >= limit:
            break
    return jsonify({"count": len(out), "comparisons": out,
                    "note": "marchés différents: modèle=1er set, marché=match"})


def _odds_for(odds_index, raw1: str, raw2: str) -> Optional[Dict[str, Any]]:
    ev = odds_api.find_event(odds_index, raw1, raw2)
    if not ev:
        return None
    mw = odds_api.fetch_match_winner(ev["id"])
    if not mw:
        return None
    return {"market_match_prob_home": round(mw["home_prob"] * 100, 1),
            "home_odds": mw["home_odds"], "away_odds": mw["away_odds"],
            "books": mw["books"]}


def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    _load_state()
    from .log import log

    token = os.environ.get("TENNISBOSS_API_TOKEN", "").strip()
    log(f"API REST sur http://{host}:{port}  (auth token: {'OUI' if token else 'non'})")
    log(f"{len(_MEM['players'])} joueurs chargés. Endpoints sous /api/ + /health.")
    app.run(host=host, port=port, threaded=True)
