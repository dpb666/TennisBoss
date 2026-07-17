# TennisBoss — Project Status

_Refreshed: 2026-07-16 (evening). Backend: Python/Flask (`bot/`). Android: Kotlin/Compose (`android/`). Primary sources: `docs/DEVELOPMENT_AUDIT_2026-07-16.md` (full audit), `docs/ARCHITECTURE_BLUEPRINT.md` (permanent architecture reference + ADRs), `MASTER_TODO.md` (work ledger). The previous version of this file (2026-07-14) is superseded; its release-readiness verdict still stands._

## Completion estimate

| Area | Estimate | Basis |
|---|---|---|
| Backend prediction/data pipeline | ~90% | Frozen core (ADR-005) + full signal/odds/value pipeline. No model work until n≥200 settled picks (currently n≈97). |
| Backend API (`bot/api.py`) | ~95% | 52+ routes, centralized auth, OpenAPI/Swagger. **Decomposition in progress** (2026-07-16): daemon loops being extracted to `bot/workers/` (6 workers, see `docs/API_DECOMPOSITION.md`) — uncommitted WIP at refresh time. |
| Autonomous mode (scheduler/supervisor) | 100% | 11 scheduled jobs + janitor (state tmp-file pruning) added 2026-07-16. |
| AI assistant | Phase 1 done (flag off) | 6 read-only tools + `mode=analyst` shipped 2026-07-16; `TENNISBOSS_AI_TOOLS=1` not yet enabled in prod. Phases 2–5 planned (`docs/AI_ASSISTANT_ARCHITECTURE.md`). |
| Android app | ~85% | 14 screens/ViewModels (incl. ComboBuilder), MVVM, no Repository/DI layer yet (ADR-010 gates offline features on it). |
| Testing | ~613 backend / ~64 Android | 2026-07-16 21:20 run: 610 passed, 2 documented Windows-only file-lock flakes (`test_backup`, `test_mantennisdata_feeder` — pass on Linux/CI), 1 failure in the in-flight worker-extraction WIP. |
| Release readiness | **READY** (since 2026-07-14) | Both former blockers fixed and verified (`RELEASE_AUDIT.md`). Deferred items unchanged (alpha `security-crypto`, R8 off). |
| Deployment (Docker/systemd/CI) | ~95% | CI (pytest + Android unit), compose, systemd. **New 2026-07-16:** `scripts/deploy.sh` (pull → restart → health check → auto-rollback) + `deployment_history` table — closes the prod/repo drift risk once adopted. |
| Architecture & docs | Blueprint ratified-pending | `docs/ARCHITECTURE_BLUEPRINT.md` + 12 ADRs (`docs/adr/`). Human ratification of ADRs pending. |

**Overall: ~92% toward a stable, production-usable single-operator product.** The binding constraint is statistical, not technical: `bet_history` needs n≥200 settled picks before any edge verdict or model unfreeze (ADR-005).

## What changed since 2026-07-14 (verified, not just claimed)

- **AI Assistant Phase 1 + `mode=analyst`** shipped behind `TENNISBOSS_AI_TOOLS` (default off) — `ai/chat/` package, 6 read-only tools, frozen-boundary guard tests.
- **Bet Builder** (markets, EV, combo endpoint + Android Combo tab).
- **Architecture Blueprint + ADR log** created (2026-07-16): bounded contexts, strangler-fig migration plan (ADR-004), debt register D-1..D-18, risk register R-1..R-11, 12-month roadmap, AI-agent ownership matrix.
- **Q3 roadmap slices landed 2026-07-16:** `compare-engines` CLI wired (closes documented gap D-9); state janitor pruning `tmp*.json.corrupt` leftovers (D-7 — 86 zero-byte files found); log rotation 10 MB × 3 (D-18); `deployment_history` table + `run.py record-deploy` + `scripts/deploy.sh` with health-check and auto-rollback (Q3 #5, risk R-6).
- **API decomposition Phase 1 (in progress, parallel agent):** value scanner, settlement, CLV, inplay-settlement, match-refresh, telegram loops extracted from `bot/api.py` into `bot/workers/` with per-worker tests — see `docs/API_DECOMPOSITION.md` and the MASTER_TODO ledger entry.

## Broken / genuinely risky

1. **Uncommitted multi-lane work tree** — blueprint slices + worker extraction are both uncommitted at refresh time. Needs two clean commits (one per lane) once the worker lane stabilizes. (Debt D-14.)
2. **Prod not yet redeployed** with post-15/07 code: AI tools flag, analyst mode, Bet Builder, janitor, rotation, workers — all need a service restart (human-triggered; use `scripts/deploy.sh` going forward).
3. **`state/` still produces `tmp*.json.corrupt` files** (newest seen 2026-07-16 19:21) — the janitor cleans them up after 7 days, but the *producer* is likely an older write path still running in the WSL prod processes; will resolve itself at next prod redeploy, worth confirming after.
4. **LAN unauthenticated-serve fallback** when `TENNISBOSS_API_TOKEN` unset — default-deny in prod (Q3 #3) is designed (blueprint §11.1) but **not yet implemented** (deferred while `bot/api.py` is under active parallel edit).

## Missing features (deliberately deferred, not bugs)

- Room/offline caching + chat persistence on Android — gated on the Repository/DI seam (ADR-010).
- `TENNISBOSS_AI_TOOLS=1` in prod + Android analyst-mode UI (`tools_called` sources chip) — audit ROI ranks #1–2.
- Knowledge base (`project_knowledge.db`, FTS5) — roadmap Q4 #8.
- Admin-token plane split + default-deny prod auth — roadmap Q3 #3 (see above).

## Technical debt

Tracked as D-1..D-18 in `docs/ARCHITECTURE_BLUEPRINT.md` §16 — the authoritative register. Closed since the blueprint was written: D-7 (janitor), D-9 (compare-engines), D-18 (log rotation); D-1/D-3 (api.py god-module / embedded daemons) actively being reduced by the worker extraction; D-14 (work-tree drift) mitigated by `deployment_history` once adopted, closed by committing the current lanes.

## Risks

Tracked as R-1..R-11 in `docs/ARCHITECTURE_BLUEPRINT.md` §17. Highest-likelihood items unchanged: upstream data-source death (R-1, Sackmann already gone once), single-host total loss (R-2 — off-host backups still pending, roadmap Q4 #11), no proven statistical edge yet (R-4 — expected until n≥200).

## Security posture

- No secrets in git history (verified 2026-07-14, unchanged).
- Central `before_request` auth; rate limiting scoped to odds-quota routes.
- Open items: `firebase-adminsdk.json` still inside `state/` (move to `secrets/` — Q3 #2, partially done: janitor yes, key move pending); alpha `security-crypto` on Android; no chat-route rate limit (D-17).

---
See `MASTER_TODO.md` for the dated, file-referenced work ledger (both agent lanes), and `docs/ARCHITECTURE_BLUEPRINT.md` §18 for the 12-month roadmap this work follows.
