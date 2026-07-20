"""Background worker loops extracted from bot/api.py (strangler-fig migration).

Each module exposes ``run_loop()`` for daemon threads and testable cycle helpers.
See docs/API_DECOMPOSITION.md for migration status.
"""

from .match_refresh_worker import refresh_watchlist_once, run_loop as run_match_refresh_loop
from .inplay_settlement_worker import settle_inplay_once, run_loop as run_inplay_settlement_loop
from .clv_worker import refresh_clv_once, run_loop as run_clv_closing_loop
from .settlement_worker import SettlementDeps, run_settlement_once, run_loop as run_value_settlement_loop
from .value_scanner import ScannerDeps, get_status, run_scanner_cycle, run_loop as run_value_scanner_loop
from .telegram_worker import (
    DigestCycleState,
    handle_telegram_message,
    poll_once,
    run_digest_loop,
    run_digest_once,
    run_poll_loop,
)
from .data_refresh_worker import DataRefreshCycleState, refresh_data_once, run_loop as run_data_refresh_loop

__all__ = [
    "refresh_watchlist_once",
    "run_match_refresh_loop",
    "settle_inplay_once",
    "run_inplay_settlement_loop",
    "refresh_clv_once",
    "run_clv_closing_loop",
    "SettlementDeps",
    "run_settlement_once",
    "run_value_settlement_loop",
    "ScannerDeps",
    "get_status",
    "run_scanner_cycle",
    "run_value_scanner_loop",
    "DigestCycleState",
    "run_digest_once",
    "run_digest_loop",
    "handle_telegram_message",
    "poll_once",
    "run_poll_loop",
    "DataRefreshCycleState",
    "refresh_data_once",
    "run_data_refresh_loop",
]
