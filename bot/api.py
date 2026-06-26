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

import json
import os
from collections import Counter
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

from . import (auto_learner, calibrate, chat as chat_mod, clv, config, datasource,
               db, elo, espn_api, features, live_api, memory, namematch,
               odds_api, predictor, sackmann_feeder, settlement, weather)
from . import __version__
from .bootstrap import bootstrap
from .log import log

app = Flask(__name__)
# Borne la taille des requêtes (upload /api/upload) : sans limite, un POST de
# plusieurs Go saturerait la RAM (f.read() charge tout en mémoire). 16 Mo suffit
# pour les PDF/CSV/TXT attendus.
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

# Mémoire chargée une fois au démarrage (modèle + profils joueurs).
_MEM: Dict[str, Any] = {}
_INDEX: Dict[str, Any] = {}
# Facteur de calibration appris (temperature scaling). 1.0 = inchangé.
_CALIB_K: float = 1.0
# Poids modèle dans le blend modèle/marché (0 = marché pur, 1 = modèle pur).
_MKT_W: float = calibrate.DEFAULT_MARKET_BLEND_W


def _load_state() -> None:
    global _MEM, _INDEX, _CALIB_K, _MKT_W
    bootstrap()
    db.init()
    _MEM = memory.load()
    counts = {n: int(p.get("n", 0)) for n, p in _MEM["players"].items()}
    _INDEX = namematch.build_index(list(_MEM["players"]), counts)
    # Rétro-remplissage surface + cartes de résolution au 1er démarrage (réseau).
    if not db.get_meta("surface_maps"):
        try:
            maps = datasource.surface_backfill()
            db.set_meta("surface_maps", json.dumps(maps))
        except Exception as exc:  # noqa: BLE001
            log(f"Backfill surface ignoré ({exc}).", "WARN")

    # ELO global + ELO par surface avec K dynamique + dominance.
    rows = db.all_matches_chrono()
    _MEM["elo"], _ = elo.build_dynamic(rows)
    _MEM["elo_surface"] = {}
    for surf in ("hard", "clay", "grass"):
        _MEM["elo_surface"][surf], _ = elo.build_dynamic(rows, surface_key=surf)
    # Rejeu des matchs réglés sur l'ELO global (apprentissage continu, survit aux reboots).
    known = _MEM["players"]
    replayed = 0
    for s in db.settled_chrono():
        w, p1, p2 = s["winner"], s["player1"], s["player2"]
        if w in known and p1 in known and p2 in known and w in (p1, p2):
            elo.update(_MEM["elo"], w, p2 if w == p1 else p1)
            replayed += 1
    if replayed:
        log(f"ELO : {replayed} matchs réglés rejoués (apprentissage continu).")
    # Cartes de résolution de surface (nom / token / semaine).
    try:
        _MEM["surface_maps"] = json.loads(db.get_meta("surface_maps") or "{}")
    except (TypeError, ValueError):
        _MEM["surface_maps"] = {}
    try:
        _CALIB_K = float(db.get_meta("match_calib_k") or 1.0)
    except (TypeError, ValueError):
        _CALIB_K = 1.0
    try:
        _MKT_W = float(db.get_meta("market_blend_w")
                       or calibrate.DEFAULT_MARKET_BLEND_W)
    except (TypeError, ValueError):
        _MKT_W = calibrate.DEFAULT_MARKET_BLEND_W
    try:
        _MEM["elo_blend"] = float(db.get_meta("elo_blend") or predictor.ELO_BLEND)
    except (TypeError, ValueError):
        _MEM["elo_blend"] = predictor.ELO_BLEND


def _calib(p_match: float) -> float:
    """Applique la calibration apprise à une proba de match (0..1)."""
    return calibrate.calibrated_prob(p_match, _CALIB_K)


# --- CORS + auth -----------------------------------------------------------
@app.after_request
def _cors(resp):
    # Pas de CORS par défaut : le client Android (OkHttp) ignore complètement
    # CORS, donc le wildcard `*` ne profitait qu'aux navigateurs — et permettait
    # à n'importe quel site web visité sur le réseau de lire l'API (vol de
    # données en drive-by, surtout quand l'auth est absente). On n'autorise une
    # origine que si elle est explicitement configurée.
    origin = os.environ.get("TENNISBOSS_CORS_ORIGIN", "").strip()
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Token"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
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


