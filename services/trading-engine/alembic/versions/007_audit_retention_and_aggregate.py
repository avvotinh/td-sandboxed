"""audit_logs retention + continuous aggregate + compression.

Revision ID: 007_audit_retention_and_aggregate
Revises: 006_trades_strategy_index
Create Date: ported 2026-05-01 (story 10.10)

Ported verbatim from
``infra/timescaledb/migrations/007_audit_retention_and_aggregate.sql``
(story 7.2). Order matters: retention → continuous aggregate →
compression so retention can drop chunks without first decompressing.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "007_audit_retention_and_aggregate"
down_revision: Union[str, Sequence[str], None] = "006_trades_strategy_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = """
-- 1. Retention: drop raw rows older than 90 days.
SELECT add_retention_policy('audit_logs', INTERVAL '90 days', if_not_exists => TRUE);

-- 2. Continuous aggregate — daily audit summaries.
-- Refresh policy uses end_offset='1 hour'; real-time data from the last
-- hour requires querying the raw audit_logs hypertable directly.
CREATE MATERIALIZED VIEW IF NOT EXISTS audit_daily_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', timestamp) AS day,
    account_id,
    event_type,
    COUNT(*) AS event_count,
    COUNT(*) FILTER (WHERE level = 'WARNING') AS warning_count,
    COUNT(*) FILTER (WHERE level = 'ERROR')   AS error_count
FROM audit_logs
GROUP BY day, account_id, event_type;

-- 3. Refresh policy: rebuild last 3 days every hour.
SELECT add_continuous_aggregate_policy(
    'audit_daily_summary',
    start_offset    => INTERVAL '3 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE
);

-- 4. Aggregate retention: keep daily summaries for 1 year.
SELECT add_retention_policy('audit_daily_summary', INTERVAL '365 days', if_not_exists => TRUE);

-- 5. Compression on raw audit_logs (chunks older than 7 days).
ALTER TABLE audit_logs SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'account_id',
    timescaledb.compress_orderby = 'timestamp DESC'
);

-- 6. Compression policy.
SELECT add_compression_policy('audit_logs', INTERVAL '7 days', if_not_exists => TRUE);
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    # Reversible: drop the policies + the continuous aggregate. The raw
    # hypertable + its data stay intact.
    op.execute(
        """
        SELECT remove_compression_policy('audit_logs', if_exists => TRUE);
        ALTER TABLE audit_logs SET (timescaledb.compress = FALSE);
        SELECT remove_retention_policy('audit_daily_summary', if_exists => TRUE);
        SELECT remove_continuous_aggregate_policy('audit_daily_summary', if_exists => TRUE);
        DROP MATERIALIZED VIEW IF EXISTS audit_daily_summary;
        SELECT remove_retention_policy('audit_logs', if_exists => TRUE);
        """
    )
