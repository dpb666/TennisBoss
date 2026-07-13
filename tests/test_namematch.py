"""Tests pour bot/namematch.py — résolution de noms entre sources.

Couvre le bug corrigé le 2026-07-12 : split_name("Andreeva M.") était compris
à l'envers (prénom="andreeva", nom="m") faute de détecter quel token est
l'initiale — deux joueurs identiques ingérés par des sources différentes
("Andreeva M." via tennisdata_feeder vs "Mirra Andreeva" via ESPN/Sackmann)
ne se rejoignaient jamais dans l'index, créant deux profils ELO/EMA distincts
pour la même personne.
"""
from __future__ import annotations

import unittest

from bot import namematch as nm


class TestSplitName(unittest.TestCase):
    def test_first_last_full_name(self):
        self.assertEqual(nm.split_name("Alexander Zverev"), ("a", "zverev"))

    def test_initial_dot_last_full_surname(self):
        self.assertEqual(nm.split_name("A. Zverev"), ("a", "zverev"))

    def test_surname_then_initial_tennisdata_format(self):
        # Format tennis-data.co.uk : nom de famille D'ABORD, initiale ensuite.
        self.assertEqual(nm.split_name("Andreeva M."), ("m", "andreeva"))

    def test_surname_comma_first_name(self):
        self.assertEqual(nm.split_name("Zverev, Alexander"), ("a", "zverev"))

    def test_single_token(self):
        self.assertEqual(nm.split_name("Djokovic"), ("", "djokovic"))

    def test_empty_name(self):
        self.assertEqual(nm.split_name(""), ("", ""))

    def test_two_full_names_both_multi_letter_defaults_first_last(self):
        # Aucun token d'une seule lettre -> on garde l'hypothèse "prénom nom".
        self.assertEqual(nm.split_name("Mirra Andreeva"), ("m", "andreeva"))


class TestResolveCrossFormat(unittest.TestCase):
    """Vérifie que les deux formats convergent désormais vers le même index."""

    def test_andreeva_formats_share_same_lastname_bucket(self):
        index = nm.build_index(["Mirra Andreeva", "Erika Andreeva"], {})
        # "Andreeva M." doit maintenant se résoudre vers "Mirra Andreeva"
        # (même nom de famille "andreeva", même initiale "m").
        self.assertEqual(nm.resolve("Andreeva M.", index), "Mirra Andreeva")

    def test_andreeva_e_resolves_to_erika(self):
        index = nm.build_index(["Mirra Andreeva", "Erika Andreeva"], {})
        self.assertEqual(nm.resolve("Andreeva E.", index), "Erika Andreeva")

    def test_no_false_positive_across_different_surnames(self):
        index = nm.build_index(["Mirra Andreeva"], {})
        self.assertIsNone(nm.resolve("Kostyuk M.", index))


if __name__ == "__main__":
    unittest.main()
