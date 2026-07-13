"""Base de données SQLite "solide" de TennisBoss.

Tables :
  meta          : clé/valeur (poids du modèle, biais, métriques globales)
  players       : dictionnaire de TOUS les joueurs (ATP+WTA) + leur probabilité
  matches       : archive de tous les matchs exploités (pour rejouer/backtester)
  predictions   : historique des prédictions demandées
  backtests     : archive des campagnes de backtest (métriques out-of-sample)

Tout est en SQL standard (module sqlite3 de la lib standard, aucune dépendance).
"""
from __future__ import annotations

import difflib
import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import config, features, predictor
from .log import log

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS players (
    name     TEXT PRIMARY KEY,
    tour     TEXT,
    n        INTEGER,
    serve    REAL,
    return1  REAL,
    return2  REAL,
    recent   REAL,
    rating   REAL,
    win_prob REAL,
    updated  TEXT
);
CREATE TABLE IF NOT EXISTS matches (
    id        TEXT PRIMARY KEY,
    date      TEXT,
    tour      TEXT,
    winner    TEXT,
    loser     TEXT,
    w_serve   REAL, w_return1 REAL, w_return2 REAL,
    l_serve   REAL, l_return1 REAL, l_return2 REAL,
    surface   TEXT,
    margin    INTEGER,
    -- Stats "clutch" (Sackmann ; NULL pour les lignes tennis-data.co.uk) :
    -- break points sauvées/concédées AU SERVICE, tie-breaks gagnés par match.
    w_bp_saved REAL, w_bp_faced REAL,
    l_bp_saved REAL, l_bp_faced REAL,
    w_tb_won  INTEGER, l_tb_won INTEGER
);
CREATE TABLE IF NOT EXISTS predictions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT,
    player1  TEXT, player2 TEXT,
    prob1    REAL, favorite TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS backtests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT,
    span         TEXT,
    tours        TEXT,
    n_train      INTEGER,
    n_test       INTEGER,
    accuracy     REAL,
    logloss      REAL,
    brier        REAL,
    baseline     REAL,
    accuracy_elo REAL,
    logloss_elo  REAL,
    brier_elo    REAL,
    notes        TEXT
);
CREATE TABLE IF NOT EXISTS settled_matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key   TEXT UNIQUE,
    date        TEXT,
    tour        TEXT,
    tournament  TEXT,
    player1     TEXT, player2 TEXT,
    winner      TEXT,
    final_score TEXT,
    sets        TEXT,
    pred_favorite TEXT,
    pred_prob1  REAL,
    correct     INTEGER,
    settled_ts  TEXT
);
CREATE TABLE IF NOT EXISTS calibration_history (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT,
    n        INTEGER,
    accuracy REAL,
    roi      REAL,
    brier    REAL,
    atp_acc  REAL,
    wta_acc  REAL,
    fav_acc  REAL,
    dog_acc  REAL,
    notes    TEXT
);
CREATE TABLE IF NOT EXISTS bet_log (
    date     TEXT,
    player1  TEXT,
    player2  TEXT,
    favorite TEXT,
    fav_odds REAL,
    ts       TEXT,
    PRIMARY KEY (player1, player2)
);
CREATE TABLE IF NOT EXISTS value_picks (
    date     TEXT,
    player1  TEXT,
    player2  TEXT,
    side     TEXT,      -- joueur misé (best_ev > 0 sur la proba blendée)
    odds     REAL,      -- cote captée au moment du pick
    ev       REAL,      -- EV blendée (%) au moment du pick
    ts       TEXT,
    PRIMARY KEY (player1, player2)
);
CREATE TABLE IF NOT EXISTS clv_log (
    event_key      TEXT PRIMARY KEY,   -- clé du match (ou paire si pas d'event)
    date           TEXT,
    player1        TEXT, player2 TEXT,
    pick_side      TEXT,               -- joueur misé
    pick_odds      REAL,               -- cote captée à la décision
    pick_prob      REAL,               -- proba blendée du modèle (pour Kelly)
    confidence     REAL,
    pick_ts        TEXT,
    closing_odds   REAL,               -- cote juste avant le match (closing line)
    closing_src    TEXT,               -- 'snapshot' (T-15) ou 'last_seen' (fallback)
    closing_ts     TEXT,
    result         INTEGER,            -- 1=gagné 0=perdu (au settlement)
    clv_pct        REAL,               -- (pick_odds/closing_odds - 1)*100
    beat_closing   INTEGER,            -- 1 si pick_odds > closing_odds
    pnl_flat       REAL,               -- mise 1u
    pnl_kelly      REAL,               -- fraction de bankroll (Kelly 0.25)
    settled_ts     TEXT,
    honeypot_flag        INTEGER,      -- 1 si conditions+surface+foule alignées (weather_profile)
    honeypot_beneficiary TEXT,         -- 'p1' ou 'p2'
    honeypot_player      TEXT,
    honeypot_edge_pct    REAL
);
CREATE TABLE IF NOT EXISTS market_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key  TEXT,            -- id événement odds-api (regroupe les snapshots d'un même match)
    ts         TEXT,            -- horodatage ISO de la capture
    player1    TEXT, player2 TEXT,
    odds_home  REAL, odds_away REAL,   -- cote de référence (sharp book / consensus, cf. fetch_match_winner)
    hours_ahead REAL            -- heures avant le coup d'envoi au moment de la capture
);
CREATE INDEX IF NOT EXISTS idx_snap_event ON market_snapshots(event_key, ts);
CREATE TABLE IF NOT EXISTS device_tokens (
    token       TEXT PRIMARY KEY,   -- token FCM (unique par installation d'app)
    platform    TEXT,               -- "android" (seule plateforme actuelle)
    registered_ts TEXT,
    last_seen_ts  TEXT
);
CREATE TABLE IF NOT EXISTS followed_players (
    name        TEXT PRIMARY KEY,   -- nom résolu (même convention que predictions.player1/2)
    followed_ts TEXT
);
CREATE TABLE IF NOT EXISTS live_prob_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key  TEXT,            -- id événement live (regroupe les points d'un même match)
    ts         TEXT,            -- horodatage ISO de la capture
    prob1      REAL,            -- proba in-play du joueur 1 à cet instant
    sets_home  INTEGER, sets_away INTEGER,
    minute     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_liveprob_event ON live_prob_snapshots(event_key, ts);
CREATE TABLE IF NOT EXISTS inplay_picks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    event_id     TEXT,          -- ID événement odds-api (pour auto-settlement)
    player1      TEXT,
    player2      TEXT,
    league       TEXT,
    market_type  TEXT,
    market_label TEXT,
    pick         TEXT,
    odds         REAL,          -- cote bookmaker au moment du pick
    odds_home    REAL,          -- cote live joueur 1 (snapshot)
    odds_away    REAL,          -- cote live joueur 2 (snapshot)
    odds_book    TEXT,          -- source (Betfair, Bet365...)
    prob         REAL,          -- proba modèle (%)
    score        TEXT,          -- score au moment du pick (ex: "6-3, 2-1")
    sets_home    INTEGER,       -- sets du joueur 1 au moment du pick
    sets_away    INTEGER,       -- sets du joueur 2 au moment du pick
    minute       INTEGER,       -- minute de jeu
    stake        REAL DEFAULT 1.0,
    result       TEXT DEFAULT NULL,   -- 'W' 'L' 'V'(void)
    pnl          REAL DEFAULT NULL,
    auto_settled INTEGER DEFAULT 0    -- 1 si réglé automatiquement
);
CREATE TABLE IF NOT EXISTS historical_odds (
    match_id TEXT PRIMARY KEY,   -- même id que matches (source tennisdata)
    date     TEXT,
    tour     TEXT,
    winner   TEXT,
    loser    TEXT,
    surface  TEXT,
    b365w    REAL,   -- Bet365 (soft)
    b365l    REAL,
    psw      REAL,   -- Pinnacle (sharp)
    psl      REAL,
    maxw     REAL,   -- meilleure cote tous books confondus (tennis-data.co.uk)
    maxl     REAL,
    avgw     REAL,   -- moyenne marché tous books
    avgl     REAL
);
CREATE INDEX IF NOT EXISTS idx_hist_odds_date ON historical_odds(date);
CREATE INDEX IF NOT EXISTS idx_inplay_ts ON inplay_picks(ts);
CREATE INDEX IF NOT EXISTS idx_clv_date ON clv_log(date);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(date);
CREATE INDEX IF NOT EXISTS idx_players_tour ON players(tour);
CREATE INDEX IF NOT EXISTS idx_settled_date ON settled_matches(date);
-- player_record / player_recent_matches / head_to_head filtrent sur winner/loser
-- (sinon scan complet des ~80 000 matchs à chaque prédiction/H2H).
CREATE INDEX IF NOT EXISTS idx_matches_winner ON matches(winner);
CREATE INDEX IF NOT EXISTS idx_matches_loser ON matches(loser);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    # timeout=15s : 3 process (quant, bot, supervisor) écrivent en concurrence
    # sur /mnt/c — laisse le temps d'acquérir le verrou plutôt que "database is
    # locked". synchronous=NORMAL est sûr et rapide EN MODE WAL (établi par init).
    #
    # ATTENTION : n'appelez JAMAIS connect() à l'intérieur d'une boucle sur de
    # nombreuses lignes (ex. `for row in big_query: with connect() as c: ...`).
    # bot/mcp_feeder.py le faisait (~3 connexions x ~4000 itérations) et un run
    # réel a dépassé 15 minutes sans terminer sur /mnt/c (WSL sur NTFS, lent
    # pour beaucoup de petits appels système) — corrigé le 2026-07-13 en
    # chargeant tout l'index en UNE requête puis en appliquant le lot dans UNE
    # transaction (voir db.matches_index_by_date / backfill_match_stats_bulk).
    # Une seule connexion par requête HTTP / tick de boucle de fond reste fine.
    conn = sqlite3.connect(config.DB_FILE, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    """Crée la base et le schéma si nécessaire (idempotent)."""
    # WAL persiste dans l'en-tête du fichier : une seule fois suffit, mais on le
    # (ré)affirme à chaque init au cas où la base aurait été créée en mode delete.
    with connect() as conn:
        mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if mode != "wal":
            log(f"Attention : WAL indisponible (mode={mode}) — concurrence fragile.",
                "WARN")
        conn.executescript(_SCHEMA)
        # Migrations idempotentes (bases déjà créées sans ces colonnes).
        for col, ddl in (
            ("surface", "ALTER TABLE matches ADD COLUMN surface TEXT"),
            ("margin", "ALTER TABLE matches ADD COLUMN margin INTEGER"),
            ("w_bp_saved", "ALTER TABLE matches ADD COLUMN w_bp_saved REAL"),
            ("w_bp_faced", "ALTER TABLE matches ADD COLUMN w_bp_faced REAL"),
            ("l_bp_saved", "ALTER TABLE matches ADD COLUMN l_bp_saved REAL"),
            ("l_bp_faced", "ALTER TABLE matches ADD COLUMN l_bp_faced REAL"),
            ("w_tb_won", "ALTER TABLE matches ADD COLUMN w_tb_won INTEGER"),
            ("l_tb_won", "ALTER TABLE matches ADD COLUMN l_tb_won INTEGER"),
            ("accuracy_elo", "ALTER TABLE backtests ADD COLUMN accuracy_elo REAL"),
            ("logloss_elo",  "ALTER TABLE backtests ADD COLUMN logloss_elo REAL"),
            ("brier_elo",    "ALTER TABLE backtests ADD COLUMN brier_elo REAL"),
            ("result",  "ALTER TABLE value_picks ADD COLUMN result INTEGER"),
            ("pnl",     "ALTER TABLE value_picks ADD COLUMN pnl REAL"),
            ("winner",  "ALTER TABLE value_picks ADD COLUMN winner TEXT"),
            ("league",  "ALTER TABLE value_picks ADD COLUMN league TEXT"),
            ("surface", "ALTER TABLE value_picks ADD COLUMN surface TEXT"),
            ("kelly_u", "ALTER TABLE value_picks ADD COLUMN kelly_u REAL"),
            ("honeypot_flag", "ALTER TABLE clv_log ADD COLUMN honeypot_flag INTEGER"),
            ("honeypot_beneficiary", "ALTER TABLE clv_log ADD COLUMN honeypot_beneficiary TEXT"),
            ("honeypot_player", "ALTER TABLE clv_log ADD COLUMN honeypot_player TEXT"),
            ("honeypot_edge_pct", "ALTER TABLE clv_log ADD COLUMN honeypot_edge_pct REAL"),
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # colonne déjà présente
    # Auto-réparation : quick_check rate les corruptions d'index (vu le 2026-06-11),
    # donc integrity_check complet ; REINDEX si nécessaire. Mais integrity_check
    # coûte ~13s sur /mnt/c (lecture de toute la base) : on le borne à 1×/24h via
    # meta, sinon 3 process × chaque démarrage = surcoût inacceptable.
    import time as _t
    try:
        last = float(get_meta("last_integrity_check") or 0.0)
    except (TypeError, ValueError):
        last = 0.0
    if _t.time() - last > 86400:
        health = health_check(repair=True)
        set_meta("last_integrity_check", str(_t.time()))
        if not health["ok"]:
            log(f"Base : corruption détectée {health['problems'][:2]} — "
                f"réparée={health['repaired']}.", "WARN")
    log(f"Base SQLite prête : {config.DB_FILE}")


def health_check(repair: bool = False) -> Dict[str, Any]:
    """Vérifie l'intégrité de la base. Si `repair`, REINDEX en cas de corruption
    d'index (cause la plus fréquente sur /mnt/c). Renvoie l'état."""
    with connect() as conn:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        problems = [r[0] for r in rows if r[0] != "ok"]
        repaired = False
        if problems and repair:
            conn.execute("REINDEX")
            conn.commit()
            rows2 = conn.execute("PRAGMA integrity_check").fetchall()
            problems = [r[0] for r in rows2 if r[0] != "ok"]
            repaired = not problems
    return {"ok": not problems, "problems": problems, "repaired": repaired}


# --- Archive des matchs ----------------------------------------------------
def archive_matches(matches: List[Dict]) -> int:
    """Insère les matchs dans l'archive (ignore les doublons). Renvoie le nb ajoutés."""
    rows = [
        (
            m["id"], m["date"], m.get("tour", "atp"),
            m["winner_name"], m["loser_name"],
            m["winner"]["serve"], m["winner"]["return1"], m["winner"]["return2"],
            m["loser"]["serve"], m["loser"]["return1"], m["loser"]["return2"],
            m.get("surface", ""), m.get("margin"),
            m.get("w_bp_saved"), m.get("w_bp_faced"),
            m.get("l_bp_saved"), m.get("l_bp_faced"),
            m.get("w_tb_won"), m.get("l_tb_won"),
        )
        for m in matches
    ]
    with connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        conn.executemany(
            "INSERT OR IGNORE INTO matches "
            "(id,date,tour,winner,loser,w_serve,w_return1,w_return2,"
            " l_serve,l_return1,l_return2,surface,margin,"
            " w_bp_saved,w_bp_faced,l_bp_saved,l_bp_faced,w_tb_won,l_tb_won) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        after = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    return after - before


def rename_players_in_matches(rename_map: Dict[str, str]) -> int:
    """Renomme winner/loser dans matches selon rename_map (alias -> canonique).

    Utilisé par la fusion de profils dupliqués (bot/dedupe_players.py) :
    une fois les alias renommés vers le nom canonique, elo.build_dynamic()
    rejoue toute la DB et produit directement un historique ELO unifié pour
    ce joueur, sans qu'il soit nécessaire de fusionner les ratings à la main.
    """
    if not rename_map:
        return 0
    total = 0
    with connect() as conn:
        for alias, canon in rename_map.items():
            total += conn.execute(
                "UPDATE matches SET winner=? WHERE winner=?", (canon, alias)).rowcount
            total += conn.execute(
                "UPDATE matches SET loser=? WHERE loser=?", (canon, alias)).rowcount
    return total


def delete_players(names: List[str]) -> int:
    """Supprime des lignes de la table players (alias fusionnés — voir
    bot/dedupe_players.py). sync_from_memory() ne fait qu'upsert, jamais de
    DELETE, donc les alias orphelins doivent être nettoyés explicitement."""
    if not names:
        return 0
    total = 0
    with connect() as conn:
        for n in names:
            total += conn.execute("DELETE FROM players WHERE name=?", (n,)).rowcount
    return total


def matches_index_by_date(tour: str) -> Dict[str, List[sqlite3.Row]]:
    """Toutes les lignes matches d'un tour, groupées par date compacte
    (YYYYMMDD) — UNE SEULE requête. Sert de base à un enrichissement en
    masse (bot/mcp_feeder.py) : interroger la DB une fois par match candidat
    (des milliers de connexions sqlite individuelles) s'est avéré beaucoup
    trop lent sur /mnt/c (WSL sur NTFS) — un run réel a dépassé 15 minutes
    sans terminer. Cet index se construit en une passe, en mémoire.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, date, winner, loser FROM matches WHERE tour=?", (tour,)
        ).fetchall()
    index: Dict[str, List[sqlite3.Row]] = {}
    for r in rows:
        index.setdefault(r["date"].replace("-", ""), []).append(r)
    return index


def _apply_backfill(conn: sqlite3.Connection, match_id: str,
                    winner_stats: Dict[str, float], loser_stats: Dict[str, float]) -> bool:
    cur = conn.execute(
        "UPDATE matches SET "
        "w_serve=COALESCE(w_serve, ?), w_return1=COALESCE(w_return1, ?), "
        "w_return2=COALESCE(w_return2, ?), "
        "l_serve=COALESCE(l_serve, ?), l_return1=COALESCE(l_return1, ?), "
        "l_return2=COALESCE(l_return2, ?), "
        "w_bp_saved=COALESCE(w_bp_saved, ?), w_bp_faced=COALESCE(w_bp_faced, ?), "
        "l_bp_saved=COALESCE(l_bp_saved, ?), l_bp_faced=COALESCE(l_bp_faced, ?) "
        "WHERE id=?",
        (
            winner_stats.get("serve"), winner_stats.get("return1"), winner_stats.get("return2"),
            loser_stats.get("serve"), loser_stats.get("return1"), loser_stats.get("return2"),
            winner_stats.get("bp_saved"), winner_stats.get("bp_faced"),
            loser_stats.get("bp_saved"), loser_stats.get("bp_faced"),
            match_id,
        ),
    )
    return cur.rowcount > 0


def backfill_match_stats(match_id: str, winner_stats: Dict[str, float],
                         loser_stats: Dict[str, float]) -> bool:
    """Complète les colonnes serve/return/clutch d'un match déjà archivé,
    SEULEMENT si elles sont actuellement NULL (COALESCE) — n'écrase jamais
    une valeur déjà présente, plus fiable qu'un enrichissement a posteriori.
    Renvoie True si la ligne existe (que quelque chose ait changé ou non).

    Un seul match -> une seule connexion. Pour un lot, voir
    backfill_match_stats_bulk (une connexion pour tout le lot).
    """
    with connect() as conn:
        return _apply_backfill(conn, match_id, winner_stats, loser_stats)


def backfill_match_stats_bulk(
    updates: List[Tuple[str, Dict[str, float], Dict[str, float]]],
) -> int:
    """Comme backfill_match_stats, mais pour tout un lot EN UNE SEULE
    connexion/transaction — voir matches_index_by_date pour le contexte
    (évite des milliers de connexions individuelles)."""
    if not updates:
        return 0
    updated = 0
    with connect() as conn:
        for match_id, winner_stats, loser_stats in updates:
            if _apply_backfill(conn, match_id, winner_stats, loser_stats):
                updated += 1
    return updated


def archive_historical_odds(rows: List[Dict]) -> int:
    """Insère les cotes historiques (tennis-data.co.uk) — ignore les doublons.

    Permet de mesurer après coup si le modèle aurait battu le marché sur les
    grands tournois 2022-2026 (CLV proxy), sans dépendre de la capture live.
    """
    tuples = [
        (
            r["match_id"], r["date"], r.get("tour", ""), r["winner"], r["loser"],
            r.get("surface", ""),
            r.get("b365w"), r.get("b365l"), r.get("psw"), r.get("psl"),
            r.get("maxw"), r.get("maxl"), r.get("avgw"), r.get("avgl"),
        )
        for r in rows
    ]
    with connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM historical_odds").fetchone()[0]
        conn.executemany(
            "INSERT OR IGNORE INTO historical_odds "
            "(match_id,date,tour,winner,loser,surface,b365w,b365l,psw,psl,maxw,maxl,avgw,avgl) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            tuples,
        )
        after = conn.execute("SELECT COUNT(*) FROM historical_odds").fetchone()[0]
    return after - before


# --- Dictionnaire des joueurs + méta ---------------------------------------
def sync_from_memory(mem: Dict[str, Any]) -> int:
    """Écrit le modèle et le dictionnaire joueurs (avec leur proba) en base.

    win_prob = probabilité que le joueur batte un adversaire "moyen" (features 0.5),
    selon le modèle appris. C'est la "force" du joueur exprimée en probabilité.
    """
    import datetime as _dt

    now = _dt.datetime.now().isoformat(timespec="seconds")
    weights, bias = mem["weights"], mem["bias"]
    neutral = {k: 0.5 for k in config.FEATURE_ORDER}

    rows = []
    for name, prof in mem["players"].items():
        feat = features.feature_vector(prof)
        win_prob, _, score, _ = predictor.probability(weights, bias, feat, neutral)
        rows.append((
            name, prof.get("tour", ""), int(prof.get("n", 0)),
            round(feat["serve"], 4), round(feat["return1"], 4),
            round(feat["return2"], 4), round(feat["recent"], 4),
            round(score, 4), round(win_prob, 4), now,
        ))

    with connect() as conn:
        conn.executemany(
            "INSERT INTO players "
            "(name,tour,n,serve,return1,return2,recent,rating,win_prob,updated) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "tour=excluded.tour,n=excluded.n,serve=excluded.serve,"
            "return1=excluded.return1,return2=excluded.return2,recent=excluded.recent,"
            "rating=excluded.rating,win_prob=excluded.win_prob,updated=excluded.updated",
            rows,
        )
        _set_meta(conn, "weights", json.dumps(weights))
        _set_meta(conn, "bias", str(bias))
        _set_meta(conn, "metrics", json.dumps(mem["metrics"]))
    return len(rows)


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# --- Lectures pratiques ----------------------------------------------------
def top_players(limit: int = 20, tour: Optional[str] = None,
                min_n: int = 5) -> List[sqlite3.Row]:
    q = ("SELECT name,tour,n,win_prob,rating,serve,recent FROM players "
         "WHERE n>=? {tour} ORDER BY win_prob DESC LIMIT ?")
    params: List[Any] = [min_n]
    tour_clause = ""
    if tour:
        tour_clause = "AND tour=?"
        params.append(tour)
    params.append(limit)
    with connect() as conn:
        return conn.execute(q.format(tour=tour_clause), params).fetchall()


def get_player(name: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM players WHERE name=?", (name,)).fetchone()


def get_meta(key: str) -> Optional[str]:
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(key: str, value: Any) -> None:
    with connect() as conn:
        _set_meta(conn, key, str(value))


def player_record(name: str) -> Dict[str, int]:
    """Bilan victoires / défaites du joueur sur l'archive des matchs."""
    with connect() as conn:
        wins = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE winner=?", (name,)).fetchone()[0]
        losses = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE loser=?", (name,)).fetchone()[0]
    return {"wins": int(wins), "losses": int(losses)}


def player_recent_matches(name: str, limit: int = 10) -> List[sqlite3.Row]:
    """Derniers matchs du joueur (gagnés ou perdus), les plus récents d'abord.

    Tri sur REPLACE(date,'-','') et pas sur date brut : la colonne mélange
    "20220103" (Sackmann) et "2022-01-17" (tennis-data.co.uk), et en tri
    lexicographique le tiret passe AVANT les chiffres — toutes les dates avec
    tirets sortiraient avant les dates compactes, quelle que soit l'année.
    """
    with connect() as conn:
        return conn.execute(
            "SELECT date,tour,winner,loser FROM matches "
            "WHERE winner=? OR loser=? "
            "ORDER BY REPLACE(date,'-','') DESC, id DESC LIMIT ?",
            (name, name, limit),
        ).fetchall()


def all_matches_chrono() -> List[sqlite3.Row]:
    """Tous les matchs par ordre chronologique avec surface (pour l'ELO).

    Voir player_recent_matches : REPLACE(date,'-','') obligatoire, sinon les
    13% de lignes tennis-data (avec tirets) sortent AVANT tout Sackmann et le
    replay chronologique (donc l'ELO) est corrompu.
    """
    with connect() as conn:
        return conn.execute(
            "SELECT winner, loser, surface, margin FROM matches "
            "ORDER BY REPLACE(date,'-','') ASC, id ASC").fetchall()


def head_to_head(name1: str, name2: str) -> List[sqlite3.Row]:
    """Confrontations directes entre deux joueurs, les plus récentes d'abord.
    Voir player_recent_matches pour la normalisation de date."""
    with connect() as conn:
        return conn.execute(
            "SELECT date,tour,winner,loser FROM matches "
            "WHERE (winner=? AND loser=?) OR (winner=? AND loser=?) "
            "ORDER BY REPLACE(date,'-','') DESC, id DESC",
            (name1, name2, name2, name1),
        ).fetchall()


def player_recent_match_count(name: str, cutoff_compact: str) -> int:
    """Nombre de matchs joués par `name` depuis `cutoff_compact` (format
    YYYYMMDD, sans tirets). matches.date mélange deux formats selon la
    source d'ingestion ("20220103" Sackmann vs "2022-01-17" tennis-data.co.uk
    — confirmé 87%/13% sur les 91946 lignes réelles) : REPLACE(date,'-','')
    normalise les deux avant comparaison, sinon un tri/filtre lexicographique
    naïf serait faux pour la majorité des lignes.
    """
    with connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM matches WHERE (winner=? OR loser=?) "
            "AND REPLACE(date,'-','') >= ?",
            (name, name, cutoff_compact),
        ).fetchone()[0]


def player_clutch_stats(name: str, limit: int) -> Dict[str, float]:
    """Agrégats "clutch" sur les `limit` derniers matchs de `name` ayant des
    stats de break points (lignes Sackmann ; les lignes tennis-data restent
    NULL et sont ignorées). Voir player_recent_matches pour la normalisation
    de date.

    Renvoie des SOMMES brutes (les taux se calculent chez l'appelant) :
      bp_saved / bp_faced : BP défendues au service par `name`
      bp_converted / bp_chances : BP converties au retour par `name`
        (= les BP que son adversaire a concédées moins celles qu'il a sauvées)
      tb_won / tb_played : tie-breaks gagnés / disputés
      n_matches : matchs avec stats BP dans la fenêtre
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT winner, w_bp_saved, w_bp_faced, l_bp_saved, l_bp_faced, "
            "w_tb_won, l_tb_won FROM matches "
            "WHERE (winner=? OR loser=?) AND w_bp_faced IS NOT NULL "
            "ORDER BY REPLACE(date,'-','') DESC, id DESC LIMIT ?",
            (name, name, limit),
        ).fetchall()
    out = {"bp_saved": 0.0, "bp_faced": 0.0, "bp_converted": 0.0,
           "bp_chances": 0.0, "tb_won": 0.0, "tb_played": 0.0,
           "n_matches": float(len(rows))}
    for r in rows:
        if r["winner"] == name:
            own_s, own_f = r["w_bp_saved"], r["w_bp_faced"]
            opp_s, opp_f = r["l_bp_saved"], r["l_bp_faced"]
            own_tb, opp_tb = r["w_tb_won"], r["l_tb_won"]
        else:
            own_s, own_f = r["l_bp_saved"], r["l_bp_faced"]
            opp_s, opp_f = r["w_bp_saved"], r["w_bp_faced"]
            own_tb, opp_tb = r["l_tb_won"], r["w_tb_won"]
        out["bp_saved"] += own_s or 0.0
        out["bp_faced"] += own_f or 0.0
        # BP converties par `name` = BP que l'adversaire n'a pas sauvées.
        out["bp_converted"] += (opp_f or 0.0) - (opp_s or 0.0)
        out["bp_chances"] += opp_f or 0.0
        out["tb_won"] += own_tb or 0
        out["tb_played"] += (own_tb or 0) + (opp_tb or 0)
    return out


def matches_for_backtest() -> List[Dict[str, Any]]:
    """Tous les matchs archivés, ordre chronologique STRICT (date normalisée),
    reconstruits au format attendu par bot.backtest.run / learner._train_one
    (l'inverse exact de archive_matches). Permet un backtest 100% hors-ligne
    sur l'archive plutôt qu'un re-téléchargement réseau des CSV.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, date, tour, winner, loser, w_serve, w_return1, w_return2, "
            "l_serve, l_return1, l_return2, surface, margin FROM matches "
            "ORDER BY REPLACE(date,'-','') ASC, id ASC"
        ).fetchall()
    return [
        {
            "id": r["id"], "date": r["date"], "tour": r["tour"],
            "winner_name": r["winner"], "loser_name": r["loser"],
            "winner": {"serve": r["w_serve"] or 0.5, "return1": r["w_return1"] or 0.5,
                       "return2": r["w_return2"] or 0.5},
            "loser": {"serve": r["l_serve"] or 0.5, "return1": r["l_return1"] or 0.5,
                      "return2": r["l_return2"] or 0.5},
            "surface": r["surface"] or "", "margin": r["margin"],
        }
        for r in rows
    ]


def historical_odds_index() -> Dict[tuple, Dict[str, Any]]:
    """Index (date_compacte, winner, loser) -> cotes marché historiques
    (tennis-data.co.uk). Clé de date normalisée SANS tirets pour joindre avec
    matches.date quel que soit son format d'origine."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT REPLACE(date,'-','') AS d, winner, loser, "
            "psw, psl, avgw, avgl FROM historical_odds"
        ).fetchall()
    return {
        (r["d"], r["winner"], r["loser"]): {
            "psw": r["psw"], "psl": r["psl"], "avgw": r["avgw"], "avgl": r["avgl"],
        }
        for r in rows
    }


def player_last_match_date(name: str) -> Optional[str]:
    """Date du dernier match connu de `name`, au format compact YYYYMMDD.

    Voir player_recent_matches pour la normalisation REPLACE(date,'-','')
    (deux formats de date coexistent en base selon la source d'ingestion).
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT REPLACE(date,'-','') AS d FROM matches "
            "WHERE winner=? OR loser=? "
            "ORDER BY REPLACE(date,'-','') DESC, id DESC LIMIT 1",
            (name, name),
        ).fetchone()
        return row["d"] if row else None


def player_recent_opponents(name: str, limit: int) -> List[sqlite3.Row]:
    """Les `limit` derniers matchs de `name` (winner, loser), plus récents
    d'abord. Voir player_recent_match_count pour la normalisation de date."""
    with connect() as conn:
        return conn.execute(
            "SELECT winner, loser FROM matches WHERE (winner=? OR loser=?) "
            "ORDER BY REPLACE(date,'-','') DESC LIMIT ?",
            (name, name, limit),
        ).fetchall()


def counts() -> Dict[str, int]:
    with connect() as conn:
        return {
            "players": conn.execute("SELECT COUNT(*) FROM players").fetchone()[0],
            "matches": conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0],
            "predictions": conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0],
            "backtests": conn.execute("SELECT COUNT(*) FROM backtests").fetchone()[0],
            "settled": conn.execute("SELECT COUNT(*) FROM settled_matches").fetchone()[0],
        }


# --- Settlement (résultats finaux) -----------------------------------------
def settled_exists(event_key: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM settled_matches WHERE event_key=?", (event_key,)).fetchone()
    return row is not None


def insert_settled(row: Dict[str, Any]) -> bool:
    """Insère un match réglé (ignore si event_key déjà présent). True si ajouté."""
    import datetime as _dt
    # Guard: ne pas enregistrer de matchs ATP/WTA croisés (ELO non comparables)
    p1, p2 = str(row.get("player1") or ""), str(row.get("player2") or "")
    with connect() as _c:
        _r1 = _c.execute("SELECT tour FROM players WHERE name=?", (p1,)).fetchone()
        _r2 = _c.execute("SELECT tour FROM players WHERE name=?", (p2,)).fetchone()
    _t1 = (_r1[0] if _r1 else "") or ""
    _t2 = (_r2[0] if _r2 else "") or ""
    if _t1 and _t2 and {_t1, _t2} == {"atp", "wta"}:
        return False
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO settled_matches "
            "(event_key,date,tour,tournament,player1,player2,winner,final_score,"
            " sets,pred_favorite,pred_prob1,correct,settled_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(row.get("event_key") or ""), str(row.get("date") or ""),
                str(row.get("tour") or ""), str(row.get("tournament") or ""),
                str(row.get("player1") or ""), str(row.get("player2") or ""),
                str(row.get("winner") or ""), str(row.get("final_score") or ""),
                json.dumps(row.get("sets", [])),
                row.get("pred_favorite"), row.get("pred_prob1"),
                row.get("correct"),
                _dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return cur.rowcount > 0


def count_settled() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM settled_matches").fetchone()[0]


def list_settled(limit: int = 5000) -> List[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM settled_matches ORDER BY date DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def list_settled_by_date(date_prefix: str, limit: int = 100) -> List[sqlite3.Row]:
    """Matchs réglés pour une date donnée (préfixe YYYY-MM-DD)."""
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM settled_matches WHERE date LIKE ? ORDER BY date ASC LIMIT ?",
            (f"{date_prefix}%", limit),
        ).fetchall()


def settled_available_dates(limit: int = 90) -> List[str]:
    """Dates distinctes avec au moins un match réglé (pour le calendrier)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT substr(date,1,10) as d FROM settled_matches "
            "WHERE d != '' ORDER BY d DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [r[0] for r in rows if r[0]]


def settled_chrono() -> List[sqlite3.Row]:
    """Matchs réglés par ordre chronologique (pour rejouer l'ELO)."""
    with connect() as conn:
        return conn.execute(
            "SELECT player1, player2, winner, tournament, date FROM settled_matches "
            "ORDER BY date ASC, id ASC").fetchall()


def save_calibration(metrics: Dict[str, Any]) -> int:
    import datetime as _dt
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO calibration_history "
            "(ts,n,accuracy,roi,brier,atp_acc,wta_acc,fav_acc,dog_acc,notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                _dt.datetime.now().isoformat(timespec="seconds"),
                metrics.get("n", 0), metrics.get("accuracy"), metrics.get("roi"),
                metrics.get("brier"), metrics.get("atp_acc"), metrics.get("wta_acc"),
                metrics.get("fav_acc"), metrics.get("dog_acc"), metrics.get("notes", ""),
            ),
        )
        return int(cur.lastrowid or 0)


def list_calibration(limit: int = 20) -> List[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM calibration_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


# --- Journal des cotes (pour le ROI) ---------------------------------------
def log_bet(date: str, p1: str, p2: str, favorite: str, fav_odds: float) -> None:
    """Capture la cote du favori du modèle pour une paire (pour calculer le ROI)."""
    import datetime as _dt
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO bet_log "
            "(date,player1,player2,favorite,fav_odds,ts) VALUES (?,?,?,?,?,?)",
            (date, p1, p2, favorite, fav_odds,
             _dt.datetime.now().isoformat(timespec="seconds")),
        )


def insert_bet(row: Dict[str, Any]) -> None:
    """Alias dict-based insert for test compatibility."""
    import datetime as _dt
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO bet_log "
            "(date,player1,player2,favorite,fav_odds,ts) VALUES (?,?,?,?,?,?)",
            (
                str(row.get("date") or _dt.date.today().isoformat()),
                str(row.get("player1") or ""), str(row.get("player2") or ""),
                str(row.get("favorite") or ""), row.get("fav_odds"),
                _dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )


def list_bets() -> List[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT date,player1,player2,favorite,fav_odds FROM bet_log").fetchall()


# --- Paper-trading des picks blendés (stratégie value) ----------------------
def log_value_pick(date: str, p1: str, p2: str, side: str,
                   odds: float, ev: float,
                   league: str = "", surface: str = "", kelly_u: float = 0.0) -> None:
    """Capture un value pick (EV blendée > 0) pour mesurer son ROI au settlement."""
    if odds <= 0 or odds > 5.0 or ev < 8.0:  # filtre de sécurité côté DB
        return
    import datetime as _dt
    with connect() as conn:
        conn.execute(
            "INSERT INTO value_picks "
            "(date,player1,player2,side,odds,ev,ts,league,surface,kelly_u) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(player1,player2) DO UPDATE SET "
            "date=excluded.date, side=excluded.side, odds=excluded.odds, "
            "ev=excluded.ev, ts=excluded.ts, league=excluded.league, "
            "surface=excluded.surface, kelly_u=excluded.kelly_u "
            "WHERE result IS NULL",  # ne jamais écraser un pick déjà réglé
            (date, p1, p2, side, odds, ev,
             _dt.datetime.now().isoformat(timespec="seconds"),
             league or "", surface or "", kelly_u or 0.0),
        )


def list_value_picks() -> List[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT date,player1,player2,side,odds,ev FROM value_picks").fetchall()


def list_value_picks_open() -> List[sqlite3.Row]:
    """Picks ouverts (result IS NULL)."""
    with connect() as conn:
        return conn.execute(
            "SELECT rowid,date,player1,player2,side,odds,ev FROM value_picks "
            "WHERE result IS NULL ORDER BY date DESC"
        ).fetchall()


def get_settled_by_players(p1: str, p2: str) -> Optional[sqlite3.Row]:
    """Cherche un settled_match pour cette paire (dans les 2 sens)."""
    p1_vars = _name_variants(p1)
    p2_vars = _name_variants(p2)
    with connect() as conn:
        for a in p1_vars:
            for b in p2_vars:
                row = conn.execute(
                    "SELECT player1, player2, winner FROM settled_matches "
                    "WHERE (player1=? AND player2=?) OR (player1=? AND player2=?) "
                    "ORDER BY date DESC LIMIT 1",
                    (a, b, b, a),
                ).fetchone()
                if row:
                    return row
    return None


def _name_variants(name: str) -> List[str]:
    """Génère les variantes d'un nom : 'Last, First' ↔ 'First Last'."""
    variants = [name]
    if ", " in name:
        parts = name.split(", ", 1)
        variants.append(f"{parts[1]} {parts[0]}")  # "Munar, Jaume" → "Jaume Munar"
    elif " " in name:
        parts = name.rsplit(" ", 1)
        variants.append(f"{parts[1]}, {parts[0]}")  # "Jaume Munar" → "Munar, Jaume"
    return list(dict.fromkeys(variants))  # dédoublonne en gardant l'ordre


def settle_value_pick(p1: str, p2: str, winner: str) -> bool:
    """Marque un value pick comme réglé (résultat connu). Retourne True si trouvé.

    Stratégie (du plus précis au plus souple) :
    1. Paire exacte + variantes Last,First ↔ First Last
    2. Joueur parié (side) seul — adversaire peut différer
    3. Fuzzy match SequenceMatcher > 0.85

    Si winner est None/vide (retraite, walkover), void le pick sans pnl.
    """
    if not winner:
        # Retraite ou abandon → void sans impacter le P&L
        p1_vars = _name_variants(p1)
        p2_vars = _name_variants(p2)
        with connect() as _c:
            for a in p1_vars:
                for b in p2_vars:
                    row = _c.execute(
                        "SELECT rowid FROM value_picks "
                        "WHERE result IS NULL AND ((player1=? AND player2=?) OR (player1=? AND player2=?))",
                        (a, b, b, a),
                    ).fetchone()
                    if row:
                        _c.execute(
                            "UPDATE value_picks SET result=-1, pnl=0, winner=NULL WHERE rowid=?",
                            (row["rowid"],)
                        )
                        return True
        return False

    p1_vars = _name_variants(p1)
    p2_vars = _name_variants(p2)
    w_vars = _name_variants(winner)

    with connect() as _c:
        # 1. Paire exacte (toutes combinaisons de variantes)
        for a in p1_vars:
            for b in p2_vars:
                row = _c.execute(
                    "SELECT rowid, side, odds FROM value_picks "
                    "WHERE result IS NULL AND ((player1=? AND player2=?) OR (player1=? AND player2=?))",
                    (a, b, b, a),
                ).fetchone()
                if row:
                    side, odds = row["side"], row["odds"]
                    won = int(side in w_vars)
                    pnl = round((odds - 1.0) if won else -1.0, 4)
                    _c.execute(
                        "UPDATE value_picks SET result=?, pnl=?, winner=? WHERE rowid=?",
                        (won, pnl, winner, row["rowid"]),
                    )
                    return True

        # 2. Matching par joueur parié uniquement
        for raw_player in (p1, p2):
            for pick_player in _name_variants(raw_player):
                rows = _c.execute(
                    "SELECT rowid, side, odds FROM value_picks "
                    "WHERE result IS NULL AND (player1=? OR player2=?) AND side=?",
                    (pick_player, pick_player, pick_player),
                ).fetchall()
                if rows:
                    for row in rows:
                        side, odds = row["side"], row["odds"]
                        won = int(side in w_vars)
                        pnl = round((odds - 1.0) if won else -1.0, 4)
                        _c.execute(
                            "UPDATE value_picks SET result=?, pnl=?, winner=? WHERE rowid=?",
                            (won, pnl, winner, row["rowid"]),
                        )
                    return True

        # 3. Fuzzy match — SequenceMatcher (ratio > 0.85) pour les erreurs d'orthographe
        open_picks = _c.execute(
            "SELECT rowid, player1, player2, side, odds FROM value_picks WHERE result IS NULL"
        ).fetchall()
        p1_n = p1.lower(); p2_n = p2.lower()
        for row in open_picks:
            rp1 = row["player1"].lower(); rp2 = row["player2"].lower()
            sim_a = max(difflib.SequenceMatcher(None, p1_n, rp1).ratio(),
                        difflib.SequenceMatcher(None, p2_n, rp1).ratio())
            sim_b = max(difflib.SequenceMatcher(None, p1_n, rp2).ratio(),
                        difflib.SequenceMatcher(None, p2_n, rp2).ratio())
            if sim_a > 0.85 and sim_b > 0.85:
                side_lower = row["side"].lower()
                winner_lower = winner.lower()
                won = int(difflib.SequenceMatcher(None, side_lower, winner_lower).ratio() > 0.80)
                pnl = round((row["odds"] - 1.0) if won else -1.0, 4)
                _c.execute(
                    "UPDATE value_picks SET result=?, pnl=?, winner=? WHERE rowid=?",
                    (won, pnl, winner, row["rowid"]),
                )
                log(f"settle_value_pick: fuzzy match '{p1}' vs '{p2}' → '{row['player1']}' vs '{row['player2']}'")
                return True
    return False


def list_value_history(limit: int = 50) -> List[sqlite3.Row]:
    """Value picks réglés, du plus récent au plus ancien."""
    with connect() as conn:
        return conn.execute(
            "SELECT date,player1,player2,side,odds,ev,result,pnl,winner,league,surface,kelly_u "
            "FROM value_picks WHERE result IS NOT NULL "
            "ORDER BY date DESC, ts DESC LIMIT ?",
            (limit,),
        ).fetchall()


def value_picks_stats() -> dict:
    """ROI et taux de réussite des value picks réglés (stratégie courante: EV≥8%, cotes≤5)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT result, pnl FROM value_picks WHERE result IN (0,1) AND odds <= 5.0 AND ev >= 8.0"
        ).fetchall()
    if not rows:
        return {"n": 0, "wins": 0, "win_rate": None, "roi": None}
    wins = sum(1 for r in rows if r["result"] == 1)
    total_pnl = sum(r["pnl"] for r in rows if r["pnl"] is not None)
    n = len(rows)
    return {
        "n": n,
        "wins": wins,
        "win_rate": round(wins / n, 3) if n else None,
        "roi": round(total_pnl / n, 4) if n else None,
    }


# --- CLV : closing line value (preuve d'edge) ------------------------------
def log_clv_pick(event_key: str, date: str, p1: str, p2: str, side: str,
                 pick_odds: float, pick_prob: float, confidence: float,
                 honeypot: Optional[Dict[str, Any]] = None) -> None:
    """Sème un pick dans le journal CLV (closing_odds rempli plus tard).

    INSERT OR IGNORE : on garde la PREMIÈRE cote vue (la décision d'entrée),
    on ne l'écrase pas si le pick réapparaît avec une cote qui a bougé.
    `honeypot` : signal weather_profile.analyze() au moment du pick (fige la
    condition constatée ce jour-là — ne pas le recalculer après coup, l'état
    des profils joueurs change avec le temps).
    """
    import datetime as _dt
    hp = honeypot or {}
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO clv_log "
            "(event_key,date,player1,player2,pick_side,pick_odds,pick_prob,"
            " confidence,pick_ts,honeypot_flag,honeypot_beneficiary,"
            " honeypot_player,honeypot_edge_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_key, date, p1, p2, side, pick_odds, pick_prob, confidence,
             _dt.datetime.now().isoformat(timespec="seconds"),
             1 if hp.get("flag") else 0, hp.get("beneficiary"),
             hp.get("player"), hp.get("edge_pct")),
        )


def list_clv_open() -> List[sqlite3.Row]:
    """Picks sans closing line encore captée (à snapshotter avant le match)."""
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM clv_log WHERE closing_odds IS NULL").fetchall()


def update_clv_closing(event_key: str, closing_odds: float, src: str) -> None:
    """Rafraîchit la closing line tant que le match n'est pas réglé.

    On écrase à chaque quote pré-match : le DERNIER quote vu avant le coup
    d'envoi est, par construction (upcoming_only), la closing line.
    """
    import datetime as _dt
    with connect() as conn:
        row = conn.execute(
            "SELECT pick_odds FROM clv_log WHERE event_key=? AND result IS NULL",
            (event_key,)).fetchone()
        if not row or not row["pick_odds"] or closing_odds <= 1.0:
            return
        pick_odds = float(row["pick_odds"])
        # Rejeter le drift intraday / post-match (ratio >2.5x = marché pendant/après match)
        if closing_odds / pick_odds > 2.5 or pick_odds / closing_odds > 2.5:
            return
        clv_pct = round((pick_odds / closing_odds - 1.0) * 100, 2)
        beat = 1 if pick_odds > closing_odds else 0
        conn.execute(
            "UPDATE clv_log SET closing_odds=?, closing_src=?, closing_ts=?, "
            "clv_pct=?, beat_closing=? WHERE event_key=?",
            (closing_odds, src,
             _dt.datetime.now().isoformat(timespec="seconds"),
             clv_pct, beat, event_key),
        )


def list_clv_unsettled() -> List[sqlite3.Row]:
    """Picks dont le résultat n'est pas encore enregistré (pour le settlement)."""
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM clv_log WHERE result IS NULL").fetchall()


def update_clv_result(event_key: str, result: int, pnl_flat: float,
                      pnl_kelly: float) -> None:
    import datetime as _dt
    with connect() as conn:
        conn.execute(
            "UPDATE clv_log SET result=?, pnl_flat=?, pnl_kelly=?, settled_ts=? "
            "WHERE event_key=?",
            (result, pnl_flat, pnl_kelly,
             _dt.datetime.now().isoformat(timespec="seconds"), event_key),
        )


def list_clv(limit: int = 100000, since: str = "") -> List[sqlite3.Row]:
    with connect() as conn:
        if since:
            return conn.execute(
                "SELECT * FROM clv_log WHERE pick_ts >= ? ORDER BY date DESC, pick_ts DESC LIMIT ?",
                (since, limit)).fetchall()
        return conn.execute(
            "SELECT * FROM clv_log ORDER BY date DESC, pick_ts DESC LIMIT ?",
            (limit,)).fetchall()


# --- Market snapshots (mouvement de ligne / sharp money) --------------------
def record_market_snapshot(event_key: str, p1: str, p2: str,
                           odds_home: float, odds_away: float,
                           hours_ahead: Optional[float] = None) -> None:
    """Capture une cote datée pour reconstruire le mouvement de ligne d'un match.

    Pas de dédup : le scanner n'appelle ceci que quand il refetch réellement
    les cotes (déjà throttlé ~10min/match par _value_scanner_loop), donc la
    fréquence des lignes reflète directement la fréquence de refresh voulue.
    """
    import datetime as _dt
    with connect() as conn:
        conn.execute(
            "INSERT INTO market_snapshots "
            "(event_key,ts,player1,player2,odds_home,odds_away,hours_ahead) "
            "VALUES (?,?,?,?,?,?,?)",
            (event_key, _dt.datetime.now().isoformat(timespec="seconds"),
             p1, p2, odds_home, odds_away, hours_ahead),
        )


# --- Notifications push (device tokens FCM) ---------------------------------
def register_device_token(token: str, platform: str = "android") -> None:
    """Enregistre/rafraîchit un token FCM (INSERT OR REPLACE = idempotent)."""
    import datetime as _dt
    now = _dt.datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute(
            "INSERT INTO device_tokens (token,platform,registered_ts,last_seen_ts) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT(token) DO UPDATE SET last_seen_ts=excluded.last_seen_ts",
            (token, platform, now, now),
        )


def list_device_tokens() -> List[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT token, platform FROM device_tokens").fetchall()


def delete_device_token(token: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM device_tokens WHERE token=?", (token,))


# --- Joueurs suivis (signal explicite de personnalisation) -------------------
def follow_player(name: str) -> None:
    """Suit un joueur (INSERT OR IGNORE = idempotent, ne rafraîchit pas la date)."""
    import datetime as _dt
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO followed_players (name, followed_ts) VALUES (?,?)",
            (name, _dt.datetime.now().isoformat(timespec="seconds")),
        )


def unfollow_player(name: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM followed_players WHERE name=?", (name,))


def list_followed_players() -> List[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT name FROM followed_players ORDER BY followed_ts DESC"
        ).fetchall()
    return [r["name"] for r in rows]


def is_player_followed(name: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM followed_players WHERE name=?", (name,)).fetchone()
    return row is not None


def line_movement(event_key: str) -> Optional[Dict[str, Any]]:
    """Mouvement de ligne (ouverture -> dernière cote captée) pour un match.

    Renvoie None si < 2 snapshots (pas encore de mouvement mesurable).
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT ts,odds_home,odds_away,hours_ahead FROM market_snapshots "
            "WHERE event_key=? ORDER BY ts ASC", (event_key,)).fetchall()
    if len(rows) < 2:
        return None
    opening, closing = rows[0], rows[-1]

    def _pct(a: float, b: float) -> float:
        return round((b - a) / a * 100, 2) if a else 0.0

    return {
        "event_key": event_key,
        "n_snapshots": len(rows),
        "opening_ts": opening["ts"], "closing_ts": closing["ts"],
        "opening_odds_home": opening["odds_home"], "closing_odds_home": closing["odds_home"],
        "opening_odds_away": opening["odds_away"], "closing_odds_away": closing["odds_away"],
        "move_home_pct": _pct(opening["odds_home"], closing["odds_home"]),
        "move_away_pct": _pct(opening["odds_away"], closing["odds_away"]),
    }


def record_live_prob(event_key: str, prob1: float, sets_home: int, sets_away: int,
                     minute: int = 0) -> None:
    """Capture un point de la proba in-play pour reconstruire son évolution.

    Pas de dédup : appelé à chaque cycle /api/live où ce match est vu, la
    fréquence des points reflète directement la fréquence de refresh de l'app.
    """
    import datetime as _dt
    with connect() as conn:
        conn.execute(
            "INSERT INTO live_prob_snapshots (event_key,ts,prob1,sets_home,sets_away,minute) "
            "VALUES (?,?,?,?,?,?)",
            (event_key, _dt.datetime.now().isoformat(timespec="seconds"),
             prob1, sets_home, sets_away, minute),
        )


def live_prob_history(event_key: str, limit: int = 50) -> List[sqlite3.Row]:
    """Points récents de la proba in-play pour un match, ordre chronologique."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT ts,prob1,sets_home,sets_away,minute FROM live_prob_snapshots "
            "WHERE event_key=? ORDER BY ts DESC LIMIT ?", (event_key, limit)).fetchall()
    return list(reversed(rows))


# --- Historique des prédictions --------------------------------------------
def log_prediction(p1: str, p2: str, prob1: float, favorite: Optional[str],
                   source: str = "cli") -> None:
    import datetime as _dt

    with connect() as conn:
        conn.execute(
            "INSERT INTO predictions(ts,player1,player2,prob1,favorite,source) "
            "VALUES (?,?,?,?,?,?)",
            (_dt.datetime.now().isoformat(timespec="seconds"), p1, p2,
             round(prob1, 4), favorite, source),
        )


# --- Archive backtest ------------------------------------------------------
def save_backtest(report: Dict[str, Any]) -> int:
    import datetime as _dt

    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO backtests"
            "(ts,span,tours,n_train,n_test,accuracy,logloss,brier,baseline,"
            " accuracy_elo,logloss_elo,brier_elo,notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                _dt.datetime.now().isoformat(timespec="seconds"),
                report.get("span"), report.get("tours"),
                report.get("n_train"), report.get("n_test"),
                report.get("accuracy"), report.get("logloss"),
                report.get("brier"), report.get("baseline"),
                report.get("accuracy_elo"), report.get("logloss_elo"),
                report.get("brier_elo"),
                report.get("notes", ""),
            ),
        )
        return cur.lastrowid


def list_backtests(limit: int = 10) -> List[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM backtests ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


# --- Inplay picks (tracking + ROI) -----------------------------------------
def log_inplay_pick(player1: str, player2: str, league: str,
                    market_type: str, market_label: str, pick: str,
                    odds: Optional[float], prob: float, stake: float = 1.0,
                    odds_home: Optional[float] = None, odds_away: Optional[float] = None,
                    odds_book: Optional[str] = None, score: Optional[str] = None,
                    minute: Optional[int] = None, event_id: Optional[str] = None,
                    sets_home: Optional[int] = None, sets_away: Optional[int] = None) -> int:
    with connect() as conn:
        # Déduplique par event_id (priorité) ou par paire joueurs si pas d'event_id
        if event_id:
            existing = conn.execute(
                "SELECT id FROM inplay_picks WHERE event_id=? AND pick=? AND result IS NULL",
                (event_id, pick),
            ).fetchone()
        else:
            import datetime as _dt
            dedup_window = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=24)).isoformat()
            existing = conn.execute(
                """SELECT id FROM inplay_picks
                   WHERE player1=? AND player2=? AND pick=? AND result IS NULL
                   AND ts > ?""",
                (player1, player2, pick, dedup_window),
            ).fetchone()
        if existing:
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO inplay_picks"
            "(event_id,player1,player2,league,market_type,market_label,pick,"
            " odds,odds_home,odds_away,odds_book,prob,score,sets_home,sets_away,minute,stake)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, player1, player2, league, market_type, market_label, pick,
             odds, odds_home, odds_away, odds_book,
             round(prob, 2), score, sets_home, sets_away, minute, round(stake, 2)),
        )
        return cur.lastrowid


def settle_inplay_pick(pick_id: int, result: str, stake: Optional[float] = None) -> bool:
    """result: 'W', 'L', or 'V' (void/annulé). Recalcule pnl automatiquement."""
    with connect() as conn:
        row = conn.execute(
            "SELECT odds, stake FROM inplay_picks WHERE id=?", (pick_id,)
        ).fetchone()
        if not row:
            return False
        odds_val, stake_val = row
        if stake is not None:
            stake_val = stake
        stake_val = stake_val or 1.0
        if result == "W":
            pnl = round((odds_val - 1) * stake_val, 2) if odds_val else None
        elif result == "L":
            pnl = round(-stake_val, 2)
        else:
            pnl = 0.0  # V = void
        conn.execute(
            "UPDATE inplay_picks SET result=?, pnl=?, stake=? WHERE id=?",
            (result, pnl, stake_val, pick_id),
        )
        return True


def list_inplay_picks(limit: int = 50) -> List[sqlite3.Row]:
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM inplay_picks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def list_inplay_picks_pending() -> List[sqlite3.Row]:
    """Retourne uniquement les picks en attente de règlement."""
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM inplay_picks WHERE result IS NULL"
        ).fetchall()


def _norm_player(name: str) -> str:
    """Normalise un nom joueur : 'Djokovic, Novak' → 'novak djokovic' (lowercase, no comma)."""
    name = (name or "").strip()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        name = f"{parts[1]} {parts[0]}"
    return name.lower()


def _players_match(a: str, b: str) -> bool:
    """True si deux noms de joueurs désignent probablement la même personne."""
    na, nb = _norm_player(a), _norm_player(b)
    if na == nb:
        return True
    # Correspondance partielle : tous les tokens de l'un dans l'autre
    ta = set(na.split())
    tb = set(nb.split())
    return len(ta & tb) >= max(1, min(len(ta), len(tb)) - 1)


def _find_in_settled(p1: str, p2: str) -> Optional[Any]:
    """Cherche un résultat dans settled_matches avec noms normalisés."""
    np1, np2 = _norm_player(p1), _norm_player(p2)
    with connect() as conn:
        # Essai exact d'abord
        sm = conn.execute(
            """SELECT winner, final_score, sets FROM settled_matches
               WHERE (player1=? AND player2=?) OR (player1=? AND player2=?)
               ORDER BY settled_ts DESC LIMIT 1""",
            (p1, p2, p2, p1),
        ).fetchone()
        if sm:
            return sm
        # Fallback : cherche par LIKE sur le nom normalisé (gère Last,First)
        tokens_p1 = np1.split()
        tokens_p2 = np2.split()
        if not tokens_p1 or not tokens_p2:
            return None
        like_p1 = f"%{tokens_p1[-1]}%"  # nom de famille
        like_p2 = f"%{tokens_p2[-1]}%"
        candidates = conn.execute(
            """SELECT winner, final_score, sets, player1, player2
               FROM settled_matches
               WHERE (player1 LIKE ? AND player2 LIKE ?)
                  OR (player1 LIKE ? AND player2 LIKE ?)
               ORDER BY settled_ts DESC LIMIT 5""",
            (like_p1, like_p2, like_p2, like_p1),
        ).fetchall()
        for c in candidates:
            cp1, cp2 = _norm_player(c["player1"]), _norm_player(c["player2"])
            if (_players_match(np1, cp1) and _players_match(np2, cp2)) or \
               (_players_match(np1, cp2) and _players_match(np2, cp1)):
                return c
    return None


def auto_settle_picks(live_event_ids: set) -> List[Dict]:
    """Règle automatiquement les picks dont le match est terminé.

    Stratégie :
    1. Picks avec event_id → skip si encore en live
    2. Picks sans event_id ou vieux (>2h) → cherche dans settled_matches
    3. Résolution nom flexible (Last,First ↔ First Last, tokens partiels)
    4. P&L correct : None si cote inconnue (gagnant sans cote)
    """
    import datetime as _dt
    settled_out = []
    cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=2)).isoformat()
    stale_cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=48)).isoformat()

    # Void picks vieux de >48h sans résultat (match terminé depuis longtemps)
    with connect() as conn:
        voided = conn.execute(
            "UPDATE inplay_picks SET result='V', pnl=0 WHERE result IS NULL AND ts < ?",
            (stale_cutoff,)
        ).rowcount
        if voided:
            log(f"auto_settle: {voided} picks >48h sans résultat → V", "INFO")

    with connect() as conn:
        # Tous les picks en attente — avec ET sans event_id
        pending = conn.execute(
            "SELECT * FROM inplay_picks WHERE result IS NULL"
        ).fetchall()
        pending = list(pending)

    for row in pending:
        eid = str(row["event_id"] or "")

        # Skip si le match est encore en live (seulement si event_id connu)
        if eid and eid in live_event_ids:
            continue

        # Skip picks récents sans event_id (attendre >2h pour tenter le settle)
        if not eid and (row["ts"] or "") > cutoff:
            continue

        p1 = row["player1"] or ""
        p2 = row["player2"] or ""
        sm = _find_in_settled(p1, p2)

        if sm is None:
            result = _infer_from_snapshot(row["market_type"], row["pick"], row)
            if result is None:
                continue
        else:
            result = _infer_from_settled(row["market_type"], row["pick"], row, sm)
            if result is None:
                continue

        # Dériver la cote du pick si odds est None mais odds_home/odds_away connus
        odds_val = row["odds"]
        if not odds_val:
            pick_norm = _norm_player(row["pick"] or "")
            p1_norm = _norm_player(p1)
            if _players_match(pick_norm, p1_norm) and row["odds_home"]:
                odds_val = row["odds_home"]
            elif row["odds_away"]:
                odds_val = row["odds_away"]
        stake_val = row["stake"] or 1.0
        if result == "W":
            pnl = round((odds_val - 1) * stake_val, 2) if odds_val else None
        elif result == "L":
            pnl = round(-stake_val, 2)
        else:
            pnl = 0.0

        with connect() as conn:
            conn.execute(
                "UPDATE inplay_picks SET result=?, pnl=?, auto_settled=1 WHERE id=?",
                (result, pnl, row["id"]),
            )
        settled_out.append({"id": row["id"], "pick": row["pick"],
                            "result": result, "pnl": pnl})

    return settled_out


