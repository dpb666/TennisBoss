# Surface Intelligence — ROI MODE Audit & Benchmark

**Date:** 15 juillet 2026  
**Lead:** ML Engineer (Surface Intelligence mission)  
**Status:** Phase 1–8 complete — **production integration REJECTED** (benchmark negative)

---

## Executive summary

| Finding | Detail |
|---------|--------|
| Archive surface coverage | **99.97%** (94 668 / 94 696 matches) |
| bet_history surface gap | **72/96 → 34/96** after archive backfill (+38 patched) |
| Baseline already uses surface | `predictor.elo_logit()` blends global + surface + recent ELO |
| TIS surface category | 25% weight via `weather_profile.surface_win_rate` (ELO-derived proxy) |
| Walk-forward benchmark | Baseline Brier **0.2211** vs +surface features **0.4035** (−82% relative) |
| **Decision** | **Do NOT wire new surface features to production predictor** |

Surface-specific *additional* features (win rate, momentum, fatigue, experience) **degrade** calibration when stacked on the current baseline. The existing surface ELO blend in `predictor.py` already captures most surface signal. High-ROI next step: **capture surface at pick time** (already wired in scanner/API) and **backfill bet_history** from archive.

---

## Phase 1 — Prediction path audit

### Data flow diagram

```
matches archive (surface 99.97%)
        │
        ▼
learner.train → memory.json
        │         ├── elo (global, time-decay 365j)
        │         ├── elo_surface {hard, clay, grass}
        │         └── elo_blend_surface (auto-tuned per surface)
        ▼
predictor.predict(mem, p1, f1, p2, f2, surface=?)
        │   z = (score1-score2) + bias + elo_logit(mem, p1, p2, surface)
        │   elo_logit: 40% global + 40% surface + 20% recent (when surface known)
        ▼
match_intelligence.compute_tis()
        │   surface score (25%): weather_profile.surface_win_rate (ELO proxy)
        │   model_health: intelligence.surface_danger flag
        ▼
calibrate.calibrated_prob() — temperature k on settled_matches (NOT surface-split)
```

### File map

| File | Surface role |
|------|-------------|
| `bot/predictor.py` | `elo_logit(mem, n1, n2, surface)` — **primary surface signal in production** |
| `bot/elo.py` | `build_dynamic(surface_key=)`, `build_recent(surface_key=)` |
| `bot/features.py` | No surface dimension — global EMA serve/return/recent only |
| `bot/match_intelligence.py` | `_surface_score()` 0–25 via `weather_profile.surface_win_rate` |
| `bot/intelligence_layer.py` | `_model_health(surface)` → `surface_danger` from `intelligence.py` |
| `bot/weather_profile.py` | `surface_win_rate()` — ELO-derived WR proxy; weather physics per surface |
| `bot/intelligence.py` | `check_surfaces()` accuracy audit; `retune_surface_blends()` on danger |
| `bot/calibrate.py` | Global temperature/Platt — **no surface-stratified calibration** |
| `bot/ml_prep/features.py` | Offline `surface_elo_diff` for ML prep (not production) |
| `bot/api.py` | `_surface_for(tournament)` resolution; ELO surface build at boot |
| `bot/settlement.py` | ELO surface update from `config.surface_from_league(tournament)` |
| `bot/db.py` | `matches.surface`, `value_picks.surface`, `bet_history.surface` |
| `bot/backtest.py` | Walk-forward with surface ELO blend (50/50 global/surface logit) |

### Calibration paths

1. **Global:** `calibrate.fit_temperature()` on `settled_matches` → `mem['calib_k']`
2. **TIS:** `match_intelligence.compute_tis(calibrate_match_prob=...)` optional hook
3. **Per-surface accuracy:** `intelligence.check_surfaces()` — monitoring only, not calibration adjustment
4. **ELO blend per surface:** `auto_learner.tune_all_surfaces()` when surface in danger

### Known gaps (from DATA_PIPELINE_AUDIT.md)

