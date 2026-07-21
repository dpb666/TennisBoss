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
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_swagger_ui import get_swaggerui_blueprint

from . import (auto_learner, calibrate, chat as chat_mod, clv, config, datasource,
               db, elo, espn_api, features, intelligence, intelligence_layer, live_api, match_intelligence,
               memory, mistake_learner, namematch, odds_api, oddspapi_feeder, openapi_spec, predictor,
               recommendations, sackmann_feeder, settlement, versions, weather)
from . import __version__
from .blueprints import register_blueprints
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

register_blueprints(app)


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


# Plan admin (blueprint §8.1/§11.2, roadmap Q3 #3) : opérations SERVEUR
# (settlement, apprentissage, ingestion, backfill) que seul l'opérateur
# déclenche. Si TENNISBOSS_ADMIN_TOKEN est défini, elles exigent X-Admin-Token
# en PLUS du token client — le token client seul ne peut plus déclencher
# d'opération d'administration. Si TENNISBOSS_ADMIN_TOKEN est absent :
# comportement inchangé (le token client suffit), rien ne casse à l'existant.
#
# Volontairement HORS plan admin : /api/inplay/picks (POST/PUT/DELETE compris).
# Ce sont les picks manuels de l'UTILISATEUR, saisis depuis l'app Android
# (TennisBossApi.kt) avec le seul token client — des données utilisateur,
# pas de l'administration serveur. Les y mettre casserait l'app avec des 403.
_ADMIN_PATHS = frozenset({
    "/api/settlement/run", "/api/learn/run", "/api/backfill",
    "/api/intelligence/cycle",
})
_ADMIN_PREFIXES = ("/api/ingest/",)


def _is_admin_request() -> bool:
    return request.path in _ADMIN_PATHS or request.path.startswith(_ADMIN_PREFIXES)


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
    admin_token = os.environ.get("TENNISBOSS_ADMIN_TOKEN", "").strip()
    if admin_token and _is_admin_request() \
            and request.headers.get("X-Admin-Token", "") != admin_token:
        return jsonify({"error": "admin token required"}), 403
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


@app.get("/api/app/version")
def api_app_version():
    """Dernière version Android connue (bandeau "mise à jour disponible" côté
    app, avant publication Play Store qui gérera ça nativement). Lecture
    seule ; mis à jour via `python run.py set-app-version` après chaque build
    notable — voir bot/db.py::set_app_version, docs/AI_ASSISTANT_ARCHITECTURE.md
    n'est pas concerné (fonctionnalité produit, pas assistant IA)."""
    info = db.get_app_version_info()
    if not info:
        return jsonify({"available": False})
    return jsonify({"available": True, **info})


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


# /api/player/* follow, /api/match/* follow → bot/blueprints/personalization.py


def _set_to_match_prob(p_set: float) -> float:
    """Proba set -> proba match (centralisée dans predictor)."""
    return predictor.set_to_match_prob(p_set)


def _build_pick_repro(
    picked_player: str, opponent_player: str,
    model_prob_raw_side: float, model_prob_calibrated_side: float, market_prob_side: float,
    ev_pct: float, surface: Optional[str], league_name: str,
    rankings: Dict[str, int], calib_k: float, market_blend_w: float,
    event_key: Optional[str] = None, home_player: Optional[str] = None,
) -> Dict[str, Any]:
    """Construit les champs de reproductibilité d'un pick (voir
    docs/LOGGING_SCHEMA.md) — utilisé par tous les points de capture
    (api_value, _value_scanner_loop). Ne touche à aucune décision de pari,
    uniquement à ce qui est ensuite passé à clv.seed_pick pour archivage."""
    player_rank = db.lookup_player_rank(picked_player, rankings)
    opponent_rank = db.lookup_player_rank(opponent_player, rankings)
    ranking_diff = (opponent_rank - player_rank) if (player_rank is not None and opponent_rank is not None) else None

    opening_odds = None
    if event_key:
        try:
            snap = db.earliest_market_snapshot(event_key)
            if snap and home_player is not None:
                opening_odds = snap["odds_home"] if picked_player == home_player else snap["odds_away"]
        except Exception as exc:  # noqa: BLE001
            log(f"earliest_market_snapshot échoué pour {event_key} ({exc}) — opening_odds omis.", "WARN")

    return {
        "tournament": league_name or None,
        "tournament_level": config.tournament_level_from_name(league_name),
        "surface": surface or None,
        "player_rank": player_rank,
        "opponent_rank": opponent_rank,
        "ranking_diff": ranking_diff,
        "model_prob_raw": round(float(model_prob_raw_side), 6),
        "model_prob_calibrated": round(float(model_prob_calibrated_side), 6),
        "market_prob": round(float(market_prob_side), 6),
        "market_disagreement": round(abs(float(model_prob_calibrated_side) - float(market_prob_side)), 6),
        "ev_pct": ev_pct,
        "calib_k": calib_k,
        "market_blend_w": market_blend_w,
        "calibration_version": versions.CALIBRATION_VERSION,
        "predictor_version": versions.PREDICTOR_VERSION,
        "feature_set_version": versions.FEATURE_SET_VERSION,
        "opening_odds": opening_odds,
    }


