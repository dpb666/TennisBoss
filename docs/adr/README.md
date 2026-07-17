# Architecture Decision Records

Index of ADRs. Source of truth for structural decisions — see
`docs/ARCHITECTURE_BLUEPRINT.md` (§15) for the architecture they compose.

**Rules:** one decision per file; never edit an accepted ADR — supersede it with
a new one and link both ways. Ratification is human-only (blueprint §13).

| ADR | Title | Status |
|-----|-------|--------|
| [001](ADR-001-modular-monolith.md) | Modular monolith; no microservices | Accepted |
| [002](ADR-002-sqlite-system-of-record.md) | SQLite (WAL) remains the system of record | Accepted |
| [003](ADR-003-flask-stays-fastapi-rejected.md) | Flask (sync) stays; FastAPI rejected | Accepted |
| [004](ADR-004-strangler-fig-migration.md) | Strangler-fig package migration with re-export shims | Accepted |
| [005](ADR-005-frozen-prediction-core.md) | Prediction core frozen; evidence-gated unfreeze | Accepted |
| [006](ADR-006-event-bus-outbox.md) | In-process event bus with SQLite outbox; no broker | Accepted |
| [007](ADR-007-ai-read-only.md) | AI assistant is read-only; write tools permanently blocked | Accepted |
| [008](ADR-008-fts5-before-embeddings.md) | FTS5 keyword retrieval before embeddings | Accepted |
| [009](ADR-009-additive-api-evolution.md) | Additive-only API evolution; no /v2 URL scheme | Accepted |
| [010](ADR-010-android-thin-client.md) | Android stays a thin client; Repository+DI seam precedes persistence | Accepted |
| [011](ADR-011-single-host-deployment.md) | Single-host deployment with a rehearsed promotion path | Accepted |
| [012](ADR-012-handwritten-openapi.md) | Hand-written OpenAPI spec, CI-checked against routes | Accepted |
