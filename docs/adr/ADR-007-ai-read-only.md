# ADR-007 — AI assistant is read-only; write tools permanently blocked

**Status:** Accepted · 2026-07-16

## Context
The assistant (ai/chat/) has tool access to DB, docs, and reports. Any write
path would eventually be exercised by an LLM in an unintended way.

## Decision
The tool registry enforces `read_only=True`. Permanently blocked tools:
`train_model`, `settle_match`, `place_bet`, `modify_memory`, `bump_version`,
`run_learn`. Enforcement is threefold: not in the registry; write endpoints
excluded; CI guard test asserting `ai/` never imports `predictor`, `calibrate`,
or `learner`. Learning output (Phase 3) is suggestions requiring human approval.

## Consequences
- The assistant can be trusted as an ops/analysis console.
- Any future write scope needs a new ADR with human-in-the-loop design.
  Bet placement is never in scope.
