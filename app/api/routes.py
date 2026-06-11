"""FastAPI routes for the hybrid quant betting system."""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.engine import BettingEngine, get_risk_engine
from app.data import odds as odds_mod
from app.data import cache, market_snap
from app.analytics import spreads, arbitrage, sharp_money, clv

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class MatchRequest(BaseModel):
    player1:  str
    player2:  str
    surface:  Optional[str] = None          # "clay" | "hard" | "grass"
    odds1:    Optional[float] = None        # decimal odds for player1
    odds2:    Optional[float] = None        # decimal odds for player2
    bankroll: Optional[float] = Field(default=None, gt=0)


class BetResultRequest(BaseModel):
    match:  str
    stake:  float
    won:    bool


# ---------------------------------------------------------------------------
# Dependency: BettingEngine with loaded mem
# ---------------------------------------------------------------------------

def get_engine() -> BettingEngine:
    from app.main import _MEM
    return BettingEngine(_MEM)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/analyze-match")
def analyze_match(req: MatchRequest, engine: BettingEngine = Depends(get_engine)):
    """Full pipeline: 4 models → consensus → EV → Kelly → risk decision."""
    cache_key = f"{req.player1}|{req.player2}|{req.surface}|{req.odds1}|{req.odds2}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Auto-fetch odds if not provided
    odds1, odds2 = req.odds1, req.odds2
    if not (odds1 and odds2):
        live = odds_mod.fetch_match_odds(req.player1, req.player2)
        if live:
            odds1, odds2 = live

    result = engine.analyze_match(
        player1  = req.player1,
        player2  = req.player2,
        surface  = req.surface,
        odds1    = odds1,
        odds2    = odds2,
        bankroll = req.bankroll,
    )
    cache.set(cache_key, result, ttl=30.0)
    return result


@router.get("/analyze-match")
def analyze_match_get(
    player1:  str = Query(...),
    player2:  str = Query(...),
    surface:  Optional[str]   = Query(default=None),
    odds1:    Optional[float]  = Query(default=None),
    odds2:    Optional[float]  = Query(default=None),
    bankroll: Optional[float]  = Query(default=None),
    engine: BettingEngine = Depends(get_engine),
):
    """GET convenience wrapper — same logic as POST."""
    req = MatchRequest(player1=player1, player2=player2,
                       surface=surface, odds1=odds1, odds2=odds2,
                       bankroll=bankroll)
    return analyze_match(req, engine)


@router.post("/bet-result")
def record_result(req: BetResultRequest):
    """Record a settled bet outcome for P&L tracking."""
    get_risk_engine().record_result(req.stake, req.won, req.match)
    return {"recorded": True, "bankroll": get_risk_engine().bankroll}


# ---------------------------------------------------------------------------
# Analytics endpoints (Phase 1: edge detection)
# ---------------------------------------------------------------------------

@router.post("/v2/spread-analysis")
def analyze_spread(req: MatchRequest, engine: BettingEngine = Depends(get_engine)):
	"""Analyze spread: model vs implied probability."""
	odds1, odds2 = req.odds1, req.odds2
	if not (odds1 and odds2):
		live = odds_mod.fetch_match_odds(req.player1, req.player2)
		if live:
			odds1, odds2 = live
		else:
			raise HTTPException(status_code=400, detail="Odds required")

	# Get model probability
	engine_result = engine.analyze_match(
		player1=req.player1,
		player2=req.player2,
		surface=req.surface,
		odds1=odds1,
		odds2=odds2,
	)

	prob1 = engine_result.get("consensus_prob", 0.5)
	prob2 = 1.0 - prob1

	# Spread analysis for both sides
	spread_s1 = spreads.spread_analysis(prob1, odds1, odds2, confidence=engine_result.get("confidence", 0.75))
	spread_s2 = spreads.spread_analysis(prob2, odds2, odds1, confidence=engine_result.get("confidence", 0.75))

	return {
		"match": f"{req.player1} vs {req.player2}",
		"model_prob_p1": prob1,
		"model_prob_p2": prob2,
		"odds_p1": odds1,
		"odds_p2": odds2,
		"spread_p1": spread_s1,
		"spread_p2": spread_s2,
		"recommendation": spread_s1["recommendation"] if spread_s1["ev"] > spread_s2["ev"] else spread_s2["recommendation"],
	}


