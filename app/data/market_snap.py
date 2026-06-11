"""Market snapshots: persist odds/volume/spreads every 5 minutes."""
from __future__ import annotations

import sqlite3
import time
from typing import Optional

SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS market_snapshots (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	match_id TEXT NOT NULL,
	ts REAL NOT NULL,
	odds_side1 REAL,
	odds_side2 REAL,
	volume REAL DEFAULT 0,
	is_sharp_signal INTEGER DEFAULT 0,
	notes TEXT,
	created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_match_ts
	ON market_snapshots(match_id, ts);
"""


def init_snapshots_table(db_path: str) -> None:
	"""Initialize market snapshots table."""
	conn = sqlite3.connect(db_path)
	conn.executescript(SNAPSHOTS_TABLE)
	conn.commit()
	conn.close()


def record_snapshot(
	db_path: str,
	match_id: str,
	odds_side1: float,
	odds_side2: float,
	volume: float = 0.0,
	is_sharp: bool = False,
	notes: Optional[str] = None,
	timestamp: Optional[float] = None,
) -> int:
	"""Store a market snapshot."""
	ts = timestamp or time.time()
	conn = sqlite3.connect(db_path)
	cur = conn.cursor()

	cur.execute(
		"""
		INSERT INTO market_snapshots
		(match_id, ts, odds_side1, odds_side2, volume, is_sharp_signal, notes, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		""",
		(match_id, ts, odds_side1, odds_side2, volume, int(is_sharp), notes, time.time()),
	)

	conn.commit()
	snapshot_id = cur.lastrowid
	conn.close()

	return snapshot_id


def fetch_snapshots(
	db_path: str,
	match_id: str,
	limit: int = 100,
) -> list[dict]:
	"""Fetch snapshots for a match, most recent first."""
	conn = sqlite3.connect(db_path)
	conn.row_factory = sqlite3.Row
	cur = conn.cursor()

	cur.execute(
		"""
		SELECT id, match_id, ts, odds_side1, odds_side2, volume, is_sharp_signal, notes
		FROM market_snapshots
		WHERE match_id = ?
		ORDER BY ts DESC
		LIMIT ?
		""",
		(match_id, limit),
	)

	rows = cur.fetchall()
	conn.close()

	return [dict(row) for row in rows]


def fetch_recent_snapshots(
	db_path: str,
	hours: int = 1,
) -> list[dict]:
	"""Fetch all snapshots from last N hours."""
	conn = sqlite3.connect(db_path)
	conn.row_factory = sqlite3.Row
	cur = conn.cursor()

	cutoff_ts = time.time() - (hours * 3600)

	cur.execute(
		"""
		SELECT match_id, ts, odds_side1, odds_side2, volume, is_sharp_signal
		FROM market_snapshots
		WHERE ts >= ?
		ORDER BY ts DESC
		""",
		(cutoff_ts,),
	)

	rows = cur.fetchall()
	conn.close()

	return [dict(row) for row in rows]


def line_movement_stats(
	db_path: str,
	match_id: str,
) -> dict:
	"""Analyze line movement for a match."""
	snapshots = fetch_snapshots(db_path, match_id, limit=1000)
	snapshots.reverse()  # Chronological order

	if len(snapshots) < 2:
		return {"error": "Insufficient snapshots"}

	opening = snapshots[0]
	closing = snapshots[-1]

	move_s1 = closing["odds_side1"] - opening["odds_side1"]
	move_s1_pct = (move_s1 / opening["odds_side1"] * 100) if opening["odds_side1"] > 0 else 0

	move_s2 = closing["odds_side2"] - opening["odds_side2"]
	move_s2_pct = (move_s2 / opening["odds_side2"] * 100) if opening["odds_side2"] > 0 else 0

	return {
		"match_id": match_id,
		"opening": {
			"ts": opening["ts"],
			"odds_side1": opening["odds_side1"],
			"odds_side2": opening["odds_side2"],
		},
		"closing": {
			"ts": closing["ts"],
			"odds_side1": closing["odds_side1"],
			"odds_side2": closing["odds_side2"],
		},
		"movement_side1": {
			"delta": round(move_s1, 3),
			"pct": round(move_s1_pct, 2),
		},
		"movement_side2": {
			"delta": round(move_s2, 3),
			"pct": round(move_s2_pct, 2),
		},
		"snapshots_count": len(snapshots),
	}