def _surface_for(tournament: str, date: str = "") -> Optional[str]:
    """Surface d'un tournoi, en couches : nom normalisé -> vote par token de ville
    -> repli saisonnier (semaine de l'année). Renvoie None si rien de fiable."""
    maps = _MEM.get("surface_maps") or {}
    toks = datasource.normalize_tournament(tournament or "")
    if toks:
        key = " ".join(toks)
        nm = maps.get("name") or {}
        if key in nm:
            return nm[key]
        tm = maps.get("token") or {}
        votes = [tm[t] for t in toks if t in tm]
        if votes:
            return Counter(votes).most_common(1)[0][0]
    # Repli saison : la semaine de l'année donne la surface dominante du circuit.
    wk = datasource._iso_week((date or "").replace("-", ""))
    if wk is not None:
        return (maps.get("week") or {}).get(str(wk))
    return None


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


# Libellés lisibles des features du modèle (pour l'écran d'explication).
FEATURE_LABELS = {
    "serve": "Service",
    "return1": "Retour (1er service adverse)",
    "return2": "Retour (2e service adverse)",
    "recent": "Forme récente",
}


def _explain(name1: str, feat1: Dict[str, float],
             name2: str, feat2: Dict[str, float]) -> Dict[str, Any]:
    """Décompose la prédiction du 1er set, facteur par facteur.

    Le modèle est une régression logistique :
        z = Σ_k  poids_k * (feature1_k - feature2_k)  + biais
        P(J1) = sigmoid(z)
    La contribution de chaque facteur au logit z est donc
        poids_k * (feature1_k - feature2_k)
    >0 pousse vers J1, <0 vers J2. C'est une explication exacte (pas une
    approximation) : la somme des contributions + biais redonne z.
    """
    weights = _MEM["weights"]
    bias = float(_MEM["bias"])
    factors = []
    z = bias
    for k in config.FEATURE_ORDER:
        w = float(weights.get(k, 0.0))
        v1 = float(feat1.get(k, 0.5))
        v2 = float(feat2.get(k, 0.5))
        contrib = w * (v1 - v2)
        z += contrib
        favors = name1 if contrib > 1e-9 else (name2 if contrib < -1e-9 else None)
        factors.append({
            "key": k,
            "label": FEATURE_LABELS.get(k, k),
            "value1": round(v1, 4),
            "value2": round(v2, 4),
            "weight": round(w, 4),
            "contribution": round(contrib, 4),
            "favors": favors,
        })

    # Facteur ELO (signal historique fort), même décomposition exacte.
    elo_ratings = _MEM.get("elo") or {}
    if elo_ratings:
        ra = elo_ratings.get(name1, predictor.ELO_BASE)
        rb = elo_ratings.get(name2, predictor.ELO_BASE)
        elo_contrib = predictor.elo_logit(_MEM, name1, name2)
        z += elo_contrib
        favors = name1 if elo_contrib > 1e-9 else (name2 if elo_contrib < -1e-9 else None)
        factors.append({
            "key": "elo",
            "label": "Niveau ELO (historique)",
            "value1": round(elo.expected(ra, rb), 4),
            "value2": round(elo.expected(rb, ra), 4),
            "weight": round(float(_MEM.get("elo_blend", predictor.ELO_BLEND)), 4),
            "contribution": round(elo_contrib, 4),
            "favors": favors,
        })

    decisive = max(factors, key=lambda f: abs(f["contribution"]))
    return {
        "bias": round(bias, 4),
        "logit": round(z, 4),
        "factors": factors,
        "decisive": decisive["key"],
        "model_accuracy": round(float(_MEM["metrics"].get("accuracy", 0.0)), 4),
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
        "rate_limit": odds_api.rate_limit_status(),
        "odds_rate_limit": odds_api.rate_limit_status(),
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


_TORONTO_TZ = None

def _toronto_tz():
    global _TORONTO_TZ
    if _TORONTO_TZ is None:
        try:
            from zoneinfo import ZoneInfo
            _TORONTO_TZ = ZoneInfo("America/Toronto")
        except Exception:
            import datetime as _dt
            _TORONTO_TZ = _dt.timezone((_dt.timedelta(hours=-4)))  # EDT fallback
    return _TORONTO_TZ


def _fmt_date(d: str) -> str:
    """Normalise diverses formes de date vers 'JJ/MM/AAAA HH:MM' (heure Toronto).

    Formats gérés :
      '20241124'              -> '24/11/2024'
      '2024-11-24'            -> '24/11/2024'
      '2024-11-24T13:35:00Z'  -> '24/11/2024 09:35'  (UTC → America/Toronto)
    """
    s = str(d).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[6:8]}/{s[4:6]}/{s[0:4]}"
    if "T" in s or (len(s) >= 10 and s[4] == "-"):
        try:
            import datetime as _dt
            dt = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            dt = dt.astimezone(_toronto_tz())
            base = dt.strftime("%d/%m/%Y")
            time_part = dt.strftime("%H:%M")
            return f"{base} {time_part}" if time_part != "00:00" else base
        except ValueError:
            pass
    return s


