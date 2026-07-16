"""Spécification OpenAPI 3.0 de l'API TennisBoss, servie en JSON sous
/api/openapi.json et via Swagger UI sous /api/docs (voir bot/api.py).

Écrite à la main plutôt que générée depuis des docstrings (flasgger) : les
30 endpoints existants n'ont pas de docstrings structurées pour ça, et
réécrire chaque docstring aurait été plus intrusif que ce fichier séparé,
qui ne touche à aucun code métier existant.
"""
from __future__ import annotations

from typing import Any, Dict

TOKEN_HEADER = {
    "ApiTokenAuth": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Token",
        "description": (
            "Requis uniquement si TENNISBOSS_API_TOKEN est définie côté serveur "
            "(voir bot/api.py::_auth). /health et /privacy restent publics."
        ),
    }
}


def _op(summary: str, params: list = None, request_body: Dict[str, Any] = None,
        responses: Dict[str, Any] = None, tags: list = None) -> Dict[str, Any]:
    op: Dict[str, Any] = {"summary": summary, "tags": tags or ["default"]}
    if params:
        op["parameters"] = params
    if request_body:
        op["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": request_body}},
        }
    op["responses"] = responses or {"200": {"description": "OK"}}
    return op


def _q(name: str, required: bool = False, type_: str = "string", desc: str = "") -> Dict[str, Any]:
    return {
        "name": name, "in": "query", "required": required,
        "schema": {"type": type_}, "description": desc,
    }


def _ok(desc: str = "Succès") -> Dict[str, Any]:
    return {"200": {"description": desc}}