_SLAMS = {"australian open", "roland garros", "french open", "wimbledon", "us open"}


def _best_of_for(tour: str, league_name: str) -> int:
    """Best-of-3 (défaut) ou best-of-5 (Grand Chelem messieurs uniquement)."""
    if (tour or "").lower() != "atp":
        return 3
    label = (league_name or "").lower()
    return 5 if any(s in label for s in _SLAMS) else 3


def _bet_builder(p1_set: float, n1: str, n2: str,
                 match_odds: Optional[Tuple[float, float]] = None) -> Dict[str, Any]:
    """Dérive plusieurs marchés à partir de la proba du 1er set (best-of-3).

    La proba match est calibrée (Platt ou temperature scaling) — logique de
    prédiction inchangée, ce qui suit n'est que de la combinatoire pure sur
    cette proba déjà calculée (aucun nouveau modèle, aucune nouvelle donnée).

    `match_odds` (cote réelle home/away), si fournie par l'appelant (seul le
    marché "match" a une vraie cote bookmaker dans ce pipeline), ajoute l'EV
    réelle dessus. Les autres marchés (set2, total_sets, handicap,
    correct_score) n'ont pas de cote bookmaker disponible ici — seule la
    cote JUSTE théorique (1/proba, `fair_odds*`) leur est associée.
    `best_market`/`best_market_confidence` : heuristique de présentation
    (le marché où un côté est le plus dominant) pour un badge "pari sûr" —
    ne modifie aucune décision de pari réelle (is_value/EV de production
    restent dans /api/value, intacts).
    """
    p = max(0.0, min(1.0, p1_set))
    q = 1.0 - p
    pm1 = _calib(_set_to_match_prob(p))   # calibration Platt appliquée ici
    pm2 = 1.0 - pm1

    def _fair(prob: float) -> Optional[float]:
        return round(1.0 / prob, 2) if prob > 1e-6 else None

    third_set = round(2 * p * q * 100, 1)
    straight_sets_prob1 = p * p   # côté 1 gagne 2-0
    straight_sets_prob2 = q * q   # côté 2 gagne 2-0

    match_market: Dict[str, Any] = {
        "prob1": round(pm1 * 100, 1), "prob2": round(pm2 * 100, 1),
        "fair_odds1": _fair(pm1), "fair_odds2": _fair(pm2),
    }
    if match_odds and match_odds[0] and match_odds[1]:
        ho, ao = match_odds
        match_market["odds1"], match_market["odds2"] = ho, ao
        match_market["ev1"] = round((pm1 * ho - 1.0) * 100, 1)
        match_market["ev2"] = round((pm2 * ao - 1.0) * 100, 1)

    set2_market = {
        "prob1": round(p * 100, 1), "prob2": round(q * 100, 1),
        "fair_odds1": _fair(p), "fair_odds2": _fair(q),
    }
    total_sets_market = {
        # "over" = le match va au 3e set (plus de 2.5 sets joués)
        "prob_over": third_set, "prob_under": round(100 - third_set, 1),
        "fair_odds_over": _fair(third_set / 100.0), "fair_odds_under": _fair(1 - third_set / 100.0),
    }
    handicap_market = {
        # Handicap -1.5 sets : ce côté gagne-t-il le match 2-0 (sans perdre un set) ?
        "prob1": round(straight_sets_prob1 * 100, 1), "prob2": round(straight_sets_prob2 * 100, 1),
        "fair_odds1": _fair(straight_sets_prob1), "fair_odds2": _fair(straight_sets_prob2),
    }

    candidates = {
        "match": max(match_market["prob1"], match_market["prob2"]),
        "set2": max(set2_market["prob1"], set2_market["prob2"]),
        "total_sets": max(total_sets_market["prob_over"], total_sets_market["prob_under"]),
        "handicap": max(handicap_market["prob1"], handicap_market["prob2"]),
    }
    best_market = max(candidates, key=candidates.get)

    return {
        "match": match_market,
        "set2": set2_market,
        "total_sets": total_sets_market,
        "handicap": handicap_market,
        "third_set_prob": third_set,   # conservé (déjà consommé ailleurs, ex. UpcomingScreen)
        "correct_score": {
            f"{n1} 2-0": round(p * p * 100, 1),
            f"{n1} 2-1": round(2 * p * p * q * 100, 1),
            f"{n2} 2-1": round(2 * p * q * q * 100, 1),
            f"{n2} 2-0": round(q * q * 100, 1),
        },
        "best_market": best_market,
        "best_market_confidence": round(candidates[best_market], 1),
    }


