"""Backfill CLV closing lines for picks settled with ``closing_src=last_seen``.

Uses local ``market_snapshots`` first, then odds-api settled events when enabled.
Does not touch predictor, calibration, or value thresholds.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db, odds_api


def _valid_closing_ratio(pick_odds: float, closing_odds: float) -> bool:
    if pick_odds <= 1.0 or closing_odds <= 1.0:
        return False
    return closing_odds / pick_odds <= 2.5 and pick_odds / closing_odds <= 2.5


def _closing_from_snapshot(row: Any, snap: Any) -> Optional[float]:
    """Map pick side to home/away odds; fallback to closest side vs pick_odds."""
    pick_side = str(row["pick_side"] or "")
    p1 = str(row["player1"] or "")
    pick_odds = float(row["pick_odds"] or 0)
    home = float(snap["odds_home"])
    away = float(snap["odds_away"])
    preferred = home if pick_side == p1 else away
    if _valid_closing_ratio(pick_odds, preferred):
        return preferred
    other = away if preferred == home else home
    if _valid_closing_ratio(pick_odds, other):
        return other
    return None


def _closing_from_odds_api(row: Any, settled_idx: Dict[Any, Any]) -> Optional[float]:
    event_key = str(row["event_key"] or "")
    if not event_key:
        return None
    ev = settled_idx.get(event_key)
    if not ev:
        for candidate in settled_idx.values():
            if str(candidate.get("id") or "") == event_key:
                ev = candidate
                break
    if not ev:
        return None
    mw = odds_api.fetch_match_winner(
        ev["id"],
        bookmakers=odds_api._sharp_book(),
        ttl=3600,
    )
    if not mw:
        mw = odds_api.fetch_match_winner(ev["id"], ttl=3600)
    if not mw:
        return None
    p1 = str(row["player1"] or "")
    pick_side = str(row["pick_side"] or "")
    home = str(ev.get("home") or "")
    if pick_side == p1 or pick_side == home:
        return float(mw["home_odds"])
    return float(mw["away_odds"])


def backfill_last_seen_closing(
    since: str = "2026-07-15",
    *,
    dry_run: bool = False,
    use_odds_api: bool = True,
    limit: int = 5000,
) -> Dict[str, Any]:
    """Re-fetch closing odds for ``last_seen`` picks since ``since``."""
    db.init()
    rows = db.list_clv_last_seen_since(since, limit=limit)
    summary: Dict[str, Any] = {
        "since": since,
        "candidates": len(rows),
        "fixed": 0,
        "fixed_from_snapshot": 0,
        "fixed_from_odds_api": 0,
        "skipped_no_source": 0,
        "skipped_invalid_odds": 0,
        "dry_run": dry_run,
        "details": [],
    }
    if not rows:
        return summary

    settled_idx: Dict[str, Any] = {}
    if use_odds_api and odds_api.is_enabled() and odds_api._current_key():
        for ev in odds_api.fetch_settled_events():
            eid = str(ev.get("id") or "")
            if eid:
                settled_idx[eid] = ev

    for row in rows:
        event_key = str(row["event_key"] or "")
        detail: Dict[str, Any] = {
            "event_key": event_key,
            "player1": row["player1"],
            "player2": row["player2"],
            "pick_side": row["pick_side"],
            "pick_odds": row["pick_odds"],
            "old_clv_pct": row["clv_pct"],
        }
        closing: Optional[float] = None
        src = ""

        snap = db.latest_market_snapshot(event_key)
        if snap:
            closing = _closing_from_snapshot(row, snap)
            if closing and closing > 1.0:
                src = "snapshot_backfill"

        if (closing is None or closing <= 1.0) and use_odds_api and settled_idx:
            api_closing = _closing_from_odds_api(row, settled_idx)
            if api_closing and api_closing > 1.0:
                closing = api_closing
                src = "odds_api_backfill"

        if closing is None or closing <= 1.0:
            summary["skipped_no_source"] += 1
            detail["status"] = "skipped_no_source"
            summary["details"].append(detail)
            continue

        pick_odds = float(row["pick_odds"] or 0)
        if not _valid_closing_ratio(pick_odds, closing):
            summary["skipped_invalid_odds"] += 1
            detail["status"] = "skipped_invalid_odds"
            detail["closing_odds"] = closing
            summary["details"].append(detail)
            continue

        new_clv = round((pick_odds / closing - 1.0) * 100, 2)
        detail["closing_odds"] = closing
        detail["new_clv_pct"] = new_clv
        detail["src"] = src

        if dry_run:
            detail["status"] = "would_fix"
            summary["fixed"] += 1
            if src == "snapshot_backfill":
                summary["fixed_from_snapshot"] += 1
            else:
                summary["fixed_from_odds_api"] += 1
        elif db.patch_clv_closing_settled(event_key, closing, src):
            detail["status"] = "fixed"
            summary["fixed"] += 1
            if src == "snapshot_backfill":
                summary["fixed_from_snapshot"] += 1
            else:
                summary["fixed_from_odds_api"] += 1
        else:
            detail["status"] = "patch_failed"
            summary["skipped_invalid_odds"] += 1

        summary["details"].append(detail)

    return summary
