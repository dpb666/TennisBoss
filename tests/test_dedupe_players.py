"""Tests pour bot/dedupe_players.py — fusion des profils dupliqués par
variation de format de nom (voir bug corrigé dans bot/namematch.py).
"""
from __future__ import annotations

import datetime as _dt
import os
import tempfile
import unittest

from bot import config, db, dedupe_players as dp


class TestFindDuplicateGroups(unittest.TestCase):
    def test_groups_full_name_and_abbreviated_form(self):
        mem = {"players": {
            "Mirra Andreeva": {"n": 40},
            "Andreeva M.": {"n": 10},
            "Novak Djokovic": {"n": 50},
        }}
        safe, ambiguous = dp.find_duplicate_groups(mem)
        self.assertEqual(len(safe), 1)
        self.assertEqual(ambiguous, {})
        (names,) = safe.values()
        self.assertEqual(set(names), {"Mirra Andreeva", "Andreeva M."})

    def test_no_group_for_unique_players(self):
        mem = {"players": {"Novak Djokovic": {"n": 50}, "Rafael Nadal": {"n": 60}}}
        safe, ambiguous = dp.find_duplicate_groups(mem)
        self.assertEqual(safe, {})
        self.assertEqual(ambiguous, {})

    def test_same_surname_different_full_first_names_is_ambiguous(self):
        # Cas réel trouvé en production : trois joueuses WTA distinctes,
        # même nom de famille "Wang", même initiale "X" -> ne DOIT PAS être
        # traité comme un seul groupe fusionnable.
        mem = {"players": {
            "Xin Yu Wang": {"n": 100},
            "Xiyu Wang": {"n": 90},
            "Xiaofei Wang": {"n": 80},
        }}
        safe, ambiguous = dp.find_duplicate_groups(mem)
        self.assertEqual(safe, {})
        self.assertEqual(len(ambiguous), 1)
        (names,) = ambiguous.values()
        self.assertEqual(set(names), {"Xin Yu Wang", "Xiyu Wang", "Xiaofei Wang"})

    def test_one_full_name_plus_abbreviated_aliases_is_safe(self):
        # Une seule joueuse : un nom complet + ses variantes abrégées -> sûr.
        mem = {"players": {
            "Mirra Andreeva": {"n": 40},
            "Andreeva M.": {"n": 10},
            "M. Andreeva": {"n": 5},
        }}
        safe, ambiguous = dp.find_duplicate_groups(mem)
        self.assertEqual(ambiguous, {})
        self.assertEqual(len(safe), 1)


class TestChooseCanonical(unittest.TestCase):
    def test_prefers_full_name_even_with_lower_n(self):
        players = {"Mirra Andreeva": {"n": 10}, "Andreeva M.": {"n": 40}}
        canon = dp.choose_canonical(list(players), players)
        self.assertEqual(canon, "Mirra Andreeva")

    def test_picks_highest_n_among_full_names(self):
        players = {"Mirra Andreeva": {"n": 40}, "Andreeva Mirra": {"n": 10}}
        canon = dp.choose_canonical(list(players), players)
        self.assertEqual(canon, "Mirra Andreeva")

    def test_picks_highest_n_among_abbreviated_forms(self):
        players = {"Andreeva M.": {"n": 40}, "M. Andreeva": {"n": 10}}
        canon = dp.choose_canonical(list(players), players)
        self.assertEqual(canon, "Andreeva M.")


