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
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

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
    honeypot_edge_pct    REAL,
    -- Champs de reproductibilité (Data Observability, 2026-07-15) : tout ce
    -- qu'il faut pour rejouer une analyse sur un pick sans reconstruction —
    -- voir docs/EVIDENCE_DRIVEN_OPTIMIZATION.md §3 et docs/LOGGING_SCHEMA.md.
    tournament            TEXT,
    tournament_level      TEXT,        -- 'grand_slam'|'tour'|'challenger_itf'|'other'
    surface               TEXT,
    player_rank           REAL,        -- classement du joueur misé (pick_side)
    opponent_rank         REAL,
    ranking_diff          REAL,        -- opponent_rank - player_rank (positif = pick mieux classé)
    model_prob_raw        REAL,        -- proba modèle AVANT calibration (set_to_match_prob brut)
    model_prob_calibrated REAL,        -- proba modèle APRÈS calibration, AVANT blend marché
    market_prob           REAL,        -- proba marché implicite utilisée dans le blend
    market_disagreement   REAL,        -- abs(model_prob_calibrated - market_prob)
    ev_pct                REAL,        -- EV% de la proba blendée (pick_prob) à la décision
    calib_k               REAL,        -- calib_k (ou a Platt) en vigueur au moment du pick
    market_blend_w        REAL,        -- market_blend_w en vigueur au moment du pick
    calibration_version   TEXT,        -- bot.versions.CALIBRATION_VERSION au moment du pick
    predictor_version     TEXT,        -- bot.versions.PREDICTOR_VERSION au moment du pick
    feature_set_version   TEXT,        -- bot.versions.FEATURE_SET_VERSION au moment du pick
    opening_odds          REAL         -- 1er snapshot de cote vu pour cet event (si disponible)
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
CREATE TABLE IF NOT EXISTS followed_matches (
    event_key        TEXT PRIMARY KEY,   -- id odds-api ou clé composite p1|p2|date
    player1          TEXT,
    player2          TEXT,
    match_date       TEXT,
    tournament       TEXT,
    followed_ts      TEXT,
    last_odds_home   REAL,               -- dernière cote vue (refresh prioritaire)
    last_odds_away   REAL,
    last_refresh_ts  TEXT
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
CREATE TABLE IF NOT EXISTS bet_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key      TEXT,
    player1        TEXT,
    player2        TEXT,
    date           TEXT,
    prediction     REAL,
    pick_side      TEXT,
    odds           REAL,
    confidence     REAL,
    result         INTEGER,
    profit_loss    REAL,
    clv_pct        REAL,
    surface        TEXT,
    model_version  TEXT,
    bookmaker      TEXT,
    ts             TEXT
);
CREATE INDEX IF NOT EXISTS idx_bet_history_date ON bet_history(date);
CREATE INDEX IF NOT EXISTS idx_bet_history_event ON bet_history(event_key);
CREATE INDEX IF NOT EXISTS idx_bet_history_surface ON bet_history(surface);
CREATE TABLE IF NOT EXISTS player_rankings (
    name        TEXT PRIMARY KEY,
    tour        TEXT,
    rank        INTEGER NOT NULL,
    points      REAL,
    as_of       TEXT,
    source      TEXT,
    updated_ts  TEXT
);
CREATE INDEX IF NOT EXISTS idx_player_rankings_tour ON player_rankings(tour);
-- Journal des déploiements (docs/ARCHITECTURE_BLUEPRINT.md §9.3, roadmap Q3 #5) :
-- chaque déploiement/rollback prod est enregistré (scripts/deploy.sh →
-- run.py record-deploy) pour éliminer la dérive prod vs repo (risque R-6).
CREATE TABLE IF NOT EXISTS deployment_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deployed_at TEXT NOT NULL,
    git_hash    TEXT,
    component   TEXT,   -- 'bot' | 'scheduler' | 'android' | 'all'
    result      TEXT,   -- 'success' | 'rollback' | 'failed'
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_clv_date ON clv_log(date);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(date);
CREATE INDEX IF NOT EXISTS idx_players_tour ON players(tour);
CREATE INDEX IF NOT EXISTS idx_settled_date ON settled_matches(date);
-- player_record / player_recent_matches / head_to_head filtrent sur winner/loser
-- (sinon scan complet des ~80 000 matchs à chaque prédiction/H2H).
CREATE INDEX IF NOT EXISTS idx_matches_winner ON matches(winner);
CREATE INDEX IF NOT EXISTS idx_matches_loser ON matches(loser);
CREATE INDEX IF NOT EXISTS idx_matches_surface ON matches(surface);
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
            ("bookmaker", "ALTER TABLE bet_history ADD COLUMN bookmaker TEXT"),
            ("w_rank", "ALTER TABLE matches ADD COLUMN w_rank INTEGER"),
            ("l_rank", "ALTER TABLE matches ADD COLUMN l_rank INTEGER"),
            # Reproductibilité des picks (Data Observability, 2026-07-15) — voir
            # docs/LOGGING_SCHEMA.md. Additif uniquement : bases existantes
            # conservées, nouvelles colonnes NULL sur l'historique déjà loggé.
            ("tournament", "ALTER TABLE clv_log ADD COLUMN tournament TEXT"),
            ("tournament_level", "ALTER TABLE clv_log ADD COLUMN tournament_level TEXT"),
            ("surface", "ALTER TABLE clv_log ADD COLUMN surface TEXT"),
            ("player_rank", "ALTER TABLE clv_log ADD COLUMN player_rank REAL"),
            ("opponent_rank", "ALTER TABLE clv_log ADD COLUMN opponent_rank REAL"),
            ("ranking_diff", "ALTER TABLE clv_log ADD COLUMN ranking_diff REAL"),
            ("model_prob_raw", "ALTER TABLE clv_log ADD COLUMN model_prob_raw REAL"),
            ("model_prob_calibrated", "ALTER TABLE clv_log ADD COLUMN model_prob_calibrated REAL"),
            ("market_prob", "ALTER TABLE clv_log ADD COLUMN market_prob REAL"),
            ("market_disagreement", "ALTER TABLE clv_log ADD COLUMN market_disagreement REAL"),
            ("ev_pct", "ALTER TABLE clv_log ADD COLUMN ev_pct REAL"),
            ("calib_k", "ALTER TABLE clv_log ADD COLUMN calib_k REAL"),
            ("market_blend_w", "ALTER TABLE clv_log ADD COLUMN market_blend_w REAL"),
            ("calibration_version", "ALTER TABLE clv_log ADD COLUMN calibration_version TEXT"),
            ("predictor_version", "ALTER TABLE clv_log ADD COLUMN predictor_version TEXT"),
            ("feature_set_version", "ALTER TABLE clv_log ADD COLUMN feature_set_version TEXT"),
            ("opening_odds", "ALTER TABLE clv_log ADD COLUMN opening_odds REAL"),
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
# Valeur neutre écrite par tennisdata_feeder quand serve/return sont inconnus.
# MCP peut remplacer ces placeholders (voir backfill_match_stats_mcp_bulk).
NEUTRAL_STAT = 0.5
NEUTRAL_STAT_EPS = 1e-4


def _is_neutral_stat(val: Optional[float]) -> bool:
    if val is None:
        return True
    try:
        return abs(float(val) - NEUTRAL_STAT) < NEUTRAL_STAT_EPS
    except (TypeError, ValueError):
        return True


def _fill_mcp_stat(current: Optional[float], new: Optional[float]) -> Optional[float]:
    """Remplace NULL ou 0.5 neutre ; conserve une vraie stat déjà présente."""
    if new is None:
        return current
    if _is_neutral_stat(current):
        return new
    return current


def _fill_mcp_bp(current: Optional[float], new: Optional[float]) -> Optional[float]:
    if new is None:
        return current
    return current if current is not None else new


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
            m.get("w_rank"), m.get("l_rank"),
        )
        for m in matches
    ]
    with connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        conn.executemany(
            "INSERT OR IGNORE INTO matches "
            "(id,date,tour,winner,loser,w_serve,w_return1,w_return2,"
            " l_serve,l_return1,l_return2,surface,margin,"
            " w_bp_saved,w_bp_faced,l_bp_saved,l_bp_faced,w_tb_won,l_tb_won,"
            " w_rank,l_rank) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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


def _apply_backfill_mcp(conn: sqlite3.Connection, match_id: str,
                        winner_stats: Dict[str, float],
                        loser_stats: Dict[str, float]) -> bool:
    """Enrichissement MCP : remplace serve/return neutres (0.5), BP en COALESCE."""
    row = conn.execute(
        "SELECT w_serve,w_return1,w_return2,l_serve,l_return1,l_return2,"
        "w_bp_saved,w_bp_faced,l_bp_saved,l_bp_faced FROM matches WHERE id=?",
        (match_id,),
    ).fetchone()
    if not row:
        return False
    ws = _fill_mcp_stat(row["w_serve"], winner_stats.get("serve"))
    wr1 = _fill_mcp_stat(row["w_return1"], winner_stats.get("return1"))
    wr2 = _fill_mcp_stat(row["w_return2"], winner_stats.get("return2"))
    ls = _fill_mcp_stat(row["l_serve"], loser_stats.get("serve"))
    lr1 = _fill_mcp_stat(row["l_return1"], loser_stats.get("return1"))
    lr2 = _fill_mcp_stat(row["l_return2"], loser_stats.get("return2"))
    wbs = _fill_mcp_bp(row["w_bp_saved"], winner_stats.get("bp_saved"))
    wbf = _fill_mcp_bp(row["w_bp_faced"], winner_stats.get("bp_faced"))
    lbs = _fill_mcp_bp(row["l_bp_saved"], loser_stats.get("bp_saved"))
    lbf = _fill_mcp_bp(row["l_bp_faced"], loser_stats.get("bp_faced"))
    conn.execute(
        "UPDATE matches SET w_serve=?, w_return1=?, w_return2=?, "
        "l_serve=?, l_return1=?, l_return2=?, "
        "w_bp_saved=?, w_bp_faced=?, l_bp_saved=?, l_bp_faced=? WHERE id=?",
        (ws, wr1, wr2, ls, lr1, lr2, wbs, wbf, lbs, lbf, match_id),
    )
    return True


def backfill_match_stats_mcp_bulk(
    updates: List[Tuple[str, Dict[str, float], Dict[str, float]]],
) -> int:
    """Backfill MCP : peut remplacer les stats neutres 0.5 (tennis-data WTA)."""
    if not updates:
        return 0
    updated = 0
    with connect() as conn:
        for match_id, winner_stats, loser_stats in updates:
            if _apply_backfill_mcp(conn, match_id, winner_stats, loser_stats):
                updated += 1
    return updated


def backfill_match_ranks_bulk(
    updates: List[Tuple[str, Optional[int], Optional[int]]],
) -> int:
    """Complète w_rank/l_rank sur des matchs existants (COALESCE)."""
    if not updates:
        return 0
    updated = 0
    with connect() as conn:
        for match_id, w_rank, l_rank in updates:
            if w_rank is None and l_rank is None:
                continue
            cur = conn.execute(
                "UPDATE matches SET "
                "w_rank=COALESCE(w_rank, ?), l_rank=COALESCE(l_rank, ?) "
                "WHERE id=?",
                (w_rank, l_rank, match_id),
            )
            if cur.rowcount:
                updated += 1
    return updated


def upsert_player_ranking(
    name: str,
    tour: str,
    rank: int,
    *,
    as_of: Optional[str] = None,
    source: str = "tennisdata",
    points: Optional[float] = None,
) -> None:
    """Upsert un classement joueur (garde le plus récent par date as_of)."""
    import datetime as _dt
    ts = _dt.datetime.utcnow().isoformat(timespec="seconds")
    with connect() as conn:
        row = conn.execute(
            "SELECT rank, as_of FROM player_rankings WHERE name=?", (name,)
        ).fetchone()
        if row and as_of and row["as_of"] and as_of < row["as_of"]:
            return
        conn.execute(
            "INSERT INTO player_rankings (name, tour, rank, points, as_of, source, updated_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "tour=excluded.tour, rank=excluded.rank, points=excluded.points, "
            "as_of=excluded.as_of, source=excluded.source, updated_ts=excluded.updated_ts",
            (name, tour, rank, points, as_of, source, ts),
        )


def upsert_player_rankings_bulk(rows: List[Dict[str, Any]]) -> int:
    """Upsert en lot — rows: {name, tour, rank, as_of?, source?, points?}."""
    n = 0
    for r in rows:
        if not r.get("name") or r.get("rank") is None:
            continue
        upsert_player_ranking(
            r["name"],
            r.get("tour") or "",
            int(r["rank"]),
            as_of=r.get("as_of"),
            source=r.get("source") or "tennisdata",
            points=r.get("points"),
        )
        n += 1
    return n


def get_all_player_rankings() -> Dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT name, rank FROM player_rankings ORDER BY rank"
        ).fetchall()
    return {r["name"]: int(r["rank"]) for r in rows}


