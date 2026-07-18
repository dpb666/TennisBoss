# CTO Execution Report — 2026-07-18

**Scope:** Full "go max" follow-up from CTO audit.  
**Frozen (verified untouched):** `bot/predictor.py`, `bot/calibrate.py`, market blend, `/api/value` thresholds, pick-selection gates.

---

## Summary

| Item | Status |
|---|---|
| P0-1 Redeploy | Committed; WSL prod restarted; `/health` OK |
| P0-2 CLV stuck at 0 | Root cause found + fix shipped |
| P0-3 No model changes | Confirmed — git diff clean on frozen files |
| P1-4 ADR-013 | `docs/adr/ADR-013-verdict-protocol.md` |
| P1-5 weekly-audit | CLI + scheduler + tests |
| P1-6 Calendar note | In weekly-audit output |
| P2-7 Off-site backup | `scripts/backup_offsite.{sh,ps1}` + `docs/BACKUP.md` (incl. Task Scheduler) |
| P2-8 Android analyst + Sources | ChatViewModel + ChatScreen chips |
| P2-9 Ledger updates | `MASTER_TODO.md`, `PROJECT_STATUS.md` |

---

## P0-1 — Deploy

### Commits (logical split)

1. **fix(clv):** event_key closing lookup, logging completeness Telegram alert, monitor hook
2. **feat(ops):** `weekly-audit` CLI, Sunday scheduler job, ADR-013, tests
3. **chore(backup):** off-site scripts + `docs/BACKUP.md`
4. **feat(android):** combo book_odds EV, analyst chat mode, sources/tools chips
5. **docs:** this report + project ledger refresh

### Deploy steps (prod WSL)

```bash
cd /mnt/c/Users/donpa/TennisBoss   # or your prod clone
git pull --ff-only                 # after push from dev machine
python3 -m pip install -r requirements.txt --quiet
sudo systemctl restart tennisboss-bot.service tennisboss-scheduler.service
curl -fsS https://api.tennisboss.online/health
python3 run.py record-deploy --component all --notes "CTO go-max 2026-07-18"
```

Or: `scripts/deploy.sh --no-pull` when already on the target commit.

### Deploy status (2026-07-18)

- WSL reachable; `tennisboss-bot` **active**
- `curl https://api.tennisboss.online/health` → `{"status":"ok",...}`
- Services restarted locally via WSL after commit (code on shared `/mnt/c` path)

---

## Post-push completion (2026-07-18 evening)

