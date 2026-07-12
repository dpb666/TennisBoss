"""Tests pour le rapport de backtest consolidé (bot/backtest_report.py) et le
fix de tri chronologique sur matches.date (formats mixtes).

DB SQLite temporaire réelle : le cœur du sujet est justement le comportement
SQL (ORDER BY REPLACE(date,'-','')) qu'un mock masquerait.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from bot import backtest_report, config, db


class ReportTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def _insert_match(self, mid: str, date: str, winner: str, loser: str,
                      w_serve: float = 0.65, l_serve: float = 0.55):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO matches (id,date,tour,winner,loser,w_serve,w_return1,"
                "w_return2,l_serve,l_return1,l_return2,surface,margin) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, date, "atp", winner, loser, w_serve, 0.5, 0.5,
                 l_serve, 0.5, 0.5, "hard", 2),
            )


class TestChronoOrderMixedFormats(ReportTestCase):
    """Le bug corrigé : en tri lexicographique brut, '2022-...' (tiret) passe
    AVANT '2021...' (chiffre) — l'ordre chronologique était faux dès qu'une
    ligne tennis-data (avec tirets) croisait une ligne Sackmann (compacte)."""

    def test_matches_for_backtest_orders_mixed_formats_chronologically(self):
        self._insert_match("m1", "2022-06-15", "Alice", "Bob")   # tennis-data
        self._insert_match("m2", "20210110", "Carol", "Dan")     # Sackmann, PLUS ANCIEN
        self._insert_match("m3", "20230505", "Eve", "Frank")     # Sackmann, PLUS RÉCENT
        rows = db.matches_for_backtest()
        self.assertEqual([m["id"] for m in rows], ["m2", "m1", "m3"])

    def test_all_matches_chrono_orders_mixed_formats(self):
        self._insert_match("m1", "2022-06-15", "Alice", "Bob")
        self._insert_match("m2", "20210110", "Carol", "Dan")
        rows = db.all_matches_chrono()
        self.assertEqual(rows[0]["winner"], "Carol")  # 2021 avant 2022

    def test_player_recent_matches_most_recent_first_mixed_formats(self):
        self._insert_match("m1", "20210110", "Alice", "Bob")
        self._insert_match("m2", "2023-06-15", "Alice", "Carol")  # plus récent, avec tirets
        rows = db.player_recent_matches("Alice", limit=5)
        self.assertEqual(rows[0]["loser"], "Carol")

    def test_head_to_head_most_recent_first_mixed_formats(self):
        self._insert_match("m1", "20200110", "Alice", "Bob")
        self._insert_match("m2", "2024-03-01", "Bob", "Alice")
        rows = db.head_to_head("Alice", "Bob")
        self.assertEqual(rows[0]["winner"], "Bob")

    def test_matches_for_backtest_reconstructs_learner_format(self):
        self._insert_match("m1", "20210110", "Alice", "Bob", w_serve=0.7, l_serve=0.4)
        m = db.matches_for_backtest()[0]
        self.assertEqual(m["winner_name"], "Alice")
        self.assertEqual(m["loser_name"], "Bob")
        self.assertEqual(m["winner"]["serve"], 0.7)
        self.assertEqual(m["loser"]["serve"], 0.4)
        self.assertEqual(m["surface"], "hard")


class TestHistoricalOddsIndex(ReportTestCase):
    def test_index_normalizes_dashed_dates(self):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO historical_odds (match_id,date,tour,winner,loser,"
                "surface,psw,psl,avgw,avgl) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("h1", "2023-05-05", "atp", "Alice", "Bob", "hard",
                 1.5, 2.6, 1.55, 2.45),
            )
        idx = db.historical_odds_index()
        self.assertIn(("20230505", "Alice", "Bob"), idx)
        self.assertEqual(idx[("20230505", "Alice", "Bob")]["avgw"], 1.55)


class TestReportBuildingBlocks(unittest.TestCase):
    def test_reliability_bins_symmetric_orientations(self):
        # Un match prédit à 0.8 -> un point (0.8, 1) et un point (0.2, 0).
        details = [{"date": "20240101", "winner": "A", "loser": "B", "p_elo": 0.8}]
        bins = backtest_report._reliability_bins(details)
        b_high = next(b for b in bins if b["range"] == "0.8–0.9")
        b_low = next(b for b in bins if b["range"] == "0.2–0.3")
        self.assertEqual(b_high["n"], 1)
        self.assertEqual(b_high["observed_rate"], 1.0)
        self.assertEqual(b_low["n"], 1)
        self.assertEqual(b_low["observed_rate"], 0.0)

    def test_theoretical_roi_flat_stake(self):
        details = [
            # Favori modèle = vainqueur réel : gagne avgw-1 = 0.55
            {"date": "20240101", "winner": "A", "loser": "B", "p_elo": 0.7},
            # Favori modèle = perdant réel (p<0.5) : perd la mise
            {"date": "2024-01-02", "winner": "C", "loser": "D", "p_elo": 0.3},
            # Pas de cotes en base : ignoré
            {"date": "20240103", "winner": "E", "loser": "F", "p_elo": 0.9},
        ]
        odds_index = {
            ("20240101", "A", "B"): {"avgw": 1.55, "avgl": 2.45, "psw": None, "psl": None},
            ("20240102", "C", "D"): {"avgw": 2.0, "avgl": 1.8, "psw": None, "psl": None},
        }
        roi = backtest_report._theoretical_roi(details, odds_index)
        m = roi["marché_moyen"]
        self.assertEqual(m["n_bets"], 2)
        self.assertAlmostEqual(m["pnl_flat"], 0.55 - 1.0, places=2)
        # Les DEUX paris sont "confiants" : p=0.7 sur le vainqueur, et p=0.3
        # équivaut à 70% de confiance sur le perdant (pari perdu, -1u).
        self.assertEqual(m["n_bets_confiants"], 2)
        self.assertAlmostEqual(m["roi_confiants_pct"], -22.5, places=1)
        # Aucune cote Pinnacle -> aucun pari réglé côté pinnacle.
        self.assertEqual(roi["pinnacle"]["n_bets"], 0)

    def test_render_html_is_self_contained(self):
        report = {
            "generated": "2026-07-12T00:00:00",
            "n_matches_archive": 100,
            "core": {"span": "20200101..20260101", "tours": "atp", "n_train": 75,
                     "n_test": 25, "accuracy": 0.62, "accuracy_elo": 0.66,
                     "baseline": 0.58, "logloss": 0.65, "logloss_elo": 0.61,
                     "brier": 0.23, "brier_elo": 0.21, "id": 7},
            "calibration_bins": backtest_report._reliability_bins(
                [{"date": "20240101", "winner": "A", "loser": "B", "p_elo": 0.8}]),
            "roi_theorique": {"marché_moyen": {"n_bets": 0, "pnl_flat": 0.0,
                                               "roi_pct": None,
                                               "n_bets_confiants": 0,
                                               "roi_confiants_pct": None}},
            "signals": {"calibration": {"fitted": False, "note": "pas assez de data"},
                        "form_signal": {"verdict": "ok", "caveat": "brut"},
                        "steam_move": {"n_with_move": 0, "note": "aucun"}},
            "production": {"value_picks": {"n": 0}, "inplay": {"n": 0},
                           "clv": {"verdict_label": "📊 pas assez de data"}},
        }
        html = backtest_report.render_html(report)
        self.assertIn("<!doctype html>", html)
        self.assertIn("Rapport de backtest", html)
        self.assertIn("<svg", html)                       # courbe inline, pas de CDN
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
        self.assertIn("0.66", html)                       # accuracy+ELO affichée
        self.assertIn("Aucun pari automatique", html)


class TestGenerateEndToEnd(ReportTestCase):
    def test_generate_writes_html_from_archive(self):
        # 80 matchs : assez pour bt.run (min 50), alternance de vainqueurs.
        for i in range(80):
            date = f"2024{(i % 12) + 1:02d}{(i % 27) + 1:02d}"
            self._insert_match(f"m{i}", date, f"P{i % 8}", f"P{(i % 8) + 8}")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(backtest_report, "bootstrap",
                             return_value=dict(config.DEFAULT_CONFIG)):
            path, report = backtest_report.generate(output_dir=tmp)
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as fh:
                html = fh.read()
        self.assertIn("Rapport de backtest", html)
        self.assertEqual(report["n_matches_archive"], 80)
        self.assertIsNotNone(report["core"]["accuracy_elo"])
        self.assertEqual(len(report["calibration_bins"]), 10)


if __name__ == "__main__":
    unittest.main()
