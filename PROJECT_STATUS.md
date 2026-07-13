# TennisBoss — Project Status

_Audit date: 2026-07-13. Backend: Python/Flask (`bot/`). Android: Kotlin/Compose (`android/`). This supersedes nothing in `docs/AUDIT.md` (2026-07-11) or `android/ANDROID_AUDIT.md` — it verifies both against the current repo state and adds what they missed._

## Completion estimate

| Area | Estimate | Basis |
|---|---|---|
| Backend prediction/data pipeline | ~90% | Elo, form, fatigue, rest-days, opponent quality, clutch, H2H, service/return, odds/value all wired and tested. WTA clutch stats gap closed 2026-07-12/13 via `bot/mcp_feeder.py`. |
| Backend API (`bot/api.py`) | ~95% | ~45 routes, centralized auth, rate limiting where it matters (odds quota), Swagger/OpenAPI. |
| Autonomous mode (scheduler/supervisor) | 100% | 7 scheduled jobs, systemd services, all confirmed active. |
| Android app | ~85% | 13 screens/ViewModels, MVVM, real error/loading states. No Room/offline (deliberately deferred). |
| Testing | Backend 403 tests passing / Android 23 tests passing | See TEST_REPORT.md — coverage is uneven (7 of 13 Android ViewModels untested). |
| Deployment (Docker/systemd/CI) | ~95% | Working GitHub Actions CI (backend pytest + Android unit tests), Dockerfile + compose, systemd units, DEPLOYMENT.md. |
| Documentation hygiene | ~70% | `docs/AUDIT.md` didn't know about the dormant `app/` FastAPI service (see below) — a real, material gap in the project's own understanding of itself until this audit. |

**Overall: ~85% toward a stable, production-usable app.** The gap to "RC1" is concentrated in test coverage, one real UI bug, a handful of dead-code/duplication cleanups, and a decision about the dormant `app/` package — not in missing core functionality.

## Working features (verified this session, not just claimed)

- Dashboard, Predict, Chat all manually driven on the Android emulator (screenshots taken, real network calls to the live backend) — all three work end-to-end with real data.
- Chat correctly grounds answers in real DB state and labels them (`📊 Basé sur nos données (ELO, forme, H2H)`), confirming the anti-hallucination work from earlier this session is live.
- `/api/upcoming` correctly prioritizes ATP/WTA over Challenger/ITF under the `limit` cap (fixed 2026-07-12).
- WTA clutch signal (break points saved/faced) now fires on real data (e.g., a real player flagged "fragile sur balles de break" from live DB stats).
- Player-identity dedup: 635 duplicate profiles merged in production (`Andreeva M.` / `Mirra Andreeva` no longer split ELO/EMA across two profiles), with a safety guard that correctly refused to merge genuinely distinct people sharing a surname (Nakashima brothers, Tsitsipas brothers, three different "Wang"s).

## Broken / genuinely risky

1. **`SurfaceBadge` name collision** (Android) — two different Composables named identically: `ui/components/SurfaceBadge.kt` (keyed on surface: clay/hard/grass) vs. `ui/UpcomingScreen.kt:905` (keyed on tournament-name substring). Compiles fine today because of package scoping, but importing the wrong one silently gives wrong colors/logic. **Real bug risk, not yet a confirmed live bug.**
2. **Dashboard "Meilleures opportunités" card shows contradictory tags** — observed live on-device: a match tagged `bonne` (good) sits next to `Pas de value` (no value) and a `HONEYPOT +23.0%` warning on the same card. Confusing to a real user; needs a UX/copy decision, not just a bug fix (see UI_REPORT.md).
3. **Undocumented dormant `app/` FastAPI package** (~34 files: `app/core`, `app/trading`, `app/risk`, `app/analytics`) — a full quant/trading engine (Kelly sizing, drawdown alerts, portfolio Greeks, auto-bet engine) that `docs/AUDIT.md` never mentioned, disabled via systemd (`tennisboss-quant.service`, confirmed `inactive`), untested, but **still imported from production code** (`bot/clv.py`, `bot/paper_trading.py`, `bot/odds_live_feeder.py` pull from `app.trading.kelly_dynamic`). This is a real architectural loose end: either finish and test it, or cut the production import and delete it. See MASTER_TODO.md #1.

