"""Tests ranking_feeder + load_rankings pour ranking_diff."""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config, db
from bot.ml_prep import features as feat


class TestRankingDb(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def test_backfill_match_ranks_coalesce(self):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO matches (id,date,tour,winner,loser,w_rank,l_rank) "
                "VALUES ('m1','2025-06-01','atp','A','B',NULL,NULL)"
            )
        updated = db.backfill_match_ranks_bulk([("m1", 5, 20)])
        self.assertEqual(updated, 1)
        with db.connect() as conn:
            row = conn.execute("SELECT w_rank,l_rank FROM matches WHERE id='m1'").fetchone()
        self.assertEqual(row["w_rank"], 5)
        self.assertEqual(row["l_rank"], 20)
        # Idempotent : ne remplace pas une valeur existante
        db.backfill_match_ranks_bulk([("m1", 99, 99)])
        with db.connect() as conn:
            row = conn.execute("SELECT w_rank,l_rank FROM matches WHERE id='m1'").fetchone()
        self.assertEqual(row["w_rank"], 5)

    def test_rebuild_player_rankings_from_matches(self):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO matches (id,date,tour,winner,loser,w_rank,l_rank) "
                "VALUES ('m1','2024-01-01','atp','A','B',10,50),"
                "('m2','2025-01-01','atp','A','C',3,80)"
            )
        n = db.rebuild_player_rankings_from_matches()
        self.assertGreaterEqual(n, 3)
        ranks = db.get_all_player_rankings()
        self.assertEqual(ranks["A"], 3)  # plus récent
        self.assertEqual(ranks["B"], 50)

    def test_load_rankings_prefers_db_over_memory(self):
        db.upsert_player_ranking("Alice", "wta", 7, as_of="2025-07-01")
        mem = {"players": {"Alice": {"rank": 99}, "Bob": {"rank": 42}}}
        ranks = feat.load_rankings(mem)
        self.assertEqual(ranks["Alice"], 7.0)
        self.assertEqual(ranks["Bob"], 42.0)

    def test_ranking_diff_feature(self):
        mem = {"players": {}}
        db.upsert_player_ranking("P1", "atp", 5, as_of="2025-01-01")
        db.upsert_player_ranking("P2", "atp", 20, as_of="2025-01-01")
        ranks = feat.load_rankings(mem)
        diffs = feat.elo_diffs("P1", "P2", "hard", {}, {}, ranks)
        self.assertEqual(diffs["ranking_diff"], 15.0)  # rank2 - rank1


class TestMcpBackfillDb(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def test_mcp_bulk_overwrites_neutral_not_real(self):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO matches (id,date,tour,winner,loser,w_serve,l_serve) "
                "VALUES ('x','2025-01-01','wta','W','L',0.5,0.777)"
            )
        w_stats = {"serve": 0.66, "return1": 0.4, "return2": 0.4}
        l_stats = {"serve": 0.55, "return1": 0.35, "return2": 0.35}
        db.backfill_match_stats_mcp_bulk([("x", w_stats, l_stats)])
        with db.connect() as conn:
            row = conn.execute("SELECT w_serve,l_serve FROM matches WHERE id='x'").fetchone()
        self.assertAlmostEqual(row["w_serve"], 0.66)
        self.assertAlmostEqual(row["l_serve"], 0.777)


class TestLiveTennisParser(unittest.TestCase):
    def test_parse_live_tennis_eu_html(self):
        from bot import ranking_feeder as rf
        html = (
            '<tr class="ITA of1"><td class=rk>1</td><td class=pn>Jannik Sinner</td></tr>'
            '<tr class="GER of2"><td class=rk>2</td><td class=pn>Alexander Zverev</td></tr>'
        )
        rows = rf._parse_live_tennis_eu(html, "atp", limit=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["name"], "Jannik Sinner")


if __name__ == "__main__":
    unittest.main()
