"""Ingestion des classements ATP/WTA pour TennisBoss.

Sources (gratuites) :
  1. tennis-data.co.uk — WRank/LRank au moment du match (GS/Masters 2020+)
  2. Reconstruction depuis la table matches (dernier rang observé par joueur)
  3. tennisexplorer.com — top 500 live ATP/WTA (HTML, fallback)

Les rangs alimentent player_rankings + memory.json (champ rank) pour
ranking_diff dans ml_prep et match_intelligence.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import requests

from . import db, memory, tennisdata_feeder
from . import config
from .log import log

LTE_RANKING_URLS: Dict[str, List[tuple]] = {
    "atp": [
        ("https://live-tennis.eu/en/official-atp-ranking", 1000),
        ("https://live-tennis.eu/en/atp-live-ranking", 500),
        ("https://live-tennis.eu/en/itf-men-live-ranking", 1000),
    ],
    "wta": [
        ("https://live-tennis.eu/en/official-wta-ranking", 1000),
        ("https://live-tennis.eu/en/wta-live-ranking", 500),
        ("https://live-tennis.eu/en/itf-women-live-ranking", 1000),
    ],
}


def _resolve_ranking_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Relie les noms complets (live-tennis) aux noms canoniques TennisBoss."""
    from . import memory, namematch

    mem = memory.load()
    names = list(mem.get("players", {}).keys())
    with db.connect() as conn:
        db_names = conn.execute(
            "SELECT DISTINCT winner AS n FROM matches "
            "UNION SELECT DISTINCT loser FROM matches"
        ).fetchall()
    for r in db_names:
        if r["n"] and r["n"] not in names:
            names.append(r["n"])
    counts = {n: int((mem.get("players") or {}).get(n, {}).get("n", 0)) for n in names}
    idx = namematch.build_index(names, counts)
    out: List[Dict[str, Any]] = []
    for r in rows:
        canon = namematch.resolve(r["name"], idx)
        if canon:
            out.append({**r, "name": canon})
    return out


