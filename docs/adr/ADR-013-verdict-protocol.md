# ADR-013 — Pre-committed edge verdict protocol (n≥200)

**Status:** Accepted · 2026-07-18  
**Related:** [ADR-005 — Prediction core frozen](ADR-005-frozen-prediction-core.md)

## Context

TennisBoss is accumulating settled picks toward an statistically valid edge verdict.
Per ADR-005, the prediction core (`bot/predictor.py`, `bot/calibrate.py`, market
blend, `/api/value` thresholds and pick-selection gates) remains frozen until
n≥200 settled picks with complete logging (`/api/logging/health` is the gate).

Before unfreezing, the team needs a **pre-committed decision protocol** so that
post-hoc rationalization does not drive model changes.

## Decision

At **n≥200 settled scanner-era picks** (post 2026-07-03 filter, consistent with
`clv.stats()` / `bet_history`), apply this verdict **without renegotiation**:

| Outcome | Criteria | Action |
|---|---|---|
| **GO** | Mean CLV > 0 **and** statistically significant (beat-closing lower 95% CI > 50%) | Maintain frozen core; scale operational layers (logging, deployment, Android). No predictor changes. |
| **ITÉRER** | Mean CLV > 0 but n or significance insufficient, **or** logging completeness < 90% | Do **not** touch predictor/thresholds. Fix observability, closing-line capture, data quality. Re-evaluate at n≥250. |
| **NO-GO (modèle)** | Mean CLV ≤ 0 with sufficient n and complete logging | New ADR required before any predictor/calibration change; parallel engine via `compare-engines` only — never in-place v1 edits. |

Supporting metrics (informational, not override):

- ROI flat on n≥200 (noisy; confirmatory only)
- Logging completeness ≥ 90% on repro fields (`db.clv_logging_completeness_report`)
- `bet_history` row count matches `clv_log` settled rows

## Process

1. Run `python run.py weekly-audit` and review `/api/logging/health`.
2. Record verdict in `deployment_history` notes + `MASTER_TODO.md`.
3. If **GO**: publish ADR-014 (unfreeze criteria met) before any model work.
4. If **ITÉRER** or **NO-GO**: remain under ADR-005 freeze; operational fixes only.

## Consequences

- Removes ambiguity at the n=200 milestone.
- Protects sample integrity (ADR-005).
- Weekly audit (`run.py weekly-audit`, Sunday scheduler job) is the operational
  checkpoint — includes calendar-quiet-week note (no selection widening).

## References

- ADR-005 — frozen prediction core
- `bot/clv.py::stats()` — verdict thresholds (edge_prouvé / prometteur / pas_d_edge)
- `docs/LOGGING_SCHEMA.md` — repro field completeness
- `bot/weekly_audit.py` — automated checkpoint
