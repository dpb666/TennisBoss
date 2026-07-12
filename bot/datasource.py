"""Récupération des données depuis internet (sans clé API).

Source principale : dataset ATP de Jeff Sackmann (CSV par année) qui contient
les statistiques détaillées de chaque match (points au service, returns...).
À partir de ces données réelles, le bot calcule les profils joueurs et apprend.

Une tentative "live" (Sofascore) est faite mais souvent bloquée (403) : dans ce
cas on bascule proprement sur l'historique — c'est le rôle du self-healing.
"""
from __future__ import annotations

import csv
import io
from typing import Dict, List, Optional

import requests

from . import config
from .log import log


def _http_get(url: str, timeout: int = 20) -> Optional[str]:
    """GET robuste avec user-agent navigateur. Renvoie None en cas d'échec."""
    try:
        resp = requests.get(
            url, headers={"User-Agent": config.BROWSER_UA}, timeout=timeout
        )
        if resp.status_code == 200:
            return resp.text
        log(f"GET {url} -> HTTP {resp.status_code}", "WARN")
    except requests.RequestException as exc:
        log(f"GET {url} a échoué : {exc}", "WARN")
    return None


def _f(row: Dict[str, str], key: str) -> Optional[float]:
    """Lecture tolérante d'un champ numérique."""
    val = row.get(key, "")
    if val is None or val == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _match_features(row: Dict[str, str]) -> Optional[Dict]:
    """Transforme une ligne brute en stats normalisées [0,1] pour les 2 joueurs.

    serve   = % de points gagnés au service
    return1 = % de points gagnés au retour sur 1re balle adverse
    return2 = % de points gagnés au retour sur 2e balle adverse
    """
    w_svpt, l_svpt = _f(row, "w_svpt"), _f(row, "l_svpt")
    w_1stIn, l_1stIn = _f(row, "w_1stIn"), _f(row, "l_1stIn")
    w_1stW, l_1stW = _f(row, "w_1stWon"), _f(row, "l_1stWon")
    w_2ndW, l_2ndW = _f(row, "w_2ndWon"), _f(row, "l_2ndWon")

    needed = [w_svpt, l_svpt, w_1stIn, l_1stIn, w_1stW, l_1stW, w_2ndW, l_2ndW]
    if any(v is None or v <= 0 for v in (w_svpt, l_svpt, w_1stIn, l_1stIn)):
        return None
    if any(v is None for v in needed):
        return None

    w_2ndpts = w_svpt - w_1stIn
    l_2ndpts = l_svpt - l_1stIn
    if w_2ndpts <= 0 or l_2ndpts <= 0:
        return None

    def ratio(num: float, den: float) -> float:
        return max(0.0, min(1.0, num / den)) if den > 0 else 0.5

    winner = {
        "serve": ratio(w_1stW + w_2ndW, w_svpt),
        "return1": ratio(l_1stIn - l_1stW, l_1stIn),     # retour sur 1re balle adverse
        "return2": ratio(l_2ndpts - l_2ndW, l_2ndpts),   # retour sur 2e balle adverse
    }
    loser = {
        "serve": ratio(l_1stW + l_2ndW, l_svpt),
        "return1": ratio(w_1stIn - w_1stW, w_1stIn),
        "return2": ratio(w_2ndpts - w_2ndW, w_2ndpts),
    }

    tb_w, tb_l = parse_tiebreaks(row.get("score", ""))
    return {
        "id": f"{row.get('tourney_id','?')}-{row.get('match_num','?')}",
        "date": row.get("tourney_date", "00000000"),
        "winner_name": (row.get("winner_name") or "").strip(),
        "loser_name": (row.get("loser_name") or "").strip(),
        "winner": winner,
        "loser": loser,
        "surface": (row.get("surface") or "").strip().lower(),   # hard/clay/grass
        "tourney_name": (row.get("tourney_name") or "").strip(),
        "margin": parse_margin(row.get("score", "")),            # jeux gagnant - perdant
        # Stats "clutch" (souvent absentes sur les vieux matchs/ITF -> None)
        "w_bp_saved": _f(row, "w_bpSaved"), "w_bp_faced": _f(row, "w_bpFaced"),
        "l_bp_saved": _f(row, "l_bpSaved"), "l_bp_faced": _f(row, "l_bpFaced"),
        "w_tb_won": tb_w, "l_tb_won": tb_l,
    }


