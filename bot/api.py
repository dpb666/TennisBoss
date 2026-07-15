"""API REST de TennisBoss — backend JSON pour l'app Android.

Lancement :  python3 run.py serve --host 0.0.0.0 --port 8000

Endpoints (tous en JSON) :
  GET /health                      -> état du service
  GET /api/status                  -> métriques modèle + base
  GET /api/players?q=&tour=&limit= -> recherche joueurs (autocomplete) + proba
  GET /api/predict?p1=&p2=         -> prédiction du 1er set entre 2 joueurs
  GET /api/upcoming?days=&limit=&odds=true  -> matchs à venir + prédictions (+cotes)
  GET /api/value?limit=            -> modèle (1er set) vs marché (vainqueur match)

Documentation complète (30 endpoints) : GET /api/docs (Swagger UI),
GET /api/openapi.json (spec brute) — les deux publics, sans token.

Sécurité : si la variable d'env TENNISBOSS_API_TOKEN est définie, chaque requête
/api/* doit présenter l'en-tête  X-API-Token: <token>  (sinon accès libre, utile
en réseau local pour le développement de l'app).
CORS ouvert (Access-Control-Allow-Origin: *) pour permettre l'appel depuis l'app.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_swagger_ui import get_swaggerui_blueprint

from . import (auto_learner, calibrate, chat as chat_mod, clv, config, datasource,
               db, elo, espn_api, features, intelligence, intelligence_layer, live_api, match_intelligence,
               memory, mistake_learner, namematch, odds_api, oddspapi_feeder, openapi_spec, predictor,
               recommendations, sackmann_feeder, settlement, weather)
from . import __version__
from .bootstrap import bootstrap
from .log import log

app = Flask(__name__)
# Borne la taille des requêtes (upload /api/upload) : sans limite, un POST de
# plusieurs Go saturerait la RAM (f.read() charge tout en mémoire). 16 Mo suffit
# pour les PDF/CSV/TXT attendus.
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

# Documentation Swagger UI (voir bot/openapi_spec.py) : /api/docs (interface)
# + /api/openapi.json (spec brute, exemptée d'auth dans _auth() plus bas).
app.register_blueprint(get_swaggerui_blueprint(
    "/api/docs", "/api/openapi.json", config={"app_name": "TennisBoss API"},
))


@app.get("/api/openapi.json")
def api_openapi_spec():
    return jsonify(openapi_spec.build_spec())


def _client_ip() -> str:
    """IP du VRAI client, pas du tunnel Cloudflare.

    Le trafic passe App -> Worker Cloudflare -> cloudflared tunnel -> Flask
    local (voir DEPLOYMENT.md) : `request.remote_addr` ne verrait que la
    connexion locale du tunnel (même IP pour tout le monde), rendant un
    rate-limit par IP inutile — tous les clients partageraient un seul
    quota. Cloudflare ajoute CF-Connecting-IP à l'edge (jamais falsifiable
    par le client, contrairement à X-Forwarded-For) ; le Worker le relaie
    tel quel (voir cloudflare/worker.js::new Headers(request.headers)).
    """
    return request.headers.get("CF-Connecting-IP") or request.remote_addr or "unknown"


limiter = Limiter(
    app=app,
    key_func=_client_ip,
    default_limits=["200 per minute"],
    storage_uri="memory://",
    headers_enabled=True,  # X-RateLimit-* dans la réponse, utile pour l'app cliente
)


@limiter.request_filter
def _skip_rate_limit() -> bool:
    # Tests (app.config["TESTING"]) et documentation publique : jamais throttlés.
    return bool(app.config.get("TESTING")) or request.path in ("/health", "/api/openapi.json") \
        or request.path.startswith("/api/docs")


@app.errorhandler(429)
def _rate_limit_exceeded(e):
    return jsonify({"error": "Trop de requêtes — réessaie dans un instant.",
                    "detail": str(e.description)}), 429

# Mémoire chargée une fois au démarrage (modèle + profils joueurs).
_MEM: Dict[str, Any] = {}
_INDEX: Dict[str, Any] = {}
# Facteur de calibration appris (temperature scaling). 1.0 = inchangé.
_CALIB_K: float = 1.0
# Platt scaling : p_calibré = sigmoid(a · logit(p) + b). Par défaut identité.
_PLATT_A: float = 1.0
_PLATT_B: float = 0.0
# Poids modèle dans le blend modèle/marché (0 = marché pur, 1 = modèle pur).
_MKT_W: float = calibrate.DEFAULT_MARKET_BLEND_W
# CLV par palier de confiance (2026-07-09, n=53) : >=75% = -6.9% de CLV vs -1.3%
# en 60-75% -> exige un EV plus élevé sur les picks à confiance élevée.
HIGH_CONF_MIN_EV = 15.0


def _load_state() -> None:
    global _MEM, _INDEX, _CALIB_K, _PLATT_A, _PLATT_B, _MKT_W
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

    # ELO global + ELO par surface + ELO de forme récente (180j).
    rows = db.all_matches_chrono()
    _MEM["elo"], _ = elo.build_dynamic(rows, time_decay_days=365)
    _MEM["elo_surface"] = {}
    for surf in ("hard", "clay", "grass"):
        _MEM["elo_surface"][surf], _ = elo.build_dynamic(rows, surface_key=surf,
                                                          time_decay_days=365)
    _MEM["elo_recent"], _ = elo.build_recent(rows, days=180)
    # Rejeu des matchs réglés : global + surface + récent (survit aux reboots).
    known = _MEM["players"]
    replayed = 0
    for s in db.settled_chrono():
        w, p1, p2 = s["winner"], s["player1"], s["player2"]
        loser = p2 if w == p1 else p1
        if w in known and p1 in known and p2 in known and w in (p1, p2):
            elo.update(_MEM["elo"], w, loser)
            elo.update(_MEM["elo_recent"], w, loser)
            surf = config.surface_from_league((s["tournament"] if "tournament" in s.keys() else "") or "")
            if surf and surf in _MEM["elo_surface"]:
                elo.update(_MEM["elo_surface"][surf], w, loser)
            replayed += 1
    if replayed:
        log(f"ELO : {replayed} matchs réglés rejoués (global + surface + récent).")
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
    try:
        import json as _json
        _surf_blends = _json.loads(db.get_meta("elo_blend_by_surface") or "{}")
        if _surf_blends:
            _MEM["elo_blend_surface"] = {k: float(v) for k, v in _surf_blends.items()}
    except Exception as exc:
        log(f"Chargement elo_blend_by_surface échoué ({exc}) — repli sur le blend global.", "WARN")
    try:
        _PLATT_A = float(db.get_meta("platt_a") or 1.0)
    except (TypeError, ValueError):
        _PLATT_A = 1.0
    try:
        _PLATT_B = float(db.get_meta("platt_b") or 0.0)
    except (TypeError, ValueError):
        _PLATT_B = 0.0

    # Charge les zones dangereuses apprises, puis recalcule sur les picks récents
    try:
        mistake_learner.load_from_db()
        mistake_learner.update()
    except Exception as exc:
        log(f"mistake_learner (zones dangereuses) échoué au démarrage ({exc}).", "WARN")

    # Intelligence autonome : blacklist joueurs + surfaces en danger
    try:
        intelligence.load_from_db()
        intelligence.run_cycle(send_telegram=False)
    except Exception as exc:
        log(f"intelligence (blacklist/surface danger) échoué au démarrage ({exc}).", "WARN")


def _calib(p_match: float) -> float:
    """Platt scaling : sigmoid(a · logit(p) + b), puis temperature k si Platt non fitté."""
    if _PLATT_A != 1.0 or _PLATT_B != 0.0:
        return calibrate.calibrated_prob_platt(p_match, _PLATT_A, _PLATT_B)
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
    # /privacy doit rester public : URL exigée par Google Play Console, sans
    # token pour que les revieweurs/utilisateurs puissent la consulter librement.
    # /api/docs (Swagger UI) et /api/openapi.json : documentation publique,
    # comme la plupart des API publiques (ne révèle aucune donnée, juste la
    # forme des requêtes/réponses).
    if (request.method == "OPTIONS" or request.path in ("/health", "/privacy", "/api/openapi.json")
            or request.path.startswith("/api/docs")):
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


def _clean_tournament(raw) -> str:
    """Extrait le nom lisible d'un tournoi, même si stocké comme dict {'name':..,'slug':..}."""
    if isinstance(raw, dict):
        return raw.get("name") or raw.get("slug") or ""
    s = str(raw or "")
    if s.startswith("{") and "'name'" in s:
        import ast
        try:
            d = ast.literal_eval(s)
            return d.get("name") or d.get("slug") or s
        except Exception:
            pass
    return s


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


