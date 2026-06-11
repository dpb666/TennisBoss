# TennisBoss Advanced — Quick Start

## Launch

```bash
# Terminal 1: API Server
python3 run.py quant
# Listens on http://localhost:8001/api/v2

# Terminal 2: WebSocket Dashboard (optional)
cd app/static
python3 -m http.server 8000
# Open http://localhost:8000/realtime-dashboard.html
```

---

## Common Tasks

### 1. Analyze Match for Edge

```bash
curl -X GET "http://localhost:8001/api/v2/market-analysis?player1=Federer&player2=Nadal&odds1=1.85&odds2=1.95"
```

**Response**: Model consensus, EV spread, arbitrage opportunity

---

### 2. Place Auto-Bet

```bash
curl -X POST "http://localhost:8001/v2/trading/auto-bet" \
  -H "Content-Type: application/json" \
  -d '{
    "match_id": "m1_fed_nad",
    "player": "Federer",
    "model_prob": 0.58,
    "odds": 1.85,
    "confidence": 0.75,
    "auto_place": true
  }'
```

**Response**: Approved/Rejected, stake amount, reasoning

---

### 3. Check Portfolio Risk

```bash
curl -X GET "http://localhost:8001/v2/risk/portfolio-risk"
```

**Response**: Greeks (Delta, Vega, Theta), Drawdown status, Overall risk tier

---

### 4. Stress Test Portfolio

```bash
curl -X POST "http://localhost:8001/v2/risk/stress-test" \
  -H "Content-Type: application/json" \
  -d '{
    "positions": [
      {"stake": 100, "odds": 1.85, "model_prob": 0.58, "confidence": 0.75},
      {"stake": 150, "odds": 1.90, "model_prob": 0.60, "confidence": 0.80}
    ],
    "bankroll": 1000
  }'
```

**Response**: Max loss, best case, risk metrics, scenarios

---

### 5. Check Drawdown & Kelly Scaling

```bash
curl -X POST "http://localhost:8001/v2/risk/update-bankroll?current_bankroll=950"
```

**Response**: Drawdown %, Kelly scale factor, recovery needed

---

## Key Endpoints by Feature

### Analytics (Edge Detection)
- `GET /api/v2/market-analysis` — Full analysis (spreads + arb + consensus)
- `POST /api/v2/spread-analysis` — EV breakdown
- `POST /api/v2/arbitrage-check` — Arb opportunities
- `POST /api/v2/record-market-snapshot` — Persist market state
- `GET /api/v2/line-movement` — Historical line moves

### Trading (Automation)
- `POST /v2/trading/auto-bet` — Conditional placement
- `POST /v2/trading/dynamic-kelly` — Kelly calculation
- `GET /v2/trading/open-positions` — Portfolio summary
- `POST /v2/trading/update-position` — Live P&L
- `POST /v2/trading/hedge-calculate` — Hedge offer
- `GET /v2/trading/hedge-summary` — All hedge opportunities
- `GET /v2/trading/trading-status` — Dashboard

### Risk (Management)
- `GET /v2/risk/portfolio-greeks` — Delta, Vega, Theta
- `POST /v2/risk/update-bankroll` — Drawdown check
- `GET /v2/risk/drawdown-status` — Current status
- `POST /v2/risk/stress-test` — Full scenario analysis
- `GET /v2/risk/portfolio-risk` — Comprehensive report
- `GET /v2/risk/risk-alerts` — Active alerts
- `POST /v2/risk/correlation-check` — New position risk
- `POST /v2/risk/cluster-detection` — Find correlated clusters

---

## Configuration

### Environment Variables
```bash
export BANKROLL=5000          # Starting bankroll
export DB_PATH=bot/state.db   # Database location
```

### Thresholds (Tunable)

**Analytics**
- MIN_EV: 0.05 (5% edge minimum)
- MIN_CONFIDENCE: 0.60 (60% confidence minimum)

**Trading**
- Auto-bet Kelly max: 5% of bankroll per bet
- Hedge threshold: Any profitable opportunity

**Risk**
- Yellow drawdown: 2.5% (-2.5%)
- Orange drawdown: 5% (-5%)
- Red drawdown: 7.5% (-7.5%)
- Correlation threshold: 0.5 (50%)

---

## Testing

```bash
# All tests
python3 -m pytest tests/test_analytics.py tests/test_trading.py tests/test_risk_advanced.py -v

# By phase
python3 -m pytest tests/test_analytics.py -v       # 14 tests
python3 -m pytest tests/test_trading.py -v         # 15 tests
python3 -m pytest tests/test_risk_advanced.py -v   # 17 tests

# Result: 46 passed ✅
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   FastAPI Server                         │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  Analytics Layer (Phase 1)                              │
│  ├─ Spreads (EV, market efficiency)                    │
│  ├─ Arbitrage (multi-bookmaker)                        │
│  ├─ Sharp Money (volume + line moves)                  │
│  ├─ CLV (closing line value tracking)                  │
│  └─ Market Snapshots (SQLite persistence)             │
│                                                           │
│  Trading Layer (Phase 2)                                │
│  ├─ Auto-Bet Engine (conditional placement)            │
│  ├─ Dynamic Kelly (4-layer adjustment)                 │
│  ├─ Position Tracker (real-time P&L)                   │
│  └─ Hedge Manager (live hedge offers)                  │
│                                                           │
│  Risk Layer (Phase 3)                                   │
│  ├─ Portfolio Greeks (Delta, Vega, Theta)              │
│  ├─ Drawdown Alerts (Kelly scaling)                    │
│  ├─ Correlation Matrix (clustering)                    │
│  ├─ Volatility Normalization (surface-specific)        │
│  └─ Scenario Analysis (VaR, CVaR, stress tests)        │
│                                                           │
│  Realtime Engine (Settlement + Updates)                 │
│  └─ WebSocket broadcasts (live P&L, alerts)            │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

---

## Decision Flow

```
Match Analysis
    ↓
[Analytics] → Model prob, EV, Sharp signals
    ↓
[Trading] → Should auto-bet? → Kelly sizing → Position open
    ↓
[Live] → Position P&L updates
    ↓
[Hedging] → Hedge opportunity? → Offer/execute
    ↓
[Risk] → Check drawdown → Scale Kelly → Set alerts
    ↓
Settlement → Update ROI → Recalibrate confidence
```

---

## Monitoring

### Watch Dashboard
```bash
# Live: http://localhost:8000/realtime-dashboard.html
# Shows: ROI, settlements, P&L, alerts
```

### Check Status
```bash
curl http://localhost:8001/api/v2/trading-status
curl http://localhost:8001/v2/risk/risk-alerts
curl http://localhost:8001/v2/risk/portfolio-risk
```

### Live Logs
```bash
# API server logs appear in terminal
# Watch for: [INFO], [ERROR], [WARNING]
```

---

## Next Steps

1. **Calibrate thresholds** — Test with historical data to find optimal EV/confidence cutoffs
2. **Feed real odds** — Connect to live odds API (Odds API integration exists)
3. **Monitor CLV** — Track if model beats closing odds consistently
4. **Backtest** — Replay historical matches through all 3 phases
5. **Telegram alerts** — Wire `realtime_alerts` to send sharp signals, hedges, drawdowns

---

## Support

See `ADVANCED_BUILD.md` for full technical documentation.

**Test coverage**: 46 tests, 100% passing ✅
