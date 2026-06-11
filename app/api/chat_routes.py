"""Telegram AI Chat integration routes.

Endpoints:
  POST /tg-webhook      : Telegram bot webhook receiver
  POST /tg-chat         : Direct chat API (for testing)
  GET  /tg-sessions/<id>: Retrieve session history

Le chat IA est branché sur le moteur réel TennisBoss :
  - prédiction 1er set + match (predictor.predict)
  - H2H depuis les 16k matchs (db.head_to_head)
  - fiche joueur : ELO, forme, record (db + features)
  - value bets : EV calculé sur les cotes live
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from bot import chat as chat_mod
from bot import telegram_handler as tg
from bot.log import log

router = APIRouter()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


class ChatRequest(BaseModel):
    user_id: int
    message: str
    session_context: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    user_id: int
    reply: str
    agent: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class LegacyChatRequest(BaseModel):
    message: str
    history: Optional[list] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/chat")
def legacy_chat(req: LegacyChatRequest):
    """Legacy /api/chat endpoint (compat Flask → FastAPI)."""
    from app.main import _MEM
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message requis")
    try:
        extra = _build_match_context(message, _MEM)
        reply = chat_mod.chat(message, req.history or [], _MEM, extra_context=extra)
        log(f"Chat reply: {reply[:60]}", "INFO")
        return {"reply": reply}
    except Exception as exc:  # noqa: BLE001
        log(f"Chat LLM en échec : {exc}", "WARN")
        raise HTTPException(status_code=503, detail=f"LLM inaccessible : {exc}") from exc


@router.post("/tg-webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram bot updates via webhook."""
    try:
        body = await request.body()
        update = json.loads(body)
    except (json.JSONDecodeError, ValueError) as e:
        log(f"Invalid webhook body: {e}", "WARN")
        return {"ok": False}

    result = tg.parse_telegram_message(update)
    if not result:
        return {"ok": True}

    user_id, username, text = result
    log(f"TG from @{username} ({user_id}): {text[:60]}", "INFO")

    session = tg.get_session(user_id, username)

    if text.lower() in ["/clear", "/reset"]:
        tg.clear_history(user_id)
        reply = "✅ Conversation effacée."
    elif text.lower() in ["/help", "help"]:
        reply = _help_text()
    else:
        agent = tg.route_agent_command(text)
        reply = _route_chat(user_id, text, session["history"], agent)

    tg.save_message(user_id, "user", text)
    tg.save_message(user_id, "assistant", reply)

    if TELEGRAM_BOT_TOKEN:
        await _send_telegram_async(user_id, reply)
    else:
        log("No TELEGRAM_BOT_TOKEN — reply not sent", "WARN")

    return {"ok": True, "reply": reply}


@router.post("/tg-chat")
def direct_chat(req: ChatRequest) -> ChatResponse:
    """Direct chat API for testing or non-webhook usage."""
    from app.main import _MEM
    session = tg.get_session(req.user_id)
    history = session["history"]

    agent = tg.route_agent_command(req.message)
    reply = _route_chat(req.user_id, req.message, history, agent)

    tg.save_message(req.user_id, "user", req.message)
    tg.save_message(req.user_id, "assistant", reply)

    return ChatResponse(user_id=req.user_id, reply=reply, agent=agent)