@router.post("/v2/arbitrage-check")
def check_arbitrage(req: MatchRequest):
	"""Detect arbitrage across odds."""
	odds1, odds2 = req.odds1, req.odds2
	if not (odds1 and odds2):
		live = odds_mod.fetch_match_odds(req.player1, req.player2)
		if live:
			odds1, odds2 = live
		else:
			raise HTTPException(status_code=400, detail="Odds required")

	result = arbitrage.check_arbitrage(odds1, odds2, threshold=0.01)

	return {
		"match": f"{req.player1} vs {req.player2}",
		"odds": {"side1": odds1, "side2": odds2},
		**result,
	}


@router.get("/v2/market-analysis")
def market_analysis(
	player1: str = Query(...),
	player2: str = Query(...),
	surface: Optional[str] = Query(None),
	odds1: Optional[float] = Query(None),
	odds2: Optional[float] = Query(None),
	engine: BettingEngine = Depends(get_engine),
):
	"""Combined market analysis: spreads + arb + engine consensus."""
	if not (odds1 and odds2):
		live = odds_mod.fetch_match_odds(player1, player2)
		if live:
			odds1, odds2 = live

	# Get engine consensus
	engine_result = engine.analyze_match(
		player1=player1,
		player2=player2,
		surface=surface,
		odds1=odds1,
		odds2=odds2,
	)

	prob1 = engine_result.get("consensus_prob", 0.5)

	# Analytics
	spread_s1 = spreads.spread_analysis(prob1, odds1, odds2)
	arb = arbitrage.check_arbitrage(odds1, odds2)

	return {
		"match": f"{player1} vs {player2}",
		"model_consensus": {
			"prob_p1": prob1,
			"confidence": engine_result.get("confidence", 0.75),
		},
		"spread": spread_s1,
		"arbitrage": arb,
		"recommendation": engine_result.get("recommendation", "PASS"),
	}


@router.post("/v2/record-market-snapshot")
def record_snapshot(
	match_id: str,
	odds_side1: float,
	odds_side2: float,
	volume: float = 0.0,
	is_sharp: bool = False,
):
	"""Record a market snapshot for line movement tracking."""
	import os
	db_path = os.environ.get("DB_PATH", "bot/state.db")
	snapshot_id = market_snap.record_snapshot(
		db_path,
		match_id,
		odds_side1,
		odds_side2,
		volume,
		is_sharp,
	)
	return {"snapshot_id": snapshot_id, "match_id": match_id}


@router.get("/v2/line-movement")
def get_line_movement(match_id: str = Query(...)):
	"""Get line movement stats for a match."""
	import os
	db_path = os.environ.get("DB_PATH", "bot/state.db")
	result = market_snap.line_movement_stats(db_path, match_id)
	return result

@router.get("/risk-status")
def risk_status():
    """Current risk engine state."""
    risk = get_risk_engine()
    return {
        "bankroll":      round(risk.bankroll, 2),
        "exposure":      risk.exposure,
        "daily_pnl":     risk.daily_pnl,
        "drawdown_pct":  risk.drawdown_pct,
    }