def rebuild_player_rankings_from_matches() -> int:
    """Reconstruit player_rankings depuis le rang le plus récent par joueur/match."""
    import datetime as _dt
    ts = _dt.datetime.utcnow().isoformat(timespec="seconds")
    best: Dict[str, Dict[str, Any]] = {}
    with connect() as conn:
        rows = conn.execute(
            "SELECT winner AS name, tour, w_rank AS rank, date AS as_of "
            "FROM matches WHERE w_rank IS NOT NULL "
            "UNION ALL "
            "SELECT loser AS name, tour, l_rank AS rank, date AS as_of "
            "FROM matches WHERE l_rank IS NOT NULL"
        ).fetchall()
        for r in rows:
            name = r["name"]
            as_of = (r["as_of"] or "").replace("-", "")
            prev = best.get(name)
            if prev is None or as_of >= prev["as_of_key"]:
                best[name] = {
                    "tour": r["tour"],
                    "rank": int(r["rank"]),
                    "as_of": r["as_of"],
                    "as_of_key": as_of,
                }
        n = 0
        for name, info in best.items():
            conn.execute(
                "INSERT INTO player_rankings (name, tour, rank, points, as_of, source, updated_ts) "
                "VALUES (?, ?, ?, NULL, ?, 'matches', ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                "tour=excluded.tour, rank=excluded.rank, "
                "as_of=CASE WHEN excluded.as_of >= COALESCE(player_rankings.as_of, '') "
                "THEN excluded.as_of ELSE player_rankings.as_of END, "
                "source=CASE WHEN excluded.as_of >= COALESCE(player_rankings.as_of, '') "
                "THEN excluded.source ELSE player_rankings.source END, "
                "updated_ts=excluded.updated_ts",
                (name, info["tour"], info["rank"], info["as_of"], ts),
            )
            n += 1
    return n


