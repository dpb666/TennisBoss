"""Trading automation API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel
from typing import Optional

from app.trading import (
	auto_bet_engine,
	kelly_dynamic,
	position_tracker,
	hedge_manager,
)
from app.core.engine import get_risk_engine

router = APIRouter(prefix="/v2/trading", tags=["trading"])

# Global instances
_auto_bet_engine: Optional[auto_bet_engine.AutoBetEngine] = None
_position_tracker: Optional[position_tracker.PositionTracker] = None
_hedge_manager: Optional[hedge_manager.HedgeManager] = None


def init_trading_engines():
	"""Initialize trading engines."""
	global _auto_bet_engine, _position_tracker, _hedge_manager
	_auto_bet_engine = auto_bet_engine.AutoBetEngine()
	_position_tracker = position_tracker.PositionTracker()
	_hedge_manager = hedge_manager.HedgeManager()


# Pydantic models

class PlaceBetRequest(BaseModel):
	match_id: str
	player: str
	model_prob: float
	odds: float
	confidence: float = 0.75
	auto_place: bool = False


class UpdatePositionRequest(BaseModel):
	bet_id: str
	current_odds: float


class ClosePositionRequest(BaseModel):
	bet_id: str
	result: bool  # True = won


# Endpoints

@router.post("/auto-bet")
def auto_bet(req: PlaceBetRequest):
	"""Auto-place bet if EV + confidence thresholds met."""
	if not _auto_bet_engine:
		init_trading_engines()

	engine = _auto_bet_engine
	bankroll = get_risk_engine().bankroll

	result = engine.place_bet(
		match_id=req.match_id,
		player=req.player,
		model_prob=req.model_prob,
		odds=req.odds,
		confidence=req.confidence,
		bankroll=bankroll,
	)

	if result["should_place"] and req.auto_place:
		# Record open position
		_position_tracker.open_position(
			bet_id=f"{req.match_id}_{result['player']}",
			match_id=req.match_id,
			player=req.player,
			stake=result["stake_amount"],
			odds=req.odds,
			model_prob=req.model_prob,
			confidence=req.confidence,
		)

	return result


@router.post("/dynamic-kelly")
def calculate_kelly(
	prob: float = Query(...),
	odds: float = Query(...),
	confidence: float = Query(default=0.75),
	portfolio_vol: float = Query(default=0.02),
	current_dd: float = Query(default=0.0),
):
	"""Calculate dynamic Kelly stake."""
	result = kelly_dynamic.composite_kelly(
		prob=prob,
		odds=odds,
		confidence=confidence,
		portfolio_volatility=portfolio_vol,
		current_drawdown_pct=current_dd,
	)
	return result


@router.get("/open-positions")
def get_open_positions():
	"""Get all open positions."""
	if not _position_tracker:
		init_trading_engines()

	summary = _position_tracker.summary()
	open_pos = _position_tracker.get_open_positions()

	return {
		"summary": summary,
		"positions": open_pos,
	}


@router.post("/update-position")
def update_position(req: UpdatePositionRequest):
	"""Update position live P&L (for potential hedging)."""
	if not _position_tracker:
		init_trading_engines()

	pnl = _position_tracker.update_live_pnl(req.bet_id, req.current_odds)

	return {
		"bet_id": req.bet_id,
		"current_pnl": pnl,
	}


@router.post("/close-position")
def close_position(req: ClosePositionRequest):
	"""Close position after settlement."""
	if not _position_tracker:
		init_trading_engines()

	closed = _position_tracker.close_position(req.bet_id, req.result)

	return {
		"bet_id": req.bet_id,
		"result": closed["result"] if closed else "NOT_FOUND",
		"final_pnl": closed.get("final_pnl", 0) if closed else 0,
	}


@router.post("/hedge-calculate")
def calculate_hedge(
	bet_id: str = Query(...),
	original_stake: float = Query(...),
	original_odds: float = Query(...),
	current_odds: float = Query(...),
):
	"""Calculate hedge for a position."""
	if not _hedge_manager:
		init_trading_engines()

	hedge = _hedge_manager.calculate_hedge(
		original_stake,
		original_odds,
		current_odds,
	)

	return {
		"bet_id": bet_id,
		**hedge,
	}


@router.get("/hedge-summary")
def hedge_summary():
	"""Summary of all hedging opportunities."""
	if not _position_tracker or not _hedge_manager:
		init_trading_engines()

	open_pos = _position_tracker.get_open_positions()

	summary = _hedge_manager.hedge_summary(
		[{
			"stake": p["stake"],
			"odds": p["odds"],
			"current_odds": p.get("current_odds", p["odds"]),
		} for p in open_pos]
	)

	return summary


@router.get("/trading-status")
def trading_status():
	"""Overall trading status."""
	if not _position_tracker or not _auto_bet_engine:
		init_trading_engines()

	portfolio = _position_tracker.summary()
	decisions = _auto_bet_engine.get_decisions()

	return {
		"portfolio": portfolio,
		"auto_bet_decisions": len(decisions),
		"approved_bets": len([d for d in decisions if d["status"] == "APPROVED"]),
	}
