"""WebSocket odds-api.io v3 — live scores + status en temps réel.

Canaux: odds (cotes), scores (~1s), status (match ajouté/live/settled/cancelled).
Lance un thread daemon : se reconnecte automatiquement si la connexion tombe.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, Optional

from .log import log

WS_URL = "wss://api.odds-api.io/v3/ws"
CHANNELS = "odds,scores,status"
RECONNECT_DELAY = 10  # secondes avant reconnexion

# Callbacks appelés par le thread WS (thread-safe si lecture seule sur mem)
_on_score:  Optional[Callable[[Dict[str, Any]], None]] = None
_on_status: Optional[Callable[[Dict[str, Any]], None]] = None
_on_odds:   Optional[Callable[[Dict[str, Any]], None]] = None

_ws_thread: Optional[threading.Thread] = None
_running = False


def start(
    api_key: str,
    on_score:  Optional[Callable] = None,
    on_status: Optional[Callable] = None,
    on_odds:   Optional[Callable] = None,
) -> None:
    """Démarre le thread WebSocket en arrière-plan."""
    global _on_score, _on_status, _on_odds, _ws_thread, _running
    _on_score  = on_score
    _on_status = on_status
    _on_odds   = on_odds
    _running   = True
    _ws_thread = threading.Thread(
        target=_loop, args=(api_key,), daemon=True, name="odds-ws"
    )
    _ws_thread.start()
    log("WebSocket odds-api.io démarré.", "INFO")


def stop() -> None:
    global _running
    _running = False


def _loop(api_key: str) -> None:
    import websocket as _ws_lib

    url = f"{WS_URL}?apiKey={api_key}&channels={CHANNELS}"
    while _running:
        try:
            ws = _ws_lib.WebSocket()
            ws.connect(url, timeout=30)
            log("WebSocket connecté.", "INFO")
            while _running:
                raw = ws.recv()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                _dispatch(msg)
            ws.close()
        except Exception as exc:
            if not _running:
                break
            msg = str(exc)
            if "403" in msg or "access not allowed" in msg.lower():
                log("WebSocket odds-api.io: accès refusé (plan actuel). "
                    "Mettre à jour le plan sur odds-api.io pour activer le live.", "WARN")
                break  # ne pas boucler indéfiniment sur 403
            log(f"WebSocket déconnecté ({exc}) — reconnexion dans {RECONNECT_DELAY}s", "WARN")
            time.sleep(RECONNECT_DELAY)


def _dispatch(msg: Dict[str, Any]) -> None:
    t = msg.get("type")
    try:
        if t == "score"  and _on_score:  _on_score(msg)
        elif t == "status" and _on_status: _on_status(msg)
        elif t == "odds"   and _on_odds:   _on_odds(msg)
    except Exception as exc:
        log(f"Erreur callback WS ({t}): {exc}", "WARN")
