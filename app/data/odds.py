"""Odds ingestion and normalization.

Supports:
- Direct decimal odds input
- Odds API via bot.odds_api (existing integration)
- Betfair-style fractional odds conversion (future)
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Odds normalization helpers
# ---------------------------------------------------------------------------

def decimal_to_prob(decimal_odds: float) -> float:
    """1 / decimal_odds (raw implied probability, includes bookmaker margin)."""
    return 1.0 / max(1.01, decimal_odds)


def fractional_to_decimal(num: int, den: int) -> float:
    """e.g. 3/1 → 4.0,  1/2 → 1.5"""
    return 1.0 + num / den


def american_to_decimal(american: int) -> float:
    """e.g. +150 → 2.50,  −200 → 1.50"""
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def overround(odds1: float, odds2: float) -> float:
    """Bookmaker margin as a fraction (e.g. 0.04 = 4% overround)."""
    return 1.0 / odds1 + 1.0 / odds2 - 1.0


def fair_odds(odds1: float, odds2: float) -> Tuple[float, float]:
    """Remove vig: return fair decimal odds (implied prob sums to 1)."""
    p1 = decimal_to_prob(odds1)
    p2 = decimal_to_prob(odds2)
    total = p1 + p2
    fair_p1 = p1 / total
    fair_p2 = p2 / total
    return 1.0 / fair_p1, 1.0 / fair_p2


# ---------------------------------------------------------------------------
# Live odds fetch (wraps existing bot.odds_api)
# ---------------------------------------------------------------------------

def fetch_match_odds(
    player1: str,
    player2: str,
) -> Optional[Tuple[float, float]]:
    """Try to get live decimal odds from Odds API for (player1, player2).

    Returns (odds1, odds2) or None if unavailable.
    fetch_match_winner returns a dict: {home_odds, away_odds, home_prob, away_prob, books}
    """
    try:
        from bot import odds_api
        events = odds_api.fetch_tennis_events(upcoming_only=True)
        index  = odds_api.build_event_index(events)
        ev     = odds_api.find_event(index, player1, player2)
        if not ev:
            return None
        data = odds_api.fetch_match_winner(ev["id"])
        if not data:
            return None
        h = data.get("home_odds")
        a = data.get("away_odds")
        if h and a and float(h) > 1.0 and float(a) > 1.0:
            return float(h), float(a)
        return None
    except Exception:
        return None


def fetch_upcoming_matches(days: int = 2, max_events: int = 25) -> List[Dict[str, Any]]:
    """Fetch upcoming tennis matches with odds from odds-api.io.

    Returns list of normalised match dicts compatible with LiveOddsFeeder.
    Filtre par horizon `days` et plafonne à `max_events` appels /odds
    (1 requête API par événement — budget 100 req/h sur le plan gratuit).
    """
    try:
        from datetime import datetime, timedelta, timezone

        from bot import odds_api
        events = odds_api.fetch_tennis_events(upcoming_only=True)
        horizon = datetime.now(timezone.utc) + timedelta(days=days)
        results = []
        for ev in events:
            raw_date = str(ev.get("date") or "")
            try:
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                if dt > horizon:
                    continue
            except ValueError:
                pass  # date illisible -> on garde l'événement
            if len(results) >= max_events:
                break
            mw = odds_api.fetch_match_winner(ev["id"])
            if not mw:
                continue
            results.append({
                "player1": ev.get("home", ""),
                "player2": ev.get("away", ""),
                "odds1":   mw["home_odds"],
                "odds2":   mw["away_odds"],
                "surface": None,
                "league":  (ev.get("league") or {}).get("name", ""),
                "status":  ev.get("status", ""),
                "event_id": ev.get("id"),
            })
        return results
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Structured event parsing
# ---------------------------------------------------------------------------

def parse_event(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalise a raw event from any source into a standard structure."""
    try:
        return {
            "id":      raw.get("id") or raw.get("event_id"),
            "player1": raw.get("home") or raw.get("player1") or "",
            "player2": raw.get("away") or raw.get("player2") or "",
            "surface": (raw.get("surface") or "").lower() or None,
            "odds1":   float(raw.get("odds1") or raw.get("home_odds") or 0),
            "odds2":   float(raw.get("odds2") or raw.get("away_odds") or 0),
            "source":  raw.get("source", "unknown"),
        }
    except (TypeError, ValueError):
        return None