def _h2h_payload(n1: str, n2: str, limit: int = 20) -> Dict[str, Any]:
    """Bilan des confrontations directes entre n1 et n2 (noms résolus)."""
    rows = db.head_to_head(n1, n2)
    wins1 = sum(1 for r in rows if r["winner"] == n1)
    wins2 = sum(1 for r in rows if r["winner"] == n2)
    meetings = [{
        "date": _fmt_date(r["date"]),
        "tour": r["tour"],
        "winner": r["winner"],
    } for r in rows[:limit]]
    leader = n1 if wins1 > wins2 else (n2 if wins2 > wins1 else None)
    return {
        "player1": n1, "player2": n2,
        "wins1": wins1, "wins2": wins2,
        "total": wins1 + wins2,
        "leader": leader,
        "meetings": meetings,
    }


@app.get("/api/h2h")
def api_h2h():
    p1, p2 = request.args.get("p1"), request.args.get("p2")
    if not p1 or not p2:
        return jsonify({"error": "paramètres requis: p1, p2"}), 400
    n1, n2 = _resolve(p1), _resolve(p2)
    if not n1 or not n2:
        return jsonify({"error": "joueur inconnu",
                        "unresolved": p1 if not n1 else p2}), 404
    return jsonify(_h2h_payload(n1, n2))


@app.get("/api/player")
def api_player():
    """Fiche détaillée d'un joueur : force, bilan V/D et forme récente."""
    name = request.args.get("name") or request.args.get("q")
    if not name:
        return jsonify({"error": "paramètre requis: name"}), 400
    resolved = _resolve(name)
    if not resolved:
        return jsonify({"error": "joueur inconnu", "unresolved": name}), 404

    payload = _player_payload(resolved)

    rec = db.player_record(resolved)
    total = rec["wins"] + rec["losses"]
    payload["record"] = {
        "wins": rec["wins"], "losses": rec["losses"], "total": total,
        "win_rate": round(rec["wins"] / total, 4) if total else 0.0,
    }

    form = []
    for r in db.player_recent_matches(resolved, limit=10):
        won = (r["winner"] == resolved)
        form.append({
            "date": _fmt_date(r["date"]),
            "tour": r["tour"],
            "opponent": r["loser"] if won else r["winner"],
            "result": "W" if won else "L",
        })
    payload["form"] = form

    prow = db.get_player(resolved)
    if prow is not None:
        payload["rating"] = round(float(prow["rating"]), 4)
        payload["win_prob"] = round(float(prow["win_prob"]), 4)

    return jsonify(payload)


def _set_to_match_prob(p_set: float) -> float:
    """Proba set -> proba match (centralisée dans predictor)."""
    return predictor.set_to_match_prob(p_set)


def _bet_builder(p1_set: float, n1: str, n2: str) -> Dict[str, Any]:
    """Dérive plusieurs marchés à partir de la proba du 1er set (best-of-3).

    Honnête : on ne renvoie que ce qui découle du modèle de set (vainqueur match,
    2e set, match en 3 sets, score exact). Points/aces ne sont PAS dérivables.
    """
    p = max(0.0, min(1.0, p1_set))
    q = 1.0 - p
    pm1 = _set_to_match_prob(p)
    return {
        "match": {"prob1": round(pm1 * 100, 1), "prob2": round((1 - pm1) * 100, 1)},
        "set2": {"prob1": round(p * 100, 1), "prob2": round(q * 100, 1)},
        "third_set_prob": round(2 * p * q * 100, 1),
        "correct_score": {
            f"{n1} 2-0": round(p * p * 100, 1),
            f"{n1} 2-1": round(2 * p * p * q * 100, 1),
            f"{n2} 2-1": round(2 * p * q * q * 100, 1),
            f"{n2} 2-0": round(q * q * 100, 1),
        },
    }


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
            "surface": r["surface"],
            "confidence": r["confidence"],
            "confidence_label": r["confidence_label"],
        },
        "explain": _explain(n1, f1, n2, f2),
        "h2h": _h2h_payload(n1, n2, limit=5),
        "bet_builder": _bet_builder(r["prob1"] / 100.0, n1, n2),
    })


