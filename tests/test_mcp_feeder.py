"""Tests du feeder Match Charting Project — enrichissement stats WTA
(sans réseau réel ; voir bot/mcp_feeder.py pour le contexte)."""
from __future__ import annotations

import datetime as _dt
import os
import tempfile
import unittest
from unittest import mock

from bot import config, db, mcp_feeder as mcp


class TestPlayerStats(unittest.TestCase):
    def test_computes_serve_and_return_ratios(self):
        row = {
            "serve_pts": "56", "first_won": "32", "second_won": "5",
            "return_pts": "49", "return_pts_won": "19",
            "bk_pts": "7", "bp_saved": "6",
        }
        stats = mcp._player_stats(row)
        self.assertAlmostEqual(stats["serve"], 37 / 56)
        self.assertAlmostEqual(stats["return1"], 19 / 49)
        self.assertAlmostEqual(stats["return2"], 19 / 49)
        self.assertEqual(stats["bp_faced"], 7.0)
        self.assertEqual(stats["bp_saved"], 6.0)

    def test_handles_zero_serve_points_without_crash(self):
        row = {"serve_pts": "0", "first_won": "0", "second_won": "0",
               "return_pts": "0", "return_pts_won": "0", "bk_pts": "0", "bp_saved": "0"}
        stats = mcp._player_stats(row)
        self.assertIsNone(stats["serve"])
        self.assertIsNone(stats["return1"])


class TestFetchOverview(unittest.TestCase):
    def test_groups_total_rows_by_match_and_player_ignores_set_rows(self):
        csv_text = (
            "match_id,player,set,serve_pts,first_won,second_won,bk_pts,bp_saved,"
            "return_pts,return_pts_won\n"
            "m1,Alice,BP,10,5,1,1,1,10,4\n"  # ligne par set -> ignorée
            "m1,Alice,Total,56,32,5,7,6,49,19\n"
            "m1,Bob,Total,49,18,4,6,2,56,19\n"
        )
        with mock.patch.object(mcp, "_http_get", return_value=csv_text):
            out = mcp.fetch_overview()
        self.assertEqual(set(out["m1"].keys()), {"Alice", "Bob"})
        self.assertEqual(out["m1"]["Alice"]["serve_pts"], "56")

    def test_returns_empty_dict_on_fetch_failure(self):
        with mock.patch.object(mcp, "_http_get", return_value=None):
            self.assertEqual(mcp.fetch_overview(), {})


