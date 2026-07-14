# TennisBoss — Project Status

_Audit date: 2026-07-14. Backend: Python/Flask (`bot/`). Android: Kotlin/Compose (`android/`). This supersedes nothing in `docs/AUDIT.md` (2026-07-11) or `android/ANDROID_AUDIT.md` — it verifies both against the current repo state and adds what they missed._

## Completion estimate

| Area | Estimate | Basis |
|---|---|---|
| Backend prediction/data pipeline | ~90% | Elo, form, fatigue, rest-days, opponent quality, clutch, H2H, service/return, odds/value all wired and tested. WTA clutch stats gap closed 2026-07-12/13 via `bot/mcp_feeder.py`. |
| Backend API (`bot/api.py`) | ~95% | ~45 routes, centralized auth, rate limiting where it matters (odds quota), Swagger/OpenAPI. |
| Autonomous mode (scheduler/supervisor) | 100% | 7 scheduled jobs, systemd services, all confirmed active. |
| Android app | ~85% | 13 screens/ViewModels, MVVM, real error/loading states. No Room/offline (deliberately deferred). |
| Testing | Backend 357 tests passing / Android 54 tests passing | See TEST_REPORT.md — 13/13 Android ViewModels covered. |
| Release readiness | **NOT READY** | See `RELEASE_AUDIT.md` (2026-07-14, Phase 11). `assembleRelease` was broken (fixed, commit `cf46a5e`) but a real crash-on-launch bug remains for Android 7.0/7.1 (API 24-25) devices — `minSdk=24` promises support the code doesn't deliver (`java.time.*` used without core library desugaring). Decision required before shipping: enable desugaring, or raise `minSdk` to 26. |
| Deployment (Docker/systemd/CI) | ~95% | Working GitHub Actions CI (backend pytest + Android unit tests), Dockerfile + compose, systemd units, DEPLOYMENT.md. |
| Documentation hygiene | ~80% | `docs/AUDIT.md` didn't know about the dormant `app/` FastAPI service (see below) until this audit — **since removed**, closing that gap. |

**Overall: ~89% toward a stable, production-usable app**, but **not release-ready as of 2026-07-14** — see `RELEASE_AUDIT.md` for the specific blocker and the 3 options to resolve it. With Android ViewModel test coverage complete (13/13) and the highest-traffic `testTag` coverage done, the remaining gap to RC1 is now concentrated in one real correctness decision (minSdk/desugaring), not missing functionality.

## Working features (verified this session, not just claimed)

- Dashboard, Predict, Chat all manually driven on the Android emulator (screenshots taken, real network calls to the live backend) — all three work end-to-end with real data.
- Chat correctly grounds answers in real DB state and labels them (`📊 Basé sur nos données (ELO, forme, H2H)`), confirming the anti-hallucination work from earlier this session is live.
- `/api/upcoming` correctly prioritizes ATP/WTA over Challenger/ITF under the `limit` cap (fixed 2026-07-12).
- WTA clutch signal (break points saved/faced) now fires on real data (e.g., a real player flagged "fragile sur balles de break" from live DB stats).
- Player-identity dedup: 635 duplicate profiles merged in production (`Andreeva M.` / `Mirra Andreeva` no longer split ELO/EMA across two profiles), with a safety guard that correctly refused to merge genuinely distinct people sharing a surname (Nakashima brothers, Tsitsipas brothers, three different "Wang"s).

## Broken / genuinely risky

1. **`SurfaceBadge` name collision** (Android) — two different Composables named identically: `ui/components/SurfaceBadge.kt` (keyed on surface: clay/hard/grass) vs. `ui/UpcomingScreen.kt:905` (keyed on tournament-name substring). Compiles fine today because of package scoping, but importing the wrong one silently gives wrong colors/logic. **Real bug risk, not yet a confirmed live bug.**
2. **Dashboard "Meilleures opportunités" card shows contradictory tags** — observed live on-device: a match tagged `bonne` (good) sits next to `Pas de value` (no value) and a `HONEYPOT +23.0%` warning on the same card. Confusing to a real user; needs a UX/copy decision, not just a bug fix (see UI_REPORT.md).
3. ~~Undocumented dormant `app/` FastAPI package~~ — **removed 2026-07-13** with user sign-off, after confirming no reachable code depended on it (`bot/clv.py`'s import already had a working fallback; the two `bot/` files with hard imports were themselves dead code). Restore point: git tag `pre-app-removal-backup`. See MASTER_TODO.md #1.

## Missing features (deliberately deferred, not bugs)

- Room/offline caching on Android (every screen reloads from network on each visit — acceptable for a betting-value app where staleness is actively bad, per prior session decision, but worth re-confirming with the user before RC1).
- `bot/agent_router.py`'s "OpenClaw sub-agent" spawn feature is stubbed and incomplete (2 TODOs, `bot/agent_router.py:84,96`) — not wired to anything failing, just unfinished.

## Technical debt

- **Orphaned modules, confirmed zero references anywhere** (safe to delete or explicitly document as future work): `bot/ai_resolver.py` (401 lines), `bot/alerts.py` (145 lines — dangerously similar name to the actually-used `bot/realtime_alerts.py`), `bot/telegram_handler.py` + `bot/telegram_poll.py` (two competing unused Telegram integrations).
- ~~Heavy `except Exception: pass` silent-swallow pattern in `bot/api.py` (31 occurrences)~~ — **fixed this session**: 26 now log a specific `WARN` message, 3 left intentionally silent with a documented reason (see `MASTER_TODO.md` #7). Not yet deployed to the live service (needs a restart).
- Android: `StatCard` duplicated byte-for-byte in `EdgeScreen.kt:183` and `PerformanceScreen.kt:320`; `RecentRow` likely duplicated the same way.
- `androidx.security:security-crypto:1.1.0-alpha06` — still alpha, used for token storage (`TokenManager.kt`) in what is otherwise a production app.
- ~~Compose BOM (`2024.09.03`) is over a year old~~ — **bumped to `2026.06.01` 2026-07-14**, verified against real Maven Google metadata, zero compile errors, confirmed on-device with no visual regression.
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

- `assembleDebug`, `compileDebugKotlin`, `testDebugUnitTest` all succeed cleanly. Backend test suite (357 tests, post-`app/`-removal) passes in ~30s.
- ~~`assembleRelease`/`bundleRelease` were completely broken~~ — **fixed 2026-07-14** (commit `cf46a5e`): `lintVitalRelease` failed on `InvalidFragmentVersionForActivityResult` (Google Play Services transitively pulls `androidx.fragment:1.1.0`, too old for the `ActivityResult` APIs used in `MainActivity.kt`). Fixed by pinning `androidx.fragment:fragment-ktx:1.8.9` as a direct dependency. Verified: `assembleRelease` now succeeds (confirmed it failed before the fix, and succeeds after, twice).
- **Full `lintDebug` reveals a real crash bug, separate from the above**: 44 `NewApi` errors — `java.time.*` (used throughout `DateUtils.kt`/`UpcomingScreen.kt`, critical-path date formatting on Dashboard/Upcoming/MatchDetail) requires API 26, but `minSdk=24` with no core library desugaring configured. This crashes immediately on real Android 7.0/7.1 devices. Does not block `assembleRelease` (not in the `lintVital` subset), so left for explicit decision rather than silently fixed — see `RELEASE_AUDIT.md` for the 3 options (desugaring recommended). This is the current release blocker.

---
See `MASTER_TODO.md` for the prioritized, file-referenced action list derived from this audit.
