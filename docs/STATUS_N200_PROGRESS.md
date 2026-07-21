# STATUS — progress toward n=200 (ADR-013)

**Snapshot date:** 2026-07-20 (operational status pass)  
**Data source:** live `/home/alchemist/tennisboss/state/tennisboss.db` (native WSL prod DB)  
**Prediction core:** frozen per ADR-005 — no predictor/calibration/threshold changes.

## Headline metrics

**Last checked:** 2026-07-20 (operational status pass)

| Metric | Value | ADR-013 gate |
|--------|------:|--------------|
| Scanner-era settled picks (clv.stats() scanner) | **n=69** | **n≥200** |
| Distance to verdict sample | **131 picks** (34.5% of target) | — |
| Mean CLV (scanner, all settled) | **+17.02%** | GO needs mean CLV > 0 + significance |
| Mean CLV (7d window, scanner) | **+30.95%** (n=29) | informational |
| bet_history settled (7d) | 30 (avg CLV **29.92%**) | confirmatory ROI |
| Logging completeness (24h, post-migration) | **100%** (2/2 picks, post Segovia fix) | **≥90%** required |
| Logging completeness (post-migration, since 2026-07-15) | **100%** (10/10 picks, post Segovia fix) | **≥90%** required |
| Logging completeness (all clv_log, legacy included) | **8.0%** (9/113) | informational only |
| Prod /health (WSL :8000) | status=ok, players_loaded=4524 | — |

**Current CLV verdict (automated):** prometteur — positive CLV but sample too short (n=69).

## Logging completeness fix (2026-07-20)

**Segovia surface gap:** pick `72982434` (Challenger Segovia, Spain) had NULL `surface` — gate dipped to 90% (9/10). Added `segovia` → clay in `config._CITY_SURFACE`; `backfill-clv-repro` patches the row. Gate restored to **100% (10/10)**.

## Logging completeness fix (2026-07-19)

**Root cause:** (1) ADR gate used all-time denominator including ~104 pre-migration rows with NULL repro columns; (2) surface not resolved for many Challenger cities (`surface_from_league` returned empty); (3) ranking NULLs counted as incomplete even when player unranked.

**Fix applied:**
- `db.resolve_pick_surface()` + city dict entries (pozoblanco, tampere, winnipeg, bunschoten)
- Ranking-aware `validate_clv_pick_row()` + `lookup_player_rank()` name variants
- Post-migration gate: `since=CLV_REPRO_EPOCH` + `calibration_version IS NOT NULL`
- `python run.py backfill-clv-repro` — patched **5/21** post-epoch rows (surface)

**Before → after (live DB):**

| Scope | Before | After |
|-------|--------|-------|
| All-time | 1.8% (2/110) | 7.1% (8/112) |
| Post-migration (gate) | ~25% (2/8, surface gaps) | **100% (8/8)** |
| Last 24h | 0% (0/3) | **100% (2/2)** |

## Calendar / volume

Mid-July often sits in a **natural ATP/WTA lull** (between Masters blocks, post–Grand Slam). The past 7d audit showed low pick seeding; **do not widen selection filters** — wait for tour flux (see weekly-audit calendar note).

## ADR-013 checkpoint countdown

- **Protocol:** [ADR-013](adr/ADR-013-verdict-protocol.md) — pre-committed GO / ITÉRER / NO-GO at **n≥200** scanner-era settled picks with complete logging.
- **Remaining:** 131 settled picks before the mandatory verdict run.
- **Blockers today:** logging gate **cleared** for post-migration picks (100% ≥ 90%). Sample size still short (n=69).
- **Operational checkpoint:** Sunday weekly-audit digest (scheduler) + manual `python run.py weekly-audit`.

## Production services (verified 2026-07-20)

**Deploy baseline:** 85b0ce4 — SQLite drvfs recovery + monitor fix; passive accumulation toward n=200.

| Check | Result |
|-------|--------|
| systemctl is-active tennisboss-bot (API :8000) | **active** |
| systemctl is-active tennisboss-scheduler | **active** |
| systemctl is-active tennisboss-supervisor | **active** |
| systemctl is-active tennisboss-api (legacy unit) | **inactive** (API via tennisboss-bot) |
| Scheduler weekly-audit | **registered** — `schedule.every().sunday.at("21:00")` |
| GET http://127.0.0.1:8000/health | **200 OK** (status=ok, players_loaded=4524) |
| Post-migration logging gate (since=2026-07-15) | **100%** (10/10, post Segovia fix) |
| `python run.py weekly-audit` | OK (7d window 2026-07-14 → 2026-07-20) |
| `python run.py data-quality` | OK |

**Monitor alerts (2026-07-20):**
- bet_history sparse: n=69 scanner settled (ADR-013 needs n≥200) — **expected** during passive phase.
- Odds-API budget: watch pick seeding during ATP/WTA lull.

## Data quality (spot check)

`python run.py data-quality`: WTA serve non-neutral **94.34%**; rankings active **49.67%**; bet_history rows **112**.

## WSL git hygiene

WSL git status may show **6 modified paths** (android UI + oddspapi_feeder). Windows Git reports a **clean** tree; `git diff --ignore-cr-at-eol` on WSL is **empty** → line-ending (CRLF) noise only, not uncommitted logic. **No stash required.**

## This week

**Passive:** let open picks settle; no pick-selection or model changes.

**Active:** read Sunday **weekly-audit** digest; run `python run.py weekly-audit` on demand; monitor logging via `/api/logging/health?since=2026-07-15T00:00:00`.

## Commands reference

```bash
curl -sS https://api.tennisboss.online/health
python run.py weekly-audit
python run.py data-quality
python run.py backfill-clv-repro
wsl systemctl is-active tennisboss-bot tennisboss-scheduler
```



## 2026-07-19 SQLite drvfs recovery (prod)

- Pre: PRAGMA integrity_check failed on drvfs state/tennisboss.db (btree corrupt).
- Action: restored state/backups/tennisboss-20260719T204000.db to /home/alchemist/tennisboss/state/tennisboss.db.
- Config: TENNISBOSS_DB_FILE in .env; bot/config.py honors env override.
- Post: integrity ok; authenticated /api/value HTTP 200; scanner n_settled=65 unchanged.
- Monitor: remaining=None no longer alerts as exhausted (bot/monitor.py).
