"""Tests de la logique de prédiction (probas set/match, Bet Builder, explicabilité).

Ces fonctions sont le cœur de TennisBoss : on vérifie qu'elles sont cohérentes
(probabilités qui somment à 1, décomposition exacte du modèle, etc.).

Lancement :  python3 -m unittest discover -s tests -v
"""
import unittest

import bot.api as api
from bot import predictor


class TestSetToMatchProb(unittest.TestCase):
    def test_bornes(self):
        self.assertAlmostEqual(api._set_to_match_prob(0.0), 0.0)
        self.assertAlmostEqual(api._set_to_match_prob(1.0), 1.0)
        self.assertAlmostEqual(api._set_to_match_prob(0.5), 0.5)

    def test_somme_a_un(self):
        # P(match J1) + P(match J2) doit toujours valoir 1.
        for p in (0.3, 0.5, 0.66, 0.8, 0.95):
            self.assertAlmostEqual(
                api._set_to_match_prob(p) + api._set_to_match_prob(1 - p), 1.0, places=9)

    def test_amplification(self):
        # Le best-of-3 amplifie : un favori au set l'est davantage au match.
        for p in (0.55, 0.6, 0.7, 0.9):
            self.assertGreater(api._set_to_match_prob(p), p)

    def test_monotone(self):
        vals = [api._set_to_match_prob(p / 10) for p in range(11)]
        self.assertEqual(vals, sorted(vals))

    def test_clamp(self):
        self.assertAlmostEqual(api._set_to_match_prob(1.5), 1.0)
        self.assertAlmostEqual(api._set_to_match_prob(-0.5), 0.0)


class TestBetBuilder(unittest.TestCase):
    def test_score_exact_somme_100(self):
        # Les 4 issues couvrent tout l'espace : somme ~100 % (tolérance d'arrondi,
        # chaque valeur étant arrondie à 0,1 indépendamment).
        for p in (0.3, 0.5, 0.66, 0.8):
            bb = api._bet_builder(p, "A", "B")
            self.assertAlmostEqual(sum(bb["correct_score"].values()), 100.0, delta=0.3)

    def test_match_coherent_avec_set(self):
        bb = api._bet_builder(0.7, "A", "B")
        attendu = round(api._set_to_match_prob(0.7) * 100, 1)
        self.assertAlmostEqual(bb["match"]["prob1"], attendu, places=1)
        self.assertAlmostEqual(bb["match"]["prob1"] + bb["match"]["prob2"], 100.0, places=1)

    def test_2e_set_egal_au_set(self):
        bb = api._bet_builder(0.65, "A", "B")
        self.assertAlmostEqual(bb["set2"]["prob1"], 65.0, places=1)

    def test_troisieme_set(self):
        # P(match en 3 sets) = 2*p*(1-p).
        bb = api._bet_builder(0.6, "A", "B")
        self.assertAlmostEqual(bb["third_set_prob"], round(2 * 0.6 * 0.4 * 100, 1), places=1)

    def test_cles_score_nominatives(self):
        bb = api._bet_builder(0.6, "Sinner", "Alcaraz")
        for k in ("Sinner 2-0", "Sinner 2-1", "Alcaraz 2-1", "Alcaraz 2-0"):
            self.assertIn(k, bb["correct_score"])


