# API decomposition — worker extraction log

**Blueprint:** `docs/ARCHITECTURE_BLUEPRINT.md` §5.1 / §5.3, roadmap item #4 (Q3 2026)  
**Approach:** Strangler fig — extract one daemon at a time; keep shims in `bot/api.py`.

---

## Migration status

| Worker | Source (api.py) | Target module | Status | Lines removed from api.py |
|--------|-----------------|---------------|--------|---------------------------|
| Watchlist odds refresh | `_followed_matches_refresh_loop` | `bot/workers/match_refresh_worker.py` | **Done** (2026-07-16) | ~55 |
| Inplay settlement | `_inplay_settle_loop` | `bot/workers/inplay_settlement_worker.py` | **Done** (2026-07-16) | ~30 |
| CLV closing + live settle | `_clv_closing_loop` | `bot/workers/clv_worker.py` | **Done** (2026-07-16) | ~95 |
| Value picks settlement | `_settlement_loop` | `bot/workers/settlement_worker.py` | **Done** (2026-07-16) | ~65 |
| Value scanner | `_value_scanner_loop` + `_SCANNER_STATE` | `bot/workers/value_scanner.py` | **Done** (2026-07-16) | ~320 |
| Telegram digest | `_digest_loop` | `bot/workers/telegram_worker.py` | **Done** (2026-07-16) | ~43 |
| Telegram poll | `_tg_poll_loop` | `bot/workers/telegram_worker.py` | **Done** (2026-07-16) | ~103 |
| Data refresh | `_data_refresh_loop` | `bot/workers/data_refresh_worker.py` | **Done** (2026-07-20) | ~31 |
| Flask blueprints (phase 2a) | `/health`, `/api/logging/health`, `/api/track-record/*` | `bot/blueprints/{core,performance}.py` | **Done** (2026-07-20) | ~75 |
| Flask blueprints (phase 2b) | `/api/player/*` follow, `/api/match/*` follow | `bot/blueprints/personalization.py` | **Done** (2026-07-20) | ~105 |
| Flask blueprints (phase 2c) | `/api/status`, `/privacy`, `/api/bet-history/*` | `bot/blueprints/{core,performance}.py` | **Done** (2026-07-20) | ~155 |

**Still in api.py (not daemons):** HTTP routes, `_SCANNER_STATE` + `/api/scanner/status`, caches, `_MEM`, calibration refit hooks used by settlement.

---

## Phase 1 — `match_refresh_worker` (shipped)

### Why this worker first

- **Isolated:** only `db`, `odds_api`, `realtime_alerts` — no `_MEM`, no predictor, no calibration.
- **Low blast radius:** watchlist is optional user feature; failure does not block picks or settlement.
- **Testable:** single-cycle helper `refresh_watchlist_once()` without infinite loop.

### Interface

```python
from bot.workers.match_refresh_worker import (
    refresh_watchlist_once,  # one cycle — for tests
    run_loop,                # daemon entry (shim: api._followed_matches_refresh_loop)
    start_daemon_thread,     # optional startup from serve()
)
```

### Environment variables (optional)

| Variable | Default | Meaning |
|----------|---------|---------|
| `MATCH_REFRESH_STARTUP_DELAY_S` | 45 | Delay before first cycle |
| `MATCH_REFRESH_INTERVAL_S` | 60 | Seconds between cycles |

### Compatibility

- `api.serve()` still starts `_followed_matches_refresh_loop()` (shim → `run_loop()`).
- Behaviour unchanged: 45s startup, 60s interval, TTL 30s live / 60s prematch, 3% steam alerts.

### Tests

`tests/test_match_refresh_worker.py` — unit tests on `refresh_watchlist_once()` and `run_loop(stop_event=...)`.

---

## Phase 2 — `inplay_settlement_worker` (shipped)

### Why second

- Small, isolated (`db` + `odds_api` only).
- No calibration refit or `_MEM` dependency.
- Preserves original sleep-before-cycle semantics (first run after `INPLAY_SETTLE_INTERVAL_S`).

### Interface

```python
from bot.workers.inplay_settlement_worker import (
    settle_inplay_once,
    run_loop,
    start_daemon_thread,
)
```

### Compatibility

- `api.serve()` still starts `_inplay_settle_loop(inplay_interval)` (shim → `run_loop(interval=...)`).
- Env `INPLAY_SETTLE_INTERVAL_S` unchanged (default 300).

### Tests

`tests/test_inplay_settlement_worker.py` — 8 tests.

---

## Phase 3 — `clv_worker` (shipped)

### Interface

```python
from bot.workers.clv_worker import refresh_clv_once, run_loop, start_daemon_thread
```

### Environment variables (optional)

| Variable | Default | Meaning |
|----------|---------|---------|
| `CLV_CLOSING_STARTUP_DELAY_S` | 30 | Delay before first cycle |
| `CLV_CLOSING_INTERVAL_S` | 600 | Seconds between cycles (10 min) |

### Tests

`tests/test_clv_worker.py` — 10 tests.

---

## Phase 4 — `settlement_worker` (shipped)

### Why fourth