def parse_margin(score: str) -> Optional[int]:
    """Marge de victoire en jeux (jeux vainqueur - jeux perdant) depuis un score
    Sackmann ('6-4 7-6(5)'). None si illisible (walkover/abandon)."""
    if not score:
        return None
    wg = lg = 0
    found = False
    for tok in score.split():
        tok = tok.split("(")[0]            # retire le tie-break "(5)"
        if "-" not in tok:
            continue
        a, _, b = tok.partition("-")
        try:
            wg += int(a)
            lg += int(b)
            found = True
        except ValueError:
            continue
    return (wg - lg) if found else None


def parse_tiebreaks(score: str) -> tuple:
    """Tie-breaks gagnés par (vainqueur, perdant) du match, lus dans le score.

    Le score Sackmann est écrit du point de vue du VAINQUEUR du match :
    '7-6(5) 4-6 7-6(10)' -> le vainqueur a gagné les sets 1 et 3 (donc leurs
    tie-breaks), '6-7(3)' serait un tie-break gagné par le perdant. Un set en
    super tie-break ('[10-7]') compte aussi. Renvoie (None, None) si score vide
    (walkover) — distinct de (0, 0) = match joué sans tie-break.
    """
    if not score or not score.strip():
        return None, None
    tb_w = tb_l = 0
    for tok in score.split():
        if tok.startswith("[") and "-" in tok:      # super tie-break '[10-7]'
            a, _, b = tok.strip("[]").partition("-")
            try:
                if int(a) > int(b):
                    tb_w += 1
                else:
                    tb_l += 1
            except ValueError:
                continue
            continue
        if "(" not in tok:                          # set sans tie-break
            continue
        a, _, b = tok.split("(")[0].partition("-")
        try:
            if int(a) > int(b):                    # ex: 7-6 -> set (et TB) au vainqueur
                tb_w += 1
            else:                                  # ex: 6-7 -> TB au perdant
                tb_l += 1
        except ValueError:
            continue
    return tb_w, tb_l


def fetch_year(year: int, tour: str = "atp") -> List[Dict]:
    """Télécharge et parse une année d'un tour (atp/wta). Liste de matchs exploitables."""
    url = config.SACKMANN_URL.format(tour=tour, year=year)
    text = _http_get(url)
    if not text:
        return []
    matches: List[Dict] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        feat = _match_features(row)
        if feat and feat["winner_name"] and feat["loser_name"]:
            feat["tour"] = tour
            feat["id"] = f"{tour}-{feat['id']}"  # évite toute collision d'id ATP/WTA
            matches.append(feat)
    log(f"{tour.upper()} {year}: {len(matches)} matchs exploitables récupérés.")
    return matches


def fetch_challengers(years: List[int], tours: List[str] = ("atp",)) -> List[Dict]:
    """Récupère les matchs Challenger/Futures ATP et ITF Women WTA de Sackmann."""
    all_matches: List[Dict] = []
    for tour in tours:
        for year in years:
            # WTA uses a separate ITF qual file (W15–W100 circuit)
            if tour == "wta":
                urls = [
                    config.WTA_ITF_URL.format(year=year),
                    config.CHALLENGER_URL.format(tour=tour, year=year),  # qual fallback
                ]
            else:
                urls = [config.CHALLENGER_URL.format(tour=tour, year=year)]

            for url in urls:
                text = _http_get(url)
                if not text:
                    continue
                added = 0
                reader = csv.DictReader(io.StringIO(text))
                for row in reader:
                    feat = _match_features(row)
                    if feat and feat["winner_name"] and feat["loser_name"]:
                        feat["tour"] = tour
                        feat["id"] = f"{tour}-chall-{feat['id']}"
                        all_matches.append(feat)
                        added += 1
                if added:
                    label = "WTA ITF" if "qual_itf" in url else f"{tour.upper()} Challenger"
                    log(f"{label} {year}: {added} matchs récupérés.")
                    break  # vrai fallback : la 2e URL dupliquerait les IDs
    all_matches.sort(key=lambda m: (m["date"], m["id"]))
    return all_matches