@app.get("/api/upcoming")
def api_upcoming():
    days = min(int(request.args.get("days", 2)), 7)
    limit = min(int(request.args.get("limit", 25)), 100)
    want_odds = request.args.get("odds", "false").lower() == "true"

    # Source 1 : API-Tennis (payante)
    fixtures = live_api.fetch_upcoming({"live_api_provider": "api-tennis"}, days_ahead=days)

    # Source 2 : ESPN (gratuite, ~800 matchs ATP+WTA)
    espn_fixtures = espn_api.fetch_upcoming(days_ahead=days)

    # Source 3 : odds-api.io (fallback cotes + fixtures)
    odds_events = []
    odds_index = None
    if odds_api.is_enabled():
        odds_events = odds_api.fetch_tennis_events(upcoming_only=True)
        if want_odds:
            odds_index = odds_api.build_event_index(odds_events)

    # Fusion des sources : ESPN en priorité si API-Tennis vide
    if not fixtures:
        if espn_fixtures:
            log(f"ESPN fallback: {len(espn_fixtures)} matchs ATP+WTA.", "INFO")
            fixtures = espn_fixtures
        elif odds_events:
            log("Fallback odds-api.io pour les fixtures.", "INFO")
            fixtures = live_api.parse_odds_events_as_fixtures(odds_events)
    else:
        # API-Tennis dispo : on enrichit avec ESPN (matchs non dupliqués)
        existing = {(f["player1"].lower(), f["player2"].lower()) for f in fixtures}
        added = 0
        for ef in espn_fixtures:
            key = (ef["player1"].lower(), ef["player2"].lower())
            if key not in existing:
                fixtures.append(ef)
                existing.add(key)
                added += 1
        if added:
            log(f"ESPN: {added} matchs supplémentaires ajoutés.", "INFO")

    # Cache météo par tournoi pour éviter les appels répétés
    _weather_cache: Dict[str, Any] = {}

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
            "source": f.get("source", "api-tennis"),
        }
        if n1 and n2:
            surface = _surface_for(f["tournament"], f["date"])
            f1 = features.feature_vector(features.get_profile(_MEM, n1))
            f2 = features.feature_vector(features.get_profile(_MEM, n2))
            r = predictor.predict(_MEM, n1, f1, n2, f2, surface=surface)
            bb = _bet_builder(r["prob1"] / 100.0, n1, n2)
            fs_prob = max(r["prob1"], r["prob2"]) / 100.0
            fair_odds = round(1.0 / fs_prob, 2) if fs_prob > 0 else None
            item["prediction"] = {
                "player1": n1, "player2": n2,
                "prob1": r["prob1"], "prob2": r["prob2"],
                "favorite": r["favorite"],
                "surface": r["surface"],
                "confidence": r["confidence"],
                "confidence_label": r["confidence_label"],
                "first_set_prob": round(fs_prob * 100, 1),
                "fair_odds": fair_odds,
                "target_160": bool(fair_odds is not None and fair_odds >= 1.60),
                "ml_prob1": bb["match"]["prob1"], "ml_prob2": bb["match"]["prob2"],
                "set2_prob1": bb["set2"]["prob1"], "set2_prob2": bb["set2"]["prob2"],
                "total_sets_over": bb["third_set_prob"],
                "correct_score_probs": bb["correct_score"],
            }
            if odds_index is not None:
                item["odds"] = _odds_for(odds_index, f["player1"], f["player2"])

            # Météo : uniquement pour les tournois outdoor connus
            tourn_key = f["tournament"].lower()
            if tourn_key not in _weather_cache:
                _weather_cache[tourn_key] = weather.fetch_weather(
                    f["tournament"], surface or "")
            w = _weather_cache[tourn_key]
            if w:
                item["weather"] = w
        out.append(item)
        if len(out) >= limit:
            break
    return jsonify({"count": len(out), "matches": out})


