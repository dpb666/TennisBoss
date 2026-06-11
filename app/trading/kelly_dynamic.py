"""Dynamic Kelly sizing with volatility and confidence adjustments."""
from __future__ import annotations

import math
from typing import Optional


def kelly_fraction(
	prob: float,
	odds: float,
	kelly_pct: float = 0.25,  # Conservative: 25% of full Kelly
) -> float:
	"""Calculate Kelly fraction for bet sizing.

	Full Kelly: (prob * odds - 1) / (odds - 1)
	Conservative Kelly (25%): above * 0.25

	Args:
		prob: Estimated win probability
		odds: Decimal odds
		kelly_pct: Fraction to apply (0.25 = quarter Kelly)

	Returns:
		Fraction of bankroll to stake (0-1)
	"""
	if prob <= 0 or prob >= 1 or odds <= 1:
		return 0.0

	full_kelly = (prob * odds - 1) / (odds - 1)
	full_kelly = max(0, min(full_kelly, 1))  # Clamp

	return full_kelly * kelly_pct


def confidence_adjusted_kelly(
	prob: float,
	odds: float,
	confidence: float,
	kelly_pct: float = 0.25,
) -> float:
	"""Scale Kelly by model confidence.

	Lower confidence → smaller stake
	Higher confidence → more aggressive (up to full Kelly fraction)

	Args:
		prob: Model probability
		odds: Decimal odds
		confidence: Model confidence (0-1)
		kelly_pct: Base Kelly fraction

	Returns:
		Confidence-weighted Kelly fraction
	"""
	base_kelly = kelly_fraction(prob, odds, kelly_pct)
	return base_kelly * confidence


def volatility_adjusted_kelly(
	prob: float,
	odds: float,
	portfolio_volatility: float,  # std dev of daily ROI
	confidence: float = 0.75,
	kelly_pct: float = 0.25,
	baseline_volatility: float = 0.02,  # 2% baseline vol
) -> float:
	"""Scale Kelly down in high-volatility periods.

	High portfolio vol → reduce Kelly
	Low portfolio vol → increase slightly (up to base)

	Scaling: kelly * (baseline_vol / current_vol)
	"""
	base_kelly = confidence_adjusted_kelly(prob, odds, confidence, kelly_pct)

	if portfolio_volatility <= 0:
		return base_kelly

	vol_scale = baseline_volatility / portfolio_volatility
	vol_scale = max(0.3, min(vol_scale, 1.2))  # Clamp: 30%-120%

	return base_kelly * vol_scale


def drawdown_adjusted_kelly(
	base_kelly: float,
	current_drawdown_pct: float,  # -5.0 = 5% down
	max_drawdown_allowed: float = 0.10,  # 10% max DD
) -> float:
	"""Reduce Kelly in drawdown.

	Current DD -2% → scale = 0.8 (20% reduction)
	Current DD -5% → scale = 0.5 (50% reduction)

	Scaling: kelly * (1 - abs(dd) / max_dd)
	"""
	if current_drawdown_pct >= 0:  # Not in drawdown
		return base_kelly

	dd_pct = abs(current_drawdown_pct) / 100
	scale = max(0.1, 1.0 - (dd_pct / max_drawdown_allowed))  # Min 10%

	return base_kelly * scale


def composite_kelly(
	prob: float,
	odds: float,
	confidence: float = 0.75,
	portfolio_volatility: float = 0.02,
	current_drawdown_pct: float = 0.0,
	kelly_pct: float = 0.25,
) -> dict:
	"""Composite Kelly calculation with all adjustments.

	Returns breakdown of each adjustment.
	"""
	# Step 1: Base Kelly + confidence
	kelly_base = kelly_fraction(prob, odds, kelly_pct)
	kelly_conf = confidence_adjusted_kelly(prob, odds, confidence, kelly_pct)

	# Step 2: Volatility adjustment
	kelly_vol = volatility_adjusted_kelly(
		prob, odds, portfolio_volatility, confidence, kelly_pct
	)

	# Step 3: Drawdown adjustment
	kelly_final = drawdown_adjusted_kelly(kelly_vol, current_drawdown_pct)

	# Clamp to reasonable bounds
	kelly_final = max(0, min(kelly_final, 0.10))  # Max 10% of bankroll per bet

	return {
		"base_kelly_pct": round(kelly_base * 100, 2),
		"confidence_adjusted_pct": round(kelly_conf * 100, 2),
		"volatility_adjusted_pct": round(kelly_vol * 100, 2),
		"drawdown_adjusted_pct": round(kelly_final * 100, 2),
		"final_kelly_fraction": round(kelly_final, 4),
		"final_stake_pct": round(kelly_final * 100, 2),
		"breakdowns": {
			"confidence": round(confidence, 2),
			"portfolio_vol": round(portfolio_volatility * 100, 2),
			"current_dd": round(current_drawdown_pct, 2),
		},
	}


def stake_from_kelly(
	kelly_fraction: float,
	bankroll: float,
) -> float:
	"""Convert Kelly fraction to actual stake amount."""
	return bankroll * kelly_fraction
