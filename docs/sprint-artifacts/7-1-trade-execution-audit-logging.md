# Story 7.1: Trade Execution Audit Logging

Status: done

## Story

As a **trader**,
I want **every trade execution logged with full details**,
So that **I have complete records for compliance verification**.

## Acceptance Criteria

1. **Given** a trade is executed
   **When** the execution confirmation returns
   **Then** a record is inserted into TimescaleDB `trades` table:
   ```sql
   INSERT INTO trades (
     trade_id, account_id, strategy_name, symbol, side,
     quantity, entry_price, entry_time, slippage,
     signal_reason, metadata
   ) VALUES (
     'uuid', 'ftmo-gold-001', 'ma_crossover', 'XAUUSD', 'BUY',
     0.1, 1850.25, '2025-12-03T14:32:15Z', 0.02,
     'MA crossover (20/50)', '{"fast_ma": 1850.10, "slow_ma": 1849.80}'
   );
   ```

2. **Given** a position is closed
   **When** the close confirmation returns
   **Then** the trade record is updated:
   ```sql
   UPDATE trades SET
     exit_price = 1858.50,
     exit_time = '2025-12-03T15:45:00Z',
     pnl_dollars = 82.50,
     pnl_percent = 0.0825
   WHERE trade_id = 'uuid';
   ```

3. **Given** I query trades for an account
   **When** I run `SELECT * FROM trades WHERE account_id = 'ftmo-gold-001'`
   **Then** I see all trades with complete entry and exit details

## Tasks / Subtasks

**Task Dependency Order:**
```
Task 1 (TradeDBWriter setup) → Task 2 (TradeAuditModel) → Task 3 (Integration with ExecutionService) → Task 4 (Position Close Updates) → Task 5 (Tests)
```

