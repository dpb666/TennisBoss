# TennisBoss — Test Report

_Both suites run fresh on 2026-07-13 for this report — not trusting prior claims in other docs._

## Backend (`pytest`)

```
403 passed, 1 warning in ~30s
```

**Zero failing tests right now.** The 1 warning is `bot/db.py:1367`'s `datetime.utcnow()` deprecation (cosmetic, see `CLEANUP_REPORT.md`).

**Historical flakiness to watch** (not currently failing, but documented in this session's own history as environment-dependent): `tests/test_backup.py::TestBackup::test_backup_now_returns_none_without_source_db` and `tests/test_mantennisdata_feeder.py::TestIngest::test_ingest_does_not_retrain_same_match_twice` have previously failed specifically when the live WSL server process holds the SQLite file open (a Windows file-locking interaction, not a logic bug). They passed clean in this run because the server wasn't contending for the file at that moment. **Recommendation**: if these ever reappear in CI (where there's no live server running), treat that as a signal the test itself has a real isolation problem, not this Windows-specific quirk — worth a `pytest-xdist`-safe temp-DB fixture audit if it recurs there.

**Coverage shape**: strong around the data pipeline additions from this session (`test_namematch.py`, `test_dedupe_players.py`, `test_mcp_feeder.py`, `test_oddspapi_feeder.py`, `test_intelligence_layer_signals.py`) and the core API (`test_api_endpoints2.py`, `test_api_endpoints_db.py`). No formal coverage percentage tool is wired in (no `pytest-cov` in `requirements.txt` / CI config) — recommend adding one to get a real number rather than eyeballing file-by-file.

## Android (`./gradlew testDebugUnitTest`)

```
BUILD SUCCESSFUL in ~25-30s
23 tests, 0 failures, 0 skipped, 0 errors
```

**Zero failing tests.** Full file list: `DashboardViewModelTest` (4), `LiveViewModelTest` (2), `MatchDetailViewModelTest` (3), `PredictViewModelTest` (3), `SortForDashboardTest` (4), `SortUpcomingTest` (3), `UpcomingViewModelTest` (2), `ValueViewModelTest` (2).

**Coverage gap (the real finding here)**: 7 of 13 ViewModels have **zero** test files — `PlayersViewModel`, `PlayerCompareViewModel`, `PlayerDetailViewModel`, `PerformanceViewModel`, `EdgeViewModel`, `ScannerViewModel`, `ChatViewModel`. `ChatViewModel` being untested is the most notable gap given the user's repeated emphasis this session on the AI chat feature as a priority. See `MASTER_TODO.md` #4.

**No instrumentation tests** (`androidTest/`) exist at all — everything is JVM unit tests against `FakeApi.kt`, none exercise real Compose UI or a real device/emulator. Combined with the complete absence of `testTag`s (see `UI_REPORT.md`), this means there is currently no automated UI-level regression protection whatsoever — every UI verification this session was manual (screenshots + `uiautomator dump` + hand-computed tap coordinates), which is slow and doesn't scale.

## Mocking patterns (both suites)

Backend: consistent `unittest.mock.patch.object` on `is_enabled()`-style feature flags per data source, and a documented convention of using unique cache-key parameters (`limit=97` vs `99` vs `96`) to avoid `_upcoming_cache` TTL collisions between tests — a slightly fragile but working pattern (see `test_api_endpoints2.py`). Android: `FakeApi.kt` implements the same interface as the real Retrofit API, with optional per-field overrides per test — clean, standard test-double pattern, and it correctly uses `RuntimeException` (not `NotImplementedError`, which extends `Error` and isn't caught by `catch (e: Exception)`) for endpoints treated as best-effort by ViewModels.

## CI (`.github/workflows/ci.yml`)

Two jobs: backend (`pytest tests/ -v`, Python 3.12) and android (`./gradlew :app:testDebugUnitTest`). No lint/type-check step (no `mypy`/`ruff`/`ktlint` gate), no coverage threshold enforced, and it does not run against the dormant `app/` package (consistent with that package being untested by design/neglect — see `MASTER_TODO.md` #1).

## Suggested fixes / next steps, in order of value

1. Write `ChatViewModelTest.kt` first — highest-priority untested surface (`MASTER_TODO.md` #4).
2. Add `pytest-cov` to get a real backend coverage number instead of file-by-file guessing.
3. Consider one instrumentation/Compose UI test for the critical path (Dashboard → tap a match → MatchDetail) now that `testTag`s would make this tractable (`MASTER_TODO.md` #10) — currently would have to rely on raw text matching, which is what slowed down this session's manual walkthrough.
