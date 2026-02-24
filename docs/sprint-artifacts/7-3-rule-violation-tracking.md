# Story 7.3: Rule Violation Tracking

Status: Done

## Story

As a **trader**,
I want **rule violations tracked separately with details**,
So that **I can analyze what caused blocked trades**.

## Acceptance Criteria

1. **Given** a rule blocks a trade
   **When** the violation is recorded
   **Then** an entry is created in `rule_violations` hypertable:
   ```sql
   INSERT INTO rule_violations (
     id, account_id, timestamp, rule_type, rule_name,
     severity, current_value, threshold_value, threshold_percent,
     action_taken, trade_id, order_blocked, message, context
   ) VALUES (
     'uuid', 'ftmo-gold-001', '2025-12-03T14:32:15Z',
     'daily_loss_limit', 'FTMO Daily Loss 5%',
     'FATAL', 4.8, 5.0, 96.0,
     'blocked', NULL, TRUE,
     'Trade blocked: daily loss 4.80% exceeds 96% of 5.00% limit',
     '{"signal": "BUY", "symbol": "XAUUSD", "size": 0.1, "strategy": "ma_crossover"}'
   );
   ```

2. **Given** I query violations for an account
   **When** I run:
   ```sql
   SELECT * FROM rule_violations
   WHERE account_id = 'ftmo-gold-001'
     AND timestamp > NOW() - INTERVAL '7 days'
   ORDER BY timestamp DESC;
   ```
   **Then** I see all violations with full context

3. **Given** I want violation summary
   **When** I query:
   ```sql
   SELECT rule_type, COUNT(*) as violations, MAX(current_value) as peak
   FROM rule_violations
   WHERE account_id = 'ftmo-gold-001'
   GROUP BY rule_type;
   ```
   **Then** I see aggregated violation statistics

## Tasks / Subtasks

**Task Dependency Order:**
```
Task 1 (RuleViolation dataclass) → Task 2 (RuleViolationModel ORM) → Task 3 (ViolationDBWriter) → Task 4 (ViolationService facade) → Task 5 (Integration with OrderValidator) → Task 6 (DB Migration: retention + aggregate + compression) → Task 7 (Tests)
```

