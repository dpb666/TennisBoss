# TennisBoss — Production Reliability Report

**Session:** 2026-07-15 18:10 EDT (UTC-4)  
**Engineer mode:** Continuous reliability — no predictor/UI changes  
**Repo HEAD:** `95c4bb7` (surface benchmark + archive backfill docs)

---

## Executive summary

| Zone | Status | Detail |
|------|--------|--------|
| Services (WSL systemd) | **OK** | `tennisboss-bot` + `tennisboss-scheduler` active since 15:50 EDT |
| `/health` (prod) | **OK** | `status=ok`, 4524 players, v1.0.0 |
| `/api/monitor/status` (prod) | **WARNING** | Auth required (401 without token); DB meta stale until scheduler fix deployed |
| Scheduler jobs | **OK** | 11 jobs configured; monitor 5m, espn_warm 2m, bet_history 04:30, rankings 03:00, calibration Sun 22:00 |
| DB integrity | **OK** | 0 duplicate event_keys, 0 null prediction/CLV on settled, 0 clv/bet result mismatches |
| bet_history (90d) | **SPARSE** | n=97 settled (< 200 threshold) — monitor-only calibration |
| Calibration | **SPARSE** | Brier=0.229, bins max n=64 — insufficient for evaluation |
| value_picks surface capture | **LOW** | 28.6% (30d), 27.6% (all-time) |
| Cache engineer/today | **OK** | cold 6.7–11.4s → cached 0.09s (~75×) |
| Fix applied this session | **1** | `job_monitor` now persists `last_monitor_check` (was stale since 2026-07-12) |

**Verdict:** Production is healthy and scanning. Statistical evaluation remains blocked by sparse `bet_history` (97 < 200). Highest ROI: deploy monitor persistence fix + continue bet_history accumulation.

---

## 1. Recent commits (git log -10)

| Hash | Date | Message |
|------|------|---------|
| `95c4bb7` | 2026-07-15 15:10 | Document surface intelligence audit, benchmark rejection, archive backfill tests |
| `69dfa25` | 2026-07-15 15:10 | Add walk-forward surface benchmark experiment and offline CLI support |
| `66f53d9` | 2026-07-15 15:09 | Add surface feature engineering module with documented math and unit tests |
| `f586e8e` | 2026-07-15 15:09 | Backfill bet_history surface from matches archive and surface benchmark CLI |
| `e2720b5` | 2026-07-15 13:07 | docs: fix commit hash in stabilization report |
| `f7ec92b` | 2026-07-15 13:06 | fix(stab): bet_history surface backfill, rankings retry, sparse alert |
| `da0be76` | 2026-07-15 12:50 | perf(api): cut engineer/today cold path via Elo prefilter |
| `80ea0bb` | 2026-07-15 12:16 | docs: add commit hashes to CTO session report |
| `9dad1e9` | 2026-07-15 12:16 | feat(ops): engineer/today batch path, endpoint timing, bet_history backfill |
| `680e5bd` | 2026-07-15 12:16 | fix(tis): apply Platt/temperature calibration to model_prob and EV |

Recent work is ops/stabilization focused (surface backfill, monitor alerts, perf). No predictor logic changes in last 10 commits beyond Platt calibration application (`680e5bd`).

---

## 2. Production health

### `/health` (public, prod)
```json
{"players_loaded":4524,"service":"TennisBoss","status":"ok","version":"1.0.0"}
```

### `/api/monitor/status` (prod)
- Returns `401 unauthorized` without `X-API-Token` (expected — `TENNISBOSS_API_TOKEN` active).
- DB meta `last_monitor_check` timestamp: **2026-07-12T03:05:33** (stale).
- Scheduler journalctl shows monitor running every 5 min with 2 alerts:
  - `bet_history sparse: 97 settled (need 200+ for calibration)`
  - `Odds-API budget exhausted, reset in 0s`

**Root cause (fixed this session):** `job_monitor()` called `run_full_check()` but never called `db.set_meta("last_monitor_check", ...)`. Only `monitor.continuous_monitor()` persisted results. API endpoint and external consumers read stale July 12 data.

### Service logs (journalctl, last 100 lines)