- [x] Task 1: Create TradeDBWriter with Batch Buffer Pattern (AC: #1)
  - [x] 1.1: Create `src/orders/trade_db_writer.py` following AuditDBWriter pattern from `src/rules/audit_db_writer.py`
  - [x] 1.2: Implement async batch buffer with configurable batch_size (default: 100) and flush_interval (default: 60s) - same as AuditDBWriter for consistency
  - [x] 1.3: Add `start()` method to initialize flush timer loop
  - [x] 1.4: Add `stop()` method for graceful shutdown with final buffer flush
  - [x] 1.5: Add `write_trade_entry(trade: Trade)` method for new trade entry
  - [x] 1.6: Add `update_trade_exit(trade_id: str, exit_data: dict)` method for position close updates

- [x] Task 2: Create TradeAuditModel SQLAlchemy ORM Model (AC: #1, #3)
  - [x] 2.1: Extend existing `TradeRecord` in `src/orders/db_models.py` to add missing fields: strategy_name, signal_reason, metadata, pnl_percent
  - [x] 2.2: Add `from_trade(trade: Trade)` factory method for converting Trade dataclass to ORM model
  - [x] 2.3: Add `to_dict()` method for serialization if needed
  - [x] 2.4: Ensure DECIMAL precision for all financial fields (entry_price, exit_price, pnl_dollars, quantity)

- [x] Task 3: Integrate TradeDBWriter with OrderExecutionService (AC: #1)
  - [x] 3.1: Inject TradeDBWriter dependency into OrderExecutionService constructor
  - [x] 3.2: In `_handle_entry_fill()`, call `trade_db_writer.write_trade_entry(trade)` after Trade creation
  - [x] 3.3: Fire-and-forget pattern: Use `asyncio.create_task()` with done_callback for non-blocking writes
  - [x] 3.4: Pass Signal object to write method: `strategy_name=signal.strategy_name`, `signal_reason=signal.metadata.get('reason')` if metadata exists, `metadata=signal.metadata`

- [x] Task 4: Implement Trade Exit Updates (AC: #2)
  - [x] 4.1: In `_handle_close_fill()`, call `trade_db_writer.update_trade_exit()` with exit details
  - [x] 4.2: Use `ON CONFLICT DO UPDATE` pattern for idempotent updates (or direct UPDATE by trade_id)
  - [x] 4.3: Calculate and store pnl_percent alongside pnl_dollars
  - [x] 4.4: Handle error cases where entry trade record may not exist yet (log warning)

- [x] Task 5: Add Unit and Integration Tests (AC: #1-3)
  - [x] 5.1: Unit test: `TradeDBWriter.write_trade_entry()` adds to buffer
  - [x] 5.2: Unit test: `TradeDBWriter._flush_buffer()` persists entries
  - [x] 5.3: Unit test: `TradeDBWriter.update_trade_exit()` updates existing record
  - [x] 5.4: Unit test: `TradeAuditModel.from_trade()` converts correctly with all fields
  - [x] 5.5: Integration test: Full flow from order execution to database query
  - [x] 5.6: Integration test: Trade entry → position close → verify complete record

### Review Follow-ups (AI)

- [ ] [AI-Review][MEDIUM] Add true database integration tests using PostgreSQL test container to verify AC #3 (SELECT queries returning complete records)
- [ ] [AI-Review][LOW] Remove redundant `index=True` on `account_id` column (composite index `idx_trades_account_time` already covers single-column lookups)
- [ ] [AI-Review][LOW] Document that `pnl_percent` is stored as percentage*100 (e.g., 10% = 10.0) and DECIMAL(8,4) limits to ±9999.9999%

## Dev Notes

### CRITICAL: Read Before Implementation

**These items MUST be completed or the feature will not work:**

1. **DECIMAL Precision**: ALL financial fields (entry_price, exit_price, pnl_dollars, quantity, slippage) MUST use `Decimal` type, NOT float. This prevents rounding errors in compliance calculations.

2. **Fire-and-Forget Pattern**: Trade logging MUST NOT block the execution flow. Use `asyncio.create_task()` with `audit_task_done_callback` pattern from existing `audit_logger.py`.

3. **Existing Trade Model**: The `Trade` dataclass in `src/orders/trade.py` already exists. Do NOT duplicate - extend or add conversion methods.

4. **Existing TradeRecord ORM**: The `TradeRecord` model in `src/orders/db_models.py` exists but is missing: `strategy_name`, `signal_reason`, `metadata`, `pnl_percent`. EXTEND it, don't replace.

5. **Database Schema**: The `trades` table is defined in `infra/timescaledb/init.sql`. Verify your model matches the schema or add migration if needed.

6. **strategy_name is NOT NULL in DB**: Architecture schema has `strategy_name VARCHAR(100) NOT NULL`. Either: (a) require strategy_name in `from_trade()` and raise ValueError if missing, OR (b) create migration to `ALTER COLUMN strategy_name DROP NOT NULL`. Recommended: option (a) - strategies should always have names.

7. **signal_reason comes from Signal.metadata**: The `Signal` class has `strategy_name` and `metadata` but NO `signal_reason` field. Extract reason from metadata: `signal.metadata.get('reason') if signal.metadata else None`.

---

### Quick Reference: What to Create/Modify

| Component | What to Do | Location |
|-----------|------------|----------|
| **TradeDBWriter** | Create new (follow AuditDBWriter pattern) | `src/orders/trade_db_writer.py` |
| **TradeRecord** | Add missing columns | `src/orders/db_models.py` |
| **OrderExecutionService** | Add db_writer injection, call write methods | `src/orders/execution_service.py` |
| **Trade dataclass** | No changes needed | `src/orders/trade.py` |
| **Tests** | New test file | `tests/unit/test_trade_db_writer.py` |

---

### Architecture Compliance

**Service:** `services/trading-engine/` (Python 3.11+)
**Database:** TimescaleDB (PostgreSQL 16+)
**ORM:** SQLAlchemy 2.0+ with async support (asyncpg)

**CRITICAL CONSTRAINTS from Architecture:**

From [Source: docs/architecture.md#Database Schema (TimescaleDB)]:
```sql
CREATE TABLE trades (
    trade_id UUID PRIMARY KEY,
    account_id VARCHAR(50) REFERENCES accounts(id),
    strategy_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL,
    quantity DECIMAL(18, 8) NOT NULL,
    entry_price DECIMAL(18, 5) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_price DECIMAL(18, 5),
    exit_time TIMESTAMPTZ,
    pnl_dollars DECIMAL(18, 2),
    pnl_percent DECIMAL(8, 4),
    slippage DECIMAL(18, 5),
    signal_reason TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trades_time ON trades (entry_time DESC);
CREATE INDEX idx_trades_account ON trades (account_id, entry_time DESC);
CREATE INDEX idx_trades_strategy ON trades (strategy_name, entry_time DESC);
```

**Communication Patterns:**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Outbound | PostgreSQL | 5432 | Trade history, audit (per account) |

---

### Context from Previous Stories

**From Story 4.8 (Rule Check Audit Logging) - Key Patterns Established:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| Batch DB Writer | `AuditDBWriter` with buffer, timer flush | `src/rules/audit_db_writer.py` |
| Fire-and-forget | `asyncio.create_task()` + done_callback | `src/rules/audit_logger.py:252-271` |
| ORM Model | `AuditLogModel` with `from_audit_entry()` factory | `src/rules/audit_db_writer.py:37-103` |
| Async Session | `async_sessionmaker` + `create_async_engine` | `src/rules/audit_db_writer.py:147-157` |

**From Story 2.5 (Order Execution Flow) - Execution Service Patterns:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| Trade creation | `_handle_entry_fill()` creates Trade | `src/orders/execution_service.py:300-329` |
| Position close | `_handle_close_fill()` with PnL | `src/orders/execution_service.py:331-388` |
| Dependency injection | Constructor with adapters | `src/orders/execution_service.py:69-86` |

**Existing Trade Dataclass Fields** (from `src/orders/trade.py`):
- trade_id, order_id, account_id, symbol, side, quantity
- entry_price, entry_time, exit_price, exit_time
- pnl_dollars, pnl_percent, slippage

**Existing TradeRecord ORM Fields** (from `src/orders/db_models.py`):
- trade_id, account_id, symbol, side, quantity
- entry_price, entry_time, exit_price, exit_time
- pnl_dollars, status, created_at
- **MISSING**: strategy_name, signal_reason, metadata, pnl_percent, slippage

---

### Latest Technical Documentation (Context7 Research)

**SQLAlchemy 2.0 Async Patterns:**

```python
# Bulk INSERT with async session (from Context7 /websites/sqlalchemy_en_20)
async with async_session() as session:
    async with session.begin():
        session.add_all([
            TradeModel(...),
            TradeModel(...),
        ])
# Commits automatically on context exit

# Bulk INSERT with RETURNING (for getting generated IDs)
users = session.scalars(
    insert(User).returning(User),
    [{"name": "alice"}, {"name": "bob"}],
)
```

**PostgreSQL Upsert Pattern (ON CONFLICT):**
```python
from sqlalchemy.dialects.postgresql import insert

stmt = insert(trades).values(trade_id=..., ...)
stmt = stmt.on_conflict_do_update(
    index_elements=['trade_id'],
    set_={'exit_price': stmt.excluded.exit_price, ...}
)
await session.execute(stmt)
```

**TimescaleDB Best Practices (from Context7 /timescale/docs):**
- Batch inserts are more efficient than row-by-row
- Use `executemany()` or batch `add_all()` for bulk operations
- Typical batch sizes: 50-1000 rows depending on payload size

---

### Implementation Guide

**Step 1: Extend TradeRecord in db_models.py**

```python
# Add these imports at top of file
import uuid
from decimal import Decimal
from sqlalchemy.dialects.postgresql import JSONB

# Add missing columns to existing TradeRecord class
strategy_name = Column(String(100), nullable=False)  # NOT NULL per architecture schema
signal_reason = Column(String, nullable=True)  # TEXT type
metadata = Column(JSONB, nullable=True)
pnl_percent = Column(DECIMAL(8, 4), nullable=True)
slippage = Column(DECIMAL(18, 5), nullable=True)

# Add index to __table_args__ (after existing indexes)
Index("idx_trades_strategy", "strategy_name", "entry_time"),

# Add factory method
@classmethod
def from_trade(cls, trade: "Trade", strategy_name: str,
               signal_reason: str = None, metadata: dict = None) -> "TradeRecord":
    """Create TradeRecord from Trade dataclass.

    Args:
        trade: Trade dataclass instance
        strategy_name: REQUIRED - name of strategy that generated the trade
        signal_reason: Optional reason extracted from signal.metadata.get('reason')
        metadata: Optional signal metadata dict

    Raises:
        ValueError: If strategy_name is None or empty (DB constraint)
    """
    if not strategy_name:
        raise ValueError("strategy_name is required (NOT NULL constraint in database)")

    return cls(
        trade_id=uuid.UUID(trade.trade_id),
        account_id=trade.account_id,
        strategy_name=strategy_name,
        symbol=trade.symbol,
        side=trade.side.value,  # OrderSide enum to string
        quantity=Decimal(str(trade.quantity)),
        entry_price=Decimal(str(trade.entry_price)),
        entry_time=trade.entry_time,
        exit_price=Decimal(str(trade.exit_price)) if trade.exit_price else None,
        exit_time=trade.exit_time,
        pnl_dollars=Decimal(str(trade.pnl_dollars)) if trade.pnl_dollars else None,
        pnl_percent=Decimal(str(trade.pnl_percent)) if trade.pnl_percent else None,
        slippage=Decimal(str(trade.slippage)) if trade.slippage else None,
        signal_reason=signal_reason,
        metadata=metadata,
        status="open" if trade.is_open else "closed",
    )
```

**Step 2: Create TradeDBWriter**

```python
# src/orders/trade_db_writer.py
"""Trade DB Writer - Batch persistence of trade records to TimescaleDB."""

import asyncio
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.dialects.postgresql import insert

from .trade import Trade
from .db_models import TradeRecord

logger = logging.getLogger(__name__)

class TradeDBWriter:
    """Batched writer for persisting trade records to TimescaleDB.

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
        self._buffer: list[TradeRecord] = []
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

        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(
            self._flush_timer_loop(),
            name="trade_db_flush_timer",
        )
        logger.info("TradeDBWriter started (batch=%d, interval=%.1fs)",
                    self._batch_size, self._flush_interval)

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
        logger.info("TradeDBWriter stopped")

    async def write_trade_entry(
        self,
        trade: Trade,
        strategy_name: str = None,
        signal_reason: str = None,
        metadata: dict = None,
    ) -> None:
        """Add new trade entry to buffer."""
        record = TradeRecord.from_trade(trade, strategy_name, signal_reason, metadata)
        async with self._buffer_lock:
            self._buffer.append(record)
            should_flush = len(self._buffer) >= self._batch_size
        if should_flush:
            asyncio.create_task(self._flush_buffer())

    async def update_trade_exit(
        self,
        trade_id: str,
        exit_price: float,
        exit_time: datetime,
        pnl_dollars: float,
        pnl_percent: float,
    ) -> None:
        """Update existing trade with exit details."""
        async with self._session_factory() as session:
            async with session.begin():
                stmt = (
                    update(TradeRecord)
                    .where(TradeRecord.trade_id == uuid.UUID(trade_id))
                    .values(
                        exit_price=Decimal(str(exit_price)),
                        exit_time=exit_time,
                        pnl_dollars=Decimal(str(pnl_dollars)),
                        pnl_percent=Decimal(str(pnl_percent)),
                        status="closed",
                    )
                )
                await session.execute(stmt)

    # ... flush timer loop and batch insert methods same as AuditDBWriter
```

**Step 3: Integrate with OrderExecutionService**

```python
# In src/orders/execution_service.py

# Add import at top
from src.rules.audit_logger import audit_task_done_callback

def __init__(
    self,
    zmq_adapter: ZmqAdapter,
    position_tracker: PositionTracker,
    trade_db_writer: Optional["TradeDBWriter"] = None,  # NEW
    order_timeout: float = 5.0,
) -> None:
    self._zmq = zmq_adapter
    self._positions = position_tracker
    self._trade_db_writer = trade_db_writer  # NEW
    # ...

# IMPORTANT: Modify execute_signal() to store Signal for later use
async def execute_signal(
    self,
    signal: Signal,
    account_id: str,
    volume: float,
    price: float,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
) -> InternalOrder:
    # Store signal for use in _handle_entry_fill
    self._current_signal = signal  # NEW: Store for DB write
    # ... rest of existing code ...

def _handle_entry_fill(self, order: InternalOrder) -> None:
    # ... existing code ...
    trade = Trade(...)
    self._trades.append(trade)

    # NEW: Fire-and-forget DB write using stored Signal
    if self._trade_db_writer and hasattr(self, '_current_signal'):
        signal = self._current_signal
        task = asyncio.create_task(
            self._trade_db_writer.write_trade_entry(
                trade,
                strategy_name=signal.strategy_name,  # From Signal object
                signal_reason=signal.metadata.get('reason') if signal.metadata else None,
                metadata=signal.metadata,
            ),
            name=f"trade_write_{trade.trade_id[:8]}",
        )
        task.add_done_callback(audit_task_done_callback)
```

---

### Project Structure Notes

**File Locations:**
```
services/trading-engine/
├── src/
│   ├── orders/
│   │   ├── db_models.py         # MODIFY: Add columns, from_trade()
│   │   ├── trade_db_writer.py   # CREATE: New file
│   │   ├── execution_service.py # MODIFY: Inject writer, call methods
│   │   └── trade.py             # READ ONLY: Reference
│   └── rules/
│       ├── audit_db_writer.py   # REFERENCE: Pattern to follow
│       └── audit_logger.py      # REFERENCE: Done callback pattern
├── tests/
│   ├── unit/
│   │   └── test_trade_db_writer.py  # CREATE: New test file
│   └── integration/
│       └── test_trade_audit_integration.py  # CREATE: New test file
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

- Unit tests: `pytest services/trading-engine/tests/unit/test_trade_db_writer.py`
- Integration tests: `pytest services/trading-engine/tests/integration/ -k trade_audit`
- Run all: `cd services/trading-engine && pytest`
- Use `pytest-asyncio` for async test functions
- Mock database with `AsyncMock` for unit tests

---

### Patterns from Previous Stories

**Batch Writer Pattern** (from `audit_db_writer.py`):
- Buffer with configurable size threshold
- Timer-based periodic flush
- Atomic buffer swap with lock
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

---

### Git History Reference

**Recent commits:**
- `9ea9da7` Implement spec 6 story 6.6 (Resume Trading Command)
- `f4cc95c` Implement spec 6 story 6.5 (Emergency Stop)
- `ff70783` Implement spec 6 story 6.4 (Rule Violation Alerts)

**Files commonly modified in execution stories:**
- `src/orders/execution_service.py`
- `src/orders/trade.py`
- `src/orders/db_models.py`

---

### Additional Implementation Notes

1. **Migration Script**: If the `trades` table schema needs updating (to add missing columns), create a migration script in `infra/timescaledb/migrations/` rather than modifying `init.sql` directly.

2. **Backward Compatibility**: Make new columns nullable so existing records aren't affected.

3. **Signal Metadata Fields**: The `Signal` class (`src/orders/signal.py`) already has `strategy_name: str` and `metadata: dict`. Extract `signal_reason` from `signal.metadata.get('reason')` - there is NO direct `signal_reason` field on Signal.

4. **Index Usage**: The `idx_trades_strategy` index enables efficient queries by strategy. Add it to TradeRecord.__table_args__.

5. **Error Handling**: If trade entry fails to write, log warning but don't block execution. Trade data is also in memory (`self._trades` list) as fallback.

---

### References

- [Source: docs/architecture.md#Database Schema (TimescaleDB)]
- [Source: docs/architecture.md#Trading Engine (Python)]
- [Source: docs/epics.md#Story 7.1: Trade Execution Audit Logging]
- [Source: docs/prd.md#FR43 - Record all trade executions with full context per account]
- [Source: services/trading-engine/src/rules/audit_db_writer.py - Pattern reference]
- [Source: services/trading-engine/src/orders/execution_service.py - Integration point]
- [Source: services/trading-engine/src/orders/db_models.py - Existing TradeRecord]
- [Source: Context7 /websites/sqlalchemy_en_20 - SQLAlchemy async bulk insert patterns]
- [Source: Context7 /timescale/docs - TimescaleDB batch insert best practices]

## Dev Agent Record

### Context Reference

Context7 MCP was used to retrieve latest documentation for:
- SQLAlchemy 2.0 - Async session INSERT, bulk operations, upsert with ON CONFLICT
- TimescaleDB - Hypertable batch insert patterns and performance best practices

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A - Story context creation phase.

### Completion Notes List

- **Task 1**: Created `TradeDBWriter` class in `src/orders/trade_db_writer.py` following the exact pattern from `AuditDBWriter`. Implemented async batch buffer with configurable batch_size (100) and flush_interval (60s). Added `start()`, `stop()`, `write_trade_entry()`, and `update_trade_exit()` methods.

- **Task 2**: Extended `TradeRecord` in `src/orders/db_models.py` with missing columns: `strategy_name` (NOT NULL), `signal_reason`, `signal_metadata` (maps to `metadata` column in DB - renamed due to SQLAlchemy reserved attribute), `pnl_percent`, `slippage`. Added `from_trade()` factory method with strategy_name validation and `to_dict()` serialization method. All financial fields use DECIMAL precision.

- **Task 3**: Integrated `TradeDBWriter` into `OrderExecutionService` via constructor injection. Signal is stored during `execute_signal()` and used in `_handle_entry_fill()` to extract strategy_name, signal_reason (from `metadata.get('reason')`), and full metadata. Fire-and-forget pattern using `asyncio.create_task()` with `audit_task_done_callback` for error handling.

- **Task 4**: Updated `_handle_close_fill()` to find existing entry trade and update it with exit details. Calls `update_trade_exit()` with trade_id, exit_price, exit_time, pnl_dollars, and pnl_percent. Logs warning if entry record not found (e.g., positions opened before DB writer was configured).

- **Task 5**: Created 19 unit tests in `tests/unit/test_trade_db_writer.py` and 12 integration tests in `tests/integration/test_trade_audit_integration.py`. All 31 new tests pass. Tests cover: TradeRecord.from_trade() conversion, strategy_name validation, buffer management, flush behavior, update_trade_exit(), fire-and-forget pattern, full trade lifecycle, PnL calculations.

### File List

**Created:**
- `services/trading-engine/src/orders/trade_db_writer.py` - TradeDBWriter class with batch buffer pattern
- `services/trading-engine/tests/unit/test_trade_db_writer.py` - Unit tests (19 tests)
- `services/trading-engine/tests/integration/test_trade_audit_integration.py` - Service-level integration tests (12 tests)
- `infra/timescaledb/migrations/006_add_trades_strategy_index.sql` - Migration for strategy+time index

**Modified:**
- `services/trading-engine/src/orders/db_models.py` - Extended TradeRecord with missing columns, factory methods, order_type, fixed slippage_pips column name
- `services/trading-engine/src/orders/execution_service.py` - Integrated TradeDBWriter, concurrency-safe signal mapping, fire-and-forget DB writes
- `docs/sprint-artifacts/sprint-status.yaml` - Sprint status update

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-01-22 | Story context created with comprehensive developer guide. Used Context7 for SQLAlchemy 2.0 async patterns and TimescaleDB batch insert best practices. Analyzed existing codebase patterns from audit_db_writer.py, audit_logger.py, execution_service.py, and db_models.py. | Claude Opus 4.5 |
| 2026-01-22 | Validation improvements applied: (1) Clarified signal_reason comes from signal.metadata.get('reason'), (2) Made strategy_name NOT NULL with ValueError on missing, (3) Fixed implementation guide to use Signal object directly instead of non-existent InternalOrder fields, (4) Added idx_trades_strategy index, (5) Added complete imports to code examples, (6) Aligned batch_size/flush_interval with AuditDBWriter defaults (100/60s). | Bob (SM Validation) |
| 2026-01-22 | Implementation complete. Created TradeDBWriter with batch buffer pattern, extended TradeRecord ORM model, integrated with OrderExecutionService using fire-and-forget pattern. Note: `metadata` column renamed to `signal_metadata` in Python due to SQLAlchemy reserved attribute (DB column still named `metadata`). All 31 tests pass (19 unit + 12 integration). | Claude Opus 4.5 |
| 2026-01-23 | **Code Review Fixes (7 issues):** (1) Fixed race condition: replaced shared `_current_signal` with order-keyed `_signals_by_order` dict for concurrency safety. (2) Fixed buffer race: `update_trade_exit()` now flushes buffer before UPDATE to prevent silent data loss on quick close. (3) Added guard for empty `strategy_name` with warning log. (4) Fixed `to_dict()` Decimal-to-float precision loss (now uses str). (5) Fixed ORM-to-DB schema mismatch: added `order_type` column (NOT NULL in DB), renamed `slippage` to `slippage_pips` to match actual DB column. Created migration for strategy index. (6) Clarified integration tests are service-level (mock DB), not true DB integration. (7) Updated File List. | Claude Opus 4.5 (Code Review) |
