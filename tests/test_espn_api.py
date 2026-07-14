"""Tests d'espn_api.fetch_upcoming — en particulier le filtre de date
(régression du bug "matchs de la veille sur le Dashboard", 2026-07-14)."""
import datetime as dt
import unittest
from unittest import mock

from bot import espn_api


def _fixture(date: str, status: str, name: str = "Player") -> dict:
    return {
        "player1": name, "player2": "Opponent",
        "tournament": "ATP Test", "round": "",
        "date": date, "time": "10:00",
        "live": status in espn_api.LIVE_STATUSES,
        "event_key": name, "is_doubles": False, "tour": "atp",
        "status": status,
    }


class TestFetchUpcomingDateFilter(unittest.TestCase):
    def setUp(self):
        self._today = dt.datetime.utcnow().strftime("%Y-%m-%d")
        self._yesterday = (dt.datetime.utcnow() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
        self._tomorrow = (dt.datetime.utcnow() + dt.timedelta(days=1)).strftime("%Y-%m-%d")

    def test_exclut_un_match_scheduled_date_hier(self):
        # Régression : un fixture ESPN marqué "scheduled" avec une date déjà
        # passée (report non reflété, retard de statut) ne doit plus jamais
        # apparaître dans "à venir" — c'était le bug live du 2026-07-14.
        fixtures = [_fixture(self._yesterday, "STATUS_SCHEDULED", "Old")]
        with mock.patch.object(espn_api, "_fetch_tour",
                                side_effect=lambda slug, tour: fixtures if tour == "atp" else []):
            out = espn_api.fetch_upcoming(days_ahead=1)
        self.assertEqual(out, [])

    def test_garde_un_match_scheduled_aujourdhui(self):
        fixtures = [_fixture(self._today, "STATUS_SCHEDULED", "Today")]
        with mock.patch.object(espn_api, "_fetch_tour",
                                side_effect=lambda slug, tour: fixtures if tour == "atp" else []):
            out = espn_api.fetch_upcoming(days_ahead=1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["player1"], "Today")

    def test_garde_un_match_scheduled_demain_dans_la_fenetre(self):
        fixtures = [_fixture(self._tomorrow, "STATUS_SCHEDULED", "Tomorrow")]
        with mock.patch.object(espn_api, "_fetch_tour",
                                side_effect=lambda slug, tour: fixtures if tour == "atp" else []):
            out = espn_api.fetch_upcoming(days_ahead=1)
        self.assertEqual(len(out), 1)

    def test_exclut_un_match_hors_fenetre_future(self):
        far = (dt.datetime.utcnow() + dt.timedelta(days=10)).strftime("%Y-%m-%d")
        fixtures = [_fixture(far, "STATUS_SCHEDULED", "TooFar")]
        with mock.patch.object(espn_api, "_fetch_tour",
                                side_effect=lambda slug, tour: fixtures if tour == "atp" else []):
            out = espn_api.fetch_upcoming(days_ahead=1)
        self.assertEqual(out, [])

    def test_mix_de_matchs_seul_aujourdhui_et_demain_passent(self):
        fixtures = [
            _fixture(self._yesterday, "STATUS_SCHEDULED", "Old"),
            _fixture(self._today, "STATUS_SCHEDULED", "Today"),
            _fixture(self._tomorrow, "STATUS_SCHEDULED", "Tomorrow"),
        ]
        with mock.patch.object(espn_api, "_fetch_tour",
                                side_effect=lambda slug, tour: fixtures if tour == "atp" else []):
            out = espn_api.fetch_upcoming(days_ahead=1)
        names = {f["player1"] for f in out}
        self.assertEqual(names, {"Today", "Tomorrow"})

    def test_ignore_un_statut_non_pertinent(self):
        fixtures = [_fixture(self._today, "STATUS_FINAL", "Done")]
        with mock.patch.object(espn_api, "_fetch_tour",
                                side_effect=lambda slug, tour: fixtures if tour == "atp" else []):
            out = espn_api.fetch_upcoming(days_ahead=1)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
