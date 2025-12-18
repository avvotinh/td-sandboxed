# Story 1.3: TimescaleDB Schema Initialization

**Epic:** 1 - Foundation & Infrastructure
**Status:** Done
**Created:** 2025-12-18

---

## User Story

As a **developer**,
I want **the database schema initialized with all required tables**,
So that **services can store trading data and audit logs**.

---

## Context

This story populates the `infra/timescaledb/init.sql` file (placeholder created in Story 1.2) with the complete database schema from the architecture specification. The schema supports multi-account trading with prop firm presets, comprehensive audit logging, and time-series market data.

### Prerequisites

- **Story 1.2 Complete:** Docker Compose infrastructure stack running with:
  - `trading-timescaledb` container (TimescaleDB/PostgreSQL 16+)
  - `trading-redis` container
  - `trading-net` Docker network
  - Placeholder `infra/timescaledb/init.sql` file exists

**Previous Story:** [1-2-docker-compose-infrastructure-stack.md](./1-2-docker-compose-infrastructure-stack.md)
**Reference:** [Epic 1 Context](../epic-1-context.md)

---

## Current State

```sql
-- infra/timescaledb/init.sql - CURRENT PLACEHOLDER
-- TimescaleDB Schema Initialization
-- Full schema implemented in Story 1.3
-- This placeholder ensures docker-compose volume mount works

SELECT 'Schema placeholder - see Story 1.3 for full implementation';
```

---

## Acceptance Criteria

### AC1: TimescaleDB Extension Enabled
**Given** TimescaleDB container starts
**When** init.sql executes
**Then** the TimescaleDB extension is enabled
**And** `SELECT default_version FROM pg_available_extensions WHERE name = 'timescaledb'` returns a version

### AC2: All Tables Created
**Given** init.sql completes execution
**When** I query the database
**Then** the following tables exist:
- `prop_firms`
- `accounts`
- `account_snapshots`
- `candles`
- `trades`
- `rule_violations`
- `audit_logs`
- `performance_metrics`

### AC3: Default Prop Firms Populated
**Given** schema is initialized
**When** I query `SELECT * FROM prop_firms`
**Then** I see entries for: `ftmo`, `the5ers`, `wmt`

### AC4: Hypertables Configured
**Given** candles table exists
**When** I check `timescaledb_information.hypertables`
**Then** the following tables are hypertables:
- `candles`
- `rule_violations`
- `audit_logs`

### AC5: Indexes Created
**Given** schema is initialized
**When** I list indexes on tables
**Then** all indexes from architecture spec are present

---

## Tasks

### Task 1: Enable TimescaleDB Extension
- [x] Add `CREATE EXTENSION IF NOT EXISTS timescaledb;` at start of init.sql
- [x] Verify extension loads without error

### Task 2: Create Core Reference Tables
- [x] Create `prop_firms` table with all columns from schema
- [x] Insert default prop firms (ftmo, the5ers, wmt)
- [x] Create `accounts` table with all columns and indexes
- [x] Add foreign key constraint from accounts to prop_firms

### Task 3: Create Account State Tables
- [x] Create `account_snapshots` table for daily state tracking
- [x] Add unique constraint on (account_id, snapshot_date)
- [x] Create `performance_metrics` table with composite primary key

### Task 4: Create Time-Series Tables (Hypertables)
- [x] Create `candles` table for OHLCV market data
- [x] Convert candles to hypertable with `create_hypertable('candles', 'time')`
- [x] Create unique index on (symbol, timeframe, time)
- [x] Create `rule_violations` table with timestamp column
- [x] Convert rule_violations to hypertable
- [x] Create `audit_logs` table with timestamp column
- [x] Convert audit_logs to hypertable

### Task 5: Create Trade Tables
- [x] Create `trades` table with all columns from schema
- [x] Add foreign key to accounts
- [x] Create indexes for account_id, symbol, status, mt5_ticket

### Task 6: Verify Schema Installation
- [x] Test schema by recreating container: `docker compose down -v && docker compose up -d`
- [x] Verify all tables exist via `\dt` in psql
- [x] Verify hypertables via `SELECT * FROM timescaledb_information.hypertables`
- [x] Verify prop_firms data via `SELECT * FROM prop_firms`

---

