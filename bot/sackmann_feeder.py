"""Sackmann Tennis Data Feeder — ingest CSV from GitHub.

Source: https://github.com/JeffSackmann/tennis_atp & tennis_wta
- ATP matches 1968-2026
- WTA matches 1968-2026
- ~23k new matches vs our 16k current

No auth required, fully open data, CC0 license.
"""

import csv
import io
from datetime import datetime
from typing import Dict, List, Tuple
from urllib.request import urlopen

from . import db, elo, memory
from .log import log


BASE_ATP = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
BASE_WTA = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"


def fetch_csv(url: str) -> List[Dict]:
    """Fetch CSV from GitHub, parse into list of dicts."""
    try:
        response = urlopen(url, timeout=15)
        content = response.read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        return list(reader)
    except Exception as e:
        log(f"Sackmann fetch error {url}: {e}", "ERROR")
        return []


def normalize_sackmann_match(row: Dict, tour: str) -> Dict:
    """Convert Sackmann CSV row to TennisBoss match format.

    Sackmann columns:
    tourney_id, tourney_name, surface, draw_size, tourney_level, tourney_date,
    match_num, winner_id, winner_seed, winner_entry, winner_name, winner_hand,
    winner_ht, winner_ioc, winner_age, winner_rank, winner_rank_points,
    loser_id, loser_seed, loser_entry, loser_name, loser_hand,
    loser_ht, loser_ioc, loser_age, loser_rank, loser_rank_points,
    score, best_of, round, minutes
    """
    try:
        return {
            "event_key": f"{row['tourney_date']}_{row['tourney_id']}_{row['winner_id']}_{row['loser_id']}",
            "date": row.get("tourney_date", ""),
            "tournament": row.get("tourney_name", ""),
            "surface": (row.get("surface", "hard") or "hard").lower(),
            "winner": row.get("winner_name", ""),
            "loser": row.get("loser_name", ""),
            "final_score": row.get("score", ""),
            "round": row.get("round", ""),
            "best_of": row.get("best_of", "3"),
            "tour": tour,
            "minutes": row.get("minutes", ""),
            "source": "sackmann",
        }
    except Exception as e:
        log(f"Parse error: {e}", "WARN")
        return None


def ingest_year_range(start_year: int = 2022, end_year: int = 2026) -> Dict[str, int]:
    """Ingest Sackmann data for ATP & WTA, year range."""
    mem = memory.load()
    counts = {"inserted": 0, "skipped": 0, "duplicates": 0}

    for year in range(start_year, end_year + 1):
        for tour, base_url in [("atp", BASE_ATP), ("wta", BASE_WTA)]:
            url = f"{base_url}/{tour}_matches_{year}.csv"
            log(f"Fetching {tour.upper()} {year}...", "INFO")
            rows = fetch_csv(url)

            for row in rows:
                match = normalize_sackmann_match(row, tour)
                if not match:
                    continue

                winner, loser = match["winner"], match["loser"]
                if winner not in mem["players"] or loser not in mem["players"]:
                    counts["skipped"] += 1
                    continue

                # Check if event_key already exists
                if db.get_match_by_event_key(match["event_key"]):
                    counts["duplicates"] += 1
                    continue

                # Insert match
                try:
                    db.insert_match(
                        event_key=match["event_key"],
                        player1=winner,
                        player2=loser,
                        winner=winner,
                        date=match["date"],
                        tournament=match["tournament"],
                        surface=match["surface"],
                        final_score=match["final_score"],
                        round=match["round"],
                    )
                    counts["inserted"] += 1
                except Exception as e:
                    log(f"Insert error: {e}", "WARN")

            log(f"  {tour.upper()} {year}: +{sum([1 for r in rows if normalize_sackmann_match(r, tour)])} matches", "INFO")

    # Rebuild ELO with new data
    log("Rebuilding ELO with new matches...", "INFO")
    rows = db.all_matches_chrono()
    elo_model, _ = elo.build_dynamic(rows)
    mem["elo"] = elo_model
    memory.save(mem)

    return counts


def stream_live_matches(year: int = 2026, tour: str = "atp") -> List[Dict]:
    """Stream current season matches (live ingestion point)."""
    url = f"{BASE_ATP if tour == 'atp' else BASE_WTA}/{tour}_matches_{year}.csv"
    matches = fetch_csv(url)
    log(f"Streamed {len(matches)} {tour.upper()} {year} matches", "INFO")
    return matches
