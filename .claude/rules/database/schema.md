---
paths:
  - "**/alembic/**/*.py"
  - "**/migrations/**/*.sql"
  - "**/models/**/*.py"
---
# Database Schema Rules

> Extends [common/sandboxed-domain.md](../common/sandboxed-domain.md) DB discipline.

## Stack

- **TimescaleDB** (PostgreSQL 16+) as the sole persistent store.
- **Alembic** owns all schema changes — source of truth under `services/trading-engine/alembic/`.
- Connection secrets loaded via `settings.get_secret("POSTGRES_PASSWORD")` — never inline.

## Migration Rules

- **Every** schema change goes through an Alembic revision. No ad-hoc `ALTER TABLE` in psql, no schema changes in ORM model files without a paired migration.
- Revision naming: `YYYYMMDD_hhmm_<slug>.py` — deterministic ordering across contributors.
- Each revision MUST define both `upgrade()` and `downgrade()`. A no-op downgrade is acceptable for data backfills but MUST be documented with a comment.
- Use `op.execute()` with parameterized SQL only — never f-string interpolation of user/config values.

## Destructive Operation Policy

| Operation | Allowed in migration? |
|---|---|
| `ADD COLUMN` nullable | YES |
| `ADD COLUMN NOT NULL` without default | NO — split into 3 revisions: add nullable, backfill, set NOT NULL |
| `DROP COLUMN` | YES, but gated behind application-level deprecation (one release cycle) |
| `DROP TABLE` in prod | NO — only via documented backup/restore runbook |
| `ALTER COLUMN TYPE` | YES for widening; for narrowing requires backfill + validation step |
| `DROP INDEX` | YES, pair with `CREATE INDEX CONCURRENTLY` for replacement |

## Indexing

- Create indexes with `CREATE INDEX CONCURRENTLY` in production; Alembic revision must set `op.execute("COMMIT")` before concurrent index DDL.
- Every FK column has a matching index unless explicitly justified.
- Use partial indexes for boolean/status filters with skewed cardinality.

## Constraints

- FK constraints: `ON DELETE` policy must be explicit (RESTRICT by default; CASCADE only for owned aggregates, documented).
- CHECK constraints enforce domain invariants (e.g., `balance >= 0`, `leverage BETWEEN 1 AND 500`).
- Use DB-level enums sparingly — string + CHECK is easier to evolve.

## Naming

- Tables: plural snake_case (`trade_audit_log`, `account_snapshot`).
- Columns: singular snake_case; booleans prefixed `is_` / `has_`.
- Indexes: `ix_<table>_<col>[_<col>]`. Unique: `uq_<table>_<col>`. FKs: `fk_<table>_<ref_table>`.

## Review Gate

Any migration PR MUST be reviewed by `database-reviewer` before merge.