def fetch_matches(years: List[int], tours: List[str] = ("atp",),
                  include_challengers: bool = False) -> List[Dict]:
    """Récupère plusieurs années/tours et trie chronologiquement (sans fuite)."""
    all_matches: List[Dict] = []
    for tour in tours:
        for year in years:
            all_matches.extend(fetch_year(year, tour))
    if include_challengers:
        all_matches.extend(fetch_challengers(years, tours))
    all_matches.sort(key=lambda m: (m["date"], m["id"]))
    return all_matches


import datetime as _date
import re as _re
import unicodedata as _ud
from collections import Counter as _Counter
from collections import defaultdict as _ddict

# Mots à ignorer dans les noms de tournois (génériques + niveaux).
_TOURNEY_STOP = {
    "open", "atp", "wta", "masters", "cup", "championships", "championship",
    "international", "trophy", "classic", "tennis", "presented", "by", "the",
    "challenger", "indoor", "outdoor", "ladies", "mens", "men", "women", "of",
    "grand", "prix", "250", "500", "1000", "series", "tour", "club", "city",
}


def normalize_tournament(name: str) -> List[str]:
    """Tokens significatifs d'un nom de tournoi (sans accents, ponctuation, mots vides)."""
    s = _ud.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = _re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return [t for t in s.split() if t and t not in _TOURNEY_STOP]


def _iso_week(date8: str) -> Optional[int]:
    if len(date8) == 8 and date8.isdigit():
        try:
            return _date.date(int(date8[:4]), int(date8[4:6]),
                              int(date8[6:8])).isocalendar()[1]
        except ValueError:
            return None
    return None


def surface_backfill(years: Optional[List[int]] = None,
                     tours: Optional[List[str]] = None) -> Dict[str, Any]:
    """Rétro-remplit matches.surface et construit 3 cartes de résolution de surface :
    par nom normalisé, par token de ville, et par semaine de l'année (saison)."""
    from . import db

    cfg = config.DEFAULT_CONFIG
    years = years or cfg.get("years", [2022, 2023, 2024])
    tours = tours or cfg.get("tours", ["atp", "wta"])

    id_surface: Dict[str, str] = {}
    id_margin: Dict[str, int] = {}
    name_map: Dict[str, str] = {}
    token_counts: Dict[str, _Counter] = _ddict(_Counter)
    week_counts: Dict[int, _Counter] = _ddict(_Counter)

    for tour in tours:
        for year in years:
            text = _http_get(config.SACKMANN_URL.format(tour=tour, year=year))
            if not text:
                continue
            for row in csv.DictReader(io.StringIO(text)):
                mid = f"{tour}-{row.get('tourney_id', '?')}-{row.get('match_num', '?')}"
                margin = parse_margin(row.get("score", ""))
                if margin is not None:
                    id_margin[mid] = margin
                surf = (row.get("surface") or "").strip().lower()
                if not surf:
                    continue
                id_surface[mid] = surf
                toks = normalize_tournament(row.get("tourney_name", ""))
                if toks:
                    name_map.setdefault(" ".join(toks), surf)
                    for t in toks:
                        token_counts[t][surf] += 1
                wk = _iso_week(row.get("tourney_date", ""))
                if wk is not None:
                    week_counts[wk][surf] += 1

    with db.connect() as conn:
        conn.executemany("UPDATE matches SET surface=? WHERE id=?",
                         [(s, i) for i, s in id_surface.items()])
        conn.executemany("UPDATE matches SET margin=? WHERE id=?",
                         [(m, i) for i, m in id_margin.items()])

    token_map = {t: c.most_common(1)[0][0] for t, c in token_counts.items()}
    week_map = {str(w): c.most_common(1)[0][0] for w, c in week_counts.items()}
    log(f"Surface rétro-remplie : {len(id_surface)} matchs ; cartes "
        f"nom={len(name_map)} token={len(token_map)} semaine={len(week_map)}.")
    return {"name": name_map, "token": token_map, "week": week_map}