## Technical Specifications

### Schema Overview

| Table | Purpose | Type |
|-------|---------|------|
| `prop_firms` | Prop firm presets (FTMO, The5ers, WMT) | Reference |
| `accounts` | Trading account configurations | Reference |
| `account_snapshots` | Daily balance/drawdown tracking | State |
| `performance_metrics` | Daily strategy performance | State |
| `candles` | OHLCV market data | Hypertable |
| `trades` | Trade lifecycle records | Transaction |
| `rule_violations` | Compliance breach records | Hypertable |
| `audit_logs` | System event audit trail | Hypertable |

### Complete init.sql Schema

The schema below extends architecture.md with additional columns for production use (website, description, is_active on prop_firms; leverage, currency on accounts). Implement EXACTLY as specified.

```sql
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
    prop_firm_id VARCHAR(50) REFERENCES prop_firms(id),
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
    account_id VARCHAR(50) REFERENCES accounts(id) NOT NULL,
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
    account_id VARCHAR(50) REFERENCES accounts(id) NOT NULL,
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
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) REFERENCES accounts(id) NOT NULL,
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
CREATE TABLE rule_violations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) REFERENCES accounts(id) NOT NULL,
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
CREATE INDEX idx_violations_account ON rule_violations (account_id, timestamp DESC);
CREATE INDEX idx_violations_rule ON rule_violations (rule_type, timestamp DESC);

-- Audit Logs (per account) - Hypertable
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL,
    account_id VARCHAR(50) REFERENCES accounts(id),
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
CREATE INDEX idx_audit_account ON audit_logs (account_id, timestamp DESC);
CREATE INDEX idx_audit_event ON audit_logs (event_type, timestamp DESC);
CREATE INDEX idx_audit_level ON audit_logs (level, timestamp DESC) WHERE level IN ('WARNING', 'ERROR');

-- ==================== VERIFICATION ====================

-- Log successful schema creation
DO $$
BEGIN
    RAISE NOTICE 'TimescaleDB schema initialization complete';
    RAISE NOTICE 'Tables created: prop_firms, accounts, account_snapshots, performance_metrics, candles, trades, rule_violations, audit_logs';
    RAISE NOTICE 'Hypertables: candles, rule_violations, audit_logs';
END $$;
```

### TimescaleDB Best Practices (from Context7 Research)

**Hypertable Creation:**
- Use `TIMESTAMPTZ` for time columns (not `TIMESTAMP`)
- Call `create_hypertable()` AFTER creating the base table
- Hypertables automatically partition data by time for efficient queries

**Index Strategy:**
- Create indexes AFTER hypertable conversion
- Use `time DESC` for most recent data queries
- Partial indexes (e.g., `WHERE status = 'open'`) for filtered queries

**Important Notes:**
- TimescaleDB 2.x+ uses `create_hypertable('table', 'time_column')`
- Default chunk interval is 7 days (appropriate for this use case)
- UUID primary keys with `gen_random_uuid()` are PostgreSQL 13+ native

---

## Architecture Compliance

Schema implements architecture.md Data Architecture section with enhancements:
- **TimescaleDB extension** enabled as first statement
- **Hypertables:** candles, rule_violations, audit_logs (time-series optimized)
- **Multi-account:** account_id FK on all transaction tables
- **PRD compliance:** NFR11 (persistence), NFR28 (TimescaleDB), FR42-45 (audit), FR20-25 (trades)

---

## Previous Story Intelligence

### From Story 1.2 (Completed)

**Key Learnings:**
- Docker infrastructure uses `trading-*` naming convention
- Placeholder init.sql exists at `infra/timescaledb/init.sql`
- Volume mount uses SELinux `:z` suffix: `../timescaledb/init.sql:/docker-entrypoint-initdb.d/init.sql:z`
- PostgreSQL credentials: `POSTGRES_DB=trading`, `POSTGRES_USER=trading`
- Health check: `pg_isready -U trading -d trading`

**Files Modified in 1.2:**
- `infra/docker/docker-compose.yml` - Container naming, network, volumes
- `infra/timescaledb/init.sql` - Placeholder (to be replaced in this story)
- `configs/dev/.env` - Database credentials

