# TennisBoss — Architecture Review

_2026-07-13. Covers Android (MVVM/Compose) and backend (Flask) architecture as actually implemented, not as aspirationally documented._

## MVVM (Android)

Consistently applied: 13 screens, 13 ViewModels, sealed `UiState` (Loading/Success/Error) per screen. Sampled `DashboardViewModel`, `MatchDetailViewModel`, `ValueViewModel`, `ChatViewModel` — all wrap Retrofit calls in try/catch and expose state correctly. `ValueViewModel` additionally branches on HTTP status codes (503/429) for odds-quota-specific messaging. **No architectural violation found.**

## Repository pattern

**Absent.** ViewModels call `ApiClient` (Retrofit) directly — there is no `Repository` layer mediating between ViewModels and the network. This is fine for the current network-only, no-cache design, but it's the reason Room/offline (deliberately deferred) would be a bigger lift than "just add Room": every ViewModel would need a Repository interposed first, since a cache-then-network strategy needs a single seam to implement it, not 13 separate call sites.

## Dependency injection

**None.** `ApiClient.create()` is called directly wherever needed (a factory function, not injected). No Hilt/Koin/manual DI graph. Works fine at current scale (13 screens) but is a genuine scaling risk if the screen count doubles — every new screen re-derives its own `ApiClient` instance rather than sharing one through a graph.

## Coroutines

Correct usage confirmed, including a same-day-fixed bug from earlier this session: `DashboardViewModel`/`MatchDetailViewModel` wrap parallel `async{}` calls in `coroutineScope{}` (not just the enclosing `launch{}`), which is the correct pattern for letting a child failure propagate to the surrounding try/catch via a normal `throw` rather than racing past it through structured-concurrency cancellation. This was a real bug caught by a test earlier this session, not a hypothetical.

## Compose

Screens fetch via `viewModel()` + `LaunchedEffect`, no heavy work found directly in composition (verified by sampling Dashboard/MatchDetail/Value for network calls or large-list processing outside a `LaunchedEffect`). **Gap**: zero `testTag`/semantics properties anywhere — see `TEST_REPORT.md`.

## Navigation

No Navigation-Compose / `NavHost`. `MainActivity.kt`'s `AppRoot()` (lines 132-233) manages a manual `tab: Int` state + `AnimatedContent` for 5 bottom tabs; `NavGroups.kt` layers sub-`TabRow`s inside 3 of those tabs to reach the other 9 screens (13 screens total, all reachable, no dead routes found). This is a deliberate, working design — not a broken navigation graph — but it means there's no deep-linking, no back-stack, and no per-screen navigation testing infrastructure that `NavHost` would provide for free. Worth a note for the backlog, not an active bug.

## Room / caching

Confirmed absent (zero `androidx.room` references). Every screen is network-only, reload-on-visit. Given the domain (live odds/predictions where staleness is actively misleading for a betting-value app), this is a defensible choice, not an oversight — but it was a deliberate deferral, not a "not gotten to it yet," and should stay a conscious decision each time it's revisited (see `MASTER_TODO.md` #12).

## Networking

Retrofit + OkHttp + Gson, `TokenManager` handles the `X-API-Token` header, `network_security_config.xml` enforces HTTPS-only in release with debug-only cleartext exceptions correctly scoped to `src/debug/`. No retry policy or client-side caching layer configured on the `OkHttpClient` (relies entirely on the backend's own caching, e.g. `_upcoming_cache` in `bot/api.py`).

## Backend architecture (`bot/`)

Flat module structure (58 files in `bot/`, no subpackages) with a clear separation: `api.py` (HTTP layer) → `predictor.py`/`features.py`/`elo.py` (model) → `db.py` (SQLite persistence) → a family of `*_feeder.py` modules (data ingestion, one per external source). This flat-file approach was deliberately chosen over restructuring into `bot/ml/` subpackages per `docs/AUDIT.md` §4 ("écartée") — a documented, reasoned decision, not neglect.

**The one real architectural gap**: the dormant `app/` FastAPI package (see `PROJECT_STATUS.md` and `MASTER_TODO.md` #1) represents a second, competing architecture (async FastAPI + Pydantic vs. sync Flask) that was started, partially built (~34 files), and then abandoned/disabled — but not fully decoupled from `bot/`. This is the one place where "architecture" isn't singular right now.

## Error handling / state management

Backend: centralized auth (`before_request`), consistent `log()` calls, but heavy `except Exception: pass` (36x in `api.py`) trades robustness for silent failure — see `MASTER_TODO.md` #7. Android: consistent sealed-state pattern, no gaps found in the sampled ViewModels.

## Summary verdict

The architecture is coherent and mostly well-reasoned for its actual scale — the main structural debt is (a) the orphaned `app/` FastAPI service pulling the codebase in two directions at once, and (b) the Android app's total absence of a Repository/DI layer, which is fine today but is exactly the seam that would need to exist before Room/offline could be added cleanly.
