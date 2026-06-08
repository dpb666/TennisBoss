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


if __name__ == "__main__":
    unittest.main()
