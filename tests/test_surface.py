"""Tests de la normalisation des noms de tournois (résolution de surface)."""
import unittest

from bot import datasource


class TestNormalizeTournament(unittest.TestCase):
    def test_retire_generiques(self):
        self.assertEqual(datasource.normalize_tournament("Stuttgart Open"), ["stuttgart"])
        self.assertEqual(
            datasource.normalize_tournament("Miami Open Masters 1000"), ["miami"])

    def test_accents_et_ponctuation(self):
        toks = datasource.normalize_tournament("'s-Hertogenbosch")
        self.assertIn("hertogenbosch", toks)

    def test_vide(self):
        self.assertEqual(datasource.normalize_tournament(""), [])
        self.assertEqual(datasource.normalize_tournament("Open ATP 250"), [])


class TestIsoWeek(unittest.TestCase):
    def test_valide(self):
        self.assertEqual(datasource._iso_week("20260610"), 24)

    def test_invalide(self):
        self.assertIsNone(datasource._iso_week("bad"))
        self.assertIsNone(datasource._iso_week(""))


if __name__ == "__main__":
    unittest.main()