- Orchestrates settlement but delegates math to ``settlement.run_settlement``.
- Calibration refit stays in ``api._refit_calibration`` — injected via ``SettlementDeps`` (no import cycle, frozen math untouched).

### Interface

```python
from bot.workers.settlement_worker import SettlementDeps, run_settlement_once, run_loop

deps = SettlementDeps(
    get_mem=lambda: api._MEM,
    resolve=api._resolve,
    refit_calibration=api._refit_calibration,
    get_calib_k=lambda: api._CALIB_K,
)
run_loop(interval=600, deps=deps)
```

### Tests

`tests/test_settlement_worker.py` — 8 tests.

---

## Phase 5 — `value_scanner` (shipped)

### Notes

- Largest extraction (~320 lines). Decision gates unchanged — ``ScannerDeps`` injects
  ``_calib``, ``_MKT_W``, ``_build_pick_repro`` from ``api.py``.
- ``SCANNER_STATE`` lives in the worker module; ``GET /api/scanner/status`` calls ``get_status()``.

### Tests

`tests/test_value_scanner_worker.py` — 10 tests.

---

## Phase 6 — `telegram_worker` (shipped)

### Notes

- Two loops in one module: daily digest notifications + Telegram long-polling bot.
- No `_MEM` dependency — uses `db` + `digest` only for digest path.
- Command routing extracted to ``handle_telegram_message()`` for unit tests.

### Interface

```python
from bot.workers.telegram_worker import (
    DigestCycleState,
    run_digest_once,
    run_digest_loop,
    handle_telegram_message,
    poll_once,
    run_poll_loop,
    start_digest_thread,
    start_poll_thread,
)
```

### Environment variables (optional)

| Variable | Default | Meaning |
|----------|---------|---------|
| `DIGEST_INTERVAL_S` | 60 | Seconds between digest checks |
| `TELEGRAM_BOT_TOKEN` | — | Required for poll loop |
| `TELEGRAM_ADMIN_ID` | 0 | Restrict bot to admin chat (0 = open) |

### Tests

`tests/test_telegram_worker.py` — 17 tests.

---

## Phase 7 — `data_refresh_worker` (shipped)

### Notes

- Nightly ingest from tennis-data.co.uk at 02:00 local; ELO rebuild when new rows inserted.
- Uses ``db``, ``tennisdata_feeder``, ``elo``, ``memory`` — no predictor or settlement deps.

### Interface

```python
from bot.workers.data_refresh_worker import (
    DataRefreshCycleState,
    refresh_data_once,
    run_loop,
    start_daemon_thread,
)
```

### Environment variables (optional)

| Variable | Default | Meaning |
|----------|---------|---------|
| `DATA_REFRESH_STARTUP_DELAY_S` | 60 | Delay before first cycle |
| `DATA_REFRESH_INTERVAL_S` | 1800 | Seconds between checks (30 min) |
| `DATA_REFRESH_HOUR` | 2 | Local hour for nightly ingest |

### Tests

`tests/test_data_refresh_worker.py` — 8 tests.

---

## Phase 8 — Flask blueprints, slice 1 (2026-07-20)

### Notes

- Read-only routes first (no predictor/value decision logic).
- ``bot/blueprints/core.py`` : ``GET /health``
- ``bot/blueprints/performance.py`` : ``GET /api/logging/health``, ``GET /api/track-record`` (+ summary/monthly/surfaces)
- ``register_blueprints(app)`` called from ``bot/api.py`` after Swagger UI blueprint.

### Tests

Existing regression harness — ``tests/test_api_endpoints2.py`` (health), ``tests/test_track_record.py``, ``tests/test_api_endpoints_db.py`` (logging/health).

---

## Phase 9 — Flask blueprints, slice 2 (2026-07-20)

### Notes

- Personalization / watchlist routes — no predictor or value logic.
- ``bot/blueprints/personalization.py`` : player/match follow + followed lists.

### Tests

``tests/test_api_endpoints_db.py`` (follow routes) — 6 tests.

---

## Phase 10 — Flask blueprints, slice 3 (2026-07-20)

### Notes

- Read-only status + privacy + bet-history — no predictor/value logic.
- ``bot/blueprints/core.py`` : ``GET /api/status``, ``GET /privacy`` (added to phase 2a health)
- ``bot/blueprints/performance.py`` : ``GET /api/bet-history/stats``, ``/recent``, ``/calibration``

### Tests

``tests/test_api_endpoints2.py`` (privacy), ``tests/test_bet_history.py`` (bet-history API) — 12 tests.

---

## Remaining decomposition plan

1. **Flask blueprints** — Phase 2 continuation (roadmap #7): core + track-record + personalization + status/privacy/bet-history **done**; next tags: matches, value, intelligence, chat, admin.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Broken thread startup | Shim preserves old function name; serve() unchanged |
| Scanner state split | Defer scanner until state object co-moves with loop |
| Settlement refit side effects | Document `_refit_calibration` as worker dependency; do not move until injectable |
| Import cycles | Workers import from `bot.db`, `bot.odds_api` — never import `bot.api` |

---

## Next recommended task

Continue Flask blueprints phase 2: extract matches routes (`/api/upcoming`, `/api/live`) — byte-identical paths; keep `api_upcoming` shim for `/api/recommendations`.
