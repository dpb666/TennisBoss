"""Tests de live_api._fetch_upcoming_oddsapi — filtre de date sur les
fixtures odds-api.io (régression du bug "matchs de la veille sur le
Dashboard", 2026-07-14 : le paramètre `date=` envoyé à odds-api.io ne
garantit pas que l'event retourné a bien cette date une fois son propre
commence_time reparsé côté client)."""
import datetime as dt
import unittest
from unittest import mock

from bot import live_api
from bot import odds_api


def _event(commence_time: str, status: str = "upcoming",
           home: str = "Player A", away: str = "Player B") -> dict:
    return {
        "id": f"{home}-{away}", "home": home, "away": away,
        "league": {"name": "ATP Test", "slug": "atp-test"},
        "date": commence_time, "status": status,
    }


class TestFetchUpcomingOddsapiDateFilter(unittest.TestCase):
    def setUp(self):
        self._today = dt.date.today()

    def test_exclut_un_event_dont_le_commence_time_reparse_tombe_hier(self):
        # Régression : la requête demande date=aujourd'hui, mais l'API répond
        # avec un event dont le commence_time réel correspond à hier une fois
        # reparsé (le paramètre `date` d'odds-api.io n'est pas fiable comme
        # seule source de vérité). C'était le bug live du 2026-07-14.
        yesterday_dt = (dt.datetime.combine(self._today, dt.time(10, 0))
                         - dt.timedelta(days=1))
        ev = _event(yesterday_dt.isoformat() + "Z", home="Old")

        with mock.patch.object(odds_api, "is_enabled", return_value=True), \
             mock.patch.object(odds_api, "_get",
                                side_effect=lambda path, params, ttl:
                                    [] if params.get("status") == "live" else [ev]):
            out = live_api._fetch_upcoming_oddsapi(days_ahead=1)

        self.assertEqual(out, [])

    def test_garde_un_event_date_aujourdhui(self):
        today_dt = dt.datetime.combine(self._today, dt.time(10, 0))
        ev = _event(today_dt.isoformat() + "Z", home="Today")

        with mock.patch.object(odds_api, "is_enabled", return_value=True), \
             mock.patch.object(odds_api, "_get",
                                side_effect=lambda path, params, ttl:
                                    [] if params.get("status") == "live" else [ev]):
            out = live_api._fetch_upcoming_oddsapi(days_ahead=1)

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["player1"], "Today")

    def test_garde_un_event_live_meme_si_date_hier(self):
        # Un match commencé hier mais toujours live est légitime — le filtre
        # de date ne doit s'appliquer qu'au flux "à venir", pas au flux "live".
        yesterday_dt = (dt.datetime.combine(self._today, dt.time(23, 0))
                         - dt.timedelta(days=1))
        ev = _event(yesterday_dt.isoformat() + "Z", home="StillLive")

        with mock.patch.object(odds_api, "is_enabled", return_value=True), \
             mock.patch.object(odds_api, "_get",
                                side_effect=lambda path, params, ttl:
                                    [ev] if params.get("status") == "live" else []):
            out = live_api._fetch_upcoming_oddsapi(days_ahead=1)

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["player1"], "StillLive")
        self.assertTrue(out[0]["live"])

    def test_exclut_settled_et_canceled(self):
        today_dt = dt.datetime.combine(self._today, dt.time(10, 0))
        settled = _event(today_dt.isoformat() + "Z", status="settled", home="Settled")
        canceled = _event(today_dt.isoformat() + "Z", status="canceled", home="Canceled")

        with mock.patch.object(odds_api, "is_enabled", return_value=True), \
             mock.patch.object(odds_api, "_get",
                                side_effect=lambda path, params, ttl:
                                    [] if params.get("status") == "live" else [settled, canceled]):
            out = live_api._fetch_upcoming_oddsapi(days_ahead=1)

        self.assertEqual(out, [])

    def test_renvoie_vide_si_odds_api_desactive(self):
        with mock.patch.object(odds_api, "is_enabled", return_value=False):
            out = live_api._fetch_upcoming_oddsapi(days_ahead=1)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
