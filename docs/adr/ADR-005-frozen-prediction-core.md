# ADR-005 — Prediction core frozen; evidence-gated unfreeze

**Status:** Accepted · 2026-07 (user decree), codified 2026-07-16

## Context
No statistically valid edge verdict is possible below n≈200 settled picks
(currently n≈97). Uncontrolled model tweaking would invalidate the sample.

## Decision
`bot/predictor.py`, `bot/calibrate.py`, the market blend, `/api/value`
thresholds and pick-selection gates are sealed until 200–500 settled picks with
complete logging (`/api/logging/health` is the gate metric). Changes are
human-only and require: a new ADR, walk-forward validation, and a version bump
in `bot/versions.py`. New engines run in parallel via the `compare_engines`
harness; they never edit v1.

## Consequences
- All near-term innovation happens in the surrounding layers.
- The eventual edge verdict (positive or negative) is statistically valid.
- Enforced by guard tests (`tests/test_ai_tools.py`) and, once packages exist,
  import lint.