_COMBO_MARKETS = ("match", "set2", "total_sets", "handicap")


def _bet_builder_leg(p1_raw: str, p2_raw: str, surface: Optional[str] = None) -> Tuple[str, str, Dict[str, Any]]:
    """Rejoue predictor.predict() + _bet_builder() pour une paire de joueurs —
    réutilise exactement le même chemin que /api/predict et /api/upcoming,
    aucune nouvelle logique de prédiction. Sert au combiné (/api/bet-builder/combo)."""
    n1 = _resolve(p1_raw) or p1_raw.strip()
    n2 = _resolve(p2_raw) or p2_raw.strip()
    f1 = features.feature_vector(features.get_profile(_MEM, n1))
    f2 = features.feature_vector(features.get_profile(_MEM, n2))
    r = predictor.predict(_MEM, n1, f1, n2, f2, surface=surface)
    bb = _bet_builder(r["prob1"] / 100.0, n1, n2)
    return n1, n2, bb


@app.route("/api/bet-builder/combo", methods=["POST"])
def api_bet_builder_combo():
    """Combine 2 à 4 pronostics déjà calculés en un combiné (parlay).

    Body JSON: {"legs": [{"player1","player2","side":"player1"|"player2",
    "market":"match"|"set2"|"total_sets"|"handicap" (défaut "match"),
    "surface"?}, ...], "book_odds"?}

    Si ``book_odds`` (cote combinée bookmaker saisie par l'utilisateur) est
    fournie (> 1), la réponse inclut ``ev_pct`` et ``edge`` analytiques :
    EV% = (proba_combinée × book_odds − 1) × 100 ;
    edge = proba_combinée − 1/book_odds (vs probabilité implicite marché).

    Probabilité combinée = produit des probas individuelles (hypothèse
    d'indépendance ENTRE MATCHS DIFFÉRENTS — standard pour un parlay, mais
    ignore toute corrélation éventuelle, ex. même tournoi/mêmes conditions —
    signalé dans la réponse). Cote combinée = produit des cotes justes
    théoriques (1/proba) de chaque leg — pas une cote de bookmaker réelle
    pour les marchés autres que "match" (aucune source de cotes pour
    set2/total_sets/handicap dans ce pipeline).

    Ne modifie aucune logique de prédiction/calibration/décision de pari :
    réutilise predictor.predict()/_bet_builder() tels quels, purement de la
    combinatoire sur des sorties déjà calculées ailleurs.
    """
    data = request.get_json(silent=True) or {}
    legs_in = data.get("legs") or []
    if not isinstance(legs_in, list) or not (2 <= len(legs_in) <= 4):
        return jsonify({"error": "2 à 4 legs requis (champ 'legs')"}), 400

    book_odds: Optional[float] = None
    if "book_odds" in data and data.get("book_odds") is not None:
        try:
            book_odds = float(data["book_odds"])
        except (TypeError, ValueError):
            return jsonify({"error": "book_odds doit être un nombre > 1"}), 400
        if book_odds <= 1.0:
            return jsonify({"error": "book_odds doit être > 1"}), 400

    legs_out: List[Dict[str, Any]] = []
    combined_prob = 1.0
    combined_fair_odds = 1.0

    for leg in legs_in:
        p1_raw, p2_raw = leg.get("player1"), leg.get("player2")
        side = leg.get("side")
        market = leg.get("market", "match")
        if market not in _COMBO_MARKETS:
            market = "match"
        if not p1_raw or not p2_raw or side not in ("player1", "player2"):
            return jsonify({"error": "chaque leg requiert player1, player2, "
                                    "side ('player1'|'player2')"}), 400
        try:
            n1, n2, bb = _bet_builder_leg(p1_raw, p2_raw, surface=leg.get("surface"))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"prédiction impossible pour {p1_raw} vs {p2_raw} : {exc}"}), 422

        if market == "total_sets":
            prob_pct = bb["total_sets"]["prob_over"] if side == "player1" else bb["total_sets"]["prob_under"]
        else:
            prob_pct = bb[market]["prob1"] if side == "player1" else bb[market]["prob2"]

        p = max(1e-6, min(1 - 1e-6, prob_pct / 100.0))
        fair_odds_leg = round(1.0 / p, 3)
        combined_prob *= p
        combined_fair_odds *= fair_odds_leg
        legs_out.append({
            "player1": n1, "player2": n2, "side": side, "market": market,
            "prob_pct": round(prob_pct, 1), "fair_odds": round(fair_odds_leg, 2),
        })

    out: Dict[str, Any] = {
        "legs": legs_out,
        "n_legs": len(legs_out),
        "combined_probability_pct": round(combined_prob * 100, 2),
        "combined_fair_odds": round(combined_fair_odds, 2),
        "note": ("Probabilité combinée = produit des probas individuelles (hypothèse "
                 "d'indépendance entre matchs différents — ignore toute corrélation "
                 "éventuelle). Cote combinée = cote JUSTE théorique, pas une cote de "
                 "bookmaker réelle pour les marchés hors 'match'."),
    }
    if book_odds is not None:
        out["book_odds"] = round(book_odds, 2)
        out["ev_pct"] = round((combined_prob * book_odds - 1.0) * 100, 1)
        out["edge"] = round(combined_prob - 1.0 / book_odds, 4)
    return jsonify(out)


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
            calibrate_match_prob=_calib,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"TIS compute échoué pour {n1} vs {n2} ({exc}) — insight sans TIS.", "WARN")
    return jsonify(insight)


