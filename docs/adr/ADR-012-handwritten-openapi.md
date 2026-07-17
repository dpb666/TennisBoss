# ADR-012 — Hand-written OpenAPI spec, CI-checked against routes

**Status:** Accepted · 2026-07-16

## Context
`bot/openapi_spec.py` is a curated, hand-written OpenAPI 3.0 document served at
`/api/openapi.json`. Generation from code would lose curation quality.

## Decision
Keep the hand-written spec as the contract source of truth. Add a CI check that
the registered Flask route table and the spec agree in both directions
(route table ⊆ spec ⊆ route table).

## Consequences
- Docs stay high-quality and intentional.
- The CI drift check is what keeps "hand-written" honest — it must land with
  the blueprint decomposition (roadmap Q4 #7).