def clutch_backfill(years: Optional[List[int]] = None,
                    tours: Optional[List[str]] = None,
                    include_challengers: bool = True,
                    url_template: Optional[str] = None) -> int:
    """Rétro-remplit les colonnes clutch (w/l_bp_saved, w/l_bp_faced,
    w/l_tb_won) des matchs déjà archivés, en re-téléchargeant les CSV Sackmann
    (même pattern que surface_backfill). Renvoie le nb de lignes mises à jour.

    Les ids d'archive diffèrent selon la source : '{tour}-{tid}-{num}' pour le
    circuit principal, '{tour}-chall-{tid}-{num}' pour les Challengers/ITF —
    on reconstruit les deux. Les lignes tennis-data.co.uk (pas de stats BP)
    restent NULL, et player_clutch_stats les ignore.

    `url_template` remplace config.SACKMANN_URL (mêmes placeholders
    {tour}/{year}) — nécessaire depuis la disparition du repo Sackmann
    (voir config.py) pour viser un miroir ou une capture Wayback.
    """
    from . import db

    cfg = config.DEFAULT_CONFIG
    years = years or cfg.get("years", [2022, 2023, 2024])
    tours = tours or cfg.get("tours", ["atp", "wta"])

    updates: List[tuple] = []

    def collect(text: str, id_prefix: str) -> None:
        for row in csv.DictReader(io.StringIO(text)):
            mid = f"{id_prefix}{row.get('tourney_id', '?')}-{row.get('match_num', '?')}"
            tb_w, tb_l = parse_tiebreaks(row.get("score", ""))
            bp = (_f(row, "w_bpSaved"), _f(row, "w_bpFaced"),
                  _f(row, "l_bpSaved"), _f(row, "l_bpFaced"))
            if all(v is None for v in bp) and tb_w is None:
                continue  # rien à écrire pour cette ligne
            updates.append((*bp, tb_w, tb_l, mid))

    template = url_template or config.SACKMANN_URL
    for tour in tours:
        for year in years:
            text = _http_get(template.format(tour=tour, year=year))
            if text:
                collect(text, f"{tour}-")
            if include_challengers:
                urls = ([config.WTA_ITF_URL.format(year=year),
                         config.CHALLENGER_URL.format(tour=tour, year=year)]
                        if tour == "wta"
                        else [config.CHALLENGER_URL.format(tour=tour, year=year)])
                for url in urls:
                    ch_text = _http_get(url)
                    if ch_text:
                        collect(ch_text, f"{tour}-chall-")
                        break  # même logique de fallback que fetch_challengers

    with db.connect() as conn:
        cur = conn.executemany(
            "UPDATE matches SET w_bp_saved=?, w_bp_faced=?, l_bp_saved=?, "
            "l_bp_faced=?, w_tb_won=?, l_tb_won=? WHERE id=?",
            updates,
        )
        n = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    log(f"Clutch rétro-rempli : {n} matchs mis à jour "
        f"(sur {len(updates)} lignes CSV avec stats).")
    return n


def probe_live() -> bool:
    """Teste l'accès au flux live. Renvoie False si bloqué (déclenche le fallback)."""
    try:
        resp = requests.get(
            config.SOFASCORE_LIVE_URL,
            headers={"User-Agent": config.BROWSER_UA},
            timeout=10,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False
