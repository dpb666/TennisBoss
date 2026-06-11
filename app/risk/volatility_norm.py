"""Volatility-normalized stake sizing."""
from __future__ import annotations

from typing import Optional


class VolatilityNormalizer:
	"""Normalize stakes by market volatility."""

	def __init__(self, baseline_volatility: float = 0.02):
		"""Initialize with baseline vol (2% is typical)."""
		self.baseline_vol = baseline_volatility
		self.surface_vols = {
			"hard": 0.025,    # Hard courts: slightly higher vol
			"clay": 0.018,    # Clay courts: lower vol
			"grass": 0.032,   # Grass: highest vol (fewer matches)
		}

	def set_surface_volatility(self, surface: str, vol: float) -> None:
		"""Update empirical surface volatility."""
		self.surface_vols[surface.lower()] = vol

	def normalize_stake(
		self,
		base_stake: float,
		current_volatility: float,
		baseline: Optional[float] = None,
	) -> dict:
		"""Scale stake inversely to current volatility.

		High vol → smaller stake
		Low vol → larger stake

		Scaling: stake * (baseline_vol / current_vol)
		"""
		baseline = baseline or self.baseline_vol

		if current_volatility <= 0:
			vol_scale = 1.0
		else:
			vol_scale = baseline / current_volatility
			vol_scale = max(0.5, min(vol_scale, 1.5))  # Clamp: 50%-150%

		normalized_stake = base_stake * vol_scale

		return {
			"base_stake": round(base_stake, 2),
			"baseline_vol": round(baseline * 100, 2),
			"current_vol": round(current_volatility * 100, 2),
			"vol_scale_factor": round(vol_scale, 3),
			"normalized_stake": round(normalized_stake, 2),
		}

	def normalize_by_surface(
		self,
		base_stake: float,
		surface: str,
		current_volatility: Optional[float] = None,
	) -> dict:
		"""Normalize stake using surface-specific baseline."""
		surface_key = surface.lower()
		baseline = self.surface_vols.get(surface_key, self.baseline_vol)

		if current_volatility is None:
			current_volatility = baseline

		result = self.normalize_stake(base_stake, current_volatility, baseline)
		result["surface"] = surface
		result["surface_baseline_vol"] = round(baseline * 100, 2)

		return result

	def multi_surface_portfolio(
		self,
		positions: list[dict],  # {surface, stake, current_vol}
	) -> dict:
		"""Normalize stakes across portfolio with mixed surfaces."""
		normalized = []
		total_original = 0.0
		total_normalized = 0.0

		for pos in positions:
			surface = pos.get("surface", "hard")
			stake = pos["stake"]
			vol = pos.get("current_vol", self.surface_vols.get(surface.lower(), self.baseline_vol))

			result = self.normalize_by_surface(stake, surface, vol)
			normalized.append(result)

			total_original += stake
			total_normalized += result["normalized_stake"]

		return {
			"positions": normalized,
			"total_original_stake": round(total_original, 2),
			"total_normalized_stake": round(total_normalized, 2),
			"portfolio_vol_scale": round(total_normalized / total_original, 3) if total_original > 0 else 1.0,
		}