@app.get("/api/value")
def api_value():
    """Compare le modèle au marché et calcule l'EV (espérance de gain) réelle.

    EV(parier J) = proba_match_modèle(J) × cote(J) − 1.  EV > 0 = value (+).
    min_confidence (float, défaut 0.4) : ignore les picks sous ce seuil de confiance.
    """
    limit = min(int(request.args.get("limit", 10)), 30)
    min_conf = float(request.args.get("min_confidence", 0.4))
    if not odds_api.is_enabled():
        return jsonify({"error": "ODDS_API_KEY absente"}), 503

    # Pool épuisé = _current_key() retourne None
    if odds_api._current_key() is None:
        rl = odds_api.rate_limit_status()
        best_reset = min((p.get("reset_in_s") or 9999 for p in rl.get("pool", [])), default=9999)
        return jsonify({
            "count": 0,
            "comparisons": [],
            "rate_limited": True,
            "retry_in_s": best_reset,
            "message": f"Limite API atteinte — réessayer dans {best_reset}s",
        })

    events = odds_api.fetch_tennis_events(upcoming_only=True)
    # Priorité aux grands tournois : ATP/WTA principaux avant ITF/UTR.
    def _tourn_rank(e: Dict) -> int:
        slug = (e.get("league") or {}).get("slug", "")
        if any(k in slug for k in ("wimbledon", "roland-garros", "us-open", "australian")):
            return 0
        if any(k in slug for k in ("eastbourne", "halle", "queens", "queens-club")):
            return 1
        if slug.startswith("atp") or slug.startswith("wta"):
            return 2
        return 3
    events = sorted(events, key=_tourn_rank)

    # Limite le nombre d'appels /odds pour préserver le quota (1 appel = 1 req)
    MAX_ODDS_CALLS = 30
    odds_calls = 0
    out = []
    for e in events:
        n1, n2 = _resolve(e.get("home", "")), _resolve(e.get("away", ""))
        if not n1 or not n2:
            continue
        if odds_calls >= MAX_ODDS_CALLS:
            break
        mw = odds_api.fetch_match_winner(e["id"])
        odds_calls += 1
        if not mw:
            continue
        f1 = features.feature_vector(features.get_profile(_MEM, n1))
        f2 = features.feature_vector(features.get_profile(_MEM, n2))
        r = predictor.predict(_MEM, n1, f1, n2, f2)

        if r["confidence"] < min_conf:
            continue

        pm1 = _calib(_set_to_match_prob(r["prob1"] / 100.0))  # proba match calibrée (J1)
        pm2 = 1.0 - pm1                                         # (J2)
        ho, ao = mw["home_odds"], mw["away_odds"]
        # Blend modèle/marché : le marché (sans vig) sert de prior, le modèle
        # ajuste selon son poids appris. L'EV est calculée sur la proba blendée,
        # sinon un modèle faible voit du "value" sur tous les outsiders.
        pb1 = calibrate.blend_probs(pm1, mw["home_prob"], _MKT_W)
        pb2 = 1.0 - pb1
        ev1 = pb1 * ho - 1.0
        ev2 = pb2 * ao - 1.0

        if ev1 >= ev2:
            best_side, best_ev = n1, ev1
        else:
            best_side, best_ev = n2, ev2

        # Capture la cote du favori du modèle (pour le ROI au settlement).
        if r["favorite"] is not None:
            fav_odds = ho if r["favorite"] == n1 else ao
            try:
                db.log_bet(e.get("date", ""), n1, n2, r["favorite"], fav_odds)
            except Exception:  # noqa: BLE001
                pass

        # Paper-trading : capture le value pick blendé (ROI mesuré au settlement).
        if best_ev > 0:
            pick_odds = ho if best_side == n1 else ao
            try:
                db.log_value_pick(e.get("date", ""), n1, n2, best_side,
                                  pick_odds, round(best_ev * 100, 1))
            except Exception:  # noqa: BLE001
                pass
            # CLV : sème le pick (1re cote = décision) puis rafraîchit la closing
            # line au quote courant (le dernier vu avant le départ fait foi).
            try:
                ekey = str(e.get("id") or "")
                pick_prob = pb1 if best_side == n1 else pb2
                clv.seed_pick(ekey, e.get("date", ""), n1, n2, best_side,
                              pick_odds, pick_prob, r["confidence"])
                clv.refresh_closing(ekey, best_side, n1, ho, ao)
            except Exception:  # noqa: BLE001
                pass

        out.append({
            "player1": n1, "player2": n2,
            "league": (e.get("league") or {}).get("name", ""),
            "confidence": r["confidence"],
            "confidence_label": r["confidence_label"],
            "model_first_set_prob1": r["prob1"],
            "model_match_prob1": round(pm1 * 100, 1),
            "model_match_prob2": round(pm2 * 100, 1),
            "blend_match_prob1": round(pb1 * 100, 1),
            "blend_match_prob2": round(pb2 * 100, 1),
            "market_match_prob1": round(mw["home_prob"] * 100, 1),
            "market_match_prob2": round(mw["away_prob"] * 100, 1),
            "odds": {"home": ho, "away": ao, "books": mw["books"]},
            "ev1": round(ev1 * 100, 1),
            "ev2": round(ev2 * 100, 1),
            "best_side": best_side if best_ev > 0 else None,
            "best_ev": round(best_ev * 100, 1),
            "value": best_ev > 0,
        })

    # Les meilleures values d'abord.
    out.sort(key=lambda c: c["best_ev"], reverse=True)
    if len(out) > limit:
        out = out[:limit]

    # Si aucun résultat live, on sert les picks DB récents (rate-limit ou pas de cotes)
    if not out:
        db_picks = db.list_value_picks()
        for row in db_picks[:limit]:
            out.append({
                "player1": row["player1"],
                "player2": row["player2"],
                "league": "",
                "confidence": None,
                "confidence_label": "",
                "best_side": row["side"],
                "best_ev": row["ev"],
                "odds": {"home": row["odds"], "away": None, "books": []},
                "ev1": row["ev"] if row["side"] == row["player1"] else None,
                "ev2": row["ev"] if row["side"] == row["player2"] else None,
                "value": True,
                "date": _fmt_date(row["date"]),
                "source": "cache_db",
            })

    return jsonify({
        "count": len(out),
        "comparisons": out,
        "rate_limited": False,
        "calibration_k": round(_CALIB_K, 3),
        "market_blend_w": round(_MKT_W, 2),
        "min_confidence": round(min_conf, 2),
        "note": ("proba match calibrée (best-of-3 + temperature), blendée au "
                 "marché (poids modèle w) ; EV = proba_blend×cote − 1"),
    })


