"""Fusion des profils joueurs dupliqués par variation de format de nom.

Contexte : bot/namematch.py::split_name() ne reconnaissait pas le format
"Andreeva M." (nom de famille D'ABORD, initiale ensuite — utilisé par
tennisdata_feeder.py / tennis-data.co.uk) et le confondait avec "prénom nom"
(bug corrigé le 2026-07-12). Conséquence en production, mesurée sur la DB
réelle : 713 groupes candidats, 1460 profils sur 5163 (~28 %) —
"Andreeva M." et "Mirra Andreeva" existaient comme DEUX profils distincts
dans mem["players"] pour la même joueuse, chacun avec un ELO, une forme
récente (EMA serve/return/recent) et un compteur de matchs (n) incomplets.

Piège découvert en construisant ce module : regrouper uniquement par
(initiale, nom_de_famille) est TROP grossier — "Xin Yu Wang", "Xiyu Wang" et
"Xiaofei Wang" sont trois joueuses WTA RÉELLEMENT DISTINCTES qui partagent
le même nom de famille et la même initiale "X". Fusionner ce groupe
mélangerait les stats de trois personnes différentes — pire que le bug
d'origine (deux profils séparés mais chacun correct individuellement).
Un groupe n'est donc fusionné automatiquement QUE s'il contient au plus UN
prénom complet distinct (ex. "Mirra Andreeva" + "Andreeva M." + "M.
Andreeva" -> un seul prénom complet, "mirra" -> fusion sûre). Les groupes
avec 2+ prénoms complets différents sont exclus de merge() et remontés à
part par report() sous "ambiguous" pour revue manuelle.

Ce module ne modifie rien tout seul :
  report(mem)  -> diagnostic dry-run (aucune écriture).
  merge(mem)   -> fusionne les groupes SÛRS : mem["players"], renomme
                  winner/loser dans db.matches vers le nom canonique, puis
                  reconstruit l'ELO en rejouant TOUTE la DB (déjà idempotent
                  et sûr : c'est exactement ce que fait
                  tennisdata_feeder.ingest() après chaque cycle normal).
                  Idempotent : après une fusion, un second appel ne
                  retrouve plus de doublon dans ce groupe.

Choix du nom canonique : on préfère un nom "complet" (aucun token réduit à
une initiale, ex. "Mirra Andreeva") à une forme abrégée ("Andreeva M." /
"M. Andreeva") — plus lisible côté Android/chat. À profils tous abrégés ou
tous complets, on garde celui avec le plus grand `n` (profil le plus
alimenté, donc le plus fiable).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import db, elo
from .log import log
from .namematch import _norm, split_name


def _is_full_name(name: str) -> bool:
    """True si aucun token n'est réduit à une initiale isolée."""
    tokens = name.replace(",", " ").split()
    return bool(tokens) and all(len(tok.strip(".")) > 1 for tok in tokens)


def _full_first_name_key(name: str) -> Optional[str]:
    """Signature normalisée du prénom complet si `name` est un nom complet
    (voir _is_full_name), sinon None. Sert à détecter les collisions
    d'initiale entre prénoms complets DIFFÉRENTS partageant un même nom de
    famille (ex. "Xin Yu Wang" vs "Xiyu Wang" vs "Xiaofei Wang")."""
    if not _is_full_name(name):
        return None
    if "," in name:
        _, _, first_part = name.partition(",")
        tokens = _norm(first_part).split()
    else:
        tokens = _norm(name).split()[:-1]
    return " ".join(tokens) or None


def find_duplicate_groups(
    mem: Dict[str, Any],
) -> Tuple[Dict[Tuple[str, str], List[str]], Dict[Tuple[str, str], List[str]]]:
    """Regroupe les noms de mem["players"] par (initiale, nom_de_famille).

    Renvoie (groupes_sûrs, groupes_ambigus) : un groupe est ambigu s'il
    contient 2+ prénoms complets distincts (collision d'initiale, pas la
    même personne — voir docstring de module).
    """
    coarse: Dict[Tuple[str, str], List[str]] = {}
    for name in mem.get("players", {}):
        key = split_name(name)
        if key == ("", ""):
            continue
        coarse.setdefault(key, []).append(name)

    safe: Dict[Tuple[str, str], List[str]] = {}
    ambiguous: Dict[Tuple[str, str], List[str]] = {}
    for key, names in coarse.items():
        if len(names) < 2:
            continue
        full_sigs = {sig for n in names if (sig := _full_first_name_key(n))}
        if len(full_sigs) > 1:
            ambiguous[key] = names
        else:
            safe[key] = names
    return safe, ambiguous


