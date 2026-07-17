# ADR-011 — Single-host deployment with a rehearsed promotion path

**Status:** Accepted · 2026-07-16

## Context
Production runs on one WSL machine (systemd + Cloudflare tunnel). The
docker-compose file already models the correct api/worker/tunnel split.

## Decision
Single host stays. `docker-compose.yml` is the portable production definition:
staging = compose against a restored backup (doubling as the restore drill);
VPS migration = the same compose on a rented box. Off-host encrypted backups
and quarterly restore drills are part of this decision, not optional extras.

## Consequences
- No orchestration platform to operate.
- The restore drill is a scheduled obligation; an untested backup is treated
  as no backup.