@router.get("/bet-history")
def bet_history(limit: int = Query(default=50, le=500)):
    """Last N bet decisions from SQLite."""
    from app.core.risk import DB_PATH
    try:
        with sqlite3.connect(DB_PATH) as cx:
            cx.row_factory = sqlite3.Row
            rows = cx.execute(
                "SELECT * FROM bet_decisions ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))


@router.get("/value-ai")
def value_ai(
    limit:      int           = Query(default=15, ge=1, le=50),
    min_ev:     float         = Query(default=0.0,  description="Filtre EV minimum (ex: 0.03 = +3%)"),
    min_conf:   float         = Query(default=0.0,  description="Confiance resolver minimum (0–1)"),
    value_only: bool          = Query(default=False, description="Retourner seulement les value bets EV>0"),
):
    """Scanner de value bets hybride — couverture totale via AI resolver (timeout guard).

    Pour chaque match tennis live/upcoming :
      1. AI Resolver tente de résoudre les deux joueurs (DB → Wikipedia → peer inference)
      2. Si bookmaker disponible → EV réel (proba modèle × cote marché − 1)
      3. Sinon → EV synthétique (écart modèle vs cote fair)
    Résultats triés par EV décroissant.

    NOTE: resolve_match() peut être coûteux (web scraping). On limit à 30 matches.
    """
    from app.main import _MEM
    from bot import odds_api, predictor, features, db as _db
    from bot.ai_resolver import resolve_match, cache_stats

    if not odds_api.is_enabled():
        raise HTTPException(status_code=503, detail="ODDS_API_KEY absente")

    events = odds_api.fetch_tennis_events(upcoming_only=True)
    if not events:
        return {"count": 0, "results": [], "resolver_cache": cache_stats()}

    # Le cap [:30] prendrait les 30 premiers événements dans l'ordre API (ITF
    # d'abord, jamais cotés par les bookmakers du plan). On exclut les doubles
    # et les matchs live (le modèle est pré-match : comparé à des cotes live
    # qui intègrent le score, l'EV serait absurde), puis on scanne ATP/WTA en
    # premier, ensuite Challenger/125K, enfin le reste.
    events = [e for e in events
              if "/" not in (e.get("home", "") + e.get("away", ""))
              and e.get("status") in ("pending", "not_started")]

    def _league_prio(e: Dict[str, Any]) -> int:
        lg = (e.get("league") or {}).get("name", "")
        if lg.startswith(("ATP - ", "WTA - ")):
            return 0
        if "Challenger" in lg or "125K" in lg:
            return 1
        return 2

    events.sort(key=_league_prio)

    # Calibration factor (temperature scaling)
    # Sanity-clamp: k must be in [0.5, 2.0] — outside this range the DB value
    # is stale/broken and we fall back to neutral (k=1.0).
    try:
        raw_k = float(_db.get_meta("match_calib_k") or 1.0)
        calib_k = raw_k if 0.5 <= raw_k <= 2.0 else 1.0
    except Exception:
        calib_k = 1.0

    def _calib(p: float) -> float:
        import math
        p = max(0.01, min(0.99, p))  # clamp before logit
        if calib_k == 1.0:
            return p
        logit = math.log(p / (1 - p)) / calib_k
        return 1 / (1 + math.exp(-logit))

    results: List[Dict[str, Any]] = []

    # Copie locale : les profils synthétiques (peer inference) injectés pour la
    # prédiction ne doivent pas polluer la mémoire globale du serveur.
    mem = dict(_MEM)
    mem["players"] = dict(_MEM.get("players") or {})

    for ev in events[:30]:  # GUARD: cap à 30 matches pour éviter timeout resolve_match
        home_raw = ev.get("home", "")
        away_raw = ev.get("away", "")
        league   = (ev.get("league") or {}).get("name", "")

        # ── Resolve players ──────────────────────────────────────────────
        p1r, p2r = resolve_match(home_raw, away_raw, mem, league=league)
        conf = min(p1r.confidence, p2r.confidence)
        if conf < min_conf:
            continue

        n1, n2 = p1r.resolved, p2r.resolved

        # Inject peer profiles if needed
        players = mem["players"]
        if p1r.profile and n1 not in players:
            players[n1] = p1r.profile
        if p2r.profile and n2 not in players:
            players[n2] = p2r.profile

        # ── Model prediction ──────────────────────────────────────────────
        try:
            f1 = features.feature_vector(features.get_profile(mem, n1))
            f2 = features.feature_vector(features.get_profile(mem, n2))
            r  = predictor.predict(mem, n1, f1, n2, f2)
            pm1 = _calib(predictor.set_to_match_prob(r["prob1"] / 100.0))
            pm2 = 1.0 - pm1
        except Exception:
            continue

        # ── Market odds (optional) ────────────────────────────────────────
        mw = odds_api.fetch_match_winner(ev["id"])

        # Only trust EV vs real odds when BOTH players are reliably resolved.
        # Peer-inferred profiles (conf < 0.60) produce unreliable probabilities.
        reliable = p1r.confidence >= 0.60 and p2r.confidence >= 0.60

        if mw and reliable:
            ho, ao = mw["home_odds"], mw["away_odds"]
            ev1 = pm1 * ho - 1.0
            ev2 = pm2 * ao - 1.0
            source = "bookmaker"
            books  = mw["books"]
        elif mw and not reliable:
            ho, ao = mw["home_odds"], mw["away_odds"]
            ev1 = ev2 = 0.0
            source = "bookmaker_low_conf"
            books  = mw["books"]
        else:
            # Synthetic: model IS the market — no edge by definition,
            # but we surface the fair odds so the user sees the full picture.
            # Guard: only show fair odds when model is not near-certain (avoid 1/~0).
            ho = round(1 / pm1, 2) if pm1 >= 0.02 else None
            ao = round(1 / pm2, 2) if pm2 >= 0.02 else None
            ev1 = ev2 = 0.0
            source = "model_only"
            books  = []

        best_ev   = max(ev1, ev2)
        best_side = n1 if ev1 >= ev2 else n2
        best_odds = ho if ev1 >= ev2 else ao

        if value_only and best_ev <= 0:
            continue
        if best_ev < min_ev:
            continue

        results.append({
            "player1":      n1,
            "player2":      n2,
            "raw1":         home_raw,
            "raw2":         away_raw,
            "league":       league,
            "status":       ev.get("status", ""),
            "date":         ev.get("date", ""),
            # Resolution quality
            "resolver": {
                "p1_source": p1r.source, "p1_conf": round(p1r.confidence, 2),
                "p2_source": p2r.source, "p2_conf": round(p2r.confidence, 2),
            },
            # Model
            "model_prob1":  round(pm1 * 100, 1),
            "model_prob2":  round(pm2 * 100, 1),
            # Market
            "odds":         {"home": ho, "away": ao, "books": books},
            "market_prob1": round(mw["home_prob"] * 100, 1) if mw else None,
            "market_prob2": round(mw["away_prob"] * 100, 1) if mw else None,
            # Value
            "ev1":          round(ev1 * 100, 1),
            "ev2":          round(ev2 * 100, 1),
            "best_side":    best_side if best_ev > 0 else None,
            "best_ev":      round(best_ev * 100, 1),
            "best_odds":    best_odds,
            "value":        best_ev > 0,
            "source":       source,
            "confidence":   round(conf, 2),
        })

    results.sort(key=lambda x: (x["value"], x["best_ev"]), reverse=True)
    results = results[:limit]

    return {
        "count":          len(results),
        "value_count":    sum(1 for r in results if r["value"]),
        "calib_k":        round(calib_k, 3),
        "results":        results,
        "resolver_cache": cache_stats(),
    }


@router.get("/health")
def health():
    from app.main import _MEM
    return {
        "service":        "TennisBoss Quant",
        "status":         "ok",
        "players_loaded": len(_MEM.get("players") or {}),
        "elo_loaded":     bool(_MEM.get("elo")),
        "cache_size":     cache.size(),
    }


@router.get("/dashboard", include_in_schema=False)
def dashboard():
    """Serve real-time ROI dashboard."""
    import os
    dashboard_path = os.path.join(os.path.dirname(__file__), "..", "static", "realtime-dashboard.html")
    return FileResponse(dashboard_path, media_type="text/html")
