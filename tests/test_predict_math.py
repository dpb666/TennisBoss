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

    def test_total_sets_over_egal_third_set_prob(self):
        bb = api._bet_builder(0.6, "A", "B")
        self.assertAlmostEqual(bb["total_sets"]["prob_over"], bb["third_set_prob"], places=1)
        self.assertAlmostEqual(
            bb["total_sets"]["prob_over"] + bb["total_sets"]["prob_under"], 100.0, places=1)

    def test_handicap_droit_sets_coherent(self):
        bb = api._bet_builder(0.7, "A", "B")
        self.assertAlmostEqual(bb["handicap"]["prob1"], round(0.7 * 0.7 * 100, 1), places=1)
        self.assertAlmostEqual(bb["handicap"]["prob2"], round(0.3 * 0.3 * 100, 1), places=1)

    def test_fair_odds_sont_inverse_proba(self):
        bb = api._bet_builder(0.65, "A", "B")
        p1 = bb["match"]["prob1"] / 100.0
        self.assertAlmostEqual(bb["match"]["fair_odds1"], round(1.0 / p1, 2), places=2)

    def test_match_odds_ajoute_ev(self):
        bb = api._bet_builder(0.65, "A", "B", match_odds=(1.8, 2.2))
        self.assertIn("ev1", bb["match"])
        self.assertIn("ev2", bb["match"])
        p1 = bb["match"]["prob1"] / 100.0
        self.assertAlmostEqual(bb["match"]["ev1"], (p1 * 1.8 - 1.0) * 100, delta=0.2)

    def test_sans_match_odds_pas_de_ev(self):
        bb = api._bet_builder(0.65, "A", "B")
        self.assertNotIn("ev1", bb["match"])

    def test_best_market_est_un_marche_connu(self):
        bb = api._bet_builder(0.9, "A", "B")
        self.assertIn(bb["best_market"], ("match", "set2", "total_sets", "handicap"))
        # Écart extrême (0.9) -> le marché dominant doit être très confiant.
        self.assertGreater(bb["best_market_confidence"], 80.0)

    def test_retro_compat_cles_existantes_preservees(self):
        # Les clés déjà consommées par UpcomingScreen/PredictScreen doivent
        # rester présentes avec la même signification après l'extension.
        bb = api._bet_builder(0.6, "A", "B")
        self.assertIn("prob1", bb["match"])
        self.assertIn("prob2", bb["match"])
        self.assertIn("prob1", bb["set2"])
        self.assertIn("third_set_prob", bb)
        self.assertIn("correct_score", bb)


class TestBetBuilderLeg(unittest.TestCase):
    def setUp(self):
        api._MEM = {
            "players": {
                "Jannik Sinner": {"serve": 0.72, "return1": 0.55, "return2": 0.58, "recent": 1.0, "n": 321, "tour": "atp"},
                "Carlos Alcaraz": {"serve": 0.70, "return1": 0.53, "return2": 0.56, "recent": 0.95, "n": 280, "tour": "atp"},
            },
            "elo": {"Jannik Sinner": 2112.0, "Carlos Alcaraz": 2085.0},
            "elo_surface": {}, "elo_blend": 0.4,
            "weights": {"serve": 1.2, "return1": 0.8, "return2": 0.6, "recent": 0.5},
            "bias": 0.0, "metrics": {}, "datasets_loaded": [],
        }

    def test_replays_prediction_and_bet_builder(self):
        n1, n2, bb = api._bet_builder_leg("Jannik Sinner", "Carlos Alcaraz")
        self.assertEqual(n1, "Jannik Sinner")
        self.assertEqual(n2, "Carlos Alcaraz")
        self.assertIn("match", bb)
        self.assertIn("best_market", bb)


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