def _parse_live_tennis_eu(html: str, tour: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Parse live-tennis.eu (class=rk + class=pn)."""
    rows: List[Dict[str, Any]] = []
    pattern = re.compile(
        r"class=rk>(\d+)</td>.*?class=pn>([^<]+)</td>",
        re.DOTALL | re.IGNORECASE,
    )
    import datetime as _dt
    as_of = _dt.date.today().isoformat()
    seen: set = set()
    for m in pattern.finditer(html):
        rank = int(m.group(1))
        name = m.group(2).strip()
        if not name or rank > limit or name in seen:
            continue
        seen.add(name)
        rows.append({
            "name": name,
            "tour": tour,
            "rank": rank,
            "as_of": as_of,
            "source": "live-tennis.eu",
        })
        if len(rows) >= limit:
            break
    return rows


def _parse_tennisexplorer(html: str, tour: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Fallback tennisexplorer (souvent 404) — conservé pour tests."""
    rows: List[Dict[str, Any]] = []
    pattern = re.compile(
        r'<td[^>]*class="rank"[^>]*>\s*(\d+)\.\s*</td>.*?'
        r'<a[^>]+href="/player/[^"]+"[^>]*>([^<]+)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    import datetime as _dt
    as_of = _dt.date.today().isoformat()
    for m in pattern.finditer(html):
        rank = int(m.group(1))
        name = m.group(2).strip()
        if not name or rank > limit:
            continue
        rows.append({
            "name": name,
            "tour": tour,
            "rank": rank,
            "as_of": as_of,
            "source": "tennisexplorer",
        })
        if len(rows) >= limit:
            break
    return rows


def _fetch_html(url: str) -> Optional[str]:
    try:
        r = requests.get(url, headers={"User-Agent": config.BROWSER_UA}, timeout=20)
        if r.status_code == 200:
            return r.text
    except requests.RequestException as exc:
        log(f"ranking fetch {url}: {exc}", "WARN")
    return None


def fetch_live_rankings(tours: List[str] = ("atp", "wta"), limit: int = 1000) -> List[Dict[str, Any]]:
    """Top N live depuis live-tennis.eu (officiel + live + ITF)."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for tour in tours:
        urls = LTE_RANKING_URLS.get(tour, [])
        tour_parsed = 0
        tour_resolved = 0
        for url, page_limit in urls:
            cap = min(limit, page_limit)
            html = _fetch_html(url)
            if not html:
                continue
            parsed = _parse_live_tennis_eu(html, tour, limit=cap)
            if not parsed:
                parsed = _parse_tennisexplorer(html, tour, limit=cap)
            tour_parsed += len(parsed)
            for row in _resolve_ranking_rows(parsed):
                key = (row["name"], row["tour"])
                if key in seen:
                    continue
                seen.add(key)
                out.append(row)
                tour_resolved += 1
        log(f"ranking live {tour.upper()}: {tour_parsed} parsés, "
            f"{tour_resolved} résolus uniques", "INFO")
    return out


def backfill_from_tennisdata(
    years: Optional[List[int]] = None,
    tours: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Backfill w_rank/l_rank depuis tennis-data.co.uk (sans ré-ingérer ELO)."""
    if years is None:
        years = list(range(2020, 2027))
    if tours is None:
        tours = ["atp", "wta"]
    db.init()
    matches = tennisdata_feeder.fetch_matches(years, tours)
    rank_updates = [(m["id"], m.get("w_rank"), m.get("l_rank")) for m in matches]
    rank_rows: List[Dict[str, Any]] = []
    for m in matches:
        for player, rank_key in [(m["winner"], m.get("w_rank")), (m["loser"], m.get("l_rank"))]:
            if player and rank_key:
                rank_rows.append({
                    "name": player,
                    "tour": m.get("tour", "atp"),
                    "rank": rank_key,
                    "as_of": m["date"],
                    "source": "tennisdata",
                })
    updated = db.backfill_match_ranks_bulk(rank_updates)
    upserted = db.upsert_player_rankings_bulk(rank_rows)
    rebuilt = db.rebuild_player_rankings_from_matches()
    return {
        "matches_fetched": len(matches),
        "match_ranks_updated": updated,
        "rankings_upserted": upserted,
        "rankings_rebuilt": rebuilt,
    }


def sync_to_memory() -> int:
    """Copie player_rankings → memory.json players[*].rank."""
    mem = memory.load()
    ranks = db.get_all_player_rankings()
    n = 0
    for name, rank in ranks.items():
        if name in mem.get("players", {}):
            mem["players"][name]["rank"] = rank
            n += 1
    memory.save(mem)
    return n


def import_from_memory() -> int:
    """Importe les rankings moyens déjà présents dans memory.json."""
    mem = memory.load()
    rows: List[Dict[str, Any]] = []
    for name, prof in (mem.get("players") or {}).items():
        rank = prof.get("rank")
        if rank is None:
            continue
        rows.append({
            "name": name,
            "tour": prof.get("tour") or "",
            "rank": int(rank),
            "source": "memory_avg",
        })
    return db.upsert_player_rankings_bulk(rows)


def ingest(
    years: Optional[List[int]] = None,
    tours: Optional[List[str]] = None,
    live: bool = True,
    live_limit: int = 500,
) -> Dict[str, Any]:
    """Pipeline complet : tennisdata archive + live top-N + sync memory."""
    db.init()
    td = backfill_from_tennisdata(years=years, tours=tours)
    mem_imported = import_from_memory()
    live_n = 0
    if live:
        live_rows = fetch_live_rankings(tours=tours or ["atp", "wta"], limit=live_limit)
        live_n = db.upsert_player_rankings_bulk(live_rows)
    synced = sync_to_memory()
    coverage = db.ranking_coverage_stats()
    return {
        **td,
        "memory_ranks_imported": mem_imported,
        "live_rankings_upserted": live_n,
        "memory_synced": synced,
        "coverage": coverage,
    }
