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
    l_serve   REAL, l_return1 REAL, l_return2 REAL
);
CREATE TABLE IF NOT EXISTS predictions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT,
    player1  TEXT, player2 TEXT,
    prob1    REAL, favorite TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS backtests (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT,
    span      TEXT,
    tours     TEXT,
    n_train   INTEGER,
    n_test    INTEGER,
    accuracy  REAL,
    logloss   REAL,
    brier     REAL,
    baseline  REAL,
    notes     TEXT
);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(date);
CREATE INDEX IF NOT EXISTS idx_players_tour ON players(tour);
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
        )
        for m in matches
    ]
    with connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        conn.executemany(
            "INSERT OR IGNORE INTO matches "
            "(id,date,tour,winner,loser,w_serve,w_return1,w_return2,"
            " l_serve,l_return1,l_return2) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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


def counts() -> Dict[str, int]:
    with connect() as conn:
        return {
            "players": conn.execute("SELECT COUNT(*) FROM players").fetchone()[0],
            "matches": conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0],
            "predictions": conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0],
            "backtests": conn.execute("SELECT COUNT(*) FROM backtests").fetchone()[0],
        }


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
            "(ts,span,tours,n_train,n_test,accuracy,logloss,brier,baseline,notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                _dt.datetime.now().isoformat(timespec="seconds"),
                report.get("span"), report.get("tours"),
                report.get("n_train"), report.get("n_test"),
                report.get("accuracy"), report.get("logloss"),
                report.get("brier"), report.get("baseline"),
                report.get("notes", ""),
            ),
        )
        return cur.lastrowid


def list_backtests(limit: int = 10) -> List[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM backtests ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