# TTL caches — endpoints Phase 12 (TIS) coûteux en requêtes SQLite par match.
_tis_response_cache: Dict[str, tuple] = {}  # key -> (expiry_ts, payload)
_MATCH_INTEL_TTL = 60
_engineer_today_cache: Dict[str, tuple] = {}
_ENGINEER_TODAY_TTL = 90
_ENGINEER_MAX_SCAN = 80       # fixtures filtrées max (scan cheap, sans TIS)
_ENGINEER_TIS_LIMIT = 15      # compute_tis complet — top candidats après heuristique Elo
_SLOW_ENDPOINT_WARN_MS = 5000.0


def _engineer_quick_score(
    n1: str, n2: str, surface: Optional[str], mem: Dict[str, Any], *, live: bool = False,
) -> float:
    """Heuristique O(1) Elo pour pré-trier avant compute_tis (SQLite batch)."""
    elo = mem.get("elo") or {}
    e1 = predictor._lookup_elo(elo, n1)
    e2 = predictor._lookup_elo(elo, n2)
    if surface:
        surf_elo = (mem.get("elo_surface") or {}).get(surface, {})
        if surf_elo:
            e1 = predictor._lookup_elo(surf_elo, n1)
            e2 = predictor._lookup_elo(surf_elo, n2)
    avg = (e1 + e2) / 2.0
    diff = abs(e1 - e2)
    # Favorise matchs de haut niveau et relativement compétitifs (proxy TIS sans DB).
    score = avg + max(0.0, 220.0 - diff) * 0.3
    if live:
        score += 200.0
    return score