def wta_stats_coverage() -> Dict[str, Any]:
    """Couverture serve/return non-neutres pour joueurs WTA (matchs MCP-enrichissables)."""
    with connect() as conn:
        total_players = conn.execute(
            "SELECT COUNT(DISTINCT name) FROM ("
            "  SELECT winner AS name FROM matches WHERE tour='wta' "
            "  UNION SELECT loser AS name FROM matches WHERE tour='wta'"
            ")"
        ).fetchone()[0]
        non_neutral_players = conn.execute(
            "SELECT COUNT(DISTINCT name) FROM ("
            "  SELECT winner AS name FROM matches WHERE tour='wta' "
            "    AND ABS(COALESCE(w_serve, 0.5) - 0.5) > 0.01 "
            "  UNION "
            "  SELECT loser AS name FROM matches WHERE tour='wta' "
            "    AND ABS(COALESCE(l_serve, 0.5) - 0.5) > 0.01"
            ")"
        ).fetchone()[0]
        total_matches = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE tour='wta'"
        ).fetchone()[0]
        mcp_matches = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE tour='wta' AND ("
            "  ABS(COALESCE(w_serve, 0.5) - 0.5) > 0.01 OR "
            "  ABS(COALESCE(l_serve, 0.5) - 0.5) > 0.01 OR "
            "  w_bp_faced IS NOT NULL)"
        ).fetchone()[0]
    pct = round(100.0 * non_neutral_players / max(total_players, 1), 2)
    return {
        "tour": "wta",
        "total_players": total_players,
        "players_non_neutral_serve": non_neutral_players,
        "player_serve_coverage_pct": pct,
        "total_matches": total_matches,
        "matches_with_real_or_bp_stats": mcp_matches,
    }


def ranking_coverage_stats(active_days: int = 365) -> Dict[str, Any]:
    """Couverture ranking pour joueurs actifs (match récent ou n>=5)."""
    import datetime as _dt
    cutoff = (_dt.date.today() - _dt.timedelta(days=active_days)).isoformat()
    with connect() as conn:
        active = conn.execute(
            "SELECT COUNT(DISTINCT name) FROM ("
            "  SELECT winner AS name FROM matches WHERE date >= ? "
            "  UNION SELECT loser AS name FROM matches WHERE date >= ?"
            ")",
            (cutoff, cutoff),
        ).fetchone()[0]
        active_with_rank = conn.execute(
            "SELECT COUNT(DISTINCT pr.name) FROM player_rankings pr "
            "WHERE pr.name IN ("
            "  SELECT winner FROM matches WHERE date >= ? "
            "  UNION SELECT loser FROM matches WHERE date >= ?"
            ")",
            (cutoff, cutoff),
        ).fetchone()[0]
        total_ranked = conn.execute(
            "SELECT COUNT(*) FROM player_rankings"
        ).fetchone()[0]
        matches_with_rank = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE w_rank IS NOT NULL OR l_rank IS NOT NULL"
        ).fetchone()[0]
        total_matches = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        # Joueurs "actifs" pour TIS : n>=5 en table players + match récent
        confident_active = conn.execute(
            "SELECT COUNT(DISTINCT p.name) FROM players p "
            "WHERE p.n >= 5 AND p.name IN ("
            "  SELECT winner FROM matches WHERE date >= ? "
            "  UNION SELECT loser FROM matches WHERE date >= ?"
            ")",
            (cutoff, cutoff),
        ).fetchone()[0]
        confident_with_rank = conn.execute(
            "SELECT COUNT(DISTINCT pr.name) FROM player_rankings pr "
            "JOIN players p ON p.name = pr.name "
            "WHERE p.n >= 5 AND pr.name IN ("
            "  SELECT winner FROM matches WHERE date >= ? "
            "  UNION SELECT loser FROM matches WHERE date >= ?"
            ")",
            (cutoff, cutoff),
        ).fetchone()[0]
    pct = round(100.0 * active_with_rank / max(active, 1), 2)
    conf_pct = round(100.0 * confident_with_rank / max(confident_active, 1), 2)
    return {
        "active_players": active,
        "active_with_rank": active_with_rank,
        "active_rank_coverage_pct": pct,
        "confident_active_players": confident_active,
        "confident_active_with_rank": confident_with_rank,
        "confident_active_rank_coverage_pct": conf_pct,
        "total_ranked_players": total_ranked,
        "matches_with_rank": matches_with_rank,
        "match_rank_coverage_pct": round(
            100.0 * matches_with_rank / max(total_matches, 1), 2
        ),
        "active_days": active_days,
    }


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


# --- Version de l'app Android (bandeau "mise à jour disponible") -----------
# Avant publication Play Store (qui gère ça nativement), l'app sideloadée
# vérifie au démarrage si une build plus récente existe (voir GET
# /api/app/version, run.py set-app-version). Stocké en meta (JSON), pas une
# nouvelle table — un seul enregistrement, mis à jour à chaque build notable.
APP_VERSION_META_KEY = "app_latest_version"