- Indoor hard **not split** from outdoor hard (stored as `hard`)
- Carpet (658 matches) excluded from surface ELO maps
- `clv_log` has **no surface column** — surface resolved via `value_picks` or archive lookup

---

## Phase 2 — Surface data coverage

Script: `scripts/surface_data_audit.py` / `python run.py surface-data-audit`

### matches archive (prod DB 2026-07-15)

| Field | Coverage |
|-------|----------|
| surface | 99.97% (94 668 / 94 696) |
| date | 100% |
| tour | 100% |
| ranking (w_rank/l_rank) | 12.77% |
| margin | 87.23% |

**Distribution:** hard 52 777 | clay 35 295 | grass 5 938 | carpet 658 | empty 28

### Betting tables

| Table | Total | With surface | Missing |
|-------|-------|--------------|---------|
| bet_history (settled) | 96 | 24 → **62** post-backfill | 34 still unknown |
| value_picks | 87 | 24 (27.6%) | 63 |
| clv_log | 97 | 0 (no column) | 97 |

### Enrichment implemented

1. **Pick time (existing):** `api.py` scanner + value tab call `db.log_value_pick(..., surface=_surf)`
2. **Settlement sync:** `db.resolve_bet_surface()` — value_pick → archive lookup
3. **Archive backfill:** `db.backfill_bet_history_surface_from_matches()` — patched **38/72** missing on prod
4. **CLI:** `python run.py backfill-bet-history --archive`

---

## Phase 3 — Feature engineering

Module: `bot/surface_features.py`

| Feature | Math definition | Unit |
|---------|-----------------|------|
| `win_rate_surface` | wins / n on surface (last n matches) | [0,1] |
| `weighted_recent_form_surface` | EMA: F_t = (1−α)F_{t-1} + α·outcome_t | [0,1] |
| `surface_elo_diff` | (Elo_surf(p1) − Elo_surf(p2)) / 400 | dimensionless |
| `surface_momentum` | WR(recent_n) − WR(baseline_n) on surface | [−1,1] |
| `fatigue_on_surface` | days since last match on same surface | days |
| `tournament_surface_experience` | count of surface matches before date | integer |

`MatchHistoryIndex` prefetches player history for O(1) lookups — no per-prediction SQL in experiment loop.

Tests: `tests/test_surface_features.py` (12 tests)

---

## Phase 4 — Experiment

Module: `bot/surface_experiment.py`  
CLI: `python run.py surface-benchmark [--test-fraction 0.25] [--min-test 500]`

### Methodology

- Walk-forward on 94 668 surface-tagged archived matches
- Train 70 507 | Test 23 503 (2025-12-01 → 2026-07-13)
- **Baseline:** frozen learner weights + `predictor.elo_logit(surface)` (current production path)
- **Enhanced:** baseline logit + learned linear combo of 6 surface feature diffs
- Metrics: log-loss, Brier, ECE, calibration bins, ROI sim (historical odds, min edge 3%)

### Results (`reports/surface_benchmark.md`)

| Metric | Baseline | + Surface features | Delta |
|--------|----------|-------------------|-------|
| Log loss | 0.6365 | 4.7730 | +4.1364 |
| Brier | **0.2211** | 0.4035 | +0.1824 |
| ECE | **0.0489** | 0.3801 | +0.3312 |
| ROI sim | −0.203 | −0.151 | marginal |

**Relative Brier change: −82.46%** (worse, not better)

Learned weights (overfit to train, hurt test):

| Feature | Weight |
|---------|--------|
| win_rate_surface_diff | +0.366 |
| win_rate_surface_20_diff | +0.324 |
| weighted_form_surface_diff | +0.215 |
| surface_momentum_diff | +0.083 |
| fatigue_on_surface_diff | −0.337 |
| tournament_surface_exp_diff | +0.204 |

Baseline calibration bins are reasonable (max gap 8.6%); enhanced model collapses to extreme probabilities (98% bin obs=57%).

---

