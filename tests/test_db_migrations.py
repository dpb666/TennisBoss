"""Tests pour bot/db_migrations.py (D-4, migration runner).

Vérifie : table de suivi créée même sans fichier, application dans l'ordre,
idempotence (jamais réappliqué), un échec n'affecte pas ce qui précède et
bloque ce qui suit, et l'intégration avec db.init() (appelé automatiquement).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unittest

from bot import config, db, db_migrations


class TestApplyPendingMigrations(unittest.TestCase):
    def setUp(self):
        fd, self._db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._migrations_dir = tempfile.mkdtemp()

    def tearDown(self):
        for path in (self._db_path, self._db_path + "-wal", self._db_path + "-shm"):
            if os.path.exists(path):
                os.remove(path)
        shutil.rmtree(self._migrations_dir, ignore_errors=True)

    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _write(self, filename: str, sql: str) -> None:
        with open(os.path.join(self._migrations_dir, filename), "w", encoding="utf-8") as f:
            f.write(sql)

    def test_empty_dir_still_creates_tracking_table_and_applies_nothing(self):
        conn = self._conn()
        applied = db_migrations.apply_pending_migrations(conn, self._migrations_dir)
        self.assertEqual(applied, [])
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        conn.close()

    def test_missing_dir_does_not_crash(self):
        conn = self._conn()
        applied = db_migrations.apply_pending_migrations(
            conn, os.path.join(self._migrations_dir, "does_not_exist"))
        self.assertEqual(applied, [])
        conn.close()

    def test_applies_one_migration_and_records_it(self):
        self._write("0001_add_col.sql",
                    "CREATE TABLE widgets (id INTEGER PRIMARY KEY); "
                    "ALTER TABLE widgets ADD COLUMN name TEXT;")
        conn = self._conn()
        applied = db_migrations.apply_pending_migrations(conn, self._migrations_dir)
        self.assertEqual(applied, ["0001_add_col.sql"])
        cols = [r[1] for r in conn.execute("PRAGMA table_info(widgets)").fetchall()]
        self.assertIn("name", cols)
        recorded = conn.execute("SELECT filename FROM schema_migrations").fetchall()
        self.assertEqual([r[0] for r in recorded], ["0001_add_col.sql"])
        conn.close()

    def test_second_call_does_not_reapply(self):
        self._write("0001_create.sql", "CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
        conn = self._conn()
        db_migrations.apply_pending_migrations(conn, self._migrations_dir)
        # Si ré-exécuté, CREATE TABLE (sans IF NOT EXISTS) lèverait — la
        # deuxième passe doit sauter le fichier déjà enregistré, pas le rejouer.
        applied_again = db_migrations.apply_pending_migrations(conn, self._migrations_dir)
        self.assertEqual(applied_again, [])
        conn.close()

    def test_applies_multiple_files_in_filename_order(self):
        self._write("0002_second.sql", "ALTER TABLE widgets ADD COLUMN b TEXT;")
        self._write("0001_first.sql", "CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
        conn = self._conn()
        applied = db_migrations.apply_pending_migrations(conn, self._migrations_dir)
        self.assertEqual(applied, ["0001_first.sql", "0002_second.sql"])
        conn.close()

    def test_failing_migration_keeps_earlier_ones_and_stops_later_ones(self):
        self._write("0001_ok.sql", "CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
        self._write("0002_broken.sql", "ALTER TABLE does_not_exist ADD COLUMN x TEXT;")
        self._write("0003_never_reached.sql", "CREATE TABLE gadgets (id INTEGER PRIMARY KEY);")
        conn = self._conn()
        applied = db_migrations.apply_pending_migrations(conn, self._migrations_dir)
        self.assertEqual(applied, ["0001_ok.sql"])
        recorded = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations").fetchall()}
        self.assertEqual(recorded, {"0001_ok.sql"})
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn("widgets", tables)
        self.assertNotIn("gadgets", tables)
        conn.close()

    def test_non_sql_files_are_ignored(self):
        self._write("README.md", "not a migration")
        conn = self._conn()
        applied = db_migrations.apply_pending_migrations(conn, self._migrations_dir)
        self.assertEqual(applied, [])
        conn.close()


class TestDbInitAppliesMigrations(unittest.TestCase):
    """db.init() doit appliquer les migrations en attente automatiquement,
    sans wiring supplémentaire côté appelant."""

    def setUp(self):
        fd, self._db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._save_db_file = config.DB_FILE
        self._save_migrations_dir = config.MIGRATIONS_DIR
        config.DB_FILE = self._db_path
        config.MIGRATIONS_DIR = tempfile.mkdtemp()

    def tearDown(self):
        config.DB_FILE = self._save_db_file
        shutil.rmtree(config.MIGRATIONS_DIR, ignore_errors=True)
        config.MIGRATIONS_DIR = self._save_migrations_dir
        for path in (self._db_path, self._db_path + "-wal", self._db_path + "-shm"):
            if os.path.exists(path):
                os.remove(path)

    def test_init_applies_a_pending_migration(self):
        with open(os.path.join(config.MIGRATIONS_DIR, "0001_widgets.sql"), "w",
                  encoding="utf-8") as f:
            f.write("CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
        db.init()
        with db.connect() as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn("widgets", tables)
        self.assertIn("schema_migrations", tables)

    def test_init_with_no_migrations_still_creates_tracking_table(self):
        db.init()
        with db.connect() as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn("schema_migrations", tables)


if __name__ == "__main__":
    unittest.main()
