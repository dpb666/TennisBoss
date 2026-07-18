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
| P2-7 Off-site backup | `scripts/backup_offsite.{sh,ps1}` + `docs/BACKUP.md` |
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

1. **`git push`** from dev machine if prod pulls from remote
2. **`TENNISBOSS_AI_TOOLS=1`** in prod `.env` when ready to surface AI tools (Android UI now displays sources)
3. **Off-site backup cron** — schedule `scripts/backup_offsite.sh` weekly; set `BACKUP_DEST` on a cloud-sync folder
4. **Backfill CLV** for picks settled with `closing_src=last_seen` since 2026-07-15 — optional manual re-run once worker has cycled (no automatic backfill shipped; consider SQL audit)
5. **Fix 4 flaky tests** in `test_api_endpoints2` / `test_telegram_worker` (pre-existing)
6. **Ratify ADR-013** at next architecture review

---

_Generated 2026-07-18 — TennisBoss CTO go-max execution._
