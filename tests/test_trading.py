"""Unit tests for trading modules."""
import pytest
from app.trading import (
	auto_bet_engine,
	kelly_dynamic,
	position_tracker,
	hedge_manager,
)


class TestAutoBetEngine:
	def test_should_place_bet_good_ev(self):
		engine = auto_bet_engine.AutoBetEngine()
		should_bet, reason, stake_pct = engine.should_place_bet(
			model_prob=0.58,
			odds=1.85,
			confidence=0.75,
		)
		assert should_bet
		assert stake_pct > 0

	def test_should_place_bet_low_confidence(self):
		engine = auto_bet_engine.AutoBetEngine()
		should_bet, reason, stake_pct = engine.should_place_bet(
			model_prob=0.58,
			odds=1.85,
			confidence=0.50,
		)
		assert not should_bet

	def test_place_bet_records_decision(self):
		engine = auto_bet_engine.AutoBetEngine()
		result = engine.place_bet(
			match_id="m1",
			player="Player A",
			model_prob=0.58,
			odds=1.85,
			confidence=0.75,
			bankroll=1000,
		)
		assert result["status"] in ["APPROVED", "REJECTED"]
		assert len(engine.decisions) == 1


class TestKellyDynamic:
	def test_kelly_fraction_basic(self):
		kelly = kelly_dynamic.kelly_fraction(0.55, 2.0, kelly_pct=0.25)
		assert 0 <= kelly <= 0.25

	def test_confidence_adjusted(self):
		kelly_low = kelly_dynamic.confidence_adjusted_kelly(0.55, 2.0, 0.50)
		kelly_high = kelly_dynamic.confidence_adjusted_kelly(0.55, 2.0, 0.90)
		assert kelly_low < kelly_high

	def test_volatility_adjusted(self):
		kelly_low_vol = kelly_dynamic.volatility_adjusted_kelly(
			0.55, 2.0, portfolio_volatility=0.01
		)
		kelly_high_vol = kelly_dynamic.volatility_adjusted_kelly(
			0.55, 2.0, portfolio_volatility=0.05
		)
		assert kelly_low_vol > kelly_high_vol

	def test_drawdown_adjusted(self):
		kelly_no_dd = kelly_dynamic.drawdown_adjusted_kelly(0.05, 0.0)
		kelly_with_dd = kelly_dynamic.drawdown_adjusted_kelly(0.05, -5.0)
		assert kelly_with_dd < kelly_no_dd

	def test_composite_kelly(self):
		result = kelly_dynamic.composite_kelly(
			prob=0.58,
			odds=1.85,
			confidence=0.75,
			portfolio_volatility=0.02,
			current_drawdown_pct=-2.0,
		)
		assert "final_kelly_fraction" in result
		assert result["final_kelly_fraction"] > 0
		assert result["final_kelly_fraction"] <= 0.10


class TestPositionTracker:
	def test_open_position(self):
		tracker = position_tracker.PositionTracker()
		pos = tracker.open_position(
			bet_id="b1",
			match_id="m1",
			player="Player A",
			stake=100,
			odds=1.85,
			model_prob=0.58,
			confidence=0.75,
		)
		assert pos["status"] == "OPEN"
		assert pos["stake"] == 100

	def test_close_position_win(self):
		tracker = position_tracker.PositionTracker()
		tracker.open_position("b1", "m1", "A", 100, 1.85, 0.58, 0.75)
		closed = tracker.close_position("b1", result=True)
		assert closed["result"] == "WIN"
		assert abs(closed["final_pnl"] - 85.0) < 0.01  # Account for float precision

	def test_portfolio_exposure(self):
		tracker = position_tracker.PositionTracker()
		tracker.open_position("b1", "m1", "A", 100, 1.85, 0.58, 0.75)
		tracker.open_position("b2", "m2", "B", 150, 2.0, 0.50, 0.70)

		exposure = tracker.portfolio_exposure()
		assert exposure["num_open"] == 2
		assert exposure["total_stake"] == 250

	def test_summary(self):
		tracker = position_tracker.PositionTracker()
		tracker.open_position("b1", "m1", "A", 100, 1.85, 0.58, 0.75)
		tracker.close_position("b1", True)

		summary = tracker.summary()
		assert summary["settled"]["wins"] == 1


class TestHedgeManager:
	def test_calculate_hedge_profitable(self):
		manager = hedge_manager.HedgeManager()
		hedge = manager.calculate_hedge(
			original_stake=100,
			original_odds=1.80,
			current_odds=2.00,  # Odds improved
		)
		assert hedge["hedge"]["pnl_if_closed"] > 0

	def test_hedge_with_opposite_bet(self):
		manager = hedge_manager.HedgeManager()
		hedge = manager.hedge_with_opposite_bet(
			original_stake=100,
			original_odds_for=1.80,
			current_odds_against=2.00,
		)
		assert "hedge" in hedge
		assert hedge["hedge"]["stake_to_place"] > 0

	def test_batch_hedge_check(self):
		manager = hedge_manager.HedgeManager()
		positions = [
			{"stake": 100, "odds": 1.80, "current_odds": 2.00},
			{"stake": 150, "odds": 1.90, "current_odds": 1.85},
		]
		hedges = manager.batch_hedge_check(positions)
		assert len(hedges) == 2


if __name__ == "__main__":
	pytest.main([__file__, "-v"])
