-- Epic 9 / P0.4: rename legacy `ftmo_*` audit event_type values → `prop_firm_*`
--
-- Per ``docs/epic-9-context.md`` this is a hard cutover (option 1 in the
-- open questions section) — no dual-write, no compat alias in application
-- code. The AuditEventType enum (src/rules/audit_logger.py) never held
-- FTMO-prefixed values in production, so in steady state this migration
-- updates zero rows. It is kept as a safety-net in case any operator,
-- script, or earlier in-flight feature branch wrote bespoke `ftmo_*`
-- values into `audit_logs.event_type` or `event_subtype`.
--
-- The `audit_logs` hypertable keeps 180 days of data (see
-- infra/timescaledb/migrations/007_audit_retention_and_aggregate.sql).
-- Running this migration rewrites a very small set of rows (if any);
-- hypertable chunk-by-chunk update is safe in a maintenance window.
--
-- Per .claude/rules/database/audit.md this migration touches an audit
-- financial-integrity table — both `database-reviewer` AND
-- `security-reviewer` sign-off are required for any PR that lands this.

BEGIN;

-- Pre-flight guard: compressed chunks are read-only; UPDATE on them
-- fails at runtime. `audit_logs` has no compression policy today (see
-- migration 007), but `.claude/rules/database/timescale.md` calls out
-- enabling compression on chunks older than 7 days. If a future
-- compression policy lands before this migration runs, fail loudly so
-- the operator decompresses the relevant chunks first rather than
-- discovering the breakage mid-transaction.
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

-- event_type normalisation (prefix rewrite).
-- The `timestamp >= NOW() - INTERVAL '180 days'` predicate matches the
-- existing retention policy and lets the TimescaleDB planner prune
-- chunks instead of opening all 180 chunks for a full hypertable scan.
-- The 180-day bound is deliberately aligned with retention: anything
-- older than that has already been dropped by the retention policy.
UPDATE audit_logs
   SET event_type = REPLACE(event_type, 'ftmo_', 'prop_firm_')
 WHERE timestamp >= NOW() - INTERVAL '180 days'
   AND event_type LIKE 'ftmo\_%' ESCAPE '\';

-- event_subtype normalisation — same chunk-pruning predicate.
UPDATE audit_logs
   SET event_subtype = REPLACE(event_subtype, 'ftmo_', 'prop_firm_')
 WHERE timestamp >= NOW() - INTERVAL '180 days'
   AND event_subtype LIKE 'ftmo\_%' ESCAPE '\';

COMMIT;

-- =============================================================================
-- Rollback (manual).
-- =============================================================================
-- Equivalent inverse — maps `prop_firm_` prefix back to `ftmo_`. Only safe
-- to run if the code has been rolled back to the pre-P0.4 naming; otherwise
-- application writes will immediately re-emit `prop_firm_*` values and the
-- table will hold both prefixes in a mixed state.
--
-- BEGIN;
--     UPDATE audit_logs
--        SET event_type = 'ftmo_' || substring(event_type FROM length('prop_firm_') + 1)
--      WHERE timestamp >= NOW() - INTERVAL '180 days'
--        AND event_type LIKE 'prop_firm\_%' ESCAPE '\';
--     UPDATE audit_logs
--        SET event_subtype = 'ftmo_' || substring(event_subtype FROM length('prop_firm_') + 1)
--      WHERE timestamp >= NOW() - INTERVAL '180 days'
--        AND event_subtype LIKE 'prop_firm\_%' ESCAPE '\';
-- COMMIT;