def _blend_samples() -> list:
    """Échantillons (logit_features, logit_elo_brut, issue) pour régler β."""
    elo_r = _MEM.get("elo") or {}
    w = _MEM["weights"]
    bias = float(_MEM["bias"])
    out = []
    for s in db.list_settled(limit=100000):
        p1, p2, winner = s["player1"], s["player2"], s["winner"]
        if p1 not in _MEM["players"] or p2 not in _MEM["players"]:
            continue
        f1 = features.feature_vector(features.get_profile(_MEM, p1))
        f2 = features.feature_vector(features.get_profile(_MEM, p2))
        feat_logit = (predictor.weighted_score(w, f1)
                      - predictor.weighted_score(w, f2) + bias)
        el = elo.match_logit(elo_r.get(p1, predictor.ELO_BASE),
                             elo_r.get(p2, predictor.ELO_BASE))
        out.append((feat_logit, el, 1.0 if winner == p1 else 0.0))
    return out


def _refit_calibration() -> Dict[str, Any]:
    """Réajuste k (température), β (poids ELO) et w (blend marché) sur les réglés."""
    global _CALIB_K, _MKT_W
    fit = calibrate.fit_temperature(db.list_settled(limit=100000))
    if fit.get("fitted"):
        _CALIB_K = float(fit["k"])
        db.set_meta("match_calib_k", _CALIB_K)

    bfit = calibrate.tune_blend(_blend_samples())
    if bfit.get("fitted") and bfit.get("elo_blend") is not None:
        _MEM["elo_blend"] = float(bfit["elo_blend"])
        db.set_meta("elo_blend", _MEM["elo_blend"])

    mfit = calibrate.fit_market_blend(settlement.market_blend_samples(_CALIB_K))
    if mfit.get("fitted") and mfit.get("market_blend_w") is not None:
        _MKT_W = float(mfit["market_blend_w"])
        db.set_meta("market_blend_w", _MKT_W)

    return {"temperature": fit, "blend": bfit, "market_blend": mfit}