def get_app_version_info() -> Optional[Dict[str, Any]]:
    raw = get_meta(APP_VERSION_META_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def set_app_version(version_code: int, version_name: str,
                    notes: str = "", download_url: Optional[str] = None) -> None:
    import datetime as _dt
    payload = {
        "version_code": int(version_code),
        "version_name": version_name,
        "notes": notes,
        "download_url": download_url,
        "published_ts": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    set_meta(APP_VERSION_META_KEY, json.dumps(payload, ensure_ascii=False))


def record_deployment(git_hash: str, component: str = "all",
                      result: str = "success", notes: str = "") -> int:
    """Journalise un déploiement prod (voir scripts/deploy.sh). Renvoie l'id.

    But : rendre chaque changement prod traçable (quoi, quand, quel commit,
    succès ou rollback) — docs/ARCHITECTURE_BLUEPRINT.md §9.3, risque R-6."""
    import datetime as _dt
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO deployment_history (deployed_at, git_hash, component, result, notes) "
            "VALUES (?,?,?,?,?)",
            (_dt.datetime.now().isoformat(timespec="seconds"),
             git_hash, component, result, notes))
        return int(cur.lastrowid)


def list_deployments(limit: int = 20) -> List[Dict[str, Any]]:
    """Derniers déploiements enregistrés, les plus récents d'abord."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, deployed_at, git_hash, component, result, notes "
            "FROM deployment_history ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    return [dict(zip(("id", "deployed_at", "git_hash", "component", "result", "notes"), r))
            for r in rows]


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


@dataclass
class PlayerIntelCache:
    """Prefetch en une connexion pour intelligence_layer (engineer/today batch)."""
    records: Dict[str, Dict[str, int]] = field(default_factory=dict)
    recent_counts: Dict[str, int] = field(default_factory=dict)
    last_dates: Dict[str, Optional[str]] = field(default_factory=dict)
    opponents: Dict[str, List[sqlite3.Row]] = field(default_factory=dict)
    clutch: Dict[str, Dict[str, float]] = field(default_factory=dict)
    h2h: Dict[Tuple[str, str], List[sqlite3.Row]] = field(default_factory=dict)


_EMPTY_CLUTCH: Dict[str, float] = {
    "bp_saved": 0.0, "bp_faced": 0.0, "bp_converted": 0.0,
    "bp_chances": 0.0, "tb_won": 0.0, "tb_played": 0.0, "n_matches": 0.0,
}


def prefetch_player_intel(
    names: Sequence[str],
    pairs: Sequence[Tuple[str, str]],
    *,
    fatigue_cutoff: str,
    opp_limit: int = 10,
    clutch_limit: int = 20,
) -> PlayerIntelCache:
    """Charge en UNE transaction les données lues par intelligence_layer.

    Évite N×~8 connexions SQLite par match sur /api/engineer/today (cold ~36s).
    """
    unique = sorted({n for n in names if n})
    cache = PlayerIntelCache()
    if not unique:
        return cache

    ph = ",".join("?" * len(unique))
    params = tuple(unique)

    with connect() as conn:
        for row in conn.execute(
            f"SELECT winner, COUNT(*) AS c FROM matches WHERE winner IN ({ph}) GROUP BY winner",
            params,
        ).fetchall():
            cache.records.setdefault(row["winner"], {"wins": 0, "losses": 0})["wins"] = int(row["c"])
        for row in conn.execute(
            f"SELECT loser, COUNT(*) AS c FROM matches WHERE loser IN ({ph}) GROUP BY loser",
            params,
        ).fetchall():
            cache.records.setdefault(row["loser"], {"wins": 0, "losses": 0})["losses"] = int(row["c"])
        for n in unique:
            cache.records.setdefault(n, {"wins": 0, "losses": 0})

        for row in conn.execute(
            f"SELECT player, COUNT(*) AS c FROM ("
            f"  SELECT winner AS player FROM matches WHERE winner IN ({ph}) "
            f"    AND REPLACE(date,'-','') >= ? "
            f"  UNION ALL "
            f"  SELECT loser AS player FROM matches WHERE loser IN ({ph}) "
            f"    AND REPLACE(date,'-','') >= ?"
            f") GROUP BY player",
            params + (fatigue_cutoff,) + params + (fatigue_cutoff,),
        ).fetchall():
            cache.recent_counts[row["player"]] = int(row["c"])

        for row in conn.execute(
            f"SELECT player, MAX(d) AS d FROM ("
            f"  SELECT winner AS player, REPLACE(date,'-','') AS d FROM matches "
            f"    WHERE winner IN ({ph}) "
            f"  UNION ALL "
            f"  SELECT loser AS player, REPLACE(date,'-','') AS d FROM matches "
            f"    WHERE loser IN ({ph})"
            f") GROUP BY player",
            params + params,
        ).fetchall():
            cache.last_dates[row["player"]] = row["d"]

        opp_rows = conn.execute(
            f"SELECT player, winner, loser, d FROM ("
            f"  SELECT winner AS player, winner, loser, REPLACE(date,'-','') AS d "
            f"    FROM matches WHERE winner IN ({ph}) "
            f"  UNION ALL "
            f"  SELECT loser AS player, winner, loser, REPLACE(date,'-','') AS d "
            f"    FROM matches WHERE loser IN ({ph})"
            f") ORDER BY player, d DESC",
            params + params,
        ).fetchall()
        for row in opp_rows:
            lst = cache.opponents.setdefault(row["player"], [])
            if len(lst) < opp_limit:
                lst.append(row)

        clutch_rows = conn.execute(
            f"SELECT winner, loser, w_bp_saved, w_bp_faced, l_bp_saved, l_bp_faced, "
            f"       w_tb_won, l_tb_won, player, d FROM ("
            f"  SELECT winner, loser, w_bp_saved, w_bp_faced, l_bp_saved, l_bp_faced, "
            f"         w_tb_won, l_tb_won, winner AS player, REPLACE(date,'-','') AS d "
            f"    FROM matches WHERE winner IN ({ph}) AND w_bp_faced IS NOT NULL "
            f"  UNION ALL "
            f"  SELECT winner, loser, w_bp_saved, w_bp_faced, l_bp_saved, l_bp_faced, "
            f"         w_tb_won, l_tb_won, loser AS player, REPLACE(date,'-','') AS d "
            f"    FROM matches WHERE loser IN ({ph}) AND w_bp_faced IS NOT NULL"
            f") ORDER BY player, d DESC",
            params + params,
        ).fetchall()
        clutch_acc: Dict[str, Dict[str, float]] = {}
        clutch_n: Dict[str, int] = {}
        for row in clutch_rows:
            pname = row["player"]
            if clutch_n.get(pname, 0) >= clutch_limit:
                continue
            out = clutch_acc.setdefault(pname, dict(_EMPTY_CLUTCH))
            if row["winner"] == pname:
                own_s, own_f = row["w_bp_saved"], row["w_bp_faced"]
                opp_s, opp_f = row["l_bp_saved"], row["l_bp_faced"]
                own_tb, opp_tb = row["w_tb_won"], row["l_tb_won"]
            else:
                own_s, own_f = row["l_bp_saved"], row["l_bp_faced"]
                opp_s, opp_f = row["w_bp_saved"], row["w_bp_faced"]
                own_tb, opp_tb = row["l_tb_won"], row["w_tb_won"]
            out["bp_saved"] += own_s or 0.0
            out["bp_faced"] += own_f or 0.0
            out["bp_converted"] += (opp_f or 0.0) - (opp_s or 0.0)
            out["bp_chances"] += opp_f or 0.0
            out["tb_won"] += own_tb or 0
            out["tb_played"] += (own_tb or 0) + (opp_tb or 0)
            clutch_n[pname] = clutch_n.get(pname, 0) + 1
            out["n_matches"] = float(clutch_n[pname])
        cache.clutch = clutch_acc

        seen_pairs: Set[Tuple[str, str]] = set()
        for n1, n2 in pairs:
            key = (n1, n2)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            cache.h2h[key] = conn.execute(
                "SELECT date,tour,winner,loser FROM matches "
                "WHERE (winner=? AND loser=?) OR (winner=? AND loser=?) "
                "ORDER BY REPLACE(date,'-','') DESC, id DESC",
                (n1, n2, n2, n1),
            ).fetchall()

    return cache


def counts() -> Dict[str, int]:
    with connect() as conn:
        return {
            "players": conn.execute("SELECT COUNT(*) FROM players").fetchone()[0],
            "matches": conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0],
            "predictions": conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0],
            "backtests": conn.execute("SELECT COUNT(*) FROM backtests").fetchone()[0],
            "settled": conn.execute("SELECT COUNT(*) FROM settled_matches").fetchone()[0],
            "bet_history": conn.execute("SELECT COUNT(*) FROM bet_history").fetchone()[0],
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


def _value_pick_surface(p1: str, p2: str) -> str:
    """Surface du dernier value_pick pour une paire (vide si inconnu)."""
    for a in _name_variants(p1):
        for b in _name_variants(p2):
            with connect() as conn:
                row = conn.execute(
                    "SELECT surface FROM value_picks "
                    "WHERE ((player1=? AND player2=?) OR (player1=? AND player2=?)) "
                    "ORDER BY ts DESC LIMIT 1",
                    (a, b, b, a),
                ).fetchone()
            if row and (row["surface"] or "").strip():
                return (row["surface"] or "").strip()
    return ""


def lookup_surface_from_archive(p1: str, p2: str, date: str = "") -> str:
    """Surface depuis l'archive matches (player pair + date optionnelle).

    Cherche d'abord une confrontation exacte à la date, sinon la plus récente
    avant cette date pour la paire.
    """
    date_compact = (date or "").replace("-", "")[:8]
    for a in _name_variants(p1):
        for b in _name_variants(p2):
            with connect() as conn:
                if date_compact:
                    row = conn.execute(
                        "SELECT surface FROM matches "
                        "WHERE ((winner=? AND loser=?) OR (winner=? AND loser=?)) "
                        "AND REPLACE(date,'-','')=? "
                        "AND surface IS NOT NULL AND surface != '' "
                        "LIMIT 1",
                        (a, b, b, a, date_compact),
                    ).fetchone()
                    if row and row["surface"]:
                        return (row["surface"] or "").strip()
                row = conn.execute(
                    "SELECT surface FROM matches "
                    "WHERE ((winner=? AND loser=?) OR (winner=? AND loser=?)) "
                    "AND surface IS NOT NULL AND surface != '' "
                    + ("AND REPLACE(date,'-','')<=? " if date_compact else "")
                    + "ORDER BY REPLACE(date,'-','') DESC, id DESC LIMIT 1",
                    (a, b, b, a, date_compact) if date_compact else (a, b, b, a),
                ).fetchone()
            if row and (row["surface"] or "").strip():
                return (row["surface"] or "").strip()
    return ""


def resolve_bet_surface(p1: str, p2: str, date: str = "") -> str:
    """Surface pour bet_history : value_pick d'abord, puis archive matches."""
    surf = _value_pick_surface(p1, p2)
    if surf:
        return surf
    return lookup_surface_from_archive(p1, p2, date)


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
                 honeypot: Optional[Dict[str, Any]] = None,
                 repro: Optional[Dict[str, Any]] = None) -> None:
    """Sème un pick dans le journal CLV (closing_odds rempli plus tard).

    INSERT OR IGNORE : on garde la PREMIÈRE cote vue (la décision d'entrée),
    on ne l'écrase pas si le pick réapparaît avec une cote qui a bougé.
    `honeypot` : signal weather_profile.analyze() au moment du pick (fige la
    condition constatée ce jour-là — ne pas le recalculer après coup, l'état
    des profils joueurs change avec le temps).
    `repro` : champs de reproductibilité (voir docs/LOGGING_SCHEMA.md) —
    tournament, tournament_level, surface, player_rank, opponent_rank,
    ranking_diff, model_prob_raw, model_prob_calibrated, market_prob,
    market_disagreement, ev_pct, calib_k, market_blend_w,
    calibration_version, predictor_version, feature_set_version,
    opening_odds. Optionnel (None -> colonnes NULL) pour ne pas casser les
    appelants existants ; toutes les nouvelles capture-paths de bot/api.py le
    renseignent systématiquement (voir clv.seed_pick).
    """
    import datetime as _dt
    hp = honeypot or {}
    rp = repro or {}
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO clv_log "
            "(event_key,date,player1,player2,pick_side,pick_odds,pick_prob,"
            " confidence,pick_ts,honeypot_flag,honeypot_beneficiary,"
            " honeypot_player,honeypot_edge_pct,"
            " tournament,tournament_level,surface,player_rank,opponent_rank,"
            " ranking_diff,model_prob_raw,model_prob_calibrated,market_prob,"
            " market_disagreement,ev_pct,calib_k,market_blend_w,"
            " calibration_version,predictor_version,feature_set_version,"
            " opening_odds) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_key, date, p1, p2, side, pick_odds, pick_prob, confidence,
             _dt.datetime.now().isoformat(timespec="seconds"),
             1 if hp.get("flag") else 0, hp.get("beneficiary"),
             hp.get("player"), hp.get("edge_pct"),
             rp.get("tournament"), rp.get("tournament_level"), rp.get("surface"),
             rp.get("player_rank"), rp.get("opponent_rank"), rp.get("ranking_diff"),
             rp.get("model_prob_raw"), rp.get("model_prob_calibrated"), rp.get("market_prob"),
             rp.get("market_disagreement"), rp.get("ev_pct"), rp.get("calib_k"),
             rp.get("market_blend_w"), rp.get("calibration_version"),
             rp.get("predictor_version"), rp.get("feature_set_version"),
             rp.get("opening_odds")),
        )