| Signal | Status | Notes |
|--------|--------|-------|
| Scanner cycles | OK | 25/25 verified, 595 events, 0 active picks |
| Settlement auto | OK | +2 settled this cycle, n=4847 acc=0.556 |
| Learn job | OK | elo blends hard=0.6 clay=0.7 grass=1.1, kfold acc=0.605 |
| API-Tennis | WARN | Inactive/expired — fallback odds-api.io works |
| oddspapi | WARN | Key pool exhausted — non-blocking |
| Odds-API budget | WARN | Exhausted during scan peaks — transient |
| Health probes | OK | `/health` 200 every ~60s |

---

## 3. Scheduler job verification

Configured in `bot/scheduler.py::setup_jobs()`:

| Job | Schedule | Verified |
|-----|----------|----------|
| `job_learn` | 1h | OK (17:51 learn complete in logs) |
| `job_ingest` | 6h | Configured |
| `job_mtd_ingest` | 6h | Configured |
| `job_mcp_backfill` | 12h | Configured |
| `job_monitor` | **5 min** | OK (running; persistence bug fixed) |
| `job_espn_warm` | **2 min** | OK (ESPN 38 matches in logs) |
| `job_backup` | 6h + boot | OK |
| `job_daily_digest` | 09:00 daily | OK (sent 2026-07-15) |
| `job_bet_history_backfill` | **04:30 daily** | Configured (guard: once/day) |
| `job_rankings` | **03:00 daily** (ISO week guard) | Configured |
| `job_calibration_report` | **Sun 22:00** | Configured |

---

## 4. Data quality report

### bet_history (source: `scripts/stabilization_db_check.py`)

| Metric | Value |
|--------|-------|
| Total rows | 97 |
| Settled (result 0/1) | 97 |
| Duplicate event_keys | 0 |
| NULL prediction on settled | 0 |
| NULL clv_pct on settled | 0 |
| clv_log total | 97 |
| clv_log NULL closing_odds | 0 |
| Settled without clv_log | 0 |
| clv/bet result mismatches | 0 |
| Total PnL | -1.01u |
| Avg PnL | -0.0104u |

### Surface coverage (bet_history settled)

| Surface | n | % |
|---------|---|---|
| grass | 38 | 39.2% |
| *(empty/unknown)* | 35 | 36.1% |
| clay | 16 | 16.5% |
| hard | 8 | 8.2% |

**Surface coverage:** 62/97 = **63.9%** (up from 23% pre-archive-backfill per stabilization pass).

### value_picks surface capture (recent)

| Window | Total | With surface | % |
|--------|-------|--------------|---|
| Last 30 days | 84 | 24 | **28.6%** |
| All-time | 87 | 24 | **27.6%** |

Pick-time surface capture remains low — archive backfill compensates in `bet_history` but live `value_picks` still miss ~72% of surfaces.

---

## 5. Calibration status (90 days)

```
python run.py calibration-report --days 90
```

| Metric | Value | Threshold |
|--------|-------|-----------|
| n_settled | **97** | < 200 → **sparse, monitor only** |
| Brier score | **0.229** | < 0.25 = better than coin flip |
| ROI | -1.0% | — |
| Win rate | 32% | — |
| Avg CLV | +1.33% | — |
| Verdict | Pas assez de paris par bin pour conclure | — |

### Reliability bins (model probability)

| Bin | n | Predicted | Observed | Gap |
|-----|---|-----------|----------|-----|
| 50-55% | 3 | 0.509 | 0.333 | -0.176 |
| 55-60% | 4 | 0.564 | 0.500 | -0.064 |
| 60-65% | 2 | 0.628 | 0.500 | -0.128 |
| 65-70% | 0 | — | — | — |
| 70-75% | 2 | 0.746 | 0.000 | -0.746 |
| 75-100% | 0 | — | — | — |

**Max bin n = 4** (fine bins) / **64** (coarse 60-80% bin). Far below n≥200 for full evaluation.

### Threshold actions

| Threshold | Status | Action |
|-----------|--------|--------|
| n < 200 | **CURRENT (97)** | Monitor only — no calibration changes |
| n ≥ 200 | Not reached | Run full calibration evaluation |
| n ≥ 500 | Not reached | `compare-engines` CLI **does not exist** in `run.py` |
| n ≥ 1000 | Not reached | Model replacement recommendation (deferred) |