| Step | Status |
|---|---|
| `git push -u origin main` | **Done** — `8e3deeb..3cea335` → [origin/main](https://github.com/dpb666/TennisBoss/tree/main) |
| Prod commit | **Aligned** — `/mnt/c/Users/donpa/TennisBoss` @ `3cea335` (shared path; no separate pull required) |
| `sudo systemctl restart tennisboss-bot tennisboss-scheduler` | **Done** — both **active** after restart |
| `TENNISBOSS_AI_TOOLS=1` | **Already set** in prod `.env` (`EnvironmentFile` for bot + scheduler) |
| `/health` post-restart | **OK** — `{"status":"ok","players_loaded":4524,...}` |
| `/api/chat?mode=analyst` | **Reachable** — returns `401 unauthorized` without auth token (expected) |
| `python run.py weekly-audit` | **Smoke OK** (7d window) |
| `pytest -k clv_worker` | **11 passed** |
| Off-site backup dry-run | **Partial** — archive created under `%TEMP%\tennisboss-backup-dryrun`; `state/backups/*.db` skipped when locked by running bot (expected on live host) |

### Off-site backup scheduling (manual)

Scripts verified: `scripts/backup_offsite.sh`, `scripts/backup_offsite.ps1`. Set **`BACKUP_DEST`** to a cloud-sync or off-machine folder; optional **`BACKUP_ENCRYPT_PASS`** for encryption (host `.env` only — never commit). See `docs/BACKUP.md`.

**WSL cron (suggested — Sunday 04:00 UTC):**

```bash
0 4 * * 0 cd /mnt/c/Users/donpa/TennisBoss && BACKUP_DEST=/mnt/backups/tennisboss ./scripts/backup_offsite.sh >> /var/log/tennisboss-backup.log 2>&1
```

**Windows Task Scheduler:** weekly trigger → PowerShell `-File scripts\backup_offsite.ps1` with user env `BACKUP_DEST` (and optional `BACKUP_ENCRYPT_PASS`) set in the task or profile.

---

## P0-2 — Closing odds / CLV = 0

### Root cause

Since ~2026-07-15, `clv_worker.refresh_clv_once()` matched odds-api events **only by player surname** (`find_event`). Picks seeded from `/api/value` store the correct **`event_key` = odds-api event id**, but name formats often diverge (e.g. `"Last, First"` in DB vs `"First Last"` in odds-api). Result:

1. `find_event` → no match → `closing_odds` stays NULL
2. `clv.settle()` fallback → `last_seen` (closing = pick odds) → **CLV = 0%**

Worker decomposition did not stop the loop; matching logic was the gap.

### Fix (additive)

`bot/workers/clv_worker.py`:

- `_find_event_for_pick()` — prefer `event_key` id lookup, then name fallback
- Shorter odds TTL (`CLV_ODDS_TTL_S = 120`) for fresher closing snapshots
- Summary counters: `matched_by_id`, `event_not_found`

### Logging completeness alert

- `db.clv_logging_completeness_recent(hours=24)`
- `monitor.check_logging_completeness()` — alert if &lt; 90% (n≥3)
- `realtime_alerts.alert_logging_completeness()` — Telegram, dedup 1×/day

---

## P0-3 — No model changes

Verified: no modifications to `predictor.py`, `calibrate.py`, or value decision thresholds in this execution.

---

## P1-4 — ADR-013

**Path:** `docs/adr/ADR-013-verdict-protocol.md`

Pre-committed verdict at n≥200: **GO** (CLV&gt;0 sig) / **ITÉRER** / **NO-GO** — references ADR-005 freeze.

---

## P1-5 — weekly-audit

```bash
python run.py weekly-audit              # human report (7d window)
python run.py weekly-audit --json       # full JSON
python run.py weekly-audit --telegram   # send owner digest
python run.py weekly-audit --days 14 --logging-hours 48
```

**Scheduler:** Sunday 21:00 UTC — `job_weekly_audit` → Telegram (meta `last_weekly_audit_week`).

**Tests:** `tests/test_weekly_audit.py` (5 tests).

---

## P1-6 — Calendar note

Included in `weekly_audit.format_report()` and Telegram digest — quiet ATP/WTA weeks are expected; **do not widen selection gates**.

---

## P2-7 — Off-site backup

```powershell
$env:BACKUP_DEST = "D:\Backups\tennisboss"
$env:BACKUP_ENCRYPT_PASS = "..."   # optional
.\scripts\backup_offsite.ps1
```

```bash
export BACKUP_DEST=/mnt/backups/tennisboss
export BACKUP_ENCRYPT_PASS=...     # optional → .gpg
scripts/backup_offsite.sh
```

See `docs/BACKUP.md`.

---

## P2-8 — Android

- `ChatViewModel.resolveChatMode()` — sends `mode=analyst` for `@agent` prefix or ROI/CLV/calibration keywords
- `ChatScreen` — disabled AssistChips for `tools_called` and `sources`
- `ApiModels` — `ChatRequest.mode`, `ChatResponse.tools_called/sources`
- Tests: `ChatViewModelTest` (+3 cases)

Combo builder (prior WIP): `book_odds` → server-side `ev_pct` / `edge` on `/api/bet-builder/combo`.

---

## Tests

- **New/updated:** 16 CLV worker + weekly-audit tests — all pass
- **Full suite:** 652 passed, 4 pre-existing failures (`test_api_endpoints2` OddsPapi merge ×2, `test_telegram_worker` digest timing ×2) — not introduced by this execution

---

## Remaining manual steps

1. ~~**`git push`** from dev machine~~ — **completed** (see Post-push completion)
2. ~~**`TENNISBOSS_AI_TOOLS=1`** in prod `.env`~~ — **already enabled**
3. ~~**Off-site backup cron / Task Scheduler**~~ — **Done** — see `docs/BACKUP.md` (WSL cron + Windows Task Scheduler examples)
4. ~~**Backfill CLV** for picks settled with `closing_src=last_seen` since 2026-07-15~~ — **Done** (see CLV backfill section below)
5. **Fix 4 flaky tests** in `test_api_endpoints2` / `test_telegram_worker` (pre-existing)
6. **Ratify ADR-013** at next architecture review

**Note:** WSL git working tree on `/mnt/c/Users/donpa/TennisBoss` shows unrelated local modifications (android/dashboard, oddspapi); prod services run from shared path @ `3cea335` — reconcile or stash before next `git pull --ff-only` on that host.

---

## CLV backfill — `last_seen` since 2026-07-15 (2026-07-18 evening)

### Investigation

- **19** settled picks with `closing_src=last_seen` and `pick_ts >= 2026-07-15` (all had `clv_pct=0`).
- **18/19** had `market_snapshots` with a pre-match last quote (`hours_ahead ≈ -1h`).
- **1** row (`72666938`, Bondioli vs Justo) had **zero** snapshots and no odds-api settled match — left unchanged.

### Command shipped

```bash
python run.py backfill-clv-closing              # apply (default since 2026-07-15)
python run.py backfill-clv-closing --dry-run      # audit only
python run.py backfill-clv-closing --no-odds-api   # snapshots only
```

Additive only: `bot/clv_backfill.py`, `db.patch_clv_closing_settled()`, `db.latest_market_snapshot()`. Does **not** touch predictor/calibration/value gates.

### Results (prod DB)

| Metric | Count |
|---|---|
| Candidates | 19 |
| Fixed (`snapshot_backfill`) | **18** |
| Skipped (no source) | **1** |
| Skipped (invalid odds ratio) | **0** |
| odds-api fallback used | 0 |

Post-backfill `weekly-audit` (7d): avg CLV **+18.1%** (was 0% on `last_seen` rows), scanner n=50, verdict **prometteur**.

---

## WSL dirty tree (documented — user work preserved)

Uncommitted on shared `/mnt/c/Users/donpa/TennisBoss` path (not stashed — no data destroyed):

| Path | Notes |
|---|---|
| `android/.../DashboardScreen.kt` | Local UI edits (~640 lines touched) |
| `android/.../DashboardViewModel.kt` | Local VM edits |
| `android/.../MatchDetailViewModel.kt` | Local VM edits |
| `bot/oddspapi_feeder.py` | Local feeder refactor (~374 lines) |
| `tests/test_oddspapi_feeder.py` | Matching test updates |
| `.gitignore` | Minor local tweak |

**Before next `git pull --ff-only` on WSL:** review diffs or stash:

```bash
git stash push -m "WIP android dashboard + oddspapi" -- android/ bot/oddspapi_feeder.py tests/test_oddspapi_feeder.py .gitignore
```

Prod services unaffected — they load Python from the same tree but run committed code paths unless restarted after uncommitted edits.

---

_Generated 2026-07-18 — TennisBoss CTO go-max execution._
