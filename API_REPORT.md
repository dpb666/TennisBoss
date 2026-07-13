# TennisBoss — API Report

_Covers `bot/api.py` (the live, deployed Flask API — `tennisboss-bot.service`, port 8000). The dormant `app/` FastAPI service is intentionally out of scope here; see `PROJECT_STATUS.md`/`MASTER_TODO.md` #1._

## Endpoint inventory

~45 routes under `/api/*`, plus `/health`, `/privacy`. Grouped by purpose: predictions (`/api/predict`, `/api/insight`), match feeds (`/api/upcoming`, `/api/live`, `/api/recommendations`), value/CLV (`/api/value`, `/api/clv`, `/api/inplay/*`), player data (`/api/players`, `/api/player/*`, `/api/h2h`), chat (`/api/chat`), account/device (`/api/device/register`, `/api/player/follow`), admin/ops (`/api/settlement/run`, `/api/monitor/status`, `/api/backup`), and OpenAPI/docs (`/api/openapi.json`, `/api/docs`).

## Authentication

Enforced **centrally** via `@app.before_request` (`bot/api.py:218-231`), checking `X-API-Token` against `TENNISBOSS_API_TOKEN` for every route except an explicit whitelist (`/health`, `/privacy`, `/api/openapi.json`, `/api/docs*`, `OPTIONS` preflight). This is the right pattern — a per-route decorator would risk a forgotten route; a global hook cannot be silently skipped. Sampled `/api/player/follow`, `/api/inplay/picks`, `/api/device/register` specifically to confirm none bypass it. **No issue found.**

One behavior worth a deliberate re-confirmation, not a bug: if `TENNISBOSS_API_TOKEN` is unset while bound to a non-localhost host, `bot/api.py:3182-3186` logs a warning but **still serves unauthenticated** rather than refusing to start. This is intentional per the code comment (LAN convenience during dev), but should be re-checked before any deployment beyond the current LAN/tunnel setup.

## Rate limiting

Applied selectively, not blanket: `/api/upcoming` (`api.py:841`), `/api/live` (`api.py:1118`), `/api/value` (`api.py:1685`) each carry `@limiter.limit("20 per minute")`. This specifically protects the shared odds-api.io quota (100 req/h) that these three endpoints consume — confirmed intentional and consistent, not an oversight, by checking that every quota-consuming endpoint has it and no non-quota endpoint does.

## Caching

`/api/upcoming` uses an in-memory `_upcoming_cache` keyed by `(days, limit, want_odds)` with a 270s TTL (`api.py:835-837`) — deliberately long enough that ESPN/odds-api.io data (which changes slowly) doesn't get re-fetched needlessly, short enough to reflect live odds movement within a reasonable window. No cache invalidation bug found; this is also exactly the mechanism that required careful unique `limit=` values in tests to avoid cross-test cache collisions (see `TEST_REPORT.md`).

## Timeouts / retry policy

No explicit retry logic found on outbound calls to external providers (odds-api.io, OddsPapi, ESPN, tennis-data.co.uk, MatchChartingProject) — each feeder's `_http_get`/`requests.get` call has a timeout (typically 8-30s depending on payload size) but fails fast on error rather than retrying, relying instead on the next scheduled job cycle to naturally retry. This is a reasonable design for a 5-minute-to-12-hour cadence background job, but would be worth adding explicit retry-with-backoff if any of these feeders become more failure-prone in practice.

## JSON parsing / error handling

Consistent use of `.get()` with defaults rather than direct key access across feeders (avoids `KeyError` crashes on schema drift from external sources) — this is a mature, defensive pattern seen throughout `bot/*_feeder.py`. The flip side (see `PROJECT_STATUS.md`/`CLEANUP_REPORT.md`) is that `bot/api.py` itself has 36 `except Exception: pass` blocks that swallow errors with zero logging — functionally safe (best-effort paths) but operationally invisible when something actually breaks.

## OpenAPI / docs

`/api/openapi.json` and `/api/docs*` exist and are correctly whitelisted from auth (so the Swagger UI itself is browsable without a token, though the underlying calls it makes would still need one). Not deeply audited for schema accuracy in this pass — worth a spot-check if the Android app's `ApiModels.kt` and this spec ever visibly diverge.

## Summary

No structural API bugs found. The API layer is more mature than the average area of this codebase — the auth/rate-limiting/caching decisions are all deliberate and internally consistent. The only real action item from this report is folded into `MASTER_TODO.md` #7 (log the silent exceptions) — everything else here is confirmation, not a new finding.
