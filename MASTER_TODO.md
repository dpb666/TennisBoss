# TennisBoss — Master TODO

_Generated from `PROJECT_STATUS.md` (2026-07-13). Every task references real files found during audit. Status is updated as work completes — see commit history for the authoritative record of what's actually done._

## Critical

### 0. Core library desugaring for java.time on minSdk 24-25 (release blocker)
- **Priority**: Critical
- **Difficulty**: Low
- **Estimated time**: 15 min
- **Dependencies**: None
- **Status**: **Done — closed 2026-07-14.** Decision made: enable core library desugaring (option A), `minSdk` stays at 24. Found during `RELEASE_AUDIT.md` (Phase 11): `lintDebug` reported 44 `NewApi` errors — `java.time.*` (`LocalDate`, `ZonedDateTime`, `DateTimeFormatter`, `ZoneId`) used throughout `DateUtils.kt` and `UpcomingScreen.kt` requires API 26, but `minSdk = 24` had no desugaring configured — a guaranteed crash on real Android 7.0/7.1 devices the moment Dashboard/Upcoming/MatchDetail render a date.
- **Fix applied** (`android/app/build.gradle.kts`): `compileOptions { isCoreLibraryDesugaringEnabled = true }` + `coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")` (latest stable, verified via `maven.google.com`, compatible with AGP 9.2.1). Zero changes to `DateUtils.kt`/`UpcomingScreen.kt` — the whole point of desugaring is that the existing `java.time.*` code works as-is.
- **Verified**:
  - `lintDebug`: **0 errors** (was 45 errors), 102 warnings + 1 hint unchanged (pre-existing, unrelated, non-blocking).
  - `compileDebugKotlin`, `assembleDebug`, `assembleRelease`, `bundleRelease`: all `BUILD SUCCESSFUL`.
  - `testDebugUnitTest`: 54/54 pass (forced fresh run, not cached).
  - On-device: installed the desugared APK, exercised Dashboard, MatchDetail, Matchs (À venir — including the `DayPicker`'s French day-name formatting, the exact code path that was crashing), Value (4 sub-tabs), Chat — all render correctly, zero visual regression, zero crash in logcat across the full pass.
- **Files involved**: `android/app/build.gradle.kts`
- **Why it matters**: this was the last real release blocker. With this closed, `PROJECT_STATUS.md`'s "Release readiness: NOT READY" should be re-evaluated (see there).

### 1. Decide the fate of the dormant `app/` FastAPI package
- **Priority**: Critical
- **Status**: **Done — removed**, with explicit user sign-off (2026-07-13).
- **What was found on closer inspection** (corrected the initial framing): `bot/clv.py`'s import of `app.trading.kelly_dynamic` was already wrapped in `try/except Exception` with a working local fallback — it was inert in production, not a real dependency. `bot/paper_trading.py` and `bot/odds_live_feeder.py` had hard, unconditional imports from `app/` with no fallback, but neither was itself imported by anything else in the codebase — they were dead code, not live callers.
- **What was removed**: `app/` (~34 files), `bot/paper_trading.py`, `bot/odds_live_feeder.py`, their dedicated test files (`tests/test_analytics.py`, `tests/test_risk_advanced.py`, `tests/test_trading.py` — tested `app/` exclusively, would otherwise break test collection), `run.py`'s `cmd_quant` + `quant` subparser, `systemd/tennisboss-quant.service`, `fastapi`/`uvicorn`/`pydantic` from `requirements.txt` (confirmed unused elsewhere), and `QUICK_START.md` (entirely about the removed service). `DEPLOYMENT.md` and `TELEGRAM_SETUP.md` updated to remove stale instructions.
- **Safety net**: annotated git tag `pre-app-removal-backup` created before any deletion — `git checkout pre-app-removal-backup` restores everything.
- **Verified**: `python3 -m pytest` 357/357 passed (down from 403 — the 46 removed tests belonged to the 3 deleted `app/`-only test files, not a regression), `python3 -c "import run"` and `import bot.api` both succeed.
- **Left untouched, flagged for separate review**: `REALTIME-ROI.md` (331-line doc, partially describes still-valid `bot/realtime.py` functionality mixed with the removed FastAPI serving layer — needs a proper rewrite, not a mechanical find-replace) and `AI_CHAT_AUDIT.md`/`RELEASE_NOTES_CHAT.md` (one diagram label and a historical release note respectively — lower priority, and the latter shouldn't be revised as history).

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

### 3b. Fix `"1er set jouable : null"` in Matchs à venir
- **Priority**: High (found live on a real device in production, not a hypothetical)
- **Difficulty**: Low
- **Estimated time**: 10 min
- **Dependencies**: None
- **Status**: **Done**, commit `b96e478`. `pred.favorite` (`String?`) is intentionally `null` for near-50/50 matches (`abs(p1-p2) < 0.04`, `bot/predictor.py:229-231`) — a genuine "too close to call" signal, not a bug. But `target_160`/`fair_odds` are computed independently and stay set in that case, and `UpcomingScreen.kt:455`'s "🎯 1er set jouable" line interpolated `pred.favorite` without checking it was non-null first — so it rendered the literal string `"null"` in production (`"1er set jouable : null @ cote juste 1.99 (≥1.60)"`). Fixed by adding `&& pred.favorite != null` to the guard, matching the convention already used correctly for the same field in `LiveScreen.kt` (`pred.favorite ?: return`).
- **Follow-up scan**: dispatched a targeted search across every nullable field in `data/ApiModels.kt` against every `Text(...)`/string-interpolation site in `ui/*.kt` and `ui/components/*.kt` for the same unguarded-null pattern. **No other instances found** — every other nullable-field interpolation in the codebase is already correctly guarded (`?.let{}`, `?:`, or an enclosing `if (x != null)`). This was an isolated miss, not a systemic pattern.
- **Files involved**: `android/app/src/main/java/com/tennisboss/app/ui/UpcomingScreen.kt`
- **Verified**: `compileDebugKotlin` + `testDebugUnitTest` (54/54) pass, confirmed on the real device that the bug no longer reproduces.

### 4. Add unit tests for the 7 untested Android ViewModels
- **Priority**: High
- **Difficulty**: Medium
- **Estimated time**: 3-4h (all 7) or ~30min each incrementally
- **Dependencies**: None — `FakeApi.kt` pattern already established, just extend it
- **Status**: **Done — 7 of 7**. `ChatViewModelTest.kt` (6 tests) added first as the highest-priority gap. Then all 6 remaining: `PlayersViewModelTest.kt` (4), `PlayerDetailViewModelTest.kt` (4), `PlayerCompareViewModelTest.kt` (5), `PerformanceViewModelTest.kt` (4), `EdgeViewModelTest.kt` (3), `ScannerViewModelTest.kt` (4) — 24 more tests, 53 total across all ViewModel test files.
- **What this required**: extending `FakeApi.kt` with configurable responses for `players()`, `historyDates()`, `historyByDate()`, `intelligenceStats()`, `learnerStats()`, `scannerStatus()`. Also — these 6 ViewModels hardcode `withContext(Dispatchers.IO)`/`async(Dispatchers.IO)` (unlike `PredictViewModel`/`UpcomingViewModel`/`ValueViewModel`, which already had an injectable `internal var io: CoroutineDispatcher` seam for tests). Applied the same established seam to `PlayersViewModel`, `PlayerCompareViewModel`, `PlayerDetailViewModel`, `PerformanceViewModel`, `EdgeViewModel`, `ScannerViewModel` so tests can pin IO to the `StandardTestDispatcher` instead of racing a real background thread pool against `advanceUntilIdle()`.
- **Real bug found and fixed in the process**: `EdgeViewModel.load()` had the same un-scoped `async{}` bug that `DashboardViewModel`/`MatchDetailViewModel` were already fixed for this session (see `ARCHITECTURE_REVIEW.md`) — `async(io){ api.clv() }` launched directly under `viewModelScope.launch` instead of inside a `coroutineScope{}` meant a CLV failure could race past the enclosing `try/catch` instead of being caught by it. Only surfaced because the new "un echec du CLV fait passer l'ecran entier en Error" test exercised that exact path and failed with a raw uncaught `RuntimeException` instead of a clean assertion failure. Fixed the same way as before: wrapped the three `async{}` calls in `coroutineScope{}`.
- `uploadFile()` (Chat) deliberately NOT tested — needs a real `android.content.Context`, would require Robolectric; out of scope for this pass.
- **Files involved**: `android/app/src/test/java/com/tennisboss/app/{Chat,Players,PlayerDetail,PlayerCompare,Performance,Edge,Scanner}ViewModelTest.kt` (new), `FakeApi.kt` (extended), `PlayersViewModel.kt`/`PlayerCompareViewModel.kt`/`PlayerDetailViewModel.kt`/`PerformanceViewModel.kt`/`EdgeViewModel.kt`/`ScannerViewModel.kt` (added `io` seam; `EdgeViewModel.kt` also got the `coroutineScope{}` fix)
- **Verified**: `testDebugUnitTest` — 53/53 pass, confirmed via the JUnit XML reports (not just BUILD SUCCESSFUL).

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
- **Difficulty**: Medium (needed care not to change behavior, just add visibility)
- **Estimated time**: 1-2h
- **Dependencies**: None
- **Status**: **Done** — added `log(f"...", "WARN")` with a specific message to 26 of the 31 confirmed sites (data loading, predictions, DB writes, weather/honeypot analysis, market snapshots, Telegram send/poll). 3 sites deliberately left silent with a documented reason: `api.py:252` (`_clean_tournament`'s `ast.literal_eval` fallback — expected/frequent parse-miss on malformed input, not an error) and `api.py:522` (`_toronto_tz`'s `zoneinfo` fallback — already has a working degraded path, not silent data loss) and the Telegram `/clear` endpoint (`api.py` `_tg_poll_loop`, hits the dormant `app/` service on port 8001 — fails systematically while that service is disabled per item #1, so a WARN log there would just be noise about a known, not unexpected, condition; documented inline instead).
- **Files involved**: `bot/api.py` (26 sites edited: `_load_state`, `api_predict`, `api_upcoming`, `api_live`, `api_inplay_best`, `_bet_builder`, settlement/calibration endpoints, `/api/value`, the value-scanner background loop, the inplay-settle loop, `_digest_loop`, `_tg_poll_loop`)
- **Verified**: `python3 -m pytest` 403/403 passed, `python3 -c "import bot.api"` succeeds (no syntax errors from the 26 edits). **Not yet deployed** — `tennisboss-bot.service` needs a restart to pick this up; deferred since it's a live production service restart (same category of action that required explicit sign-off earlier this session).

### 8. Bump Compose BOM and evaluate `security-crypto` alpha dependency
- **Priority**: Medium
- **Difficulty**: Low (bump) / Medium (crypto lib — needs testing token storage still works)
- **Estimated time**: 1h
- **Dependencies**: None
- **Status**: **Compose BOM bump done** (`2024.09.03` → `2026.06.01`, verified against the real Maven Google metadata — a session-earlier attempt to do this was deferred for lack of a way to verify an exact version without network access; confirmed network access was actually available and fetched the real version list this time). `security-crypto` alpha dependency **left alone** — that's the higher-blast-radius half (touches token storage), still needs explicit approval per this session's standing convention on higher-risk dependency swaps.
- **What changed**: `android/app/build.gradle.kts`'s `compose-bom` version only. No source changes needed — the huge version gap (18 months of releases) produced zero compile errors, only new deprecation warnings (`TabRow` → `PrimaryTabRow`/`SecondaryTabRow` in 4 files: `NavGroups.kt` x3, `PerformanceScreen.kt`, `ValueScreen.kt`) which were **not** auto-fixed since `PrimaryTabRow` changes the default visual style — that's a UI decision, not a mechanical rename.
- **Verified**: `compileDebugKotlin` + `testDebugUnitTest` (54/54) + `assembleDebug` all pass; confirmed on-device (Dashboard, Value screen with its `TabRow` sub-tabs) — no visual regression, no crash.
- **Files involved**: `android/app/build.gradle.kts`, `android/app/src/main/java/com/tennisboss/app/TokenManager.kt` (crypto swap still pending, not touched)
- **Why it matters**: Shipping an alpha-versioned crypto library (`androidx.security:security-crypto:1.1.0-alpha06`) for token storage in a production app is a stability risk if Google ships a breaking change; the Compose BOM staleness is now resolved.

### 9. Document the `db.connect()`-per-call convention
- **Priority**: Medium
- **Difficulty**: Low
- **Estimated time**: 15 min
- **Dependencies**: None
- **Status**: **Done** — warning comment added inside `connect()` documenting the `mcp_feeder.py` incident and the "never call `connect()` inside a loop over many rows" rule.
- **Files involved**: `bot/db.py:229-242` (`connect()` docstring/comment)
- **Why it matters**: The `mcp_feeder.py` performance bug (fixed 2026-07-13) happened because this pattern is fine for ~100 low-frequency call sites but a real footgun inside a loop over many rows. A one-line warning comment prevents the next feeder from repeating it — audit confirmed no other instance exists today, so this is purely preventive.

## Low

### 10. Add Compose `testTag`/semantics to key interactive elements
- **Priority**: Low
- **Difficulty**: Medium (touches many files, low risk per file)
- **Estimated time**: 2-3h for the highest-traffic screens (Dashboard, Chat, bottom nav)
- **Dependencies**: None
- **Status**: **Done — all 13 screens covered.** Bottom nav (5 tabs), Dashboard's 2 clickable match cards, Chat's input/send/upload/message-list, `PredictScreen` + its 2 sub-tabs, `UpcomingScreen` + `LiveScreen` + Matchs' 2 sub-tabs, `PlayersScreen`, `MatchDetailScreen`, Value's 4 top-level sub-tabs + `ValueScreen`, `ScannerScreen`, `PerformanceScreen`, `EdgeScreen` (`edge_screen` root — its only "interactive" elements are no-op decorative `AssistChip`s with `onClick = {}`, not real actions, so not worth tagging individually).
- **Important scoping correction**: verified via a fresh `uiautomator dump` on-device that `testTag` does **not** surface there — it's a Compose semantics property visible only to `androidx.compose.ui.test` (instrumented Compose UI tests via `createAndroidComposeRule`), not the platform accessibility/View tree that `uiautomator` reads. So this work sets up *future* Compose UI tests; it does **not** speed up this session's own `uiautomator`-based manual navigation (that would need real `contentDescription`/text, which already exists for most of what was tapped this session).
- **Files involved**: `MainActivity.kt`, `DashboardScreen.kt`, `ui/components/ValueCard.kt`, `ChatScreen.kt`, `PredictScreen.kt`, `UpcomingScreen.kt`, `LiveScreen.kt`, `NavGroups.kt`, `PlayersScreen.kt`, `MatchDetailScreen.kt`, `ValueScreen.kt`, `ScannerScreen.kt`, `PerformanceScreen.kt`, `EdgeScreen.kt`
- **Verified**: `compileDebugKotlin` + `testDebugUnitTest` (54/54) pass after every single-screen increment (8 separate commits, one per screen/group); confirmed app installs/launches/navigates normally on-device (tags are additive, no visual or behavioral effect).

### 11. Improve accessibility (`contentDescription`) coverage
- **Priority**: Low
- **Difficulty**: Low
- **Estimated time**: 1-2h
- **Dependencies**: None
- **Status**: **Done**. Audited `DashboardScreen.kt`, `PlayersScreen.kt`, `MatchDetailScreen.kt`, `ChatScreen.kt`, `UpcomingScreen.kt` for icon-only actionable elements (not just raw `contentDescription` counts — most `null` usages found were actually *correct*: an `Icon` sitting next to visible text should stay `null` to avoid TalkBack double-announcing the same label, e.g. `SectionHeader`'s icon+title pairs in `DashboardScreen.kt`, `SignalCard`'s icon+title in `MatchDetailScreen.kt`). Found and fixed the real gaps: `PlayersScreen.kt`'s icon-only clear/`Close` `IconButton` (`contentDescription = null` → `"Effacer"`), and `ChatScreen.kt`'s two `IconButton`s that use raw emoji `Text` instead of `Icon` (paperclip upload, send arrow) — these had **no accessible label mechanism at all**, not just a `null` one, since `Text` has no `contentDescription` param. Added `Modifier.semantics { contentDescription = "..." }` directly on those two `IconButton`s ("Joindre un fichier", "Envoyer").
- **Files involved**: `PlayersScreen.kt`, `ChatScreen.kt`
- **Verified**: `compileDebugKotlin` + `testDebugUnitTest` (54/54) pass; confirmed visually on-device that Chat/Players screens render unchanged (the fix is semantics-only, no visual change expected).

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