@app.get("/privacy")
def privacy_policy():
    """Politique de confidentialité — URL publique requise par Google Play Console.

    Sert PRIVACY_POLICY.md (racine du repo) en HTML simple, sans dépendance
    de rendu markdown (juste un mapping ligne à ligne suffisant pour ce doc).
    """
    import os as _os
    path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "PRIVACY_POLICY.md")
    try:
        with open(path, encoding="utf-8") as f:
            md = f.read()
    except OSError:
        return "Politique de confidentialité indisponible.", 404

    import re as _re

    def _inline(text: str) -> str:
        return _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    lines_html = []
    in_table = False
    in_list = False
    para_buf: list = []

    def _flush_para():
        if para_buf:
            lines_html.append(f"<p>{_inline(' '.join(para_buf))}</p>")
            para_buf.clear()

    def _close_list():
        nonlocal in_list
        if in_list:
            lines_html.append("</ul>")
            in_list = False

    for line in md.splitlines():
        s = line.strip()
        is_sep_row = bool(_re.fullmatch(r"\|?[\s:|-]+\|?", s)) if s.startswith("|") else False
        if is_sep_row:
            continue
        if s.startswith("|"):
            _flush_para()
            _close_list()
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not in_table:
                lines_html.append("<table>")
                in_table = True
            tag = "th" if lines_html[-1] == "<table>" else "td"
            lines_html.append("<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            lines_html.append("</table>")
            in_table = False
        if s.startswith("# "):
            _flush_para()
            _close_list()
            lines_html.append(f"<h1>{_inline(s[2:])}</h1>")
        elif s.startswith("## "):
            _flush_para()
            _close_list()
            lines_html.append(f"<h2>{_inline(s[3:])}</h2>")
        elif s.startswith("- "):
            _flush_para()
            if not in_list:
                lines_html.append("<ul>")
                in_list = True
            lines_html.append(f"<li>{_inline(s[2:])}</li>")
        elif s:
            _close_list()
            para_buf.append(s)
        else:
            _flush_para()
            _close_list()
    _flush_para()
    _close_list()
    if in_table:
        lines_html.append("</table>")

    html = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Politique de confidentialité — TennisBoss AI</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 720px;
       margin: 0 auto; padding: 24px 20px 60px; line-height: 1.55; color: #1a1a1a; }}
h1 {{ font-size: 1.5rem; }} h2 {{ font-size: 1.15rem; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 0.9rem; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
th {{ background: #f5f5f5; }}
</style></head><body>{"".join(lines_html)}</body></html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


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
    # Accepte ?q= ou ?name= comme alias
    q = (request.args.get("q") or request.args.get("name") or "").strip().lower()
    tour = request.args.get("tour")
    limit = min(int(request.args.get("limit", 20)), 200)
    elo_dict = _MEM.get("elo") or {}
    elo_grass = (_MEM.get("elo_surface") or {}).get("grass", {})
    elo_clay = (_MEM.get("elo_surface") or {}).get("clay", {})
    elo_hard = (_MEM.get("elo_surface") or {}).get("hard", {})
    # Set pré-chargé une seule fois (pas une requête DB par joueur dans la
    # boucle ci-dessous, qui itère sur TOUS les joueurs connus avant la limite).
    followed_set = set(db.list_followed_players())
    results = []
    for name in _MEM["players"]:
        if q and q not in name.lower():
            continue
        if tour and (_MEM["players"][name].get("tour") != tour):
            continue
        p = _player_payload(name)
        p["followed"] = name in followed_set
        from .predictor import _lookup_elo, ELO_BASE
        p["elo"] = round(_lookup_elo(elo_dict, name))
        p["elo_grass"] = round(_lookup_elo(elo_grass, name)) if elo_grass else None
        p["elo_clay"] = round(_lookup_elo(elo_clay, name)) if elo_clay else None
        p["elo_hard"] = round(_lookup_elo(elo_hard, name)) if elo_hard else None
        results.append(p)
    results.sort(key=lambda p: p["win_prob_vs_avg"], reverse=True)
    return jsonify({"count": len(_MEM["players"]), "players": results[:limit]})


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
    payload["followed"] = db.is_player_followed(resolved)

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

    # ELO (signal le plus fort du modèle) + rang parmi les joueurs connus.
    elo_ratings = _MEM.get("elo") or {}
    if resolved in elo_ratings:
        r_elo = elo_ratings[resolved]
        same_tour = [v for n, v in elo_ratings.items()
                     if (_MEM.get("players") or {}).get(n, {}).get("tour") == payload.get("tour")]
        rank = sum(1 for v in same_tour if v > r_elo) + 1 if same_tour else None
        payload["elo"] = {
            "rating": round(r_elo, 1),
            "rank": rank,
            "n_ranked": len(same_tour) if same_tour else None,
        }
        surf_elo = _MEM.get("elo_surface") or {}
        by_surface = {s: round(d[resolved], 1) for s, d in surf_elo.items() if resolved in d}
        if by_surface:
            payload["elo"]["by_surface"] = by_surface

    return jsonify(payload)


@app.route("/api/player/follow", methods=["POST"])
def api_player_follow():
    """Suit un joueur — signal explicite de personnalisation (voir
    bot/recommendations.py::favorite_players, qui priorise les suivis
    explicites sur l'inférence par fréquence de recherche)."""
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "paramètre requis: name"}), 400
    resolved = _resolve(name) or name
    db.follow_player(resolved)
    return jsonify({"name": resolved, "followed": True})


@app.route("/api/player/unfollow", methods=["POST"])
def api_player_unfollow():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "paramètre requis: name"}), 400
    resolved = _resolve(name) or name
    db.unfollow_player(resolved)
    return jsonify({"name": resolved, "followed": False})


@app.get("/api/players/followed")
def api_players_followed():
    """Liste des joueurs suivis, avec leur fiche complète (réutilise _player_payload)."""
    names = db.list_followed_players()
    players = []
    for n in names:
        p = _player_payload(n)
        p["followed"] = True
        players.append(p)
    return jsonify({"count": len(names), "players": players})


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


@app.route("/api/match/follow", methods=["POST"])
def api_match_follow():
    """Suit un match — refresh odds prioritaire (watchlist parieur).

    Corps JSON : event_key (optionnel), player1, player2, match_date, tournament.
    """
    body = request.get_json(silent=True) or {}
    p1 = (body.get("player1") or "").strip()
    p2 = (body.get("player2") or "").strip()
    if not p1 or not p2:
        return jsonify({"error": "paramètres requis: player1, player2"}), 400
    r1 = _resolve(p1) or p1
    r2 = _resolve(p2) or p2
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


@app.route("/api/match/unfollow", methods=["POST"])
def api_match_unfollow():
    body = request.get_json(silent=True) or {}
    p1 = (body.get("player1") or "").strip()
    p2 = (body.get("player2") or "").strip()
    if not body.get("event_key") and (not p1 or not p2):
        return jsonify({"error": "paramètres requis: event_key ou player1+player2"}), 400
    db.unfollow_match(
        body.get("event_key"),
        _resolve(p1) or p1 if p1 else "",
        _resolve(p2) or p2 if p2 else "",
        match_date=(body.get("match_date") or "").strip(),
    )
    return jsonify({"followed": False})


@app.get("/api/matches/followed")
def api_matches_followed():
    """Matchs suivis avec dernières cotes et mouvement de ligne."""
    rows = db.list_followed_matches()
    matches = [_followed_match_payload(r) for r in rows]
    return jsonify({"count": len(matches), "matches": matches})


def _set_to_match_prob(p_set: float) -> float:
    """Proba set -> proba match (centralisée dans predictor)."""
    return predictor.set_to_match_prob(p_set)


_SLAMS = {"australian open", "roland garros", "french open", "wimbledon", "us open"}


def _best_of_for(tour: str, league_name: str) -> int:
    """Best-of-3 (défaut) ou best-of-5 (Grand Chelem messieurs uniquement)."""
    if (tour or "").lower() != "atp":
        return 3
    label = (league_name or "").lower()
    return 5 if any(s in label for s in _SLAMS) else 3


def _bet_builder(p1_set: float, n1: str, n2: str) -> Dict[str, Any]:
    """Dérive plusieurs marchés à partir de la proba du 1er set (best-of-3).

    La proba match est calibrée (Platt ou temperature scaling).
    """
    p = max(0.0, min(1.0, p1_set))
    q = 1.0 - p
    pm1 = _calib(_set_to_match_prob(p))   # calibration Platt appliquée ici
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

    # Fallback : si un joueur est inconnu, on utilise son nom brut avec profil neutre
    unknown = []
    if not n1:
        n1 = p1.strip()
        unknown.append(n1)
    if not n2:
        n2 = p2.strip()
        unknown.append(n2)

    # Guard cross-genre
    _pt1 = (_MEM.get("players") or {}).get(n1, {}).get("tour", "")
    _pt2 = (_MEM.get("players") or {}).get(n2, {}).get("tour", "")
    if _pt1 and _pt2 and {_pt1, _pt2} == {"atp", "wta"}:
        return jsonify({"error": "Impossible de comparer un joueur ATP et une joueuse WTA"}), 400

    f1 = features.feature_vector(features.get_profile(_MEM, n1))
    f2 = features.feature_vector(features.get_profile(_MEM, n2))
    _surf_req = request.args.get("surface") or None
    r = predictor.predict(_MEM, n1, f1, n2, f2, surface=_surf_req)

    # Si les deux joueurs sont inconnus → 50/50 forcé, confiance nulle
    if len(unknown) == 2:
        r["prob1"] = 50.0
        r["prob2"] = 50.0
        r["favorite"] = None
        r["confidence"] = 0.0
        r["confidence_label"] = "non profilé"
        r["verdict"] = "50/50 — joueurs non profilés"
    elif unknown:
        # Un seul inconnu : on pénalise la confiance
        r["confidence"] = min(r.get("confidence", 0.3), 0.3)
        r["confidence_label"] = "très faible (joueur non profilé)"

    try:
        db.log_prediction(n1, n2, r["prob1"] / 100.0, r["favorite"], source="api")
    except Exception as exc:  # noqa: BLE001
        log(f"db.log_prediction échoué pour {n1} vs {n2} ({exc}) — prédiction non archivée.", "WARN")

    payload = {
        "player1": _player_payload(n1) if n1 not in unknown else {"name": n1, "tour": "", "matches": 0, "confident": False},
        "player2": _player_payload(n2) if n2 not in unknown else {"name": n2, "tour": "", "matches": 0, "confident": False},
        "first_set": {
            "prob1": r["prob1"], "prob2": r["prob2"],
            "favorite": r["favorite"], "verdict": r["verdict"],
            "surface": r["surface"],
            "confidence": r["confidence"],
            "confidence_label": r["confidence_label"],
        },
        "h2h": _h2h_payload(n1, n2, limit=5),
        "bet_builder": _bet_builder(r["prob1"] / 100.0, n1, n2),
    }
    if not unknown:
        payload["explain"] = _explain(n1, f1, n2, f2)
    if unknown:
        payload["unknown_players"] = unknown

    # Analyse météo + crowd pour la prédiction directe
    tournament = request.args.get("tournament", "")
    surface_req = request.args.get("surface", r.get("surface", "hard"))
    try:
        from . import weather_profile as wp
        w_data = None
        if tournament:
            w_data = weather.fetch_weather(tournament, surface_req or "")
        p1_prof = features.get_profile(_MEM, n1)
        p2_prof = features.get_profile(_MEM, n2)
        wa = wp.analyze(_MEM, n1, p1_prof, n2, p2_prof,
                        w_data, tournament, surface_req or "hard")
        payload["weather_analysis"] = wa
    except Exception as exc:  # noqa: BLE001
        log(f"weather_profile.analyze échoué pour {n1} vs {n2} (/api/predict) ({exc}) — ignoré.", "WARN")

    return jsonify(payload)


@app.get("/api/insight")
def api_insight():
    """Sport Intelligence Layer (Phase 1) : "pourquoi ce pick ?" en un seul appel.

    Façade sur des calculs déjà faits ailleurs (voir bot/intelligence_layer.py) :
    décomposition exacte du logit (comme /api/predict), H2H, santé du modèle
    (drift/blacklist/surface, comme /api/intelligence/stats) et mouvement de
    cotes (comme /api/line-movement) — pour éviter à l'app de faire 3 appels
    et de recomposer elle-même l'explication.

    `event_id` (optionnel) = id odds-api du match (voir /api/live, /api/value),
    utilisé uniquement pour joindre le mouvement de ligne s'il existe.
    `sentiment=true` (optionnel, défaut false) : ajoute le sentiment
    actualités (NewsAPI.org). Opt-in volontaire — quota NewsAPI gratuit très
    serré (100 req/jour), voir bot/sentiment.py.
    """
    p1, p2 = request.args.get("p1"), request.args.get("p2")
    if not p1 or not p2:
        return jsonify({"error": "paramètres requis: p1, p2"}), 400
    n1 = _resolve(p1) or p1.strip()
    n2 = _resolve(p2) or p2.strip()

    surface = request.args.get("surface") or None
    event_id = request.args.get("event_id") or None
    include_sentiment = request.args.get("sentiment", "false").lower() == "true"

    f1 = features.feature_vector(features.get_profile(_MEM, n1))
    f2 = features.feature_vector(features.get_profile(_MEM, n2))
    r = predictor.predict(_MEM, n1, f1, n2, f2, surface=surface)
    explain = _explain(n1, f1, n2, f2)

    insight = intelligence_layer.build_insight(
        _MEM, n1, n2, explain,
        confidence=r["confidence"], confidence_label=r["confidence_label"],
        surface=surface, event_id=event_id, include_sentiment=include_sentiment,
    )

    # Phase 12a — Tennis Intelligence Score (TIS), extension non-breaking.
    try:
        odds_data = _tis_odds_snapshot(event_id)
        insight["match_intelligence"] = match_intelligence.compute_tis(
            n1, n2, surface=surface, odds_data=odds_data,
            mem=_MEM, event_key=event_id, explain=explain, prediction=r,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"TIS compute échoué pour {n1} vs {n2} ({exc}) — insight sans TIS.", "WARN")
    return jsonify(insight)


# TTL caches — endpoints Phase 12 (TIS) coûteux en requêtes SQLite par match.
_tis_response_cache: Dict[str, tuple] = {}  # key -> (expiry_ts, payload)
_MATCH_INTEL_TTL = 60
_engineer_today_cache: Dict[str, tuple] = {}
_ENGINEER_TODAY_TTL = 90
_ENGINEER_MAX_FIXTURES = 40  # cap TIS — évite N×~10 requêtes DB sur tout le tableau ESPN


def _tis_cache_get(cache: Dict[str, tuple], key: str) -> Optional[Any]:
    import time as _t
    hit = cache.get(key)
    if hit and hit[0] > _t.time():
        return hit[1]
    return None


def _tis_cache_set(cache: Dict[str, tuple], key: str, payload: Any, ttl: float) -> None:
    import time as _t
    cache[key] = (_t.time() + ttl, payload)


def _tis_odds_snapshot(event_key: Optional[str], *, http_timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    """Cotes ML pour TIS — timeout court pour ne pas bloquer l'origine (524 CF)."""
    if not event_key or not odds_api.is_enabled():
        return None
    try:
        mw = odds_api.fetch_match_winner(
            str(event_key), ttl=120, http_timeout=http_timeout,
        )
        if not mw:
            return None
        return {
            "home_odds": mw["home_odds"],
            "away_odds": mw["away_odds"],
            "home_prob": mw.get("home_prob"),
            "away_prob": mw.get("away_prob"),
        }
    except Exception as exc:  # noqa: BLE001
        log(f"TIS odds fetch échoué pour {event_key} ({exc}) — ignoré.", "WARN")
        return None


@app.get("/api/match/intelligence")
def api_match_intelligence():
    """Tennis Intelligence Score (TIS) — score 0-100 + recommandation de pari.

    Paramètres : p1, p2 (requis), surface (optionnel), event_key (optionnel,
    id odds-api pour cotes + steam move).
    """
    p1, p2 = request.args.get("p1"), request.args.get("p2")
    if not p1 or not p2:
        return jsonify({"error": "paramètres requis: p1, p2"}), 400
    n1 = _resolve(p1) or p1.strip()
    n2 = _resolve(p2) or p2.strip()
    surface = request.args.get("surface") or None
    event_key = request.args.get("event_key") or request.args.get("event_id") or None

    cache_key = f"{n1}|{n2}|{surface or ''}|{event_key or ''}"
    cached = _tis_cache_get(_tis_response_cache, cache_key)
    if cached is not None:
        return jsonify(cached)

    f1 = features.feature_vector(features.get_profile(_MEM, n1))
    f2 = features.feature_vector(features.get_profile(_MEM, n2))
    r = predictor.predict(_MEM, n1, f1, n2, f2, surface=surface)
    explain = _explain(n1, f1, n2, f2)

    odds_data = _tis_odds_snapshot(event_key)

    payload = match_intelligence.compute_tis(
        n1, n2, surface=surface, odds_data=odds_data,
        mem=_MEM, event_key=event_key, explain=explain, prediction=r,
    )
    payload["player1"] = n1
    payload["player2"] = n2
    _tis_cache_set(_tis_response_cache, cache_key, payload, _MATCH_INTEL_TTL)
    return jsonify(payload)


@app.get("/api/engineer/today")
@limiter.limit("10 per minute")
def api_engineer_today():
    """Tableau Engineer : matchs du jour classés par TIS (Phase 12d).

    Colonnes : match, surface, prédiction, confiance, cotes marché, cote juste,
    edge %, risque. Sans fetch odds massif (quota) — EV/edge à 0 sauf si cotes
    déjà présentes dans les fixtures.
    """
    import datetime as _dt

    limit = min(int(request.args.get("limit", 15)), 30)
    min_tis = float(request.args.get("min_tis", 0))

    cache_key = f"{limit}_{min_tis}"
    cached = _tis_cache_get(_engineer_today_cache, cache_key)
    if cached is not None:
        return jsonify(cached)

    fixtures = espn_api.fetch_upcoming(days_ahead=1)
    _today = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    fixtures = [
        f for f in fixtures
        if not f.get("is_doubles") and (f.get("live") or f.get("date", "") >= _today)
    ]

    rows: List[Dict[str, Any]] = []
    processed = 0
    for f in fixtures:
        if processed >= _ENGINEER_MAX_FIXTURES:
            break
        n1 = _resolve(f.get("player1", "")) or f.get("player1", "")
        n2 = _resolve(f.get("player2", "")) or f.get("player2", "")
        if not n1 or not n2:
            continue
        t1 = (_MEM.get("players") or {}).get(n1, {}).get("tour", "")
        t2 = (_MEM.get("players") or {}).get(n2, {}).get("tour", "")
        if t1 and t2 and {t1, t2} == {"atp", "wta"}:
            continue
        surface = f.get("surface") or config.surface_from_league(f.get("tournament", ""))
        try:
            tis = match_intelligence.compute_tis(n1, n2, surface=surface, mem=_MEM)
        except Exception as exc:  # noqa: BLE001
            log(f"engineer/today: TIS échoué {n1} vs {n2} ({exc}) — ignoré.", "WARN")
            continue
        processed += 1
        if tis["tis"] < min_tis:
            continue
        rows.append({
            "match": f"{n1} vs {n2}",
            "player1": n1,
            "player2": n2,
            "surface": surface or tis.get("surface"),
            "prediction": tis["favorite"],
            "confidence": tis["confidence"],
            "confidence_label": tis.get("confidence_label", ""),
            "market_odds": tis.get("market_odds"),
            "fair_odds": tis.get("fair_odds"),
            "edge_pct": tis.get("edge_pct", 0.0),
            "ev_pct": tis.get("ev_pct", 0.0),
            "risk_score": tis.get("risk_score", 0.0),
            "tis": tis["tis"],
            "recommendation": tis["recommendation"],
            "tournament": f.get("tournament", ""),
            "date": f.get("date", ""),
            "time": f.get("time", ""),
        })

    rows.sort(key=lambda r: (r["tis"], r.get("ev_pct", 0)), reverse=True)
    top = rows[:limit]
    result = {"count": len(top), "matches": top}
    _tis_cache_set(_engineer_today_cache, cache_key, result, _ENGINEER_TODAY_TTL)
    return jsonify(result)


_upcoming_cache: Dict[str, Any] = {}
_upcoming_cache_ts: float = 0.0
_UPCOMING_TTL = 270  # 4.5 min — ESPN change rarement plus vite


@app.get("/api/upcoming")
@limiter.limit("20 per minute")  # protège le quota odds-api.io partagé (100 req/h)
def api_upcoming():
    import time as _t
    import datetime as _dt
    days = min(int(request.args.get("days", 2)), 7)
    limit = min(int(request.args.get("limit", 25)), 100)
    want_odds = request.args.get("odds", "false").lower() == "true"
    cache_key = f"{days}_{limit}_{want_odds}"
    now = _t.time()
    global _upcoming_cache_ts
    if cache_key in _upcoming_cache and (now - _upcoming_cache_ts) < _UPCOMING_TTL:
        return jsonify(_upcoming_cache[cache_key])

    # Source 1 : API-Tennis (payante)
    fixtures = live_api.fetch_upcoming({"live_api_provider": "api-tennis"}, days_ahead=days)

    # Source 2 : ESPN (gratuite, ~800 matchs ATP+WTA)
    espn_fixtures = espn_api.fetch_upcoming(days_ahead=days)

    # Source 3 : odds-api.io (fallback cotes + fixtures + heures manquantes)
    odds_events = []
    odds_index = None
    odds_time_index: Dict[frozenset, str] = {}
    if odds_api.is_enabled():
        odds_events = odds_api.fetch_tennis_events(upcoming_only=True)
        # Index temps : comble les 00:00 ESPN avec les vraies heures odds-api.io
        odds_time_index = odds_api.build_time_index(odds_events)
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

    # Source 4 : OddsPapi (gratuit, 250 req/mois/compte, pool de clés) — comble
    # la couverture ATP/WTA/Challenger/ITF pendant qu'API-Tennis est impayé
    # (voir bot/oddspapi_feeder.py). Toujours un ajout, jamais un remplacement :
    # is_enabled() renvoie False sans clé configurée -> aucun effet de bord.
    if oddspapi_feeder.is_enabled():
        try:
            raw_oddspapi = oddspapi_feeder.fetch_tennis_fixtures(days_ahead=days)
            oddspapi_fixtures = oddspapi_feeder.parse_fixtures(raw_oddspapi)
            existing = {(f["player1"].lower(), f["player2"].lower()) for f in fixtures}
            added = 0
            for opf in oddspapi_fixtures:
                key = (opf["player1"].lower(), opf["player2"].lower())
                if key not in existing:
                    fixtures.append(opf)
                    existing.add(key)
                    added += 1
            if added:
                log(f"OddsPapi: {added} matchs supplémentaires ajoutés.", "INFO")
        except Exception as exc:
            log(f"OddsPapi fixtures en échec ({exc}) — ignoré.", "WARN")

    # ── Injection des matchs live ITF/UTR (non couverts par ESPN) ───────────────
    # Les matchs odds-api.io "live" ne sont pas dans ESPN → ils disparaissent de
    # l'onglet "À venir" avant même d'y figurer.  On les injecte ici avec live=True
    # pour qu'ils soient visibles avec le badge 🔴 LIVE dans la liste à venir.
    if odds_api.is_enabled():
        try:
            live_odds_events = odds_api.fetch_live_events()
            live_fixtures = live_api.parse_odds_events_as_fixtures(live_odds_events)
            existing_keys = {(f["player1"].lower(), f["player2"].lower()) for f in fixtures}
            added_live = 0
            for lf in live_fixtures:
                if lf.get("is_doubles"):
                    continue
                key = (lf["player1"].lower(), lf["player2"].lower())
                if key not in existing_keys:
                    lf["live"] = True
                    fixtures.append(lf)
                    existing_keys.add(key)
                    added_live += 1
            if added_live:
                log(f"Inplay inject: {added_live} matchs live ITF/UTR ajoutés à upcoming.", "INFO")
        except Exception as exc:
            log(f"Inplay inject (matchs live ITF/UTR) échoué ({exc}) — ignoré.", "WARN")

    # Filet de sécurité global : quelle que soit la source (API-Tennis, ESPN,
    # odds-api.io, OddsPapi, injection live), un fixture non-live daté d'avant
    # aujourd'hui ne doit jamais atteindre l'app — c'est ce qui produisait des
    # matchs de la veille sur le Dashboard (2026-07-14, voir MASTER_TODO.md
    # #3d). Chaque source a déjà été corrigée individuellement ; ce filtre est
    # une seconde ligne de défense pour qu'une future source avec le même bug
    # ne puisse plus reproduire le symptôme en prod.
    _today_str = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    _before = len(fixtures)
    fixtures = [f for f in fixtures if f.get("live") or f.get("date", "") >= _today_str]
    if len(fixtures) < _before:
        log(f"Filet de sécurité upcoming : {_before - len(fixtures)} fixture(s) daté(s) "
            f"avant aujourd'hui écarté(s) (source non identifiée individuellement).", "WARN")

    # Priorité ATP/WTA avant Challenger/ITF/UTR dans l'ordre de troncature :
    # le cap `limit` (défaut 100) coupe la liste avant la fin, et le volume
    # Challenger/ITF (toujours majoritaire) noyait sinon les matchs ATP/WTA
    # fraîchement ajoutés par OddsPapi. Tri stable -> à priorité égale,
    # l'ordre d'origine (et donc les autres critères déjà appliqués) est conservé.
    def _fixture_prio(f: Dict) -> int:
        return 0 if (f.get("tour") or "").lower() in ("atp", "wta") else 1
    fixtures = sorted(fixtures, key=_fixture_prio)

    # Cache météo par tournoi pour éviter les appels répétés
    _weather_cache: Dict[str, Any] = {}

    out = []
    for f in fixtures:
        if f["is_doubles"]:
            continue
        n1, n2 = _resolve(f["player1"]), _resolve(f["player2"])

        # Enrichissement heure : si ESPN ne connaît pas l'heure (00:00 ou 06:00 =
        # placeholder API-Tennis pour « horaire non publié »), on complète via odds-api.io.
        match_time = f["time"]
        _placeholder = not match_time or match_time in ("00:00", "06:00")
        if _placeholder and odds_time_index:
            from .namematch import split_name
            _, l1 = split_name(f["player1"])
            _, l2 = split_name(f["player2"])
            if l1 and l2:
                enriched_time = odds_time_index.get(frozenset((l1, l2)))
                if enriched_time:
                    match_time = enriched_time
        if _placeholder and (not match_time or match_time in ("00:00", "06:00")):
            match_time = "TBD"

        item = {
            "player1_raw": f["player1"], "player2_raw": f["player2"],
            "tournament": f["tournament"], "round": f["round"],
            "date": f["date"], "time": match_time, "live": f["live"],
            "tour": f["tour"], "predictable": bool(n1 and n2),
            "source": f.get("source", "api-tennis"),
        }
        if n1 and n2:
            # Guard: ne pas croiser ATP et WTA (ELO non comparables)
            t1 = (_MEM.get("players") or {}).get(n1, {}).get("tour", "")
            t2 = (_MEM.get("players") or {}).get(n2, {}).get("tour", "")
            if t1 and t2 and {t1, t2} == {"atp", "wta"}:
                item["predictable"] = False
                item["prediction_skip"] = "cross-gender"
                continue
            surface = _surface_for(f["tournament"], f["date"])
            f1 = features.feature_vector(features.get_profile(_MEM, n1))
            f2 = features.feature_vector(features.get_profile(_MEM, n2))
            r = predictor.predict(_MEM, n1, f1, n2, f2, surface=surface)
            # ITF/inconnu + joueurs peu vus → prédiction non fiable
            _tour_raw = (f.get("tour") or "").lower()
            _n1_matches = int((_MEM.get("players") or {}).get(n1, {}).get("n", 0))
            _n2_matches = int((_MEM.get("players") or {}).get(n2, {}).get("n", 0))
            _itf_unreliable = (_tour_raw in ("", "itf") and min(_n1_matches, _n2_matches) < 15)
            if _itf_unreliable:
                r["confidence"] = min(r.get("confidence", 0.0), 0.15)
                r["confidence_label"] = "très faible (ITF / données insuffisantes)"
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

            # ── Contexte pari : favori modèle vs marché ───────────────────────
            odds_item = item.get("odds")
            if odds_item and odds_item.get("home_odds") and odds_item.get("away_odds"):
                oh, oa = float(odds_item["home_odds"]), float(odds_item["away_odds"])
                mkt_fav = n1 if oh < oa else n2
                mkt_fav_prob = round((1.0 / oh if mkt_fav == n1 else 1.0 / oa) * 100, 1)
                model_fav = r.get("favorite")
                model_fav_prob = r["prob1"] if model_fav == n1 else r["prob2"]
                agree = (mkt_fav == model_fav)

                if agree:
                    edge_pct = round(model_fav_prob / 100.0 - (1.0 / (oh if mkt_fav == n1 else oa)), 4)
                    if edge_pct >= 0.04:
                        bet_tag = "good_bet"
                        bet_label = "✅ Good bet — modèle + marché accordés, edge positif"
                    elif edge_pct >= 0:
                        bet_tag = "neutral"
                        bet_label = "📊 Favori bookmaker — peu d'edge"
                    else:
                        bet_tag = "bad_bet"
                        bet_label = "⚠️ Bad bet — marché surpaye le favori"
                else:
                    edge_pct = round(model_fav_prob / 100.0 - (1.0 / (oh if model_fav == n1 else oa)), 4)
                    bet_tag = "value_underdog"
                    bet_label = f"💎 Value underdog — modèle: {model_fav}, marché: {mkt_fav}"

                item["bet_context"] = {
                    "model_fav": model_fav,
                    "model_fav_prob": model_fav_prob,
                    "market_fav": mkt_fav,
                    "market_fav_prob": mkt_fav_prob,
                    "agree": agree,
                    "edge_pct": round(edge_pct * 100, 1),
                    "tag": bet_tag,
                    "label": bet_label,
                }

            # Météo : uniquement pour les tournois outdoor connus
            tourn_key = f["tournament"].lower()
            if tourn_key not in _weather_cache:
                _weather_cache[tourn_key] = weather.fetch_weather(
                    f["tournament"], surface or "")
            w = _weather_cache[tourn_key]
            if w:
                item["weather"] = w

            # ── Analyse météo + crowd + honeypot ─────────────────────────────
            if n1 and n2:
                try:
                    from . import weather_profile as wp
                    p1_prof = features.get_profile(_MEM, n1)
                    p2_prof = features.get_profile(_MEM, n2)
                    wa = wp.analyze(_MEM, n1, p1_prof, n2, p2_prof,
                                    w, f["tournament"], surface or "hard")
                    item["weather_analysis"] = wa
                except Exception as exc:
                    log(f"weather_profile.analyze échoué pour {n1} vs {n2} ({exc}) — ignoré.", "WARN")

            # ── H2H résumé rapide ─────────────────────────────────────────────
            try:
                h2h_rows = db.head_to_head(n1, n2)
                hw1 = sum(1 for r in h2h_rows if r["winner"] == n1)
                hw2 = sum(1 for r in h2h_rows if r["winner"] == n2)
                item["h2h"] = {
                    "wins1": hw1, "wins2": hw2, "total": hw1 + hw2,
                    "last_winner": h2h_rows[0]["winner"] if h2h_rows else None,
                }
            except Exception as exc:
                log(f"H2H échoué pour {n1} vs {n2} ({exc}) — ignoré.", "WARN")

            # ── Ranking ───────────────────────────────────────────────────────
            item["rank1"] = _MEM["players"].get(n1, {}).get("rank")
            item["rank2"] = _MEM["players"].get(n2, {}).get("rank")
        out.append(item)
        if len(out) >= limit:
            break
    result = {"count": len(out), "matches": out}
    _upcoming_cache[cache_key] = result
    _upcoming_cache_ts = _t.time()
    return jsonify(result)


@app.get("/api/recommendations")
def api_recommendations():
    """Recommandations personnalisées : matchs à venir triés selon l'usage du
    compte (joueurs consultés, picks pris, surfaces préférées).

    Réutilise /api/upcoming tel quel (même pipeline multi-source, même cache)
    en appelant directement la vue Flask plutôt que de dupliquer la logique
    de fetch — pas de round-trip HTTP, même contexte de requête. Conséquence
    assumée : cet appel direct consomme aussi le quota de rate-limit de
    /api/upcoming (20/min) pour ce client — cohérent, puisque c'est le même
    coût réel (appels odds-api.io) qui est protégé, pas l'endpoint en soi.
    """
    limit = min(int(request.args.get("limit", 10)), 30)
    upcoming_data = api_upcoming().get_json()
    matches = upcoming_data.get("matches", []) if upcoming_data else []
    return jsonify(recommendations.build_recommendations(matches, limit=limit))


@app.get("/api/live")
@limiter.limit("20 per minute")  # protège le quota odds-api.io partagé (100 req/h)
def api_live():
    """Matchs tennis EN COURS : score, jeu courant, serve, odds live, prédiction pré-match.

    Rafraîchissement côté Android recommandé : 30s.
    """
    if not odds_api.is_enabled():
        return jsonify({"error": "ODDS_API_KEY absente"}), 503

    live_events = odds_api.fetch_live_events() or []
    # Priorité ATP/WTA → ITF en dernier ; cap à 30 pour éviter les timeouts
    def _live_prio(ev):
        lg = (ev.get("league") or {}).get("name", "") if isinstance(ev.get("league"), dict) else str(ev.get("league", ""))
        if "ATP" in lg or "WTA" in lg: return 0
        if "Challenger" in lg or "ITF" in lg: return 2
        return 1
    live_events = sorted(live_events, key=_live_prio)[:30]

    # Pré-charger les cotes live en une seule passe (max 5 matchs ATP/WTA)
    _odds_fetched: dict = {}
    _odds_budget = 5
    for _ev in live_events:
        if _odds_budget <= 0:
            break
        _lg_n = (_ev.get("league") or {}).get("name", "") if isinstance(_ev.get("league"), dict) else str(_ev.get("league", ""))
        if "ATP" in _lg_n or "WTA" in _lg_n:
            try:
                _mw = odds_api.fetch_match_winner(_ev["id"], ttl=60)
                if _mw:
                    _odds_fetched[str(_ev["id"])] = _mw
                    _odds_budget -= 1
            except Exception as exc:
                log(f"fetch_match_winner échoué pour event {_ev.get('id')} ({exc}) — ignoré.", "WARN")

    out = []
    for e in live_events:
        home_raw = e.get("home", "")
        away_raw = e.get("away", "")
        n1 = _resolve(home_raw)
        n2 = _resolve(away_raw)

        # ── Score ────────────────────────────────────────────────────────────
        scores = e.get("scores") or {}
        periods = scores.get("periods") or {}
        sets_home = int(scores.get("home") or 0)
        sets_away = int(scores.get("away") or 0)

        # Sets détaillés : [{"h":6,"a":3}, {"h":2,"a":4}, ...]
        set_scores = []
        for i in range(1, 8):
            p = periods.get(f"p{i}")
            if p and (p.get("home") is not None or p.get("away") is not None):
                set_scores.append({"h": int(p.get("home") or 0),
                                   "a": int(p.get("away") or 0)})

        cg = periods.get("currentgame") or {}
        game_h = str(cg.get("home", "")) if cg else ""
        game_a = str(cg.get("away", "")) if cg else ""

        # ── Horloge ──────────────────────────────────────────────────────────
        clock = e.get("clock") or {}
        serve = clock.get("serve", "")          # "home" | "away"
        status_detail = clock.get("statusDetail", "")
        minute = int(clock.get("minute") or 0)

        # ── Prédiction pré-match ──────────────────────────────────────────────
        prediction = None
        _live_lg = e.get("league") or {}
        _live_league = _live_lg if isinstance(_live_lg, str) else _live_lg.get("name", "")
        _live_surf = e.get("surface") or config.surface_from_league(_live_league) or None
        if n1 and n2:
            try:
                f1 = features.feature_vector(features.get_profile(_MEM, n1))
                f2 = features.feature_vector(features.get_profile(_MEM, n2))
                r = predictor.predict(_MEM, n1, f1, n2, f2, surface=_live_surf)
                pm1_prematch = _calib(_set_to_match_prob(r["prob1"] / 100.0))
                # In-play : ré-ajuste au score en cours (sets gagnés/perdus),
                # pas juste la proba pré-match figée. Voir predictor.inplay_match_prob.
                _p_set_calib = predictor.invert_set_to_match_prob(pm1_prematch)
                _bo = _best_of_for(e.get("tour") or _live_league, _live_league)
                pm1 = predictor.inplay_match_prob(_p_set_calib, sets_home, sets_away, best_of=_bo)
                prediction = {
                    "player1": n1, "player2": n2,
                    "prob1": round(pm1 * 100, 1),
                    "prob2": round((1 - pm1) * 100, 1),
                    # Favori recalculé sur la proba in-play (pas la pré-match r["favorite"]) —
                    # sinon il peut contredire prob1/prob2 une fois le score pris en compte.
                    "favorite": n1 if pm1 >= 0.5 else n2,
                    "confidence": r["confidence"],
                    "confidence_label": r["confidence_label"],
                }
                # Historique pour le graphique d'évolution (écran Live).
                try:
                    db.record_live_prob(str(e["id"]), round(pm1 * 100, 1),
                                       sets_home, sets_away, minute)
                    hist = db.live_prob_history(str(e["id"]))
                    prediction["prob_history"] = [
                        {"ts": h["ts"], "prob1": h["prob1"], "minute": h["minute"],
                         "sets": f"{h['sets_home']}-{h['sets_away']}"}
                        for h in hist
                    ]
                except Exception as exc:  # noqa: BLE001
                    log(f"record_live_prob/history échoué pour event {e.get('id')} ({exc}) — ignoré.", "WARN")
            except Exception as exc:  # noqa: BLE001
                log(f"Prédiction in-play échouée pour event {e.get('id')} ({exc}) — ignoré.", "WARN")

        # ── Cotes live (pré-chargées pour ATP/WTA uniquement) ────────────────
        live_mw = _odds_fetched.get(str(e["id"]))

        _lg = e.get("league") or {}
        league = _lg if isinstance(_lg, str) else _lg.get("name", "")
        out.append({
            "event_id": e["id"],
            "player1": home_raw, "player2": away_raw,
            "player1_resolved": n1, "player2_resolved": n2,
            "league": league,
            "surface": _live_surf,
            "sets_home": sets_home, "sets_away": sets_away,
            "set_scores": set_scores,
            "game_home": game_h, "game_away": game_a,
            "serve": serve,
            "status_detail": status_detail,
            "minute": minute,
            "prediction": prediction,
            "live_odds": {
                "home": live_mw["home_odds"] if live_mw else None,
                "away": live_mw["away_odds"] if live_mw else None,
                "books": live_mw["books"] if live_mw else [],
            } if live_mw else None,
        })

    # Matchs avec cotes live en premier, puis par durée décroissante
    out.sort(key=lambda m: (m["live_odds"] is None, -m["minute"]))

    # ── Auto-settlement des picks en attente ─────────────────────────────────
    try:
        live_ids = {str(m["event_id"]) for m in out}
        settled = db.auto_settle_picks(live_ids)
        if settled:
            log(f"Auto-settled {len(settled)} pick(s): {[s['pick'] for s in settled]}", "INFO")
    except Exception as _e:
        log(f"auto_settle_picks error: {_e}", "WARN")

    return jsonify({"count": len(out), "matches": out})


@app.get("/api/inplay/best")
def api_inplay_best():
    """Meilleur pick parmi les matchs live selon notre modèle + base de données.

    Score = confiance × max(edge_vs_marché, 0).
    Sans cotes live : score = confiance × 0.5 (demi-poids).
    Retourne les 3 meilleurs candidats triés par score décroissant.
    """
    if not odds_api.is_enabled():
        return jsonify({"error": "ODDS_API_KEY absente"}), 503

    live_events = odds_api.fetch_live_events()
    candidates = []

    for e in live_events:
        home_raw = e.get("home", "")
        away_raw = e.get("away", "")
        n1 = _resolve(home_raw) or home_raw.strip()
        n2 = _resolve(away_raw) or away_raw.strip()
        if not n1 or not n2:
            continue

        _ip_lg = e.get("league") or {}
        _ip_league = _ip_lg if isinstance(_ip_lg, str) else _ip_lg.get("name", "")
        _ip_surf = e.get("surface") or config.surface_from_league(_ip_league) or None
        try:
            f1 = features.feature_vector(features.get_profile(_MEM, n1))
            f2 = features.feature_vector(features.get_profile(_MEM, n2))
            r = predictor.predict(_MEM, n1, f1, n2, f2, surface=_ip_surf)
        except Exception as exc:
            log(f"Prédiction échouée pour {n1} vs {n2} (inplay/best) ({exc}) — candidat ignoré.", "WARN")
            continue

        conf = r.get("confidence", 0.0)
        if conf < 0.20:
            continue

        scores = e.get("scores") or {}
        _ip_sets_home = int(scores.get("home") or 0)
        _ip_sets_away = int(scores.get("away") or 0)

        pm1_prematch = _calib(_set_to_match_prob(r["prob1"] / 100.0))
        # In-play : ré-ajuste au score en cours plutôt que la proba pré-match figée.
        _p_set_calib = predictor.invert_set_to_match_prob(pm1_prematch)
        _ip_bo = _best_of_for(e.get("tour") or _ip_league, _ip_league)
        pm1 = predictor.inplay_match_prob(_p_set_calib, _ip_sets_home, _ip_sets_away, best_of=_ip_bo)
        pm2 = 1.0 - pm1

        # Cotes live (1 req par match, on limite à 20 matchs)
        live_mw = None
        if len(candidates) < 20:
            try:
                live_mw = odds_api.fetch_match_winner(e["id"], ttl=60)
            except Exception as exc:
                log(f"fetch_match_winner échoué pour event {e.get('id')} (inplay/best) ({exc}) — ignoré.", "WARN")

        edge: Optional[float] = None
        fav_odds: Optional[float] = None
        if live_mw and live_mw.get("home_odds") and live_mw.get("away_odds"):
            ho, ao = live_mw["home_odds"], live_mw["away_odds"]
            if pm1 >= pm2:
                edge = pm1 - live_mw["home_prob"]
                fav_odds = ho
            else:
                edge = pm2 - live_mw["away_prob"]
                fav_odds = ao
            score = conf * max(edge, 0.0)
        else:
            score = conf * 0.5

        periods = scores.get("periods") or {}
        set_scores = []
        for i in range(1, 8):
            p = periods.get(f"p{i}")
            if p and (p.get("home") is not None or p.get("away") is not None):
                set_scores.append({"h": int(p.get("home") or 0), "a": int(p.get("away") or 0)})

        _lg = e.get("league") or {}
        league = _lg if isinstance(_lg, str) else _lg.get("name", "")
        clock = e.get("clock") or {}

        candidates.append({
            "event_id": e["id"],
            "player1": home_raw, "player2": away_raw,
            "player1_resolved": n1, "player2_resolved": n2,
            "league": league,
            "sets_home": int(scores.get("home") or 0),
            "sets_away": int(scores.get("away") or 0),
            "set_scores": set_scores,
            "minute": int(clock.get("minute") or 0),
            "status_detail": clock.get("statusDetail", ""),
            "prediction": {
                "player1": n1, "player2": n2,
                "prob1": round(pm1 * 100, 1),
                "prob2": round(pm2 * 100, 1),
                "favorite": n1 if pm1 >= pm2 else n2,
                "confidence": round(conf, 3),
                "confidence_label": r.get("confidence_label", ""),
            },
            "live_odds": {
                "home": live_mw["home_odds"] if live_mw else None,
                "away": live_mw["away_odds"] if live_mw else None,
                "books": live_mw["books"] if live_mw else [],
            } if live_mw else None,
            "edge_pct": round(edge * 100, 1) if edge is not None else None,
            "fav_odds": fav_odds,
            "score": round(score, 4),
        })

    candidates.sort(key=lambda c: -c["score"])
    return jsonify({
        "count": len(candidates),
        "best": candidates[:3],
        "note": "Score = confiance × edge_vs_marché. Haut score = meilleur pick selon la DB.",
    })


@app.get("/api/inplay/markets")
def api_inplay_markets():
    """Marchés inplay dérivés par joueur : gagnant set, O/U jeux, O/U aces.

    Pour chaque match live, calcule 3 marchés depuis les profils joueurs EMA :
    - set_winner   : qui va gagner le set en cours (depuis le score + serve EMA)
    - total_games  : Over/Under 9.5 jeux par set (serve haute → plus de jeux)
    - aces         : Over/Under aces restants (serve haute → plus d'aces)
    """
    if not odds_api.is_enabled():
        return jsonify({"error": "ODDS_API_KEY absente"}), 503

    live_events = odds_api.fetch_live_events()
    result = []

    for e in live_events[:20]:
        home_raw = e.get("home", "")
        away_raw = e.get("away", "")
        n1 = _resolve(home_raw) or home_raw.strip()
        n2 = _resolve(away_raw) or away_raw.strip()
        if not n1 or not n2:
            continue

        # Marchés réels Betfair Exchange (Spread + Totals) — TTL 60s
        event_id = e.get("id")
        bk_markets = odds_api.fetch_live_game_markets(event_id) if event_id else {}

        p1 = features.get_profile(_MEM, n1)
        p2 = features.get_profile(_MEM, n2)

        serve1 = float(p1.get("serve", 0.5))
        serve2 = float(p2.get("serve", 0.5))
        avg_serve = (serve1 + serve2) / 2

        # Score actuel
        scores = e.get("scores") or {}
        periods = scores.get("periods") or {}
        sets_home = int(scores.get("home") or 0)
        sets_away = int(scores.get("away") or 0)
        current_set = sets_home + sets_away + 1
        current_period = periods.get(f"p{current_set}") or {}
        games_h = int(current_period.get("home") or 0)
        games_a = int(current_period.get("away") or 0)

        _lg = e.get("league") or {}
        league = _lg if isinstance(_lg, str) else _lg.get("name", "")
        clock = e.get("clock") or {}
        minute = int(clock.get("minute") or 0)

        set_scores_display = []
        for i in range(1, 8):
            pp = periods.get(f"p{i}")
            if pp and (pp.get("home") is not None or pp.get("away") is not None):
                set_scores_display.append(f"{pp.get('home', 0)}-{pp.get('away', 0)}")

        markets = []

        # ── Market 0 : Vainqueur du match (modèle calibré, pas une heuristique
        # comme les marchés ci-dessous) — même pipeline que /api/live et
        # /api/inplay/best, jamais exposé jusqu'ici dans la liste de marchés.
        try:
            _mw_f1 = features.feature_vector(p1)
            _mw_f2 = features.feature_vector(p2)
            _mw_surf = e.get("surface") or config.surface_from_league(league) or None
            _mw_r = predictor.predict(_MEM, n1, _mw_f1, n2, _mw_f2, surface=_mw_surf)
            _mw_pm1_prematch = _calib(_set_to_match_prob(_mw_r["prob1"] / 100.0))
            _mw_p_set_calib = predictor.invert_set_to_match_prob(_mw_pm1_prematch)
            _mw_bo = _best_of_for(e.get("tour") or league, league)
            _mw_pm1 = predictor.inplay_match_prob(_mw_p_set_calib, sets_home, sets_away, best_of=_mw_bo)
            if _mw_pm1 >= 0.5:
                mw_name, mw_prob = n1, _mw_pm1
            else:
                mw_name, mw_prob = n2, 1.0 - _mw_pm1
            mw_conf = "Forte" if mw_prob > 0.70 else "Moyenne" if mw_prob > 0.57 else "Faible"
            live_mw = odds_api.fetch_match_winner(event_id, ttl=60) if event_id else None
            mw_odds = None
            if live_mw and live_mw.get("home_odds") and live_mw.get("away_odds"):
                mw_odds = live_mw["home_odds"] if mw_name == n1 else live_mw["away_odds"]
            markets.append({
                "type": "match_winner",
                "label": "Vainqueur du match",
                "pick": mw_name,
                "prob": round(mw_prob * 100, 1),
                "confidence": mw_conf,
                "rationale": f"Modèle calibré · sets {sets_home}-{sets_away} · bo{_mw_bo}",
                "odds": mw_odds,
                "has_real_odds": mw_odds is not None,
            })
        except Exception as exc:
            log(f"Marché 'Vainqueur du match' échoué ({exc}) — omis.", "WARN")

        # ── Market 1 : Gagnant set actuel ──────────────────────────────────────
        lead = games_h - games_a
        # serve élevée → le leader tient plus facilement → probabilité +robuste
        set_prob_h = 0.5 + lead * (0.07 + avg_serve * 0.05)
        set_prob_h = max(0.10, min(0.90, set_prob_h))
        if set_prob_h >= 0.5:
            sw_name, sw_prob = n1, set_prob_h
        else:
            sw_name, sw_prob = n2, 1.0 - set_prob_h
        sw_conf = "Forte" if sw_prob > 0.70 else "Moyenne" if sw_prob > 0.57 else "Faible"
        markets.append({
            "type": "set_winner",
            "label": f"Gagnant set {current_set}",
            "pick": sw_name,
            "prob": round(sw_prob * 100, 1),
            "confidence": sw_conf,
            "rationale": f"Score {games_h}-{games_a} · service moy. {avg_serve:.2f}",
        })

        # ── Market 2 : Prochain set (winner) ──────────────────────────────────
        # Avantage sets gagnés → momentum
        set_lead = sets_home - sets_away
        next_prob_h = 0.5 + set_lead * 0.06 + (serve1 - serve2) * 0.15
        next_prob_h = max(0.15, min(0.85, next_prob_h))
        if next_prob_h >= 0.5:
            ns_name, ns_prob = n1, next_prob_h
        else:
            ns_name, ns_prob = n2, 1.0 - next_prob_h
        ns_conf = "Forte" if ns_prob > 0.70 else "Moyenne" if ns_prob > 0.57 else "Faible"
        markets.append({
            "type": "next_set",
            "label": f"Gagnant set {current_set + 1}",
            "pick": ns_name,
            "prob": round(ns_prob * 100, 1),
            "confidence": ns_conf,
            "rationale": f"Sets {sets_home}-{sets_away} · serve diff {serve1 - serve2:+.2f}",
        })

        # ── Market 3 : Tiebreak set actuel O/U 9.5 ──────────────────────────
        # Serve élevée → peu de breaks → tiebreak probable
        threshold_games = 9.5
        raw_prob_over = 0.50 + (avg_serve - 0.50) * 0.80
        raw_prob_over = max(0.30, min(0.80, raw_prob_over))
        if raw_prob_over >= 0.50:
            tg_pick = f"OVER {threshold_games}"
            tg_prob = raw_prob_over
        else:
            tg_pick = f"UNDER {threshold_games}"
            tg_prob = 1.0 - raw_prob_over
        tg_conf = "Forte" if tg_prob > 0.68 else "Moyenne" if tg_prob > 0.57 else "Faible"
        markets.append({
            "type": "total_games",
            "label": f"Jeux set {current_set} O/U {threshold_games}",
            "pick": tg_pick,
            "prob": round(tg_prob * 100, 1),
            "confidence": tg_conf,
            "rationale": f"Serve moyen {avg_serve:.2f} · tiebreak set {current_set} probable si serve haute",
        })

        sets_remaining = max(1, 3 - sets_home - sets_away)

        # ── Market 4 : Aces O/U ───────────────────────────────────────────────
        # Calibration ATP réelle : serve=0.62 ≈ 8-10 aces/match, serve=0.75 → ~15
        aces_per_match = max(1.0, (avg_serve - 0.40) * 35.0)  # ~3.5@0.5, ~7.7@0.62, ~12@0.74
        expected_aces = aces_per_match * (sets_remaining / 2.2)  # proratisé sets restants
        threshold_aces = max(2.5, round(expected_aces * 2) / 2)
        raw_prob_over_aces = 0.50 + (expected_aces - threshold_aces) * 0.10
        raw_prob_over_aces = max(0.30, min(0.82, raw_prob_over_aces))
        if raw_prob_over_aces >= 0.50:
            ac_pick = f"OVER {threshold_aces}"
            ac_prob = raw_prob_over_aces
        else:
            ac_pick = f"UNDER {threshold_aces}"
            ac_prob = 1.0 - raw_prob_over_aces
        ac_conf = "Forte" if ac_prob > 0.68 else "Moyenne" if ac_prob > 0.57 else "Faible"
        markets.append({
            "type": "aces",
            "label": f"Aces O/U {threshold_aces}",
            "pick": ac_pick,
            "prob": round(ac_prob * 100, 1),
            "confidence": ac_conf,
            "rationale": f"~{expected_aces:.1f} aces attendus ({sets_remaining} sets restants · serve {avg_serve:.2f})",
        })

        # ── Market 5 : Total jeux match (ligne Betfair réelle si dispo) ─────────
        best_tot = bk_markets.get("best_totals")
        if best_tot:
            # Ligne réelle Betfair Exchange
            threshold_tgm = best_tot["hdp"]
            impl_over = best_tot["implied_over_prob"]
            # Notre modèle : serve haute → plus de jeux
            model_over = 0.50 + (avg_serve - 0.5) * 0.40
            model_over = max(0.20, min(0.85, model_over))
            # Edge = notre prob - prob implicite bookmaker
            edge_tgm = model_over - impl_over
            if model_over >= 0.50:
                tgm_pick = f"OVER {threshold_tgm}"
                tgm_prob = model_over
            else:
                tgm_pick = f"UNDER {threshold_tgm}"
                tgm_prob = 1.0 - model_over
            tgm_rationale = (f"Betfair · impl={impl_over*100:.0f}% · "
                             f"modèle={model_over*100:.0f}% · edge={edge_tgm*100:+.1f}%")
            tgm_odds = best_tot["over_odds"] if model_over >= 0.50 else best_tot["under_odds"]
        else:
            # Fallback heuristique si pas de cotes Betfair disponibles
            games_per_set = 9.5 + (avg_serve - 0.5) * 3.0
            expected_total_games = 2.2 * games_per_set
            threshold_tgm = round(expected_total_games * 2) / 2
            threshold_tgm = max(17.5, min(27.5, threshold_tgm))
            raw_over = 0.50 + (avg_serve - 0.5) * 0.40
            raw_over = max(0.30, min(0.80, raw_over))
            if raw_over >= 0.50:
                tgm_pick = f"OVER {threshold_tgm}"
                tgm_prob = raw_over
            else:
                tgm_pick = f"UNDER {threshold_tgm}"
                tgm_prob = 1.0 - raw_over
            tgm_rationale = f"~{expected_total_games:.1f}j attendus (serve {avg_serve:.2f})"
            tgm_odds = None
        tgm_conf = "Forte" if tgm_prob > 0.68 else "Moyenne" if tgm_prob > 0.57 else "Faible"
        markets.append({
            "type": "total_points",
            "label": f"Total jeux O/U {threshold_tgm}",
            "pick": tgm_pick,
            "prob": round(tgm_prob * 100, 1),
            "confidence": tgm_conf,
            "rationale": tgm_rationale,
            "odds": tgm_odds,
            "has_real_odds": best_tot is not None,
        })

        # ── Market 6 : Total fautes doubles O/U ───────────────────────────────
        # Calibration ATP : serve=0.62 ≈ 4-5 DF/match, serve=0.50 → ~6-7 DF/match
        df_per_match = max(1.0, (0.85 - avg_serve) * 18.0)  # ~6.3@0.5, ~4.1@0.62, ~1.8@0.75
        expected_df = df_per_match * (sets_remaining / 2.2)
        threshold_df = max(1.5, round(expected_df * 2) / 2)  # arrondi à 0.5
        raw_prob_over_df = 0.50 + (expected_df - threshold_df) * 0.10
        raw_prob_over_df = max(0.30, min(0.80, raw_prob_over_df))
        if raw_prob_over_df >= 0.50:
            df_pick = f"OVER {threshold_df}"
            df_prob = raw_prob_over_df
        else:
            df_pick = f"UNDER {threshold_df}"
            df_prob = 1.0 - raw_prob_over_df
        df_conf = "Forte" if df_prob > 0.68 else "Moyenne" if df_prob > 0.57 else "Faible"
        markets.append({
            "type": "double_faults",
            "label": f"Dbl fautes O/U {threshold_df}",
            "pick": df_pick,
            "prob": round(df_prob * 100, 1),
            "confidence": df_conf,
            "rationale": f"~{expected_df:.1f} DF attendues · serve {avg_serve:.2f}",
        })

        # ── Market 7 : Handicap jeux (ligne Betfair réelle si dispo) ─────────
        best_sprd = bk_markets.get("best_spread")
        set_lead = sets_home - sets_away
        prob_h_hcp = 0.5 + (serve1 - serve2) * 0.35 + set_lead * 0.04
        prob_h_hcp = max(0.15, min(0.85, prob_h_hcp))
        if prob_h_hcp >= 0.5:
            hcp_fav, hcp_model_prob = n1, prob_h_hcp
        else:
            hcp_fav, hcp_model_prob = n2, 1.0 - prob_h_hcp
        if best_sprd:
            hcp_line = best_sprd["hdp"]
            impl_hcp = best_sprd["implied_home_prob"] if hcp_fav == n1 else 1 - best_sprd["implied_home_prob"]
            edge_hcp = hcp_model_prob - impl_hcp
            hcp_cover_prob = hcp_model_prob
            hcp_rationale = (f"Betfair · impl={impl_hcp*100:.0f}% · "
                             f"modèle={hcp_model_prob*100:.0f}% · edge={edge_hcp*100:+.1f}%")
            hcp_odds = best_sprd["home_odds"] if hcp_fav == n1 else best_sprd["away_odds"]
        else:
            expected_margin = (hcp_model_prob - 0.5) * 16
            hcp_line = max(0.5, round(expected_margin * 2) / 2)
            hcp_cover_prob = 0.50 + (hcp_model_prob - 0.5) * 0.55
            hcp_cover_prob = max(0.35, min(0.80, hcp_cover_prob))
            hcp_rationale = (f"Serve diff {serve1 - serve2:+.2f} · sets {sets_home}-{sets_away} "
                             f"· marge ~{expected_margin:.1f}j")
            hcp_odds = None
        hcp_conf = "Forte" if hcp_cover_prob > 0.68 else "Moyenne" if hcp_cover_prob > 0.57 else "Faible"
        markets.append({
            "type": "handicap",
            "label": f"Hcp jeux -{hcp_line}",
            "pick": f"{hcp_fav} -{hcp_line}",
            "prob": round(hcp_cover_prob * 100, 1),
            "confidence": hcp_conf,
            "rationale": hcp_rationale,
            "odds": hcp_odds,
            "has_real_odds": best_sprd is not None,
        })

        markets.sort(key=lambda m: -m["prob"])

        result.append({
            "event_id": e["id"],
            "player1": home_raw,
            "player2": away_raw,
            "player1_resolved": n1,
            "player2_resolved": n2,
            "league": league,
            "sets_home": sets_home,
            "sets_away": sets_away,
            "score_display": ", ".join(set_scores_display),
            "minute": minute,
            "markets": markets,
        })

    # Tri : match avec le meilleur marché en tête
    result.sort(key=lambda x: max((m["prob"] for m in x["markets"]), default=0), reverse=True)
    return jsonify({"count": len(result), "matches": result})


@app.get("/api/value")
@limiter.limit("20 per minute")  # protège le quota odds-api.io partagé (100 req/h)
def api_value():
    """Compare le modèle au marché et calcule l'EV (espérance de gain) réelle.

    EV(parier J) = proba_match_modèle(J) × cote(J) − 1.  EV > 0 = value (+).
    min_confidence (float, défaut 0.55) : ignore les picks sous ce seuil de confiance.
    min_ev (float, défaut 8.0) : EV minimum (%) pour qu'un pick soit tagué 'value'.
    """
    limit = min(int(request.args.get("limit", 10)), 30)
    min_conf = float(request.args.get("min_confidence", 0.55))
    min_ev = max(float(request.args.get("min_ev", 8.0)), 5.0)   # plancher absolu 5%
    # Cap dur à 5.0 : données historiques montrent ROI négatif sur cotes > 5.
    max_odds = min(float(request.args.get("max_odds", 5.0)), 5.0)
    # Ratio max modèle/marché : si modèle > 3× la probabilité implicite, pick rejeté.
    # Évite les picks aberrants (EV > 100% typiquement) dus à l'overconfidence sur longshots.
    max_prob_ratio = 3.0
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
        _lg_s = e.get("league") or {}
        slug = "" if isinstance(_lg_s, str) else _lg_s.get("slug", "")
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
    import datetime as _dt
    _now_utc = _dt.datetime.now(_dt.timezone.utc)
    # Fenêtre de pick : 0h → 8h avant le coup d'envoi.
    # Les lignes à >8h sont trop "souples" (early market) → CLV très négatif.
    _MAX_HOURS_AHEAD = 8.0

    out = []
    for e in events:
        n1, n2 = _resolve(e.get("home", "")), _resolve(e.get("away", ""))
        if not n1 or not n2:
            continue
        # Filtre temporel : ignore les matchs trop lointains (lignes non ajustées)
        _e_date = e.get("commence_time") or e.get("date") or ""
        if _e_date:
            try:
                _e_dt = _dt.datetime.fromisoformat(str(_e_date).replace("Z", "+00:00"))
                _hours_ahead = (_e_dt - _now_utc).total_seconds() / 3600
                if _hours_ahead > _MAX_HOURS_AHEAD or _hours_ahead < -3.0:
                    continue  # trop lointain ou déjà commencé depuis >3h
            except Exception as exc:
                log(f"Parsing date événement échoué ({_e_date!r}: {exc}) — filtre temporel ignoré.", "WARN")
        if odds_calls >= MAX_ODDS_CALLS:
            break
        mw = odds_api.fetch_match_winner(e["id"])
        odds_calls += 1
        if not mw:
            continue
        # Rejeter les matchs cross-genre (ITF mixte → picks impossibles)
        t1 = (_MEM.get("players") or {}).get(n1, {}).get("tour", "")
        t2 = (_MEM.get("players") or {}).get(n2, {}).get("tour", "")
        if t1 and t2 and {t1, t2} == {"atp", "wta"}:
            continue
        f1 = features.feature_vector(features.get_profile(_MEM, n1))
        f2 = features.feature_vector(features.get_profile(_MEM, n2))
        _ev_surf = e.get("surface") or config.surface_from_league(
            (e.get("league") or {}).get("name", "") if isinstance(e.get("league"), dict)
            else str(e.get("league", ""))
        )
        r = predictor.predict(_MEM, n1, f1, n2, f2, surface=_ev_surf or None)

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

        # Sélection du meilleur côté.
        # model_beats_mkt supprimé quand _MKT_W=0 : avec w=0, pm1 est compressé
        # vers 50% par Platt (a≈0.21) → filtre presque toujours False sur les favs
        # → rejette de bons picks de line-shopping. On garde un check direction
        # uniquement si le modèle contribue réellement (w > 0.05).
        if _MKT_W > 0.05:
            model_beats_mkt1 = pm1 > mw["home_prob"]
            model_beats_mkt2 = pm2 > mw["away_prob"]
        else:
            model_beats_mkt1 = model_beats_mkt2 = True  # pure line-shopping

        if ev1 >= ev2:
            best_side, best_ev = n1, ev1
            if not model_beats_mkt1:
                _rej_mkt += 1; continue
        else:
            best_side, best_ev = n2, ev2
            if not model_beats_mkt2:
                _rej_mkt += 1; continue

        # Capture la cote du favori du modèle (pour le ROI au settlement).
        if r["favorite"] is not None:
            fav_odds = ho if r["favorite"] == n1 else ao
            try:
                db.log_bet(e.get("date", ""), n1, n2, r["favorite"], fav_odds)
            except Exception as exc:  # noqa: BLE001
                log(f"db.log_bet échoué pour {n1} vs {n2} ({exc}) — pari non archivé.", "WARN")

        # EV en % pour filtrage et affichage.
        best_ev_pct = round(best_ev * 100, 1)
        pick_odds_check = ho if best_side == n1 else ao

        # Zone EV 12-18% : historiquement 2W/9L (14% WR) toutes cotes confondues → skip.
        # Données : 16 picks en 12-18% EV, avg CLV -25%, WR 12.5%. La restriction
        # précédente (odds > 2.8 seulement) était trop étroite — étendu à toutes cotes.
        _dead_zone = (12.0 <= best_ev_pct < 18.0)
        # Plancher 1.40 : cotes très basses = overcertitude modèle, aucune valeur réelle.
        _below_floor = pick_odds_check < 1.40
        _leag_raw = e.get("league") or {}
        _leag_name = (_leag_raw if isinstance(_leag_raw, str) else _leag_raw.get("name", "")) or str(e.get("sport_key", ""))

        # Ratio modèle/marché : cap à max_prob_ratio× la probabilité implicite.
        # Bloque les picks aberrants (EV > 50%) où le modèle dépasse largement le marché.
        _model_prob = pb1 if best_side == n1 else pb2
        _implied_prob = (1.0 / pick_odds_check) if pick_odds_check > 1.0 else 1.0
        _prob_ratio = _model_prob / _implied_prob if _implied_prob > 0 else 0
        _overconfident = _prob_ratio > max_prob_ratio

        # Zones dangereuses apprises automatiquement (mistake_learner)
        _surf_pick = r.get("surface") or e.get("surface") or config.surface_from_league(
            (e.get("league") or {}).get("name", "") if isinstance(e.get("league"), dict) else str(e.get("league", ""))
        )
        _learned_danger = mistake_learner.is_danger_zone(best_ev_pct, pick_odds_check, _surf_pick)

        # Intelligence autonome : joueur sur-évalué ou surface systématiquement mauvaise
        _intel_blacklist = intelligence.is_blacklisted(best_side)
        _intel_surf_danger = intelligence.is_surface_danger(_surf_pick)

        # CLV par palier de confiance (2026-07-09) : confiance >=75% affiche -6.9%
        # de CLV vs -1.3% en 60-75% -> le modèle est le plus surconfiant (donc le
        # moins fiable) précisément sur ses picks les plus sûrs. On exige un EV
        # plus élevé dans cette zone pour compenser.
        _high_conf_low_ev = r["confidence"] >= 0.75 and best_ev_pct < HIGH_CONF_MIN_EV

        is_value = (best_ev_pct >= min_ev
                    and pick_odds_check <= max_odds
                    and not _dead_zone
                    and not _below_floor
                    and not _overconfident
                    and not _learned_danger
                    and not _intel_blacklist
                    and not _intel_surf_danger
                    and not _high_conf_low_ev)

        # Honeypot : conditions + surface + foule alignées (pas de fetch météo
        # ici, juste surface/style — un appel HTTP par pick serait trop coûteux
        # dans cette boucle). Affiché même hors value, comme sur /api/predict.
        _honeypot = None
        try:
            from . import weather_profile as _wp
            _wa = _wp.analyze(_MEM, n1, features.get_profile(_MEM, n1),
                              n2, features.get_profile(_MEM, n2),
                              None, _leag_name, _ev_surf or "hard")
            _honeypot = _wa.get("honeypot")
        except Exception as exc:  # noqa: BLE001
            log(f"weather_profile.analyze (honeypot) échoué pour {n1} vs {n2} ({exc}) — ignoré.", "WARN")

        # Paper-trading : capture uniquement les picks qui passent le filtre is_value.
        if is_value:
            pick_odds = ho if best_side == n1 else ao
            _surf_log = r.get("surface") or e.get("surface") or config.surface_from_league(_leag_name)
            _p_log = pb1 if best_side == n1 else pb2
            _b_log = pick_odds - 1.0
            _kelly_u_log = round(max(0.0, (_p_log * _b_log - (1.0 - _p_log)) / _b_log * 0.25 * 100), 1) if _b_log > 0 else 0.0
            try:
                db.log_value_pick(e.get("date", ""), n1, n2, best_side,
                                  pick_odds, best_ev_pct,
                                  league=_leag_name, surface=_surf_log,
                                  kelly_u=_kelly_u_log)
            except Exception as exc:  # noqa: BLE001
                log(f"db.log_value_pick échoué pour {n1} vs {n2} ({exc}) — value pick non archivé.", "WARN")
            # CLV : sème le pick à la cote de décision.
            # NE PAS appeler refresh_closing ici — la closing line doit être
            # captée APRÈS la décision par le _clv_closing_loop (toutes les 20min)
            # pour refléter la vraie variation de cote avant le départ.
            try:
                ekey = str(e.get("id") or "")
                pick_prob = pb1 if best_side == n1 else pb2
                clv.seed_pick(ekey, e.get("date", ""), n1, n2, best_side,
                              pick_odds, pick_prob, r["confidence"],
                              honeypot=_honeypot)
            except Exception as exc:  # noqa: BLE001
                log(f"clv.seed_pick échoué pour {n1} vs {n2} ({exc}) — CLV non semé.", "WARN")

        # Kelly criterion (fraction 1/4 pour limiter le risque) :
        # f* = (p*b - q) / b  où b = cote-1, p = proba blendée du côté conseillé
        _p_best = pb1 if best_side == n1 else pb2
        _b_best = (ho if best_side == n1 else ao) - 1.0
        _kelly_full = (_p_best * _b_best - (1.0 - _p_best)) / _b_best if _b_best > 0 else 0.0
        _kelly_frac = max(0.0, round(_kelly_full * 0.25, 4))   # Kelly 1/4 = prudent
        _kelly_u = round(_kelly_frac * 100, 1)                 # en % de bankroll

        # Badge tournoi profitable (> 58% de précision historique ATP/WTA)
        _GOOD_TOURN = {"berlin", "nottingham", "eastbourne", "parma", "plovdiv",
                       "brasov", "piracicaba", "dublin", "troyes", "wimbledon"}
        _tourn_label = _leag_name.lower()
        _terrain_ok = any(k in _tourn_label for k in _GOOD_TOURN)

        # Steam move (Sport Intelligence Layer Phase 2) : purement informatif,
        # n'entre pas dans is_value/best_ev — voir note en tête de
        # bot/intelligence_layer.py (pas encore backtesté).
        _steam_move = intelligence_layer.steam_move_signal(e.get("id"))

        _pick_entry = {
            "player1": n1, "player2": n2,
            "date": e.get("date", ""),
            "time": e.get("time", ""),
            "league": _leag_name,
            "surface": _ev_surf or None,
            "confidence": r["confidence"],
            "confidence_label": r["confidence_label"],
            "kelly_u": _kelly_u,
            "terrain_favorable": _terrain_ok,
            "honeypot": _honeypot,
            "steam_move": _steam_move,
            "model_first_set_prob1": r["prob1"],
            "model_match_prob1": round(pm1 * 100, 1),
            "model_match_prob2": round(pm2 * 100, 1),
            "blend_match_prob1": round(pb1 * 100, 1),
            "blend_match_prob2": round(pb2 * 100, 1),
            "market_match_prob1": round(mw["home_prob"] * 100, 1),
            "market_match_prob2": round(mw["away_prob"] * 100, 1),
            "odds": {"home": ho, "away": ao, "books": mw["books"],
                     "home_book": mw.get("home_book"), "away_book": mw.get("away_book")},
            "ev1": round(ev1 * 100, 1),
            "ev2": round(ev2 * 100, 1),
            "best_side": best_side if is_value else None,
            "best_ev": best_ev_pct,
            # Où parier le meilleur prix pour le côté conseillé (line shopping).
            "best_book": (mw.get("home_book") if best_side == n1
                          else mw.get("away_book")) if is_value else None,
            "value": is_value,
            "filter_reason": (
                "overconfident" if _overconfident else
                "dead_zone" if _dead_zone else
                "below_floor" if _below_floor else
                "low_ev" if best_ev_pct < min_ev else
                "high_odds" if pick_odds_check > max_odds else
                None
            ) if not is_value else None,
        }
        out.append(_pick_entry)

        # Telegram alert pour les picks value haute confiance (non bloquant)
        if is_value and r["confidence"] >= 0.55 and best_ev_pct >= 10.0:
            try:
                from . import realtime_alerts as _ra
                _alerter = _ra.get()
                if _alerter:
                    import threading as _th
                    _th.Thread(target=_alerter.on_value_pick,
                               args=(_pick_entry,), daemon=True).start()
            except Exception as exc:
                log(f"Alerte Telegram (value pick) échouée pour {n1} vs {n2} ({exc}) — ignorée.", "WARN")

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
        "min_ev": round(min_ev, 1),
        "min_odds": 1.40,
        "max_odds": round(max_odds, 1),
        "note": ("proba match calibrée (best-of-3 + temperature), blendée au "
                 "marché (poids modèle w) ; EV = proba_blend×cote − 1 ; "
                 f"value = EV ≥ {min_ev}%"),
    })


