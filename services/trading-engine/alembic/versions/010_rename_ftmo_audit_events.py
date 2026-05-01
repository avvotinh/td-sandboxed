"""Rename legacy ftmo_* audit event_type/event_subtype values → prop_firm_*.

Revision ID: 010_rename_ftmo_audit_events
Revises: 009_multi_firm_account_binding
Create Date: ported 2026-05-01 (story 10.10)

Ported verbatim from
``infra/timescaledb/migrations/010_rename_ftmo_audit_events.sql``
(Epic 9 / P0.4). Hard cutover — no dual-write, no compat alias. The
``AuditEventType`` enum never held FTMO-prefixed values in production
in the first place, so in steady state this rewrites zero rows; it is
kept as a safety-net for in-flight feature branches and ad-hoc
operator scripts.

This migration touches an audit / financial-integrity table — per
``.claude/rules/database/audit.md`` PRs landing it require both
``database-reviewer`` AND ``security-reviewer`` sign-off. The
original raw-SQL migration carried that gate; this Alembic port
preserves it.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "010_rename_ftmo_audit_events"
down_revision: Union[str, Sequence[str], None] = "009_multi_firm_account_binding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = r"""
-- Pre-flight: compressed chunks are read-only. UPDATE on them fails
-- mid-transaction; surface the issue up front so the operator can
-- decompress before retrying. Compression isn't enabled on
-- audit_logs in 007, but a future policy change could land before
-- this migration runs on a long-running deployment.
DO $$
DECLARE
    compressed_count INTEGER;
BEGIN
    SELECT COUNT(*)
      INTO compressed_count
      FROM timescaledb_information.chunks
     WHERE hypertable_name = 'audit_logs'
       AND is_compressed = TRUE;
    IF compressed_count > 0 THEN
        RAISE EXCEPTION
            'audit_logs has % compressed chunk(s); decompress before running migration 010. '
            'See .claude/rules/database/timescale.md for `decompress_chunk` usage.',
            compressed_count;
    END IF;
END $$;

-- event_type normalisation.
-- The 180-day predicate matches the existing retention policy and lets
-- the TimescaleDB planner prune chunks instead of scanning all 180.
UPDATE audit_logs
   SET event_type = REPLACE(event_type, 'ftmo_', 'prop_firm_')
 WHERE timestamp >= NOW() - INTERVAL '180 days'
   AND event_type LIKE 'ftmo\_%' ESCAPE '\';

-- event_subtype normalisation.
UPDATE audit_logs
   SET event_subtype = REPLACE(event_subtype, 'ftmo_', 'prop_firm_')
 WHERE timestamp >= NOW() - INTERVAL '180 days'
   AND event_subtype LIKE 'ftmo\_%' ESCAPE '\';
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    # The inverse rewrite is only safe if application code has been
    # rolled back to the pre-P0.4 naming; otherwise application writes
    # immediately re-emit prop_firm_* and the table holds both prefixes
    # in a mixed state. Refuse silent rollback.
    raise NotImplementedError(
        "Downgrade of 010_rename_ftmo_audit_events is unsafe in a live "
        "deployment — application writes would mix prop_firm_* and "
        "ftmo_* values. Roll back the application code first, then "
        "apply the inverse REPLACE() manually as documented in the "
        "original SQL file's rollback section."
    )
