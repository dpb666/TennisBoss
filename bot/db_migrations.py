"""Migration runner (D-4, docs/ARCHITECTURE_BLUEPRINT.md §7.2).

Complements — does NOT replace — the existing ``CREATE TABLE IF NOT EXISTS``
+ ad-hoc ``ALTER`` dance in ``bot/db.py::init()``. That mechanism keeps
working exactly as before for the ~34 columns it already covers; this module
gives every *future* schema change a versioned, ordered, recorded path
instead of a 35th entry appended to a flat tuple list.

Convention: numbered ``.sql`` files under ``config.MIGRATIONS_DIR``
(``NNNN_description.sql``, zero-padded, ascending). Each file is applied at
most once, inside its own transaction, and recorded in ``schema_migrations``
by filename. A file that fails to apply is never recorded — it stays
pending and blocks nothing already applied before it.
"""
from __future__ import annotations

import os
import sqlite3
from typing import List

from . import config
from .log import log

_CREATE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _ensure_tracking_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TRACKING_TABLE)


def _applied_filenames(conn: sqlite3.Connection) -> set:
    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def _pending_files(migrations_dir: str, applied: set) -> List[str]:
    if not os.path.isdir(migrations_dir):
        return []
    names = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
    return [f for f in names if f not in applied]


def apply_pending_migrations(conn: sqlite3.Connection,
                              migrations_dir: str = None) -> List[str]:
    """Applique dans l'ordre les fichiers .sql pas encore enregistrés.

    Additif uniquement (P3) : ne touche aucun fichier déjà appliqué. Chaque
    fichier est commit séparément — un échec sur le fichier N n'affecte pas
    les fichiers 1..N-1 déjà appliqués avec succès. Renvoie la liste des noms
    de fichiers nouvellement appliqués (vide si `migrations_dir` n'existe pas
    ou ne contient rien de nouveau — c'est l'état normal aujourd'hui, aucune
    migration n'ayant encore été écrite).
    """
    migrations_dir = migrations_dir or config.MIGRATIONS_DIR
    _ensure_tracking_table(conn)
    conn.commit()

    applied_now: List[str] = []
    pending = _pending_files(migrations_dir, _applied_filenames(conn))
    for filename in pending:
        path = os.path.join(migrations_dir, filename)
        with open(path, encoding="utf-8") as f:
            sql = f.read()
        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (?)", (filename,)
            )
            conn.commit()
            applied_now.append(filename)
            log(f"Migration appliquée : {filename}", "INFO")
        except sqlite3.Error as exc:
            conn.rollback()
            log(f"Migration échouée ({filename}) : {exc} — arrêt, fichiers "
                f"suivants non tentés.", "ERROR")
            break
    return applied_now