@app.get("/api/value/open")
def api_value_open():
    """Picks value ouverts (non réglés) — pour l'onglet Edge/Android."""
    db.init()
    with db.connect() as c:
        rows = c.execute(
            "SELECT date,player1,player2,side,odds,ev,kelly_u,league,surface "
            "FROM value_picks WHERE result IS NULL ORDER BY ev DESC LIMIT 20"
        ).fetchall()
    picks = []
    for r in rows:
        p = dict(r)
        # Surface fallback depuis le nom du tournoi si non renseignée
        if not p.get("surface") and p.get("league"):
            p["surface"] = config.surface_from_league(p["league"])
        picks.append(p)
    return jsonify({"count": len(picks), "picks": picks})


@app.get("/api/value/history")
def api_value_history():
    """Historique des value picks réglés avec résultat et P&L.

    ?odds_max=5.0  (défaut 5.0) — filtre les cotes aberrantes historiques.
    ?ev_min=0      (défaut 0)   — filtre par EV minimum.
    """
    limit = int(request.args.get("limit", 50))
    odds_max = float(request.args.get("odds_max", 5.0))
    ev_min = float(request.args.get("ev_min", 8.0))
    rows = db.list_value_history(limit=limit * 3)  # fetch extra to allow filtering
    stats = db.value_picks_stats()
    picks = []
    for r in rows:
        if (r["odds"] or 999) > odds_max:
            continue
        if (r["ev"] or 0) < ev_min:
            continue
        picks.append({
            "date": _fmt_date(r["date"]),
            "player1": r["player1"],
            "player2": r["player2"],
            "side": r["side"],
            "odds": r["odds"],
            "ev": r["ev"],
            "result": r["result"],
            "pnl": r["pnl"],
            "winner": r["winner"],
            "league": r["league"] if "league" in r.keys() else None,
            "surface": r["surface"] if "surface" in r.keys() else None,
            "kelly_u": r["kelly_u"] if "kelly_u" in r.keys() else None,
        })
        if len(picks) >= limit:
            break
    total_pnl = round(sum(p["pnl"] for p in picks if p["pnl"] is not None), 2)
    stats["pnl"] = total_pnl
    return jsonify({
        "picks": picks,
        "stats": stats,
        "filters": {"odds_max": odds_max, "ev_min": ev_min},
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
    """Réajuste Platt (a,b), température k, β ELO et w marché sur les matchs réglés."""
    global _CALIB_K, _PLATT_A, _PLATT_B, _MKT_W

    settled = db.list_settled(limit=100000)

    # 1. Platt scaling (priorité sur temperature)
    pfit = calibrate.fit_platt(settled)
    if pfit.get("fitted"):
        _PLATT_A = float(pfit["a"])
        _PLATT_B = float(pfit["b"])
        db.set_meta("platt_a", _PLATT_A)
        db.set_meta("platt_b", _PLATT_B)
        log(f"Platt: a={_PLATT_A:.4f} b={_PLATT_B:.4f} "
            f"gain={pfit['gain_pct']:.2f}% ({pfit['interpretation']})")

    # 2. Temperature (fallback si Platt non fitté, et pour calibration_k affiché)
    fit = calibrate.fit_temperature(settled)
    if fit.get("fitted"):
        _CALIB_K = float(fit["k"])
        db.set_meta("match_calib_k", _CALIB_K)

    # 3. ELO blend
    bfit = calibrate.tune_blend(_blend_samples())
    if bfit.get("fitted") and bfit.get("elo_blend") is not None:
        _MEM["elo_blend"] = float(bfit["elo_blend"])
        db.set_meta("elo_blend", _MEM["elo_blend"])

    # 4. Market blend
    mfit = calibrate.fit_market_blend(settlement.market_blend_samples(_CALIB_K))
    if mfit.get("fitted") and mfit.get("market_blend_w") is not None:
        _MKT_W = float(mfit["market_blend_w"])
        db.set_meta("market_blend_w", _MKT_W)

    return {"platt": pfit, "temperature": fit, "blend": bfit, "market_blend": mfit}


@app.get("/api/backfill")
def api_backfill():
    """Rétroactivement calcule les prédictions manquantes sur settled_matches.

    Pour chaque match sans pred_favorite, on tente une prédiction (avec fallback
    profil neutre). Seuil de confiance mini = ?min_conf (défaut 0.20).
    """
    min_conf = float(request.args.get("min_conf", 0.20))
    limit = int(request.args.get("limit", 5000))
    updated = 0
    skipped_conf = 0
    skipped_doubles = 0

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, player1, player2, winner FROM settled_matches "
            "WHERE pred_favorite IS NULL LIMIT ?", (limit,)
        ).fetchall()

    for r in rows:
        p1, p2, winner = r["player1"], r["player2"], r["winner"]
        if "/" in str(p1) or "/" in str(p2):
            skipped_doubles += 1
            continue
        n1 = _resolve(p1) or p1
        n2 = _resolve(p2) or p2
        try:
            f1 = features.feature_vector(features.get_profile(_MEM, n1))
            f2 = features.feature_vector(features.get_profile(_MEM, n2))
            pr = predictor.predict(_MEM, n1, f1, n2, f2)
            conf = pr.get("confidence", 0.0)
            if conf < min_conf:
                skipped_conf += 1
                continue
            pred_fav = pr["favorite"]
            pred_prob1 = round(predictor.set_to_match_prob(pr["prob1"] / 100.0) * 100, 1)
            correct = None
            if pred_fav:
                correct = 1 if pred_fav == winner else 0
            with db.connect() as conn:
                conn.execute(
                    "UPDATE settled_matches SET pred_favorite=?, pred_prob1=?, correct=? "
                    "WHERE id=?",
                    (pred_fav, pred_prob1, correct, r["id"])
                )
            updated += 1
        except Exception as exc:
            log(f"Backfill pred_favorite échoué pour settled_matches id={r.get('id')} ({exc}) — ignoré.", "WARN")

    metrics = settlement.calibration_metrics()
    if metrics["n"] > 0:
        db.save_calibration(metrics)
    return jsonify({
        "rows_checked": len(rows),
        "updated": updated,
        "skipped_doubles": skipped_doubles,
        "skipped_low_conf": skipped_conf,
        "accuracy_after": metrics.get("accuracy"),
        "n_after": metrics.get("n"),
    })


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
        except Exception as exc:  # noqa: BLE001
            log(f"db.save_calibration échoué ({exc}) — métriques non persistées.", "WARN")
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
                    "platt_a": round(_PLATT_A, 4), "platt_b": round(_PLATT_B, 4),
                    "market_blend_w": round(_MKT_W, 2),
                    "elo_blend": round(float(_MEM.get("elo_blend", predictor.ELO_BLEND)), 2),
                    "recent": recent})


