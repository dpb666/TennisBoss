"""Risk management API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query, Depends
from typing import Optional

from app.risk import (
	portfolio_greeks,
	drawdown_alerts,
	volatility_norm,
	correlation_matrix,
	scenario_analysis,
)
from app.core.engine import get_risk_engine

router = APIRouter(prefix="/v2/risk", tags=["risk"])

# Global instances
_drawdown_alerts: Optional[drawdown_alerts.DrawdownAlerts] = None
_correlation_matrix: Optional[correlation_matrix.CorrelationMatrix] = None


def init_risk_engines():
	"""Initialize risk engines."""
	global _drawdown_alerts, _correlation_matrix
	engine = get_risk_engine()
	_drawdown_alerts = drawdown_alerts.DrawdownAlerts(peak_bankroll=engine.bankroll)
	_correlation_matrix = correlation_matrix.CorrelationMatrix()


@router.get("/portfolio-greeks")
def get_portfolio_greeks(
	positions: Optional[list[dict]] = None,
):
	"""Calculate portfolio Greeks (Delta, Vega, Theta)."""
	if positions is None:
		positions = []

	summary = portfolio_greeks.PortfolioGreeks.portfolio_summary(positions)

	return {
		"greeks": summary,
		"interpretation": {
			"delta": "Exposure to player outcomes",
			"vega": "Exposure to confidence changes",
			"theta": "Time decay effect",
		},
	}


@router.post("/update-bankroll")
def update_bankroll(current_bankroll: float = Query(...)):
	"""Update bankroll and check drawdown alerts."""
	if not _drawdown_alerts:
		init_risk_engines()

	_drawdown_alerts.update_bankroll(current_bankroll)
	alert = _drawdown_alerts.drawdown_alert()
	recovery = _drawdown_alerts.recovery_needed()

	return {
		"alert": alert,
		"recovery": recovery,
		"kelly_scale_factor": alert["kelly_scale"],
	}


@router.get("/drawdown-status")
def get_drawdown_status():
	"""Get current drawdown status."""
	if not _drawdown_alerts:
		init_risk_engines()

	alert = _drawdown_alerts.drawdown_alert()
	recovery = _drawdown_alerts.recovery_needed()

	return {
		"current_alert": alert,
		"recovery_needed": recovery,
	}


@router.post("/volatility-normalize")
def normalize_stakes(body: dict):
	"""Normalize stakes by volatility."""
	positions = body.get("positions", [])
	normalizer = volatility_norm.VolatilityNormalizer()
	result = normalizer.multi_surface_portfolio(positions)

	return result


@router.post("/correlation-check")
def check_correlation(body: dict):
	"""Check if new position is correlated with portfolio."""
	if not _correlation_matrix:
		init_risk_engines()

	new_player = body.get("new_player", "")
	existing_positions = body.get("existing_positions", [])

	result = _correlation_matrix.analyze_exposure(
		new_player,
		existing_positions,
		correlation_threshold=0.5,
	)

	return result


@router.post("/correlation-matrix")
def build_correlation_matrix(body: dict):
	"""Build full correlation matrix."""
	if not _correlation_matrix:
		init_risk_engines()

	positions = body.get("positions", [])
	matrix = _correlation_matrix.portfolio_correlation_matrix(positions)

	return matrix


@router.post("/cluster-detection")
def detect_clusters(body: dict):
	"""Detect correlated player clusters."""
	if not _correlation_matrix:
		init_risk_engines()

	positions = body.get("positions", [])
	clusters = _correlation_matrix.cluster_detection(positions, correlation_threshold=0.6)

	return {
		"clusters": clusters,
		"risk_interpretation": (
			"HIGH_RISK: Large cluster detected" if clusters["max_cluster_size"] > 3
			else "MEDIUM_RISK: Moderate clustering" if clusters["max_cluster_size"] > 1
			else "LOW_RISK: Diversified portfolio"
		),
	}


@router.post("/stress-test")
def run_stress_test(body: dict):
	"""Run full stress test scenarios."""
	positions = body.get("positions", [])
	bankroll = body.get("bankroll", 1000)
	stress = scenario_analysis.ScenarioAnalyzer.full_stress_test(positions, bankroll)

	return {
		"stress_test": stress,
		"summary": {
			"worst_case_pct": stress["worst_case_loss_pct"],
			"best_case_pct": stress["best_case_gain_pct"],
			"risk_reward": stress["risk_reward_ratio"],
		},
	}


@router.post("/var-cvar")
def calculate_risk_metrics(body: dict):
	"""Calculate Value at Risk and Conditional Value at Risk."""
	positions = body.get("positions", [])
	risk = scenario_analysis.ScenarioAnalyzer.var_cvar(positions, confidence_level=0.95)

	return {
		"risk_metrics": risk,
		"interpretation": f"95% confidence: loss will not exceed ${abs(risk['var_95_pct']):.2f}",
	}


@router.get("/portfolio-risk")
def comprehensive_risk_report():
	"""Comprehensive portfolio risk report."""
	if not _drawdown_alerts or not _correlation_matrix:
		init_risk_engines()

	positions = []
	greeks = portfolio_greeks.PortfolioGreeks.portfolio_summary(positions)
	drawdown = _drawdown_alerts.drawdown_alert()
	clusters = _correlation_matrix.cluster_detection(positions)

	return {
		"greeks": greeks,
		"drawdown": drawdown,
		"clusters": clusters,
		"overall_risk": (
			"CRITICAL" if drawdown["tier"] == "red"
			else "HIGH" if drawdown["tier"] == "orange" or clusters["max_cluster_size"] > 3
			else "MEDIUM" if drawdown["tier"] == "yellow"
			else "LOW"
		),
	}


@router.get("/risk-alerts")
def get_risk_alerts():
	"""Get all active risk alerts."""
	if not _drawdown_alerts:
		init_risk_engines()

	alert = _drawdown_alerts.drawdown_alert()
	alerts = []

	if alert["status"] != "NO_DRAWDOWN":
		alerts.append({
			"type": "DRAWDOWN",
			"severity": alert["tier"],
			"message": alert["message"],
			"action": f"Reduce Kelly to {alert['kelly_scale']*100:.0f}%",
		})

	return {
		"active_alerts": len(alerts),
		"alerts": alerts,
	}
