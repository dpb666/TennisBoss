# TennisBoss — Performance Report

_2026-07-13. Backend + Android, based on a dedicated audit pass plus this session's own real incident._

## The one confirmed-and-fixed real bug

`bot/mcp_feeder.py`'s original `backfill()` implementation called `db.connect()` (a fresh `sqlite3.connect()`, per `bot/db.py:230-242`) roughly 3 times per loop iteration across ~4000 candidate matches — on the order of 12,000 individual connections. On this machine (WSL process, DB file on `/mnt/c`, i.e. NTFS accessed via the 9p protocol — much slower than a native filesystem for many small syscalls), a real run exceeded 15 minutes without completing and had to be killed. Fixed by loading the entire match index in one query (`db.matches_index_by_date()`) and applying all updates in one transaction (`db.backfill_match_stats_bulk()`) — the real run now completes in ~2 seconds. This was found, diagnosed, and fixed in the same session it was introduced.

## Is this a systemic pattern or an isolated bug?

**Isolated, confirmed by a dedicated audit pass.** Every other `db.connect()` call site in `bot/*.py` (api.py, digest.py, mistake_learner.py, realtime_alerts.py, recommendations.py, signal_backtest.py — roughly 10 sites) opens one connection, then iterates over the already-fetched `.fetchall()` result in memory. `tennisdata_feeder.py`, `mantennisdata_feeder.py`, `sackmann_feeder.py`, `scheduler.py`, `auto_learner.py`, `backtest.py` don't call `db.connect()` directly at all — they go through higher-level batch functions. No other instance of the anti-pattern exists today.

**Design note, not a bug**: `db.py`'s per-call-site `sqlite3.connect()` pattern is a reasonable design for the ~100 low-frequency call sites (one connection per HTTP request or background-loop tick) — it would only be worth pooling connections if a profiling pass showed connection overhead actually mattering at that scale, which it doesn't. It's a footgun specifically inside a loop over many rows, which is now documented (`MASTER_TODO.md` #9).

## Hot-path complexity

No O(n²)-or-worse algorithm found on any per-HTTP-request code path. `elo.build_dynamic()`/`build_from_matches()`/`build_recent()` (each O(n) over the full ~92k-row match history) are invoked only at server startup (`bot/api.py:3173`) and inside offline feeders/backtest jobs — never per-request. `predictor.py`/`features.py` operate on precomputed, constant-size feature vectors per prediction request. The settlement/calibration refit (`_refit_calibration`/`_blend_samples`, O(n) over ~100k settled rows) runs only inside the 600-second background settlement loop.

## Android / Compose

No recomposition-storm patterns found in the 3 screens sampled (`DashboardScreen.kt`, `MatchDetailScreen.kt`, `ValueScreen.kt`) — all network/heavy work happens inside `LaunchedEffect` or the ViewModel, never directly in composition. List rendering is bounded everywhere checked (`.take(5)`, small signal lists).

## Memory / large objects

Not deeply profiled in this pass (would need an actual memory profiler run, not a code read) — flagged as a gap in this report rather than a finding. If revisited: the ~92k-row `all_matches_chrono()` result set, loaded fully into memory for every ELO rebuild, is the single largest in-memory structure in the backend and would be the first place to look if memory pressure ever becomes a real symptom.

## Network efficiency

Rate limiting and caching are already tuned specifically around the odds-api.io quota (100 req/h) — see `API_REPORT.md`. No redundant/duplicate outbound calls found in the sampled feeders.

## Summary

Performance is in good shape. The one real incident this session was found and fixed the same day it was introduced, and a dedicated follow-up audit confirmed it was isolated rather than a symptom of a broader problem. No other performance action items beyond the preventive documentation task in `MASTER_TODO.md` #9.
