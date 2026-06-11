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

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

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
    margin    INTEGER
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
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(date);
CREATE INDEX IF NOT EXISTS idx_players_tour ON players(tour);
CREATE INDEX IF NOT EXISTS idx_settled_date ON settled_matches(date);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    """Crée la base et le schéma si nécessaire (idempotent)."""
    with connect() as conn:
        conn.executescript(_SCHEMA)
        # Migrations idempotentes (bases déjà créées sans ces colonnes).
        for col, ddl in (
            ("surface", "ALTER TABLE matches ADD COLUMN surface TEXT"),
            ("margin", "ALTER TABLE matches ADD COLUMN margin INTEGER"),
            ("accuracy_elo", "ALTER TABLE backtests ADD COLUMN accuracy_elo REAL"),
            ("logloss_elo",  "ALTER TABLE backtests ADD COLUMN logloss_elo REAL"),
            ("brier_elo",    "ALTER TABLE backtests ADD COLUMN brier_elo REAL"),
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # colonne déjà présente
    log(f"Base SQLite prête : {config.DB_FILE}")


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
        )
        for m in matches
    ]
    with connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        conn.executemany(
            "INSERT OR IGNORE INTO matches "
            "(id,date,tour,winner,loser,w_serve,w_return1,w_return2,"
            " l_serve,l_return1,l_return2,surface,margin) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        after = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
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
    """Derniers matchs du joueur (gagnés ou perdus), les plus récents d'abord."""
    with connect() as conn:
        return conn.execute(
            "SELECT date,tour,winner,loser FROM matches "
            "WHERE winner=? OR loser=? ORDER BY date DESC, id DESC LIMIT ?",
            (name, name, limit),
        ).fetchall()


def all_matches_chrono() -> List[sqlite3.Row]:
    """Tous les matchs par ordre chronologique avec surface (pour l'ELO)."""
    with connect() as conn:
        return conn.execute(
            "SELECT winner, loser, surface, margin FROM matches "
            "ORDER BY date ASC, id ASC").fetchall()


def head_to_head(name1: str, name2: str) -> List[sqlite3.Row]:
    """Confrontations directes entre deux joueurs, les plus récentes d'abord."""
    with connect() as conn:
        return conn.execute(
            "SELECT date,tour,winner,loser FROM matches "
            "WHERE (winner=? AND loser=?) OR (winner=? AND loser=?) "
            "ORDER BY date DESC, id DESC",
            (name1, name2, name2, name1),
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


def list_settled(limit: int = 50) -> List[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM settled_matches ORDER BY date DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def settled_chrono() -> List[sqlite3.Row]:
    """Matchs réglés par ordre chronologique (pour rejouer l'ELO)."""
    with connect() as conn:
        return conn.execute(
            "SELECT player1, player2, winner FROM settled_matches "
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
                   odds: float, ev: float) -> None:
    """Capture un value pick (EV blendée > 0) pour mesurer son ROI au settlement."""
    import datetime as _dt
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO value_picks "
            "(date,player1,player2,side,odds,ev,ts) VALUES (?,?,?,?,?,?,?)",
            (date, p1, p2, side, odds, ev,
             _dt.datetime.now().isoformat(timespec="seconds")),
        )


def list_value_picks() -> List[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT date,player1,player2,side,odds,ev FROM value_picks").fetchall()


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
