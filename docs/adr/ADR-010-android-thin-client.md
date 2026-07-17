# ADR-010 — Android stays a thin client; Repository+DI seam precedes persistence

**Status:** Accepted · 2026-07-16

## Context
All 14 ViewModels call the Retrofit client directly (no Repository layer, no
DI). Network-only rendering is a deliberate choice: stale odds/predictions are
actively misleading in a betting context.

## Decision
Android remains presentation-only. Any offline/caching/persistence feature
(Room, chat history, cross-screen state) may only be built after a Repository
layer with constructor-injected dependencies exists (Hilt or manual — the
implementer chooses), introduced screen-by-screen.

## Consequences
- Prevents 14 divergent caching implementations.
- The seam design is a joint deliverable: contract by Claude, implementation by
  Cursor Composer (blueprint §13).
