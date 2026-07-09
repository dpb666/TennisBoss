"""Feeder tennis-data.co.uk — ATP + WTA grands tournois + Masters (2020-2026).

CSV avec : Winner, Loser, WRank, LRank, Surface, Score, cotes B365/PS.
Source libre, pas d'auth. Résolution joueur → profil TennisBoss.

URLs: http://www.tennis-data.co.uk/{year}/{tournament}.csv
      http://www.tennis-data.co.uk/{year}w/{tournament}.csv  (WTA)
"""
from __future__ import annotations

import csv
import io
import time
from typing import Any, Dict, List, Optional

import requests

from . import db, elo, learner, memory
from .log import log

BASE = "http://www.tennis-data.co.uk"

ATP_TOURNAMENTS = [
    "ausopen", "frenchopen", "wimbledon", "usopen",
    "indian_wells", "miami", "barcelona", "madrid", "rome",
    "montreal", "canada", "cincinnati", "eastbourne", "queens", "halle",
    "rotterdam", "doha", "dubai", "vienna", "basel", "paris",
    "toronto", "washington", "hamburg", "metz",
]
WTA_TOURNAMENTS = [
    "ausopen", "frenchopen", "wimbledon", "usopen",
    "indian_wells", "miami", "madrid", "rome",
    "montreal", "canada", "cincinnati", "eastbourne",
    "dubai", "doha", "toronto", "rome",
]

_FETCH_CACHE: Dict[str, tuple] = {}
_TTL = 3600 * 12  # 12h — ne change pas en intra-journée


def _fetch_csv(url: str) -> Optional[List[Dict]]:
    now = time.time()
    hit = _FETCH_CACHE.get(url)
    if hit and hit[0] > now:
        return hit[1]
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            reader = csv.DictReader(io.StringIO(r.text))
            rows = list(reader)
            _FETCH_CACHE[url] = (now + _TTL, rows)
            return rows
        return None
    except Exception as exc:
        log(f"tennisdata {url}: {exc}", "WARN")
        return None


def _parse_row(row: Dict, tour: str, year: int) -> Optional[Dict]:
    """Normalise une ligne CSV tennis-data.co.uk en format TennisBoss."""
    winner = (row.get("Winner") or "").strip()
    loser = (row.get("Loser") or "").strip()
    if not winner or not loser:
        return None

    date_raw = row.get("Date", "")
    try:
        from datetime import datetime
        dt = datetime.strptime(date_raw.strip(), "%d/%m/%Y")
        date_str = dt.strftime("%Y-%m-%d")
    except Exception:
        date_str = str(year)

    surface = (row.get("Surface") or "hard").lower()
    tournament = (row.get("Tournament") or "").strip()
    rnd = (row.get("Round") or "").strip()
    best_of = str(row.get("Best of") or "3")

    # Score reconstruit depuis les colonnes set-par-set
    sets = []
    for i in range(1, 6):
        ws = row.get(f"W{i}", "").strip()
        ls = row.get(f"L{i}", "").strip()
        if ws and ls:
            sets.append(f"{ws}-{ls}")
    score = " ".join(sets) if sets else row.get("Score", "")

    # Ranking au moment du match ('-' = non classé)
    w_rank = (row.get("WRank") or "").strip().lstrip("'")
    l_rank = (row.get("LRank") or "").strip().lstrip("'")

    # Cotes clôture — '-' = non disponible. B365=Bet365 (soft), PS=Pinnacle (sharp),
    # Max/Avg = meilleure cote / moyenne tous bookmakers agrégés par tennis-data.co.uk.
    def _odds(col: str) -> Optional[float]:
        v = (row.get(col) or "").strip().replace(",", ".")
        return float(v) if v and v not in ("-", "N/A") else None

    b365w, b365l = _odds("B365W"), _odds("B365L")
    psw, psl = _odds("PSW"), _odds("PSL")
    maxw, maxl = _odds("MaxW"), _odds("MaxL")
    avgw, avgl = _odds("AvgW"), _odds("AvgL")

    uid = f"td_{year}_{tour}_{winner}_{loser}_{date_str}"

    return {
        "id": uid,
        "event_key": uid,
        "date": date_str,
        "tournament": tournament,
        "surface": surface,
        "winner": winner,
        "loser": loser,
        "final_score": score,
        "round": rnd,
        "best_of": best_of,
        "tour": tour,
        "w_rank": int(w_rank) if w_rank.isdigit() else None,
        "l_rank": int(l_rank) if l_rank and l_rank.isdigit() else None,
        "b365w": b365w, "b365l": b365l,
        "psw": psw, "psl": psl,
        "maxw": maxw, "maxl": maxl,
        "avgw": avgw, "avgl": avgl,
        "source": "tennisdata",
    }


