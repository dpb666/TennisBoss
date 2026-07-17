# ADR-002 — SQLite (WAL) remains the system of record

**Status:** Accepted · 2026-07-16

## Context
~94k matches, ~4.8k logged picks, 20 tables, WAL mode, two processes sharing the
file. The one past performance incident (mcp_feeder opening ~12k connections)
was a usage bug, not an engine limit.

## Decision
No Postgres migration. SQLite (WAL) stays, with single-writer-per-table
discipline and an archive strategy (yearly attached DB files) at growth
thresholds.

## Consequences
- Zero database ops burden; backups are file snapshots via the sqlite3 backup API.
- Multi-host writes are impossible — acceptable under ADR-001/ADR-011.

## Revisit trigger
DB file > 2 GB, hot-query p95 > 100 ms measured, or true multi-host writes needed.
