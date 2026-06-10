"""FastAPI routes for the hybrid quant betting system."""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.engine import BettingEngine, get_risk_engine
from app.data import odds as odds_mod
from app.data import cache

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
