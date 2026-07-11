"""Tests pour bot/intelligence_layer.py (Sport Intelligence Layer Phase 1/2/3).

steam_move_signal n'avait aucun test dédié jusqu'ici (seulement testé
indirectement via /api/insight) — c'est ce qui a laissé passer un bug
(voir ci-dessous) jusqu'à ce que bot/signal_backtest.py le révèle par un
résultat aberrant (edge négatif de -16.8% au lieu d'un edge positif).
"""
from __future__ import annotations

from unittest.mock import patch

from bot import intelligence_layer


def _mv(n_snapshots=3, move_home_pct=0.0, move_away_pct=0.0,
        opening_odds_home=2.0, opening_odds_away=2.0):
    return {
        "n_snapshots": n_snapshots,
        "move_home_pct": move_home_pct, "move_away_pct": move_away_pct,
        "opening_odds_home": opening_odds_home, "opening_odds_away": opening_odds_away,
        "closing_odds_home": opening_odds_home, "closing_odds_away": opening_odds_away,
    }


class TestSteamMoveSignal:
    def test_none_without_event_id(self):
        assert intelligence_layer.steam_move_signal(None) is None

    def test_none_with_fewer_than_2_snapshots(self):
        with patch.object(intelligence_layer.db, "line_movement", return_value=_mv(n_snapshots=1)):
            assert intelligence_layer.steam_move_signal("42") is None

    def test_flags_when_odds_shorten_significantly(self):
        # move_home_pct négatif = la cote a raccourci (plus de monde parie dessus).
        with patch.object(intelligence_layer.db, "line_movement",
                          return_value=_mv(move_home_pct=-20.0, move_away_pct=5.0)):
            sig = intelligence_layer.steam_move_signal("42")
        assert sig is not None
        assert sig["side"] == "home"
        assert sig["move_pct"] == -20.0

    def test_does_not_flag_a_lengthening_odds_as_steam_move(self):
        """Bug réel corrigé : un allongement de cote (moins de monde dessus, +20%)
        est l'exact opposé d'un steam move — ne doit JAMAIS être signalé comme tel,
        même s'il dépasse le seuil en valeur absolue."""
        with patch.object(intelligence_layer.db, "line_movement",
                          return_value=_mv(move_home_pct=20.0, move_away_pct=-5.0)):
            sig = intelligence_layer.steam_move_signal("42")
        assert sig is None

    def test_none_below_threshold(self):
        with patch.object(intelligence_layer.db, "line_movement",
                          return_value=_mv(move_home_pct=-5.0, move_away_pct=3.0)):
            assert intelligence_layer.steam_move_signal("42") is None

    def test_picks_the_side_that_shortened_more_when_both_shorten(self):
        with patch.object(intelligence_layer.db, "line_movement",
                          return_value=_mv(move_home_pct=-16.0, move_away_pct=-22.0)):
            sig = intelligence_layer.steam_move_signal("42")
        assert sig["side"] == "away"
        assert sig["move_pct"] == -22.0


class TestFormSignals:
    def _mem(self, recent1, n1, recent2, n2):
        return {"players": {
            "A": {"recent": recent1, "n": n1},
            "B": {"recent": recent2, "n": n2},
        }}

    def test_no_signal_when_recent_matches_baseline(self):
        mem = self._mem(0.55, 20, 0.50, 20)
        with patch.object(intelligence_layer.db, "player_record",
                          side_effect=lambda n: {"wins": 11, "losses": 9} if n == "A" else {"wins": 10, "losses": 10}):
            assert intelligence_layer.form_signals(mem, "A", "B") == []

    def test_flags_surperformance(self):
        mem = self._mem(0.90, 20, 0.50, 20)
        with patch.object(intelligence_layer.db, "player_record",
                          side_effect=lambda n: {"wins": 10, "losses": 10} if n == "A" else {"wins": 10, "losses": 10}):
            signals = intelligence_layer.form_signals(mem, "A", "B")
        assert len(signals) == 1
        assert signals[0]["player"] == "A"
        assert signals[0]["direction"] == "surperformance"

    def test_no_signal_below_min_matches(self):
        mem = self._mem(0.90, 5, 0.50, 20)  # n=5 < FORM_SWING_MIN_MATCHES
        with patch.object(intelligence_layer.db, "player_record",
                          return_value={"wins": 10, "losses": 10}):
            assert intelligence_layer.form_signals(mem, "A", "B") == []
