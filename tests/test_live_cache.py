"""Tests du cache TTL d'API-Tennis (live_api) + parsing du reset rate-limit."""
import time
import unittest
from unittest import mock

from bot import live_api, odds_api


class FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


class TestLiveCache(unittest.TestCase):
    def setUp(self):
        live_api.clear_cache()

    def test_cache_evite_second_appel(self):
        resp = FakeResp({"success": 1, "result": [{"x": 1}]})
        params = {"method": "get_fixtures", "APIkey": "k",
                  "date_start": "a", "date_stop": "b"}
        with mock.patch.object(live_api.requests, "get", return_value=resp) as m:
            a = live_api._cached_request(params, ttl=60)
            b = live_api._cached_request(params, ttl=60)
        self.assertEqual(m.call_count, 1)
        self.assertEqual(a, b)

    def test_cle_ignore_apikey(self):
        resp = FakeResp({"success": 1, "result": []})
        with mock.patch.object(live_api.requests, "get", return_value=resp) as m:
            live_api._cached_request({"method": "x", "APIkey": "AAA"}, ttl=60)
            live_api._cached_request({"method": "x", "APIkey": "BBB"}, ttl=60)
        self.assertEqual(m.call_count, 1)   # clé identique malgré APIkey différent

    def test_erreur_reseau_sert_stale(self):
        ok = FakeResp({"success": 1, "result": [{"x": 1}]})
        params = {"method": "get_fixtures", "APIkey": "k"}
        with mock.patch.object(live_api.requests, "get", return_value=ok):
            live_api._cached_request(params, ttl=0)   # remplit le cache (périmé tout de suite)
        with mock.patch.object(live_api.requests, "get",
                               side_effect=live_api.requests.RequestException("boom")):
            res = live_api._cached_request(params, ttl=0)
        self.assertEqual(res, {"success": 1, "result": [{"x": 1}]})  # stale servi


class TestResetParsing(unittest.TestCase):
    def test_secondes_restantes(self):
        self.assertAlmostEqual(odds_api._parse_reset("30"), time.time() + 30, delta=2)

    def test_epoch_absolu(self):
        target = time.time() + 100
        self.assertAlmostEqual(odds_api._parse_reset(str(target)), target, delta=2)

    def test_iso_8601(self):
        v = odds_api._parse_reset("2030-01-01T00:00:00Z")
        self.assertIsNotNone(v)
        self.assertGreater(v, time.time())

    def test_invalide(self):
        self.assertIsNone(odds_api._parse_reset("nope"))


if __name__ == "__main__":
    unittest.main()
