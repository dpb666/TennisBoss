#!/usr/bin/env python3
"""One-shot surface data coverage audit (Phase 2)."""
from __future__ import annotations

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

    def pct(n: int, total: int) -> float:
        return round(100.0 * n / total, 2) if total else 0.0

    c.execute("SELECT COUNT(*) AS n FROM matches")
    m_total = c.fetchone()["n"]

    checks = {
        "surface": "surface IS NOT NULL AND surface != ''",
        "date": "date IS NOT NULL AND date != ''",
        "tour": "tour IS NOT NULL AND tour != ''",
        "ranking": "w_rank IS NOT NULL OR l_rank IS NOT NULL",
        "margin": "margin IS NOT NULL",
    }
    matches_cov = {}
    for key, cond in checks.items():
        c.execute(f"SELECT COUNT(*) AS n FROM matches WHERE {cond}")
        n = c.fetchone()["n"]
        matches_cov[key] = {"n": n, "pct": pct(n, m_total)}

    c.execute(
        "SELECT surface, COUNT(*) AS n FROM matches "
        "GROUP BY surface ORDER BY n DESC"
    )
    surface_dist = {r["surface"] or "(empty)": r["n"] for r in c.fetchall()}

    c.execute("SELECT COUNT(*) AS n FROM historical_odds")
    ho_total = c.fetchone()["n"]
    c.execute(
        "SELECT COUNT(*) AS n FROM historical_odds "
        "WHERE surface IS NOT NULL AND surface != ''"
    )
    ho_surf = c.fetchone()["n"]

    c.execute("PRAGMA table_info(clv_log)")
    clv_has_surface = "surface" in {r["name"] for r in c.fetchall()}

    tables = {}
    for tbl in ("bet_history", "value_picks", "clv_log"):
        c.execute(f"SELECT COUNT(*) AS n FROM {tbl}")
        total = c.fetchone()["n"]
        if tbl == "clv_log" and not clv_has_surface:
            with_surf = 0
        else:
            c.execute(
                f"SELECT COUNT(*) AS n FROM {tbl} "
                "WHERE surface IS NOT NULL AND surface != ''"
            )
            with_surf = c.fetchone()["n"]
        settled = None
        if tbl == "bet_history":
            c.execute(
                "SELECT COUNT(*) AS n FROM bet_history WHERE result IN (0, 1)"
            )
            settled = c.fetchone()["n"]
            c.execute(
                "SELECT COUNT(*) AS n FROM bet_history "
                "WHERE result IN (0, 1) AND (surface IS NULL OR surface = '')"
            )
            missing = c.fetchone()["n"]
        else:
            missing = total - with_surf if tbl != "clv_log" or clv_has_surface else total
        tables[tbl] = {
            "total": total,
            "with_surface": with_surf,
            "pct": pct(with_surf, total),
            "settled": settled,
            "missing_surface": missing,
            "has_surface_column": tbl != "clv_log" or clv_has_surface,
        }

    out = {
        "db_path": str(DB),
        "matches_total": m_total,
        "matches_coverage": matches_cov,
        "matches_surface_distribution": surface_dist,
        "historical_odds": {
            "total": ho_total,
            "with_surface": ho_surf,
            "pct": pct(ho_surf, ho_total),
        },
        "tables": tables,
    }
    print(json.dumps(out, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
