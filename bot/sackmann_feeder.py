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



def ingest_year_range(start_year: int = 2022, end_year: int = 2026,
                      include_challengers: bool = True) -> Dict[str, int]:
    """Ingest ATP & WTA main draw + Challengers/ITF via datasource. Crée les profils."""
    from . import datasource, learner, config as cfg_mod
    mem = memory.load()
    cfg = cfg_mod.DEFAULT_CONFIG
    counts = {"inserted": 0, "new_players": 0, "players_before": len(mem["players"])}

    years = list(range(start_year, end_year + 1))
    tours = ["atp", "wta"]

    log(f"Téléchargement ATP+WTA {start_year}-{end_year}...", "INFO")
    matches = datasource.fetch_matches(years, tours, include_challengers=False)

    if include_challengers:
        log("Téléchargement Challengers/ITF...", "INFO")
        chall = datasource.fetch_challengers(years, tours)
        existing_ids = {m["id"] for m in matches}
        new_chall = [m for m in chall if m["id"] not in existing_ids]
        log(f"  +{len(new_chall)} matchs Challengers/ITF.", "INFO")
        matches = matches + new_chall
        matches.sort(key=lambda m: (m["date"], m["id"]))

    # Entraîner le modèle avec tous les matchs (crée les profils joueurs)
    log(f"Entraînement sur {len(matches)} matchs...", "INFO")
    learner.train(mem, matches, cfg)

    # Archiver et synchroniser
    db.init()
    added = db.archive_matches(matches)
    db.sync_from_memory(mem)
    counts["inserted"] = added
    counts["new_players"] = len(mem["players"]) - counts["players_before"]

    # Reconstruire ELO
    log("Rebuilding ELO...", "INFO")
    db_rows = db.all_matches_chrono()
    elo_model, _ = elo.build_dynamic(db_rows)
    mem["elo"] = elo_model
    memory.save(mem)

    return counts


def stream_live_matches(year: int = 2026, tour: str = "atp") -> List[Dict]:
    """Stream current season matches (live ingestion point)."""
    url = f"{BASE_ATP if tour == 'atp' else BASE_WTA}/{tour}_matches_{year}.csv"
    matches = fetch_csv(url)
    log(f"Streamed {len(matches)} {tour.upper()} {year} matches", "INFO")
    return matches
