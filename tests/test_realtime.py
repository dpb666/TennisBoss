"""Tests for the real-time settlement engine."""
import asyncio
import os
import tempfile

import pytest
from bot import config, realtime, db, memory
from bot.realtime import RealtimeSettlementEngine


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    """Isole chaque test sur une DB SQLite temporaire.

    Sans ceci, test_roi_calculation écrivait un faux pari ("Player A" vs
    "Player B") directement dans le bet_log de PRODUCTION (state/tennisboss.db)
    à chaque exécution — et le test plantait sur un checkout propre (pas de
    state/ local, donc "no such table: bet_log"). Même pattern que
    test_settlement.py::TestCalibrationMetrics.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    monkeypatch.setattr(config, "DB_FILE", path)
    db.init()
    yield
    os.close(fd)
    os.remove(path)


@pytest.fixture
def mem():
    """Load test memory state."""
    return memory.load()


def test_engine_init(mem):
    """Engine initializes with correct state."""
    engine = RealtimeSettlementEngine(mem, poll_interval=10)
    assert engine.poll_interval == 10
    assert engine._running is False
    assert len(engine._subscribers) == 0


def test_subscribers(mem):
    """Subscribers can register and be notified."""
    engine = RealtimeSettlementEngine(mem)
    events = []
    engine.subscribe(lambda e: events.append(e))

    # Manually emit
    engine._emit("test", {"data": "test"})

    assert len(events) == 1
    assert events[0]["type"] == "test"


@pytest.mark.asyncio
async def test_engine_lifecycle(mem):
    """Engine can start and stop gracefully."""
    engine = RealtimeSettlementEngine(mem, poll_interval=1)

    # Start
    await engine.start()
    assert engine._running is True
    assert engine._task is not None

    # Let it run for a moment
    await asyncio.sleep(0.5)

    # Stop
    await engine.stop()
    assert engine._running is False


def test_roi_calculation(mem):
    """ROI delta calculation is correct."""
    engine = RealtimeSettlementEngine(mem)

    # Insert a test bet
    db.insert_bet({
        "player1": "Player A",
        "player2": "Player B",
        "favorite": "Player A",
        "fav_odds": 2.5,
        "dog_odds": 1.5,
    })

    # Test win
    result_win = {
        "player1": "Player A",
        "player2": "Player B",
        "winner": "Player A",
        "pred_favorite": "Player A",
    }
    delta = engine._compute_roi_delta(result_win)
    assert delta == 1.5  # 2.5 - 1.0

    # Test loss
    result_loss = {
        "player1": "Player A",
        "player2": "Player B",
        "winner": "Player B",
        "pred_favorite": "Player A",
    }
    delta = engine._compute_roi_delta(result_loss)
    assert delta == -1.0


def test_name_resolution(mem):
    """Name resolver works with known players."""
    engine = RealtimeSettlementEngine(mem)

    # If a known player is in the index
    known_players = list(mem.get("players", {}).keys())
    if known_players:
        resolved = engine.resolve(known_players[0])
        assert resolved == known_players[0] or resolved is None