def _record_endpoint_timing(name: str, elapsed_ms: float) -> None:
    """Persiste les timings lents pour /api/monitor/status."""
    import datetime as _dt
    import json as _j
    try:
        stats = _j.loads(db.get_meta("endpoint_timings") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        stats = {}
    prev = stats.get(name, {})
    count = int(prev.get("count", 0)) + 1
    max_ms = max(float(prev.get("max_ms", 0)), elapsed_ms)
    avg_ms = (float(prev.get("avg_ms", 0)) * (count - 1) + elapsed_ms) / count
    stats[name] = {
        "count": count,
        "last_ms": round(elapsed_ms, 1),
        "max_ms": round(max_ms, 1),
        "avg_ms": round(avg_ms, 1),
        "last_ts": _dt.datetime.utcnow().isoformat(timespec="seconds"),
    }
    db.set_meta("endpoint_timings", _j.dumps(stats))
    if elapsed_ms >= _SLOW_ENDPOINT_WARN_MS:
        log(f"Endpoint lent {name}: {elapsed_ms:.0f}ms", "WARN")


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
        calibrate_match_prob=_calib,
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
    import time as _t

    t0 = _t.time()
    limit = min(int(request.args.get("limit", 15)), 30)
    min_tis = float(request.args.get("min_tis", 0))

    cache_key = f"{limit}_{min_tis}"
    cached = _tis_cache_get(_engineer_today_cache, cache_key)
    if cached is not None:
        _record_endpoint_timing("engineer/today", (_t.time() - t0) * 1000)
        return jsonify(cached)

    t_espn = _t.time()
    fixtures = espn_api.fetch_upcoming(days_ahead=1)
    espn_ms = (_t.time() - t_espn) * 1000
    _today = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    known_players = _MEM.get("players") or {}
    scanned: List[tuple] = []

    for f in fixtures:
        if len(scanned) >= _ENGINEER_MAX_SCAN:
            break
        if f.get("is_doubles"):
            continue
        if not (f.get("live") or f.get("date", "") >= _today):
            continue
        n1 = _resolve(f.get("player1", "")) or f.get("player1", "")
        n2 = _resolve(f.get("player2", "")) or f.get("player2", "")
        if not n1 or not n2:
            continue
        if n1 not in known_players or n2 not in known_players:
            continue
        t1 = known_players.get(n1, {}).get("tour", "")
        t2 = known_players.get(n2, {}).get("tour", "")
        if t1 and t2 and {t1, t2} == {"atp", "wta"}:
            continue
        surface = f.get("surface") or config.surface_from_league(f.get("tournament", ""))
        qscore = _engineer_quick_score(n1, n2, surface, _MEM, live=bool(f.get("live")))
        scanned.append((qscore, f, n1, n2, surface))

    tis_cap = _ENGINEER_TIS_LIMIT
    candidates = [
        (f, n1, n2, surface)
        for _, f, n1, n2, surface in sorted(scanned, key=lambda x: x[0], reverse=True)[:tis_cap]
    ]
    batch_names: List[str] = []
    batch_pairs: List[tuple] = []
    for f, n1, n2, surface in candidates:
        batch_names.extend([n1, n2])
        batch_pairs.append((n1, n2))

    rows: List[Dict[str, Any]] = []
    t_tis = _t.time()
    with intelligence_layer.intel_batch(batch_names, batch_pairs):
        for f, n1, n2, surface in candidates:
            try:
                tis = match_intelligence.compute_tis(
                    n1, n2, surface=surface, mem=_MEM, calibrate_match_prob=_calib,
                )
            except Exception as exc:  # noqa: BLE001
                log(f"engineer/today: TIS échoué {n1} vs {n2} ({exc}) — ignoré.", "WARN")
                continue
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

    tis_ms = (_t.time() - t_tis) * 1000
    rows.sort(key=lambda r: (r["tis"], r.get("ev_pct", 0)), reverse=True)
    top = rows[:limit]
    result = {"count": len(top), "matches": top}
    _tis_cache_set(_engineer_today_cache, cache_key, result, _ENGINEER_TODAY_TTL)
    total_ms = (_t.time() - t0) * 1000
    if total_ms >= 2000:
        log(
            f"engineer/today cold breakdown: espn={espn_ms:.0f}ms "
            f"tis({len(candidates)})={tis_ms:.0f}ms total={total_ms:.0f}ms",
            "INFO",
        )
    _record_endpoint_timing("engineer/today", total_ms)
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
            # Cote réelle (si dispo) récupérée AVANT _bet_builder pour lui passer
            # match_odds — un seul appel _odds_for, réutilisé pour item["odds"]
            # ci-dessous (pas de requête odds-api supplémentaire).
            odds_result = _odds_for(odds_index, f["player1"], f["player2"]) if odds_index is not None else None
            match_odds_tuple = ((odds_result["home_odds"], odds_result["away_odds"])
                                if odds_result else None)
            bb = _bet_builder(r["prob1"] / 100.0, n1, n2, match_odds=match_odds_tuple)
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
                "bet_builder": bb,
            }
            if odds_result is not None:
                item["odds"] = odds_result

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

    # Rankings chargés une fois par requête (pas par match) — reproductibilité
    # du logging (clv_log.player_rank/opponent_rank/ranking_diff), voir
    # docs/LOGGING_SCHEMA.md. N'affecte ni la prédiction ni is_value.
    _rankings_cache = db.get_all_player_rankings()

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

        _pm1_raw = _set_to_match_prob(r["prob1"] / 100.0)       # proba match AVANT calibration
        pm1 = _calib(_pm1_raw)  # proba match calibrée (J1)
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
            _surf_log = db.resolve_pick_surface(
                n1, n2, _leag_name, r.get("surface") or e.get("surface"), e.get("date", ""),
            )
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
                _opponent = n2 if best_side == n1 else n1
                _repro = _build_pick_repro(
                    best_side, _opponent,
                    _pm1_raw if best_side == n1 else (1.0 - _pm1_raw),
                    pm1 if best_side == n1 else pm2,
                    mw["home_prob"] if best_side == n1 else mw["away_prob"],
                    best_ev_pct, _surf_log, _leag_name, _rankings_cache,
                    _CALIB_K, _MKT_W, event_key=ekey, home_player=n1,
                )
                clv.seed_pick(ekey, e.get("date", ""), n1, n2, best_side,
                              pick_odds, pick_prob, r["confidence"],
                              honeypot=_honeypot, repro=_repro)
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


