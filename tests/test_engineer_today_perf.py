"""Tests perf path engineer/today — heuristique Elo + cap compute_tis."""
from __future__ import annotations

from unittest.mock import patch

from bot import api


def _fake_mem():
    return {
        "players": {
            "Player A": {"n": 100, "recent": 0.6, "tour": "atp"},
            "Player B": {"n": 100, "recent": 0.55, "tour": "atp"},
            "Player C": {"n": 100, "recent": 0.5, "tour": "atp"},
            "Player D": {"n": 100, "recent": 0.5, "tour": "atp"},
        },
        "elo": {
            "Player A": 2100.0,
            "Player B": 2050.0,
            "Player C": 1600.0,
            "Player D": 1550.0,
        },
        "elo_surface": {"hard": {"Player A": 2110.0, "Player B": 2060.0}},
        "weights": {"serve": 1.0, "return1": 0.8, "return2": 0.6, "recent": 0.5},
        "bias": 0.0,
        "metrics": {"accuracy": 0.64},
    }


class TestEngineerQuickScore:
    def test_higher_elo_ranks_above_low_elo(self):
        mem = _fake_mem()
        top = api._engineer_quick_score("Player A", "Player B", "hard", mem)
        low = api._engineer_quick_score("Player C", "Player D", "hard", mem)
        assert top > low

    def test_live_bonus(self):
        mem = _fake_mem()
        live = api._engineer_quick_score("Player C", "Player D", "hard", mem, live=True)
        sched = api._engineer_quick_score("Player C", "Player D", "hard", mem, live=False)
        assert live > sched


class TestEngineerTisCap:
    def test_compute_tis_capped_at_limit(self):
        api._MEM = _fake_mem()
        api._engineer_today_cache.clear()
        api.app.testing = True
        fixtures = [
            {
                "player1": "Player A", "player2": "Player B",
                "surface": "hard", "tournament": "Test", "date": "2099-01-01",
                "time": "14:00", "is_doubles": False,
            },
            {
                "player1": "Player C", "player2": "Player D",
                "surface": "hard", "tournament": "Test", "date": "2099-01-01",
                "time": "15:00", "is_doubles": False,
            },
        ]
        calls = []

        def _fake_tis(n1, n2, **kwargs):
            calls.append((n1, n2))
            return {
                "tis": 70.0 if n1 == "Player A" else 50.0,
                "favorite": n1,
                "confidence": 60.0,
                "confidence_label": "medium",
                "edge_pct": 0.0,
                "ev_pct": 0.0,
                "risk_score": 10.0,
                "recommendation": "WATCH",
                "fair_odds": 1.5,
                "market_odds": None,
                "surface": "hard",
            }

        with patch.object(api, "_ENGINEER_TIS_LIMIT", 1), \
             patch.object(api.espn_api, "fetch_upcoming", return_value=fixtures), \
             patch.object(api.match_intelligence, "compute_tis", side_effect=_fake_tis), \
             patch.object(api.intelligence_layer, "intel_batch", side_effect=lambda *a, **k: _NullCtx()):
            resp = api.app.test_client().get("/api/engineer/today?limit=5")

        assert resp.status_code == 200
        assert len(calls) == 1  # top Elo pair only (A vs B), not C vs D


class _NullCtx:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False
