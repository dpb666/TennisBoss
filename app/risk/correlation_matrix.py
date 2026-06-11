"""Player correlation analysis for portfolio risk."""
from __future__ import annotations

from typing import Optional


class CorrelationMatrix:
	"""Track player correlation in portfolio."""

	def __init__(self):
		self.player_pairs: dict[tuple[str, str], float] = {}  # (p1, p2) -> correlation

	def add_correlation(self, player1: str, player2: str, correlation: float) -> None:
		"""Record correlation between two players."""
		key = tuple(sorted([player1, player2]))
		self.player_pairs[key] = correlation

	def get_correlation(self, player1: str, player2: str) -> float:
		"""Get correlation between two players."""
		key = tuple(sorted([player1, player2]))
		return self.player_pairs.get(key, 0.0)

	def analyze_exposure(
		self,
		new_player: str,
		existing_positions: list[dict],  # {player, stake, confidence}
		correlation_threshold: float = 0.5,
	) -> dict:
		"""Analyze if new player position is correlated with existing portfolio."""
		correlated_players = []
		total_correlated_stake = 0.0

		for pos in existing_positions:
			existing_player = pos["player"]
			corr = self.get_correlation(new_player, existing_player)

			if corr >= correlation_threshold:
				correlated_players.append({
					"player": existing_player,
					"correlation": round(corr, 3),
					"stake": pos["stake"],
				})
				total_correlated_stake += pos["stake"]

		is_high_correlation = len(correlated_players) > 0
		should_reject = is_high_correlation and total_correlated_stake > sum(
			p["stake"] for p in existing_positions
		) * 0.5  # Reject if correlated positions > 50% of portfolio

		return {
			"new_player": new_player,
			"correlated_players": correlated_players,
			"total_correlated_stake": round(total_correlated_stake, 2),
			"is_high_correlation": is_high_correlation,
			"should_reject": should_reject,
			"recommendation": (
				"REJECT" if should_reject
				else "CAUTION" if is_high_correlation
				else "APPROVE"
			),
		}

	def build_from_rankings(
		self,
		rankings: dict[str, int],  # player -> rank (1=best)
		rank_diff_threshold: int = 5,  # Rank diff < 5 = correlated
	) -> None:
		"""Build correlation matrix from rankings.

		Players ranked close together are correlated (play same level).
		"""
		players = sorted(rankings.items(), key=lambda x: x[1])

		for i, (p1, rank1) in enumerate(players):
			for p2, rank2 in players[i + 1 :]:
				rank_diff = abs(rank1 - rank2)
				# Correlation: higher for similar ranks
				# rank_diff = 1 → correlation = 0.9
				# rank_diff = 10 → correlation = 0.1
				correlation = max(0, 1.0 - (rank_diff / 10.0))
				self.add_correlation(p1, p2, correlation)

	def portfolio_correlation_matrix(
		self,
		positions: list[dict],
	) -> dict:
		"""Build full correlation matrix for portfolio."""
		players = [p["player"] for p in positions]
		unique_players = list(set(players))

		matrix = {}
		for p1 in unique_players:
			matrix[p1] = {}
			for p2 in unique_players:
				if p1 == p2:
					matrix[p1][p2] = 1.0
				else:
					matrix[p1][p2] = self.get_correlation(p1, p2)

		# Average correlation
		all_corrs = []
		for p1 in unique_players:
			for p2 in unique_players:
				if p1 < p2:
					all_corrs.append(matrix[p1][p2])

		avg_corr = sum(all_corrs) / len(all_corrs) if all_corrs else 0.0

		return {
			"matrix": matrix,
			"avg_correlation": round(avg_corr, 3),
			"num_players": len(unique_players),
			"highly_correlated_pairs": [
				(p1, p2, round(matrix[p1][p2], 3))
				for p1 in unique_players
				for p2 in unique_players
				if p1 < p2 and matrix[p1][p2] > 0.7
			],
		}

	def cluster_detection(
		self,
		positions: list[dict],
		correlation_threshold: float = 0.6,
	) -> dict:
		"""Detect clusters of correlated players."""
		players = list(set(p["player"] for p in positions))

		clusters = []
		visited = set()

		for player in players:
			if player in visited:
				continue

			cluster = {player}
			visited.add(player)

			for other_player in players:
				if other_player not in visited:
					corr = self.get_correlation(player, other_player)
					if corr >= correlation_threshold:
						cluster.add(other_player)
						visited.add(other_player)

			if len(cluster) > 1:
				clusters.append(sorted(list(cluster)))

		return {
			"num_clusters": len(clusters),
			"clusters": clusters,
			"cluster_sizes": [len(c) for c in clusters],
			"max_cluster_size": max([len(c) for c in clusters]) if clusters else 0,
		}
