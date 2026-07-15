"""Feeder Match Charting Project (github.com/JeffSackmann/tennis_MatchChartingProject)
— ENRICHISSEMENT (pas ingestion) des matchs WTA déjà archivés avec des stats
serve/return/break-points que tennis-data.co.uk n'a jamais fournies.

Contexte : depuis la disparition des repos tennis_wta/tennis_atp de Sackmann
(~mai-juin 2026, voir docs/AUDIT.md et bot/mantennisdata_feeder.py qui comble
le manque côté ATP), aucune source gratuite ÉQUIVALENTE n'a été identifiée
pour les stats fines WTA. Le repo MCP, LUI, reste actif et à jour (vérifié le
2026-07-12 : dernier match chargé 2026-05-24) — mais c'est un projet
CROWDSOURCÉ (~200 matchs WTA/an chartés, grands tournois/joueuses connues),
pas une couverture exhaustive comme Sackmann. On l'utilise donc en
ENRICHISSEMENT d'un match déjà présent dans la DB (inséré par
tennisdata_feeder avec des stats neutres 0.5), jamais en source d'ingestion
de nouveaux matchs.

Détermination du gagnant : MCP ne fournit pas de colonne "winner" exploitable
simplement (voir data_dictionary.txt — il faudrait rejouer les points bruts).
On la déduit du match DÉJÀ archivé : on résout "Player 1"/"Player 2" (noms
complets MCP) vers les noms déjà en base à cette date via bot/namematch.py
(même mécanisme que la résolution de noms d'API), puis on lit directement
qui a gagné dans la ligne existante — pas de nouvelle logique de score à
écrire, et le risque de mal déterminer un gagnant est nul (si la résolution
échoue, le match est simplement ignoré).

Limite connue : MCP donne UN SEUL agrégat retour (return_pts/return_pts_won),
pas de séparation retour 1re/2e balle adverse comme Sackmann/ManTennisData.
return1 et return2 reçoivent donc la même valeur — moins précis, mais
toujours mieux que le neutre 0.5 utilisé jusqu'ici pour ces matchs.

Effet observé (corrigé 2026-07-15) : db.backfill_match_stats_mcp_bulk() remplace
les serve/return neutres 0.5 écrits par tennisdata_feeder, tout en conservant
les vraies stats déjà présentes (ex. 0.777 Sackmann). Les colonnes BP restent
en COALESCE (NULL seulement).

db.backfill_match_stats() (COALESCE strict) reste pour les autres feeders ;
MCP utilise backfill_match_stats_mcp_bulk — idempotent, sans risque d'écraser
une donnée plus fiable que le placeholder 0.5.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional

from .datasource import _f, _http_get
from .log import log
from .namematch import build_index, resolve

MCP_MATCHES_URL = (
    "https://raw.githubusercontent.com/JeffSackmann/tennis_MatchChartingProject/"
    "master/charting-w-matches.csv"
)
MCP_OVERVIEW_URL = (
    "https://raw.githubusercontent.com/JeffSackmann/tennis_MatchChartingProject/"
    "master/charting-w-stats-Overview.csv"
)


def fetch_matches() -> List[Dict[str, str]]:
    text = _http_get(MCP_MATCHES_URL, timeout=30)
    if not text:
        return []
    return list(csv.DictReader(io.StringIO(text)))


def fetch_overview() -> Dict[str, Dict[str, Dict[str, str]]]:
    """match_id -> {player -> ligne "Total" de charting-w-stats-Overview.csv}."""
    text = _http_get(MCP_OVERVIEW_URL, timeout=30)
    if not text:
        return {}
    out: Dict[str, Dict[str, Dict[str, str]]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("set") != "Total":
            continue
        mid = row.get("match_id", "")
        player = row.get("player", "")
        if not mid or not player:
            continue
        out.setdefault(mid, {})[player] = row
    return out


def _player_stats(row: Dict[str, str]) -> Dict[str, float]:
    """Convertit une ligne Overview "Total" en stats standard TennisBoss.

    serve = (1re + 2e balles gagnées) / points au service.
    return1/return2 = MÊME valeur (return_pts_won/return_pts) : MCP ne
    sépare pas retour 1re/2e balle adverse (voir docstring de module).
    """
    serve_pts = _f(row, "serve_pts")
    first_won = _f(row, "first_won") or 0.0
    second_won = _f(row, "second_won") or 0.0
    serve = (first_won + second_won) / serve_pts if serve_pts else None

    return_pts = _f(row, "return_pts")
    return_pts_won = _f(row, "return_pts_won")
    return_ratio = (return_pts_won / return_pts) if return_pts else None

    return {
        "serve": serve,
        "return1": return_ratio,
        "return2": return_ratio,
        "bp_faced": _f(row, "bk_pts"),
        "bp_saved": _f(row, "bp_saved"),
    }


def backfill(tour: str = "wta") -> Dict[str, Any]:
    """Complète les matchs WTA déjà archivés avec les stats MCP disponibles.

    Ne modifie que des colonnes NULL ou neutres 0.5 pour serve/return (voir
    db.backfill_match_stats_mcp_bulk) — BP en COALESCE strict ; ré-exécutable.

    Charge TOUT l'index (date -> lignes matches) en UNE requête plutôt que
    d'ouvrir une connexion sqlite par match candidat : sur /mnt/c (WSL sur
    NTFS), ~4000 matchs MCP × 3 connexions chacun a mis plus de 15 minutes
    sans terminer lors du premier essai — voir db.matches_index_by_date.
    """
    from . import db

    matches = fetch_matches()
    if not matches:
        return {"checked": 0, "updated": 0, "error": "Aucun match MCP récupéré"}

    overview = fetch_overview()
    date_index = db.matches_index_by_date(tour)
    name_index_cache: Dict[str, Dict[str, List[str]]] = {}

    updates: List[Any] = []
    checked = 0
    skipped_unresolved = 0

    for m in matches:
        p1, p2 = (m.get("Player 1") or "").strip(), (m.get("Player 2") or "").strip()
        date = (m.get("Date") or "").strip()
        match_id = m.get("match_id", "")
        if not p1 or not p2 or not date or not match_id:
            continue
        ov = overview.get(match_id)
        if not ov or p1 not in ov or p2 not in ov:
            continue

        rows_for_date = date_index.get(date)
        if not rows_for_date:
            continue
        checked += 1

        if date not in name_index_cache:
            names = set()
            for r in rows_for_date:
                names.add(r["winner"])
                names.add(r["loser"])
            name_index_cache[date] = build_index(list(names), {})
        r1 = resolve(p1, name_index_cache[date])
        r2 = resolve(p2, name_index_cache[date])
        if not r1 or not r2 or r1 == r2:
            skipped_unresolved += 1
            continue

        row = next(
            (r for r in rows_for_date if {r["winner"], r["loser"]} == {r1, r2}), None)
        if not row:
            skipped_unresolved += 1
            continue

        s1, s2 = _player_stats(ov[p1]), _player_stats(ov[p2])
        w_stats, l_stats = (s1, s2) if row["winner"] == r1 else (s2, s1)
        updates.append((row["id"], w_stats, l_stats))

    updated = db.backfill_match_stats_mcp_bulk(updates)
    log(f"MCP backfill {tour.upper()} : {checked} matchs avec stats exploitables, "
        f"{updated} lignes enrichies, {skipped_unresolved} non résolus.", "INFO")
    return {
        "fetched": len(matches),
        "checked": checked,
        "updated": updated,
        "skipped_unresolved": skipped_unresolved,
    }