@app.get("/api/history")
def api_history():
    """Historique des matchs réglés par date + liste des dates disponibles.

    ?date=YYYY-MM-DD  -> matchs de ce jour
    ?dates=1          -> liste des dates avec matchs (calendrier)
    """
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
            "date": _fmt_date(r["date"]),
            "tour": r["tour"],
            "tournament": _clean_tournament(r["tournament"]),
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
        "honeypot": ({
            "flag": True, "beneficiary": r["honeypot_beneficiary"],
            "player": r["honeypot_player"], "edge_pct": r["honeypot_edge_pct"],
        } if r["honeypot_flag"] else None),
    } for r in db.list_clv(limit=30)]
    return jsonify({**stats, "recent": recent})


@app.get("/api/clv/weekly")
def api_clv_weekly():
    """Rapport CLV sur les 7 derniers jours (validation paper trading).

    Query : ?days=7 (défaut), max 90.
    """
    days = min(90, max(1, int(request.args.get("days", 7))))
    return jsonify(clv.weekly_stats(days=days))


@app.get("/api/bet-history/stats")
def api_bet_history_stats():
    """Performance agrégée des paris réglés (ROI, calibration, surface).

    Query : ?days=30 (défaut), max 365.
    """
    days = min(365, max(1, int(request.args.get("days", 30))))
    return jsonify(db.bet_history_stats(days=days))


