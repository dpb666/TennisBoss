# ADR-006 — In-process event bus with SQLite outbox; no broker

**Status:** Accepted · 2026-07-16

## Context
Settlement, odds moves, and job failures each need to fan out to notifications,
learning, and knowledge ingestion — today via direct calls that couple contexts.

## Decision
A small in-process dispatcher (~100 lines, stdlib) plus a durable
`events_outbox` table. Producers publish typed events (PickOpened, PickSettled,
OddsMoved, DataIngested, ModelDriftDetected, JobFailed, BackupCompleted,
DecisionRecorded); subscribers register per type; outbox rows enable replay.
No Kafka/Redis/broker.

## Consequences
- The event schema catalog is the real contract — version it.
- Transport is swappable later without touching producers/consumers.

## Revisit trigger
Multi-host consumers.