@router.get("/tg-sessions/{user_id}")
def get_session_history(user_id: int):
    """Retrieve session history for a user."""
    session = tg.get_session(user_id)
    return {
        "user_id": user_id,
        "username": session.get("username", "unknown"),
        "history": session["history"],
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _route_chat(user_id: int, message: str, history: list, agent: Optional[str]) -> str:
    if agent == "stats_agent":
        return _stats_agent(message, history)
    if agent == "odds_agent":
        return _odds_agent(message, history)
    if agent == "analyzer_agent":
        return _analyzer_agent(message, history)
    return _general_chat(message, history)


# ---------------------------------------------------------------------------
# Agent handlers — appellent le vrai moteur
# ---------------------------------------------------------------------------

def _stats_agent(message: str, history: list) -> str:
    """@stats_agent : analyse joueur/match depuis les données réelles."""
    from app.main import _MEM
    # Supprimer le tag de la question
    clean = message.replace("@stats_agent", "").strip()

    players = _detect_players_from_mem(clean, _MEM)
    if len(players) >= 2:
        ctx = _predict_context(players[0], players[1], _MEM)
    elif len(players) == 1:
        ctx = _player_context(players[0], _MEM)
    else:
        ctx = ""

    if not ctx:
        return (
            "❓ Précise les joueurs. Ex : @stats_agent Djokovic vs Sinner\n"
            "ou @stats_agent Alcaraz"
        )

    try:
        return chat_mod.chat(
            clean or message,
            history,
            _MEM,
            extra_context=f"[STATS AGENT]\n{ctx}",
        )
    except Exception as e:
        log(f"stats_agent LLM error: {e}", "WARN")
        return f"📊 Stats directes :\n{ctx}"


def _odds_agent(message: str, history: list) -> str:
    """@odds_agent : value bets, EV, cotes depuis le moteur."""
    from app.main import _MEM
    clean = message.replace("@odds_agent", "").strip()

    players = _detect_players_from_mem(clean, _MEM)
    if len(players) >= 2:
        ctx = _value_context(players[0], players[1], _MEM)
    else:
        ctx = _value_list_context(_MEM)

    if not ctx:
        return "❓ Aucune cote live disponible. Vérifie que l'API odds est active."

    try:
        return chat_mod.chat(
            clean or message,
            history,
            _MEM,
            extra_context=f"[ODDS AGENT]\n{ctx}",
        )
    except Exception as e:
        log(f"odds_agent LLM error: {e}", "WARN")
        return f"💎 Value bets :\n{ctx}"


def _analyzer_agent(message: str, history: list) -> str:
    """@analyzer_agent : combine stats + odds pour une synthèse."""
    from app.main import _MEM
    clean = message.replace("@analyzer_agent", "").strip()

    players = _detect_players_from_mem(clean, _MEM)
    ctx_parts = []
    if len(players) >= 2:
        ctx_parts.append(_predict_context(players[0], players[1], _MEM))
        ctx_parts.append(_value_context(players[0], players[1], _MEM))
    ctx = "\n".join(p for p in ctx_parts if p)

    if not ctx:
        return "❓ Précise le match. Ex : @analyzer_agent Djokovic vs Sinner"

    try:
        return chat_mod.chat(
            clean or message,
            history,
            _MEM,
            extra_context=f"[ANALYZER AGENT — synthèse stats + marché]\n{ctx}",
        )
    except Exception as e:
        log(f"analyzer_agent LLM error: {e}", "WARN")
        return f"🔬 Analyse :\n{ctx}"


def _general_chat(message: str, history: list) -> str:
    """Chat général : détecte automatiquement le contexte match/joueur."""
    from app.main import _MEM
    extra = _build_match_context(message, _MEM)
    try:
        return chat_mod.chat(message, history, _MEM, extra_context=extra)
    except Exception as e:
        log(f"General chat error: {e}", "ERROR")
        return f"❌ LLM inaccessible : {e}"


# ---------------------------------------------------------------------------
# Constructeurs de contexte — appellent bot/ directement (même process)
# ---------------------------------------------------------------------------

def _resolve_player(name: str, mem: Dict[str, Any]) -> Optional[str]:
    """Résout un nom de joueur depuis _MEM (namematch + fallback partiel)."""
    from bot import namematch
    players = mem.get("players") or {}
    if name in players:
        return name
    counts = {n: int(p.get("n", 0)) for n, p in players.items()}
    index = namematch.build_index(list(players.keys()), counts)
    return namematch.resolve(name, index)


def _calib_blend_params() -> Tuple[float, float]:
    """Lit (k calibration, w blend marché) appris, mêmes bornes que /value-ai.

    Sans ça, le chat afficherait les probas brutes sur-confiantes du modèle et
    des EV absurdes — incohérent avec /api/value et /value-ai.
    """
    from bot import db, calibrate
    try:
        k = float(db.get_meta("match_calib_k") or 1.0)
        if not (0.1 <= k <= 3.0):
            k = 1.0
    except (TypeError, ValueError):
        k = 1.0
    try:
        w = float(db.get_meta("market_blend_w") or calibrate.DEFAULT_MARKET_BLEND_W)
        w = min(1.0, max(0.0, w))
    except (TypeError, ValueError):
        w = calibrate.DEFAULT_MARKET_BLEND_W
    return k, w


def _detect_players_from_mem(text: str, mem: Dict[str, Any]) -> List[str]:
    """Détecte jusqu'à 2 joueurs connus dans un texte libre."""
    from bot import chat as c
    players_lower = {n.lower(): n for n in (mem.get("players") or {})}
    return c._detect_players(text, players_lower)[:2]


def _predict_context(p1: str, p2: str, mem: Dict[str, Any]) -> str:
    """Prédiction 1er set + match + H2H depuis le moteur local."""
    from bot import predictor, features, db, calibrate

    n1 = _resolve_player(p1, mem) or p1
    n2 = _resolve_player(p2, mem) or p2

    try:
        f1 = features.feature_vector(features.get_profile(mem, n1))
        f2 = features.feature_vector(features.get_profile(mem, n2))
        r = predictor.predict(mem, n1, f1, n2, f2)

        # Proba match best-of-3, CALIBRÉE (temperature scaling appris) — sinon le
        # chat sur-vendrait la confiance du modèle (ex. 93 % au lieu de 60 %).
        k, _ = _calib_blend_params()
        p_set1 = r["prob1"] / 100.0
        p_match1 = calibrate.calibrated_prob(predictor.set_to_match_prob(p_set1), k)
        p_match2 = 1.0 - p_match1

        # H2H
        h2h_rows = db.head_to_head(n1, n2)
        w1 = sum(1 for row in h2h_rows if row["winner"] == n1)
        w2 = sum(1 for row in h2h_rows if row["winner"] == n2)
        last3 = [
            f"  {row['date'][:10]} — {row['winner']} gagne"
            for row in h2h_rows[:3]
        ]

        lines = [
            f"Match : {n1} vs {n2}",
            f"1er set : {n1} {r['prob1']:.1f}% | {n2} {r['prob2']:.1f}%",
            f"Match (best-of-3, calibré) : {n1} {p_match1*100:.1f}% | {n2} {p_match2*100:.1f}%",
            f"Favori : {r['favorite'] or 'très serré'}",
            f"H2H ({w1+w2} confrontations) : {n1} {w1}–{w2} {n2}",
        ]
        if last3:
            lines.append("Dernières confrontations :")
            lines.extend(last3)

        # ELO
        elo = mem.get("elo") or {}
        if n1 in elo or n2 in elo:
            lines.append(
                f"ELO : {n1}={elo.get(n1, 1500):.0f}  {n2}={elo.get(n2, 1500):.0f}"
            )

        return "\n".join(lines)

    except Exception as e:
        log(f"_predict_context error: {e}", "WARN")
        return f"Prédiction {p1} vs {p2} indisponible ({e})"


def _player_context(name: str, mem: Dict[str, Any]) -> str:
    """Fiche joueur : ELO, forme, record."""
    from bot import features, db

    n = _resolve_player(name, mem) or name
    try:
        prof = features.get_profile(mem, n)
        feat = features.feature_vector(prof)
        rec = db.player_record(n)
        form_rows = db.player_recent_matches(n, limit=5)
        form = []
        for row in form_rows:
            won = row["winner"] == n
            opp = row["loser"] if won else row["winner"]
            form.append(f"  {'W' if won else 'L'} vs {opp} ({row['date'][:10]})")

        elo_val = (mem.get("elo") or {}).get(n, 1500)
        total = rec["wins"] + rec["losses"]
        win_rate = rec["wins"] / total if total else 0.0

        lines = [
            f"Joueur : {n}",
            f"ELO : {elo_val:.0f}",
            f"Record : {rec['wins']}V-{rec['losses']}D ({win_rate*100:.1f}%)",
            f"Serve : {feat['serve']:.3f}  Retour1 : {feat['return1']:.3f}  Retour2 : {feat['return2']:.3f}",
            f"Forme récente ({feat['recent']:.3f}) — 5 derniers matchs :",
        ]
        lines.extend(form or ["  (aucune donnée récente)"])
        return "\n".join(lines)

    except Exception as e:
        log(f"_player_context error: {e}", "WARN")
        return f"Stats {name} indisponibles ({e})"


def _fetch_match_odds(n1: str, n2: str) -> Optional[Tuple[float, float]]:
    """Retourne (odds1, odds2) pour n1 vs n2 depuis odds-api.io, ou None."""
    from bot import odds_api
    if not odds_api.is_enabled():
        return None
    events = odds_api.fetch_tennis_events(upcoming_only=True)
    if not events:
        return None
    index = odds_api.build_event_index(events)
    ev = odds_api.find_event(index, n1, n2)
    if not ev:
        return None
    mw = odds_api.fetch_match_winner(ev.get("id") or ev.get("eventId"))
    if not mw:
        return None
    return mw["home_odds"], mw["away_odds"]


def _value_context(p1: str, p2: str, mem: Dict[str, Any]) -> str:
    """EV du match si les cotes sont disponibles."""
    from bot import odds_api, predictor, features, calibrate

    n1 = _resolve_player(p1, mem) or p1
    n2 = _resolve_player(p2, mem) or p2

    if not odds_api.is_enabled():
        return "Odds API désactivée (ODDS_API_KEY non configurée)."
    try:
        pair = _fetch_match_odds(n1, n2)
        if not pair:
            return f"Aucune cote live trouvée pour {n1} vs {n2}."

        o1, o2 = pair
        f1 = features.feature_vector(features.get_profile(mem, n1))
        f2 = features.feature_vector(features.get_profile(mem, n2))
        r = predictor.predict(mem, n1, f1, n2, f2)

        # Proba marché sans vig (normalisée), comme home_prob côté odds_api.
        inv1, inv2 = 1.0 / o1, 1.0 / o2
        pmkt1 = inv1 / (inv1 + inv2)

        # Modèle calibré, PUIS blendé au marché : l'EV doit se calculer sur la
        # proba blendée (sinon un modèle faible voit du value sur tout outsider).
        k, w = _calib_blend_params()
        pm1 = calibrate.calibrated_prob(predictor.set_to_match_prob(r["prob1"] / 100.0), k)
        pb1 = calibrate.blend_probs(pm1, pmkt1, w)
        pb2 = 1.0 - pb1

        ev1 = round(pb1 * o1 - 1, 4)
        ev2 = round(pb2 * o2 - 1, 4)

        lines = [
            f"Value {n1} vs {n2}",
            f"Cotes : {n1}={o1}  {n2}={o2}",
            f"Proba modèle (calibré) : {n1} {pm1*100:.1f}% | {n2} {(1-pm1)*100:.1f}%",
            f"Proba blend (modèle+marché) : {n1} {pb1*100:.1f}% | {n2} {pb2*100:.1f}%",
            f"Proba implicite marché : {n1} {pmkt1*100:.1f}% | {n2} {(1-pmkt1)*100:.1f}%",
            f"EV {n1} : {ev1:+.3f}  EV {n2} : {ev2:+.3f}",
            f"{'✅ VALUE ' + (n1 if ev1 >= ev2 else n2) if max(ev1, ev2) > 0 else '❌ Pas de value'}",
        ]
        return "\n".join(lines)

    except Exception as e:
        log(f"_value_context error: {e}", "WARN")
        return f"EV {p1} vs {p2} indisponible ({e})"


def _value_list_context(mem: Dict[str, Any]) -> str:
    """Top value bets actuels (liste courte)."""
    from bot import odds_api, predictor, features, calibrate

    if not odds_api.is_enabled():
        return "Odds API désactivée — configure ODDS_API_KEY."
    try:
        events = odds_api.fetch_tennis_events(upcoming_only=True)
        if not events:
            return "Aucun événement live trouvé."

        # Mêmes garde-fous que /value-ai : singles pré-match d'abord, ATP/WTA
        # avant Challenger/ITF (les bookmakers du plan ne cotent pas l'ITF), et
        # cap à 12 appels /odds (budget 100 req/h).
        events = [e for e in events
                  if "/" not in (e.get("home", "") + e.get("away", ""))
                  and e.get("status") in ("pending", "not_started")]

        def _prio(e: Dict[str, Any]) -> int:
            lg = (e.get("league") or {}).get("name", "")
            if lg.startswith(("ATP - ", "WTA - ")):
                return 0
            return 1 if ("Challenger" in lg or "125K" in lg) else 2
        events.sort(key=_prio)

        k, w = _calib_blend_params()
        results = []
        for ev in events[:12]:
            r1 = _resolve_player(ev.get("home", ""), mem)
            r2 = _resolve_player(ev.get("away", ""), mem)
            if not (r1 and r2):
                continue
            mw = odds_api.fetch_match_winner(ev.get("id") or ev.get("eventId"))
            if not mw:
                continue
            o1, o2 = mw["home_odds"], mw["away_odds"]
            f1 = features.feature_vector(features.get_profile(mem, r1))
            f2 = features.feature_vector(features.get_profile(mem, r2))
            r = predictor.predict(mem, r1, f1, r2, f2)
            pm1 = calibrate.calibrated_prob(predictor.set_to_match_prob(r["prob1"] / 100.0), k)
            pb1 = calibrate.blend_probs(pm1, mw["home_prob"], w)
            ev1 = pb1 * o1 - 1
            ev2 = (1 - pb1) * o2 - 1
            best = max(ev1, ev2)
            if best > 0:
                side = r1 if ev1 >= ev2 else r2
                cote = o1 if ev1 >= ev2 else o2
                results.append((best, f"  ✅ {r1} vs {r2} → {side} EV={best:+.3f} cote {cote}"))

        if not results:
            return "Aucune value bet détectée pour l'instant."
        results.sort(reverse=True)
        return "Top value bets :\n" + "\n".join(line for _, line in results[:5])
    except Exception as e:
        log(f"_value_list_context error: {e}", "WARN")
        return f"Erreur value list : {e}"


def _build_match_context(message: str, mem: Dict[str, Any]) -> str:
    """Contexte automatique : si 2 joueurs détectés → prédiction + H2H."""
    players = _detect_players_from_mem(message, mem)
    if len(players) >= 2:
        return _predict_context(players[0], players[1], mem)
    if len(players) == 1:
        return _player_context(players[0], mem)
    return ""


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

def _help_text() -> str:
    return (
        "TennisBoss AI 🎾\n\n"
        "Pose n'importe quelle question tennis :\n"
        "• « Djokovic vs Sinner qui gagne ? »\n"
        "• « Fiche Alcaraz »\n\n"
        "Agents spécialisés :\n"
        "• @stats_agent Djokovic vs Nadal\n"
        "• @odds_agent Roland Garros\n"
        "• @analyzer_agent Sinner vs Zverev\n\n"
        "• /clear — effacer l'historique"
    )


async def _send_telegram_async(chat_id: int, text: str):
    import aiohttp
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"chat_id": chat_id, "text": text},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    log(f"Telegram API {resp.status}: {await resp.text()}", "WARN")
    except aiohttp.ClientError as e:
        log(f"Telegram send error: {e}", "WARN")
