"""Drop legacy ``prop_firms`` table + ``accounts.prop_firm_id`` column.

Revision ID: 011_drop_prop_firm_legacy
Revises: 010_rename_ftmo_audit_events
Create Date: 2026-05-02 (story 10.14)

Story 10.14 — final piece of the Phase 5 cleanup. Story 10.12 dropped
the application-level ``AccountConfig.prop_firm`` field and 10.13
removed the rule-engine preset loader; this migration retires the
schema artefacts the legacy preset path used:

- ``accounts.prop_firm_id`` (FK to ``prop_firms.id``) — dropped.
- ``idx_accounts_prop_firm`` — dropped (column gone).
- ``prop_firms`` table — dropped.

Pre-flight gate
---------------

Per ``.claude/rules/database/schema.md`` ``DROP TABLE`` in production is
gated by the documented backup/restore runbook. This migration enforces
that gate at the SQL level: it refuses to run while any account row
still references a ``prop_firms.id`` (i.e. ``prop_firm_id IS NOT NULL``).
The migration audit CLI shipped in story 10.11 (
``trading-engine accounts audit-rules-source --strict``) is the
operational sign-off that produces this state.

Down-grade
----------

There is no automatic downgrade. Re-creating ``prop_firms`` from a fresh
schema would not restore the per-account FK rows the application no
longer carries. ``downgrade()`` raises ``NotImplementedError`` — restore
from the pre-migration ``pg_dump`` instead, per the destructive-ops
runbook.

Review gate
-----------

Per ``.claude/rules/database/audit.md`` and ``schema.md``, this PR
requires both ``database-reviewer`` and ``security-reviewer`` sign-off
(``accounts`` is the financial-table list and the migration drops a
column from it). The audit gate above + manual ``pg_dump`` are the
defenses against data loss.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "011_drop_prop_firm_legacy"
down_revision: Union[str, Sequence[str], None] = "010_rename_ftmo_audit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = r"""
-- Lock the table for the entire migration so a concurrent writer can't
-- INSERT/UPDATE a prop_firm_id row between the count check and the
-- DROP COLUMN — `accounts` is admin-mutated only, but the gate must
-- be airtight either way. SHARE ROW EXCLUSIVE blocks writers but lets
-- read-only queries continue.
LOCK TABLE accounts IN SHARE ROW EXCLUSIVE MODE;

-- Audit-trail discipline: per .claude/rules/database/audit.md, every
-- write to `accounts.*` must be preceded by an `audit_log` insert in
-- the same transaction. ``DROP COLUMN`` is a destructive structural
-- write — record the schema mutation so post-incident forensics can
-- correlate the column going away with the migration that caused it.
INSERT INTO audit_logs (
    timestamp, account_id, event_type, event_subtype, source, level,
    message, rule_name, rule_result, context
) VALUES (
    NOW(),
    NULL,
    'system_event',
    'schema_migration',
    'alembic',
    'WARNING',
    'Story 10.14: DROP COLUMN accounts.prop_firm_id + DROP TABLE prop_firms',
    '',
    '',
    '{"revision": "011_drop_prop_firm_legacy", "story": "10.14"}'::jsonb
);

-- Pre-flight gate: every prop-firm-typed account must already be on
-- the firm-bound path (story 10.11 audit). Refuse to run while any
-- ``prop_firm_id`` is still populated — operators ran
-- ``trading-engine accounts audit-rules-source --strict`` before this.
DO $$
DECLARE
    legacy_count INTEGER;
BEGIN
    SELECT COUNT(*)
      INTO legacy_count
      FROM accounts
     WHERE prop_firm_id IS NOT NULL;

    IF legacy_count > 0 THEN
        RAISE EXCEPTION
            'Refusing to drop accounts.prop_firm_id: % account row(s) '
            'still reference a prop_firms.id. Migrate them to '
            'firm_id+product_id+phase first (see story 10.11 audit CLI), '
            'or run a manual pg_dump and clear the column before retrying.',
            legacy_count;
    END IF;
END $$;

-- Drop the partial index keyed on prop_firm_id before the column.
-- ``IF EXISTS`` because the index originates from ``init.sql`` only —
-- fresh-deploy DBs created from init have it, but Alembic-chain-only
-- environments do not. Both paths land in the same end state.
DROP INDEX IF EXISTS idx_accounts_prop_firm;

-- Drop the column. The FK constraint goes with it.
ALTER TABLE accounts DROP COLUMN IF EXISTS prop_firm_id;

-- Drop the reference table itself. CASCADE is intentionally NOT used —
-- the only FK pointing at ``prop_firms`` was the one we just removed,
-- so a plain DROP TABLE confirms there is nothing else still attached.
-- Any unrelated dependency surfaces here as an explicit error rather
-- than a silent cascade. Operators should run ``\\d prop_firms`` and
-- check ``information_schema.view_table_usage`` before applying to
-- catch external dependencies (e.g., reporting views in another DB).
DROP TABLE IF EXISTS prop_firms;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    # Re-creating ``prop_firms`` would not restore per-account FK rows;
    # the only safe rollback is restoring from the pre-migration backup.
    raise NotImplementedError(
        "Downgrade of 011_drop_prop_firm_legacy is intentionally "
        "unimplemented. ``DROP TABLE prop_firms`` is destructive — "
        "restore from the pre-migration pg_dump per the destructive-ops "
        "runbook. See .claude/rules/database/schema.md."
    )