class TestBackfillIntegration(unittest.TestCase):
    """Base SQLite temporaire (pas de mock db) : vérifie la résolution de nom
    par date + l'écriture COALESCE de bout en bout."""

    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def _insert_match(self, match_id, date, winner, loser, w_serve=0.5):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO matches (id,date,tour,winner,loser,w_serve,l_serve) "
                "VALUES (?,?,?,?,?,?,?)",
                (match_id, date, "wta", winner, loser, w_serve, 0.5),
            )

    def test_backfill_enriches_existing_match_without_overwriting_id(self):
        date = "20260524"
        self._insert_match("td_1", date, "Andreeva M.", "Ferro F.")

        mcp_matches = [{
            "match_id": "mcp1", "Player 1": "Mirra Andreeva", "Player 2": "Fiona Ferro",
            "Date": date,
        }]
        overview = {"mcp1": {
            "Mirra Andreeva": {"serve_pts": "56", "first_won": "32", "second_won": "5",
                               "return_pts": "49", "return_pts_won": "19",
                               "bk_pts": "7", "bp_saved": "6"},
            "Fiona Ferro": {"serve_pts": "49", "first_won": "18", "second_won": "4",
                            "return_pts": "56", "return_pts_won": "19",
                            "bk_pts": "6", "bp_saved": "2"},
        }}

        with mock.patch.object(mcp, "fetch_matches", return_value=mcp_matches), \
             mock.patch.object(mcp, "fetch_overview", return_value=overview):
            result = mcp.backfill()

        self.assertEqual(result["updated"], 1)
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM matches WHERE id='td_1'").fetchone()
        self.assertAlmostEqual(row["w_bp_faced"], 7.0)
        self.assertAlmostEqual(row["w_bp_saved"], 6.0)
        self.assertAlmostEqual(row["l_bp_faced"], 6.0)

    def test_backfill_never_overwrites_existing_stats(self):
        date = "20260524"
        self._insert_match("td_1", date, "Andreeva M.", "Ferro F.", w_serve=0.777)

        mcp_matches = [{
            "match_id": "mcp1", "Player 1": "Mirra Andreeva", "Player 2": "Fiona Ferro",
            "Date": date,
        }]
        overview = {"mcp1": {
            "Mirra Andreeva": {"serve_pts": "56", "first_won": "32", "second_won": "5",
                               "return_pts": "49", "return_pts_won": "19",
                               "bk_pts": "7", "bp_saved": "6"},
            "Fiona Ferro": {"serve_pts": "49", "first_won": "18", "second_won": "4",
                            "return_pts": "56", "return_pts_won": "19",
                            "bk_pts": "6", "bp_saved": "2"},
        }}
        with mock.patch.object(mcp, "fetch_matches", return_value=mcp_matches), \
             mock.patch.object(mcp, "fetch_overview", return_value=overview):
            mcp.backfill()
        with db.connect() as conn:
            row = conn.execute("SELECT w_serve FROM matches WHERE id='td_1'").fetchone()
        self.assertAlmostEqual(row["w_serve"], 0.777)  # déjà présent -> pas écrasé

    def test_backfill_skips_match_with_no_db_row_that_date(self):
        mcp_matches = [{
            "match_id": "mcp1", "Player 1": "Nobody One", "Player 2": "Nobody Two",
            "Date": "20260101",
        }]
        overview = {"mcp1": {
            "Nobody One": {"serve_pts": "1", "first_won": "1", "second_won": "0",
                           "return_pts": "1", "return_pts_won": "1", "bk_pts": "0", "bp_saved": "0"},
            "Nobody Two": {"serve_pts": "1", "first_won": "1", "second_won": "0",
                           "return_pts": "1", "return_pts_won": "1", "bk_pts": "0", "bp_saved": "0"},
        }}
        with mock.patch.object(mcp, "fetch_matches", return_value=mcp_matches), \
             mock.patch.object(mcp, "fetch_overview", return_value=overview):
            result = mcp.backfill()
        self.assertEqual(result["updated"], 0)

    def test_backfill_is_idempotent(self):
        date = "20260524"
        self._insert_match("td_1", date, "Andreeva M.", "Ferro F.")
        mcp_matches = [{
            "match_id": "mcp1", "Player 1": "Mirra Andreeva", "Player 2": "Fiona Ferro",
            "Date": date,
        }]
        overview = {"mcp1": {
            "Mirra Andreeva": {"serve_pts": "56", "first_won": "32", "second_won": "5",
                               "return_pts": "49", "return_pts_won": "19",
                               "bk_pts": "7", "bp_saved": "6"},
            "Fiona Ferro": {"serve_pts": "49", "first_won": "18", "second_won": "4",
                            "return_pts": "56", "return_pts_won": "19",
                            "bk_pts": "6", "bp_saved": "2"},
        }}
        with mock.patch.object(mcp, "fetch_matches", return_value=mcp_matches), \
             mock.patch.object(mcp, "fetch_overview", return_value=overview):
            mcp.backfill()
            second = mcp.backfill()
        # Toujours "updated" (la ligne existe et est retouchée, valeurs identiques) —
        # ce qui compte est l'absence d'exception et la stabilité des valeurs.
        with db.connect() as conn:
            row = conn.execute("SELECT w_bp_faced FROM matches WHERE id='td_1'").fetchone()
        self.assertEqual(row["w_bp_faced"], 7.0)


if __name__ == "__main__":
    unittest.main()
