"""state_snapshots hypertable for cold storage backup.

Revision ID: 005_state_snapshots
Revises: (None — first revision in the chain after init.sql baseline)
Create Date: ported 2026-05-01 (story 10.10)

Ported verbatim from ``infra/timescaledb/migrations/005_state_snapshots.sql``
(story 5.7). Idempotent — safe to run on a DB that already has the
table from the raw-SQL apply path.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "005_state_snapshots"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE tablename = 'state_snapshots') THEN
        CREATE TABLE state_snapshots (
            id UUID DEFAULT gen_random_uuid(),
            account_id VARCHAR(50) NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            positions JSONB NOT NULL,
            pending_orders JSONB NOT NULL,
            account_balance DECIMAL(18, 2) NOT NULL,
            equity DECIMAL(18, 2) NOT NULL,
            peak_balance DECIMAL(18, 2) NOT NULL,
            daily_starting_balance DECIMAL(18, 2) NOT NULL,
            checksum VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        PERFORM create_hypertable('state_snapshots', 'timestamp');

        CREATE UNIQUE INDEX idx_state_snapshots_id
            ON state_snapshots (id, timestamp);
        CREATE INDEX idx_state_snapshots_account
            ON state_snapshots (account_id, timestamp DESC);

        ALTER TABLE state_snapshots
            ADD CONSTRAINT fk_state_snapshots_account
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

        PERFORM add_retention_policy('state_snapshots', INTERVAL '7 days');

        RAISE NOTICE 'state_snapshots table created successfully';
    ELSE
        RAISE NOTICE 'state_snapshots table already exists, skipping';
    END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    # Dropping the hypertable destroys retained snapshot data — the
    # canonical reverse-migration would be a manual restore from
    # backup. Refuse to do it silently in a migration.
    raise NotImplementedError(
        "Downgrade of 005_state_snapshots requires a manual restore — "
        "dropping the hypertable would lose audit-trail data. See "
        ".claude/rules/database/schema.md §'DROP TABLE in prod'."
    )