@app.get("/api/bet-history/recent")
def api_bet_history_recent():
    """Derniers paris réglés enregistrés dans bet_history.

    Query : ?limit=50 (défaut), max 500.
    """
    limit = min(500, max(1, int(request.args.get("limit", 50))))
    rows = db.list_bet_history(limit=limit)
    bets = [{
        "event_key": r["event_key"],
        "date": _fmt_date(r["date"]),
        "player1": r["player1"],
        "player2": r["player2"],
        "prediction": r["prediction"],
        "pick_side": r["pick_side"],
        "odds": r["odds"],
        "confidence": r["confidence"],
        "result": r["result"],
        "profit_loss": r["profit_loss"],
        "clv_pct": r["clv_pct"],
        "surface": r["surface"],
        "model_version": r["model_version"],
        "ts": r["ts"],
    } for r in rows]
    return jsonify({"count": len(bets), "bets": bets})


@app.get("/api/bet-history/calibration")
def api_bet_history_calibration():
    """Calibration modèle : bins 50-55% … 75%+ (prédit vs observé).

    Query : ?days=90 (défaut), max 365.
    """
    days = min(365, max(1, int(request.args.get("days", 90))))
    return jsonify(db.bet_history_calibration(days=days))


@app.get("/api/line-movement")
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


