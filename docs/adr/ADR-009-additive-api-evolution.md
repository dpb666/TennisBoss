# ADR-009 — Additive-only API evolution; no /v2 URL scheme

**Status:** Accepted · 2026-07-16

## Context
Android clients in the field cannot be force-updated instantly; the API has ~52
routes consumed by 14 screens.

## Decision
The contract grows by optional fields only; nothing is removed or re-typed. A
breaking change requires a new route, a deprecation window with sunset header,
and an Android version gate via `/api/app/version`. No URL versioning scheme.

## Consequences
- Old clients keep working indefinitely on old fields.
- `openapi_spec.py` stays authoritative (see ADR-012).