def build_spec() -> Dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "TennisBoss API",
            "version": "1.0.0",
            "description": (
                "Backend d'analyse tennis (ATP/WTA) : prédictions calibrées, "
                "value betting, Sport Intelligence Layer (form_signal, "
                "steam_move, sentiment — informatifs, non injectés dans le "
                "modèle), recommandations personnalisées. Outil d'aide à la "
                "décision — pas de pari automatique, aucune exécution de "
                "transaction financière."
            ),
        },
        "servers": [{"url": "/"}],
        "components": {"securitySchemes": TOKEN_HEADER},
        "security": [{"ApiTokenAuth": []}],
        "tags": [
            {"name": "core", "description": "Santé, statut, joueurs, prédiction"},
            {"name": "matches", "description": "Matchs à venir / en direct"},
            {"name": "value", "description": "Value betting (EV modèle vs marché)"},
            {"name": "intelligence", "description": "Sport Intelligence Layer + auto-diagnostic"},
            {"name": "personalization", "description": "Recommandations, joueurs suivis"},
            {"name": "inplay", "description": "Marchés et picks en direct"},
            {"name": "chat", "description": "Assistant IA"},
            {"name": "admin", "description": "Ingestion / ré-apprentissage / settlement"},
        ],
        "paths": {
            "/health": {"get": _op(
                "Santé du service (public, sans token)",
                responses=_ok(), tags=["core"])},
            "/api/status": {"get": _op(
                "Métriques modèle + base + quota odds-api.io",
                responses=_ok(), tags=["core"])},
            "/api/players": {"get": _op(
                "Recherche joueurs (autocomplete) + probabilité vs moyenne",
                params=[_q("q", desc="Sous-chaîne du nom"),
                        _q("tour", desc="atp | wta"),
                        _q("limit", type_="integer")],
                responses=_ok(), tags=["core"])},
            "/api/player": {"get": _op(
                "Fiche détaillée d'un joueur (ELO, forme, bilan, suivi)",
                params=[_q("name", required=True)],
                responses={**_ok(), "404": {"description": "Joueur inconnu"}}, tags=["core"])},
            "/api/player/follow": {"post": _op(
                "Suit un joueur — signal explicite de personnalisation",
                request_body={"type": "object", "properties": {"name": {"type": "string"}},
                              "required": ["name"]},
                responses=_ok(), tags=["personalization"])},
            "/api/player/unfollow": {"post": _op(
                "Ne plus suivre un joueur",
                request_body={"type": "object", "properties": {"name": {"type": "string"}},
                              "required": ["name"]},
                responses=_ok(), tags=["personalization"])},
            "/api/players/followed": {"get": _op(
                "Liste des joueurs suivis (fiche complète)",
                responses=_ok(), tags=["personalization"])},
            "/api/h2h": {"get": _op(
                "Confrontations directes entre deux joueurs",
                params=[_q("p1", required=True), _q("p2", required=True)],
                responses=_ok(), tags=["core"])},
            "/api/predict": {"get": _op(
                "Prédiction calibrée du 1er set entre deux joueurs (+ explicabilité)",
                params=[_q("p1", required=True), _q("p2", required=True),
                        _q("surface", desc="hard | clay | grass")],
                responses={**_ok(), "400": {"description": "Paramètres manquants"}}, tags=["core"])},
            "/api/bet-builder/combo": {"post": _op(
                "Combine 2-4 pronostics déjà calculés en un combiné (parlay) — "
                "probabilité combinée = produit des probas (hypothèse d'indépendance), "
                "aucune nouvelle logique de prédiction",
                request_body={"type": "object", "properties": {
                    "legs": {"type": "array", "items": {"type": "object", "properties": {
                        "player1": {"type": "string"}, "player2": {"type": "string"},
                        "side": {"type": "string", "enum": ["player1", "player2"]},
                        "market": {"type": "string",
                                  "enum": ["match", "set2", "total_sets", "handicap"]},
                        "surface": {"type": "string"},
                    }}}},
                    "required": ["legs"]},
                responses={**_ok(), "400": {"description": "2-4 legs requis"},
                          "422": {"description": "Prédiction impossible pour une leg"}},
                tags=["core"])},
            "/api/insight": {"get": _op(
                "Sport Intelligence Layer : facteurs de décision, santé du modèle, "
                "mouvement de marché, sentiment (opt-in ?sentiment=true)",
                params=[_q("p1", required=True), _q("p2", required=True),
                        _q("surface"), _q("event_id"),
                        _q("sentiment", type_="boolean", desc="Active NewsAPI (quota limité)")],
                responses=_ok(), tags=["intelligence"])},
            "/api/upcoming": {"get": _op(
                "Matchs à venir (fusion multi-source) + prédictions",
                params=[_q("days", type_="integer"), _q("limit", type_="integer"),
                        _q("odds", type_="boolean")],
                responses=_ok(), tags=["matches"])},
            "/api/live": {"get": _op(
                "Matchs en cours : score, prédiction in-play, cotes live",
                responses={**_ok(), "503": {"description": "ODDS_API_KEY absente"}}, tags=["matches"])},
            "/api/inplay/best": {"get": _op(
                "Meilleur pick en direct selon confiance × edge",
                responses=_ok(), tags=["inplay"])},
            "/api/inplay/markets": {"get": _op(
                "Marchés dérivés en direct (gagnant set, O/U jeux/aces)",
                responses=_ok(), tags=["inplay"])},
            "/api/inplay/picks": {
                "get": _op("Liste des picks en direct pris + stats ROI", responses=_ok(), tags=["inplay"]),
                "post": _op(
                    "Enregistre un pick en direct",
                    request_body={"type": "object", "properties": {
                        "player1": {"type": "string"}, "player2": {"type": "string"},
                        "market_type": {"type": "string"}, "pick": {"type": "string"},
                        "prob": {"type": "number"},
                    }, "required": ["player1", "player2", "market_type", "pick", "prob"]},
                    responses={"201": {"description": "Créé"}}, tags=["inplay"]),
            },
            "/api/inplay/picks/{pick_id}": {
                "put": _op("Règle un pick en direct (W/L/V)", tags=["inplay"],
                          params=[{"name": "pick_id", "in": "path", "required": True,
                                   "schema": {"type": "integer"}}],
                          responses=_ok()),
                "delete": _op("Supprime un pick en direct", tags=["inplay"],
                             params=[{"name": "pick_id", "in": "path", "required": True,
                                      "schema": {"type": "integer"}}],
                             responses=_ok()),
            },
            "/api/value": {"get": _op(
                "Value bets : EV modèle vs cotes marché",
                params=[_q("limit", type_="integer"), _q("min_confidence", type_="number"),
                        _q("min_ev", type_="number"), _q("max_odds", type_="number")],
                responses={**_ok(), "503": {"description": "ODDS_API_KEY absente"}}, tags=["value"])},
            "/api/value/open": {"get": _op("Value picks ouverts (non réglés)", responses=_ok(), tags=["value"])},
            "/api/value/history": {"get": _op(
                "Historique des value picks réglés + P&L",
                params=[_q("limit", type_="integer"), _q("odds_max", type_="number"),
                        _q("ev_min", type_="number")],
                responses=_ok(), tags=["value"])},
            "/api/logging/health": {"get": _op(
                "Santé du pipeline de logging (complétude des champs de reproductibilité, clv_log)",
                params=[_q("bucket", type_="string"), _q("incomplete_limit", type_="integer")],
                responses=_ok(), tags=["observability"])},
            "/api/recommendations": {"get": _op(
                "Recommandations personnalisées (usage du compte actuel)",
                params=[_q("limit", type_="integer")], responses=_ok(), tags=["personalization"])},
            "/api/calibration": {"get": _op(
                "Métriques de calibration (Platt/température, ELO/marché blend)",
                responses=_ok(), tags=["intelligence"])},
            "/api/clv": {"get": _op(
                "Closing Line Value — preuve d'edge honnête", responses=_ok(), tags=["intelligence"])},
            "/api/clv/weekly": {"get": _op(
                "Rapport CLV glissant (7 jours par défaut)",
                params=[_q("days", type_="integer")], responses=_ok(), tags=["intelligence"])},
            "/api/match/intelligence": {"get": _op(
                "Tennis Intelligence Score (TIS) 0-100 + EV + recommandation",
                params=[_q("p1", required=True), _q("p2", required=True),
                        _q("surface"), _q("event_key"), _q("event_id")],
                responses={**_ok(), "400": {"description": "p1/p2 manquants"}},
                tags=["intelligence"])},
            "/api/engineer/today": {"get": _op(
                "Top matchs du jour classés par TIS (tableau Engineer)",
                params=[_q("limit", type_="integer"), _q("min_tis", type_="number")],
                responses=_ok(), tags=["intelligence"])},
            "/api/bet-history/stats": {"get": _op(
                "Performance agrégée paris réglés (ROI, yield, CLV, surface)",
                params=[_q("days", type_="integer")], responses=_ok(), tags=["intelligence"])},
            "/api/bet-history/recent": {"get": _op(
                "Derniers paris réglés (bet_history)",
                params=[_q("limit", type_="integer")], responses=_ok(), tags=["intelligence"])},
            "/api/bet-history/calibration": {"get": _op(
                "Bins calibration prédit vs observé (50-55% … 75%+)",
                params=[_q("days", type_="integer")], responses=_ok(), tags=["intelligence"])},
            "/api/line-movement": {"get": _op(
                "Mouvement de cote capté par le scanner pour un match",
                params=[_q("event_id")], responses=_ok(), tags=["intelligence"])},
            "/api/intelligence/stats": {"get": _op(
                "Auto-diagnostic : drift, surfaces en danger, blacklist joueurs",
                responses=_ok(), tags=["intelligence"])},
            "/api/intelligence/cycle": {"post": _op(
                "Force un cycle d'auto-diagnostic immédiat", responses=_ok(), tags=["intelligence"])},
            "/api/learner/stats": {"get": _op(
                "Zones dangereuses apprises automatiquement", responses=_ok(), tags=["intelligence"])},
            "/api/scanner/status": {"get": _op(
                "État temps réel du scanner de value bets", responses=_ok(), tags=["intelligence"])},
            "/api/monitor/status": {"get": _op(
                "Dernier health check système (DB, endpoints, quota odds, dérive modèle) — "
                "calculé toutes les 5 min par le worker (bot/scheduler.py::job_monitor)",
                responses=_ok(), tags=["intelligence"])},
            "/api/history": {"get": _op(
                "Historique des matchs réglés par date",
                params=[_q("date"), _q("dates")], responses=_ok(), tags=["core"])},
            "/api/device/register": {"post": _op(
                "Enregistre le token FCM d'un appareil (notifications push)",
                request_body={"type": "object", "properties": {
                    "token": {"type": "string"}, "platform": {"type": "string"}},
                    "required": ["token"]},
                responses=_ok(), tags=["personalization"])},
            "/api/chat": {"post": _op(
                "Assistant IA conversationnel (contexte prédiction ancré ; réponse "
                "inclut tools_called/sources quand les outils analytiques en lecture "
                "seule se déclenchent, voir docs/AI_ASSISTANT_ARCHITECTURE.md)",
                request_body={"type": "object", "properties": {
                    "message": {"type": "string"}, "history": {"type": "array"}},
                    "required": ["message"]},
                responses={**_ok(), "503": {"description": "LLM inaccessible"}}, tags=["chat"])},
            "/api/upload": {"post": _op(
                "Upload PDF/CSV/TXT — extraction texte + question optionnelle",
                responses=_ok(), tags=["chat"])},
            "/api/settlement/run": {"get": _op(
                "Règle les matchs terminés récents + recalibre",
                params=[_q("days", type_="integer")], responses=_ok(), tags=["admin"])},
            "/api/backfill": {"get": _op(
                "Rétro-calcule les prédictions manquantes sur l'historique",
                params=[_q("min_conf", type_="number"), _q("limit", type_="integer")],
                responses=_ok(), tags=["admin"])},
            "/api/learn/run": {"post": _op(
                "Déclenche un cycle d'auto-apprentissage complet (min 6h entre 2 runs)",
                responses={**_ok(), "429": {"description": "Cycle déjà en cours ou trop récent"}},
                tags=["admin"])},
            "/api/ingest/sackmann": {"post": _op(
                "Ingestion Sackmann (GitHub) ATP/WTA + Challengers/ITF",
                params=[_q("start_year", type_="integer"), _q("end_year", type_="integer")],
                responses=_ok(), tags=["admin"])},
            "/api/ingest/tennisdata": {"post": _op(
                "Ingestion tennis-data.co.uk (grands tournois + Masters)",
                params=[_q("start_year", type_="integer"), _q("end_year", type_="integer")],
                responses=_ok(), tags=["admin"])},
        },
    }