@app.get("/api/intelligence/stats")
def api_intelligence_stats():
    """Auto-diagnostic: drift, surfaces en danger, blacklist joueurs."""
    return jsonify({**intelligence.stats(), "ok": True})


@app.post("/api/intelligence/cycle")
def api_intelligence_cycle():
    """Force un cycle d'intelligence immédiat (sans attendre les 6h)."""
    result = intelligence.run_cycle(send_telegram=False)
    return jsonify({**result, "ok": True})


@app.get("/api/learner/stats")
def api_learner_stats():
    """Zones dangereuses apprises automatiquement depuis les résultats réels.

    Retourne les segments (EV bucket × cote × surface) où le ROI est
    systématiquement négatif et que le scanner bloque automatiquement.
    """
    return jsonify({**mistake_learner.stats(), "ok": True})


@app.get("/api/scanner/status")
def api_scanner_status():
    """État temps réel du scanner : cycle, rejets, near-misses, picks actifs."""
    with _SCANNER_STATE_LOCK:
        return jsonify({**_SCANNER_STATE, "ok": True})


@app.get("/api/monitor/status")
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
    return jsonify({"available": True, **result})


_LEARN_LOCK = __import__("threading").Lock()
_LEARN_LAST_RUN: float = 0.0
_LEARN_MIN_INTERVAL = 3600 * 6  # 6h minimum entre deux cycles


