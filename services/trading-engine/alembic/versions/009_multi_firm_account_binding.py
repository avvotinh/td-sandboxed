"""Multi-firm account binding — firm_id + product_id + phase + rule_overrides.

Revision ID: 009_multi_firm_account_binding
Revises: 008_violations_retention_and_aggregate
Create Date: ported 2026-05-01 (story 10.10)

Ported verbatim from
``infra/timescaledb/migrations/009_multi_firm_account_binding.sql``
(Epic 9 / P0.3). Adds the firm-binding triple and per-account
``rule_overrides`` JSONB to ``accounts``, with two CHECK constraints
that mirror the application-level validation in
``src/accounts/models.py::AccountConfig.validate_rules_source``.

The original migration intentionally added the JSONB column NOT NULL
with a literal default in a single ALTER — Postgres 11+ stores the
default in pg_catalog without a heap rewrite, and ``accounts`` is a
small admin table outside the trading hot path. The 3-revision
"NOT NULL without default" pattern from
``.claude/rules/database/schema.md`` does not apply here; the rule
generally still holds for hot-path tables.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "009_multi_firm_account_binding"
down_revision: Union[str, Sequence[str], None] = "008_violations_retention_and_aggregate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = """
ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS firm_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS product_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS phase VARCHAR(50),
    ADD COLUMN IF NOT EXISTS rule_overrides JSONB DEFAULT '{}'::jsonb NOT NULL;

-- All-or-nothing firm binding.
ALTER TABLE accounts
    DROP CONSTRAINT IF EXISTS accounts_firm_binding_consistent;
ALTER TABLE accounts
    ADD CONSTRAINT accounts_firm_binding_consistent
    CHECK (
        (firm_id IS NULL AND product_id IS NULL AND phase IS NULL)
        OR (firm_id IS NOT NULL AND product_id IS NOT NULL AND phase IS NOT NULL)
    );

-- rule_overrides only meaningful on firm-bound accounts.
ALTER TABLE accounts
    DROP CONSTRAINT IF EXISTS accounts_rule_overrides_scope;
ALTER TABLE accounts
    ADD CONSTRAINT accounts_rule_overrides_scope
    CHECK (
        firm_id IS NOT NULL OR rule_overrides = '{}'::jsonb
    );

-- Lookup index for firm-scoped queries. Partial index excludes legacy
-- preset rows. Bootstrap-time DDL — production hot-add of firm-bound
-- accounts after this revision should switch to CREATE INDEX
-- CONCURRENTLY per .claude/rules/database/schema.md.
CREATE INDEX IF NOT EXISTS ix_accounts_firm_product_phase
    ON accounts (firm_id, product_id, phase)
    WHERE firm_id IS NOT NULL;
"""


_DOWNGRADE_SQL = """
DROP INDEX IF EXISTS ix_accounts_firm_product_phase;
ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_rule_overrides_scope;
ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_firm_binding_consistent;
ALTER TABLE accounts
    DROP COLUMN IF EXISTS rule_overrides,
    DROP COLUMN IF EXISTS phase,
    DROP COLUMN IF EXISTS product_id,
    DROP COLUMN IF EXISTS firm_id;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
