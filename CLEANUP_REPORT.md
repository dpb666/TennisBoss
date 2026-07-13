# TennisBoss — Cleanup Report (dead code / duplication)

_Verified 2026-07-13 by grepping actual reference counts, not inferred from naming. "Zero references" means checked against every `bot/*.py`, `run.py`, `tests/*.py`, `docker-compose.yml`, and `.github/workflows/*.yml`._

## Unused classes/modules (backend)

| File | Lines | References found | Verdict |
|---|---|---|---|
| `bot/ai_resolver.py` | 401 | 0 outside its own file | Dead — full AI-based player-resolution pipeline never wired to anything |
| `bot/alerts.py` | 145 | 0 outside its own file | Dead — sharp-signal/hedge/drawdown alerts; superseded by `bot/realtime_alerts.py` which IS used. Name collision risk. |
| `bot/telegram_poll.py` | 213 | 0 anywhere | Fully dead — zero references. **Left in place** (user chose to keep the 4 orphaned modules for now). |
| `bot/telegram_handler.py` | 158 | was 1, from the now-deleted `app/` | Its only caller was removed along with `app/` — now also fully dead. **Left in place** (same decision). |
| `app/` (~34 files) | — | none reachable (see correction below) | **Removed 2026-07-13**, user-confirmed, see `MASTER_TODO.md` #1. |

Correction from an earlier draft of this report: I initially assumed `bot/telegram_poll.py` was the live one because `bot/api.py` runs a `_tg_poll_loop` background thread (`api.py:3237,3328`) — but that function is defined **inline inside `api.py` itself**, not imported from either `telegram_poll.py` or `telegram_handler.py`. So there are actually **three independent Telegram implementations**: the inline one in `api.py` (live), `bot/telegram_poll.py` (fully dead), and `bot/telegram_handler.py` (reachable only from the dormant `app/` package, so dead in any currently-running configuration). Verified via `grep -rn "telegram_poll\|telegram_handler" --include=*.py .` across the whole repo before asserting this.

## Duplicate code (Android)

| Composable | Locations | Status |
|---|---|---|
| `StatCard` | was `EdgeScreen.kt:183`, `PerformanceScreen.kt:320` | Byte-for-byte identical — **fixed**: extracted to `ui/components/StatCard.kt`, both call sites updated. |
| `RecentRow` | `EdgeScreen.kt:218` (`ClvRecent`), `PerformanceScreen.kt:344` (`SettledRecent`) | **Verified NOT a duplicate** — diffed both bodies: they render different data types (CLV/honeypot info vs. settled-match correctness) with genuinely different logic, and both are already file-`private`, so there's no collision risk either. Same name, coincidence, not a bug. No action needed. |
| `SurfaceBadge` | `ui/components/SurfaceBadge.kt`, `UpcomingScreen.kt:905` | **Fixed** — was a name COLLISION (not simple duplication) with different signatures/logic that caused a real live bug (wrong badge style rendered in the Matchs tab). See `MASTER_TODO.md` #2. |

Already-completed extractions from earlier this session (for reference, not re-flagging): `ValueCard.kt`, `EdgeIndicator.kt` were pulled out of `DashboardScreen.kt`/`ValueScreen.kt` duplication.

## Duplicate/dead code NOT found (checked, clean)

- No duplicated date-formatting logic outside `DateUtils.kt` (Android).
- No unused Gradle dependencies in `android/app/build.gradle.kts` — every declared dependency (Retrofit, Gson, OkHttp logging-interceptor, coroutines, WorkManager, Firebase, security-crypto) has at least one real import site.
- `tennisdata_feeder.py`, `mantennisdata_feeder.py`, `sackmann_feeder.py`, `mcp_feeder.py`, `oddspapi_feeder.py` — despite similar names/purposes, each covers a genuinely distinct data source and time window; none is a duplicate of another (confirmed by reading each module's docstring, which documents why it exists alongside the others).

## Deprecated APIs

- `bot/db.py:1367` — `datetime.datetime.utcnow()` (deprecated since Python 3.12, still functional, surfaces as a `DeprecationWarning` in every test run). Trivial fix: `datetime.datetime.now(datetime.UTC)`.
- Android: `Icons.Filled.ArrowBack` and `Icons.Filled.TrendingUp` (used in `MatchDetailScreen.kt:51,166,191`) are deprecated in favor of `Icons.AutoMirrored.Filled.*` — currently only compiler warnings, not errors.

## Recommended actions (see MASTER_TODO.md for priority/time estimates)

1. Delete `bot/ai_resolver.py`, `bot/alerts.py`, `bot/telegram_handler.py` — **after user confirmation** (never delete without asking, per project convention).
2. Rename the `UpcomingScreen.kt` `SurfaceBadge` to avoid the collision (higher priority than plain duplication — this one risks a silent wrong-behavior bug, not just extra maintenance).
3. Extract `StatCard`/`RecentRow` to `ui/components/`.
4. Fix the two deprecated-API one-liners (`utcnow()`, Compose icon imports) opportunistically — low risk, low value, do only if touching those files for another reason.
