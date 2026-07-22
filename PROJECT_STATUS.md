# TennisBoss — Project Status

_Refreshed: 2026-07-22, from a full verified workspace audit (CI status, real prod DB, fresh-clone test runs) — not a re-read of prior reports. Backend: Python/Flask (`bot/`). Android: Kotlin/Compose (`android/`). Primary sources: `docs/ARCHITECTURE_BLUEPRINT.md`, `MASTER_TODO.md` (dated ledger), `gh run list` (CI ground truth)._

## Completion estimate

| Area | Estimate | Basis |
|---|---|---|
| Backend prediction/data pipeline | ~90% | Frozen core (ADR-005) + full signal/odds/value pipeline. No model changes until the ADR-013 verdict at n≥200. |
| Backend API (`bot/api.py`) | ~96% | 52+ routes; worker decomposition + Flask-blueprint extraction (phases 2a–2d, 7) done in `bot/workers/` and `bot/blueprints/`. |
| Autonomous mode (scheduler/supervisor) | 100% | 12 scheduled jobs incl. weekly-audit (Sun 21h). |
| AI assistant | Phase 1 done | 6 read-only tools + `mode=analyst`; `TENNISBOSS_AI_TOOLS=1` set in prod `.env`. |
| Android app | ~87% | Analyst chat mode + combo book_odds EV; Room/DI still deferred (ADR-010). |
| **Testing** | **674 backend / 75 Android, 0 failures** | Verified 2026-07-22 in a genuinely fresh clone (not the long-lived dev checkout) — see CI note below. |
| **CI (GitHub Actions)** | **Green** (since commit `3dbc777`) | Was **red on 20/20 consecutive runs** (≥7 days, both jobs) — found and fixed 2026-07-22, see history below. |
| Release readiness | **READY** (as of `3dbc777`) | Android was **not actually buildable** from 2026-07-18 to 2026-07-22 (`compileDebugKotlin` failure) — fixed; see history below. |
| Deployment | ~96% | Prod running current `main` HEAD. `scripts/deploy.sh` + `deployment_history` (2 entries) available; one restart (2026-07-21) had to be logged retroactively. |
| Architecture & docs | 13 ADRs | ADR-013 verdict protocol pre-committed at n≥200; not yet triggered (see Edge status). |

**Overall: ~93%.** Binding constraint remains statistical, not technical — see Edge status below.

## Edge status (ADR-013 — ground truth from live prod DB, 2026-07-22)

| Metric | Value | ADR-013 gate |
|---|---:|---|
| Scanner-era settled picks | **n=72** | n≥200 |
| Mean CLV (scanner-era) | **+15.6%** | must be > 0 |
| Beat-closing rate (scanner-era) | **33.3%** (95% CI ±10.9) | must clear 50% lower bound for GO |
| ROI flat (scanner-era) | **+9.0%** | confirmatory only |
| Global settled (all-time) | n=119, ROI flat **−6.2%**, mean CLV +7.6% | informational |

**Automated verdict: "prometteur" — positive CLV, sample still short of n≥200.** Correctly not a GO (beat-closing far below the 50% significance bar even ignoring sample size) and correctly not a NO-GO (too early to call). No predictor/threshold changes made or warranted. Accumulation pace is slower than earlier estimates (~1.5 picks/day, ATP/WTA calendar lull) — realistic n=200 horizon is **4–6 weeks**, not 2.

## What changed 2026-07-22 (full workspace audit + fixes)

- **Found and fixed: CI had been red for ≥7 days** (20/20 runs failing on both jobs since at least 07-15) — invisible because every "tests passing" figure in prior docs came from local Windows runs, never from CI itself.
  - Android: `compileDebugKotlin` failed outright (missing `CircularProgressIndicator` import in `ChatScreen.kt`, introduced 07-18) — no Android test had actually run in CI for 4 days.
  - Backend: 5 tests failed deterministically on any fresh checkout (reproduced in a clean WSL clone) — each called a real, unmocked `db.*` function and silently depended on a pre-populated `state/tennisboss.db` that only exists on a long-lived dev machine. Fixed via the same temp-DB isolation convention already used in ~30 other test files.
  - Verified on real CI post-fix: [run 29942410519](https://github.com/dpb666/TennisBoss/actions/runs/29942410519) — both jobs green.
- **Found: `docs/STATUS_N200_PROGRESS.md`'s "100% logging completeness" claim was true only for the newest ~8–10 picks** (post-migration window); the 4-week bucketed view is ~13% (expected — repro columns were added after older rows were logged, not a regression).
- **Found (from git history, not this session's doing): a real SQLite corruption incident on 2026-07-19** — `PRAGMA integrity_check` failed on the `/mnt/c` (drvfs)-hosted DB; recovered from `state/backups/`, DB now lives at a native WSL path (`TENNISBOSS_DB_FILE` override). Validates the off-site-backup work done just before it.
- **Retroactively logged** the 2026-07-21 prod restart into `deployment_history` (was done manually, never journaled at the time).

## Broken / watch

1. ~~4 pre-existing test failures (OddsPapi merge, telegram digest timing)~~ — **did not exist** as of 2026-07-22 (674/674 on a fresh clone); prior doc was stale.
2. **`TENNISBOSS_ADMIN_TOKEN`** still not set in prod `.env` (deliberately left to the operator — a secret minted by an agent shouldn't live in a transcript).
3. Accumulation pace toward n=200 has slowed (calendar lull) — do not widen pick-selection filters to compensate; let the sample stay valid.

## Frozen core (ADR-005)

`predictor.py`, `calibrate.py`, market blend, `/api/value` gates — verified untouched (`git diff` clean) through all 2026-07-22 audit/fix work.

---
See `MASTER_TODO.md` for the full dated ledger and `docs/ARCHITECTURE_BLUEPRINT.md` for the architecture reference.
