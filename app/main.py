"""FastAPI entry point for the TennisBoss Quant Betting System.

Run with:
    uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

Or via run.py:
    python3 run.py quant
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.engine import init_engine

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

    yield

    # ---- shutdown ----------------------------------------------------------
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

# Root redirect to docs
@app.get("/", include_in_schema=False)
def root():
    return {"docs": "/docs", "version": "2.0.0", "service": "TennisBoss Quant"}