**Testing Pattern Established:**
```bash
# Set password
export POSTGRES_PASSWORD=devpassword

# Start infrastructure
docker compose -f infra/docker/docker-compose.yml up -d

# Verify
docker exec trading-timescaledb pg_isready -U trading -d trading
```

---

## Dev Agent Guardrails

### MUST DO:

1. **Replace placeholder init.sql** with complete schema from Technical Specifications section
2. **Enable TimescaleDB extension** as first statement
3. **Create tables in dependency order:**
   - prop_firms (no dependencies)
   - accounts (depends on prop_firms)
   - account_snapshots, performance_metrics (depends on accounts)
   - trades (depends on accounts)
   - candles (no account dependency - shared market data)
   - rule_violations, audit_logs (depends on accounts, optional FK to trades)
4. **Convert time-series tables to hypertables** using `create_hypertable()` AFTER table creation
5. **Create indexes AFTER hypertable conversion**
6. **Test schema by recreating container** (`docker compose down -v && docker compose up -d`)

### DO NOT:

1. **Modify docker-compose.yml** - Infrastructure is complete from Story 1.2
2. **Skip hypertable conversion** - Required for time-series performance
3. **Use TIMESTAMP instead of TIMESTAMPTZ** - Always use timezone-aware timestamps
4. **Create indexes before hypertable conversion** - Will cause errors
5. **Hardcode passwords in init.sql** - Passwords come from environment variables
6. **Add application logic** - This is pure schema definition
7. **Modify hypertable chunk intervals** - Default 7 days is optimal for MVP; custom intervals require performance analysis

### Common Pitfalls:

1. **Foreign key order matters** - Create parent tables before child tables
2. **Hypertable primary keys** - Must include the time partitioning column or use UUID
3. **SELinux volume mounts** - Keep `:z` suffix on Fedora/RHEL systems
4. **Container recreation needed** - init.sql only runs on fresh database creation

---

## Testing Verification

### Manual Test Steps

```bash
# 0. Set environment variable (required)
export POSTGRES_PASSWORD=devpassword

# 1. Recreate database to run new init.sql
docker compose -f infra/docker/docker-compose.yml down -v
docker compose -f infra/docker/docker-compose.yml up -d

# 2. Wait for healthy status
docker inspect trading-timescaledb --format='{{.State.Health.Status}}'
# Expected: healthy (may take 10-30 seconds)

# 3. Connect to database
docker exec -it trading-timescaledb psql -U trading -d trading

# 4. Verify TimescaleDB extension
SELECT default_version FROM pg_available_extensions WHERE name = 'timescaledb';
-- Expected: Returns version (e.g., 2.x.x)

# 5. List all tables
\dt
-- Expected: 8 tables (prop_firms, accounts, account_snapshots, etc.)

# 6. Verify hypertables
SELECT hypertable_name FROM timescaledb_information.hypertables;
-- Expected: candles, rule_violations, audit_logs

# 7. Verify prop_firms data
SELECT id, name, rules_preset FROM prop_firms;
-- Expected: ftmo, the5ers, wmt

# 8. Exit psql
\q
```

### Verification Queries

```sql
-- Check all tables exist
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;

-- Check hypertables are configured
SELECT hypertable_name, num_dimensions, num_chunks
FROM timescaledb_information.hypertables;

-- Check indexes on trades table
SELECT indexname FROM pg_indexes WHERE tablename = 'trades';

-- Verify foreign key constraints
SELECT conname, conrelid::regclass, confrelid::regclass
FROM pg_constraint
WHERE contype = 'f';
```

---

## Dependencies

- **Prerequisites:** Story 1.2 (Docker Compose Infrastructure) - DONE
- **Blocks:**
  - Story 1.4 (Environment Config) - needs database working
  - Story 2.1+ (Account Management) - needs accounts table
  - Story 4.x (Rule Engine) - needs rule_violations table
  - Story 7.x (Audit Logging) - needs audit_logs table

---

## Definition of Done

- [x] TimescaleDB extension enabled in init.sql
- [x] All 8 tables created with correct schema
- [x] Hypertables configured for: candles, rule_violations, audit_logs
- [x] Default prop_firms data inserted (ftmo, the5ers, wmt)
- [x] All indexes created per architecture spec
- [x] Schema tested by recreating container
- [x] All verification queries pass
- [x] Story status updated to `review` in sprint-status.yaml

