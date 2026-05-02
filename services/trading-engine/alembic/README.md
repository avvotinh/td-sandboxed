# Alembic — Sandboxed trading engine schema migrations

Story 10.10 introduced this directory. Schema changes for the
trading-engine TimescaleDB now flow through Alembic; the historical
raw-SQL files in `infra/timescaledb/migrations/` are preserved for
audit but new revisions go here.

## Bootstrap

### Existing environment (raw SQL 005-010 already applied)

Stamp the head so Alembic recognises the current state without re-running:

```bash
DATABASE_URL=postgresql://user:pass@host/trading \
    uv run alembic stamp 010_rename_ftmo_audit_events
```

### Fresh environment

1. Apply the base schema:

   ```bash
   psql -d trading -f infra/timescaledb/init.sql
   ```

2. Apply the Alembic chain:

   ```bash
   DATABASE_URL=postgresql://user:pass@host/trading \
       uv run alembic upgrade head
   ```

## Day-to-day

```bash
# Inspect chain
DATABASE_URL=... uv run alembic history

# Show current revision
DATABASE_URL=... uv run alembic current

# Create a new revision (autogenerate is OFF — write op.execute by hand)
DATABASE_URL=... uv run alembic revision -m "<slug>"
```

## Rules

- `target_metadata = None` in `env.py` — autogenerate is intentionally
  disabled. TimescaleDB DDL (hypertables, retention, continuous
  aggregates, compression) is not understood by SQLAlchemy's
  comparator; every revision is hand-written with `op.execute(...)`.
- `DATABASE_URL` is the canonical source. The `sqlalchemy+asyncpg`
  prefix used by the application engine is coerced to `postgresql://`
  automatically (`psycopg2-binary` is bundled for this).
- Downgrade for hypertables that hold audit-trail data
  (`state_snapshots`, `audit_logs`) raises `NotImplementedError` —
  reverse the change via documented backup/restore. See
  `.claude/rules/database/schema.md` §"DROP TABLE in prod".
- PRs that touch `audit_logs` / `rule_violations` / financial-integrity
  tables require both `database-reviewer` AND `security-reviewer`
  sign-off (see `.claude/rules/database/audit.md`).

## Ported revisions

| Revision | Source SQL | Effort / story |
|---|---|---|
| `005_state_snapshots` | `005_state_snapshots.sql` | Story 5.7 — cold storage |
| `006_trades_strategy_index` | `006_add_trades_strategy_index.sql` | Story 7.1 — trade audit |
| `007_audit_retention_and_aggregate` | `007_audit_retention_and_aggregate.sql` | Story 7.2 |
| `008_violations_retention_and_aggregate` | `008_violations_retention_and_aggregate.sql` | Story 7.3 |
| `009_multi_firm_account_binding` | `009_multi_firm_account_binding.sql` | Epic 9 / P0.3 |
| `010_rename_ftmo_audit_events` | `010_rename_ftmo_audit_events.sql` | Epic 9 / P0.4 |
