-- Epic 9 / P0.3: multi-firm account binding
--
-- Introduces the firm_id + product_id + phase tuple + per-account rule_overrides
-- on the `accounts` table. The pre-existing `prop_firm_id` column stays for
-- backwards compatibility with Epic 4 preset-based accounts. P0.11 migrates
-- the remaining YAML presets into configs/firms/*.yaml; a later story will
-- drop `prop_firm_id` after the deprecation window.
--
-- Application-level validation (`AccountConfig.validate_rules_source` in
-- services/trading-engine/src/accounts/models.py) already enforces that
-- exactly one rule source is set per account. The DB-level CHECKs below
-- are the defence-in-depth layer for direct SQL writes, backfills, and
-- future services.

BEGIN;

-- NOTE: `rule_overrides JSONB DEFAULT '{}' NOT NULL` is added in a single
-- ALTER — this is the documented PostgreSQL 11+ exception to the
-- "NOT NULL without default" 3-revision rule in .claude/rules/database/
-- schema.md: literal defaults on JSONB land in pg_catalog without
-- rewriting the heap, so there is no lock-holding table rewrite. The
-- `accounts` table is ≤ a few hundred rows and lives outside the hot
-- trading path; even a rewrite would be safe in a maintenance window.
-- When Alembic is bootstrapped, port this revision with the three-step
-- pattern to keep the rule general.
ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS firm_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS product_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS phase VARCHAR(50),
    ADD COLUMN IF NOT EXISTS rule_overrides JSONB DEFAULT '{}'::jsonb NOT NULL;

-- Cross-column invariant: firm binding is all-or-nothing.
-- Row passes when (all three NULL) OR (all three NOT NULL); rejected
-- otherwise — e.g., setting firm_id without product_id is illegal.
ALTER TABLE accounts
    DROP CONSTRAINT IF EXISTS accounts_firm_binding_consistent;

ALTER TABLE accounts
    ADD CONSTRAINT accounts_firm_binding_consistent
    CHECK (
        (firm_id IS NULL AND product_id IS NULL AND phase IS NULL)
        OR (firm_id IS NOT NULL AND product_id IS NOT NULL AND phase IS NOT NULL)
    );

-- rule_overrides are only meaningful on firm-bound accounts. Legacy
-- `prop_firm_id`-bound rows (where firm_id IS NULL) MUST keep the default
-- empty object. Violation case (row rejected): rule_overrides is non-empty
-- AND firm_id IS NULL.
ALTER TABLE accounts
    DROP CONSTRAINT IF EXISTS accounts_rule_overrides_scope;

ALTER TABLE accounts
    ADD CONSTRAINT accounts_rule_overrides_scope
    CHECK (
        firm_id IS NOT NULL OR rule_overrides = '{}'::jsonb
    );

-- Lookup index for firm-scoped queries (e.g. "all accounts on
-- FTMO challenge eval"). Partial index excludes legacy preset rows where
-- firm_id IS NULL — tiny table today but documents the access pattern.
-- CONCURRENTLY is not used here; migrations 005–008 follow the same
-- pattern because this DDL runs in the bootstrap / low-traffic window.
-- When Alembic is bootstrapped, switch to CREATE INDEX CONCURRENTLY
-- per .claude/rules/database/schema.md.
CREATE INDEX IF NOT EXISTS ix_accounts_firm_product_phase
    ON accounts (firm_id, product_id, phase)
    WHERE firm_id IS NOT NULL;

COMMIT;

-- =============================================================================
-- Rollback (manual — no Alembic downgrade yet).
-- =============================================================================
-- Order matters: drop the index and constraints BEFORE the columns. Although
-- `DROP COLUMN` would implicitly drop dependent CHECKs, doing it explicitly
-- makes the rollback traceable and avoids surprise cascades if new
-- constraints referencing these columns are added later.
--
-- BEGIN;
--     DROP INDEX IF EXISTS ix_accounts_firm_product_phase;
--     ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_rule_overrides_scope;
--     ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_firm_binding_consistent;
--     ALTER TABLE accounts
--         DROP COLUMN IF EXISTS rule_overrides,
--         DROP COLUMN IF EXISTS phase,
--         DROP COLUMN IF EXISTS product_id,
--         DROP COLUMN IF EXISTS firm_id;
-- COMMIT;
