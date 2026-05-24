"""audit_logs retention 90 -> 180 days.

Revision ID: 012_audit_logs_retention_180
Revises: 011_drop_prop_firm_legacy
Create Date: 2026-05-24 (Epic 15 story 15.3)

Migration 007 set ``audit_logs`` retention to 90 days, but FTMO compliance
requires a 180-day audit trail (``.claude/rules/database/timescale.md`` +
``sandboxed-domain.md``). This revision swaps the retention policy: remove the
existing one, add a 180-day one.

Retention-policy-only — the table is never dropped and no rows are lost. The
hypertable and its data are untouched; the continuous aggregate
(``audit_daily_summary``) and compression policy from revision 007 are left
exactly as they are.

Review gate: touches the ``audit_logs`` financial-audit table, so per
``.claude/rules/database/audit.md`` it requires ``database-reviewer`` +
``security-reviewer`` sign-off before merging to main. The change itself was
prescribed by the database-reviewer (RegimeActor design review, finding F1).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "012_audit_logs_retention_180"
down_revision: Union[str, Sequence[str], None] = "011_drop_prop_firm_legacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = """
-- audit_logs retention 90 -> 180 days (FTMO compliance; revision 007 set 90).
SELECT remove_retention_policy('audit_logs', if_exists => TRUE);
SELECT add_retention_policy('audit_logs', INTERVAL '180 days', if_not_exists => TRUE);
"""


_DOWNGRADE_SQL = """
-- Restore the revision-007 value (90 days).
SELECT remove_retention_policy('audit_logs', if_exists => TRUE);
SELECT add_retention_policy('audit_logs', INTERVAL '90 days', if_not_exists => TRUE);
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