# Champs de reproductibilité requis sur chaque pick (voir log_clv_pick.repro
# et docs/LOGGING_SCHEMA.md) — utilisés par la validation de complétude.
CLV_REPRO_FIELDS = (
    "tournament", "tournament_level", "surface", "player_rank", "opponent_rank",
    "ranking_diff", "model_prob_raw", "model_prob_calibrated", "market_prob",
    "market_disagreement", "ev_pct", "calib_k", "market_blend_w",
    "calibration_version", "predictor_version", "feature_set_version",
)


def validate_clv_pick_row(row: Any) -> List[str]:
    """Renvoie la liste des champs de reproductibilité manquants (NULL) pour
    une ligne clv_log. Liste vide = pick complet. `opening_odds` et
    `closing_odds` sont exclus (légitimement absents tant que le marché n'a
    pas encore bougé/le match n'est pas terminé — pas un défaut de capture)."""
    missing = []
    for field in CLV_REPRO_FIELDS:
        try:
            val = row[field]
        except (IndexError, KeyError):
            val = None
        if val is None:
            missing.append(field)
    return missing


def find_incomplete_clv_picks(limit: int = 200, since: Optional[str] = None) -> List[Dict[str, Any]]:
    """Picks dont au moins un champ de reproductibilité requis est NULL —
    détection automatique des enregistrements incomplets (voir
    docs/LOGGING_SCHEMA.md, section validation)."""
    where = "WHERE date >= ?" if since else ""
    params: Tuple[Any, ...] = (since,) if since else ()
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM clv_log {where} ORDER BY pick_ts DESC LIMIT ?",
            params + (limit,),
        ).fetchall()
    out = []
    for r in rows:
        missing = validate_clv_pick_row(r)
        if missing:
            out.append({"event_key": r["event_key"], "date": r["date"],
                       "player1": r["player1"], "player2": r["player2"],
                       "pick_ts": r["pick_ts"], "missing_fields": missing})
    return out


