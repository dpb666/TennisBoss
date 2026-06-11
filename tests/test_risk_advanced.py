"""Tests for advanced risk management."""
import pytest
from app.risk import (
	portfolio_greeks,
	drawdown_alerts,
	volatility_norm,
	correlation_matrix,
	scenario_analysis,
)


class TestPortfolioGreeks:
	def test_calculate_delta(self):
		positions = [
			{"player": "Federer", "stake": 100, "model_prob": 0.60, "odds": 1.80},
			{"player": "Nadal", "stake": 150, "model_prob": 0.55, "odds": 1.90},
		]
		delta = portfolio_greeks.PortfolioGreeks.calculate_delta(positions)
		assert "total_delta" in delta
		assert "delta_by_player" in delta

	def test_calculate_vega(self):
		positions = [
			{"stake": 100, "confidence": 0.75},
			{"stake": 100, "confidence": 0.85},
		]
		vega = portfolio_greeks.PortfolioGreeks.calculate_vega(positions)
		assert vega["vega"] >= 0
		assert vega["avg_confidence"] > 0

	def test_portfolio_summary(self):
		positions = [
			{"player": "A", "stake": 100, "model_prob": 0.55, "odds": 1.85, "confidence": 0.75},
			{"player": "B", "stake": 150, "model_prob": 0.60, "odds": 1.90, "confidence": 0.80},
		]
		summary = portfolio_greeks.PortfolioGreeks.portfolio_summary(positions)
		assert "delta" in summary
		assert "vega" in summary
		assert "theta" in summary


class TestDrawdownAlerts:
	def test_no_drawdown(self):
		alerts = drawdown_alerts.DrawdownAlerts(peak_bankroll=1000)
		alerts.update_bankroll(1000)
		alert = alerts.drawdown_alert()
		assert alert["status"] == "NO_DRAWDOWN"

	def test_minor_drawdown(self):
		alerts = drawdown_alerts.DrawdownAlerts(peak_bankroll=1000)
		alerts.update_bankroll(990)
		alert = alerts.drawdown_alert()
		assert alert["tier"] == "green"

	def test_yellow_alert(self):
		alerts = drawdown_alerts.DrawdownAlerts(peak_bankroll=1000)
		alerts.update_bankroll(960)  # 4% DD
		alert = alerts.drawdown_alert()
		assert alert["tier"] == "yellow"
		assert alert["kelly_scale"] == 0.75

	def test_recovery_calculation(self):
		alerts = drawdown_alerts.DrawdownAlerts(peak_bankroll=1000)
		alerts.update_bankroll(900)
		recovery = alerts.recovery_needed()
		assert recovery["recovery_needed_amount"] == 100
		assert recovery["recovery_needed_pct"] > 0


class TestVolatilityNorm:
	def test_normalize_stake(self):
		normalizer = volatility_norm.VolatilityNormalizer(baseline_volatility=0.02)
		result = normalizer.normalize_stake(100, current_volatility=0.01)
		assert result["normalized_stake"] > 100  # Lower vol → larger stake

	def test_normalize_by_surface(self):
		normalizer = volatility_norm.VolatilityNormalizer()
		result = normalizer.normalize_by_surface(100, surface="hard")
		assert result["surface"] == "hard"
		assert result["normalized_stake"] > 0

	def test_multi_surface(self):
		normalizer = volatility_norm.VolatilityNormalizer()
		positions = [
			{"surface": "hard", "stake": 100, "current_vol": 0.025},
			{"surface": "clay", "stake": 100, "current_vol": 0.018},
		]
		result = normalizer.multi_surface_portfolio(positions)
		assert len(result["positions"]) == 2


class TestCorrelationMatrix:
	def test_add_and_get_correlation(self):
		corr_matrix = correlation_matrix.CorrelationMatrix()
		corr_matrix.add_correlation("Fed", "Nad", 0.65)
		assert corr_matrix.get_correlation("Fed", "Nad") == 0.65

	def test_analyze_exposure(self):
		corr_matrix = correlation_matrix.CorrelationMatrix()
		corr_matrix.add_correlation("Fed", "Djok", 0.70)

		positions = [{"player": "Fed", "stake": 500, "confidence": 0.75}]
		result = corr_matrix.analyze_exposure("Djok", positions, correlation_threshold=0.6)
		assert result["is_high_correlation"]

	def test_build_from_rankings(self):
		corr_matrix = correlation_matrix.CorrelationMatrix()
		rankings = {"Fed": 1, "Nad": 2, "Djok": 3, "Murray": 20}
		corr_matrix.build_from_rankings(rankings)

		fed_nad = corr_matrix.get_correlation("Fed", "Nad")
		fed_murray = corr_matrix.get_correlation("Fed", "Murray")
		assert fed_nad > fed_murray  # Close ranks more correlated


class TestScenarioAnalysis:
	def test_max_loss_scenario(self):
		positions = [
			{"stake": 100, "odds": 2.0},
			{"stake": 150, "odds": 1.85},
		]
		scenario = scenario_analysis.ScenarioAnalyzer.max_loss_scenario(positions)
		assert scenario["max_loss"] == -250

	def test_best_case_scenario(self):
		positions = [
			{"stake": 100, "odds": 2.0},
			{"stake": 100, "odds": 2.0},
		]
		scenario = scenario_analysis.ScenarioAnalyzer.best_case_scenario(positions)
		assert scenario["max_profit"] == 200  # 100 * 1 + 100 * 1

	def test_var_cvar(self):
		positions = [
			{"stake": 100, "model_prob": 0.55},
			{"stake": 100, "model_prob": 0.60},
		]
		risk = scenario_analysis.ScenarioAnalyzer.var_cvar(positions)
		assert risk["var_95_pct"] < 0

	def test_full_stress_test(self):
		positions = [
			{"stake": 100, "odds": 1.85, "model_prob": 0.55, "confidence": 0.75},
		]
		stress = scenario_analysis.ScenarioAnalyzer.full_stress_test(positions, bankroll=1000)
		assert stress["worst_case_loss"] == -100
		assert stress["best_case_gain"] == 85
		assert "scenarios" in stress


if __name__ == "__main__":
	pytest.main([__file__, "-v"])
