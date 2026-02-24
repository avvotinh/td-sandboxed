-- Story 7.2: Add retention policy, continuous aggregate, and compression for audit_logs
-- ORDER: retention -> continuous aggregate -> compression
-- Retention first avoids needing to decompress chunks before dropping them

-- 1. Add retention policy (remove raw data older than 90 days)
SELECT add_retention_policy('audit_logs', INTERVAL '90 days');

-- 2. Create continuous aggregate for daily audit summaries
-- NOTE: Refresh policy uses end_offset='1 hour', so real-time data from the last hour
-- requires querying the raw audit_logs hypertable directly.
CREATE MATERIALIZED VIEW audit_daily_summary
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 day', timestamp) AS day,
  account_id,
  event_type,
  COUNT(*) as event_count,
  COUNT(*) FILTER (WHERE level = 'WARNING') as warning_count,
  COUNT(*) FILTER (WHERE level = 'ERROR') as error_count
FROM audit_logs
GROUP BY day, account_id, event_type;

-- 3. Add refresh policy for continuous aggregate (refresh last 3 days every hour)
SELECT add_continuous_aggregate_policy('audit_daily_summary',
  start_offset => INTERVAL '3 days',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour');

-- 4. Add retention policy for aggregate (keep summaries for 1 year)
SELECT add_retention_policy('audit_daily_summary', INTERVAL '365 days');

-- 5. Enable compression on audit_logs
ALTER TABLE audit_logs SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'account_id',
  timescaledb.compress_orderby = 'timestamp DESC'
);

-- 6. Add compression policy (compress chunks older than 7 days)
SELECT add_compression_policy('audit_logs', INTERVAL '7 days');
