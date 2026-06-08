"""Tests de la couche cache + rate-limit d'odds_api (sans réseau réel)."""
import time
import unittest
from unittest import mock

from bot import odds_api


class FakeResp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class TestOddsCache(unittest.TestCase):
    def setUp(self):
        odds_api.clear_cache()

    def test_cle_ignore_apikey(self):
        k1 = odds_api._cache_key("/events", {"sport": "tennis", "apiKey": "AAA"})
        k2 = odds_api._cache_key("/events", {"sport": "tennis", "apiKey": "BBB"})
        self.assertEqual(k1, k2)

    def test_cache_evite_second_appel(self):
        resp = FakeResp(200, [{"id": 1}], {"x-ratelimit-remaining": "50"})
        with mock.patch.object(odds_api.requests, "get", return_value=resp) as m:
            a = odds_api._get("/events", {"sport": "tennis", "apiKey": "k"}, ttl=60)
            b = odds_api._get("/events", {"sport": "tennis", "apiKey": "k"}, ttl=60)
        self.assertEqual(m.call_count, 1)        # 2e servi par le cache
        self.assertEqual(a, b)

    def test_budget_bas_suspend_et_sert_stale(self):
        resp = FakeResp(200, [{"id": 1}], {
            "x-ratelimit-remaining": "2",
            "x-ratelimit-reset": str(time.time() + 100),
        })
        with mock.patch.object(odds_api.requests, "get", return_value=resp) as m:
            odds_api._get("/events", {"sport": "tennis", "apiKey": "k"}, ttl=0)
            res = odds_api._get("/events", {"sport": "tennis", "apiKey": "k"}, ttl=0)
        self.assertEqual(m.call_count, 1)        # 2e appel suspendu (budget < 5)
        self.assertEqual(res, [{"id": 1}])       # stale servi

    def test_429_suspend_et_remaining_zero(self):
        resp = FakeResp(429, {}, {})
        with mock.patch.object(odds_api.requests, "get", return_value=resp):
            res = odds_api._get("/odds", {"eventId": 1, "apiKey": "k"}, ttl=60)
        self.assertIsNone(res)
        self.assertEqual(odds_api._RL["remaining"], 0)
        self.assertGreater(odds_api._RL["reset"], time.time())

    def test_rate_limit_status(self):
        odds_api._RL.update(remaining=10, reset=time.time() + 30)
        st = odds_api.rate_limit_status()
        self.assertEqual(st["remaining"], 10)
        self.assertTrue(0 <= st["reset_in_s"] <= 30)


if __name__ == "__main__":
    unittest.main()