### By bookmaker (closing source)

| Source | n | Win% | Yield | Avg CLV |
|--------|---|------|-------|---------|
| pre_closing | 13 | 46.2% | +45.1% | +21.2% |
| snapshot | 41 | 39.0% | +16.3% | -3.6% |
| last_seen | 43 | 20.9% | -31.5% | 0.0% |

Positive signal on pre_closing CLV but N too small for conclusions.

---

## 6. API endpoint timings

From meta `endpoint_timings` (updated by bot during requests):

| Endpoint | count | avg_ms | max_ms | last_ms |
|----------|-------|--------|--------|---------|
| engineer/today | 29 | 2590.5 | 11152.8 | 0.1 |

Local benchmark (`scripts/bench_engineer_today.py`):

| Mode | Latency |
|------|---------|
| Cold (ESPN warm) | 11.38s |
| True cold (ESPN cleared) | 6.66s |
| Cached (TTL 90s) | **0.09s** |

TIS compute dominates cold path (~5.8–9.2s for 15 matches). Cache ratio ~75×. WARN >5s expected on cold hits.

---

## 7. Cache (engineer/today)

| Property | Value |
|----------|-------|
| TTL | 90s |
| Cold | 6.7–11.4s |
| Cached | 0.09s |
| espn_warm | 2 min (keeps ESPN cache hot) |

**Status: OK** — cache functional, cold path acceptable with espn_warm.

---

## 8. Fix applied this session

### Monitor persistence gap (HIGH)

**Problem:** `job_monitor()` ran health checks every 5 min but never persisted results. `/api/monitor/status` served stale data from 2026-07-12.

**Fix:** Added `db.set_meta("last_monitor_check", json.dumps(result))` in `bot/scheduler.py::job_monitor`.

**Tests:** `tests/test_scheduler.py::TestJobMonitor` — 2 passed.

**Deploy:** Restart `tennisboss-scheduler` after push to activate.

---

## 9. Remaining technical debt

| Item | Severity | Notes |
|------|----------|-------|
| bet_history sparse (97 < 200) | **H** | Blocks calibration evaluation; clv_log fully backfilled — need more settled picks over time |
| value_picks surface capture 28.6% | **M** | Archive backfill helps bet_history but live picks still lack surface |
| Odds-API budget exhaustion | **M** | Transient during scan peaks; all keys rotate but budget hits zero |
| API-Tennis key inactive | **L** | Fallback odds-api.io works |
| oddspapi pool empty | **L** | Non-blocking for current picks |
| `compare-engines` CLI missing | **L** | Documented in MASTER_TODO but not implemented |
| NTFS/WSL SQLite I/O | **M** | Intermittent `disk I/O error` on concurrent access; services recovered after restart |
| Sackmann CSV 404 | **L** | Known dead source; MTD/MCP compensate |
| Danger zones (EV 8-18%) | **M** | ROI -22% to -24% on small n=8-10 — monitor, don't change predictor yet |

---

## 10. Highest ROI recommendation

**Deploy monitor persistence fix** (`job_monitor` → `last_monitor_check`) and **wait for bet_history to reach n≥200** through natural settlement + daily 04:30 backfill.

No predictor changes warranted at n=97. Pre_closing CLV signal (+21% avg) is promising but sample size is 13 — monitor only.

Secondary: improve `value_picks` surface capture at pick time (currently 28.6%) to reduce reliance on archive backfill for surface-stratified calibration.

---

## 11. Auto-threshold tracker

| Threshold | n required | Current n | Status |
|-----------|------------|-----------|--------|
| Sparse monitor | < 200 | 97 | **ACTIVE** |
| Full calibration eval | ≥ 200 | 97 | 103 short |
| compare-engines | ≥ 500 | 97 | CLI not implemented |
| Model replacement doc | ≥ 1000 | 97 | Deferred |

---

*Next cycle: re-check bet_history count, verify `last_monitor_check` freshness post-deploy, re-run `calibration-report --days 90`.*