class TestMerge(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def _insert_match(self, date, winner, loser, surface="hard", margin=0):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO matches (id,date,tour,winner,loser,surface,margin) "
                "VALUES (?,?,?,?,?,?,?)",
                (f"m-{winner}-{loser}-{date}", date, "wta", winner, loser, surface, margin),
            )

    def test_merge_combines_n_and_removes_alias(self):
        recent = _dt.date.today().strftime("%Y-%m-%d")
        self._insert_match(recent, "Mirra Andreeva", "Coco Gauff")
        self._insert_match(recent, "Andreeva M.", "Iga Swiatek")
        mem = {"players": {
            "Mirra Andreeva": {"n": 40, "serve": 0.6, "return1": 0.5, "return2": 0.5, "recent": 0.55, "tour": "wta"},
            "Andreeva M.": {"n": 10, "serve": 0.4, "return1": 0.5, "return2": 0.5, "recent": 0.45, "tour": "wta"},
            "Coco Gauff": {"n": 5, "serve": 0.5, "return1": 0.5, "return2": 0.5, "recent": 0.5, "tour": "wta"},
            "Iga Swiatek": {"n": 5, "serve": 0.5, "return1": 0.5, "return2": 0.5, "recent": 0.5, "tour": "wta"},
        }, "weights": {}, "bias": 0.0, "metrics": {}}

        result = dp.merge(mem)

        self.assertEqual(result["merged_groups"], 1)
        self.assertNotIn("Andreeva M.", mem["players"])
        self.assertIn("Mirra Andreeva", mem["players"])
        self.assertEqual(mem["players"]["Mirra Andreeva"]["n"], 50)
        # Moyenne pondérée : (40*0.6 + 10*0.4) / 50 = 0.56
        self.assertAlmostEqual(mem["players"]["Mirra Andreeva"]["serve"], 0.56, places=6)

    def test_merge_renames_matches_table(self):
        recent = _dt.date.today().strftime("%Y-%m-%d")
        self._insert_match(recent, "Mirra Andreeva", "Coco Gauff")
        self._insert_match(recent, "Andreeva M.", "Iga Swiatek")
        mem = {"players": {
            "Mirra Andreeva": {"n": 40, "tour": "wta"},
            "Andreeva M.": {"n": 10, "tour": "wta"},
            "Coco Gauff": {"n": 5, "tour": "wta"},
            "Iga Swiatek": {"n": 5, "tour": "wta"},
        }, "weights": {}, "bias": 0.0, "metrics": {}}

        dp.merge(mem)

        with db.connect() as conn:
            rows = conn.execute(
                "SELECT winner, loser FROM matches ORDER BY id").fetchall()
        winners = {r["winner"] for r in rows}
        self.assertNotIn("Andreeva M.", winners)
        self.assertIn("Mirra Andreeva", winners)

    def test_merge_is_idempotent(self):
        recent = _dt.date.today().strftime("%Y-%m-%d")
        self._insert_match(recent, "Mirra Andreeva", "Coco Gauff")
        self._insert_match(recent, "Andreeva M.", "Iga Swiatek")
        mem = {"players": {
            "Mirra Andreeva": {"n": 40, "tour": "wta"},
            "Andreeva M.": {"n": 10, "tour": "wta"},
            "Coco Gauff": {"n": 5, "tour": "wta"},
            "Iga Swiatek": {"n": 5, "tour": "wta"},
        }, "weights": {}, "bias": 0.0, "metrics": {}}

        dp.merge(mem)
        second = dp.merge(mem)
        self.assertEqual(second["merged_groups"], 0)

    def test_merge_never_touches_ambiguous_groups(self):
        recent = _dt.date.today().strftime("%Y-%m-%d")
        self._insert_match(recent, "Xin Yu Wang", "Coco Gauff")
        self._insert_match(recent, "Xiyu Wang", "Iga Swiatek")
        mem = {"players": {
            "Xin Yu Wang": {"n": 100, "tour": "wta"},
            "Xiyu Wang": {"n": 90, "tour": "wta"},
            "Coco Gauff": {"n": 5, "tour": "wta"},
            "Iga Swiatek": {"n": 5, "tour": "wta"},
        }, "weights": {}, "bias": 0.0, "metrics": {}}

        result = dp.merge(mem)

        self.assertEqual(result["merged_groups"], 0)
        self.assertEqual(result["ambiguous_groups_skipped"], 1)
        self.assertIn("Xin Yu Wang", mem["players"])
        self.assertIn("Xiyu Wang", mem["players"])
        self.assertEqual(mem["players"]["Xin Yu Wang"]["n"], 100)
        self.assertEqual(mem["players"]["Xiyu Wang"]["n"], 90)


class TestReport(unittest.TestCase):
    def test_report_is_read_only_and_lists_details(self):
        mem = {"players": {
            "Mirra Andreeva": {"n": 40},
            "Andreeva M.": {"n": 10},
        }}
        result = dp.report(mem)
        self.assertEqual(result["duplicate_groups"], 1)
        self.assertEqual(result["players_involved"], 2)
        self.assertEqual(result["details"][0]["canonical"], "Mirra Andreeva")
        self.assertEqual(result["details"][0]["aliases"], ["Andreeva M."])
        # dry-run : mem non modifié
        self.assertIn("Andreeva M.", mem["players"])

    def test_report_separates_ambiguous_groups(self):
        mem = {"players": {
            "Xin Yu Wang": {"n": 100},
            "Xiyu Wang": {"n": 90},
            "Mirra Andreeva": {"n": 40},
            "Andreeva M.": {"n": 10},
        }}
        result = dp.report(mem)
        self.assertEqual(result["duplicate_groups"], 1)
        self.assertEqual(result["ambiguous_groups"], 1)
        self.assertEqual(result["ambiguous_details"][0]["canonical"], "Xin Yu Wang")


if __name__ == "__main__":
    unittest.main()