def clv_logging_completeness_report(bucket: str = "week", limit_buckets: int = 26) -> Dict[str, Any]:
    """Taux de complétude des champs de reproductibilité, agrégé par période
    (`bucket` = 'week' ou 'day') — pour un rapport de santé du logging dans le
    temps (voir docs/LOGGING_SCHEMA.md). Une ligne est "complète" si TOUS les
    champs CLV_REPRO_FIELDS sont renseignés (hors opening/closing odds, cf.
    validate_clv_pick_row)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM clv_log ORDER BY date ASC"
        ).fetchall()

    def _period_key(date_str: str) -> str:
        d = (date_str or "")[:10]
        if not d:
            return "inconnue"
        if bucket == "day":
            return d
        try:
            import datetime as _dt
            dt = _dt.date.fromisoformat(d)
            monday = dt - _dt.timedelta(days=dt.weekday())
            return monday.isoformat()
        except ValueError:
            return d

    by_period: Dict[str, Dict[str, int]] = {}
    field_missing_counts: Dict[str, int] = {f: 0 for f in CLV_REPRO_FIELDS}
    n_total = 0
    n_complete = 0

    for r in rows:
        n_total += 1
        period = _period_key(r["date"])
        stats = by_period.setdefault(period, {"n": 0, "n_complete": 0})
        stats["n"] += 1
        missing = validate_clv_pick_row(r)
        if not missing:
            stats["n_complete"] += 1
            n_complete += 1
        for f in missing:
            field_missing_counts[f] += 1

    periods_sorted = sorted(by_period.keys(), reverse=True)[:limit_buckets]
    by_period_out = {
        p: {
            "n": by_period[p]["n"],
            "n_complete": by_period[p]["n_complete"],
            "completeness_pct": round(by_period[p]["n_complete"] / by_period[p]["n"] * 100, 1)
                                if by_period[p]["n"] else None,
        }
        for p in periods_sorted
    }

    return {
        "bucket": bucket,
        "n_total": n_total,
        "n_complete": n_complete,
        "completeness_pct_overall": round(n_complete / n_total * 100, 1) if n_total else None,
        "by_period": by_period_out,
        "missing_field_counts": field_missing_counts,
        "most_incomplete_field": (max(field_missing_counts, key=field_missing_counts.get)
                                  if n_total and any(field_missing_counts.values()) else None),
    }


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


# --- Bet history (performance tracking unifié) ------------------------------
def log_bet_history(row: Dict[str, Any]) -> int:
    """Enregistre un pari réglé dans bet_history (ignore les doublons event_key)."""
    import datetime as _dt
    event_key = str(row.get("event_key") or "")
    with connect() as conn:
        if event_key:
            existing = conn.execute(
                "SELECT 1 FROM bet_history WHERE event_key=?", (event_key,)).fetchone()
            if existing:
                return 0
        cur = conn.execute(
            "INSERT INTO bet_history "
            "(event_key,player1,player2,date,prediction,pick_side,odds,confidence,"
            " result,profit_loss,clv_pct,surface,model_version,bookmaker,ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_key or None,
                str(row.get("player1") or ""),
                str(row.get("player2") or ""),
                str(row.get("date") or ""),
                row.get("prediction"),
                str(row.get("pick_side") or ""),
                row.get("odds"),
                row.get("confidence"),
                row.get("result"),
                row.get("profit_loss"),
                row.get("clv_pct"),
                str(row.get("surface") or ""),
                str(row.get("model_version") or ""),
                str(row.get("bookmaker") or "") or None,
                row.get("ts") or _dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return int(cur.lastrowid or 0)


def _bet_history_model_version() -> str:
    raw = get_meta("metrics")
    if raw:
        try:
            m = json.loads(raw)
            if m.get("updated"):
                return str(m["updated"])[:10]
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return "default"


def sync_bet_history_on_settle(p1: str, p2: str, winner_name: str,
                               event_key: Optional[str] = None) -> bool:
    """Auto-log après settlement CLV ou value pick (un seul point d'appel).

    Priorité : ligne clv_log réglée pour cette paire, sinon value_pick réglé.
    """
    if not winner_name:
        return False

    p1_vars = set(_name_variants(p1))
    p2_vars = set(_name_variants(p2))
    winner_vars = set(_name_variants(winner_name))

    with connect() as conn:
        clv_row = None
        if event_key:
            clv_row = conn.execute(
                "SELECT * FROM clv_log WHERE event_key=? AND result IS NOT NULL",
                (event_key,)).fetchone()
        if clv_row is None:
            for r in conn.execute(
                "SELECT * FROM clv_log WHERE result IS NOT NULL ORDER BY settled_ts DESC"
            ).fetchall():
                r1 = set(_name_variants(r["player1"]))
                r2 = set(_name_variants(r["player2"]))
                if (r1 & p1_vars and r2 & p2_vars) or (r1 & p2_vars and r2 & p1_vars):
                    if event_key and r["event_key"] != event_key:
                        continue
                    clv_row = r
                    break

        vp_row = None
        vp_settled = None
        for a in p1_vars:
            for b in p2_vars:
                vp_settled = conn.execute(
                    "SELECT * FROM value_picks "
                    "WHERE result IN (0,1) AND ((player1=? AND player2=?) OR (player1=? AND player2=?)) "
                    "ORDER BY ts DESC LIMIT 1",
                    (a, b, b, a),
                ).fetchone()
                vp_row = vp_settled or conn.execute(
                    "SELECT * FROM value_picks "
                    "WHERE ((player1=? AND player2=?) OR (player1=? AND player2=?)) "
                    "ORDER BY ts DESC LIMIT 1",
                    (a, b, b, a),
                ).fetchone()
                if vp_row:
                    break
            if vp_row:
                break

        if clv_row is None and vp_settled is None:
            return False

        ek = (clv_row["event_key"] if clv_row else None) or event_key or ""
        if ek:
            if conn.execute(
                "SELECT 1 FROM bet_history WHERE event_key=?", (ek,)
            ).fetchone():
                return False

        if clv_row:
            pick_side = clv_row["pick_side"]
            return log_bet_history({
                "event_key": ek,
                "player1": clv_row["player1"],
                "player2": clv_row["player2"],
                "date": clv_row["date"],
                "prediction": clv_row["pick_prob"],
                "pick_side": pick_side,
                "odds": clv_row["pick_odds"],
                "confidence": clv_row["confidence"],
                "result": clv_row["result"],
                "profit_loss": clv_row["pnl_flat"],
                "clv_pct": clv_row["clv_pct"],
                "surface": resolve_bet_surface(clv_row["player1"], clv_row["player2"], clv_row["date"]),
                "model_version": _bet_history_model_version(),
                "bookmaker": clv_row["closing_src"] or "",
                "ts": clv_row["settled_ts"],
            }) > 0

        side = vp_settled["side"]
        won = bool(set(_name_variants(side)) & winner_vars)
        if not ek:
            dup = conn.execute(
                "SELECT 1 FROM bet_history WHERE player1=? AND player2=? AND date=?",
                (vp_settled["player1"], vp_settled["player2"], vp_settled["date"]),
            ).fetchone()
            if dup:
                return False
        pnl = vp_settled["pnl"]
        if pnl is None:
            odds = float(vp_settled["odds"] or 0)
            pnl = round((odds - 1.0) if won else -1.0, 4) if odds > 1 else None
        return log_bet_history({
            "event_key": ek or None,
            "player1": vp_settled["player1"],
            "player2": vp_settled["player2"],
            "date": vp_settled["date"],
            "prediction": None,
            "pick_side": side,
            "odds": vp_settled["odds"],
            "confidence": None,
            "result": vp_settled["result"],
            "profit_loss": pnl,
            "clv_pct": None,
            "surface": vp_settled["surface"] or "",
            "model_version": _bet_history_model_version(),
        }) > 0


def list_bet_history(limit: int = 50, days: Optional[int] = None) -> List[sqlite3.Row]:
    """Historique des paris réglés, du plus récent au plus ancien."""
    with connect() as conn:
        if days is not None and days > 0:
            import datetime as _dt
            since = (_dt.date.today() - _dt.timedelta(days=days - 1)).isoformat()
            return conn.execute(
                "SELECT * FROM bet_history WHERE date >= ? "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM bet_history ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def _bet_history_calibration_bins(rows: List[sqlite3.Row], n_bins: int = 5) -> List[Dict[str, Any]]:
    """Bins de calibration sur la confiance (observé vs prédit implicite)."""
    bins = [{"lo": i / n_bins, "hi": (i + 1) / n_bins, "n": 0,
             "sum_conf": 0.0, "sum_outcome": 0.0} for i in range(n_bins)]
    for r in rows:
        conf = r["confidence"]
        if conf is None or r["result"] not in (0, 1):
            continue
        idx = min(int(float(conf) * n_bins), n_bins - 1)
        if float(conf) >= 1.0:
            idx = n_bins - 1
        b = bins[idx]
        b["n"] += 1
        b["sum_conf"] += float(conf)
        b["sum_outcome"] += float(r["result"])
    out = []
    for b in bins:
        if b["n"] == 0:
            out.append({"bin": f"{b['lo']:.0%}-{b['hi']:.0%}", "n": 0,
                        "mean_confidence": None, "observed_rate": None})
        else:
            out.append({
                "bin": f"{b['lo']:.0%}-{b['hi']:.0%}",
                "n": b["n"],
                "mean_confidence": round(b["sum_conf"] / b["n"], 3),
                "observed_rate": round(b["sum_outcome"] / b["n"], 3),
            })
    return out


def _bet_history_surface_stats(rows: List[sqlite3.Row]) -> Dict[str, Dict[str, Any]]:
    by_surf: Dict[str, List[sqlite3.Row]] = {}
    for r in rows:
        surf = (r["surface"] or "unknown").lower() or "unknown"
        by_surf.setdefault(surf, []).append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for surf, pool in by_surf.items():
        settled = [x for x in pool if x["result"] in (0, 1)]
        n = len(settled)
        if n == 0:
            out[surf] = {"n": 0, "win_rate": None, "roi": None}
            continue
        wins = sum(1 for x in settled if x["result"] == 1)
        pnls = [x["profit_loss"] for x in settled if x["profit_loss"] is not None]
        out[surf] = {
            "n": n,
            "wins": wins,
            "win_rate": round(wins / n, 3),
            "roi": round(sum(pnls) / len(pnls), 4) if pnls else None,
        }
    return out


def _bet_history_bookmaker_stats(rows: List[sqlite3.Row]) -> Dict[str, Dict[str, Any]]:
    """Performance par source de closing line (proxy bookmaker)."""
    by_bk: Dict[str, List[sqlite3.Row]] = {}
    for r in rows:
        bk = (r["bookmaker"] if "bookmaker" in r.keys() else None) or "unknown"
        by_bk.setdefault(str(bk), []).append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for bk, pool in by_bk.items():
        settled = [x for x in pool if x["result"] in (0, 1)]
        n = len(settled)
        if n == 0:
            out[bk] = {"n": 0}
            continue
        wins = sum(1 for x in settled if x["result"] == 1)
        pnls = [x["profit_loss"] for x in settled if x["profit_loss"] is not None]
        clvs = [x["clv_pct"] for x in settled if x["clv_pct"] is not None]
        out[bk] = {
            "n": n,
            "win_rate": round(wins / n, 3),
            "yield_pct": round(sum(pnls) / len(pnls) * 100, 1) if pnls else None,
            "avg_clv_pct": round(sum(clvs) / len(clvs), 2) if clvs else None,
        }
    return out


def bet_history_calibration(days: int = 90) -> Dict[str, Any]:
    """Bins 50-55%, 55-60%, … 75%+ : probabilité modèle vs taux de victoire réel."""
    rows = list_bet_history(limit=100000, days=days)
    settled = [r for r in rows if r["result"] in (0, 1) and r["prediction"] is not None]
    bins_def = [
        (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70),
        (0.70, 0.75), (0.75, 1.01),
    ]
    bins_out: List[Dict[str, Any]] = []
    for lo, hi in bins_def:
        pool = [r for r in settled if lo <= float(r["prediction"]) < hi]
        if not pool:
            bins_out.append({
                "bin": f"{int(lo*100)}-{int(min(hi, 1)*100)}%",
                "n": 0, "predicted": None, "observed": None, "gap": None,
            })
            continue
        pred_mean = sum(float(r["prediction"]) for r in pool) / len(pool)
        obs = sum(int(r["result"]) for r in pool) / len(pool)
        bins_out.append({
            "bin": f"{int(lo*100)}-{int(min(hi, 1)*100)}%",
            "n": len(pool),
            "predicted": round(pred_mean, 3),
            "observed": round(obs, 3),
            "gap": round(obs - pred_mean, 3),
        })
    brier = None
    if settled:
        brier = sum(
            (float(r["prediction"]) - int(r["result"])) ** 2 for r in settled
        ) / len(settled)
    return {
        "days": days,
        "n_settled": len(settled),
        "brier_score": round(brier, 4) if brier is not None else None,
        "bins": bins_out,
    }


def backfill_bet_history_from_clv(limit: int = 500) -> Dict[str, int]:
    """Remplit bet_history depuis clv_log réglés; corrige surfaces manquantes."""
    added = 0
    patched = 0
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM clv_log WHERE result IS NOT NULL "
            "ORDER BY settled_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    for r in rows:
        ek = r["event_key"] or ""
        with connect() as c:
            if ek and c.execute(
                "SELECT 1 FROM bet_history WHERE event_key=?", (ek,)
            ).fetchone():
                continue
        if log_bet_history({
            "event_key": ek,
            "player1": r["player1"],
            "player2": r["player2"],
            "date": r["date"],
            "prediction": r["pick_prob"],
            "pick_side": r["pick_side"],
            "odds": r["pick_odds"],
            "confidence": r["confidence"],
            "result": r["result"],
            "profit_loss": r["pnl_flat"],
            "clv_pct": r["clv_pct"],
            "surface": resolve_bet_surface(r["player1"], r["player2"], r["date"]),
            "model_version": _bet_history_model_version(),
            "bookmaker": r["closing_src"] or "",
            "ts": r["settled_ts"],
        }) > 0:
            added += 1
    with connect() as c:
        missing = c.execute(
            "SELECT id, player1, player2 FROM bet_history "
            "WHERE surface IS NULL OR surface=''"
        ).fetchall()
    for row in missing:
        surf = resolve_bet_surface(row["player1"], row["player2"])
        if surf:
            with connect() as c:
                c.execute(
                    "UPDATE bet_history SET surface=? WHERE id=?",
                    (surf, row["id"]),
                )
            patched += 1
    return {"added": added, "patched": patched}


def backfill_bet_history_surface_from_matches() -> Dict[str, int]:
    """Remplit les surfaces manquantes via archive matches (player+date)."""
    patched = 0
    with connect() as c:
        missing = c.execute(
            "SELECT id, player1, player2, date FROM bet_history "
            "WHERE surface IS NULL OR surface=''"
        ).fetchall()
    for row in missing:
        surf = lookup_surface_from_archive(
            row["player1"], row["player2"], row["date"] or "",
        )
        if surf:
            with connect() as c:
                c.execute(
                    "UPDATE bet_history SET surface=? WHERE id=?",
                    (surf, row["id"]),
                )
            patched += 1
    return {"patched": patched}


def bet_history_stats(days: int = 30) -> Dict[str, Any]:
    """ROI, win rate, bins de calibration et performance par surface."""
    rows = list_bet_history(limit=100000, days=days)
    settled = [r for r in rows if r["result"] in (0, 1)]
    n = len(settled)
    if n == 0:
        return {
            "days": days,
            "n": 0,
            "wins": 0,
            "win_rate": None,
            "roi": None,
            "total_pnl": 0.0,
            "calibration_bins": _bet_history_calibration_bins([]),
            "by_surface": {},
            "by_bookmaker": {},
            "avg_clv_pct": None,
            "yield_pct": None,
        }
    wins = sum(1 for r in settled if r["result"] == 1)
    pnls = [r["profit_loss"] for r in settled if r["profit_loss"] is not None]
    clvs = [r["clv_pct"] for r in settled if r["clv_pct"] is not None]
    return {
        "days": days,
        "n": n,
        "wins": wins,
        "win_rate": round(wins / n, 3),
        "roi": round(sum(pnls) / len(pnls), 4) if pnls else None,
        "yield_pct": round(sum(pnls) / len(pnls) * 100, 1) if pnls else None,
        "total_pnl": round(sum(pnls), 2) if pnls else 0.0,
        "calibration_bins": _bet_history_calibration_bins(settled),
        "by_surface": _bet_history_surface_stats(settled),
        "by_bookmaker": _bet_history_bookmaker_stats(settled),
        "avg_clv_pct": round(sum(clvs) / len(clvs), 2) if clvs else None,
    }


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


def _match_event_key(event_key: Optional[str], p1: str, p2: str, date: str) -> str:
    if event_key:
        return str(event_key)
    return f"{p1.lower()}|{p2.lower()}|{date}"


def follow_match(event_key: Optional[str], p1: str, p2: str,
                 match_date: str = "", tournament: str = "") -> str:
    """Suit un match (INSERT OR IGNORE). Retourne la clé utilisée."""
    import datetime as _dt
    key = _match_event_key(event_key, p1, p2, match_date)
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO followed_matches "
            "(event_key, player1, player2, match_date, tournament, followed_ts) "
            "VALUES (?,?,?,?,?,?)",
            (key, p1, p2, match_date, tournament,
             _dt.datetime.now().isoformat(timespec="seconds")),
        )
    return key


def unfollow_match(event_key: Optional[str], p1: str = "", p2: str = "",
                   match_date: str = "") -> None:
    key = event_key or _match_event_key(None, p1, p2, match_date)
    with connect() as conn:
        conn.execute("DELETE FROM followed_matches WHERE event_key=?", (key,))


def list_followed_matches() -> List[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM followed_matches ORDER BY followed_ts DESC"
        ).fetchall()


def is_match_followed(event_key: Optional[str], p1: str = "", p2: str = "",
                      match_date: str = "") -> bool:
    key = event_key or _match_event_key(None, p1, p2, match_date)
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM followed_matches WHERE event_key=?", (key,)
        ).fetchone()
    return row is not None


def update_followed_match_odds(event_key: str, odds_home: float,
                               odds_away: float) -> None:
    import datetime as _dt
    with connect() as conn:
        conn.execute(
            "UPDATE followed_matches SET last_odds_home=?, last_odds_away=?, "
            "last_refresh_ts=? WHERE event_key=?",
            (odds_home, odds_away,
             _dt.datetime.now().isoformat(timespec="seconds"), event_key),
        )


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


def earliest_market_snapshot(event_key: str) -> Optional[sqlite3.Row]:
    """1er snapshot de cote vu pour un event (potentiellement le seul) — sert
    de "cote d'ouverture" pour le logging de reproductibilité (clv_log.
    opening_odds), sans exiger 2 snapshots comme line_movement()."""
    if not event_key:
        return None
    with connect() as conn:
        return conn.execute(
            "SELECT ts, odds_home, odds_away FROM market_snapshots "
            "WHERE event_key=? ORDER BY ts ASC LIMIT 1", (event_key,)
        ).fetchone()


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
