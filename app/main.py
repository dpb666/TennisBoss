"""FastAPI entry point for the TennisBoss Quant Betting System.

Run with:
    uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

Or via run.py:
    python3 run.py quant
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api import realtime_ws, trading_routes, risk_routes, chat_routes
from app.core.engine import init_engine
from bot import realtime, realtime_alerts

# ---------------------------------------------------------------------------
# Shared application state (populated at startup)
# ---------------------------------------------------------------------------
_MEM: Dict[str, Any] = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tennisboss.quant")


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- startup -----------------------------------------------------------
    logger.info("Loading TennisBoss model state…")
    try:
        from bot import db, elo, memory as mem_mod

        db.init()
        state = mem_mod.load()
        _MEM.update(state)

        # Dynamic ELO (K=64/28/12 + dominance) from chronological DB archive
        rows = db.all_matches_chrono()
        _MEM["elo"], _ = elo.build_dynamic(rows)
        _MEM["elo_surface"] = {}
        for surf in ("hard", "clay", "grass"):
            _MEM["elo_surface"][surf], _ = elo.build_dynamic(rows, surface_key=surf)

        n_players = len(_MEM.get("players") or {})
        logger.info("Loaded %d players, ELO built.", n_players)
    except Exception as exc:
        logger.error("Failed to load model state: %s", exc)

    # Risk engine with configurable bankroll
    bankroll = float(os.environ.get("BANKROLL", "1000"))
    init_engine(bankroll)
    logger.info("Risk engine initialised — bankroll=%.2f", bankroll)

    # Real-time settlement engine + alerts
    realtime_alerts.init()
    engine = realtime.init(_MEM)
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(engine.start())
        logger.info("Real-time settlement engine started.")
    except Exception as e:
        logger.warning("Could not start async engine: %s", e)

    # Trading engines
    trading_routes.init_trading_engines()
    logger.info("Trading engines initialized.")

    # Risk engines
    risk_routes.init_risk_engines()
    logger.info("Risk engines initialized.")

    # WebSocket odds-api.io v3 — live scores + settlement instantané
    odds_key = os.environ.get("ODDS_API_KEY", "").strip()
    if odds_key:
        try:
            from bot import odds_ws, settlement
            from bot import odds_api as _odds_api

            _odds_api.clear_cache()  # purge stale ITF event IDs after v3 upgrade

            from bot import namematch as _nm

            def _resolve(name: str):
                players = _MEM.get("players") or {}
                counts = {n: int(p.get("n", 0)) for n, p in players.items()}
                idx = _nm.build_index(list(players.keys()), counts)
                return _nm.resolve(name, idx)

            # Dédup en mémoire : le settlement enregistre des clés odds_/API-Tennis,
            # jamais ws_{eid} — on ne peut donc pas dédupliquer via la DB ici.
            _ws_seen: set = set()
            _ws_last_run = [0.0]

            def _on_ws_status(msg: dict) -> None:
                if msg.get("status") != "settled":
                    return
                scores = msg.get("scores") or {}
                home_s = scores.get("home", 0)
                away_s = scores.get("away", 0)
                if home_s == away_s:
                    return
                eid = str(msg.get("id", ""))
                if not eid or eid in _ws_seen:
                    return
                _ws_seen.add(eid)
                # Throttle : run_settlement traite TOUS les settled récents d'un coup,
                # inutile de le relancer plus d'une fois toutes les 2 minutes.
                now = time.time()
                if now - _ws_last_run[0] < 120:
                    return
                _ws_last_run[0] = now
                logger.info("WS settled: event %s (%s-%s)", eid, home_s, away_s)
                try:
                    settlement.run_settlement(_MEM, _resolve, days_back=1)
                except Exception as exc:
                    logger.warning("WS settlement error for %s: %s", eid, exc)

            odds_ws.start(api_key=odds_key, on_status=_on_ws_status)
            logger.info("WebSocket odds-api.io v3 started (scores+status).")
        except Exception as exc:
            logger.warning("Could not start odds WebSocket: %s", exc)

    yield

    # ---- shutdown ----------------------------------------------------------
    from bot import odds_ws as _ows
    _ows.stop()
    logger.info("TennisBoss Quant shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title       = "TennisBoss Quant API",
    description = "Hybrid ELO + Bayesian + Feature + Transformer betting system",
    version     = "2.0.0",
    lifespan    = lifespan,
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["*"],
    allow_methods  = ["GET", "POST"],
    allow_headers  = ["*"],
)

app.include_router(router, prefix="/api/v2")
app.include_router(realtime_ws.router, prefix="/api/v2")
app.include_router(trading_routes.router)
app.include_router(risk_routes.router)
app.include_router(chat_routes.router)

# Root redirect to docs
@app.get("/", include_in_schema=False)
def root():
    return {"docs": "/docs", "version": "2.0.0", "service": "TennisBoss Quant"}
