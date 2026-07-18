# TennisBoss — Project Status

_Refreshed: 2026-07-18. Backend: Python/Flask (`bot/`). Android: Kotlin/Compose (`android/`). Primary sources: `docs/CTO_EXECUTION_REPORT_2026-07-18.md`, `docs/ARCHITECTURE_BLUEPRINT.md`, `MASTER_TODO.md`._

## Completion estimate

| Area | Estimate | Basis |
|---|---|---|
| Backend prediction/data pipeline | ~90% | Frozen core (ADR-005) + full signal/odds/value pipeline. No model work until n≥200 settled picks. |
| Backend API (`bot/api.py`) | ~96% | 52+ routes; worker decomposition **done** (6 workers in `bot/workers/`). Combo EV endpoint shipped. |
| Autonomous mode (scheduler/supervisor) | 100% | 12 scheduled jobs (added weekly-audit Sun 21h). |
| AI assistant | Phase 1 done (flag off) | 6 read-only tools + `mode=analyst`; Android sources chip wired 2026-07-18. |
| Android app | ~87% | Analyst chat mode + combo book_odds EV; Room/DI still deferred (ADR-010). |
| Testing | ~656 backend / ~67 Android | 652 passed / 4 pre-existing failures (OddsPapi merge, telegram digest timing). |
| Release readiness | **READY** | Unchanged since 2026-07-14. |
| Deployment | ~96% | Prod redeployed 2026-07-18 (WSL restart, health OK). `scripts/deploy.sh` available. |
| Architecture & docs | ADR-013 added | 13 ADRs; verdict protocol pre-committed at n≥200. |

**Overall: ~93%.** Binding constraint remains statistical (n≥200 settled picks, ADR-005/ADR-013).

## What changed 2026-07-18 (CTO go-max)

- **CLV closing fix** — event_key lookup in `clv_worker` (root cause of CLV=0 since ~Jul 15).
- **Logging completeness alert** — monitor + Telegram when &lt;90% in 24h.
- **`weekly-audit` CLI** + Sunday scheduler digest + calendar-quiet note.
- **ADR-013** — GO / ITÉRER / NO-GO protocol at n≥200.
- **Off-site backup** scripts + `docs/BACKUP.md`.
- **Android** — analyst mode on chat, tools/sources chips; combo `book_odds` EV.
- **Prod redeploy** — services restarted, `https://api.tennisboss.online/health` OK.

## Broken / watch

1. **4 pre-existing test failures** — `test_api_endpoints2` (OddsPapi merge), `test_telegram_worker` (digest dedup). Not regressions from 2026-07-18 work.
2. **`TENNISBOSS_AI_TOOLS=1`** still off in prod — enable when operator ready.
3. **Historical CLV rows** with `closing_src=last_seen` since Jul 15 — not auto-backfilled; audit optional.

## Frozen core (ADR-005)

`predictor.py`, `calibrate.py`, market blend, `/api/value` gates — **unchanged** in 2026-07-18 execution.

---
See `MASTER_TODO.md` and `docs/CTO_EXECUTION_REPORT_2026-07-18.md` for full detail.
