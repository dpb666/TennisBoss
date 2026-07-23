# Schema migrations

Applied by `bot/db_migrations.py::apply_pending_migrations()`, called from
`bot/db.py::init()` — see D-4 / `docs/ARCHITECTURE_BLUEPRINT.md` §7.2.

This directory is empty today: the ~34 columns added since launch went
through the ad-hoc `ALTER TABLE` list in `bot/db.py::init()`, and that list
is left as-is (rewriting working history against the live prod DB isn't
worth the risk). This mechanism is for schema changes from here on.

## Adding a migration

1. Create `NNNN_short_description.sql`, next number, zero-padded to 4 digits
   (`0001_...`, `0002_...`), ascending — applied in filename order.
2. Write plain SQL (any statement `sqlite3.Connection.executescript()`
   accepts). Additive only (P3): `ADD COLUMN`, `CREATE TABLE IF NOT EXISTS`,
   `CREATE INDEX IF NOT EXISTS`. Anything destructive or irreversible
   (`DROP`, data-losing `ALTER`) must say so in a comment at the top of the
   file.
3. Do not edit a migration file once it has been applied anywhere (including
   just your own dev DB) — file identity is the filename, tracked forever in
   `schema_migrations`. Ship a new migration to fix a mistake instead.
4. Nothing else to wire up: `db.init()` picks up new files automatically on
   the next start.