@app.get("/api/settlement/run")
def api_settlement_run():
    """Enregistre les matchs terminés récents, recalibre, et met à jour les métriques."""
    days = min(int(request.args.get("days", 2)), 7)
    summary = settlement.run_settlement(_MEM, _resolve, days_back=days)
    fit = _refit_calibration()
    metrics = settlement.calibration_metrics()
    if metrics["n"] > 0:
        try:
            db.save_calibration(metrics)
        except Exception:  # noqa: BLE001
            pass
    return jsonify({"settlement": summary, "calibration": metrics, "fit": fit})


@app.get("/api/calibration")
def api_calibration():
    """Métriques de performance du modèle sur les matchs réglés + facteur appris."""
    metrics = settlement.calibration_metrics()
    recent = [{
        "date": _fmt_date(r["date"]), "tour": r["tour"],
        "player1": r["player1"], "player2": r["player2"],
        "winner": r["winner"], "score": r["final_score"],
        "pred_favorite": r["pred_favorite"], "correct": r["correct"],
    } for r in db.list_settled(limit=25)]
    return jsonify({"metrics": metrics, "calibration_k": round(_CALIB_K, 3),
                    "market_blend_w": round(_MKT_W, 2),
                    "elo_blend": round(float(_MEM.get("elo_blend", predictor.ELO_BLEND)), 2),
                    "recent": recent})


@app.get("/api/clv")
def api_clv():
    """Closing Line Value — la preuve d'edge (indicateur avancé de profitabilité).

    Renvoie : CLV% moyen, % de picks qui battent la clôture (± IC95), ROI flat,
    P&L Kelly, le tout global + par palier de confiance, et un verdict honnête.
    """
    stats = clv.stats()
    recent = [{
        "date": _fmt_date(r["date"]),
        "player1": r["player1"], "player2": r["player2"],
        "side": r["pick_side"], "pick_odds": r["pick_odds"],
        "closing_odds": r["closing_odds"], "closing_src": r["closing_src"],
        "clv_pct": r["clv_pct"], "beat_closing": r["beat_closing"],
        "result": r["result"], "pnl_flat": r["pnl_flat"],
    } for r in db.list_clv(limit=30)]
    return jsonify({**stats, "recent": recent})


