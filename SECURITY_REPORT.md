# TennisBoss — Security Report

_2026-07-13. Backend + Android. Findings verified directly (git history, grep, config inspection), not assumed from documentation._

## Secrets

- `.env` confirmed in `.gitignore` (repo root). `git log --all --oneline -- .env` returns **empty** — never committed to git history, at any point, on any branch. Clean.
- No hardcoded secrets/API keys found in `bot/*.py` via pattern search (key-like literals: long hex/base64 strings, `sk_`, `gsk_`, UUID-shaped keys) outside of what's read from `os.environ`.
- No hardcoded secrets found in Android Kotlin source. The only hardcoded strings are non-secret base URLs (`ApiClient.kt:19,24` — localhost emulator fallback and the production Cloudflare Worker URL). The actual API token comes from `BuildConfig.TENNISBOSS_API_TOKEN`, sourced from `local.properties`/env at build time, empty in release builds unless explicitly provided.

## Logged secrets

Checked for the specific mistake pattern this session already caught once (a curl response echoing back an API key was displayed unredacted mid-session, self-corrected at the time): grepped `bot/*.py` for `log()`/`print()` calls that might interpolate a full secret value. Found the opposite of a problem — `bot/odds_api.py:274` deliberately logs only `api_key[-6:]` (last 6 characters), an already-safe pattern. No instance found of a full secret being logged.

## Authentication

`X-API-Token` enforced globally via `@app.before_request` (`bot/api.py:218-231`) for all `/api/*` routes except an explicit, narrow whitelist (`/health`, `/privacy`, `/api/openapi.json`, `/api/docs*`, `OPTIONS`). Verified by sampling several routes directly rather than trusting the pattern to hold everywhere. **This is a robust pattern** — a per-route decorator scheme would risk a route silently missing auth; a global before-request hook cannot be forgotten per-route.

**One item worth re-confirming with the user, not a code defect**: if `TENNISBOSS_API_TOKEN` is unset while the server is bound to a non-localhost interface, `bot/api.py:3182-3186` logs a warning but still serves requests unauthenticated. This is explicitly intentional (LAN dev convenience per the code comment), but it's a real exposure if the binding or network context ever changes without someone remembering this default.

## Android transport security

`AndroidManifest.xml:15` sets `usesCleartextTraffic="false"`. Backed by a `network_security_config.xml` restricting to system trust anchors with cleartext disabled. Debug-only cleartext exceptions (needed for local emulator testing against `127.0.0.1`/LAN IPs) are correctly scoped to `src/debug/res/xml/`, excluded from release builds. **Clean — no gap found.**

## Android permissions

`AndroidManifest.xml` declares exactly two permissions: `INTERNET` (required for all API calls) and `POST_NOTIFICATIONS` (required for FCM push). Both are justified by actual, implemented features. No over-permissioning.

## Dependency risk

`androidx.security:security-crypto:1.1.0-alpha06` is used in `TokenManager.kt` for token storage — still an **alpha** release being used in what is otherwise treated as a production app. Not an active vulnerability, but a stability risk (an alpha library can ship breaking changes without the same compatibility guarantees as a stable release). See `MASTER_TODO.md` #8.

## The dormant `app/` service, security angle

~~`tennisboss-quant.service`...~~ **Removed 2026-07-13** (user-confirmed, git tag `pre-app-removal-backup` as restore point) — no longer a latent attack surface to track. See `MASTER_TODO.md` #1.

## Summary

No active secrets exposure, no transport-security gap, no authentication bypass found. The codebase's security posture is genuinely solid for its scale. The one item worth tracking is non-urgent: the alpha crypto dependency (stability, not a known CVE).
