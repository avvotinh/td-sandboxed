-- Migration 006: Add strategy+entry_time index to trades table
-- Required for: Story 7.1 (Trade Execution Audit Logging)
-- The ORM model defines this index but init.sql does not include it.
-- This index enables efficient queries by strategy_name with time ordering.

CREATE INDEX IF NOT EXISTS idx_trades_strategy
    ON trades (strategy_name, entry_time DESC);