## Missing features (deliberately deferred, not bugs)

- Room/offline caching on Android (every screen reloads from network on each visit — acceptable for a betting-value app where staleness is actively bad, per prior session decision, but worth re-confirming with the user before RC1).
- `bot/agent_router.py`'s "OpenClaw sub-agent" spawn feature is stubbed and incomplete (2 TODOs, `bot/agent_router.py:84,96`) — not wired to anything failing, just unfinished.

## Technical debt

- **Orphaned modules, confirmed zero references anywhere** (safe to delete or explicitly document as future work): `bot/ai_resolver.py` (401 lines), `bot/alerts.py` (145 lines — dangerously similar name to the actually-used `bot/realtime_alerts.py`), `bot/telegram_handler.py` + `bot/telegram_poll.py` (two competing unused Telegram integrations).
- ~~Heavy `except Exception: pass` silent-swallow pattern in `bot/api.py` (31 occurrences)~~ — **fixed this session**: 26 now log a specific `WARN` message, 3 left intentionally silent with a documented reason (see `MASTER_TODO.md` #7). Not yet deployed to the live service (needs a restart).
- Android: `StatCard` duplicated byte-for-byte in `EdgeScreen.kt:183` and `PerformanceScreen.kt:320`; `RecentRow` likely duplicated the same way.
- `androidx.security:security-crypto:1.1.0-alpha06` — still alpha, used for token storage (`TokenManager.kt`) in what is otherwise a production app.
- Compose BOM (`2024.09.03`) is over a year old relative to today; likely several releases behind.
- Zero Compose `testTag`/semantics anywhere in the Android UI — makes any future UI-automation testing fragile (confirmed hands-on this session: every interaction had to be located by raw text or hand-computed pixel coordinates via `uiautomator dump`).

## Risks

- LAN-exposed API without `TENNISBOSS_API_TOKEN` set logs a warning but still serves unauthenticated (`bot/api.py:3182-3186`) — intentional per code comment, but worth re-confirming that's still the desired behavior before wider deployment.
- No proven statistical edge yet (small settled-picks sample) — this is a modeling/data reality, not a code bug, and the app's own copy already reflects this honestly ("aide à la décision", not "gagnant garanti").
- Single-machine (WSL) deployment — a hardware failure interrupts service; docker-compose exists for fast redeploy to a VPS if needed.

## Performance issues

- One confirmed-and-fixed instance this session (`bot/mcp_feeder.py` opening ~12,000 individual SQLite connections in a loop — fixed, now ~2s instead of 15+ min). A dedicated audit pass found **no other instance** of this pattern anywhere else in `bot/*.py` — it was isolated, not systemic.
- No O(n²)-or-worse hot path found on any per-request code path (`predictor.py`, `features.py`, `elo.py` — all O(n) full-history rebuilds are confined to startup/background jobs, never per-request).
- No Compose recomposition-storm patterns found in the 3 screens sampled (Dashboard, MatchDetail, Value).

## Security issues

- No secrets ever committed to git history (`.env` verified never committed, `git log --all -- .env` empty).
- No hardcoded secrets found in `bot/*.py` or Android Kotlin.
- Auth (`X-API-Token`) enforced centrally via `before_request`, not per-route — no risk of a forgotten route.
- Android: `usesCleartextTraffic="false"` enforced in release, debug-only exceptions correctly scoped to `src/debug/`.
- The one open item is the alpha crypto dependency noted above under Technical Debt.

## API issues

- None structural. Rate limiting is deliberately scoped to the 3 odds-consuming endpoints (protecting the odds-api.io quota), not applied blanket — this is a design decision, not an oversight, confirmed by sampling other routes.

## Build issues

- None. `./gradlew assembleDebug`, `compileDebugKotlin`, and `testDebugUnitTest` all succeed cleanly as of this audit. Backend test suite (403 tests) passes in ~30s.

---
See `MASTER_TODO.md` for the prioritized, file-referenced action list derived from this audit.