@app.post("/api/learn/run")
def api_learn_run():
    """Déclenche un cycle d'auto-learning : tuning par surface + k-fold eval.

    Garde-fou : un seul cycle à la fois, min 6h entre deux runs.
    """
    global _LEARN_LAST_RUN
    import time as _t

    if not _LEARN_LOCK.acquire(blocking=False):
        return jsonify({"status": "skipped",
                        "reason": "Un cycle est déjà en cours."}), 429

    now = _t.time()
    if now - _LEARN_LAST_RUN < _LEARN_MIN_INTERVAL:
        _LEARN_LOCK.release()
        wait = int(_LEARN_MIN_INTERVAL - (now - _LEARN_LAST_RUN))
        return jsonify({"status": "skipped",
                        "reason": f"Cycle récent — prochain dans {wait}s."}), 429
    try:
        _LEARN_LAST_RUN = now
        learner = auto_learner.AutoLearner()
        result = learner.run_full_cycle()
        # Apply tuned elo_blend + surface blends to live server state
        new_blend = db.get_meta("elo_blend")
        if new_blend:
            _MEM["elo_blend"] = float(new_blend)
        import json as _jj
        _sb = _jj.loads(db.get_meta("elo_blend_by_surface") or "{}")
        if _sb:
            _MEM["elo_blend_surface"] = {k: float(v) for k, v in _sb.items()}
        log(f"✓ Live elo_blend={_MEM['elo_blend']:.3f}, surfaces={_MEM.get('elo_blend_surface')}", "INFO")
        return jsonify({"status": "ok", "learning": result})
    except Exception as e:  # noqa: BLE001
        log(f"auto-learning error: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500
    finally:
        _LEARN_LOCK.release()


@app.post("/api/ingest/sackmann")
def api_ingest_sackmann():
    """Ingest Sackmann tennis data (GitHub) : ATP & WTA 2022-2026 + Challengers/ITF."""
    start_year = int(request.args.get("start_year", 2024))
    end_year = int(request.args.get("end_year", 2026))
    include_challengers = request.args.get("challengers", "true").lower() != "false"
    try:
        counts = sackmann_feeder.ingest_year_range(start_year, end_year,
                                                    include_challengers=include_challengers)
        # Recharger les joueurs en mémoire serveur
        global _MEM, _INDEX
        _MEM = memory.load()
        counts_map = {n: p.get("n", 1) for n, p in _MEM["players"].items()}
        _INDEX = namematch.build_index(list(_MEM["players"].keys()), counts_map)
        return jsonify({
            "status": "ok",
            "ingest": counts,
            "players_now": len(_MEM["players"]),
            "message": (f"+{counts['new_players']} nouveaux joueurs, "
                        f"+{counts['inserted']} matchs archivés"),
        })
    except Exception as e:  # noqa: BLE001
        log(f"sackmann ingest error: {e}", "ERROR")
        return jsonify({"error": str(e)}), 500


@app.post("/api/ingest/tennisdata")
def api_ingest_tennisdata():
    """Ingest tennis-data.co.uk : ATP + WTA grands tournois + Masters (2022-2026).

    CSV libres avec ranking, cotes B365/Pinnacle, score complet.
    Enrichit la base joueurs avec le ranking moyen observé.
    """
    start_year = int(request.args.get("start_year", 2022))
    end_year = int(request.args.get("end_year", 2026))
    tours_param = request.args.get("tours", "atp,wta")
    tours = [t.strip() for t in tours_param.split(",") if t.strip()]
    years = list(range(start_year, end_year + 1))
    try:
        from . import tennisdata_feeder
        counts = tennisdata_feeder.ingest(years=years, tours=tours)
        global _MEM, _INDEX
        _MEM = memory.load()
        counts_map = {n: p.get("n", 1) for n, p in _MEM["players"].items()}
        _INDEX = namematch.build_index(list(_MEM["players"].keys()), counts_map)
        return jsonify({
            "status": "ok",
            "ingest": counts,
            "players_now": len(_MEM["players"]),
            "message": (f"+{counts.get('new_players', 0)} nouveaux joueurs, "
                        f"+{counts.get('inserted', 0)} matchs archivés"),
        })
    except Exception as e:  # noqa: BLE001
        log(f"tennisdata ingest error: {e}", "ERROR")
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
        agent, clean_message = chat_mod.strip_agent_prefix(message)
        agent_prompt = chat_mod.AGENT_PROMPTS.get(agent, "") if agent else ""
        extra = chat_mod.build_match_context(clean_message, _MEM, agent=agent)
        reply = chat_mod.chat(clean_message, history, _MEM, primary_url, model=primary_model,
                              extra_context=extra, agent_prompt=agent_prompt)
        return jsonify({"reply": reply, "context_used": bool(extra), "agent": agent})
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


@app.route("/api/inplay/picks", methods=["GET"])
def api_inplay_picks_list():
    picks = db.list_inplay_picks(limit=100)
    stats = db.inplay_roi_stats()
    return jsonify({
        "stats": stats,
        "picks": [dict(r) for r in picks],
    })


@app.route("/api/inplay/picks", methods=["POST"])
def api_inplay_picks_log():
    body = request.get_json(silent=True) or {}
    required = ("player1", "player2", "market_type", "pick", "prob")
    if not all(k in body for k in required):
        return jsonify({"error": f"Champs requis : {required}"}), 400

    # Cap cotes live : éviter les longs shots ITF > 5.0 sur "Gagnant match"
    _raw_odds = body.get("odds") or body.get("odds_home") or body.get("odds_away")
    _mkt = (body.get("market_type") or "").lower()
    if _raw_odds and float(_raw_odds) > 5.0 and "winner" in _mkt:
        return jsonify({"error": "odds > 5.0 sur Gagnant match — pick refusé (longshot)"}), 422

    # Enrichir avec les cotes live actuelles si event_id fourni
    odds_home = body.get("odds_home")
    odds_away = body.get("odds_away")
    odds_book = body.get("odds_book")
    eid = str(body["event_id"]) if body.get("event_id") else None

    if not odds_home and eid:
        # 1. Cache mémoire live (rapide, prioritaire)
        try:
            live_data = _MEM.get("live_matches") or {}
            ev = live_data.get(eid) or {}
            lo = ev.get("live_odds") or {}
            if lo.get("home"):
                odds_home = lo["home"]
                odds_away = lo["away"]
                odds_book = ", ".join(lo.get("books", []))
        except Exception as exc:
            log(f"Lecture cache live_matches échouée pour event {eid} ({exc}) — repli sur fetch direct.", "WARN")

    if not odds_home and eid:
        # 2. Fallback : appel direct odds-api.io Betfair Exchange
        try:
            mw = odds_api.fetch_match_winner(eid, ttl=60)
            if mw and mw.get("home_odds"):
                odds_home = mw["home_odds"]
                odds_away = mw["away_odds"]
                odds_book = "Betfair Exchange"
        except Exception as exc:
            log(f"fetch_match_winner échoué pour event {eid} (log manuel) ({exc}) — odds non enrichies.", "WARN")

    # Dériver odds du côté misé si pas fourni explicitement
    pick_odds = body.get("odds")
    if not pick_odds and odds_home and odds_away:
        p1 = (body.get("player1") or "").strip().lower()
        pick_lower = (body.get("pick") or "").strip().lower()
        # Correspondance approximative : pick contient le nom du player1 ?
        if p1 and any(tok in pick_lower for tok in p1.split() if len(tok) > 3):
            pick_odds = odds_home
        elif odds_away:
            pick_odds = odds_away

    pick_id = db.log_inplay_pick(
        player1=body["player1"],
        player2=body["player2"],
        league=body.get("league", ""),
        market_type=body["market_type"],
        market_label=body.get("market_label", ""),
        pick=body["pick"],
        odds=pick_odds,
        prob=float(body["prob"]),
        stake=float(body.get("stake", 1.0)),
        odds_home=odds_home,
        odds_away=odds_away,
        odds_book=odds_book or body.get("odds_book"),
        score=body.get("score"),
        minute=body.get("minute"),
        event_id=eid,
        sets_home=body.get("sets_home"),
        sets_away=body.get("sets_away"),
    )
    return jsonify({"id": pick_id, "status": "logged"}), 201


@app.route("/api/inplay/picks/<int:pick_id>", methods=["PUT"])
def api_inplay_picks_settle(pick_id: int):
    body = request.get_json(silent=True) or {}
    result = (body.get("result") or "").upper()
    if result not in ("W", "L", "V"):
        return jsonify({"error": "result doit être W, L ou V"}), 400
    ok = db.settle_inplay_pick(
        pick_id=pick_id,
        result=result,
        stake=body.get("stake"),
    )
    if not ok:
        return jsonify({"error": "pick introuvable"}), 404
    return jsonify({"id": pick_id, "result": result, "status": "settled"})


@app.route("/api/inplay/picks/<int:pick_id>", methods=["DELETE"])
def api_inplay_picks_delete(pick_id: int):
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM inplay_picks WHERE id=?", (pick_id,))
        if cur.rowcount == 0:
            return jsonify({"error": "pick introuvable"}), 404
    return jsonify({"id": pick_id, "status": "deleted"})


@app.route("/api/device/register", methods=["POST"])
def api_device_register():
    """Enregistre le token FCM d'un appareil pour les notifications push.

    Appelé par l'app au démarrage et à chaque renouvellement de token
    (FirebaseMessagingService.onNewToken). Idempotent : ré-enregistrer un
    token déjà connu se contente de rafraîchir last_seen_ts.
    """
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    if not token:
        return jsonify({"error": "paramètre requis: token"}), 400
    platform = (body.get("platform") or "android").strip()
    db.register_device_token(token, platform)
    return jsonify({"status": "registered"})


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


# État global du scanner (partagé avec l'endpoint /api/scanner/status)
_SCANNER_STATE: Dict[str, Any] = {
    "running": False,
    "last_cycle_ts": None,       # timestamp ISO du dernier cycle
    "next_cycle_ts": None,       # timestamp ISO du prochain cycle (approx)
    "interval": 90,
    "total_events": 0,
    "checked": 0,
    "cap": 25,
    "active_picks": 0,
    "last_pick_ts": None,
    "last_pick": None,           # détail du dernier pick {side, ev, odds, hours, league}
    "rejections": {},            # {fenetre, cache, no_odds, conf, mkt, ev, zone, bl, surf}
    "near_misses": [],           # events EV 2-8% (pas encore picks)
}
_SCANNER_STATE_LOCK = __import__("threading").Lock()


def _value_scanner_loop(interval: int = 90) -> None:
    """Scanner autonome : détecte les value picks dès l'ouverture des cotes.

    Tourne toutes les `interval` secondes (défaut 90s). Budget API :
    - 1 req /events (cache 15min) → ~4 vraies req/h
    - 1 req /odds par NOUVEL event ou event < 2h du départ → ~10-15 vraies req/h
    Total estimé : < 25 vraies req/h (bien sous la limite 100 req/h).

    Logique dédup :
    - _seen : {event_id → ts_premier_check}. Évite de refetch les events déjà
      évalués et situés à > 2h (cotes peu intéressantes = early market).
    - _alerted : set d'event_ids ayant déjà généré un pick value → pas de double alerte.
    """
    import time as _t
    import datetime as _dt
    from .log import log
    from . import realtime_alerts as _ra

    _seen: Dict[str, float] = {}       # event_id → timestamp du dernier check
    _no_odds_seen: Dict[str, float] = {}  # event_id → ts du dernier no-odds (skip 10min)
    _alerted: set = set()              # event_ids déjà alertés ce cycle

    _t.sleep(45)  # laisse le serveur et les autres threads démarrer
    log(f"Value scanner démarré (intervalle {interval}s).")
    with _SCANNER_STATE_LOCK:
        _SCANNER_STATE["running"] = True
        _SCANNER_STATE["interval"] = interval

    _near_misses: list = []  # buffer local des near-misses du cycle courant

    while True:
        try:
            if not odds_api.is_enabled() or odds_api._current_key() is None:
                _t.sleep(interval)
                continue

            events = odds_api.fetch_tennis_events(upcoming_only=True)
            now_utc = _dt.datetime.now(_dt.timezone.utc)
            _near_misses = []

            # Tri priorité : grands tournois en premier
            def _tourn_rank_s(e: Dict) -> int:
                _lg = e.get("league") or {}
                slug = "" if isinstance(_lg, str) else _lg.get("slug", "")
                if any(k in slug for k in ("wimbledon", "roland-garros", "us-open", "australian")):
                    return 0
                if slug.startswith("atp") or slug.startswith("wta"):
                    return 1
                if any(k in slug for k in ("challenger", "125k", "itf")):
                    return 3
                return 2
            events = sorted(events, key=_tourn_rank_s)

            odds_calls_this_cycle = 0
            MAX_ODDS_PER_CYCLE = 25  # plafond par cycle de 90s
            # Compteurs de rejet pour diagnostic
            _rej_time = _rej_seen = _rej_no_odds = _rej_conf = _rej_mkt = _rej_ev = _rej_dead = _rej_bl = _rej_surf = 0

            for e in events:
                if odds_calls_this_cycle >= MAX_ODDS_PER_CYCLE:
                    break

                eid = str(e.get("id", ""))
                if not eid:
                    continue

                # Filtre temporel : 0→6h avant le coup d'envoi
                _e_date = e.get("commence_time") or e.get("date") or ""
                hours_ahead = None
                if _e_date:
                    try:
                        _edt = _dt.datetime.fromisoformat(str(_e_date).replace("Z", "+00:00"))
                        hours_ahead = (_edt - now_utc).total_seconds() / 3600
                        if hours_ahead > 6.0 or hours_ahead < -1.0:
                            _rej_time += 1
                            continue
                    except Exception as exc:
                        log(f"Parsing date événement échoué ({_e_date!r}: {exc}) — filtre temporel ignoré (scanner).", "WARN")

                # Déjà alerté = pas la peine de re-fetcher les cotes
                if eid in _alerted:
                    continue

                # Déjà vu et à > 2h : skip (cotes stables, pas de nouvelle valeur)
                last_check = _seen.get(eid, 0.0)
                recheck_window = (hours_ahead is not None and hours_ahead < 2.0)
                if last_check and not recheck_window:
                    if _t.time() - last_check < 600:  # re-check toutes les 10min max
                        _rej_seen += 1
                        continue

                # Skip rapide : event sans cotes connues depuis < 10min
                _no_odds_ts = _no_odds_seen.get(eid, 0.0)
                if _no_odds_ts and _t.time() - _no_odds_ts < 600:
                    _rej_no_odds += 1
                    continue

                # Fetch des cotes (1 req, cache 10min)
                mw = odds_api.fetch_match_winner(eid)
                _seen[eid] = _t.time()
                odds_calls_this_cycle += 1

                if not mw or not mw.get("home_odds") or not mw.get("away_odds"):
                    _no_odds_seen[eid] = _t.time()
                    _rej_no_odds += 1
                    continue

                # Résolution des noms
                n1 = _resolve(e.get("home", "")) or e.get("home", "").strip()
                n2 = _resolve(e.get("away", "")) or e.get("away", "").strip()
                if not n1 or not n2:
                    continue

                # Sharp money / mouvement de ligne : capture la cote à chaque
                # refresh réel (déjà throttlé ~10min/match ci-dessus) pour
                # reconstruire l'historique de ligne, indépendamment de is_value.
                try:
                    db.record_market_snapshot(eid, n1, n2, mw["home_odds"], mw["away_odds"],
                                              hours_ahead=round(hours_ahead, 2) if hours_ahead is not None else None)
                except Exception as exc:  # noqa: BLE001
                    log(f"record_market_snapshot échoué pour {n1} vs {n2} ({exc}) — ligne non archivée.", "WARN")

                # Guard cross-genre
                t1 = (_MEM.get("players") or {}).get(n1, {}).get("tour", "")
                t2 = (_MEM.get("players") or {}).get(n2, {}).get("tour", "")
                if t1 and t2 and {t1, t2} == {"atp", "wta"}:
                    continue

                # Prédiction modèle
                try:
                    f1 = features.feature_vector(features.get_profile(_MEM, n1))
                    f2 = features.feature_vector(features.get_profile(_MEM, n2))
                    _lg_name = (e.get("league") or {}).get("name", "") if isinstance(e.get("league"), dict) else str(e.get("league", ""))
                    _surf = e.get("surface") or config.surface_from_league(_lg_name)
                    r = predictor.predict(_MEM, n1, f1, n2, f2, surface=_surf or None)
                except Exception as exc:
                    log(f"Prédiction échouée pour {n1} vs {n2} (scanner) ({exc}) — événement ignoré.", "WARN")
                    continue

                # Seuil de confiance : plus strict pour ITF (rang 3)
                _tier = _tourn_rank_s(e)
                _conf_seuil = 0.65 if _tier >= 3 else 0.55
                if r.get("confidence", 0.0) < _conf_seuil:
                    _rej_conf += 1
                    continue

                pm1 = _calib(_set_to_match_prob(r["prob1"] / 100.0))
                pm2 = 1.0 - pm1
                ho, ao = mw["home_odds"], mw["away_odds"]
                pb1 = calibrate.blend_probs(pm1, mw["home_prob"], _MKT_W)
                pb2 = 1.0 - pb1
                ev1 = pb1 * ho - 1.0
                ev2 = pb2 * ao - 1.0

                if _MKT_W > 0.05:
                    model_beats_mkt1 = pm1 > mw["home_prob"]
                    model_beats_mkt2 = pm2 > mw["away_prob"]
                else:
                    model_beats_mkt1 = model_beats_mkt2 = True

                if ev1 >= ev2:
                    best_side, best_ev, pick_odds, pb_pick = n1, ev1, ho, pb1
                    if not model_beats_mkt1:
                        _rej_mkt += 1
                        continue
                else:
                    best_side, best_ev, pick_odds, pb_pick = n2, ev2, ao, pb2
                    if not model_beats_mkt2:
                        _rej_mkt += 1
                        continue

                best_ev_pct = round(best_ev * 100, 1)
                dead_zone = 12.0 <= best_ev_pct < 18.0
                below_floor = pick_odds < 1.40
                above_ceil = pick_odds > 5.0
                _implied = 1.0 / pick_odds if pick_odds > 1.0 else 1.0
                overconfident = (pb_pick / _implied) > 3.0
                learned_danger = mistake_learner.is_danger_zone(best_ev_pct, pick_odds, _surf or None)
                intel_blacklist = intelligence.is_blacklisted(best_side)
                intel_surf_danger = intelligence.is_surface_danger(_surf or None)
                # Voir HIGH_CONF_MIN_EV plus haut : confiance >=75% = pire CLV mesuré.
                high_conf_low_ev = r["confidence"] >= 0.75 and best_ev_pct < HIGH_CONF_MIN_EV

                if best_ev_pct < 8.0 or below_floor or above_ceil or overconfident or high_conf_low_ev:
                    _rej_ev += 1
                    # Near-miss : EV positif mais sous le seuil (2-8%)
                    if 2.0 <= best_ev_pct < 8.0 and not below_floor and not above_ceil and not overconfident:
                        _near_misses.append({
                            "player1": n1, "player2": n2,
                            "side": best_side, "ev": best_ev_pct,
                            "odds": pick_odds, "hours": round(hours_ahead, 1) if hours_ahead else None,
                            "league": _lg_name,
                        })
                    continue
                if dead_zone or learned_danger:
                    _rej_dead += 1
                    continue
                if intel_blacklist:
                    _rej_bl += 1
                    continue
                if intel_surf_danger:
                    _rej_surf += 1
                    continue

                # Log en DB (idempotent : log_value_pick garde le premier pick)
                _b = pick_odds - 1.0
                _kelly = round(max(0.0, (pb_pick * _b - (1.0 - pb_pick)) / _b * 0.25 * 100), 1) if _b > 0 else 0.0
                _sc_honeypot = None
                try:
                    from . import weather_profile as _wp_sc
                    _sc_honeypot = _wp_sc.analyze(
                        _MEM, n1, features.get_profile(_MEM, n1),
                        n2, features.get_profile(_MEM, n2),
                        None, _lg_name, _surf or "hard",
                    ).get("honeypot")
                except Exception as exc:  # noqa: BLE001
                    log(f"weather_profile.analyze (honeypot) échoué pour {n1} vs {n2} (scanner) ({exc}) — ignoré.", "WARN")
                try:
                    db.log_value_pick(e.get("date", ""), n1, n2, best_side,
                                      pick_odds, best_ev_pct, league=_lg_name,
                                      surface=_surf, kelly_u=_kelly)
                    ekey = str(eid)
                    clv.seed_pick(ekey, e.get("date", ""), n1, n2, best_side,
                                  pick_odds, pb_pick, r["confidence"],
                                  honeypot=_sc_honeypot)
                except Exception as exc:
                    log(f"log_value_pick/seed_pick échoué pour {n1} vs {n2} (scanner) ({exc}) — pick non archivé.", "WARN")

                # Alerte Telegram immédiate (priorité haute = scanner temps réel)
                alerter = _ra.get()
                if alerter:
                    _h = f"{hours_ahead:.1f}h" if hours_ahead is not None else "?"
                    _urgency = "⚡" if (hours_ahead is not None and hours_ahead < 1.0) else "🔔"
                    # Cote sharp (Betfair) de référence pour afficher le gap line-shopping
                    _fair_prob = mw["home_prob"] if best_side == n1 else mw["away_prob"]
                    _fair_odds = round(1.0 / _fair_prob, 2) if _fair_prob > 0 else None
                    _pick_entry = {
                        "player1": n1, "player2": n2,
                        "best_side": best_side, "best_ev": best_ev_pct,
                        "pick_odds": pick_odds, "kelly_u": _kelly,
                        "confidence_label": r.get("confidence_label", ""),
                        "league": _lg_name,
                        "surface": _surf or "",
                        "fair_odds": _fair_odds,
                        "best_book": (mw.get("books") or [""])[0] if mw.get("books") else "",
                        "hours_ahead": hours_ahead,
                        "urgency": _urgency,
                        "scanner": True,
                    }
                    import threading as _th_sc
                    _th_sc.Thread(target=alerter.on_value_pick,
                                  args=(_pick_entry,), daemon=True).start()
                    log(f"{_urgency} Scanner value pick: {best_side} EV+{best_ev_pct}% @ {pick_odds} ({_h} avant match)")

                _alerted.add(eid)
                with _SCANNER_STATE_LOCK:
                    _SCANNER_STATE["last_pick_ts"] = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                    _SCANNER_STATE["last_pick"] = {
                        "side": best_side, "ev": best_ev_pct,
                        "odds": pick_odds, "hours": round(hours_ahead, 1) if hours_ahead else None,
                        "league": _lg_name,
                    }

            # Mise à jour de l'état global (endpoint /api/scanner/status)
            _now_iso = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            _next_iso = (_dt.datetime.utcnow() + _dt.timedelta(seconds=interval)).strftime("%Y-%m-%dT%H:%M:%SZ")
            with _SCANNER_STATE_LOCK:
                _SCANNER_STATE.update({
                    "last_cycle_ts": _now_iso,
                    "next_cycle_ts": _next_iso,
                    "total_events": len(events),
                    "checked": odds_calls_this_cycle,
                    "cap": MAX_ODDS_PER_CYCLE,
                    "active_picks": len(_alerted),
                    "rejections": {
                        "fenetre": _rej_time, "cache": _rej_seen,
                        "no_odds": _rej_no_odds, "conf": _rej_conf,
                        "mkt": _rej_mkt, "ev": _rej_ev,
                        "zone": _rej_dead, "bl": _rej_bl, "surf": _rej_surf,
                    },
                    "near_misses": _near_misses[:10],
                })

            # Purge des caches d'events trop anciens (> 8h)
            if len(_seen) > 500 or len(_no_odds_seen) > 500:
                cutoff = _t.time() - 28800  # 8h
                _seen = {k: v for k, v in _seen.items() if v > cutoff}
                _no_odds_seen = {k: v for k, v in _no_odds_seen.items() if v > cutoff}

            log(
                f"Scanner: {odds_calls_this_cycle}/{MAX_ODDS_PER_CYCLE} vérifiés ({len(events)} events)"
                f" | skip: fenêtre={_rej_time} cache={_rej_seen} no_odds={_rej_no_odds}"
                f" conf={_rej_conf} mkt={_rej_mkt} EV={_rej_ev} zone={_rej_dead} BL={_rej_bl} surf={_rej_surf}"
                f" | {len(_alerted)} pick(s) actifs"
            )

        except Exception as exc:
            log(f"Value scanner erreur: {exc}", "WARN")

        _t.sleep(interval)


def _followed_matches_refresh_loop() -> None:
    """Refresh odds prioritaire pour les matchs suivis (watchlist parieur).

    TTL 30s sur les matchs de la watchlist vs 10min pour le reste — budget
    odds-api.io concentré sur ce que l'utilisateur suit activement.
    """
    import time as _t
    from .log import log

    _LIVE_TTL = 30
    _t.sleep(45)
    while True:
        try:
            watched = db.list_followed_matches()
            if not watched or not odds_api.is_enabled() or not odds_api._current_key():
                _t.sleep(60)
                continue

            all_events = odds_api.fetch_tennis_events(upcoming_only=False)
            idx = odds_api.build_event_index(all_events)
            refreshed = 0

            for row in watched:
                p1, p2 = row["player1"], row["player2"]
                ev = odds_api.find_event(idx, p1, p2)
                if not ev:
                    continue
                eid = ev.get("id") or row["event_key"]
                is_live = ev.get("status") in {"live", "inplay"}
                ttl = _LIVE_TTL if is_live else 60
                mw = odds_api.fetch_match_winner(eid, ttl=ttl)
                if not mw:
                    continue

                home_odds = float(mw["home_odds"])
                away_odds = float(mw["away_odds"])
                prev_h = row["last_odds_home"]
                prev_a = row["last_odds_away"]
                db.update_followed_match_odds(str(eid), home_odds, away_odds)
                db.record_market_snapshot(str(eid), p1, p2, home_odds, away_odds)

                from . import realtime_alerts as _ra
                if prev_h and prev_h > 1.0 and abs(home_odds - prev_h) / prev_h >= 0.03:
                    _ra.on_odds_move(p1, p2, p1, float(prev_h), home_odds)
                if prev_a and prev_a > 1.0 and abs(away_odds - prev_a) / prev_a >= 0.03:
                    _ra.on_odds_move(p1, p2, p2, float(prev_a), away_odds)

                refreshed += 1

            if refreshed:
                log(f"Watchlist: {refreshed}/{len(watched)} match(s) odds MAJ.")
        except Exception as exc:
            log(f"Watchlist refresh échoué ({exc}).", "WARN")
        _t.sleep(60)


def _clv_closing_loop() -> None:
    """Snapshote les cotes pré-match pour les picks CLV ouverts (toutes les 10min).

    - Mise à jour closing : seulement sur events PRÉ-MATCH (pas live/inplay).
      Closing = Betfair Exchange (sharp reference). CLV = Bet365_pick / Betfair_closing.
    - Settlement rapide : si un event live montre sets≥2 pour un côté, règle immédiatement
      le pick CLV sans attendre le settlement loop (qui dépend de status=settled, 24h+).
    """
    import time as _t
    from .log import log

    _LIVE_STATUSES = {"live", "inplay"}

    _t.sleep(30)  # laisse le serveur démarrer
    while True:
        try:
            open_picks = db.list_clv_open()
            if open_picks and odds_api.is_enabled() and odds_api._current_key():
                # Tous les events upcoming (pending + live) — source unique
                all_events = odds_api.fetch_tennis_events(upcoming_only=True)

                # Index pré-match seulement (closing line = avant le coup d'envoi)
                prematch = [e for e in all_events
                            if e.get("status") not in _LIVE_STATUSES]
                idx = odds_api.build_event_index(prematch)

                # Index live pour settlement rapide via scores
                live_evs = [e for e in all_events
                            if e.get("status") in _LIVE_STATUSES]
                idx_live = odds_api.build_event_index(live_evs)

                updated = 0
                settled_live = 0
                for pick in open_picks:
                    p1 = pick["player1"]
                    p2 = pick["player2"]
                    pick_side = pick["pick_side"]

                    # ── Settlement rapide depuis scores live ─────────────────
                    lev = odds_api.find_event(idx_live, p1, p2)
                    if lev:
                        scores = lev.get("scores") or {}
                        try:
                            h_sets = int(scores.get("home", 0))
                            a_sets = int(scores.get("away", 0))
                        except (TypeError, ValueError):
                            h_sets = a_sets = 0
                        # Best-of-3 : fin à 2 sets. Best-of-5 : fin à 3 sets.
                        target = 3 if max(h_sets, a_sets) >= 3 else 2
                        if h_sets >= target or a_sets >= target:
                            live_winner = lev.get("home") if h_sets > a_sets else lev.get("away")
                            if live_winner:
                                try:
                                    clv.settle(p1, p2, live_winner)
                                    log(f"CLV live-settle: {p1} vs {p2} → {live_winner} "
                                        f"({h_sets}-{a_sets})")
                                    settled_live += 1
                                except Exception as _se:
                                    log(f"CLV live-settle erreur: {_se}", "WARN")
                        continue  # match en cours : pas de closing update

                    # ── Closing update (pré-match seulement) ─────────────────
                    ev = odds_api.find_event(idx, p1, p2)
                    if not ev:
                        continue
                    mw = odds_api.fetch_match_winner(ev["id"])
                    if not mw:
                        continue
                    curr_odds = mw["home_odds"] if pick_side == p1 else mw["away_odds"]
                    mw_sharp = odds_api.fetch_match_winner(
                        ev["id"], bookmakers=odds_api._sharp_book()
                    )
                    if mw_sharp:
                        sharp_h = mw_sharp["home_odds"]
                        sharp_a = mw_sharp["away_odds"]
                    else:
                        sharp_h, sharp_a = mw["home_odds"], mw["away_odds"]
                    clv.refresh_closing(pick["event_key"], pick_side, p1,
                                        sharp_h, sharp_a,
                                        match_date=ev.get("date") or ev.get("commence_time") or "")
                    from . import realtime_alerts as _ra
                    pick_odds_orig = float(pick["pick_odds"] or 0)
                    if pick_odds_orig > 1.0 and curr_odds > 1.0:
                        _ra.on_odds_move(p1, p2, pick_side, pick_odds_orig, curr_odds)
                    updated += 1

                parts = []
                if updated:
                    parts.append(f"{updated} closing MAJ")
                if settled_live:
                    parts.append(f"{settled_live} settled live")
                if parts:
                    log(f"CLV: {', '.join(parts)}.")
        except Exception as exc:
            log(f"CLV closing loop erreur: {exc}", "WARN")
        _t.sleep(600)  # 10 min


def _settlement_loop(interval: int) -> None:
    """Boucle de fond : règle les matchs terminés, envoie alertes, recalibre."""
    import time as _t

    from .log import log
    from . import realtime_alerts as _ra
    while True:
        _t.sleep(interval)
        try:
            # Snapshot des picks ouverts avant settlement (pour détecter les nouveaux réglés)
            with db.connect() as _c:
                _open_before = {r["rowid"]: r for r in _c.execute(
                    "SELECT rowid,player1,player2,side,odds FROM value_picks WHERE result IS NULL"
                ).fetchall()}

            summary = settlement.run_settlement(_MEM, _resolve, days_back=2)

            # Alertes pour les picks qui viennent d'être réglés
            if summary.get("added", 0) and _ra.get():
                with db.connect() as _c:
                    for rowid in list(_open_before):
                        r = _c.execute(
                            "SELECT result,pnl,winner FROM value_picks WHERE rowid=? AND result IS NOT NULL",
                            (rowid,)
                        ).fetchone()
                        if r:
                            p = _open_before[rowid]
                            import threading as _thr
                            _thr.Thread(
                                target=_ra.on_settlement,
                                args=(p["player1"], p["player2"],
                                      r["winner"] or "", p["side"],
                                      float(p["odds"] or 0), float(r["pnl"] or 0)),
                                daemon=True
                            ).start()

            _refit_calibration()
            metrics = settlement.calibration_metrics()
            if metrics["n"] > 0:
                db.save_calibration(metrics)
            log(f"Settlement auto: +{summary['added']} réglés, "
                f"n={metrics['n']} acc={metrics['accuracy']} k={round(_CALIB_K, 3)}")

            # Apprentissage des erreurs : recalcule les zones dangereuses
            try:
                mistake_learner.update()
            except Exception as _ml_exc:
                log(f"mistake_learner.update échoué: {_ml_exc}", "WARN")

            # Void les picks ouverts depuis >48h (match annulé / résultat introuvable).
            import datetime as _dt
            _cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=48)).isoformat()
            with db.connect() as _c:
                _stale = _c.execute(
                    "SELECT rowid, player1, player2, date FROM value_picks "
                    "WHERE result IS NULL AND date < ?", (_cutoff,)
                ).fetchall()
            for _s in _stale:
                db.settle_value_pick(_s["player1"], _s["player2"], None)
                log(f"Void stale pick: {_s['player1']} vs {_s['player2']} ({_s['date']})", "WARN")
        except Exception as exc:  # noqa: BLE001
            log(f"Settlement auto en échec ({exc}).", "WARN")