- [x] Task 1: Create RuleViolation Dataclass (AC: #1)
  - [x] 1.1: Create `src/rules/violation.py` with `RuleViolation` dataclass
  - [x] 1.2: Fields must match ALL 17 columns in init.sql `rule_violations` table (see Dev Notes): id, account_id, timestamp, rule_type, rule_name, severity, current_value, threshold_value, threshold_percent, action_taken, trade_id, order_blocked, message, context, acknowledged, acknowledged_at, created_at
  - [x] 1.3: Add `from_rule_result(rule, result, account_id, ...)` factory classmethod to convert existing `BaseRule` + `RuleResult` into a `RuleViolation`
  - [x] 1.4: Implement severity mapping logic:
    - `RuleAction.BLOCK` → `severity="FATAL"`, `action_taken="blocked"`, `order_blocked=True`
    - `RuleAction.WARN` at >=90% → `severity="CRITICAL"`, `action_taken="warned"`, `order_blocked=False`
    - `RuleAction.WARN` at >=80% → `severity="WARNING"`, `action_taken="warned"`, `order_blocked=False`
    - `RuleAction.WARN` at <80% → `severity="INFO"`, `action_taken="warned"`, `order_blocked=False`
  - [x] 1.5: Calculate `threshold_percent` as `(current_value / threshold_value) * 100` when both values are non-None
  - [x] 1.6: Add `to_dict()` method for serialization

- [x] Task 2: Create RuleViolationModel SQLAlchemy ORM (AC: #1, #2, #3)
  - [x] 2.1: Create `RuleViolationModel` class in `src/rules/violation_db_writer.py` (or `src/rules/violation.py` alongside dataclass)
  - [x] 2.2: Map ALL 17 columns from init.sql exactly (see Architecture Compliance section)
  - [x] 2.3: Use `Column(UUID(as_uuid=True), primary_key=True)` for `id` - same hypertable pattern as AuditLogModel
  - [x] 2.4: Add `from_violation(violation: RuleViolation)` factory classmethod
  - [x] 2.5: Use `Numeric(18, 4)` for `current_value`, `threshold_value` and `Numeric(8, 4)` for `threshold_percent`
  - [x] 2.6: CHECK constraints enforced by DB (`severity`, `action_taken`) - validate in Python too for early error detection

- [x] Task 3: Create ViolationDBWriter with Batch Buffer Pattern (AC: #1)
  - [x] 3.1: Create `src/rules/violation_db_writer.py` following exact `AuditDBWriter` pattern
  - [x] 3.2: Implement async batch buffer with configurable `batch_size` (default: 100) and `flush_interval` (default: 60s) - same as AuditDBWriter for consistency
  - [x] 3.3: Add `start()` method to initialize flush timer loop
  - [x] 3.4: Add `stop()` method for graceful shutdown with final buffer flush
  - [x] 3.5: Add `add_violation(violation: RuleViolation)` method that converts to ORM model and buffers
  - [x] 3.6: Implement `_flush_buffer()` with atomic buffer swap under `asyncio.Lock`, re-add on failure
  - [x] 3.7: Use same `create_async_engine` + `async_sessionmaker` pattern from AuditDBWriter

- [x] Task 4: Create ViolationService Facade (AC: #1, #2)
  - [x] 4.1: Create `src/rules/violation_service.py` with `ViolationService` class
  - [x] 4.2: Constructor accepts `ViolationDBWriter` dependency
  - [x] 4.3: Implement `record_violation(rule, result, account_id, order_id=None, trade_id=None, signal_context=None)` - creates `RuleViolation` and queues to writer
  - [x] 4.4: Implement `record_block(rule, result, account_id, order_id=None, signal_context=None)` convenience method for BLOCK violations
  - [x] 4.5: Implement `record_warning(rule, result, account_id, trade_id=None, signal_context=None)` convenience method for WARN violations
  - [x] 4.6: Fire-and-forget pattern: all methods are `async` but callers use `asyncio.create_task()` with `audit_task_done_callback`

- [x] Task 5: Integrate ViolationService with OrderValidator Flow (AC: #1, #2)
  - [x] 5.1: Inject `ViolationService` into `OrderValidator` constructor as optional dependency (alongside existing `audit_registry: AuditLoggerRegistry | None`)
  - [x] 5.2: In `OrderValidator._log_rule_results_to_audit()` - after the existing `log_all_fire_and_forget()` call, for BLOCK results: call `violation_service.record_block()` via `asyncio.create_task()` with `audit_task_done_callback`
  - [x] 5.3: In `OrderValidator._log_rule_results_to_audit()` - for WARN results: call `violation_service.record_warning()` via `asyncio.create_task()` with `audit_task_done_callback`
  - [x] 5.4: Pass `rule`, `result`, `order.account_id` to violation service. The `RuleViolation.from_rule_result()` factory extracts `rule.rule_type`, `rule.name`, `result.current_value`, `result.threshold_value`, `result.message`
  - [x] 5.5: Build signal context from existing `audit_context` dict already available in `_log_rule_results_to_audit()`: `{"signal": order.action, "symbol": order.symbol, "size": order.volume, "price": order.price}`
  - [x] 5.6: For WARN results, `RuleViolation.from_rule_result()` already calculates `threshold_percent` from `result.current_value / result.threshold_value * 100`
  - [x] 5.7: Wire up ViolationDBWriter + ViolationService in the caller that creates `OrderValidator` (pass alongside `AuditLoggerRegistry`). **Note:** `AuditLogger` is per-account Redis-only; `AuditService` (in `engine.py`) wraps `AuditDBWriter` for TimescaleDB. ViolationService follows the AuditService pattern as a separate facade.

- [x] Task 6: DB Migration - Retention + Continuous Aggregate + Compression (AC: #3)
  - [x] 6.1: Create migration `infra/timescaledb/migrations/008_violations_retention_and_aggregate.sql`
  - [x] 6.2: Add retention policy FIRST: `SELECT add_retention_policy('rule_violations', INTERVAL '90 days');`
  - [x] 6.3: Create continuous aggregate for daily violation summaries:
    ```sql
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
    ```
  - [x] 6.4: Add refresh policy: `SELECT add_continuous_aggregate_policy('violation_daily_summary', '3 days', '1 hour', '1 hour');`
  - [x] 6.5: Add aggregate retention: `SELECT add_retention_policy('violation_daily_summary', INTERVAL '365 days');`
  - [x] 6.6: Enable compression: `ALTER TABLE rule_violations SET (timescaledb.compress, timescaledb.compress_segmentby = 'account_id', timescaledb.compress_orderby = 'timestamp DESC');`
  - [x] 6.7: Add compression policy: `SELECT add_compression_policy('rule_violations', INTERVAL '7 days');`

- [x] Task 7: Add Unit and Integration Tests (AC: #1-3)
  - [x] 7.1: Unit test: `RuleViolation.from_rule_result()` correctly maps BLOCK → FATAL severity, order_blocked=True
  - [x] 7.2: Unit test: `RuleViolation.from_rule_result()` correctly maps WARN → severity based on threshold %
  - [x] 7.3: Unit test: `threshold_percent` calculated correctly from current_value/threshold_value
  - [x] 7.4: Unit test: `RuleViolationModel.from_violation()` maps all 15 fields correctly with DECIMAL precision
  - [x] 7.5: Unit test: `ViolationDBWriter.add_violation()` adds to buffer
  - [x] 7.6: Unit test: `ViolationDBWriter._flush_buffer()` persists entries via session.add_all()
  - [x] 7.7: Unit test: `ViolationService.record_block()` creates correct RuleViolation
  - [x] 7.8: Unit test: `ViolationService.record_warning()` creates correct RuleViolation for each warning threshold
  - [x] 7.9: Integration test: OrderValidator BLOCK → ViolationService.record_block() → violation in buffer
  - [x] 7.10: Integration test: OrderValidator WARN → ViolationService.record_warning() → warning violation in buffer
  - [x] 7.11: Integration test: Multiple violations for same account create separate entries
  - [x] 7.12: Integration test: Verify backward compatibility - existing rule_check ALLOW paths unaffected

## Dev Notes

### CRITICAL: Read Before Implementation

**These items MUST be completed or the feature will not work:**

1. **init.sql is SOURCE OF TRUTH**: The `rule_violations` table in `infra/timescaledb/init.sql` has **17 columns** (id, account_id, timestamp, rule_type, rule_name, severity, current_value, threshold_value, threshold_percent, action_taken, trade_id, order_blocked, message, context, acknowledged, acknowledged_at, created_at). The architecture.md schema is STALE (only shows 9 columns). Always reference init.sql for column names, types, and constraints.

2. **DECIMAL Precision**: ALL numeric fields (`current_value`, `threshold_value`, `threshold_percent`) MUST use `Decimal` type in Python, NOT float. Convert via `Decimal(str(value))` to prevent floating-point errors.

3. **Severity CHECK Constraint**: The DB enforces `severity IN ('INFO', 'WARNING', 'CRITICAL', 'FATAL')`. Any other value will cause an INSERT error. Validate in Python before queueing.

4. **action_taken CHECK Constraint**: The DB enforces `action_taken IN ('blocked', 'warned', 'notified', 'logged')`. Validate in Python.

5. **account_id is NOT NULL**: Unlike `audit_logs` where `account_id` can be NULL (system events), `rule_violations.account_id` is `NOT NULL`. Every violation MUST have an account.

6. **Hypertable Composite Key**: The `rule_violations` table uses `CREATE UNIQUE INDEX idx_violations_id ON rule_violations (id, timestamp)` instead of a traditional PK. The ORM uses `id` as `primary_key=True` for SQLAlchemy's identity map, but DB uniqueness is via the composite index.

7. **FK Constraints**: `account_id` FK to `accounts(id)` with `ON DELETE CASCADE`. `trade_id` FK to `trades(trade_id)` with `ON DELETE SET NULL`. For BLOCK violations, `trade_id` = NULL (no trade created). For WARN violations where trade proceeds, `trade_id` can be set after trade is created.

8. **Fire-and-Forget**: Violation recording MUST NOT block the rule validation flow. Use `asyncio.create_task()` with `audit_task_done_callback` (same callback as audit logging).

9. **Existing RuleResult Fields**: The `RuleResult` dataclass (`src/rules/base_rule.py`) already provides: `action`, `message`, `metadata`, `current_value`, `threshold_value`. The `BaseRule` provides: `rule_type`, `name`, `priority`, `get_threshold()`, `get_warning_thresholds()`.

10. **Warning Threshold Detection**: Warning thresholds come from `rule.get_warning_thresholds()` which returns percentages like `[0.7, 0.8, 0.9]`. When `result.action == WARN`, the `result.metadata` may contain `threshold_pct` indicating which threshold triggered. Calculate `threshold_percent = (current_value / threshold_value) * 100` for storage.

11. **OrderValidator is the Integration Point**: The `OrderValidator._log_rule_results_to_audit()` (at `src/execution/order_validator.py:440-466`) already iterates ALL `(rule, result)` tuples and calls `AuditLoggerRegistry.log_all_fire_and_forget()` for each. This is the ideal place to also call `ViolationService` for BLOCK and WARN results. **Note:** `AuditLogger` is a per-account Redis-only writer with constructor `(redis_client, account_id)` — it does NOT accept `db_writer` or `violation_service`. The method is `log_rule_check()`, NOT `log_validation()`.

12. **Don't Duplicate Redis Storage**: The existing `RedisStateManager.record_risk_violation()` writes a simple JSON to `risk:{account_id}:violations` (Redis list, TTL 90d). This story adds proper TimescaleDB tracking. The Redis path remains for quick lookups; TimescaleDB is the long-term store. Do NOT remove the Redis path.

13. **acknowledged Fields**: The `acknowledged` (BOOLEAN) and `acknowledged_at` (TIMESTAMPTZ) columns exist in init.sql for future use. Default `acknowledged=False`, `acknowledged_at=None`. Do NOT implement acknowledgment workflow in this story - just map the columns.

---

### Quick Reference: What to Create/Modify

| Component | What to Do | Location |
|-----------|------------|----------|
| **RuleViolation** | Create dataclass with from_rule_result() | `src/rules/violation.py` (NEW) |
| **RuleViolationModel** | Create ORM model mapping all 15 columns | `src/rules/violation_db_writer.py` (NEW) |
| **ViolationDBWriter** | Create batch writer (follow AuditDBWriter pattern) | `src/rules/violation_db_writer.py` (NEW) |
| **ViolationService** | Create facade with record_block(), record_warning() | `src/rules/violation_service.py` (NEW) |
| **OrderValidator** | Add violation_service injection, call on BLOCK/WARN in `_log_rule_results_to_audit()` | `src/execution/order_validator.py` (MODIFY) |
| **Engine/Startup** | Wire up ViolationDBWriter + ViolationService, pass to OrderValidator | Wherever OrderValidator is created (MODIFY) |
| **Migration** | Retention → aggregate → compression | `infra/timescaledb/migrations/008_violations_retention_and_aggregate.sql` (NEW) |
| **Tests** | Unit + integration | `tests/unit/test_violation_service.py` (NEW), `tests/integration/test_violation_tracking.py` (NEW) |

---

### Architecture Compliance

**Service:** `services/trading-engine/` (Python 3.11+)
**Database:** TimescaleDB (PostgreSQL 16+)
**ORM:** SQLAlchemy 2.0+ with async support (asyncpg)

**CRITICAL CONSTRAINTS from init.sql (SOURCE OF TRUTH):**

From [Source: infra/timescaledb/init.sql#rule_violations]:
```sql
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

ALTER TABLE rule_violations ADD CONSTRAINT fk_violations_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE rule_violations ADD CONSTRAINT fk_violations_trade
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id) ON DELETE SET NULL;
```

**STALE ARCHITECTURE DOC WARNING:** The `docs/architecture.md` lines 1247-1263 show a SIMPLIFIED schema for `rule_violations` missing: `severity`, `threshold_percent`, `trade_id`, `order_blocked`, `message`, `acknowledged`, `acknowledged_at`. Also incorrectly shows `order_id UUID` instead of `trade_id UUID`. The init.sql is the ACTUAL deployed schema.

**Communication Patterns:**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Outbound | PostgreSQL | 5432 | Violation records (per account) |

---

### Library/Framework Requirements

**SQLAlchemy 2.0+ Async Patterns (from Context7 /websites/sqlalchemy_en_21):**

```python
# Bulk INSERT with async session
async with async_session() as session:
    async with session.begin():
        session.add_all([
            RuleViolationModel(...),
            RuleViolationModel(...),
        ])
# Commits automatically on context exit
```

**TimescaleDB Hypertable Best Practices (from Context7 /timescale/docs):**
- Batch inserts are more efficient than row-by-row
- `segmentby = 'account_id'` ensures efficient compressed chunk queries by account
- `orderby = 'timestamp DESC'` optimizes time-range queries
- Retention must be set BEFORE compression to avoid decompression overhead

---

### Context from Previous Stories

**From Story 4.8 (Rule Check Audit Logging) - Key Patterns Established:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| Batch DB Writer | `AuditDBWriter` with buffer, timer flush | `src/rules/audit_db_writer.py` |
| Fire-and-forget | `asyncio.create_task()` + `audit_task_done_callback` | `src/rules/audit_logger.py:280-300` |
| ORM Model | `AuditLogModel` with `from_audit_entry()` factory | `src/rules/audit_db_writer.py:37-103` |
| Async Session | `async_sessionmaker` + `create_async_engine` | `src/rules/audit_db_writer.py:147-157` |
| Rule Result | `RuleResult` dataclass (action, message, metadata, current_value, threshold_value) | `src/rules/base_rule.py` |
| Audit Registry | `AuditLoggerRegistry` - per-account logger management, `log_all_fire_and_forget()` | `src/rules/audit_registry.py` |
| Order Validator | `OrderValidator._log_rule_results_to_audit()` - iterates all (rule, result) tuples | `src/execution/order_validator.py:440-466` |

**From Story 7.1 (Trade Execution Audit Logging) - Writer Patterns:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| TradeDBWriter | Batch write of trade records to TimescaleDB | `src/orders/trade_db_writer.py` |
| Signal mapping | `_signals_by_order` dict for concurrency-safe signal storage | `src/orders/execution_service.py` |
| Done callback | `audit_task_done_callback` for fire-and-forget error handling | `src/rules/audit_logger.py:252-271` |

**From Story 7.2 (Comprehensive Audit Log Table) - Service Facade Patterns:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| AuditService | Facade wrapping AuditDBWriter with typed convenience methods | `src/audit/audit_service.py` |
| Event logging | `log_trade_executed()`, `log_position_closed()`, `log_system_event()` | `src/audit/audit_service.py` |
| Engine wiring | Injected into Engine + OrderExecutionService | `src/engine.py`, `src/orders/execution_service.py` |

**Existing Rule Engine Flow (from `src/rules/engine.py`):**

```python
class RuleEngine:
    def validate(self, context: dict[str, Any]) -> RuleEngineResult:
        # Evaluates all rules in priority order
        # Returns: action (ALLOW/WARN/BLOCK), blocked_by, blocking_reason,
        #          warnings (list), all_results (list of (rule, result) tuples)
```

**Existing AuditLogger (per-account Redis logger, from `src/rules/audit_logger.py`):**

```python
# AuditLogger.__init__(redis_client: Redis, account_id: str) - NO db_writer param
# AuditLogger.log_rule_check(rule, result, order_id, context) - writes to Redis only
# _create_entry() maps:
# - action == "block" → event_type = TRADE_BLOCKED, level = WARNING
# - action == "warn" → event_type = WARNING_TRIGGERED, level = WARNING
# - action == "allow" → event_type = RULE_CHECK, level = INFO
# Context includes: rule_type, blocking_reason
```

**Existing OrderValidator (actual integration point, from `src/execution/order_validator.py`):**

```python
# OrderValidator.__init__(rule_engine, redis_client, audit_registry=None)
# validate_order() calls RuleEngine.validate() then _log_rule_results_to_audit()
# _log_rule_results_to_audit() iterates ALL (rule, result) tuples and calls
#   audit_registry.log_all_fire_and_forget() for each one
# This is where ViolationService calls should be added for BLOCK/WARN results
```

**Existing AuditLoggerRegistry (from `src/rules/audit_registry.py`):**

```python
# AuditLoggerRegistry(redis_client) - manages per-account AuditLogger instances
# log_all_fire_and_forget(account_id, rule, result, order_id, context)
#   → creates asyncio.Task with audit_task_done_callback
```

**Existing Redis Violation Storage (from `src/state/redis_state.py:251-278`):**

```python
async def record_risk_violation(self, account_id, rule_type, current_value, limit_value):
    # Key: risk:{account_id}:violations
    # Format: {"rule_type", "current_value", "limit_value", "timestamp"}
    # TTL: 90 days, Max entries: 1000
```

**Existing RuleResult Dataclass (from `src/rules/base_rule.py`):**

```python
@dataclass
class RuleResult:
    action: RuleAction = RuleAction.ALLOW  # ALLOW, WARN, or BLOCK
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    current_value: float | None = None
    threshold_value: float | None = None
```

---

### Latest Technical Documentation (Context7 Research)

**TimescaleDB Hypertable Management (from Context7 /timescale/docs):**

```sql
-- Modern syntax for hypertable creation (existing schema uses legacy style)
SELECT create_hypertable('rule_violations', by_range('timestamp'));

-- Idempotent creation (useful for migrations)
SELECT create_hypertable('rule_violations', by_range('timestamp'), if_not_exists => TRUE);
```

**TimescaleDB Continuous Aggregates (from Context7 /timescale/docs):**

```sql
-- Daily violation summaries with FILTER for severity breakdown
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

-- Refresh policy: 3-day lookback, 1-hour lag, hourly refresh
SELECT add_continuous_aggregate_policy('violation_daily_summary',
  start_offset => INTERVAL '3 days',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour');
```

**TimescaleDB Retention + Compression (from Context7 /timescale/docs):**

```sql
-- ORDER MATTERS: retention BEFORE compression (avoids decompression overhead)

-- 1. Retention: drop raw data older than 90 days
SELECT add_retention_policy('rule_violations', INTERVAL '90 days');

-- 2. Compression: segmentby account_id for efficient per-account queries
ALTER TABLE rule_violations SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'account_id',
  timescaledb.compress_orderby = 'timestamp DESC'
);

-- 3. Compress chunks older than 7 days
SELECT add_compression_policy('rule_violations', INTERVAL '7 days');
```

**SQLAlchemy 2.0 Async Bulk Insert (from Context7 /websites/sqlalchemy_en_21):**

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# Engine creation with connection pooling
engine = create_async_engine(
    "postgresql+asyncpg://user:password@localhost:5432/tradingdb",
    echo=False,
    pool_size=5,
    max_overflow=10,
)

# Async session factory
session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Bulk insert pattern
async with session_factory() as session:
    async with session.begin():
        session.add_all(models)
# Transaction commits automatically on exit
```

**Key Constraint:** UNIQUE/PRIMARY KEY indexes on hypertables MUST include the partition column (`timestamp`). The init.sql correctly uses composite unique index `(id, timestamp)` instead of `PRIMARY KEY (id)`.

---

### Implementation Guide

**Step 1: Create RuleViolation Dataclass**

```python
# src/rules/violation.py
"""Rule Violation data model for tracking violations in TimescaleDB."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .base_rule import BaseRule, RuleAction, RuleResult


# Severity mapping from rule action + threshold percentage
SEVERITY_MAP = {
    "block": "FATAL",      # Trade was actually blocked
    "warn_90": "CRITICAL",  # 90%+ of limit reached
    "warn_80": "WARNING",   # 80%+ of limit reached
    "warn_default": "INFO", # Below 80% (e.g., 70% threshold)
}

ACTION_MAP = {
    RuleAction.BLOCK: "blocked",
    RuleAction.WARN: "warned",
    RuleAction.ALLOW: "logged",  # Shouldn't normally occur for violations
}


@dataclass
class RuleViolation:
    """Represents a rule violation for persistence to TimescaleDB."""

    account_id: str                              # NOT NULL - always required
    timestamp: datetime
    rule_type: str                               # e.g., "daily_loss_limit"
    rule_name: str                               # e.g., "FTMO Daily Loss 5%"
    severity: str                                # INFO, WARNING, CRITICAL, FATAL
    action_taken: str                            # blocked, warned, notified, logged
    current_value: float | None = None
    threshold_value: float | None = None
    threshold_percent: float | None = None       # (current/threshold) * 100
    trade_id: str | None = None                  # UUID string, FK to trades
    order_blocked: bool = False
    message: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    acknowledged_at: datetime | None = None

    @classmethod
    def from_rule_result(
        cls,
        rule: BaseRule,
        result: RuleResult,
        account_id: str,
        trade_id: str | None = None,
        signal_context: dict[str, Any] | None = None,
    ) -> "RuleViolation":
        """Create a RuleViolation from an existing rule check result.

        Args:
            rule: The rule that triggered the violation
            result: The rule's validation result (BLOCK or WARN)
            account_id: Account that was evaluated
            trade_id: UUID of trade if it proceeded (WARN), None if blocked
            signal_context: Additional context about the signal/order
        """
        is_block = result.action == RuleAction.BLOCK

        # Calculate threshold percentage
        threshold_pct = None
        if result.current_value is not None and result.threshold_value is not None:
            if result.threshold_value != 0:
                threshold_pct = (result.current_value / result.threshold_value) * 100

        # Determine severity
        if is_block:
            severity = "FATAL"
        elif threshold_pct is not None:
            if threshold_pct >= 90:
                severity = "CRITICAL"
            elif threshold_pct >= 80:
                severity = "WARNING"
            else:
                severity = "INFO"
        else:
            severity = "WARNING"  # Default for WARN without threshold data

        # Build context
        ctx = {}
        if signal_context:
            ctx.update(signal_context)
        if result.metadata:
            ctx["rule_metadata"] = result.metadata

        return cls(
            account_id=account_id,
            timestamp=datetime.now(timezone.utc),
            rule_type=rule.rule_type,
            rule_name=rule.name,
            severity=severity,
            action_taken=ACTION_MAP.get(result.action, "logged"),
            current_value=result.current_value,
            threshold_value=result.threshold_value,
            threshold_percent=threshold_pct,
            trade_id=trade_id,
            order_blocked=is_block,
            message=result.message,
            context=ctx,
        )
```

**Step 2: Create RuleViolationModel ORM + ViolationDBWriter**

```python
# src/rules/violation_db_writer.py
"""Rule Violation DB Writer - Batch persistence to TimescaleDB rule_violations hypertable."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Column, DateTime, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .violation import RuleViolation

# Use same Base as AuditLogModel
from .audit_db_writer import Base

logger = logging.getLogger(__name__)


class RuleViolationModel(Base):
    """SQLAlchemy ORM model for rule_violations hypertable."""

    __tablename__ = "rule_violations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    rule_type = Column(String(50), nullable=False)
    rule_name = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False)  # CHECK in DB: INFO/WARNING/CRITICAL/FATAL
    current_value = Column(Numeric(18, 4), nullable=True)
    threshold_value = Column(Numeric(18, 4), nullable=True)
    threshold_percent = Column(Numeric(8, 4), nullable=True)
    action_taken = Column(String(50), nullable=False)  # CHECK in DB: blocked/warned/notified/logged
    trade_id = Column(UUID(as_uuid=True), nullable=True)
    order_blocked = Column(Boolean, default=False)
    message = Column(Text, nullable=True)
    context = Column(JSONB, nullable=True)
    acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_violation(cls, violation: RuleViolation) -> "RuleViolationModel":
        """Convert a RuleViolation dataclass to an ORM model instance.

        Validates severity and action_taken against DB CHECK constraints.
        """
        valid_severities = {"INFO", "WARNING", "CRITICAL", "FATAL"}
        if violation.severity not in valid_severities:
            raise ValueError(
                f"Invalid severity '{violation.severity}'. Must be one of {valid_severities}"
            )

        valid_actions = {"blocked", "warned", "notified", "logged"}
        if violation.action_taken not in valid_actions:
            raise ValueError(
                f"Invalid action_taken '{violation.action_taken}'. Must be one of {valid_actions}"
            )

        return cls(
            account_id=violation.account_id,
            timestamp=violation.timestamp,
            rule_type=violation.rule_type,
            rule_name=violation.rule_name,
            severity=violation.severity,
            current_value=Decimal(str(violation.current_value)) if violation.current_value is not None else None,
            threshold_value=Decimal(str(violation.threshold_value)) if violation.threshold_value is not None else None,
            threshold_percent=Decimal(str(violation.threshold_percent)) if violation.threshold_percent is not None else None,
            action_taken=violation.action_taken,
            trade_id=uuid.UUID(violation.trade_id) if violation.trade_id else None,
            order_blocked=violation.order_blocked,
            message=violation.message,
            context=violation.context or None,
            acknowledged=violation.acknowledged,
            acknowledged_at=violation.acknowledged_at,
        )


class ViolationDBWriter:
    """Batched writer for persisting rule violations to TimescaleDB.

    Follows same pattern as AuditDBWriter for consistency.
    Uses same defaults (batch_size=100, flush_interval=60s).
    """

    def __init__(
        self,
        database_url: str,
        batch_size: int = 100,
        flush_interval: float = 60.0,
    ) -> None:
        self._database_url = database_url
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._buffer: list[RuleViolationModel] = []
        self._buffer_lock = asyncio.Lock()

        self._engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self._flush_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(
            self._flush_timer_loop(),
            name="violation_db_flush_timer",
        )
        logger.info(
            "ViolationDBWriter started (batch=%d, interval=%.1fs)",
            self._batch_size, self._flush_interval,
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush_buffer()
        await self._engine.dispose()
        logger.info("ViolationDBWriter stopped")

    async def add_violation(self, violation: RuleViolation) -> None:
        """Add violation to buffer for batch persistence."""
        model = RuleViolationModel.from_violation(violation)
        should_flush = False
        async with self._buffer_lock:
            self._buffer.append(model)
            should_flush = len(self._buffer) >= self._batch_size
        if should_flush:
            asyncio.create_task(self._flush_buffer())

    async def _flush_timer_loop(self) -> None:
        """Periodically flush buffer to database."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                if self._buffer:
                    await self._flush_buffer()
            except asyncio.CancelledError:
                break

    async def _flush_buffer(self) -> None:
        """Flush buffered violations to TimescaleDB."""
        async with self._buffer_lock:
            if not self._buffer:
                return
            entries_to_flush = self._buffer
            self._buffer = []

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add_all(entries_to_flush)
            logger.debug("Flushed %d violations to TimescaleDB", len(entries_to_flush))
        except Exception:
            logger.exception("Failed to flush %d violations, re-adding to buffer", len(entries_to_flush))
            async with self._buffer_lock:
                self._buffer = entries_to_flush + self._buffer
```

**Step 3: Create ViolationService Facade**

```python
# src/rules/violation_service.py
"""Violation Service - Facade for recording rule violations."""

import logging
from typing import Any

from .base_rule import BaseRule, RuleAction, RuleResult
from .violation import RuleViolation
from .violation_db_writer import ViolationDBWriter

logger = logging.getLogger(__name__)


class ViolationService:
    """Facade for recording rule violations to TimescaleDB.

    Wraps ViolationDBWriter to provide typed convenience methods.
    No try/except internally - errors propagate to caller's done_callback.
    """

    def __init__(self, db_writer: ViolationDBWriter) -> None:
        self._db_writer = db_writer

    async def record_violation(
        self,
        rule: BaseRule,
        result: RuleResult,
        account_id: str,
        trade_id: str | None = None,
        signal_context: dict[str, Any] | None = None,
    ) -> None:
        """Record any type of violation (block or warn)."""
        violation = RuleViolation.from_rule_result(
            rule=rule,
            result=result,
            account_id=account_id,
            trade_id=trade_id,
            signal_context=signal_context,
        )
        await self._db_writer.add_violation(violation)

    async def record_block(
        self,
        rule: BaseRule,
        result: RuleResult,
        account_id: str,
        signal_context: dict[str, Any] | None = None,
    ) -> None:
        """Record a trade BLOCK violation. trade_id is always None (no trade created)."""
        await self.record_violation(
            rule=rule,
            result=result,
            account_id=account_id,
            trade_id=None,  # Blocked trade has no trade record
            signal_context=signal_context,
        )

    async def record_warning(
        self,
        rule: BaseRule,
        result: RuleResult,
        account_id: str,
        trade_id: str | None = None,
        signal_context: dict[str, Any] | None = None,
    ) -> None:
        """Record a trade WARNING violation. trade_id set if trade proceeded."""
        await self.record_violation(
            rule=rule,
            result=result,
            account_id=account_id,
            trade_id=trade_id,
            signal_context=signal_context,
        )
```

**Step 4: Integrate with OrderValidator**

```python
# In src/execution/order_validator.py

# Modify __init__() to accept ViolationService:
from ..rules.violation_service import ViolationService

def __init__(
    self,
    rule_engine: RuleEngine,
    redis_client: Redis,
    audit_registry: AuditLoggerRegistry | None = None,
    violation_service: ViolationService | None = None,  # NEW
) -> None:
    self._rule_engine = rule_engine
    self._redis = redis_client
    self._audit_registry = audit_registry
    self._violation_service = violation_service  # NEW
    self._context_builder = RuleContextBuilder()

# In _log_rule_results_to_audit() - add violation recording after existing audit loop:
def _log_rule_results_to_audit(self, all_results, order, account_state):
    if self._audit_registry is None and self._violation_service is None:
        return

    # Build context for audit entries (existing code)
    audit_context = {
        "signal": order.action.value if hasattr(order.action, "value") else str(order.action),
        "symbol": order.symbol,
        "size": order.volume,
        "price": order.price,
    }

    for rule, result in all_results:
        # Existing: fire-and-forget Redis audit logging
        if self._audit_registry is not None:
            self._audit_registry.log_all_fire_and_forget(
                account_id=order.account_id,
                rule=rule,
                result=result,
                order_id=order.order_id,
                context=audit_context,
            )

        # NEW: fire-and-forget violation recording for BLOCK/WARN
        if self._violation_service is not None:
            if result.action == RuleAction.BLOCK:
                task = asyncio.create_task(
                    self._violation_service.record_block(
                        rule=rule,
                        result=result,
                        account_id=order.account_id,
                        signal_context=audit_context,
                    ),
                    name=f"violation_block_{rule.rule_type}",
                )
                task.add_done_callback(audit_task_done_callback)
            elif result.action == RuleAction.WARN:
                task = asyncio.create_task(
                    self._violation_service.record_warning(
                        rule=rule,
                        result=result,
                        account_id=order.account_id,
                        trade_id=None,  # Not yet known at validation time
                        signal_context=audit_context,
                    ),
                    name=f"violation_warn_{rule.rule_type}",
                )
                task.add_done_callback(audit_task_done_callback)
```

**Step 5: Wire in Engine / Startup Code**

```python
# ViolationService is wired where OrderValidator is created (NOT in engine.py).
# engine.py uses AuditService (facade for AuditDBWriter). ViolationService follows
# the same facade pattern but is injected into OrderValidator, not TradingEngine.
#
# In the code that creates OrderValidator (likely the account/execution startup):

# 1. Create ViolationDBWriter with its own connection pool (isolated from AuditDBWriter)
violation_db_writer = ViolationDBWriter(database_url=timescale_url)
await violation_db_writer.start()

# 2. Create ViolationService facade
violation_service = ViolationService(violation_db_writer)

# 3. Pass to OrderValidator alongside existing AuditLoggerRegistry
order_validator = OrderValidator(
    rule_engine=rule_engine,
    redis_client=redis_client,
    audit_registry=audit_registry,
    violation_service=violation_service,  # NEW
)

# 4. In shutdown:
await violation_db_writer.stop()
```

---

### Project Structure Notes

**File Locations:**
```
services/trading-engine/
├── src/
│   ├── rules/
│   │   ├── violation.py              # CREATE: RuleViolation dataclass
│   │   ├── violation_db_writer.py    # CREATE: RuleViolationModel + ViolationDBWriter
│   │   ├── violation_service.py      # CREATE: ViolationService facade
│   │   ├── audit_logger.py           # READ ONLY: audit_task_done_callback import
│   │   ├── audit_db_writer.py        # READ ONLY: Pattern reference (AuditDBWriter), Base import
│   │   ├── audit_registry.py         # READ ONLY: AuditLoggerRegistry pattern reference
│   │   ├── base_rule.py              # READ ONLY: RuleResult, RuleAction, BaseRule
│   │   └── engine.py                 # READ ONLY: RuleEngine, RuleEngineResult
│   ├── execution/
│   │   └── order_validator.py        # MODIFY: Add violation_service injection + BLOCK/WARN recording
│   └── engine.py                     # READ ONLY (AuditService pattern reference)
├── tests/
│   ├── unit/
│   │   └── test_violation_service.py     # CREATE: Unit tests
│   └── integration/
│       └── test_violation_tracking.py    # CREATE: Integration tests
infra/timescaledb/migrations/
└── 008_violations_retention_and_aggregate.sql  # CREATE: Migration
```

---

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TIMESCALE_URL` | Yes | - | TimescaleDB connection URL |
| `TIMESCALE_POOL_SIZE` | No | 5 | Connection pool size |

**Connection URL Format:**
```
postgresql+asyncpg://user:password@localhost:5432/tradingdb
```

---

### Testing Standards

- Unit tests: `pytest services/trading-engine/tests/unit/test_violation_service.py`
- Integration tests: `pytest services/trading-engine/tests/integration/ -k violation_tracking`
- Run all: `cd services/trading-engine && pytest`
- Use `pytest-asyncio` for async test functions
- Mock `ViolationDBWriter` with `AsyncMock` for unit tests
- Verify CHECK constraints: invalid severity/action_taken raises ValueError
- Verify DECIMAL precision: float → Decimal conversion via `Decimal(str(value))`

---

### Patterns from Previous Stories

**Batch Writer Pattern** (from `audit_db_writer.py`):
- Buffer with configurable size threshold (100)
- Timer-based periodic flush (60s)
- Atomic buffer swap with `asyncio.Lock`
- Re-add on failure for resilience

**Done Callback Pattern** (from `audit_logger.py:252-271`):
```python
def audit_task_done_callback(task: asyncio.Task) -> None:
    if task.cancelled():
        logger.debug("Task %s cancelled", task.get_name())
        return
    exc = task.exception()
    if exc:
        logger.warning("Task %s failed: %s", task.get_name(), exc)
```

**Severity-to-Action Mapping for Violations:**
| Rule Action | Threshold % | Severity | action_taken | order_blocked |
|-------------|-------------|----------|--------------|---------------|
| BLOCK | Any | FATAL | blocked | True |
| WARN | >= 90% | CRITICAL | warned | False |
| WARN | >= 80% | WARNING | warned | False |
| WARN | < 80% | INFO | warned | False |

---

### Git History Reference

**Recent commits:**
- `67cf9cc` Implement spec 7 story 7.2 (Comprehensive Audit Log Table)
- `13fca35` Implement spec 7 story 7.1 (Trade Execution Audit Logging)
- `9ea9da7` Implement spec 6 story 6.6 (Resume Trading Command)
- `f4cc95c` Implement spec 6 story 6.5 (Emergency Stop)
- `ff70783` Implement spec 6 story 6.4 (Rule Violation Alerts)

**Files commonly modified in rule/audit stories:**
- `src/rules/audit_logger.py` - Rule validation event logging
- `src/rules/audit_db_writer.py` - Batch persistence to TimescaleDB
- `src/orders/execution_service.py` - Trade execution integration
- `src/engine.py` - Service wiring and lifecycle

---

### Additional Implementation Notes

1. **Migration Numbering**: Use `008_violations_retention_and_aggregate.sql`. Previous migrations: `006_add_trades_strategy_index.sql` (Story 7.1), `007_audit_retention_and_aggregate.sql` (Story 7.2).

2. **Shared vs Separate Engine**: ViolationDBWriter should use its OWN `create_async_engine()` instance (not shared with AuditDBWriter or TradeDBWriter). This provides connection pool isolation so one writer can't starve another.

3. **Don't Remove Redis Violations**: The `RedisStateManager.record_risk_violation()` at `src/state/redis_state.py:251-278` writes to `risk:{account_id}:violations`. Keep this for quick lookups. TimescaleDB is the durable long-term store; Redis is the hot cache.

4. **acknowledged Columns**: Map in ORM but don't implement acknowledgment workflow. Default: `acknowledged=False`, `acknowledged_at=None`. This is reserved for Story 7.5 CLI commands or future admin UI.

5. **Continuous Aggregate Lag**: The refresh policy uses `end_offset => INTERVAL '1 hour'`, meaning data from the last hour is NOT in the aggregate. Real-time violation queries for the last hour must hit the raw `rule_violations` hypertable.

6. **FK Race Condition**: `trade_id` FK references `trades(trade_id)`. For WARN violations where the trade proceeds, the trade record is created by TradeDBWriter in a separate batch. Since both use 60s flush intervals, the trade record should exist before the violation record is flushed. But if a violation references a trade_id that doesn't exist yet, the FK constraint will fail. **Solution:** For WARN violations, set `trade_id=None` at violation creation time. If linking is needed later, it can be updated via a separate process.

7. **Base Class Sharing**: Import `Base` from `audit_db_writer.py` for ORM model inheritance. All ORM models should use the same `DeclarativeBase` instance for metadata consistency.

8. **Error Handling in ViolationService**: Like AuditService, ViolationService methods have NO try/except. Errors propagate to the `asyncio.Task` and are caught by the caller's `audit_task_done_callback`. Do NOT add redundant exception handling.

---

### References

- [Source: infra/timescaledb/init.sql#rule_violations - Full DB schema with all 15 columns, CHECK constraints, FK constraints]
- [Source: docs/architecture.md#Database Schema (TimescaleDB) - STALE schema, missing 6 columns]
- [Source: docs/epics.md#Story 7.3: Rule Violation Tracking]
- [Source: docs/prd.md#FR44 - System can track rule violations with violation details and context]
- [Source: services/trading-engine/src/rules/audit_db_writer.py - AuditDBWriter + AuditLogModel pattern reference]
- [Source: services/trading-engine/src/rules/audit_logger.py - AuditLogger (per-account Redis writer) + AuditEntry + audit_task_done_callback]
- [Source: services/trading-engine/src/rules/audit_registry.py - AuditLoggerRegistry (per-account management, log_all_fire_and_forget)]
- [Source: services/trading-engine/src/execution/order_validator.py - OrderValidator (INTEGRATION POINT: _log_rule_results_to_audit iterates all results)]
- [Source: services/trading-engine/src/rules/base_rule.py - RuleResult, RuleAction, BaseRule interface]
- [Source: services/trading-engine/src/rules/engine.py - RuleEngine validation flow]
- [Source: services/trading-engine/src/state/redis_state.py - Existing Redis violation storage]
- [Source: services/trading-engine/src/accounts/risk_isolation.py - RiskIsolationService violation handling]
- [Source: Context7 /timescale/docs - Hypertable management, continuous aggregates, retention, compression]
- [Source: Context7 /websites/sqlalchemy_en_21 - SQLAlchemy 2.0 async ORM, bulk insert, DECIMAL types]

## Dev Agent Record

### Context Reference

Context7 MCP was used to retrieve latest documentation for:
- TimescaleDB - Hypertable creation (modern vs legacy syntax), continuous aggregates with FILTER, retention policies, compression with segmentby/orderby
- SQLAlchemy 2.1 - Async ORM model patterns, bulk insert with async sessions, Numeric/DECIMAL types, JSONB handling
- Python/CPython - asyncio fire-and-forget task patterns, batch writer patterns

### Agent Model Used

Claude Opus 4.6

### Debug Log References

N/A - No issues encountered during implementation.

### Completion Notes List

- Implemented RuleViolation dataclass with from_rule_result() factory supporting severity mapping (BLOCK→FATAL, WARN→CRITICAL/WARNING/INFO based on threshold %)
- Created RuleViolationModel ORM mapping all 17 columns from init.sql with Decimal precision and CHECK constraint validation in Python
- Built ViolationDBWriter following exact AuditDBWriter batch buffer pattern (100 batch, 60s flush, atomic swap, re-add on failure)
- Created ViolationService facade with record_block() and record_warning() convenience methods
- Integrated ViolationService into OrderValidator._log_rule_results_to_audit() with fire-and-forget pattern using asyncio.create_task() + audit_task_done_callback
- OrderValidator constructor extended with optional violation_service parameter (backward compatible)
- Created DB migration 008 with retention (90 days), continuous aggregate (violation_daily_summary), and compression (segmentby=account_id)
- 36 unit tests + 6 integration tests all passing, 0 regressions in existing test suite

### File List

- `services/trading-engine/src/rules/violation.py` (NEW) - RuleViolation dataclass with from_rule_result() factory, severity mapping, to_dict()
- `services/trading-engine/src/rules/violation_db_writer.py` (NEW) - RuleViolationModel ORM + ViolationDBWriter batch writer
- `services/trading-engine/src/rules/violation_service.py` (NEW) - ViolationService facade with record_block(), record_warning()
- `services/trading-engine/src/execution/order_validator.py` (MODIFIED) - Added violation_service injection, BLOCK/WARN recording in _log_rule_results_to_audit()
- `infra/timescaledb/migrations/008_violations_retention_and_aggregate.sql` (NEW) - Retention, continuous aggregate, compression policies
- `services/trading-engine/tests/unit/test_violation_service.py` (NEW) - 36 unit tests for Tasks 1-4
- `services/trading-engine/tests/integration/test_violation_tracking.py` (NEW) - 6 integration tests for Tasks 5, 7
- `docs/sprint-artifacts/7-3-rule-violation-tracking.md` (MODIFIED) - Story status and task completion tracking
- `docs/sprint-artifacts/sprint-status.yaml` (MODIFIED) - Story status updated

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-02-24 | Story context created with comprehensive developer guide. Used Context7 for TimescaleDB hypertable management, continuous aggregates, retention/compression policies, and SQLAlchemy 2.1 async ORM patterns. Exhaustive analysis of init.sql schema (15 columns, discovered architecture.md is stale). Analyzed existing codebase: AuditDBWriter pattern, RuleEngine flow, AuditLogger violation logging, RiskIsolationService, RedisStateManager. Incorporated intelligence from Story 7.1 (TradeDBWriter), 7.2 (AuditService), and 4.8 (AuditLogger). | Claude Opus 4.6 |
| 2026-02-24 | Validation fixes: (1) Column count 15→17 (was missing created_at, acknowledged_at in count). (2) Integration point changed from AuditLogger to OrderValidator — AuditLogger is per-account Redis-only with `__init__(redis_client, account_id)`, NOT `(redis_client, db_writer, violation_service)`. The actual integration point is `OrderValidator._log_rule_results_to_audit()` which already iterates all (rule, result) tuples. (3) Method name `log_validation()` → `log_rule_check()`. (4) Engine wiring updated — ViolationService injected into OrderValidator, not AuditLogger. (5) Added AuditLoggerRegistry and OrderValidator to context references. | Claude Opus 4.6 |
| 2026-02-24 | Implementation complete. Created RuleViolation dataclass, RuleViolationModel ORM (17 columns, Decimal precision, CHECK constraint validation), ViolationDBWriter (batch buffer pattern), ViolationService facade, OrderValidator integration (fire-and-forget BLOCK/WARN recording), DB migration 008 (retention + continuous aggregate + compression). 37 tests (31 unit + 6 integration), 0 regressions. | Claude Opus 4.6 |
| 2026-02-24 | Code review fixes: (H1) Added order_id to violation signal context for traceability. (M1) Removed unused uuid import from violation.py (ruff F401). (M2) Added 5 tests for ViolationDBWriter start/stop lifecycle (start, idempotency, stop with flush+dispose, stop idempotency). (M3) Added done_callback to fire-and-forget flush task in add_violation(). (M4) Added test for auto-flush at batch_size threshold. 42 tests (36 unit + 6 integration), 0 regressions. | Claude Opus 4.6 |