@app.post("/api/learn/run")
def api_learn_run():
    """Déclenche un cycle d'auto-learning : tuning par surface + k-fold eval."""
    try:
        learner = auto_learner.AutoLearner()
        result = learner.run_full_cycle()
        return jsonify({"status": "ok", "learning": result})
    except Exception as e:  # noqa: BLE001
        log(f"auto-learning error: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500


@app.post("/api/ingest/sackmann")
def api_ingest_sackmann():
    """Ingest Sackmann tennis data (GitHub) : ATP & WTA 2022-2026."""
    start_year = int(request.args.get("start_year", 2022))
    end_year = int(request.args.get("end_year", 2026))
    try:
        counts = sackmann_feeder.ingest_year_range(start_year, end_year)
        return jsonify({
            "status": "ok",
            "ingest": counts,
            "message": f"Ingested {counts['inserted']} new matches, "
                      f"{counts['duplicates']} duplicates, {counts['skipped']} skipped (unknown players)"
        })
    except Exception as e:  # noqa: BLE001
        log(f"sackmann ingest error: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Chat IA (Groq primaire / Gemini-Gemma fallback / Ollama local). Body JSON: {message, history=[]}."""
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    history = data.get("history") or []
    if not message:
        return jsonify({"error": "message requis"}), 400
    primary_url = os.environ.get("GROQ_API_URL", config.GROQ_API_URL)
    primary_model = os.environ.get("GROQ_MODEL", config.GROQ_MODEL)
    try:
        extra = chat_mod.build_match_context(message, _MEM)
        reply = chat_mod.chat(message, history, _MEM, primary_url, model=primary_model,
                              extra_context=extra)
        return jsonify({"reply": reply, "context_used": bool(extra)})
    except Exception as exc:  # noqa: BLE001
        log(f"Chat LLM en échec : {exc}", "WARN")
        return jsonify({"error": f"LLM inaccessible (modèle: {primary_model}) : {exc}"}), 503


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload d'un fichier (PDF/CSV/TXT) — retourne le texte extrait.

    Multipart: champ 'file'. La question optionnelle 'message' permet de
    poser une question sur le fichier directement dans la même requête.
    """
    if "file" not in request.files:
        return jsonify({"error": "champ 'file' manquant"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "fichier vide"}), 400
    try:
        from .file_parser import parse
        text, ftype = parse(f.filename, f.read())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 415
    except Exception as exc:
        return jsonify({"error": f"Erreur lecture fichier : {exc}"}), 500

    message = (request.form.get("message") or "").strip()
    if not message:
        return jsonify({"extracted_text": text, "type": ftype})

    # Question posée sur le fichier → injecter le texte dans le chat
    primary_url = os.environ.get("GROQ_API_URL", config.GROQ_API_URL)
    primary_model = os.environ.get("GROQ_MODEL", config.GROQ_MODEL)
    augmented = f"{message}\n\n[Contenu du fichier {f.filename}]\n{text}"
    try:
        reply = chat_mod.chat(augmented, [], _MEM, primary_url, model=primary_model)
        return jsonify({"reply": reply, "extracted_text": text, "type": ftype})
    except Exception as exc:
        log(f"Chat upload LLM en échec : {exc}", "WARN")
        return jsonify({"error": f"LLM inaccessible : {exc}"}), 503


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


def _settlement_loop(interval: int) -> None:
    """Boucle de fond : règle les matchs terminés et recalibre périodiquement."""
    import time as _t

    from .log import log
    while True:
        _t.sleep(interval)
        try:
            summary = settlement.run_settlement(_MEM, _resolve, days_back=2)
            _refit_calibration()
            metrics = settlement.calibration_metrics()
            if metrics["n"] > 0:
                db.save_calibration(metrics)
            log(f"Settlement auto: +{summary['added']} réglés, "
                f"n={metrics['n']} acc={metrics['accuracy']} k={round(_CALIB_K, 3)}")
        except Exception as exc:  # noqa: BLE001
            log(f"Settlement auto en échec ({exc}).", "WARN")


def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    _load_state()
    from .log import log

    # Charge .env AVANT toute lecture de token : _auth() lit os.environ à chaque
    # requête, il faut donc que TENNISBOSS_API_TOKEN y soit présent dès le départ.
    from .live_api import load_env as _load_env
    _load_env()

    token = os.environ.get("TENNISBOSS_API_TOKEN", "").strip()
    if not token and host not in ("127.0.0.1", "localhost"):
        log("SÉCURITÉ : API exposée sur le LAN SANS token (TENNISBOSS_API_TOKEN "
            "absent du .env) — tout le réseau peut lire les données ET déclencher "
            "/api/settlement/run, /api/learn/run, /api/upload. Définissez un token.",
            "WARN")
    log(f"API REST sur http://{host}:{port}  (auth token: {'OUI' if token else 'non'})")
    log(f"{len(_MEM['players'])} joueurs chargés. Endpoints sous /api/ + /health.")

    interval = int(os.environ.get("SETTLEMENT_INTERVAL_S", "1800"))
    if interval > 0:
        import threading
        threading.Thread(target=_settlement_loop, args=(interval,),
                         daemon=True).start()
        log(f"Settlement automatique toutes les {interval}s (auto-calibration).")

    # Self-healing agent (DeepSeek R1 via Ollama)
    from . import healer as _healer
    _healer.start(_MEM)

    # WebSocket odds-api.io — live scores + settlement instantané
    from .live_api import load_env as _load_env; _load_env()
    odds_key = os.environ.get("ODDS_API_KEY", "").strip()
    if odds_key:
        from . import odds_ws
        odds_ws.start(
            api_key=odds_key,
            on_status=_ws_on_status,
        )

    app.run(host=host, port=port, threaded=True)


def _ws_on_status(msg: dict) -> None:
    """Callback WebSocket : règle immédiatement un match settled."""
    if msg.get("status") != "settled":
        return
    scores = msg.get("scores") or {}
    home_s = scores.get("home", 0)
    away_s = scores.get("away", 0)
    if home_s == away_s:
        return
    eid = str(msg.get("id", ""))
    if not eid or settlement.db.settled_exists(f"ws_{eid}"):
        return

    from .log import log
    log(f"WS settled: event {eid} ({home_s}-{away_s})", "INFO")
    # Déclencher un settlement ciblé au prochain cycle (simple flag)
    _WS_PENDING.add(eid)


_WS_PENDING: set = set()