def _infer_from_settled(market_type: str, pick: str, row: Any, sm: Any) -> Optional[str]:
    """Déduit W/L depuis le résultat réel dans settled_matches."""
    import json as _json
    winner = sm["winner"] or ""
    final_score = sm["final_score"] or ""  # ex: "2 - 0" ou "6-3, 7-5"
    p1 = (row["player1"] or "").strip()
    p2 = (row["player2"] or "").strip()

    if market_type in ("set_winner", "next_set", "match_winner", None, ""):
        # Comparaison normalisée : pick → gagnant
        if _players_match(pick, winner):
            return "W"
        # Vérifie que le pick est bien l'un des deux joueurs (pas de garbage)
        if not (_players_match(pick, p1) or _players_match(pick, p2)):
            return None  # pick ne correspond à aucun joueur → données corrompues
        return "L"

    if market_type in ("total_games", "total_points"):
        # Compter les jeux du score final
        try:
            threshold = float(pick.split()[-1])
            is_over = pick.upper().startswith("OVER")
        except Exception:
            return None
        # final_score peut être "2 - 0" (sets) ou "6-3, 7-5, 6-4" (jeux)
        total = 0
        for part in final_score.replace(" ", "").split(","):
            if "-" in part:
                try:
                    h, a = [int(x) for x in part.split("-")]
                    if h <= 7 and a <= 7:  # filtre sets vs jeux
                        total += h + a
                except Exception:
                    pass
        if total == 0:
            # Fallback : essayer depuis le score snapshot
            return _infer_from_snapshot(market_type, pick, row)
        return "W" if (is_over and total > threshold) or \
                      (not is_over and total < threshold) else "L"

    if market_type == "handicap":
        try:
            parts_hcp = pick.rsplit(" ", 1)
            hcp = float(parts_hcp[-1])
            pick_name_low = parts_hcp[0].strip().lower()
            p1_low = p1.split(",")[0].strip().lower()
            total_h = total_a = 0
            for part in final_score.replace(" ", "").split(","):
                if "-" in part:
                    try:
                        h, a = [int(x) for x in part.split("-")]
                        if h <= 7 and a <= 7:
                            total_h += h; total_a += a
                    except Exception:
                        pass
            pick_total = total_h if p1_low in pick_name_low else total_a
            opp_total  = total_a if p1_low in pick_name_low else total_h
            return "W" if (pick_total + hcp) > opp_total else "L"
        except Exception:
            return None

    return None