# /api/logging/health, /api/track-record/* → bot/blueprints/performance.py

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
    from .workers.value_scanner import get_status
    return jsonify({**get_status(), "ok": True})


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
    try:
        endpoint_timings = json.loads(db.get_meta("endpoint_timings") or "{}")
    except (json.JSONDecodeError, TypeError):
        endpoint_timings = {}
    return jsonify({"available": True, "endpoint_timings": endpoint_timings, **result})


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
    # mode=analyst (docs/AI_ASSISTANT_ARCHITECTURE.md §3.5) : réponses plus
    # longues/factuelles pour les questions techniques (ROI, calibration,
    # architecture...) ; mode=chat (défaut) garde le comportement mobile
    # actuel inchangé (MAX_TOKENS/TEMPERATURE d'origine).
    mode = (data.get("mode") or "chat").strip().lower()
    if mode == "analyst":
        req_max_tokens = data.get("max_tokens")
        chat_max_tokens = int(req_max_tokens) if req_max_tokens else chat_mod.ANALYST_MAX_TOKENS
        chat_temperature = chat_mod.ANALYST_TEMPERATURE
    else:
        chat_max_tokens = None
        chat_temperature = None
    try:
        agent, clean_message = chat_mod.strip_agent_prefix(message)
        agent_prompt = chat_mod.AGENT_PROMPTS.get(agent, "") if agent else ""
        extra = chat_mod.build_match_context(clean_message, _MEM, agent=agent)
        # AI Assistant Phase 1 (read-only tools, docs/AI_ASSISTANT_ARCHITECTURE.md
        # §3) : ne s'exécute QUE si aucun joueur n'a été détecté (build_match_context
        # vide) et seulement derrière un flag désactivé par défaut — comportement
        # strictement identique à avant quand TENNISBOSS_AI_TOOLS n'est pas activé.
        tools_called: list = []
        sources: list = []
        if config.AI_TOOLS_ENABLED and not extra:
            try:
                from ai.chat import orchestrator as ai_orchestrator
                tool_context, tools_called, sources = ai_orchestrator.run_tools_for_message(clean_message)
                if tool_context:
                    extra = tool_context
            except Exception as exc:  # noqa: BLE001
                log(f"AI tools orchestrator échoué ({exc}) — chat inchangé.", "WARN")
        reply = chat_mod.chat(clean_message, history, _MEM, primary_url, model=primary_model,
                              extra_context=extra, agent_prompt=agent_prompt,
                              max_tokens=chat_max_tokens, temperature=chat_temperature)
        resp = {"reply": reply, "context_used": bool(extra), "agent": agent, "mode": mode}
        if tools_called:
            resp["tools_called"] = tools_called
            resp["sources"] = sources
        return jsonify(resp)
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


