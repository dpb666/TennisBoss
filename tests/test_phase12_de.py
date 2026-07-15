"""Tests Phase 12d/12e — engineer API et ml_experiments stub."""
from __future__ import annotations

from unittest.mock import patch

from bot import api, ml_experiments


def _fake_mem():
    return {
        "players": {
            "Jannik Sinner": {
                "serve": 0.72, "return1": 0.55, "return2": 0.58,
                "recent": 0.85, "n": 321, "tour": "atp",
            },
            "Carlos Alcaraz": {
                "serve": 0.70, "return1": 0.53, "return2": 0.56,
                "recent": 0.60, "n": 280, "tour": "atp",
            },
        },
        "elo": {"Jannik Sinner": 2112.0, "Carlos Alcaraz": 2085.0},
        "elo_surface": {
            "hard": {"Jannik Sinner": 2120.0, "Carlos Alcaraz": 2090.0},
        },
        "weights": {"serve": 1.2, "return1": 0.8, "return2": 0.6, "recent": 0.5},
        "bias": 0.0,
        "metrics": {"accuracy": 0.644},
    }


class TestEngineerToday:
    def test_returns_ranked_matches(self):
        api._MEM = _fake_mem()
        api.app.testing = True
        fixtures = [{
            "player1": "Jannik Sinner", "player2": "Carlos Alcaraz",
            "surface": "hard", "tournament": "Wimbledon", "date": "2099-01-01",
            "time": "14:00", "is_doubles": False,
        }]
        with patch.object(api.espn_api, "fetch_upcoming", return_value=fixtures), \
             patch.object(api.match_intelligence.intelligence_layer.db, "head_to_head", return_value=[]), \
             patch.object(api.match_intelligence.intelligence_layer.db, "player_recent_match_count", return_value=0), \
             patch.object(api.match_intelligence.intelligence_layer.db, "player_last_match_date", return_value=None), \
             patch.object(api.match_intelligence.intelligence_layer.db, "player_recent_opponents", return_value=[]), \
             patch.object(api.match_intelligence.intelligence_layer.db, "player_clutch_stats", return_value={
                 "bp_saved": 0.0, "bp_faced": 0.0, "bp_converted": 0.0,
                 "bp_chances": 0.0, "tb_won": 0.0, "tb_played": 0.0, "n_matches": 0.0,
             }), \
             patch.object(api.match_intelligence.intelligence_layer.db, "player_record",
                          return_value={"wins": 50, "losses": 50}), \
             patch.object(api.match_intelligence.intelligence_layer.db, "line_movement", return_value=None), \
             patch.object(api.match_intelligence.intelligence_layer.intelligence, "stats", return_value={
                 "blacklist": [], "surface_danger": [], "accuracy_drift_pts": 0.0,
             }):
            resp = api.app.test_client().get("/api/engineer/today?limit=5")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] >= 1
        row = data["matches"][0]
        assert "tis" in row
        assert "prediction" in row
        assert "risk_score" in row
        assert "edge_pct" in row


class TestMlExperiments:
    def test_feature_columns_defined(self):
        assert "elo_diff_norm" in ml_experiments.FEATURE_COLUMNS
        assert len(ml_experiments.SUPPORTED_MODELS) == 3

    def test_build_feature_matrix_empty(self):
        out = ml_experiments.build_feature_matrix([])
        assert out["X"] == []
        assert out["y"] is None

    def test_compare_models_empty(self):
        assert ml_experiments.compare_models([]) == []

    def test_default_model_grid(self):
        grid = ml_experiments.default_model_grid()
        assert {g.name for g in grid} == {"logistic", "random_forest", "xgboost"}
