"""Risk management layer.

Kelly criterion staking with hard limits:
- Max single bet : 2% of bankroll
- Max total exposure : 6% of bankroll
- Daily drawdown stop : −5%

All state is held by RiskEngine, which should be a singleton per server session.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent.parent / "state" / "betting_history.db"

# ---- Kelly ----------------------------------------------------------------

KELLY_FRACTION = 0.25   # quarter-Kelly for safety
MAX_BET_PCT    = 0.02   # 2% of bankroll max per bet
MAX_EXPOSURE   = 0.06   # 6% total open exposure
MAX_DRAWDOWN   = 0.05   # stop if day-P&L < −5% of starting bankroll


def kelly_fraction(prob: float, decimal_odds: float) -> float:
    """Standard Kelly: f = (b·p − q) / b  where b = odds − 1."""
    b = decimal_odds - 1.0
    if b <= 0:
        return 0.0
    q = 1.0 - prob
    k = (b * prob - q) / b
    return max(0.0, k)


def kelly_stake(
    prob: float,
    decimal_odds: float,
    bankroll: float,
    fraction: float = KELLY_FRACTION,
    max_pct: float = MAX_BET_PCT,
) -> float:
    """Fractional Kelly stake, capped at max_pct of bankroll."""
    raw = bankroll * kelly_fraction(prob, decimal_odds) * fraction
    ceiling = bankroll * max_pct
    return round(min(raw, ceiling), 2)


# ---- Risk engine -----------------------------------------------------------

class RiskEngine:
    """Stateful risk manager — tracks exposure and daily P&L."""

    def __init__(
        self,
        bankroll: float = 1000.0,
        max_bet_pct: float = MAX_BET_PCT,
        max_exposure_pct: float = MAX_EXPOSURE,
        max_drawdown: float = MAX_DRAWDOWN,
    ) -> None:
        self.bankroll        = bankroll
        self.max_bet_pct     = max_bet_pct
        self.max_exposure_pct = max_exposure_pct
        self.max_drawdown    = max_drawdown

        self._day_start_bankroll = bankroll
        self._day_pnl            = 0.0
        self._exposure           = 0.0   # sum of open stakes
        self._day_key            = self._today()
        self._init_db()

    # ---- public API --------------------------------------------------------

    def approve(
        self,
        stake: float,
        prob: float,
        odds: float,
        match: str = "",
    ) -> tuple[bool, str]:
        """Return (approved, reason).  Checks all risk limits."""
        self._maybe_reset_day()

        # 1. Drawdown check
        if self._day_pnl < -self.max_drawdown * self._day_start_bankroll:
            return False, "daily drawdown limit reached — betting suspended"

        # 2. Single bet size check
        max_single = self.bankroll * self.max_bet_pct
        if stake > max_single:
            return False, f"stake {stake:.2f} > max single {max_single:.2f}"

        # 3. Total exposure check
        if (self._exposure + stake) > self.bankroll * self.max_exposure_pct:
            return False, (f"exposure {self._exposure + stake:.2f} would exceed "
                           f"max {self.bankroll * self.max_exposure_pct:.2f}")

        self._exposure += stake
        self._log_decision(match, prob, odds, stake, approved=True)
        return True, f"approved — stake={stake:.2f} exposure={self._exposure:.2f}"

    def record_result(self, stake: float, won: bool, match: str = "") -> None:
        """Call after a bet settles to update P&L and exposure."""
        self._maybe_reset_day()
        pnl = stake * (1.0 if won else -1.0)
        self._day_pnl  += pnl
        self._exposure  = max(0.0, self._exposure - stake)
        self.bankroll  += pnl
        self._log_result(match, stake, won, pnl, self.bankroll)

    @property
    def daily_pnl(self) -> float:
        return round(self._day_pnl, 2)

    @property
    def exposure(self) -> float:
        return round(self._exposure, 2)

    @property
    def drawdown_pct(self) -> float:
        ratio = self._day_pnl / max(1.0, self._day_start_bankroll)
        return round(ratio * 100, 2)

    # ---- persistence -------------------------------------------------------

    def _init_db(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as cx:
            cx.execute("""
                CREATE TABLE IF NOT EXISTS bet_decisions (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts        REAL    NOT NULL,
                    match     TEXT,
                    prob      REAL,
                    odds      REAL,
                    stake     REAL,
                    approved  INTEGER,
                    note      TEXT
                )
            """)
            cx.execute("""
                CREATE TABLE IF NOT EXISTS bet_results (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts        REAL    NOT NULL,
                    match     TEXT,
                    stake     REAL,
                    won       INTEGER,
                    pnl       REAL,
                    bankroll  REAL
                )
            """)

    def _log_decision(self, match, prob, odds, stake, approved, note="") -> None:
        with sqlite3.connect(DB_PATH) as cx:
            cx.execute(
                "INSERT INTO bet_decisions (ts,match,prob,odds,stake,approved,note) "
                "VALUES (?,?,?,?,?,?,?)",
                (time.time(), match, prob, odds, stake, int(approved), note),
            )

    def _log_result(self, match, stake, won, pnl, bankroll) -> None:
        with sqlite3.connect(DB_PATH) as cx:
            cx.execute(
                "INSERT INTO bet_results (ts,match,stake,won,pnl,bankroll) "
                "VALUES (?,?,?,?,?,?)",
                (time.time(), match, stake, int(won), pnl, bankroll),
            )

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _today() -> str:
        import datetime
        return datetime.date.today().isoformat()

    def _maybe_reset_day(self) -> None:
        today = self._today()
        if today != self._day_key:
            self._day_key            = today
            self._day_start_bankroll = self.bankroll
            self._day_pnl            = 0.0
