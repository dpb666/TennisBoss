# ADR-008 — FTS5 keyword retrieval before embeddings

**Status:** Accepted · 2026-07-16

## Context
The knowledge base (project_knowledge.db) will index < 100 markdown documents
plus structured decision entries.

## Decision
Ship retrieval on SQLite FTS5 only. Add an embedding index only if a measured
recall evaluation (< 80% on a golden-question set) demands it — as a second
index, not a replacement.

## Consequences
- Zero new dependencies; deterministic, debuggable retrieval.
- A golden-question eval set must exist before any embedding discussion.
