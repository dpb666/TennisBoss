"""Tests du système ELO et de son intégration au prédicteur."""
import unittest

from bot import elo, predictor


class TestElo(unittest.TestCase):
    def test_expected_symetrique(self):
        self.assertAlmostEqual(elo.expected(1500, 1500), 0.5)
        self.assertGreater(elo.expected(1700, 1500), 0.5)
        self.assertLess(elo.expected(1300, 1500), 0.5)

    def test_match_logit_signe(self):
        self.assertGreater(elo.match_logit(1600, 1500), 0)
        self.assertAlmostEqual(elo.match_logit(1500, 1500), 0.0)
        self.assertLess(elo.match_logit(1400, 1500), 0)

    def test_build_vainqueur_constant(self):
        rows = [{"winner": "A", "loser": "B"} for _ in range(5)]
        r = elo.build_from_matches(rows)
        self.assertGreater(r["A"], 1500)
        self.assertLess(r["B"], 1500)
        self.assertGreater(r["A"], r["B"])

    def test_conservation_points(self):
        # ELO est à somme nulle : ce que A gagne, B le perd.
        rows = [{"winner": "A", "loser": "B"}]
        r = elo.build_from_matches(rows)
        self.assertAlmostEqual(r["A"] + r["B"], 3000.0, places=6)


class TestEloDansPredicteur(unittest.TestCase):
    def _mem(self, elo_ratings=None):
        return {
            "weights": {"serve": 1.0, "return1": 1.0, "return2": 1.0, "recent": 1.0},
            "bias": 0.0,
            "elo": elo_ratings or {},
        }

    def test_elo_influence_la_prediction(self):
        feat = {"serve": 0.5, "return1": 0.5, "return2": 0.5, "recent": 0.5}
        # Sans ELO : 50/50.
        r0 = predictor.predict(self._mem(), "A", feat, "B", feat)
        self.assertAlmostEqual(r0["prob1"], 50.0, places=1)
        # Avec A bien mieux noté : A favori.
        r1 = predictor.predict(self._mem({"A": 1800, "B": 1400}), "A", feat, "B", feat)
        self.assertGreater(r1["prob1"], 60.0)
        self.assertEqual(r1["favorite"], "A")

    def test_elo_logit_pondere(self):
        mem = self._mem({"A": 1600, "B": 1500})
        # contribution = ELO_BLEND * (100/400)*ln10
        self.assertGreater(predictor.elo_logit(mem, "A", "B"), 0)
        self.assertAlmostEqual(predictor.elo_logit(mem, "A", "A"), 0.0)


if __name__ == "__main__":
    unittest.main()
