-- Story 10.14: drop legacy `prop_firms` table + `accounts.prop_firm_id`
-- column.
--
-- Story 10.12 dropped the application-level `AccountConfig.prop_firm`
-- field and 10.13 removed the rule-engine preset loader; this
-- migration retires the schema artefacts the legacy preset path used.
--
-- Gate: every prop-firm-typed account must already be on
-- firm_id+product_id+phase before this runs (see
-- `trading-engine accounts audit-rules-source --strict` from story
-- 10.11). The pre-flight DO block enforces that gate inline so the
-- migration cannot silently leave production in a half-migrated state.
--
-- Per .claude/rules/database/schema.md, DROP TABLE in production must
-- be paired with the backup/restore runbook. Take a `pg_dump` snapshot
-- before applying.
--
-- Test alongside `services/trading-engine/alembic/versions/011_drop_prop_firm_legacy.py`.

-- Run inside a transaction. When applied via Alembic the `op.execute()`
-- already wraps in `context.begin_transaction()` so we cannot add our
-- own BEGIN/COMMIT here (Postgres does not nest transactions; the
-- inner BEGIN would be silently ignored, masking commit failures).
-- For direct ops use, wrap with `psql --single-transaction -f ...`
-- or surround with BEGIN; / COMMIT; manually before applying.

-- Lock the table for the entire migration so a concurrent writer can't
-- INSERT/UPDATE a prop_firm_id row between the count check and the
-- DROP COLUMN. SHARE ROW EXCLUSIVE blocks writers but lets read-only
-- queries continue.
LOCK TABLE accounts IN SHARE ROW EXCLUSIVE MODE;

-- Audit-trail discipline (.claude/rules/database/audit.md): record the
-- structural write before mutating the financial table.
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

-- Pre-flight gate ------------------------------------------------------
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

-- Forward migration ----------------------------------------------------
DROP INDEX IF EXISTS idx_accounts_prop_firm;
ALTER TABLE accounts DROP COLUMN IF EXISTS prop_firm_id;
-- ``IF EXISTS`` on the table drop guards Alembic-chain-only environments
-- where ``prop_firms`` was never bootstrapped through ``init.sql`` —
-- the silent-success in that path is intentional, not a chain-failure
-- concealer. Real chain breakage surfaces at the column drop above.
DROP TABLE IF EXISTS prop_firms;