def fetch_matches(years: List[int], tours: List[str] = ("atp", "wta")) -> List[Dict]:
    """Télécharge tous les matchs ATP+WTA pour les années demandées."""
    all_matches = []
    seen_ids: set = set()

    for year in years:
        for tour in tours:
            tournaments = ATP_TOURNAMENTS if tour == "atp" else WTA_TOURNAMENTS
            url_base = f"{BASE}/{year}" if tour == "atp" else f"{BASE}/{year}w"

            for tourn in tournaments:
                url = f"{url_base}/{tourn}.csv"
                rows = _fetch_csv(url)
                if not rows:
                    continue
                for row in rows:
                    m = _parse_row(row, tour, year)
                    if m and m["id"] not in seen_ids:
                        seen_ids.add(m["id"])
                        all_matches.append(m)
                time.sleep(0.1)  # politesse — 100ms entre requêtes

    all_matches.sort(key=lambda m: m["date"])
    log(f"tennisdata: {len(all_matches)} matchs chargés ({years}, {list(tours)})")
    return all_matches


def ingest(years: List[int] = None, tours: List[str] = None) -> Dict[str, Any]:
    """Ingère les données tennis-data.co.uk dans mémoire + DB TennisBoss.

    Ces matchs n'ont pas les stats serve/return (seuls Sackmann les a), donc
    on n'appelle pas learner.train(). À la place :
    - On crée des profils "neutres" pour les joueurs inconnus (visible dans index).
    - On reconstruit l'ELO global + surface depuis tous les matchs DB.
    - Le ranking moyen observé est stocké dans le profil.
    """
    if years is None:
        years = list(range(2022, 2027))
    if tours is None:
        tours = ["atp", "wta"]

    mem = memory.load()
    players_before = len(mem["players"])
    matches = fetch_matches(years, tours)

    if not matches:
        return {"inserted": 0, "new_players": 0, "error": "Aucun match récupéré"}

    db.init()

    # Créer des profils minimaux pour les joueurs inconnus
    new_names = set()
    rank_totals: Dict[str, List[int]] = {}
    for m in matches:
        for player, rank_key in [(m["winner"], "w_rank"), (m["loser"], "l_rank")]:
            if not player:
                continue
            r = m.get(rank_key)
            if r:
                rank_totals.setdefault(player, []).append(r)
            if player not in mem["players"]:
                mem["players"][player] = {
                    "serve": 0.5, "return1": 0.5, "return2": 0.5,
                    "recent": 0.5, "n": 0, "tour": m.get("tour", ""),
                }
                new_names.add(player)

    # Enrichir les profils avec le ranking moyen observé
    for player, ranks in rank_totals.items():
        avg_rank = sum(ranks) // len(ranks)
        if player in mem["players"]:
            mem["players"][player]["rank"] = avg_rank

    # Archiver les matchs en DB — features neutres (pas de serve/return dans ce CSV)
    _neutral = {"serve": 0.5, "return1": 0.5, "return2": 0.5}
    db_matches = []
    for m in matches:
        db_matches.append({
            "id": m["id"],
            "date": m["date"],
            "tour": m.get("tour", "atp"),
            "winner_name": m["winner"],
            "loser_name": m["loser"],
            "winner": _neutral,
            "loser": _neutral,
            "surface": m["surface"],
            "margin": None,
        })
    added = db.archive_matches(db_matches)

    # Archiver les cotes historiques (CLV proxy sur grands tournois 2022-2026).
    odds_rows = [
        {
            "match_id": m["id"], "date": m["date"], "tour": m.get("tour", "atp"),
            "winner": m["winner"], "loser": m["loser"], "surface": m["surface"],
            "b365w": m.get("b365w"), "b365l": m.get("b365l"),
            "psw": m.get("psw"), "psl": m.get("psl"),
            "maxw": m.get("maxw"), "maxl": m.get("maxl"),
            "avgw": m.get("avgw"), "avgl": m.get("avgl"),
        }
        for m in matches
        if m.get("b365w") or m.get("psw") or m.get("maxw")
    ]
    odds_added = db.archive_historical_odds(odds_rows) if odds_rows else 0
    db.sync_from_memory(mem)

    # Reconstruire ELO global + surface depuis toute la DB
    db_rows = db.all_matches_chrono()
    mem["elo"], _ = elo.build_dynamic(db_rows, time_decay_days=365)
    mem["elo_surface"] = {}
    for surf in ("hard", "clay", "grass"):
        mem["elo_surface"][surf], _ = elo.build_dynamic(db_rows, surface_key=surf,
                                                         time_decay_days=365)
    mem["elo_recent"], _ = elo.build_recent(db_rows, days=180)

    memory.save(mem)
    new_players = len(new_names)

    log(f"tennisdata ingest: {added} nouveaux matchs, {odds_added} cotes historiques, "
        f"{new_players} nouveaux joueurs")
    return {
        "inserted": added,
        "odds_inserted": odds_added,
        "total_fetched": len(matches),
        "new_players": new_players,
        "players_total": len(mem["players"]),
        "years": years,
        "tours": tours,
    }
