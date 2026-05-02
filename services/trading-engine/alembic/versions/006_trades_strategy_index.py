"""Add (strategy_name, entry_time DESC) index on trades.

Revision ID: 006_trades_strategy_index
Revises: 005_state_snapshots
Create Date: ported 2026-05-01 (story 10.10)

Ported verbatim from
``infra/timescaledb/migrations/006_add_trades_strategy_index.sql``
(story 7.1 trade execution audit logging). The ORM model already
declared this index but ``init.sql`` did not include it.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "006_trades_strategy_index"
down_revision: Union[str, Sequence[str], None] = "005_state_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_trades_strategy
            ON trades (strategy_name, entry_time DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_trades_strategy;")
