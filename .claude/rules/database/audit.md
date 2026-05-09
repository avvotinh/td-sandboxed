---
paths:
  - "**/models/account*.py"
  - "**/services/**/audit*.py"
  - "**/alembic/**/*.py"
---
# Audit & Financial Integrity

> Extends [common/security.md](../common/security.md) FTMO section.

## Double-Entry Discipline

- Every write to `account.*` tables MUST be preceded (within the same DB transaction) by an `audit_log` insert. No exceptions.
- `audit_log` row captures: `(ts, actor, action, target_table, target_id, before_json, after_json, correlation_id)`.
- Rollback on audit failure — the account mutation never commits without the audit row.

## Balance / Equity Reads

- Hot path reads: Redis snapshot only (`account:{id}:snapshot`).
- NEVER recompute balance from `trade_audit_log` in request path — O(N) over 180 days of trades.
- Reconciliation job (offline) recomputes from audit trail and alerts on Redis drift.

## Correlation IDs

- Every inbound request (webhook, ZeroMQ order) allocates a `correlation_id` (ULID).
- ID flows through: `audit_log`, Redis keys, notification messages, log lines.
- Makes cross-service tracing possible without distributed tracing infra.

## Migrations Touching Financial Tables

PRs modifying any of these tables require `database-reviewer` + `security-reviewer` sign-off:

- `account`, `account_snapshot`
- `trade_audit_log`, `rule_check_log`
- `audit_log`
- any table with `balance`, `equity`, `pnl`, `drawdown` columns

## Backups

- Nightly `pg_dump` to offsite storage — retention 30 days.
- Before any destructive migration in prod: manual snapshot + runbook entry.
