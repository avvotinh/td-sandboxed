---
paths:
  - "**/alembic/**/*.py"
  - "**/migrations/**/*.sql"
---
# TimescaleDB Rules

## Hypertables

Active hypertables (per `sandboxed-domain.md`):

| Table | Time column | Chunk interval | Retention |
|---|---|---|---|
| `trade_audit_log` | `ts` | 1 day | 180 days |
| `rule_check_log` | `ts` | 1 day | 180 days |
| `account_snapshot` | `ts` | 1 hour | 180 days |

## Creation Pattern

```python
# in an Alembic revision
op.execute("""
    SELECT create_hypertable(
        'trade_audit_log',
        'ts',
        chunk_time_interval => INTERVAL '1 day',
        if_not_exists => TRUE
    );
""")
```

## Retention Policy

Retention MUST be set via policy job, not cron:

```python
op.execute("""
    SELECT add_retention_policy(
        'trade_audit_log',
        INTERVAL '180 days',
        if_not_exists => TRUE
    );
""")
```

## Compression

- Enable compression on hypertables older than 7 days.
- Compressed chunks are read-only — late-arriving rows must use `decompress_chunk` or be routed to a staging table.

```python
op.execute("""
    ALTER TABLE trade_audit_log SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'account_id'
    );
    SELECT add_compression_policy('trade_audit_log', INTERVAL '7 days');
""")
```

## Query Patterns

- Always filter on the time column first — TimescaleDB pruning depends on it.
- Use `time_bucket()` for aggregation, never raw `date_trunc()` on hypertables at scale.
- Continuous aggregates for dashboards > 1M rows:
  ```sql
  CREATE MATERIALIZED VIEW account_daily_pnl
  WITH (timescaledb.continuous) AS
  SELECT time_bucket('1 day', ts) AS day, account_id, sum(pnl) AS pnl
  FROM trade_audit_log
  GROUP BY day, account_id;
  ```

## Forbidden

- `SELECT *` without a `ts` predicate on hypertables — will scan all chunks.
- `UPDATE` / `DELETE` on compressed chunks without decompressing first.
- Manual `DROP CHUNK` in prod — use retention policy only.