class TestExplain(unittest.TestCase):
    def setUp(self):
        # Mémoire factice : poids/biais/métriques connus.
        self._save = api._MEM
        api._MEM = {
            "weights": {"serve": 2.0, "return1": -0.5, "return2": 1.0, "recent": 1.5},
            "bias": 0.1,
            "metrics": {"accuracy": 0.6},
        }

    def tearDown(self):
        api._MEM = self._save

    def test_decomposition_exacte(self):
        # Somme des contributions + biais == logit (décomposition exacte).
        f1 = {"serve": 0.7, "return1": 0.4, "return2": 0.6, "recent": 0.9}
        f2 = {"serve": 0.6, "return1": 0.5, "return2": 0.5, "recent": 0.5}
        ex = api._explain("A", f1, "B", f2)
        somme = sum(f["contribution"] for f in ex["factors"]) + ex["bias"]
        self.assertAlmostEqual(somme, ex["logit"], places=3)

    def test_facteur_decisif(self):
        f1 = {"serve": 0.7, "return1": 0.4, "return2": 0.6, "recent": 0.99}
        f2 = {"serve": 0.6, "return1": 0.5, "return2": 0.5, "recent": 0.5}
        ex = api._explain("A", f1, "B", f2)
        decisif = max(ex["factors"], key=lambda x: abs(x["contribution"]))
        self.assertEqual(ex["decisive"], decisif["key"])

    def test_favors_signe(self):
        f1 = {"serve": 0.9, "return1": 0.5, "return2": 0.5, "recent": 0.5}
        f2 = {"serve": 0.5, "return1": 0.5, "return2": 0.5, "recent": 0.5}
        ex = api._explain("A", f1, "B", f2)
        serve = next(f for f in ex["factors"] if f["key"] == "serve")
        # serve poids>0 et f1>f2 -> contribution>0 -> favorise A.
        self.assertEqual(serve["favors"], "A")


class TestFmtDate(unittest.TestCase):
    def test_format(self):
        self.assertEqual(api._fmt_date("20241124"), "24/11/2024")

    def test_tolerant(self):
        self.assertEqual(api._fmt_date("bizarre"), "bizarre")


class TestPredictorProbability(unittest.TestCase):
    def test_somme_a_un(self):
        w = {"serve": 1.0, "return1": 1.0, "return2": 1.0, "recent": 1.0}
        f1 = {"serve": 0.7, "return1": 0.6, "return2": 0.5, "recent": 0.8}
        f2 = {"serve": 0.5, "return1": 0.5, "return2": 0.5, "recent": 0.5}
        p1, p2, _, _ = predictor.probability(w, 0.0, f1, f2)
        self.assertAlmostEqual(p1 + p2, 1.0, places=9)

    def test_symetrie(self):
        w = {"serve": 1.0, "return1": 1.0, "return2": 1.0, "recent": 1.0}
        f = {"serve": 0.6, "return1": 0.6, "return2": 0.6, "recent": 0.6}
        p1, p2, _, _ = predictor.probability(w, 0.0, f, f)
        self.assertAlmostEqual(p1, 0.5, places=9)


class TestConfidence(unittest.TestCase):
    def _mem(self, n1=0, n2=0):
        return {
            "weights": {"serve": 1.0, "return1": 1.0, "return2": 1.0, "recent": 1.0},
            "bias": 0.0,
            "players": {"A": {"n": n1}, "B": {"n": n2}},
        }

    def test_borne_entre_0_et_1(self):
        for n in (0, 5, 30, 100):
            c = predictor.confidence_score(self._mem(n, n), "A", "B", z=1.0)
            self.assertGreaterEqual(c, 0.0)
            self.assertLessEqual(c, 1.0)

    def test_plus_de_matchs_plus_confiant(self):
        c_peu = predictor.confidence_score(self._mem(2, 2), "A", "B", z=0.5)
        c_bcp = predictor.confidence_score(self._mem(30, 30), "A", "B", z=0.5)
        self.assertGreater(c_bcp, c_peu)

    def test_grand_z_augmente_confiance(self):
        mem = self._mem(10, 10)
        c_proche = predictor.confidence_score(mem, "A", "B", z=0.1)
        c_tranché = predictor.confidence_score(mem, "A", "B", z=2.5)
        self.assertGreater(c_tranché, c_proche)

    def test_labels(self):
        self.assertEqual(predictor.confidence_label(0.2), "faible")
        self.assertEqual(predictor.confidence_label(0.5), "modérée")
        self.assertEqual(predictor.confidence_label(0.7), "bonne")
        self.assertEqual(predictor.confidence_label(0.9), "élevée")


if __name__ == "__main__":
    unittest.main()