def _infer_from_snapshot(market_type: str, pick: str, row: Any) -> Optional[str]:
    """Heuristique sur le score snapshot (fallback si pas encore dans settled_matches)."""
    score = row["score"] or ""
    odds_val = row["odds"]

    if market_type in ("set_winner", "next_set"):
        p1_low = (row["player1"] or "").split(",")[0].strip().lower()
        pick_low = pick.lower()
        pick_is_home = p1_low in pick_low

        # Confiance extrême basée sur les cotes : < 1.10 → très forte probabilité de victoire
        if odds_val and odds_val < 1.10:
            return "W"
        if odds_val and odds_val > 8.0:
            return "L"

        if not score:
            return None
        parts = [s.strip() for s in score.split(",")]
        if not parts:
            return None
        last = parts[-1]
        try:
            h, a = [int(x) for x in last.split("-")]
        except Exception:
            return None
        pg = h if pick_is_home else a
        og = a if pick_is_home else h
        if pg >= 6 and og <= 3:
            return "W"
        if og >= 6 and pg <= 3:
            return "L"
        return None

    if market_type in ("total_games", "total_points"):
        try:
            threshold = float(pick.split()[-1])
            is_over = pick.upper().startswith("OVER")
        except Exception:
            return None
        total = 0
        for p in score.split(","):
            p = p.strip()
            if "-" in p and all(x.strip().isdigit() for x in p.split("-", 1)):
                h_g, a_g = p.split("-", 1)
                total += int(h_g) + int(a_g)
        if total == 0:
            return None
        return "W" if (is_over and total > threshold) or \
                      (not is_over and total < threshold) else "L"

    if market_type == "handicap":
        try:
            parts_hcp = pick.rsplit(" ", 1)
            hcp = float(parts_hcp[-1])
            pick_name_low = parts_hcp[0].strip().lower()
            p1_low = (row["player1"] or "").split(",")[0].strip().lower()
            total_h = sum(int(p.split("-")[0]) for p in score.split(",") if "-" in p)
            total_a = sum(int(p.split("-")[1]) for p in score.split(",") if "-" in p)
            pick_total = total_h if p1_low in pick_name_low else total_a
            opp_total  = total_a if p1_low in pick_name_low else total_h
            return "W" if (pick_total + hcp) > opp_total else "L"
        except Exception:
            return None

    return None


def inplay_roi_stats() -> Dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT result, stake, pnl, odds FROM inplay_picks"
        ).fetchall()
    total = len(rows)
    settled = [r for r in rows if r[0] in ("W", "L")]
    wins = sum(1 for r in settled if r[0] == "W")
    losses = sum(1 for r in settled if r[0] == "L")
    pending = total - len(settled) - sum(1 for r in rows if r[0] == "V")
    staked = sum(r[1] for r in settled if r[1])
    pnl = sum(r[2] for r in settled if r[2] is not None)
    roi = (pnl / staked * 100) if staked > 0 else 0.0
    avg_odds = (sum(r[3] for r in settled if r[3]) / len(settled)) if settled else 0.0
    return {
        "total": total, "settled": len(settled), "wins": wins,
        "losses": losses, "pending": pending,
        "staked": round(staked, 2), "pnl": round(pnl, 2),
        "roi_pct": round(roi, 1), "avg_odds": round(avg_odds, 2),
    }