## Phase 5 — Decision

**REJECT production integration.**

Criteria required: >1% relative Brier improvement OR clear calibration bin improvement.  
Observed: large degradation across all metrics.

### Rationale

1. Baseline **already embeds surface ELO** (40% of combined ELO logit when surface known)
2. Additional surface WR/momentum/fatigue features are **partially collinear** with ELO surface + global recent form
3. Linear stacking without regularisation on high-dimensional collinear features → overconfident predictions
4. TIS surface score (25%) uses a different proxy (ELO-derived WR) — separate path, not evaluated here

### What WAS shipped (safe, data-quality only)

- `db.resolve_bet_surface()` / archive backfill for bet_history
- `idx_matches_surface` index
- Audit script + benchmark tooling (offline only)
- **No changes to `predictor.predict()` or TIS weights**

---

## Phase 6 — Performance

- Added `CREATE INDEX idx_matches_surface ON matches(surface)`
- `MatchHistoryIndex` in-memory prefetch — experiment completes ~3.5 min on 94k matches (no hot-path SQL)
- `player_recent_matches` unchanged; surface queries use index when added via `lookup_surface_from_archive`

---

## Phase 7 — Tests

| File | Tests | Status |
|------|-------|--------|
| `tests/test_surface_features.py` | 12 | ✅ pass |
| `tests/test_surface_experiment.py` | 6 | ✅ pass |
| `tests/test_bet_history.py` (+2 surface) | 30 total | ✅ pass |

Run: `pytest tests/test_surface_features.py tests/test_surface_experiment.py tests/test_bet_history.py`

---

## Phase 8 — Files & commits

### New files

- `bot/surface_features.py` — feature definitions + MatchHistoryIndex
- `bot/surface_experiment.py` — walk-forward benchmark
- `scripts/surface_data_audit.py` — coverage report
- `reports/surface_benchmark.md` — benchmark output
- `docs/surface_features.md` — this document
- `tests/test_surface_features.py`
- `tests/test_surface_experiment.py`

### Modified files

- `bot/db.py` — `lookup_surface_from_archive`, `resolve_bet_surface`, `backfill_bet_history_surface_from_matches`, index
- `run.py` — `surface-benchmark`, `surface-data-audit`, `--archive` on backfill
- `tests/test_bet_history.py` — archive surface tests

### Suggested commit sequence (per phase)

```text
Phase 1-2: docs: surface intelligence audit + data coverage script
Phase 3:   feat: surface_features module with unit tests
Phase 4:   feat: surface_experiment walk-forward benchmark CLI
Phase 5-6: feat: bet_history surface backfill from matches archive
Phase 7:   test: surface capture and experiment coverage
Phase 8:   docs: surface benchmark results and rejection decision
```

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| 34 bet_history rows still missing surface | M | Live picks now capture surface; archive can't match future fixtures |
| Indoor/clay conflation | M | Documented; no split until data source provides it |
| Carpet matches excluded from ELO surface | L | 658 rows; negligible volume |
| Collinear surface features if retried | H | Any future attempt needs strong L2 / surface-only holdout / exclude surface_elo_diff |

---

## Next ROI tasks (prioritised)

1. **Capture surface at 100% of value picks** — verify scanner `_surf` propagation; eliminate remaining 34 unknown bet_history rows over time
2. **Accumulate 200+ settled bets** — calibration still sparse (n=96, Brier=0.231)
3. **Surface-stratified calibration monitoring** — extend `calibration_report.py` by surface once n≥30 per surface in bet_history
4. **Indoor split investigation** — only if odds API / ESPN provides reliable indoor flag (DATA_PIPELINE_AUDIT gap)
5. **Do NOT retry surface feature stacking** without ablation study isolating features from existing surface ELO

---

## Commands reference

```bash
python run.py surface-data-audit
python run.py surface-benchmark --min-test 500
python run.py backfill-bet-history --archive
pytest tests/test_surface_features.py tests/test_surface_experiment.py
```