def _value_scanner_loop(interval: int = 90) -> None:
    """Compatibility shim — implementation: ``bot.workers.value_scanner``."""
    from .workers.value_scanner import ScannerDeps, run_loop

    deps = ScannerDeps(
        get_mem=lambda: _MEM,
        resolve=_resolve,
        calibrate_match_prob=_calib,
        get_calib_k=lambda: _CALIB_K,
        get_market_blend_w=lambda: _MKT_W,
        build_pick_repro=_build_pick_repro,
        set_to_match_prob=_set_to_match_prob,
        high_conf_min_ev=HIGH_CONF_MIN_EV,
    )
    run_loop(interval=interval, deps=deps)


def _followed_matches_refresh_loop() -> None:
    """Compatibility shim — implementation: ``bot.workers.match_refresh_worker``."""
    from .workers.match_refresh_worker import run_loop
    run_loop()


def _clv_closing_loop() -> None:
    """Compatibility shim — implementation: ``bot.workers.clv_worker``."""
    from .workers.clv_worker import run_loop
    run_loop()


def _settlement_loop(interval: int) -> None:
    """Compatibility shim — implementation: ``bot.workers.settlement_worker``."""
    from .workers.settlement_worker import SettlementDeps, run_loop

    deps = SettlementDeps(
        get_mem=lambda: _MEM,
        resolve=_resolve,
        refit_calibration=_refit_calibration,
        get_calib_k=lambda: _CALIB_K,
    )
    run_loop(interval=interval, deps=deps)


def _inplay_settle_loop(interval: int = 300) -> None:
    """Compatibility shim — implementation: ``bot.workers.inplay_settlement_worker``."""
    from .workers.inplay_settlement_worker import run_loop
    run_loop(interval=interval)


def _enforce_prod_token(host: str) -> str:
    """Default-deny en production (blueprint §11.1, roadmap Q3 #3).

    Renvoie le token client courant. Sans token : en TENNISBOSS_ENV=prod le
    démarrage est REFUSÉ (SystemExit) ; en dev, simple avertissement si l'API
    est exposée au-delà de localhost (comportement historique conservé —
    l'opt-in prod se fait en ajoutant TENNISBOSS_ENV=prod au .env)."""
    from .log import log
    token = os.environ.get("TENNISBOSS_API_TOKEN", "").strip()
    if token:
        return token
    env = os.environ.get("TENNISBOSS_ENV", "dev").strip().lower()
    if env == "prod":
        log("SÉCURITÉ : TENNISBOSS_ENV=prod sans TENNISBOSS_API_TOKEN — "
            "démarrage refusé (default-deny, docs/ARCHITECTURE_BLUEPRINT.md "
            "§11.1). Définissez le token puis relancez.", "ERROR")
        raise SystemExit(1)
    if host not in ("127.0.0.1", "localhost"):
        log("SÉCURITÉ : API exposée sur le LAN SANS token (TENNISBOSS_API_TOKEN "
            "absent du .env) — tout le réseau peut lire les données ET déclencher "
            "/api/settlement/run, /api/learn/run, /api/upload. Définissez un token.",
            "WARN")
    return token


def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    _load_state()
    from .log import log

    # Charge .env AVANT toute lecture de token : _auth() lit os.environ à chaque
    # requête, il faut donc que TENNISBOSS_API_TOKEN y soit présent dès le départ.
    # include_auth=True : seul ce point d'entrée serveur charge les clés d'auth
    # (les autres call sites de load_env n'injectent que les clés fournisseurs).
    from .live_api import load_env as _load_env
    _load_env(include_auth=True)

    token = _enforce_prod_token(host)
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
    """Compatibility shim — implementation: ``bot.workers.telegram_worker``."""
    from .workers.telegram_worker import run_digest_loop
    run_digest_loop()


def _data_refresh_loop() -> None:
    """Compatibility shim — implementation: ``bot.workers.data_refresh_worker``."""
    from .workers.data_refresh_worker import run_loop
    run_loop()


def _tg_poll_loop() -> None:
    """Compatibility shim — implementation: ``bot.workers.telegram_worker``."""
    from .workers.telegram_worker import run_poll_loop
    run_poll_loop()


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
