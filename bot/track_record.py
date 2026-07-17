"""Track Record — read layer over bet_history + clv_log.

Agrège l'historique des picks réglés sans toucher à la logique de prédiction.
Analytique uniquement : le stake configurable (config.TRACK_RECORD_STAKE) sert
aux métriques ROI/yield affichées, pas aux décisions de pari.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from . import config, db, versions


def _stake() -> float:
    return max(0.01, float(config.TRACK_RECORD_STAKE))


def _since_date(days: Optional[int]) -> Optional[str]:
    if days is None or days <= 0:
        return None
    return (_dt.date.today() - _dt.timedelta(days=days - 1)).isoformat()


def _result_label(result: Optional[int]) -> str:
    if result == 1:
        return "win"
    if result == 0:
        return "loss"
    if result == -1:
        return "void"
    return "pending"


def _profit_loss(odds: Optional[float], result: Optional[int], stake: float) -> Optional[float]:
    if result == -1:
        return 0.0
    if result not in (0, 1) or odds is None or odds <= 1.0:
        return None
    if result == 1:
        return round(stake * (float(odds) - 1.0), 4)
    return round(-stake, 4)


def _clv_by_event() -> Dict[str, Any]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM clv_log").fetchall()
    by_event: Dict[str, Any] = {}
    by_match: Dict[str, Any] = {}
    for r in rows:
        ek = r["event_key"]
        if ek:
            by_event[ek] = r
        key = f"{(r['player1'] or '').lower()}|{(r['player2'] or '').lower()}|{r['date'] or ''}"
        by_match[key] = r
        key_rev = f"{(r['player2'] or '').lower()}|{(r['player1'] or '').lower()}|{r['date'] or ''}"
        by_match[key_rev] = r
    return {"by_event": by_event, "by_match": by_match}


def _enrich_clv(bh: Any, clv_maps: Dict[str, Dict[str, Any]]) -> Optional[Any]:
    ek = bh["event_key"]
    if ek and ek in clv_maps["by_event"]:
        return clv_maps["by_event"][ek]
    key = f"{(bh['player1'] or '').lower()}|{(bh['player2'] or '').lower()}|{bh['date'] or ''}"
    return clv_maps["by_match"].get(key)


def _fetch_bet_rows(
    days: Optional[int] = None,
    surface: Optional[str] = None,
    result_filter: Optional[str] = None,
) -> List[Any]:
    since = _since_date(days)
    params: List[Any] = []
    clauses = ["result IS NOT NULL"]
    if since:
        clauses.append("date >= ?")
        params.append(since)
    if surface:
        clauses.append("LOWER(COALESCE(surface, '')) = ?")
        params.append(surface.lower())
    if result_filter == "win":
        clauses.append("result = 1")
    elif result_filter == "loss":
        clauses.append("result = 0")
    elif result_filter == "void":
        clauses.append("result = -1")
    where = " AND ".join(clauses)
    with db.connect() as conn:
        return conn.execute(
            f"SELECT * FROM bet_history WHERE {where} ORDER BY ts DESC, id DESC",
            params,
        ).fetchall()


def _row_to_pick(bh: Any, clv: Optional[Any], stake: float) -> Dict[str, Any]:
    surf = (bh["surface"] or (clv["surface"] if clv else None) or "").lower() or None
    odds = bh["odds"]
    res = bh["result"]
    pnl = _profit_loss(odds, res, stake)
    if pnl is None and bh["profit_loss"] is not None and stake == 1.0:
        pnl = bh["profit_loss"]
    elif pnl is None and bh["profit_loss"] is not None and stake != 1.0:
        pnl = round(float(bh["profit_loss"]) * stake, 4)

    pick_ts = (clv["pick_ts"] if clv else None) or bh["ts"]
    closing = clv["closing_odds"] if clv else None
    ev_pct = (clv["ev_pct"] if clv else None)
    if ev_pct is None and clv and clv["pick_prob"] and odds and float(odds) > 1:
        ev_pct = round((float(clv["pick_prob"]) * float(odds) - 1.0) * 100, 2)

    return {
        "id": bh["id"],
        "pick_id": bh["event_key"] or str(bh["id"]),
        "timestamp": pick_ts,
        "date": bh["date"],
        "match": f"{bh['player1']} vs {bh['player2']}",
        "player1": bh["player1"],
        "player2": bh["player2"],
        "tournament": (clv["tournament"] if clv else None),
        "tournament_level": (clv["tournament_level"] if clv else None),
        "surface": surf,
        "market": "match_winner",
        "selection": bh["pick_side"],
        "odds_at_pick": odds,
        "closing_odds": closing,
        "closing_odds_available": closing is not None,
        "result": _result_label(res),
        "result_code": res,
        "stake": stake,
        "profit_loss": pnl,
        "clv_pct": bh["clv_pct"] if bh["clv_pct"] is not None else (clv["clv_pct"] if clv else None),
        "ev_pct": ev_pct,
        "confidence": bh["confidence"],
        "predictor_version": (
            (clv["predictor_version"] if clv else None) or versions.PREDICTOR_VERSION
        ),
        "calibration_version": (
            (clv["calibration_version"] if clv else None) or versions.CALIBRATION_VERSION
        ),
        "settled_ts": bh["ts"],
    }


def list_picks(
    days: Optional[int] = 365,
    surface: Optional[str] = None,
    result: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
) -> Dict[str, Any]:
    """Liste paginée des picks réglés, enrichie depuis clv_log."""
    page = max(1, page)
    limit = min(500, max(1, limit))
    stake = _stake()
    rows = _fetch_bet_rows(days=days, surface=surface, result_filter=result)
    clv_maps = _clv_by_event()
    total = len(rows)
    offset = (page - 1) * limit
    page_rows = rows[offset: offset + limit]
    picks = [_row_to_pick(r, _enrich_clv(r, clv_maps), stake) for r in page_rows]
    closing_n = sum(1 for p in picks if p["closing_odds_available"])
    return {
        "stake_unit": stake,
        "days": days,
        "filters": {"surface": surface, "result": result},
        "page": page,
        "limit": limit,
        "total": total,
        "pages": max(1, (total + limit - 1) // limit),
        "closing_odds_coverage_pct": round(100.0 * closing_n / len(picks), 1) if picks else None,
        "picks": picks,
    }


def _aggregate_pool(rows: List[Any], clv_maps: Dict[str, Dict[str, Any]], stake: float) -> List[Dict[str, Any]]:
    return [_row_to_pick(r, _enrich_clv(r, clv_maps), stake) for r in rows]


def _streaks(picks_chrono: List[Dict[str, Any]]) -> Dict[str, int]:
    """Plus longues séries win/loss (void ignorés)."""
    best_win = best_loss = cur_win = cur_loss = 0
    for p in picks_chrono:
        if p["result"] == "win":
            cur_win += 1
            cur_loss = 0
            best_win = max(best_win, cur_win)
        elif p["result"] == "loss":
            cur_loss += 1
            cur_win = 0
            best_loss = max(best_loss, cur_loss)
        else:
            cur_win = cur_loss = 0
    return {"longest_win_streak": best_win, "longest_loss_streak": best_loss}


def _confidence_buckets(picks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bins_def = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)]
    out = []
    for lo, hi in bins_def:
        pool = [
            p for p in picks
            if p["confidence"] is not None and lo <= float(p["confidence"]) < hi
            and p["result"] in ("win", "loss")
        ]
        if not pool:
            out.append({
                "bucket": f"{int(lo*100)}-{int(min(hi, 1)*100)}%",
                "n": 0, "wins": 0, "win_rate": None,
                "units_won": 0.0, "roi": None,
            })
            continue
        wins = sum(1 for p in pool if p["result"] == "win")
        pnls = [p["profit_loss"] for p in pool if p["profit_loss"] is not None]
        out.append({
            "bucket": f"{int(lo*100)}-{int(min(hi, 1)*100)}%",
            "n": len(pool),
            "wins": wins,
            "win_rate": round(wins / len(pool), 3),
            "units_won": round(sum(pnls), 2) if pnls else 0.0,
            "roi": round(sum(pnls) / (len(pool) * _stake()), 4) if pnls else None,
        })
    return out


def _summary_from_picks(picks: List[Dict[str, Any]], days: Optional[int]) -> Dict[str, Any]:
    stake = _stake()
    settled = [p for p in picks if p["result"] in ("win", "loss")]
    voids = [p for p in picks if p["result"] == "void"]
    n = len(settled)
    if n == 0:
        return {
            "days": days,
            "stake_unit": stake,
            "total_picks": len(picks),
            "settled_picks": 0,
            "void_picks": len(voids),
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "units_won": 0.0,
            "units_lost": 0.0,
            "net_units": 0.0,
            "total_staked": 0.0,
            "roi": None,
            "yield_pct": None,
            "avg_odds": None,
            "avg_ev_pct": None,
            "avg_clv_pct": None,
            "closing_odds_coverage_pct": None,
            "longest_win_streak": 0,
            "longest_loss_streak": 0,
            "by_confidence": _confidence_buckets(picks),
        }

    wins = sum(1 for p in settled if p["result"] == "win")
    losses = n - wins
    pnls = [p["profit_loss"] for p in settled if p["profit_loss"] is not None]
    units_won = round(sum(p for p in pnls if p > 0), 2)
    units_lost = round(abs(sum(p for p in pnls if p < 0)), 2)
    net = round(sum(pnls), 2) if pnls else 0.0
    total_staked = stake * n
    odds_vals = [p["odds_at_pick"] for p in settled if p["odds_at_pick"]]
    ev_vals = [p["ev_pct"] for p in settled if p["ev_pct"] is not None]
    clv_vals = [p["clv_pct"] for p in settled if p["clv_pct"] is not None]
    closing_n = sum(1 for p in settled if p["closing_odds_available"])

    chrono = sorted(
        [p for p in picks if p["result"] in ("win", "loss")],
        key=lambda x: (x["date"] or "", x["timestamp"] or ""),
    )
    streaks = _streaks(chrono)

    return {
        "days": days,
        "stake_unit": stake,
        "total_picks": len(picks),
        "settled_picks": n,
        "void_picks": len(voids),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / n, 3),
        "units_won": units_won,
        "units_lost": units_lost,
        "net_units": net,
        "total_staked": round(total_staked, 2),
        "roi": round(net / total_staked, 4) if total_staked else None,
        "yield_pct": round(net / total_staked * 100, 1) if total_staked else None,
        "avg_odds": round(sum(odds_vals) / len(odds_vals), 3) if odds_vals else None,
        "avg_ev_pct": round(sum(ev_vals) / len(ev_vals), 2) if ev_vals else None,
        "avg_clv_pct": round(sum(clv_vals) / len(clv_vals), 2) if clv_vals else None,
        "closing_odds_coverage_pct": round(100.0 * closing_n / n, 1) if n else None,
        "longest_win_streak": streaks["longest_win_streak"],
        "longest_loss_streak": streaks["longest_loss_streak"],
        "by_confidence": _confidence_buckets(picks),
    }


def summary(days: Optional[int] = 365, surface: Optional[str] = None) -> Dict[str, Any]:
    stake = _stake()
    rows = _fetch_bet_rows(days=days, surface=surface)
    clv_maps = _clv_by_event()
    picks = _aggregate_pool(rows, clv_maps, stake)
    out = _summary_from_picks(picks, days)
    if surface:
        out["filters"] = {"surface": surface}
    return out


def _group_stats(pool: List[Dict[str, Any]], key_fn) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for p in pool:
        k = key_fn(p)
        if not k:
            k = "unknown"
        groups.setdefault(k, []).append(p)
    out = []
    for label, items in sorted(groups.items()):
        settled = [x for x in items if x["result"] in ("win", "loss")]
        n = len(settled)
        if n == 0:
            out.append({
                "label": label, "n": 0, "wins": 0,
                "win_rate": None, "net_units": 0.0, "roi": None, "yield_pct": None,
            })
            continue
        wins = sum(1 for x in settled if x["result"] == "win")
        pnls = [x["profit_loss"] for x in settled if x["profit_loss"] is not None]
        net = round(sum(pnls), 2) if pnls else 0.0
        staked = _stake() * n
        out.append({
            "label": label,
            "n": n,
            "wins": wins,
            "win_rate": round(wins / n, 3),
            "net_units": net,
            "roi": round(net / staked, 4) if staked else None,
            "yield_pct": round(net / staked * 100, 1) if staked else None,
            "avg_clv_pct": (
                round(sum(x["clv_pct"] for x in settled if x["clv_pct"] is not None)
                      / max(1, sum(1 for x in settled if x["clv_pct"] is not None)), 2)
                if any(x["clv_pct"] is not None for x in settled) else None
            ),
        })
    return out


def monthly_breakdown(days: Optional[int] = 365) -> Dict[str, Any]:
    rows = _fetch_bet_rows(days=days)
    clv_maps = _clv_by_event()
    picks = _aggregate_pool(rows, clv_maps, _stake())

    def _month_key(p: Dict[str, Any]) -> str:
        d = p["date"] or ""
        if len(d) >= 7 and d[4] == "-":
            return d[:7]
        if len(d) >= 6 and d.isdigit():
            return f"{d[:4]}-{d[4:6]}"
        return "unknown"

    months = _group_stats(picks, _month_key)
    return {"days": days, "stake_unit": _stake(), "months": months}


def surface_breakdown(days: Optional[int] = 365) -> Dict[str, Any]:
    rows = _fetch_bet_rows(days=days)
    clv_maps = _clv_by_event()
    picks = _aggregate_pool(rows, clv_maps, _stake())
    surfaces = _group_stats(picks, lambda p: (p["surface"] or "unknown").lower())
    return {"days": days, "stake_unit": _stake(), "surfaces": surfaces}


def tournament_breakdown(days: Optional[int] = 365, limit: int = 50) -> Dict[str, Any]:
    rows = _fetch_bet_rows(days=days)
    clv_maps = _clv_by_event()
    picks = _aggregate_pool(rows, clv_maps, _stake())
    tournaments = _group_stats(picks, lambda p: p["tournament"] or "unknown")
    tournaments.sort(key=lambda x: (-x["n"], x["label"]))
    return {
        "days": days,
        "stake_unit": _stake(),
        "tournaments": tournaments[:limit],
    }
