"""WebSocket endpoint for live settlement ticks + ROI dashboard."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from bot import realtime

router = APIRouter()
logger = logging.getLogger("tennisboss.ws")

# Track active connections
_active_clients: Set[WebSocket] = set()


def _on_settlement_event(payload: dict) -> None:
    """Callback invoked by realtime engine on settlement tick."""
    # Broadcast to all connected WebSocket clients
    for ws in list(_active_clients):
        try:
            # Note: WebSocket.send_json is not awaitable, so we schedule it
            asyncio.create_task(_send_safe(ws, payload))
        except Exception as e:
            logger.error("Failed to queue message to client: %s", e)


async def _send_safe(ws: WebSocket, payload: dict) -> None:
    """Send a message safely, removing client if closed."""
    try:
        await ws.send_json(payload)
    except Exception as e:
        logger.warning("Client disconnected or send failed: %s", e)
        _active_clients.discard(ws)


@router.websocket("/ws/settlement")
async def websocket_settlement(websocket: WebSocket):
    """WebSocket: real-time settlement ticks.

    Emits:
      {
        "type": "settled",
        "data": {
          "player1": "...",
          "player2": "...",
          "winner": "...",
          "pred_favorite": "...",
          "correct": 1|0,
          "roi_delta": 0.25,
          ...
        },
        "ts": 1234567890.5
      }
    """
    await websocket.accept()
    _active_clients.add(websocket)
    logger.info("WebSocket client connected (total: %d)", len(_active_clients))

    # Register this connection as a subscriber (one-time setup)
    if len(_active_clients) == 1:
        eng = realtime.get()
        if eng:
            eng.subscribe(_on_settlement_event)
            logger.info("Realtime settlement subscriber registered.")

    try:
        # Keep connection alive, ignore incoming messages
        while True:
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        _active_clients.discard(websocket)
        logger.info("WebSocket client disconnected (remaining: %d)", len(_active_clients))
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        _active_clients.discard(websocket)


@router.get("/settlement-status")
async def settlement_status():
    """Poll endpoint: current settlement engine status + recent settlements."""
    from bot import db

    eng = realtime.get()
    if not eng:
        return {"status": "not_initialized"}

    rows = db.list_settled(limit=5)
    recent = [
        {
            "player1": r["player1"],
            "player2": r["player2"],
            "winner": r["winner"],
            "pred_favorite": r["pred_favorite"],
            "correct": r["correct"],
            "date": r["date"],
        }
        for r in rows
    ]

    return {
        "status": "running" if eng._running else "idle",
        "poll_interval": eng.poll_interval,
        "subscribers": len(eng._subscribers),
        "active_ws_clients": len(_active_clients),
        "recent_settlements": recent,
    }