def _inplay_settle_loop(interval: int = 300) -> None:
    """Boucle toutes les 5 min : settle les picks inplay terminés.

    Deux chemins :
    - picks avec event_id : disparus du live = terminés
    - picks sans event_id ou >2h : cherchés dans settled_matches par nom normalisé
    """
    import time as _t
    from .log import log

    while True:
        _t.sleep(interval)
        try:
            pending = db.list_inplay_picks_pending()
            if not pending:
                continue
            # Récupère les IDs en live (peut utiliser le cache TTL)
            try:
                live_events = odds_api.fetch_live_events()
                live_ids = {str(e.get("event_id", "")) for e in live_events}
            except Exception as exc:
                log(f"fetch_live_events échoué (inplay settle loop) ({exc}) — traité comme aucun match live.", "WARN")
                live_ids = set()
            settled = db.auto_settle_picks(live_ids)
            if settled:
                log(f"[Inplay] Auto-settled {len(settled)} pick(s): "
                    f"{[(s['pick'], s['result'], s['pnl']) for s in settled]}", "INFO")
        except Exception as exc:  # noqa: BLE001
            log(f"[Inplay] Erreur settlement: {exc}", "WARN")


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
    from . import realtime_alerts as _ra_init
    _ra_init.init()

    log(f"API REST sur http://{host}:{port}  (auth token: {'OUI' if token else 'non'})")
    log(f"{len(_MEM['players'])} joueurs chargés. Endpoints sous /api/ + /health.")

    interval = int(os.environ.get("SETTLEMENT_INTERVAL_S", "600"))
    if interval > 0:
        import threading
        threading.Thread(target=_settlement_loop, args=(interval,),
                         daemon=True).start()
        log(f"Settlement automatique toutes les {interval}s (auto-calibration).")

    inplay_interval = int(os.environ.get("INPLAY_SETTLE_INTERVAL_S", "300"))
    if inplay_interval > 0:
        import threading as _th
        _th.Thread(target=_inplay_settle_loop, args=(inplay_interval,),
                   daemon=True).start()
        log(f"Settlement inplay toutes les {inplay_interval}s.")

    # Snapshot closing odds pour tous les picks CLV ouverts (toutes les 20min)
    import threading as _th_clv
    _th_clv.Thread(target=_clv_closing_loop, daemon=True).start()
    log("CLV closing snapshot démarré (20min).")

    import threading as _th_watch
    _th_watch.Thread(target=_followed_matches_refresh_loop, daemon=True).start()
    log("Watchlist odds refresh démarré (60s, TTL 30s live).")

    # Scanner temps réel — détecte les value picks dès l'ouverture des cotes
    _scan_interval = int(os.environ.get("SCANNER_INTERVAL_S", "90"))
    if _scan_interval > 0 and odds_api.is_enabled():
        import threading as _th_scan
        _th_scan.Thread(target=_value_scanner_loop, args=(_scan_interval,),
                        daemon=True).start()
        log(f"Value scanner temps réel démarré ({_scan_interval}s).")

    # Intelligence autonome — cycle diagnostic toutes les 6h
    import threading as _th_intel
    _th_intel.Thread(target=intelligence._loop, kwargs={"first_delay": 600},
                     daemon=True).start()
    log("Intelligence autonome démarrée (cycle 6h).")

    # Digest quotidien Telegram à 21h
    import threading as _th2
    _th2.Thread(target=_digest_loop, daemon=True).start()
    log("Digest Telegram quotidien 21h activé.")

    # Refresh données tennis (tennis-data.co.uk) à 2h du matin
    import threading as _thd
    _thd.Thread(target=_data_refresh_loop, daemon=True).start()

    # Bot Telegram polling (/picks /digest /clear)
    import threading as _th3
    _th3.Thread(target=_tg_poll_loop, daemon=True).start()
    log("Bot Telegram polling démarré (/picks /digest).")

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


def _digest_loop() -> None:
    """Digest Telegram : à 21h ET quand tous les picks du jour sont settlés."""
    import datetime as _dt2
    import time as _time
    sent_date: str = ""
    all_settled_notified: str = ""
    weekly_sent_week: str = ""

    while True:
        _time.sleep(60)
        try:
            now = _dt2.datetime.now()
            today = now.date().isoformat()

            # 1. Digest 21h
            if now.hour == 21 and sent_date != today:
                from . import digest as _digest
                _digest.send_daily_digest(today)
                sent_date = today
                # 1b. Rapport CLV hebdo — en même temps que le digest du dimanche
                iso_week = now.strftime("%G-W%V")
                if now.weekday() == 6 and weekly_sent_week != iso_week:
                    _digest.send_weekly_clv_digest()
                    weekly_sent_week = iso_week

            # 2. Alerte "tous settlés" dès que plus aucun pick du jour n'est ouvert
            if all_settled_notified != today and now.hour >= 14:
                with db.connect() as _c:
                    pending = _c.execute(
                        "SELECT COUNT(*) FROM value_picks WHERE date LIKE ? AND result IS NULL",
                        (f"{today}%",)
                    ).fetchone()[0]
                    total = _c.execute(
                        "SELECT COUNT(*) FROM value_picks WHERE date LIKE ? AND odds<=5.0",
                        (f"{today}%",)
                    ).fetchone()[0]
                if pending == 0 and total >= 3:
                    from . import digest as _digest
                    _digest.send_daily_digest(today)
                    all_settled_notified = today
        except Exception as exc:
            log(f"Digest loop (notifications quotidiennes) échoué ({exc}).", "WARN")


def _data_refresh_loop() -> None:
    """Rafraîchit les données tennis (tennis-data.co.uk) à 2h du matin."""
    import datetime as _dt_r
    import time as _time_r
    _refreshed_on: str = ""
    _time_r.sleep(60)  # attendre démarrage complet
    while True:
        try:
            now = _dt_r.datetime.now()
            today = now.date().isoformat()
            if now.hour == 2 and _refreshed_on != today:
                log("Data refresh: ingest tennis-data.co.uk...")
                from . import tennisdata_feeder as _tdf
                result = _tdf.ingest(years=[now.year, now.year - 1])
                inserted = result.get("inserted", 0)
                log(f"Data refresh: {inserted} nouveaux matchs.")
                if inserted > 0:
                    # Rebuild ELO incrémental
                    from . import elo as _elo, memory as _mem
                    rows = db.all_matches_chrono()
                    elo_r = {}
                    for row in rows:
                        _elo.update(elo_r, dict(row).get("winner"), dict(row).get("loser"))
                    mem = _mem.load()
                    mem["elo"] = elo_r
                    _mem.save(mem)
                    log(f"ELO rebuild: {len(elo_r)} joueurs.")
                _refreshed_on = today
        except Exception as exc:
            log(f"Data refresh erreur: {exc}", "WARN")
        _time_r.sleep(1800)  # check toutes les 30min


def _tg_poll_loop() -> None:
    """Bot Telegram polling — gère /picks, /digest, /clear et forward au chat IA."""
    import time as _time
    import requests as _req
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    admin_id = int(os.environ.get("TELEGRAM_ADMIN_ID", "0") or 0)
    if not token:
        return
    base = f"https://api.telegram.org/bot{token}"
    offset = 0

    def _send(chat_id: int, text: str) -> None:
        try:
            _req.post(f"{base}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                      timeout=10)
        except Exception as exc:
            log(f"Envoi Telegram échoué vers chat {chat_id} ({exc}).", "WARN")

    while True:
        try:
            r = _req.get(f"{base}/getUpdates",
                         params={"offset": offset, "timeout": 10, "allowed_updates": ["message"]},
                         timeout=16)
            updates = r.json().get("result", []) if r.ok else []
        except Exception as exc:
            log(f"Telegram getUpdates échoué ({exc}) — retry dans 5s.", "WARN")
            _time.sleep(5)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message", {})
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            chat_id = msg["chat"]["id"]
            # Restriction admin uniquement
            if admin_id and chat_id != admin_id:
                _send(chat_id, "Accès restreint.")
                continue
            if text.startswith("/picks"):
                from . import digest as _dig
                _send(chat_id, _dig.build_picks_summary())
            elif text.startswith("/value"):
                from . import digest as _dig
                _send(chat_id, _dig.build_value_open())
            elif text.startswith("/clv"):
                from . import digest as _dig
                _send(chat_id, _dig.build_clv_report())
            elif text.startswith("/clv-weekly"):
                from . import digest as _dig
                _send(chat_id, _dig.build_weekly_clv_report())
            elif text.startswith("/digest"):
                from . import digest as _dig
                _send(chat_id, _dig.build_digest())
            elif text.startswith("/stats"):
                from . import digest as _dig
                _send(chat_id, _dig.build_global_stats())
            elif text.startswith("/intel"):
                from . import digest as _dig
                _send(chat_id, _dig.build_intel_report())
            elif text.startswith("/roi"):
                from . import digest as _dig
                _send(chat_id, _dig.build_roi_breakdown())
            elif text.startswith("/scanner"):
                from . import digest as _dig
                _send(chat_id, _dig.build_scanner_status())
            elif text.startswith("/start"):
                _send(chat_id,
                    "🎾 *TennisBoss*\n\n"
                    "/picks — picks du jour\n"
                    "/value — picks ouverts\n"
                    "/clv — Closing Line Value\n"
                    "/clv-weekly — CLV des 7 derniers jours\n"
                    "/roi — ROI par tranche EV\n"
                    "/intel — cerveau IA (blacklist, zones)\n"
                    "/scanner — état du scanner 90s\n"
                    "/stats — bilan global\n"
                    "/digest — rapport complet\n"
                    "/clear — reset chat\n\n"
                    "_Ou posez n'importe quelle question en texte libre._"
                )
            elif text.startswith("/clear"):
                # NOTE (audit 2026-07-13) : ce endpoint vit dans le service FastAPI
                # `app/` (port 8001, tennisboss-quant.service), actuellement DÉSACTIVÉ
                # (voir MASTER_TODO.md #1) -> cet appel échoue systématiquement
                # aujourd'hui. Pas de log ici : ce n'est pas une panne inattendue,
                # c'est la conséquence connue du service désactivé ; le message
                # "Historique effacé" reste affiché car côté Telegram l'historique
                # de CETTE conversation (géré ailleurs) est bien effacé.
                try:
                    _req.post(f"http://127.0.0.1:8001/tg-sessions/{chat_id}/clear", timeout=5)
                except Exception:
                    pass
                _send(chat_id, "Historique effacé.")
            else:
                # Forward vers le chat IA
                try:
                    resp = _req.post("http://127.0.0.1:8001/api/chat",
                                     json={"user_id": chat_id, "username": "tg",
                                           "message": text}, timeout=60)
                    reply = resp.json().get("reply") or resp.json().get("response") or "..."
                except Exception as exc:
                    reply = f"Erreur chat: {exc}"
                _send(chat_id, reply)
        _time.sleep(1)


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
