"""Tests pour bot/match_intelligence.py (TIS — Phase 12)."""
from __future__ import annotations

from unittest.mock import patch

from bot import match_intelligence


def _fake_mem():
    return {
        "players": {
            "Jannik Sinner": {
                "serve": 0.72, "return1": 0.55, "return2": 0.58,
                "recent": 0.85, "n": 321,
            },
            "Carlos Alcaraz": {
                "serve": 0.70, "return1": 0.53, "return2": 0.56,
                "recent": 0.60, "n": 280,
            },
        },
        "elo": {"Jannik Sinner": 2112.0, "Carlos Alcaraz": 2085.0},
        "elo_surface": {
            "hard": {"Jannik Sinner": 2120.0, "Carlos Alcaraz": 2090.0},
            "clay": {"Jannik Sinner": 2050.0, "Carlos Alcaraz": 2150.0},
            "grass": {"Jannik Sinner": 2100.0, "Carlos Alcaraz": 2070.0},
        },
        "weights": {"serve": 1.2, "return1": 0.8, "return2": 0.6, "recent": 0.5},
        "bias": 0.0,
        "metrics": {"accuracy": 0.644},
    }


_STABLE_RECORDS = {
    "Jannik Sinner": {"wins": 85, "losses": 15},
    "Carlos Alcaraz": {"wins": 60, "losses": 40},
}


def _patch_signals():
    return (
        patch.object(match_intelligence.intelligence_layer.db, "head_to_head", return_value=[]),
        patch.object(match_intelligence.intelligence_layer.db, "player_recent_match_count", return_value=0),
        patch.object(match_intelligence.intelligence_layer.db, "player_last_match_date", return_value=None),
        patch.object(match_intelligence.intelligence_layer.db, "player_recent_opponents", return_value=[]),
        patch.object(match_intelligence.intelligence_layer.db, "player_clutch_stats", return_value={
            "bp_saved": 0.0, "bp_faced": 0.0, "bp_converted": 0.0,
            "bp_chances": 0.0, "tb_won": 0.0, "tb_played": 0.0, "n_matches": 0.0,
        }),
        patch.object(match_intelligence.intelligence_layer.db, "player_record",
                     side_effect=lambda n: _STABLE_RECORDS[n]),
        patch.object(match_intelligence.intelligence_layer.db, "line_movement", return_value=None),
        patch.object(match_intelligence.intelligence_layer.intelligence, "stats", return_value={
            "blacklist": [], "surface_danger": [], "accuracy_drift_pts": 0.0,
        }),
    )


class TestComputeTis:
    def test_returns_score_in_range(self):
        patches = _patch_signals()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            result = match_intelligence.compute_tis(
                "Jannik Sinner", "Carlos Alcaraz", surface="hard", mem=_fake_mem(),
            )
        assert 0 <= result["tis"] <= 100
        assert result["recommendation"] in ("STRONG_BET", "VALUE_BET", "WATCH", "NO_BET")
        assert "categories" in result
        assert abs(result["categories"]["player"] + result["categories"]["surface"]
                   + result["categories"]["market"] - result["tis"]) < 0.2
        assert isinstance(result["why"], list)
        assert isinstance(result["risks"], list)
        assert 0 <= result["risk_score"] <= 100
        assert "edge_pct" in result

    def test_ev_computed_with_odds(self):
        patches = _patch_signals()
        odds = {"home_odds": 1.85, "away_odds": 2.10}
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            result = match_intelligence.compute_tis(
                "Jannik Sinner", "Carlos Alcaraz", surface="hard",
                odds_data=odds, mem=_fake_mem(),
            )
        assert result["market_odds"] is not None
        assert result["ev_pct"] != 0.0
        assert result["fair_odds"] is not None
        assert result["edge_pct"] != 0.0

    def test_strong_bet_tier_with_high_ev(self):
        patches = _patch_signals()
        odds = {"home_odds": 3.50, "away_odds": 1.40}
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            result = match_intelligence.compute_tis(
                "Jannik Sinner", "Carlos Alcaraz", surface="hard",
                odds_data=odds, mem=_fake_mem(),
            )
        if result["tis"] >= match_intelligence.TIER_STRONG_TIS and result["ev_pct"] >= 8.0:
            assert result["recommendation"] == "STRONG_BET"

    def test_surface_clay_favors_alcaraz_in_risks_or_why(self):
        patches = _patch_signals()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            result = match_intelligence.compute_tis(
                "Jannik Sinner", "Carlos Alcaraz", surface="clay", mem=_fake_mem(),
            )
        combined = " ".join(result["why"] + result["risks"]).lower()
        assert "clay" in combined or "terre" in combined or result["categories"]["surface"] != 12.5

    def test_blacklist_adds_risk(self):
        patches = _patch_signals()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
             patch.object(match_intelligence.intelligence_layer.intelligence, "stats", return_value={
                 "blacklist": ["Jannik Sinner"], "surface_danger": [], "accuracy_drift_pts": 0.0,
             }):
            result = match_intelligence.compute_tis(
                "Jannik Sinner", "Carlos Alcaraz", surface="hard", mem=_fake_mem(),
            )
        if result["favorite"] == "Jannik Sinner":
            assert any("sur-listé" in r for r in result["risks"])
            assert result["risk_score"] > 20.0


class TestApiMatchIntelligence:
    def test_endpoint_requires_players(self):
        from bot import api
        api._MEM = _fake_mem()
        api.app.testing = True
        resp = api.app.test_client().get("/api/match/intelligence?p1=Jannik+Sinner")
        assert resp.status_code == 400

    def test_endpoint_returns_tis(self):
        from bot import api
        api._MEM = _fake_mem()
        api.app.testing = True
        patches = _patch_signals()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], \
             patch.object(api.odds_api, "is_enabled", return_value=False):
            resp = api.app.test_client().get(
                "/api/match/intelligence?p1=Jannik+Sinner&p2=Carlos+Alcaraz&surface=hard"
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["player1"] == "Jannik Sinner"
        assert "tis" in data
        assert "recommendation" in data
        assert "edge_pct" in data
        assert "risk_score" in data


class TestInsightExtension:
    def test_insight_includes_match_intelligence(self):
        from bot import api
        api._MEM = _fake_mem()
        api.app.testing = True
        patches = _patch_signals()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], \
             patch.object(api.odds_api, "is_enabled", return_value=False):
            resp = api.app.test_client().get(
                "/api/insight?p1=Jannik+Sinner&p2=Carlos+Alcaraz&surface=hard"
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "match_intelligence" in data
        assert "tis" in data["match_intelligence"]