def choose_canonical(names: List[str], players: Dict[str, Any]) -> str:
    full = [n for n in names if _is_full_name(n)]
    pool = full or names
    return max(pool, key=lambda n: int(players.get(n, {}).get("n", 0) or 0))


def report(mem: Dict[str, Any]) -> Dict[str, Any]:
    """Diagnostic dry-run : ne modifie rien."""
    safe, ambiguous = find_duplicate_groups(mem)
    players = mem.get("players", {})

    def _details(groups):
        out = []
        for names in groups.values():
            canon = choose_canonical(names, players)
            out.append({
                "canonical": canon,
                "aliases": sorted(n for n in names if n != canon),
                "total_n": sum(int(players.get(n, {}).get("n", 0) or 0) for n in names),
            })
        out.sort(key=lambda d: d["total_n"], reverse=True)
        return out

    return {
        "total_players": len(players),
        "duplicate_groups": len(safe),
        "players_involved": sum(len(v) for v in safe.values()),
        "details": _details(safe),
        "ambiguous_groups": len(ambiguous),
        "ambiguous_details": _details(ambiguous),
    }


def _merge_profile(names: List[str], canon: str, players: Dict[str, Any]) -> Dict[str, Any]:
    total_n = sum(int(players.get(n, {}).get("n", 0) or 0) for n in names)

    def _wavg(field: str, default: float = 0.5) -> float:
        if total_n <= 0:
            vals = [float(players[n].get(field, default) or default)
                     for n in names if n in players]
            return sum(vals) / len(vals) if vals else default
        acc = 0.0
        for n in names:
            p = players.get(n, {})
            w = int(p.get("n", 0) or 0)
            acc += w * float(p.get(field, default) or default)
        return acc / total_n

    merged = dict(players.get(canon, {}))
    merged["n"] = total_n
    merged["serve"] = _wavg("serve")
    merged["return1"] = _wavg("return1")
    merged["return2"] = _wavg("return2")
    merged["recent"] = _wavg("recent")
    for field in ("tour", "rank"):
        if not merged.get(field):
            for n in names:
                v = players.get(n, {}).get(field)
                if v:
                    merged[field] = v
                    break
    return merged


def merge(mem: Dict[str, Any]) -> Dict[str, Any]:
    """Applique la fusion des groupes SÛRS uniquement (voir find_duplicate_groups) :
    mem["players"] + rename dans db.matches + rebuild ELO.

    Ne persiste PAS mem (l'appelant décide, comme les autres feeders —
    voir mantennisdata_feeder.ingest()/tennisdata_feeder.ingest()).
    """
    safe, ambiguous = find_duplicate_groups(mem)
    players = mem["players"]
    rename_map: Dict[str, str] = {}
    merged_groups = 0

    for names in safe.values():
        canon = choose_canonical(names, players)
        aliases = [n for n in names if n != canon]
        if not aliases:
            continue
        players[canon] = _merge_profile(names, canon, players)
        for alias in aliases:
            rename_map[alias] = canon
            players.pop(alias, None)
        merged_groups += 1

    matches_renamed = db.rename_players_in_matches(rename_map)
    players_deleted = db.delete_players(list(rename_map.keys()))

    # Reconstruit l'ELO depuis toute la DB (winner/loser maintenant renommés
    # vers le nom canonique) — mêmes appels qu'un ingest normal, voir
    # tennisdata_feeder.ingest().
    db_rows = db.all_matches_chrono()
    mem["elo"], _ = elo.build_dynamic(db_rows, time_decay_days=365)
    mem["elo_surface"] = {}
    for surf in ("hard", "clay", "grass"):
        mem["elo_surface"][surf], _ = elo.build_dynamic(
            db_rows, surface_key=surf, time_decay_days=365)
    mem["elo_recent"], _ = elo.build_recent(db_rows, days=180)

    db.sync_from_memory(mem)
    log(f"Dédup joueurs : {merged_groups} groupes fusionnés, "
        f"{matches_renamed} lignes matches renommées, "
        f"{players_deleted} alias supprimés de la table players, "
        f"{len(ambiguous)} groupes ambigus laissés de côté.", "INFO")
    return {
        "merged_groups": merged_groups,
        "matches_renamed": matches_renamed,
        "players_deleted": players_deleted,
        "players_total": len(players),
        "ambiguous_groups_skipped": len(ambiguous),
    }
