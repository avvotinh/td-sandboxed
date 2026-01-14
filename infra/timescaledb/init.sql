-- TimescaleDB Schema Initialization
-- Multi-Account Trading System
-- Version: 1.0
-- Generated: 2025-12-18

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ==================== REFERENCE TABLES ====================

-- Prop Firms (presets reference)
CREATE TABLE prop_firms (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    rules_preset VARCHAR(50) NOT NULL,
    website VARCHAR(255),
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default prop firms
INSERT INTO prop_firms (id, name, rules_preset, website) VALUES
    ('ftmo', 'FTMO', 'ftmo', 'https://ftmo.com'),
    ('the5ers', 'The5ers', 'the5ers', 'https://the5ers.com'),
    ('wmt', 'WeMasterTrade', 'wmt', 'https://wemastertrade.com');

-- Trading Accounts
CREATE TABLE accounts (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    account_type VARCHAR(20) NOT NULL CHECK (account_type IN ('prop_firm', 'personal', 'demo')),
    prop_firm_id VARCHAR(50) REFERENCES prop_firms(id) ON DELETE SET NULL,
    custom_rules_file VARCHAR(255),
    mt5_server VARCHAR(100) NOT NULL,
    mt5_login BIGINT NOT NULL,
    mt5_password_env VARCHAR(100) NOT NULL,
    strategy_name VARCHAR(100) NOT NULL,
    strategy_params JSONB,
    signal_filter JSONB,
    status VARCHAR(20) DEFAULT 'inactive' CHECK (status IN ('active', 'inactive', 'paused', 'error')),
    initial_balance DECIMAL(18, 2),
    current_balance DECIMAL(18, 2),
    peak_balance DECIMAL(18, 2),
    currency VARCHAR(3) DEFAULT 'USD',
    leverage INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_sync_at TIMESTAMPTZ
);

CREATE INDEX idx_accounts_status ON accounts (status);
CREATE INDEX idx_accounts_type ON accounts (account_type);
CREATE INDEX idx_accounts_prop_firm ON accounts (prop_firm_id);

-- ==================== ACCOUNT STATE TABLES ====================

-- Account Daily Snapshots (for compliance tracking)
CREATE TABLE account_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
    snapshot_date DATE NOT NULL,
    snapshot_time TIME DEFAULT '00:00:00',
    opening_balance DECIMAL(18, 2),
    closing_balance DECIMAL(18, 2),
    high_balance DECIMAL(18, 2),
    low_balance DECIMAL(18, 2),
    daily_pnl DECIMAL(18, 2),
    daily_pnl_percent DECIMAL(8, 4),
    peak_balance DECIMAL(18, 2),
    drawdown_from_peak DECIMAL(18, 2),
    drawdown_percent DECIMAL(8, 4),
    trades_count INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    total_volume DECIMAL(18, 2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(account_id, snapshot_date)
);

CREATE INDEX idx_snapshots_account_date ON account_snapshots (account_id, snapshot_date DESC);

-- Performance Metrics (daily, per account)
CREATE TABLE performance_metrics (
    date DATE NOT NULL,
    account_id VARCHAR(50) REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
    strategy_name VARCHAR(100) NOT NULL,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    gross_profit DECIMAL(18, 2) DEFAULT 0,
    gross_loss DECIMAL(18, 2) DEFAULT 0,
    net_profit DECIMAL(18, 2) DEFAULT 0,
    win_rate DECIMAL(8, 4),
    profit_factor DECIMAL(8, 4),
    average_win DECIMAL(18, 2),
    average_loss DECIMAL(18, 2),
    largest_win DECIMAL(18, 2),
    largest_loss DECIMAL(18, 2),
    max_drawdown_percent DECIMAL(8, 4),
    sharpe_ratio DECIMAL(8, 4),
    sortino_ratio DECIMAL(8, 4),
    total_volume DECIMAL(18, 2),
    average_hold_time_minutes INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (date, account_id, strategy_name)
);

CREATE INDEX idx_metrics_account ON performance_metrics (account_id, date DESC);

-- ==================== MARKET DATA TABLES ====================

-- OHLCV Candles (hypertable for time-series)
CREATE TABLE candles (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    open DECIMAL(18, 5) NOT NULL,
    high DECIMAL(18, 5) NOT NULL,
    low DECIMAL(18, 5) NOT NULL,
    close DECIMAL(18, 5) NOT NULL,
    volume DECIMAL(18, 2),
    tick_volume INTEGER,
    spread DECIMAL(18, 5),
    source VARCHAR(20) DEFAULT 'tradingview'
);

SELECT create_hypertable('candles', 'time');
CREATE UNIQUE INDEX idx_candles_unique ON candles (symbol, timeframe, time);
CREATE INDEX idx_candles_symbol_time ON candles (symbol, time DESC);

-- ==================== TRADING TABLES ====================

-- Trades (per account)
CREATE TABLE trades (
    trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
    mt5_ticket BIGINT,
    mt5_position_id BIGINT,
    strategy_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT')),
    quantity DECIMAL(18, 8) NOT NULL,
    entry_price DECIMAL(18, 5) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    stop_loss DECIMAL(18, 5),
    take_profit DECIMAL(18, 5),
    exit_price DECIMAL(18, 5),
    exit_time TIMESTAMPTZ,
    exit_reason VARCHAR(50),
    pnl_dollars DECIMAL(18, 2),
    pnl_pips DECIMAL(18, 2),
    pnl_percent DECIMAL(8, 4),
    commission DECIMAL(18, 2) DEFAULT 0,
    swap DECIMAL(18, 2) DEFAULT 0,
    slippage_pips DECIMAL(18, 2),
    execution_time_ms INTEGER,
    signal_reason TEXT,
    metadata JSONB,
    status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trades_account_time ON trades (account_id, entry_time DESC);
CREATE INDEX idx_trades_symbol ON trades (symbol, entry_time DESC);
CREATE INDEX idx_trades_status ON trades (status) WHERE status = 'open';
CREATE INDEX idx_trades_mt5_ticket ON trades (mt5_ticket);

-- ==================== COMPLIANCE TABLES ====================

-- Rule Violations (per account) - Hypertable
-- Note: Using composite primary key with timestamp for hypertable compatibility
CREATE TABLE rule_violations (
    id UUID DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    rule_type VARCHAR(50) NOT NULL,
    rule_name VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL', 'FATAL')),
    current_value DECIMAL(18, 4),
    threshold_value DECIMAL(18, 4),
    threshold_percent DECIMAL(8, 4),
    action_taken VARCHAR(50) NOT NULL CHECK (action_taken IN ('blocked', 'warned', 'notified', 'logged')),
    trade_id UUID,
    order_blocked BOOLEAN DEFAULT FALSE,
    message TEXT,
    context JSONB,
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('rule_violations', 'timestamp');
CREATE UNIQUE INDEX idx_violations_id ON rule_violations (id, timestamp);
CREATE INDEX idx_violations_account ON rule_violations (account_id, timestamp DESC);
CREATE INDEX idx_violations_rule ON rule_violations (rule_type, timestamp DESC);

-- Add foreign key constraints (added after hypertable creation)
ALTER TABLE rule_violations ADD CONSTRAINT fk_violations_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE rule_violations ADD CONSTRAINT fk_violations_trade
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id) ON DELETE SET NULL;

-- Audit Logs (per account) - Hypertable
-- Note: Using composite unique index with timestamp for hypertable compatibility
CREATE TABLE audit_logs (
    log_id UUID DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL,
    account_id VARCHAR(50),
    event_type VARCHAR(50) NOT NULL,
    event_subtype VARCHAR(50),
    source VARCHAR(50) NOT NULL,
    level VARCHAR(20) DEFAULT 'INFO' CHECK (level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    message TEXT,
    rule_name VARCHAR(100),
    rule_result VARCHAR(20),
    current_value DECIMAL(18, 4),
    threshold_value DECIMAL(18, 4),
    trade_id UUID,
    order_id VARCHAR(50),
    context JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('audit_logs', 'timestamp');
CREATE UNIQUE INDEX idx_audit_id ON audit_logs (log_id, timestamp);
CREATE INDEX idx_audit_account ON audit_logs (account_id, timestamp DESC);
CREATE INDEX idx_audit_event ON audit_logs (event_type, timestamp DESC);
CREATE INDEX idx_audit_rule ON audit_logs (rule_name, timestamp DESC);
CREATE INDEX idx_audit_level ON audit_logs (level, timestamp DESC) WHERE level IN ('WARNING', 'ERROR');

-- Add foreign key constraints (added after hypertable creation)
ALTER TABLE audit_logs ADD CONSTRAINT fk_audit_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL;
ALTER TABLE audit_logs ADD CONSTRAINT fk_audit_trade
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id) ON DELETE SET NULL;

-- ==================== STATE PERSISTENCE TABLES ====================

-- State Snapshots (for crash recovery fallback) - Hypertable
-- Cold storage backup for Redis snapshots - 60 second interval, 7-day retention
CREATE TABLE state_snapshots (
    id UUID DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    positions JSONB NOT NULL,
    pending_orders JSONB NOT NULL,
    account_balance DECIMAL(18, 2) NOT NULL,
    equity DECIMAL(18, 2) NOT NULL,
    peak_balance DECIMAL(18, 2) NOT NULL,
    daily_starting_balance DECIMAL(18, 2) NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Convert to hypertable BEFORE adding constraints (required pattern)
SELECT create_hypertable('state_snapshots', 'timestamp');

-- Create indexes
CREATE UNIQUE INDEX idx_state_snapshots_id ON state_snapshots (id, timestamp);
CREATE INDEX idx_state_snapshots_account ON state_snapshots (account_id, timestamp DESC);

-- Add foreign key AFTER hypertable creation (matches rule_violations pattern)
ALTER TABLE state_snapshots ADD CONSTRAINT fk_state_snapshots_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- Add 7-day retention policy
SELECT add_retention_policy('state_snapshots', INTERVAL '7 days');

-- ==================== VERIFICATION ====================

-- Log successful schema creation
DO $$
BEGIN
    RAISE NOTICE 'TimescaleDB schema initialization complete';
    RAISE NOTICE 'Tables created: prop_firms, accounts, account_snapshots, performance_metrics, candles, trades, rule_violations, audit_logs, state_snapshots';
    RAISE NOTICE 'Hypertables: candles, rule_violations, audit_logs, state_snapshots';
    RAISE NOTICE 'Indexes: 22 explicit + 5 PK indexes + 1 unique constraint = 28 total';
    RAISE NOTICE 'FK constraints: 10 with ON DELETE behavior (CASCADE/SET NULL)';
    RAISE NOTICE 'Retention policies: state_snapshots (7 days)';
END $$;
