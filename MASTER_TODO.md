# TennisBoss — Master TODO

_Generated from `PROJECT_STATUS.md` (2026-07-13). Every task references real files found during audit. Status is updated as work completes — see commit history for the authoritative record of what's actually done._

## Critical

### 1. Decide the fate of the dormant `app/` FastAPI package
- **Priority**: Critical
- **Difficulty**: Medium (decision) / High (if fully finishing it) / Low (if cutting it)
- **Estimated time**: 30 min (decision) + 2-4h (execute either path)
- **Dependencies**: None — but blocks a clean answer to "is this repo production-ready"
- **Status**: Not started
- **Files involved**: `app/core/*`, `app/trading/*`, `app/risk/*`, `app/analytics/*`, `app/api/*`, `app/main.py`, `app/STATUS.md`, `bot/clv.py`, `bot/paper_trading.py`, `bot/odds_live_feeder.py` (all import from `app.trading.kelly_dynamic` etc.), `docker-compose.yml`, `requirements.txt`
- **Why it matters**: An entire second backend service exists, is disabled (`tennisboss-quant.service` confirmed `inactive`), untested, and undocumented in `docs/AUDIT.md` — yet production code still imports from it. This is the single largest gap between "the docs say the project is understood" and reality.
- **Recommended path**: cut the production dependency (replace the 3 `app.trading.kelly_dynamic` imports with a small local Kelly-fraction function in `bot/`, since it's presumably a short formula) and delete `app/` entirely, rather than resurrecting and testing a whole second FastAPI service for a feature (auto-bet execution) explicitly out of scope per `docs/AUDIT.md` ("NON utilisée pour du placement automatique de paris"). Requires user sign-off before deleting — this is a "could permanently change project behavior" decision.

### 2. Fix `SurfaceBadge` name collision (Android)
- **Priority**: Critical
- **Difficulty**: Low
- **Estimated time**: 20 min
- **Dependencies**: None
- **Status**: **Done** — imported the correct `ui.components.SurfaceBadge` in `UpcomingScreen.kt`, removed the shadowing local variant (it had zero legitimate callers once the bug was fixed). Verified live on emulator: the "Terre" badge now renders with proper emoji styling in the Matchs tab.
- **Files involved**: `android/app/src/main/java/com/tennisboss/app/ui/components/SurfaceBadge.kt`, `android/app/src/main/java/com/tennisboss/app/ui/UpcomingScreen.kt`
- **Why it matters**: Two Composables with the identical name and different signatures/logic (one keyed on surface type, one on tournament-name substring) compiled today only because of package scoping — and the bug already existed live: `UpcomingScreen.kt:381` passed a real surface value into the wrong function, silently degrading the rendered badge.
- **Fix**: rename one (e.g. `TournamentSurfaceBadge` for the `UpcomingScreen.kt` variant) and update its call site.

## High

### 3. Fix the contradictory tag combination on Dashboard/Matchs cards
- **Priority**: High
- **Difficulty**: Low-Medium (needed a product-semantics read, not just a code fix)
- **Estimated time**: 1h
- **Dependencies**: None
- **Status**: **Done**, pure-copy fix (no backend logic changed):
  1. Traced the actual semantics: `"bonne"` is `predictor.confidence_label` (model confidence, `bot/predictor.py:203-210`) — an axis totally independent of betting value. Fixed by prefixing it "Confiance : bonne" (`ConfidenceBadge.kt`), matching wording already used elsewhere (`LiveScreen.kt:1214`).
  2. Traced "HONEYPOT": it's `weather_profile.py`'s conditions-edge signal ("weather+surface+crowd favor player X by N%, check if the market already reflects it") — **not** a warning that opposes the pick. In the observed screenshot, the honeypot beneficiary was the SAME player the model+market already favored (reinforcing, not contradicting) — the alarming "⚠️ HONEYPOT" wording was the actual bug. Relabeled to "🌤️ Conditions +X%" across all 4 render sites (`ValueCard.kt`, `EdgeScreen.kt`, `UpcomingScreen.kt` x2).
- **Files involved**: `android/app/src/main/java/com/tennisboss/app/ui/components/ConfidenceBadge.kt`, `ValueCard.kt`, `android/app/src/main/java/com/tennisboss/app/ui/EdgeScreen.kt`, `UpcomingScreen.kt`, `bot/predictor.py` (read, not modified), `bot/weather_profile.py` (read, not modified)
- **Verified**: `compileDebugKotlin` + `testDebugUnitTest` pass, confirmed live on emulator — cards now read "Confiance : élevée" / "🌤️ Conditions +10.5%" instead of the ambiguous "bonne" / "⚠️ HONEYPOT".
- **Note**: this fixed the *labeling*, which was the actual defect (the underlying signals were correct all along, just mislabeled in a way that read as contradictory). If a real disagreement case exists (honeypot beneficiary opposite the model/market favorite), that would still show two amber-ish chips that don't visually resolve to a single verdict — worth a follow-up if that combination is ever observed live.

### 4. Add unit tests for the 7 untested Android ViewModels
- **Priority**: High
- **Difficulty**: Medium
- **Estimated time**: 3-4h (all 7) or ~30min each incrementally
- **Dependencies**: None — `FakeApi.kt` pattern already established, just extend it
- **Status**: Not started
- **Files involved**: `android/app/src/test/java/com/tennisboss/app/` (new: `PlayersViewModelTest.kt`, `PlayerCompareViewModelTest.kt`, `PlayerDetailViewModelTest.kt`, `PerformanceViewModelTest.kt`, `EdgeViewModelTest.kt`, `ScannerViewModelTest.kt`, `ChatViewModelTest.kt`), existing `FakeApi.kt`
- **Why it matters**: 7 of 13 ViewModels (54%) have zero test coverage. `ChatViewModel` in particular is the "AI booster" feature the user has repeatedly prioritized this session.

### 5. Delete or repurpose confirmed-orphaned backend modules
- **Priority**: High
- **Difficulty**: Low
- **Estimated time**: 30 min
- **Dependencies**: Requires user confirmation before deleting (see project convention: never delete without confirming intent)
- **Status**: Not started
- **Files involved**: `bot/ai_resolver.py` (401 lines, zero references anywhere including tests), `bot/alerts.py` (145 lines, zero references — dangerously similar name to the actually-used `bot/realtime_alerts.py`), `bot/telegram_handler.py`, `bot/telegram_poll.py` (two competing, both unused, Telegram integrations)
- **Why it matters**: Dead code with a near-duplicate live module name (`alerts.py` vs `realtime_alerts.py`) is a real trap for a future contributor (human or AI) who greps for "alerts" and edits the wrong file.

## Medium

### 6. Extract duplicated Android Composables
- **Priority**: Medium
- **Difficulty**: Low
- **Estimated time**: 30 min
- **Dependencies**: None
- **Status**: **Done** — `StatCard` extracted to `android/app/src/main/java/com/tennisboss/app/ui/components/StatCard.kt`, both `EdgeScreen.kt`/`PerformanceScreen.kt` call sites updated. `RecentRow` investigated and found NOT to be a duplicate (different data types `ClvRecent`/`SettledRecent`, both already file-private, no collision risk) — no action needed, see `CLEANUP_REPORT.md`.
- **Files involved**: `android/app/src/main/java/com/tennisboss/app/ui/components/StatCard.kt` (new), `EdgeScreen.kt`, `PerformanceScreen.kt`
- **Verified**: `compileDebugKotlin` + `testDebugUnitTest` pass (BUILD SUCCESSFUL, 23/23 tests).

### 7. Reduce silent exception swallowing in `bot/api.py`
- **Priority**: Medium
- **Difficulty**: Medium (needs care not to change behavior, just add visibility)
- **Estimated time**: 1-2h
- **Dependencies**: None
- **Status**: Not started
- **Files involved**: `bot/api.py` (36 occurrences of `except Exception: pass`, e.g. lines 169, 184, 191, 933, 1072, 1084, 1149 per audit sampling)
- **Fix**: add a `log(f"...", "WARN")` inside each, at minimum — most already have this pattern elsewhere in the file (e.g. the OddsPapi/ESPN merge blocks in `api_upcoming()`), so this is about consistency, not new infrastructure.

### 8. Bump Compose BOM and evaluate `security-crypto` alpha dependency
- **Priority**: Medium
- **Difficulty**: Low (bump) / Medium (crypto lib — needs testing token storage still works)
- **Estimated time**: 1h
- **Dependencies**: None
- **Status**: Not started
- **Files involved**: `android/app/build.gradle.kts`, `android/app/src/main/java/com/tennisboss/app/TokenManager.kt`
- **Why it matters**: Shipping an alpha-versioned crypto library (`androidx.security:security-crypto:1.1.0-alpha06`) for token storage in a production app is a stability risk if Google ships a breaking change; Compose BOM is over a year stale.

### 9. Document the `db.connect()`-per-call convention
- **Priority**: Medium
- **Difficulty**: Low
- **Estimated time**: 15 min
- **Dependencies**: None
- **Status**: Not started
- **Files involved**: `bot/db.py:230-242` (`connect()` docstring/comment)
- **Why it matters**: The `mcp_feeder.py` performance bug (fixed 2026-07-13) happened because this pattern is fine for ~100 low-frequency call sites but a real footgun inside a loop over many rows. A one-line warning comment prevents the next feeder from repeating it — audit confirmed no other instance exists today, so this is purely preventive.

## Low

### 10. Add Compose `testTag`/semantics to key interactive elements
- **Priority**: Low
- **Difficulty**: Medium (touches many files, low risk per file)
- **Estimated time**: 2-3h for the highest-traffic screens (Dashboard, Chat, bottom nav)
- **Dependencies**: None
- **Status**: Not started
- **Files involved**: `android/app/src/main/java/com/tennisboss/app/ui/*.kt`, `MainActivity.kt` (bottom nav)
- **Why it matters**: Confirmed hands-on this session — zero `testTag`s exist anywhere, so UI Automator/Compose UI testing has no stable target and must rely on raw text or hand-computed pixel bounds (fragile, breaks on any copy change or layout shift).

### 11. Improve accessibility (`contentDescription`) coverage
- **Priority**: Low
- **Difficulty**: Low
- **Estimated time**: 1-2h
- **Dependencies**: None
- **Status**: Not started
- **Files involved**: `DashboardScreen.kt`, `PlayersScreen.kt`, `MatchDetailScreen.kt` (icon-heavy screens with signal cards, badges, chips)
- **Why it matters**: Only 5 `contentDescription` usages found across the sampled screens, 4 of them explicitly `null`.

### 12. Re-confirm Room/offline is still deliberately out of scope
- **Priority**: Low
- **Difficulty**: N/A (decision, not code)
- **Estimated time**: 5 min conversation
- **Dependencies**: None
- **Status**: Not started (deliberately deferred per prior session decisions)
- **Files involved**: N/A — architectural decision only
- **Why it matters**: Just a periodic sanity check that this is still the right call, not a bug.

---

## Execution order (this session, if proceeding autonomously)

Given #1 (the `app/` package) and #5 (deleting orphaned modules) both involve deleting code and therefore need explicit user sign-off before acting (per this project's standing conventions on destructive/hard-to-reverse actions), the safe autonomous execution order is:

1. #2 (SurfaceBadge rename) — pure rename, zero behavior change, safe to do immediately.
2. #6 (extract duplicated Composables) — pure refactor, safe.
3. #9 (document db.connect() convention) — pure comment, safe.
4. #3 (Dashboard tag contradiction) — needs a product-copy decision folded in; will propose the specific fix and apply the less risky interpretation, flagging it for override.
5. #7 (silent exception logging) — mechanical, safe, but touches 36 call sites — will do in one focused pass with tests re-run after.
6. #4 (ViewModel tests) — additive only, safe, but time-consuming; will do as many as fit.
7. #8 (dependency bumps) — will do the Compose BOM bump (low risk) but leave the alpha crypto swap for explicit user approval (touches token storage — higher blast radius).
8. #1 and #5 — will present findings and the recommended path, and wait for explicit go-ahead before deleting anything, per this project's established pattern this session (destructive actions get a confirm step even under a broad "continue" instruction).
