#!/usr/bin/env python3
"""One-shot DB integrity checks for stabilization pass."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "state" / "tennisboss.db"


def main() -> int:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT COUNT(*) as n FROM bet_history")
    bh_total = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) as n FROM bet_history WHERE result IN (0, 1)")
    bh_settled = c.fetchone()["n"]
    c.execute(
        "SELECT COUNT(*) as n FROM bet_history WHERE result IN (0, 1) "
        "AND (prediction IS NULL OR prediction=0)"
    )
    bh_null_prob = c.fetchone()["n"]
    c.execute(
        "SELECT COUNT(*) as n FROM bet_history WHERE result IN (0, 1) AND clv_pct IS NULL"
    )
    bh_null_clv = c.fetchone()["n"]
    c.execute(
        "SELECT event_key, COUNT(*) as cnt FROM bet_history "
        "GROUP BY event_key HAVING cnt>1"
    )
    dupes = [dict(r) for r in c.fetchall()]

    c.execute("SELECT COUNT(*) as n FROM clv_log")
    clv_total = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) as n FROM clv_log WHERE closing_odds IS NULL")
    clv_null = c.fetchone()["n"]
    c.execute(
        "SELECT COUNT(*) as n FROM bet_history bh "
        "LEFT JOIN clv_log cl ON bh.event_key=cl.event_key "
        "WHERE bh.result IN (0, 1) AND cl.event_key IS NULL"
    )
    bh_no_clv = c.fetchone()["n"]

    c.execute(
        "SELECT key, value FROM meta WHERE key LIKE 'last_%' "
        "OR key LIKE '%calibration%' OR key LIKE '%ranking%' "
        "OR key LIKE '%backfill%'"
    )
    meta = {r["key"]: r["value"] for r in c.fetchall()}

    c.execute("SELECT SUM(profit_loss) as total_pnl, AVG(profit_loss) as avg_pnl FROM bet_history WHERE result IN (0, 1)")
    roi_row = c.fetchone()

    c.execute("SELECT surface, COUNT(*) as n FROM bet_history WHERE result IN (0, 1) GROUP BY surface")
    by_surface = {r["surface"]: r["n"] for r in c.fetchall()}

    out = {
        "db_path": str(DB),
        "bet_history_total": bh_total,
        "bet_history_settled": bh_settled,
        "null_model_prob_settled": bh_null_prob,
        "null_clv_pct_settled": bh_null_clv,
        "duplicate_event_keys": len(dupes),
        "duplicate_samples": dupes[:5],
        "clv_log_total": clv_total,
        "clv_null_closing": clv_null,
        "settled_without_clv_log": bh_no_clv,
        "total_pnl": roi_row["total_pnl"],
        "avg_pnl": roi_row["avg_pnl"],
        "by_surface": by_surface,
        "meta": meta,
    }
    print(json.dumps(out, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
