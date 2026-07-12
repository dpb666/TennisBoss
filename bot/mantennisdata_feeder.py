"""Feeder ManTennisData (github.com/msolonskyi/ManTennisData) — circuit ATP
principal, matchs FEATURE-COMPLETS (serve/return/break points/tie-breaks).

Remplace Sackmann pour l'INGESTION CONTINUE depuis la disparition de ses
repos GitHub (tennis_atp/tennis_wta, constatée le 2026-07-12 — voir la note
en tête de bot/config.py). Sans cette couche, plus aucun nouveau match
n'entrait dans l'apprentissage des poids serve/return/recent ni des stats
clutch : seul bot/tennisdata_feeder.py continuait d'alimenter l'ELO et le
classement, avec des matchs "neutres" (pas de stats détaillées).

Portée : ATP seulement — pas d'équivalent WTA gratuit identifié à ce jour.
bot/tennisdata_feeder.py reste la seule source de matchs WTA (voir sa
docstring pour la limite : pas de stats serve/return/BP/TB pour les femmes).

N'ingère QUE les tournois commençant à partir de MTD_CUTOFF_DATE (lendemain
du dernier match ATP principal archivé depuis Sackmann, 2026-05-17). Avant
cette date, la couverture est déjà assurée par l'archive Sackmann ; comme les
deux sources utilisent des schémas d'id différents ("atp-{tourney_id}-{num}"
vs "atp-mtd-{id}"), un simple INSERT OR IGNORE ne dédupliquerait PAS un même
match réel apparaissant sous les deux id — la coupure nette à la date évite
ce risque plutôt que de tenter un rapprochement flou par (date, joueurs).

Schéma ManTennisData : ratios DÉJÀ agrégés côté source (contrairement à
Sackmann où on reconstruit depuis des comptes de points bruts) :
  win_service_points_won / win_service_points_total       -> serve
  win_first_serve_return_won / ..._total                  -> return1 (retour 1re balle adverse)
  win_second_serve_return_won / ..._total                 -> return2 (retour 2e balle adverse)
  win_break_points_saved / win_break_points_serve_total    -> BP sauvées au service
  winner_tiebreaks_won / loser_tiebreaks_won                -> TB gagnés (direct, pas de score à parser)
Deux fichiers par tour : matches_{year}.csv (les matchs, tournament_id en clé
étrangère) et tournaments.csv (id -> surface + date de début du tournoi).
"""
from __future__ import annotations

import csv
import io
import time
from typing import Any, Dict, List, Optional

from .datasource import _f, _http_get
from .log import log

MTD_MATCHES_URL = (
    "https://raw.githubusercontent.com/msolonskyi/ManTennisData/master/"
    "{tour}/matches_{year}.csv"
)
MTD_TOURNAMENTS_URL = (
    "https://raw.githubusercontent.com/msolonskyi/ManTennisData/master/"
    "{tour}/tournaments.csv"
)

# Lendemain du dernier match ATP principal archivé depuis Sackmann (voir
# docstring). À ne PAS reculer sans revérifier ce cutoff dans la DB
# (MAX(REPLACE(date,'-','')) FROM matches WHERE id LIKE 'atp-%' AND id NOT
# LIKE 'atp-chall-%' AND id NOT LIKE 'atp-mtd-%').
MTD_CUTOFF_DATE = "20260518"

_TOURNEY_CACHE: Dict[str, tuple] = {}
_TOURNEY_TTL = 3600 * 12


def _tournament_index(tour: str = "atp") -> Dict[str, Dict[str, str]]:
    """id de tournoi -> {surface, start_dtm}. Caché en mémoire process (le
    fichier ne change quasiment jamais rétroactivement, seuls des tournois
    y sont ajoutés au fil du temps)."""
    now = time.time()
    hit = _TOURNEY_CACHE.get(tour)
    if hit and hit[0] > now:
        return hit[1]
    text = _http_get(MTD_TOURNAMENTS_URL.format(tour=tour))
    idx: Dict[str, Dict[str, str]] = {}
    if text:
        for row in csv.DictReader(io.StringIO(text)):
            tid = row.get("id")
            if tid:
                idx[tid] = {
                    "surface": (row.get("surface") or "").strip().lower(),
                    "start_dtm": (row.get("start_dtm") or "").strip(),
                }
    _TOURNEY_CACHE[tour] = (now + _TOURNEY_TTL, idx)
    return idx


def _ratio(num: Optional[float], den: Optional[float]) -> float:
    if num is None or den is None or den <= 0:
        return 0.5
    return max(0.0, min(1.0, num / den))


