# ADR-003 — Flask (sync) stays; FastAPI rejected

**Status:** Accepted · 2026-07-13 (app/ removal), codified 2026-07-16

## Context
A parallel FastAPI package (`app/`, ~34 files) was built alongside the Flask
API, went dormant, and was removed 2026-07-13 after proving inert in production
(git tag `pre-app-removal-backup`).

## Decision
Flask (sync) is the API framework. No parallel or replacement framework.

## Consequences
- Long-running work never runs in-request; workers own it (blueprint §5.3).
- One HTTP idiom for all agents to learn and maintain.

## Revisit trigger
Sustained request concurrency the sync worker pool measurably cannot serve.
