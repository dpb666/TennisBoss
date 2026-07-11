"""Tests pour bot/sentiment.py (NewsAPI, sans réseau réel)."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from bot import sentiment


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class TestSentiment(unittest.TestCase):
    def setUp(self):
        sentiment._CACHE.clear()
        self._env_save = os.environ.get("NEWSAPI_KEY")
        os.environ["NEWSAPI_KEY"] = "test-key"

    def tearDown(self):
        if self._env_save is None:
            os.environ.pop("NEWSAPI_KEY", None)
        else:
            os.environ["NEWSAPI_KEY"] = self._env_save

    def test_is_enabled_reflects_env(self):
        self.assertTrue(sentiment.is_enabled())
        del os.environ["NEWSAPI_KEY"]
        self.assertFalse(sentiment.is_enabled())

    def test_player_sentiment_disabled_returns_none(self):
        del os.environ["NEWSAPI_KEY"]
        self.assertIsNone(sentiment.player_sentiment("Jannik Sinner"))

    def test_player_sentiment_below_min_articles_returns_none(self):
        resp = FakeResp({"articles": [{"title": "Sinner wins again", "description": ""}]})
        with mock.patch.object(sentiment.requests, "get", return_value=resp):
            self.assertIsNone(sentiment.player_sentiment("Jannik Sinner"))

    def test_player_sentiment_positive(self):
        articles = [
            {"title": "Sinner wins in dominant form", "description": "impressive victory"},
            {"title": "Sinner's comeback continues", "description": "confident display"},
        ]
        resp = FakeResp({"articles": articles})
        with mock.patch.object(sentiment.requests, "get", return_value=resp):
            result = sentiment.player_sentiment("Jannik Sinner")
        self.assertIsNotNone(result)
        self.assertEqual(result["label"], "positif")
        self.assertGreater(result["score"], 0)
        self.assertEqual(result["n_articles"], 2)

    def test_player_sentiment_negative(self):
        articles = [
            {"title": "Player injured, forced to withdraw", "description": "retirement looms"},
            {"title": "Struggling with form after defeat", "description": "controversy"},
        ]
        resp = FakeResp({"articles": articles})
        with mock.patch.object(sentiment.requests, "get", return_value=resp):
            result = sentiment.player_sentiment("Some Player")
        self.assertEqual(result["label"], "négatif")
        self.assertLess(result["score"], 0)

    def test_player_sentiment_caches_and_avoids_second_call(self):
        articles = [
            {"title": "Sinner wins", "description": "victory"},
            {"title": "Sinner triumph", "description": "champion"},
        ]
        resp = FakeResp({"articles": articles})
        with mock.patch.object(sentiment.requests, "get", return_value=resp) as m:
            sentiment.player_sentiment("Jannik Sinner")
            sentiment.player_sentiment("Jannik Sinner")
        self.assertEqual(m.call_count, 1)

    def test_player_sentiment_returns_none_on_network_error(self):
        with mock.patch.object(sentiment.requests, "get", side_effect=OSError("boom")):
            self.assertIsNone(sentiment.player_sentiment("Jannik Sinner"))


if __name__ == "__main__":
    unittest.main()
