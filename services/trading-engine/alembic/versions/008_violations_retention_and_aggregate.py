"""rule_violations retention + continuous aggregate + compression.

Revision ID: 008_violations_retention_and_aggregate
Revises: 007_audit_retention_and_aggregate
Create Date: ported 2026-05-01 (story 10.10)

Ported verbatim from
``infra/timescaledb/migrations/008_violations_retention_and_aggregate.sql``
(story 7.3). Mirrors the audit_logs pattern in revision 007.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "008_violations_retention_and_aggregate"
down_revision: Union[str, Sequence[str], None] = "007_audit_retention_and_aggregate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = """
-- 1. Retention: drop raw rows older than 90 days.
SELECT add_retention_policy('rule_violations', INTERVAL '90 days', if_not_exists => TRUE);

-- 2. Continuous aggregate — daily violation summaries.
CREATE MATERIALIZED VIEW IF NOT EXISTS violation_daily_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', timestamp) AS day,
    account_id,
    rule_type,
    COUNT(*) AS violation_count,
    COUNT(*) FILTER (WHERE severity IN ('CRITICAL', 'FATAL')) AS critical_count,
    COUNT(*) FILTER (WHERE severity = 'WARNING')              AS warning_count,
    COUNT(*) FILTER (WHERE order_blocked = TRUE)              AS blocked_count,
    MAX(current_value) AS peak_value,
    MIN(threshold_value) AS min_threshold
FROM rule_violations
GROUP BY day, account_id, rule_type;

-- 3. Refresh policy.
SELECT add_continuous_aggregate_policy(
    'violation_daily_summary',
    start_offset    => INTERVAL '3 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE
);

-- 4. Aggregate retention: 1 year.
SELECT add_retention_policy('violation_daily_summary', INTERVAL '365 days', if_not_exists => TRUE);

-- 5. Compression on raw rule_violations.
ALTER TABLE rule_violations SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'account_id',
    timescaledb.compress_orderby = 'timestamp DESC'
);

-- 6. Compression policy.
SELECT add_compression_policy('rule_violations', INTERVAL '7 days', if_not_exists => TRUE);
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(
        """
        SELECT remove_compression_policy('rule_violations', if_exists => TRUE);
        ALTER TABLE rule_violations SET (timescaledb.compress = FALSE);
        SELECT remove_retention_policy('violation_daily_summary', if_exists => TRUE);
        SELECT remove_continuous_aggregate_policy('violation_daily_summary', if_exists => TRUE);
        DROP MATERIALIZED VIEW IF EXISTS violation_daily_summary;
        SELECT remove_retention_policy('rule_violations', if_exists => TRUE);
        """
    )