---

## File List

**Files to Modify:**
- `infra/timescaledb/init.sql` - Replace placeholder with complete schema

**Files NOT to Modify:**
- `infra/docker/docker-compose.yml` - Complete from Story 1.2
- `configs/dev/.env` - Complete from Story 1.2
- Any service files - Schema only

---

## References

- [Architecture - Data Architecture Section](../architecture.md#data-architecture)
- [Schema Design Draft](../schema-design-draft.md)
- [Epic 1 Context](../epic-1-context.md)
- [Story 1.2 - Docker Infrastructure](./1-2-docker-compose-infrastructure-stack.md)
- [TimescaleDB Documentation (Context7)](https://github.com/timescale/docs)

---

## Dev Agent Record

### Context Reference

- Epic 1 Context: `docs/epic-1-context.md`
- Architecture: `docs/architecture.md` (Data Architecture section)
- Schema Design: `docs/schema-design-draft.md`
- Previous Story: `docs/sprint-artifacts/1-2-docker-compose-infrastructure-stack.md`

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Initial schema attempt failed with `Permission denied` on init.sql due to SELinux file context (resolved by file permission update)
- Second attempt failed with `cannot create a unique index without the column "timestamp"` for hypertables with UUID primary key
- Resolution: Removed PRIMARY KEY constraint from rule_violations and audit_logs, added composite unique index on (id, timestamp), and moved foreign key constraints to after hypertable creation

### Completion Notes List

- Implemented complete TimescaleDB schema with 8 tables as specified in architecture
- Enabled TimescaleDB extension (v2.23.0)
- Created hypertables for time-series tables (candles, rule_violations, audit_logs) with proper composite indexes
- Fixed TimescaleDB hypertable compatibility issue: tables with UUID cannot have PRIMARY KEY when converted to hypertable - used unique index on (id, timestamp) instead
- All 26 indexes created including primary keys, foreign key indexes, and query optimization indexes (20 explicit + 5 PK + 1 unique constraint)
- Inserted default prop firm presets (ftmo, the5ers, wmt)
- Verified schema installation via container recreation and SQL verification queries

### Code Review Fixes Applied (2025-12-18)

- **H1 Fixed:** Renamed `trades.id` to `trades.trade_id` per architecture.md specification
- **H2 Fixed:** Renamed `audit_logs.id` to `audit_logs.log_id` per architecture.md specification
- **M2 Fixed:** Added ON DELETE behavior to all 9 foreign key constraints:
  - CASCADE: account_snapshots, performance_metrics, trades, rule_violations (account_id)
  - SET NULL: accounts.prop_firm_id, audit_logs.account_id, rule_violations.trade_id, audit_logs.trade_id
- **M3 Fixed:** Added FK constraints for trade_id columns in rule_violations and audit_logs
- **M4 Fixed:** Added missing idx_audit_rule index from architecture spec

### File List

- `infra/timescaledb/init.sql` - Modified (complete 251-line schema with code review fixes)

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-18 | Story created with comprehensive developer context by create-story workflow |
| 2025-12-18 | **Validation improvements applied:** Added CHECK constraints for data integrity (accounts, trades, rule_violations, audit_logs); Added schema overview table; Documented schema enhancements vs architecture.md; Added anti-pattern warning for chunk intervals; Added future retention policy note; Consolidated Architecture Compliance section |
| 2025-12-18 | **Implementation completed:** Full TimescaleDB schema implemented with 8 tables, 3 hypertables, 26 indexes; Fixed hypertable UUID primary key compatibility; All acceptance criteria verified |
| 2025-12-18 | **Code Review fixes applied:** Renamed trades.id→trade_id, audit_logs.id→log_id per architecture; Added ON DELETE behavior to all FKs; Added trade_id FK constraints; Added idx_audit_rule index |

---

## Notes

- This story focuses ONLY on database schema creation
- No application code or service changes
- Schema matches architecture.md and schema-design-draft.md exactly
- Container must be recreated (`down -v`) to run updated init.sql
- Hypertable chunk interval uses TimescaleDB defaults (7 days)
- **Future Enhancement:** Consider adding `add_retention_policy()` for automatic data aging in production
