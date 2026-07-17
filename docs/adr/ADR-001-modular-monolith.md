# ADR-001 — Modular monolith; no microservices

**Status:** Accepted · 2026-07-16

## Context
Single operator, single host, SQLite storage, AI agents doing most implementation
work. The system spans many domains (prediction, data, odds, betting, AI, ops)
that could tempt a service split.

## Decision
One codebase, two process roles (api, worker), one host. Bounded contexts are
Python packages with enforced import rules (CI lint once packages exist), not
network services.

## Consequences
- Discipline must come from import rules and CI, not process boundaries.
- Deployment, debugging, and agent navigation stay simple.
- Cross-context calls are function calls through published interfaces.

## Revisit trigger
A context demonstrably needs independent scaling, or a second host becomes
necessary for availability.
