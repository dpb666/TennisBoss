"""Tests de l'auto-calibration (temperature scaling)."""
import unittest

from bot import calibrate


class Row(dict):
    """Imite une ligne sqlite (accès par clé)."""


def _row(pred_prob1, winner, player1="A"):
    return Row(pred_prob1=pred_prob1, winner=winner, player1=player1)


class TestCalibratedProb(unittest.TestCase):
    def test_k_1_inchange(self):
        self.assertAlmostEqual(calibrate.calibrated_prob(0.7, 1.0), 0.7, places=6)

    def test_k_inferieur_rapproche_de_50(self):
        # k<1 réduit la confiance.
        self.assertLess(calibrate.calibrated_prob(0.8, 0.5), 0.8)
        self.assertGreater(calibrate.calibrated_prob(0.8, 0.5), 0.5)

    def test_symetrie(self):
        self.assertAlmostEqual(calibrate.calibrated_prob(0.5, 0.3), 0.5, places=6)


class TestFitTemperature(unittest.TestCase):
    def test_pas_assez_de_donnees(self):
        fit = calibrate.fit_temperature([_row(70.0, "A")] * 3)
        self.assertFalse(fit["fitted"])
        self.assertEqual(fit["k"], 1.0)

    def test_modele_surconfiant_donne_k_inferieur_1(self):
        # Le modèle dit 90 % pour J1, mais J1 ne gagne qu'une fois sur deux.
        rows = []
        for _ in range(40):
            rows.append(_row(90.0, "A"))   # prédit J1 fort, J1 gagne
            rows.append(_row(90.0, "B"))   # prédit J1 fort, J1 perd
        fit = calibrate.fit_temperature(rows)
        self.assertTrue(fit["fitted"])
        self.assertLess(fit["k"], 0.9)                       # sur-confiant
        self.assertLess(fit["logloss_after"], fit["logloss_before"])  # amélioration

    def test_modele_bien_calibre_garde_k_proche_1(self):
        # 70 % prédit, J1 gagne ~70 % du temps.
        rows = [_row(70.0, "A") for _ in range(70)] + \
               [_row(70.0, "B") for _ in range(30)]
        fit = calibrate.fit_temperature(rows)
        self.assertTrue(fit["fitted"])
        self.assertTrue(0.8 <= fit["k"] <= 1.2)


class TestTuneBlend(unittest.TestCase):
    def test_pas_assez_de_donnees(self):
        fit = calibrate.tune_blend([(0.0, 0.0, 1.0)] * 5)
        self.assertFalse(fit["fitted"])

    def test_elo_informatif_donne_beta_positif(self):
        # ELO parfaitement prédictif, features nulles -> β > 0 optimal.
        samples = []
        for i in range(60):
            el = 1.0 if i % 2 == 0 else -1.0
            samples.append((0.0, el, 1.0 if el > 0 else 0.0))
        fit = calibrate.tune_blend(samples)
        self.assertTrue(fit["fitted"])
        self.assertGreater(fit["elo_blend"], 0.0)
        self.assertLessEqual(fit["logloss_best"], fit["logloss_no_elo"])

    def test_elo_inutile_donne_beta_nul(self):
        # ELO sans rapport avec l'issue -> β optimal proche de 0.
        samples = []
        for i in range(60):
            samples.append((0.0, 1.0 if i % 2 == 0 else -1.0, 1.0 if i % 3 == 0 else 0.0))
        fit = calibrate.tune_blend(samples)
        self.assertTrue(fit["fitted"])
        self.assertLessEqual(fit["elo_blend"], 0.5)


class TestMarketBlend(unittest.TestCase):
    def test_blend_extremes(self):
        # w=1 -> modèle pur ; w=0 -> marché pur ; entre les deux -> intermédiaire.
        self.assertAlmostEqual(calibrate.blend_probs(0.8, 0.3, 1.0), 0.8, places=6)
        self.assertAlmostEqual(calibrate.blend_probs(0.8, 0.3, 0.0), 0.3, places=6)
        mid = calibrate.blend_probs(0.8, 0.3, 0.5)
        self.assertGreater(mid, 0.3)
        self.assertLess(mid, 0.8)

    def test_blend_w_clampe(self):
        self.assertAlmostEqual(calibrate.blend_probs(0.8, 0.3, 5.0), 0.8, places=6)
        self.assertAlmostEqual(calibrate.blend_probs(0.8, 0.3, -1.0), 0.3, places=6)

    def test_marche_informatif_donne_w_faible(self):
        # Issues tirées des probas marché, modèle bruité -> w optimal ~0.
        import random
        rng = random.Random(42)
        samples = []
        for _ in range(400):
            p_mkt = rng.uniform(0.2, 0.9)
            y = 1.0 if rng.random() < p_mkt else 0.0
            p_model = min(0.95, max(0.05, p_mkt + rng.uniform(-0.35, 0.35)))
            samples.append((p_model, p_mkt, y))
        fit = calibrate.fit_market_blend(samples)
        self.assertTrue(fit["fitted"])
        self.assertLessEqual(fit["market_blend_w"], 0.35)
        self.assertLessEqual(fit["logloss_best"], fit["logloss_model"])

    def test_modele_informatif_donne_w_fort(self):
        # Issues tirées des probas modèle, marché bruité -> w optimal élevé.
        import random
        rng = random.Random(7)
        samples = []
        for _ in range(400):
            p_model = rng.uniform(0.2, 0.9)
            y = 1.0 if rng.random() < p_model else 0.0
            p_mkt = min(0.95, max(0.05, p_model + rng.uniform(-0.35, 0.35)))
            samples.append((p_model, p_mkt, y))
        fit = calibrate.fit_market_blend(samples)
        self.assertTrue(fit["fitted"])
        self.assertGreaterEqual(fit["market_blend_w"], 0.65)

    def test_pas_assez_de_donnees(self):
        fit = calibrate.fit_market_blend([(0.6, 0.5, 1.0)] * 10)
        self.assertFalse(fit["fitted"])
        self.assertIsNone(fit["market_blend_w"])


if __name__ == "__main__":
    unittest.main()
