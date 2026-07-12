"""Tests pour bot/recommendations.py — personnalisation basée sur l'usage
du compte actuel (pas de comptes multi-utilisateurs, voir note en tête du
module : décision produit explicite de ne pas refondre l'authentification).
"""
from __future__ import annotations

import os
import tempfile
import unittest

from bot import config, db, recommendations as reco


class RecoTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)


class TestFavoritePlayers(RecoTestCase):
    def test_empty_without_history(self):
        self.assertEqual(reco.favorite_players(), [])

    def test_counts_queries_across_both_slots(self):
        for _ in range(3):
            db.log_prediction("Sinner", "Alcaraz", 0.6, "Sinner")
        db.log_prediction("Djokovic", "Sinner", 0.5, "Djokovic")
        favs = {f["player"]: f["queries"] for f in reco.favorite_players()}
        self.assertEqual(favs["Sinner"], 4)
        self.assertEqual(favs["Alcaraz"], 3)

    def test_respects_min_queries_threshold(self):
        db.log_prediction("A", "B", 0.5, "A")  # 1 requête chacun -> sous le seuil par défaut (2)
        self.assertEqual(reco.favorite_players(min_queries=2), [])

    def test_explicit_follow_takes_priority_over_query_frequency(self):
        # Djokovic n'est jamais recherché mais suivi explicitement -> doit
        # apparaître ; le signal explicite prime sur l'inférence par fréquence.
        for _ in range(5):
            db.log_prediction("Sinner", "Alcaraz", 0.6, "Sinner")
        db.follow_player("Djokovic")
        favs = {f["player"]: f["followed"] for f in reco.favorite_players()}
        self.assertTrue(favs["Djokovic"])
        self.assertFalse(favs["Sinner"])

    def test_followed_player_not_duplicated_by_frequency_signal(self):
        for _ in range(5):
            db.log_prediction("Sinner", "Alcaraz", 0.6, "Sinner")
        db.follow_player("Sinner")
        favs = [f["player"] for f in reco.favorite_players()]
        self.assertEqual(favs.count("Sinner"), 1)


class TestRiskProfile(RecoTestCase):
    def test_insufficient_with_few_picks(self):
        db.log_value_pick("2026-07-01", "A", "B", "A", 2.0, 12.0)
        result = reco.risk_profile()
        self.assertEqual(result["profile"], "insuffisant")

    def test_classifies_prudent(self):
        for i in range(6):
            db.log_value_pick(f"2026-07-0{i+1}", f"A{i}", f"B{i}", f"A{i}", 1.5, 12.0)
        result = reco.risk_profile()
        self.assertEqual(result["profile"], "prudent")

    def test_classifies_agressif(self):
        for i in range(6):
            db.log_value_pick(f"2026-07-0{i+1}", f"A{i}", f"B{i}", f"A{i}", 4.5, 12.0)
        result = reco.risk_profile()
        self.assertEqual(result["profile"], "agressif")


class TestPreferredSurfaces(RecoTestCase):
    def test_ranks_by_frequency(self):
        db.log_value_pick("2026-07-01", "A", "B", "A", 2.0, 12.0, surface="clay")
        db.log_value_pick("2026-07-02", "C", "D", "C", 2.0, 12.0, surface="clay")
        db.log_value_pick("2026-07-03", "E", "F", "E", 2.0, 12.0, surface="hard")
        surfs = reco.preferred_surfaces()
        self.assertEqual(surfs[0]["surface"], "clay")
        self.assertEqual(surfs[0]["n"], 2)


class TestScoreUpcomingMatch(unittest.TestCase):
    def test_favorite_player_boosts_score(self):
        # player1_raw/player2_raw (bruts) sont ignorés à dessein : seuls les
        # noms résolus sous "prediction" doivent matcher favorite_players().
        match = {"player1_raw": "Sinner, Jannik", "player2_raw": "Nobody",
                 "prediction": {"player1": "Sinner", "player2": "Nobody"}}
        result = reco.score_upcoming_match(match, {"Sinner"}, "équilibré", set())
        self.assertGreater(result["score"], 0)
        self.assertIn("Tu suis Sinner", result["reasons"][0])

    def test_raw_names_alone_never_match_favorites(self):
        """Bug réel corrigé : player1_raw/player2_raw ("Sinner, Jannik") ne
        matchent jamais favorite_players() (noms résolus "Jannik Sinner")."""
        match = {"player1_raw": "Sinner, Jannik", "player2_raw": "Nobody"}
        result = reco.score_upcoming_match(match, {"Sinner"}, "équilibré", set())
        self.assertEqual(result["score"], 0)

    def test_no_match_gives_zero_score(self):
        match = {"prediction": {"player1": "X", "player2": "Y", "surface": "grass"}}
        result = reco.score_upcoming_match(match, {"Sinner"}, "insuffisant", {"clay"})
        self.assertEqual(result["score"], 0)

    def test_prudent_profile_boosts_high_confidence(self):
        match = {"prediction": {"player1": "X", "player2": "Y", "confidence": 0.8}}
        result = reco.score_upcoming_match(match, set(), "prudent", set())
        self.assertGreater(result["score"], 0)


class TestDailyDigest(RecoTestCase):
    def test_cold_start_without_any_history(self):
        result = reco.daily_digest()
        self.assertTrue(result["cold_start"])
        self.assertIn("Bienvenue", result["title"])

    def test_summarizes_recent_wins_and_losses(self):
        # Historique suffisant pour sortir du cold-start (risk_profile + favs).
        for i in range(6):
            db.log_value_pick(f"2026-07-0{i+1}", f"A{i}", f"B{i}", f"A{i}", 2.0, 12.0)
        db.log_value_pick("2026-07-11", "Sinner", "Alcaraz", "Sinner", 1.9, 12.0)
        db.settle_value_pick("Sinner", "Alcaraz", "Sinner")  # gagné
        db.log_value_pick("2026-07-11", "Djokovic", "Medvedev", "Djokovic", 1.9, 12.0)
        db.settle_value_pick("Djokovic", "Medvedev", "Medvedev")  # perdu

        result = reco.daily_digest()
        self.assertFalse(result["cold_start"])
        self.assertIn("1W-1L", result["body"])

    def test_old_results_outside_window_are_excluded(self):
        for i in range(6):
            db.log_value_pick(f"2026-07-0{i+1}", f"A{i}", f"B{i}", f"A{i}", 2.0, 12.0)
        db.log_value_pick("2026-01-01", "Old1", "Old2", "Old1", 1.9, 12.0)
        db.settle_value_pick("Old1", "Old2", "Old1")
        with db.connect() as conn:
            conn.execute("UPDATE value_picks SET ts=? WHERE player1='Old1'",
                         ("2026-01-01T00:00:00",))

        result = reco.daily_digest(window_hours=24)
        self.assertNotIn("1W", result["body"])


class TestBuildRecommendations(RecoTestCase):
    def test_filters_out_zero_score_matches_and_sorts(self):
        for _ in range(3):
            db.log_prediction("Sinner", "Nobody", 0.6, "Sinner")
        matches = [
            {"prediction": {"player1": "Random1", "player2": "Random2"}},
            {"prediction": {"player1": "Sinner", "player2": "Alcaraz"}},
        ]
        result = reco.build_recommendations(matches)
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["prediction"]["player1"], "Sinner")
        self.assertIn("Sinner", result["favorite_players"])


if __name__ == "__main__":
    unittest.main()