def _match_features(row: Dict[str, str], tinfo: Dict[str, Dict[str, str]],
                    tour: str) -> Optional[Dict[str, Any]]:
    """Transforme une ligne matches_{year}.csv en match TennisBoss standard.

    Renvoie None si les stats de service sont absentes (~4% des lignes,
    principalement des abandons précoces — match_ret non vide, comptes
    tronqués) : mêmes critères de viabilité que datasource._match_features.
    """
    tinfo_row = tinfo.get(row.get("tournament_id", ""))
    if not tinfo_row or not tinfo_row["start_dtm"]:
        return None

    w_svc_won, w_svc_tot = _f(row, "win_service_points_won"), _f(row, "win_service_points_total")
    l_svc_won, l_svc_tot = _f(row, "los_service_points_won"), _f(row, "los_service_points_total")
    if not w_svc_tot or not l_svc_tot:  # abandon précoce -> stats non fiables
        return None

    winner_name = (row.get("winner_name") or "").strip()
    loser_name = (row.get("loser_name") or "").strip()
    if not winner_name or not loser_name:
        return None

    wg, lg = _f(row, "winner_games_won"), _f(row, "loser_games_won")
    margin = int(wg - lg) if wg is not None and lg is not None else None

    def _int(key: str) -> Optional[int]:
        v = _f(row, key)
        return int(v) if v is not None else None

    return {
        "id": f"atp-mtd-{row.get('id', '')}",
        "date": tinfo_row["start_dtm"],
        "tour": tour,
        "winner_name": winner_name,
        "loser_name": loser_name,
        "winner": {
            "serve": _ratio(w_svc_won, w_svc_tot),
            "return1": _ratio(_f(row, "win_first_serve_return_won"),
                              _f(row, "win_first_serve_return_total")),
            "return2": _ratio(_f(row, "win_second_serve_return_won"),
                              _f(row, "win_second_serve_return_total")),
        },
        "loser": {
            "serve": _ratio(l_svc_won, l_svc_tot),
            "return1": _ratio(_f(row, "los_first_serve_return_won"),
                              _f(row, "los_first_serve_return_total")),
            "return2": _ratio(_f(row, "los_second_serve_return_won"),
                              _f(row, "los_second_serve_return_total")),
        },
        "surface": tinfo_row["surface"],
        "margin": margin,
        "w_bp_saved": _f(row, "win_break_points_saved"),
        "w_bp_faced": _f(row, "win_break_points_serve_total"),
        "l_bp_saved": _f(row, "los_break_points_saved"),
        "l_bp_faced": _f(row, "los_break_points_serve_total"),
        "w_tb_won": _int("winner_tiebreaks_won"),
        "l_tb_won": _int("loser_tiebreaks_won"),
    }


def fetch_year(year: int, tour: str = "atp",
              cutoff_date: str = MTD_CUTOFF_DATE) -> List[Dict[str, Any]]:
    """Matchs exploitables d'une année, filtrés à cutoff_date (voir docstring
    de module pour la raison de ce filtre)."""
    text = _http_get(MTD_MATCHES_URL.format(tour=tour, year=year))
    if not text:
        return []
    tinfo = _tournament_index(tour)
    matches: List[Dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text)):
        feat = _match_features(row, tinfo, tour)
        if feat and feat["date"] >= cutoff_date:
            matches.append(feat)
    log(f"ManTennisData {tour.upper()} {year}: {len(matches)} matchs "
        f"exploitables récupérés (>= {cutoff_date}).")
    return matches


def fetch_matches(years: List[int], tour: str = "atp",
                  cutoff_date: str = MTD_CUTOFF_DATE) -> List[Dict[str, Any]]:
    all_matches: List[Dict[str, Any]] = []
    for year in years:
        all_matches.extend(fetch_year(year, tour, cutoff_date))
    all_matches.sort(key=lambda m: (m["date"], m["id"]))
    return all_matches


def ingest(years: Optional[List[int]] = None,
          cutoff_date: str = MTD_CUTOFF_DATE) -> Dict[str, Any]:
    """Entraîne les poids/profils sur les matchs neufs et les archive.

    Mêmes garde-fous que run.py cmd_train : learner.train() ignore tout
    seul les ids déjà présents dans mem["processed"] (persisté), donc
    rappeler cette fonction en boucle (scheduler) ne réapprend jamais deux
    fois sur le même match. db.archive_matches est également idempotent
    (INSERT OR IGNORE sur id). L'ELO est rebâti par bot/tennisdata_feeder.py
    à son prochain cycle (il relit toute la table matches) — pas dupliqué ici.
    """
    from . import config, db, learner, memory

    if years is None:
        import datetime as _dt
        this_year = _dt.date.today().year
        years = [this_year - 1, this_year]  # chevauchement volontaire (fin d'année)

    db.init()
    matches = fetch_matches(years, cutoff_date=cutoff_date)
    if not matches:
        return {"trained": 0, "inserted": 0, "years": years, "error": "Aucun match récupéré"}

    mem = memory.load()
    cfg = config.DEFAULT_CONFIG
    report = learner.train(mem, matches, cfg)
    memory.save(mem)

    added = db.archive_matches(matches)
    n_players = db.sync_from_memory(mem)

    log(f"ManTennisData ingest : +{report['new_matches']} appris, "
        f"+{added} archivés, {n_players} joueurs synchronisés.")
    return {
        "fetched": len(matches),
        "trained": report["new_matches"],
        "inserted": added,
        "players_total": n_players,
        "years": years,
        "cutoff_date": cutoff_date,
    }
