# ADR-004 — Strangler-fig package migration with re-export shims

**Status:** Accepted · 2026-07-16

## Context
Flat `bot/` (~69 modules) has no enforceable boundaries; a big-bang
restructuring would endanger ~585 passing tests and production continuity.

## Decision
Migrate modules into bounded-context packages (blueprint §4) in slices. Every
move leaves a re-export shim at the old path (`bot/xyz.py` →
`from <new>.xyz import *`). Every slice ships with the full suite green and
byte-identical API behavior. Shims are removed after two release cycles via a
grep gate. `from bot import predictor` keeps working throughout.

## Consequences
- Temporary dual import paths; a visible shim inventory must be maintained.
- No flag-day risk; migration can pause indefinitely at any safe point.
