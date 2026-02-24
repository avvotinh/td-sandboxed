-- Story 7.3: Add retention, continuous aggregate, and compression for rule_violations
-- ORDER: retention -> continuous aggregate -> compression
-- Retention first avoids needing to decompress chunks before dropping them

-- 1. Add retention policy (remove raw data older than 90 days)
SELECT add_retention_policy('rule_violations', INTERVAL '90 days');

-- 2. Create continuous aggregate for daily violation summaries
-- NOTE: Refresh policy uses end_offset='1 hour', so real-time data from the last hour
-- requires querying the raw rule_violations hypertable directly.
CREATE MATERIALIZED VIEW violation_daily_summary
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 day', timestamp) AS day,
  account_id,
  rule_type,
  COUNT(*) as violation_count,
  COUNT(*) FILTER (WHERE severity = 'CRITICAL' OR severity = 'FATAL') as critical_count,
  COUNT(*) FILTER (WHERE severity = 'WARNING') as warning_count,
  COUNT(*) FILTER (WHERE order_blocked = TRUE) as blocked_count,
  MAX(current_value) as peak_value,
  MIN(threshold_value) as min_threshold
FROM rule_violations
GROUP BY day, account_id, rule_type;

-- 3. Add refresh policy for continuous aggregate (refresh last 3 days every hour)
SELECT add_continuous_aggregate_policy('violation_daily_summary',
  start_offset => INTERVAL '3 days',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour');

-- 4. Add retention policy for aggregate (keep summaries for 1 year)
SELECT add_retention_policy('violation_daily_summary', INTERVAL '365 days');

-- 5. Enable compression on rule_violations
ALTER TABLE rule_violations SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'account_id',
  timescaledb.compress_orderby = 'timestamp DESC'
);

-- 6. Add compression policy (compress chunks older than 7 days)
SELECT add_compression_policy('rule_violations', INTERVAL '7 days');
