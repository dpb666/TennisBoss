"""Rapport qualité données — WTA serve/return, rankings, bet_history."""
from __future__ import annotations

from typing import Any, Dict

from . import db


def report(active_days: int = 365) -> Dict[str, Any]:
    """Métriques avant/après correctifs pipeline (WTA MCP, rankings)."""
    from bot.ml_prep import features as feat
    from bot import memory

    db.init()
    mem = memory.load()
    rk = db.ranking_coverage_stats(active_days=active_days)
    all_ranks = feat.load_rankings(mem)
    official = db.get_all_player_rankings()
    cutoff_players = set()
    import datetime as _dt
    cutoff = (_dt.date.today() - _dt.timedelta(days=active_days)).isoformat()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT winner AS n FROM matches WHERE date >= ? "
            "UNION SELECT loser FROM matches WHERE date >= ?",
            (cutoff, cutoff),
        ).fetchall()
    cutoff_players = {r["n"] for r in rows}
    active_with_official = sum(1 for p in cutoff_players if p in official)
    active_with_any_rank = sum(1 for p in cutoff_players if p in all_ranks)
    rk["active_official_rank_pct"] = round(
        100.0 * active_with_official / max(len(cutoff_players), 1), 2
    )
    rk["ranking_diff_coverage_pct"] = round(
        100.0 * active_with_any_rank / max(len(cutoff_players), 1), 2
    )
    return {
        "wta": db.wta_stats_coverage(),
        "rankings": rk,
        "bet_history_rows": db.counts().get("bet_history", 0),
    }


def print_report(active_days: int = 365) -> None:
    r = report(active_days=active_days)
    w = r["wta"]
    rk = r["rankings"]
    print("\n--- DATA QUALITY ---")
    print(f"WTA joueurs serve non-neutre : {w['players_non_neutral_serve']}/{w['total_players']} "
          f"({w['player_serve_coverage_pct']}%)")
    print(f"WTA matchs enrichis (serve ou BP) : {w['matches_with_real_or_bp_stats']}/{w['total_matches']}")
    print(f"Rankings actifs ({rk['active_days']}j) : {rk['active_with_rank']}/{rk['active_players']} "
          f"({rk['active_rank_coverage_pct']}%)")
    print(f"Rankings actifs confiants (n>=5) : {rk['confident_active_with_rank']}/"
          f"{rk['confident_active_players']} ({rk['confident_active_rank_coverage_pct']}%)")
    print(f"Rankings officiels actifs : {rk.get('active_official_rank_pct')}%")
    print(f"ranking_diff coverage (incl. Elo fallback) : {rk.get('ranking_diff_coverage_pct')}%")
    print(f"Matchs avec w_rank/l_rank : {rk['matches_with_rank']} "
          f"({rk['match_rank_coverage_pct']}%)")
    print(f"bet_history rows : {r['bet_history_rows']}")
    print()
