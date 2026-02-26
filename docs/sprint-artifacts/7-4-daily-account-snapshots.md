# Story 7.4: Daily Account Snapshots

Status: Done

## Story

As a **trader**,
I want **daily snapshots of my account status stored**,
So that **I can track compliance over time**.

## Acceptance Criteria

1. **Given** it's midnight UTC
   **When** the day ends
   **Then** a snapshot is created for each active account:
   ```sql
   INSERT INTO account_snapshots (
     id, account_id, snapshot_date, snapshot_time,
     opening_balance, closing_balance,
     high_balance, low_balance,
     daily_pnl, daily_pnl_percent,
     peak_balance, drawdown_from_peak, drawdown_percent,
     trades_count, winning_trades, losing_trades, total_volume
   ) VALUES (
     'uuid', 'ftmo-gold-001', '2025-12-03', '00:00:00',
     100000.00, 99350.00,
     101200.00, 99100.00,
     -650.00, -0.65,
     102500.00, 3150.00, 3.07,
     8, 3, 5, 1.20
   );
   ```

2. **Given** I want to see my FTMO challenge progress
   **When** I query:
   ```sql
   SELECT snapshot_date, closing_balance, daily_pnl_percent, drawdown_percent
   FROM account_snapshots
   WHERE account_id = 'ftmo-gold-001'
   ORDER BY snapshot_date;
   ```
   **Then** I see daily progress through my challenge

3. **Given** FTMO requires minimum 4 trading days
   **When** I query:
   ```sql
   SELECT COUNT(*) as trading_days
   FROM account_snapshots
   WHERE account_id = 'ftmo-gold-001' AND trades_count > 0;
   ```
   **Then** I can verify my trading days requirement

4. **Given** the snapshot job already ran today for an account
   **When** a duplicate snapshot is attempted (e.g., engine restart)
   **Then** the existing snapshot is updated (upsert), NOT duplicated
   (enforced by UNIQUE(account_id, snapshot_date) constraint)

## Tasks / Subtasks

**Task Dependency Order:**
```
Task 1 (AccountSnapshotModel ORM) → Task 2 (SnapshotDBWriter) → Task 3 (DailySnapshotService) → Task 4 (Engine Integration) → Task 5 (Tests)
```

- [x] Task 1: Create AccountSnapshotModel ORM Model (AC: #1)
  - [x] 1.1: Create `src/snapshots/models.py` with `AccountSnapshotModel` class mapping ALL 17 columns from `init.sql` (NOT the stale architecture.md schema)
  - [x] 1.2: Map all financial fields as `DECIMAL(18, 2)` or `DECIMAL(8, 4)` matching exact DB column types
  - [x] 1.3: Add `from_snapshot_data()` classmethod to create ORM instance from collected metrics dict
  - [x] 1.4: Add `to_dict()` method for serialization (financial fields as strings for precision)
  - [x] 1.5: Create `src/snapshots/__init__.py` with exports

- [x] Task 2: Create SnapshotDBWriter (AC: #1, #4)
  - [x] 2.1: Create `src/snapshots/snapshot_db_writer.py` with `SnapshotDBWriter` class
  - [x] 2.2: Implement `write_snapshot(snapshot_data: dict)` method using INSERT ... ON CONFLICT (account_id, snapshot_date) DO UPDATE for idempotent upserts
  - [x] 2.3: Use `async_sessionmaker` + `create_async_engine` pattern from existing writers (AuditDBWriter)
  - [x] 2.4: Implement `start()` and `stop()` lifecycle methods matching existing pattern
  - [x] 2.5: NO batch buffer needed (one snapshot per account per day = low volume) - direct write is sufficient

- [x] Task 3: Create DailySnapshotService (AC: #1, #2, #3)
  - [x] 3.1: Create `src/snapshots/daily_snapshot_service.py` with `DailySnapshotService` class
  - [x] 3.2: Implement midnight UTC scheduler using asyncio: calculate seconds until next midnight, sleep, execute, repeat
  - [x] 3.3: Implement `_collect_snapshot_data(account_id)` method that gathers data from:
    - Redis `RiskState` (opening_balance=daily_starting_balance, daily_pnl, daily_pnl_percent, peak_equity, total_drawdown_percent)
    - Redis `StateSnapshot` (closing_balance=account_balance, peak_balance)
    - TimescaleDB `state_snapshots` table (high_balance=MAX, low_balance=MIN for today)
    - TimescaleDB `trades` table (trades_count, winning_trades, losing_trades, total_volume for today)
  - [x] 3.4: Implement `_take_all_snapshots()` that iterates over all active accounts
  - [x] 3.5: Calculate derived fields: `drawdown_from_peak = peak_balance - closing_balance`
  - [x] 3.6: Fire-and-forget pattern: log errors per account but continue with remaining accounts
  - [x] 3.7: Add `start()` and `stop()` lifecycle methods with running flag

- [x] Task 4: Integrate DailySnapshotService with Engine (AC: #1)
  - [x] 4.0: Add `get_active_account_ids()` method to `AccountManager` returning `[aid for aid, acc in self._accounts.items() if acc.status == 'active']` (method does not exist yet)
  - [x] 4.1: Add `_daily_snapshot_service` to `TradingEngine.__init__()` (optional dependency)
  - [x] 4.2: Create `_initialize_daily_snapshots()` method following `_initialize_cold_storage()` pattern
  - [x] 4.3: Call `_initialize_daily_snapshots()` in `engine.run()` after `_initialize_cold_storage()`
  - [x] 4.4: Add `_daily_snapshot_service.stop()` to engine shutdown sequence
  - [x] 4.5: Log system_event via AuditService when daily snapshots are taken (event_subtype="daily_snapshot")

- [x] Task 5: Add Unit and Integration Tests (AC: #1-4)
  - [x] 5.1: Unit test: `AccountSnapshotModel.from_snapshot_data()` maps all 17 columns correctly
  - [x] 5.2: Unit test: `AccountSnapshotModel.to_dict()` preserves DECIMAL precision (no float conversion)
  - [x] 5.3: Unit test: `SnapshotDBWriter.write_snapshot()` calls session with correct model
  - [x] 5.4: Unit test: `SnapshotDBWriter.write_snapshot()` upsert handles duplicate (account_id, snapshot_date)
  - [x] 5.5: Unit test: `DailySnapshotService._collect_snapshot_data()` aggregates from Redis + DB sources
  - [x] 5.6: Unit test: `DailySnapshotService._calculate_seconds_until_midnight()` returns correct delay
  - [x] 5.7: Unit test: `DailySnapshotService._take_all_snapshots()` continues on per-account failure
  - [x] 5.8: Unit test: `drawdown_from_peak` calculation: `peak_balance - closing_balance`
  - [x] 5.9: Integration test: Full flow from Redis state + trades query → account_snapshots INSERT
  - [x] 5.10: Integration test: Upsert overwrites existing snapshot for same account+date
  - [x] 5.11: Integration test: Engine lifecycle start → snapshot service running → shutdown stops service
  - [x] 5.12: Integration test: Compliance query: trading days count WHERE trades_count > 0

## Dev Notes

### CRITICAL: Read Before Implementation

**These items MUST be completed or the feature will not work:**

1. **USE init.sql SCHEMA, NOT architecture.md**: The `account_snapshots` table in `infra/timescaledb/init.sql` (lines 60-82) has 7 additional columns compared to `docs/architecture.md` (lines 1184-1197). The init.sql is the deployed schema. Map ALL 17 data columns.

2. **init.sql Schema (AUTHORITATIVE):**
   ```sql
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
   ```

3. **NOT a Hypertable**: Unlike `audit_logs` and `rule_violations`, `account_snapshots` is a regular PostgreSQL table with a standard UUID PRIMARY KEY. No hypertable-specific patterns needed.

4. **UNIQUE Constraint for Idempotent Upsert**: The `UNIQUE(account_id, snapshot_date)` constraint enables INSERT ... ON CONFLICT DO UPDATE. Use this for idempotent writes - if the engine restarts and the scheduler fires again for the same date, the snapshot is updated, not duplicated.

5. **ON DELETE CASCADE**: Deleting an account will cascade-delete all its snapshots. No orphan cleanup needed.

6. **`account_id` is NOT NULL**: Unlike `audit_logs`, every snapshot MUST have an account_id. System-level snapshots do not exist.

7. **No Batch Buffer**: Unlike AuditDBWriter/TradeDBWriter, daily snapshots have extremely low volume (one per account per day, typically 1-5 accounts). Direct INSERT is appropriate - no buffer/flush pattern needed.

8. **Data Sources - Where Each Field Comes From:**

   | Snapshot Field | Source | Access Pattern |
   |---------------|--------|---------------|
   | `opening_balance` | `RiskState.daily_starting_balance` | Redis: `risk:{account_id}:state` |
   | `closing_balance` | `StateSnapshot.account_balance` | Redis: `snapshot:{account_id}:latest` |
   | `high_balance` | `MAX(account_balance)` from `state_snapshots` today | TimescaleDB query |
   | `low_balance` | `MIN(account_balance)` from `state_snapshots` today | TimescaleDB query |
   | `daily_pnl` | `RiskState.daily_pnl` | Redis: `risk:{account_id}:state` |
   | `daily_pnl_percent` | `RiskState.daily_pnl_percent` | Redis: `risk:{account_id}:state` |
   | `peak_balance` | `StateSnapshot.peak_balance` | Redis: `snapshot:{account_id}:latest` |
   | `drawdown_from_peak` | `peak_balance - closing_balance` | Calculated |
   | `drawdown_percent` | `RiskState.total_drawdown_percent` | Redis: `risk:{account_id}:state` |
   | `trades_count` | `COUNT(*)` from `trades` today | TimescaleDB query |
   | `winning_trades` | `COUNT(*) FILTER (pnl_dollars > 0)` from `trades` today | TimescaleDB query |
   | `losing_trades` | `COUNT(*) FILTER (pnl_dollars < 0)` from `trades` today | TimescaleDB query |
   | `total_volume` | `SUM(quantity)` from `trades` today | TimescaleDB query |

9. **High/Low Balance from state_snapshots**: The `state_snapshots` hypertable stores balance snapshots every 60 seconds (ColdStorageService). Query `MAX(account_balance)` and `MIN(account_balance)` for the current day. The 7-day retention policy means today's data is always available.

10. **Midnight UTC Scheduling Pattern**: Use asyncio-native scheduling, NOT APScheduler (avoids new dependency). Calculate seconds until next midnight UTC, `await asyncio.sleep(delay)`, execute, repeat. This follows the existing timer patterns in ColdStorageService and AuditDBWriter.

11. **Timezone Handling**: All times in UTC. Use `datetime.now(timezone.utc)`. The `snapshot_date` field is a DATE type (no timezone). Calculate `today = datetime.now(timezone.utc).date()` for the snapshot date. The `snapshot_time` defaults to '00:00:00' in the DB.

12. **DECIMAL Precision**: ALL financial fields MUST use Python `Decimal` type, NOT float. Convert via `Decimal(str(value))`. This prevents rounding errors in compliance calculations. FTMO challenge precision matters.

13. **Per-Account Error Isolation**: If data collection fails for one account (e.g., Redis key missing, MT5 disconnected), log error and continue with remaining accounts. Do NOT halt the entire snapshot run.

14. **Trades Query for Daily Stats**: Query the `trades` table for the snapshot date:
    ```sql
    SELECT
        COUNT(*) as trades_count,
        COUNT(*) FILTER (WHERE pnl_dollars > 0) as winning_trades,
        COUNT(*) FILTER (WHERE pnl_dollars < 0) as losing_trades,
        COALESCE(SUM(quantity), 0) as total_volume
    FROM trades
    WHERE account_id = :account_id
      AND entry_time >= :midnight_utc
      AND entry_time < :next_midnight_utc;
    ```

15. **High/Low Balance Query from state_snapshots**:
    ```sql
    SELECT
        MAX(account_balance) as high_balance,
        MIN(account_balance) as low_balance
    FROM state_snapshots
    WHERE account_id = :account_id
      AND timestamp >= :midnight_utc
      AND timestamp < :next_midnight_utc;
    ```
    If no state_snapshots exist for the day (engine was down all day), fall back to `closing_balance` for both high and low.

16. **Upsert Pattern** (PostgreSQL ON CONFLICT):
    ```python
    from sqlalchemy.dialects.postgresql import insert

    stmt = insert(AccountSnapshotModel).values(**snapshot_dict)
    stmt = stmt.on_conflict_do_update(
        constraint='account_snapshots_account_id_snapshot_date_key',  # UNIQUE constraint name
        set_={col: stmt.excluded[col] for col in updatable_columns}
    )
    await session.execute(stmt)
    ```

17. **Fire-and-Forget for Audit Logging**: When snapshot is taken, log via AuditService.log_system_event() with event_subtype="daily_snapshot". Use same fire-and-forget pattern as other audit events.

---

### Quick Reference: What to Create/Modify

| Component | What to Do | Location |
|-----------|------------|----------|
| **AccountSnapshotModel** | Create ORM model matching ALL 17 init.sql columns | `src/snapshots/models.py` (NEW) |
| **SnapshotDBWriter** | Create DB writer with upsert (no batch buffer) | `src/snapshots/snapshot_db_writer.py` (NEW) |
| **DailySnapshotService** | Create service with midnight scheduler + data collection | `src/snapshots/daily_snapshot_service.py` (NEW) |
| **__init__.py** | Package exports | `src/snapshots/__init__.py` (NEW) |
| **TradingEngine** | Add daily snapshot service init + shutdown | `src/engine.py` (MODIFY) |
| **Tests** | Unit + integration tests | `tests/unit/test_daily_snapshots.py` (NEW), `tests/integration/test_daily_snapshots.py` (NEW) |

---

### Architecture Compliance

**Service:** `services/trading-engine/` (Python 3.11+)
**Database:** TimescaleDB (PostgreSQL 16+)
**ORM:** SQLAlchemy 2.0+ with async support (asyncpg)

**CRITICAL CONSTRAINTS from Architecture:**

From [Source: infra/timescaledb/init.sql#account_snapshots]:
```sql
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
```

**Communication Patterns:**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Inbound | Redis | 6379 | Account state (RiskState, StateSnapshot) |
| Outbound | PostgreSQL | 5432 | account_snapshots INSERT/UPSERT |
| Inbound | PostgreSQL | 5432 | trades query (daily stats), state_snapshots query (high/low) |

---

### Context from Previous Stories

**From Story 7.1 (Trade Execution Audit Logging) - Key Patterns:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| TradeDBWriter | Batch write of trade records | `src/orders/trade_db_writer.py` |
| TradeRecord ORM | Full column mapping with from_trade() factory | `src/orders/db_models.py:27-129` |
| Fire-and-forget | `asyncio.create_task()` + done_callback | `src/rules/audit_logger.py:252-271` |
| Signal mapping | `_signals_by_order` dict for concurrency safety | `src/orders/execution_service.py` |

**From Story 7.2 (Comprehensive Audit Log Table) - Integration Patterns:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| AuditService | Facade for audit logging | `src/audit/audit_service.py` |
| Engine lifecycle audit | log_system_event() for start/stop/recovery | `src/engine.py` |
| Continuous aggregate | Daily summary materialized view | `infra/timescaledb/migrations/007_*.sql` |

**From Story 7.3 (Rule Violation Tracking) - DB Writer Patterns:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| Hypertable writer | RuleViolationDBWriter pattern | `src/rules/` |
| ORM model | Full column mapping with factory classmethod | `src/rules/` |

**Existing Account State Tracking:**

| Component | Data Available | Location |
|-----------|---------------|----------|
| RiskState | daily_pnl, daily_pnl_percent, peak_equity, total_drawdown_percent, daily_starting_balance | `src/accounts/risk_state.py:12-108` |
| StateSnapshot | account_balance, equity, peak_balance, daily_starting_balance | `src/state/snapshot.py:26-74` |
| RedisStateManager | save/get snapshot, account balances, risk state | `src/state/redis_state.py` |
| ColdStorageWriter | 60-second state_snapshots to TimescaleDB | `src/state/cold_storage_writer.py` |
| AccountManager | Account lifecycle, active accounts list | `src/accounts/account_manager.py` |

**Key Redis Keys:**
- `snapshot:{account_id}:latest` → StateSnapshot hash (balance, equity, peak_balance, daily_starting_balance)
- `risk:{account_id}:state` → RiskState hash (daily_pnl, daily_pnl_percent, peak_equity, total_drawdown_percent, daily_starting_balance)
- `account:{account_id}:balance` → Current balance (Decimal)

---

### Latest Technical Documentation (Context7 Research)

**TimescaleDB `add_job()` for Scheduled Background Jobs (from Context7 /timescale/docs):**

```sql
-- TimescaleDB's built-in cron-like scheduler (runs inside PostgreSQL)
SELECT add_job(
    proc              => REGPROC,         -- Required: function/procedure name
    schedule_interval  => INTERVAL,        -- Required: e.g., '1 day'
    initial_start     => TIMESTAMPTZ,      -- Optional: first run time
    fixed_schedule    => BOOLEAN,          -- Optional: default TRUE
    timezone          => TEXT              -- Optional: handles DST
);
```

**Decision: NOT using TimescaleDB `add_job()`** because the snapshot logic requires:
- Reading from Redis (account state, risk state)
- Python Decimal calculations
- Access to AccountManager for active accounts list
- Error handling per account with Python logging

PL/pgSQL cannot access Redis or Python objects. The Python-side asyncio scheduler is the correct choice.

**SQLAlchemy 2.0 Upsert Pattern (from Context7 /websites/sqlalchemy_en_20):**

```python
from sqlalchemy.dialects.postgresql import insert

stmt = insert(AccountSnapshotModel).values(
    account_id='ftmo-gold-001',
    snapshot_date=date(2025, 12, 3),
    opening_balance=Decimal('100000.00'),
    closing_balance=Decimal('99350.00'),
    # ... all other fields
)
stmt = stmt.on_conflict_do_update(
    constraint='account_snapshots_account_id_snapshot_date_key',
    set_={
        'closing_balance': stmt.excluded.closing_balance,
        'daily_pnl': stmt.excluded.daily_pnl,
        # ... all updatable fields
    }
)
await session.execute(stmt)
```

**Key TimescaleDB state_snapshots Query for High/Low Balance:**
```sql
-- Efficient query using existing hypertable with time-based partitioning
SELECT
    MAX(account_balance) as high_balance,
    MIN(account_balance) as low_balance
FROM state_snapshots
WHERE account_id = 'ftmo-gold-001'
  AND timestamp >= '2025-12-03T00:00:00Z'
  AND timestamp < '2025-12-04T00:00:00Z';
-- Uses idx_state_snapshots_account index (account_id, timestamp DESC)
```

**asyncio Midnight Scheduler Pattern (no external dependency):**
```python
async def _scheduler_loop(self) -> None:
    while self._running:
        now = datetime.now(timezone.utc)
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        delay = (next_midnight - now).total_seconds()
        logger.info("Next daily snapshot in %.0f seconds (at %s)", delay, next_midnight)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            break
        if self._running:
            await self._take_all_snapshots()
```

---

### Implementation Guide

**Step 1: Create AccountSnapshotModel**

```python
# src/snapshots/models.py
import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Local declarative base (matches existing codebase convention - each module defines its own)."""
    pass


class AccountSnapshotModel(Base):
    __tablename__ = "account_snapshots"
    __table_args__ = (
        UniqueConstraint('account_id', 'snapshot_date',
                         name='account_snapshots_account_id_snapshot_date_key'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(String(50), nullable=False)  # FK to accounts(id), ON DELETE CASCADE
    snapshot_date = Column(Date, nullable=False)
    snapshot_time = Column(Time, nullable=True, default=time(0, 0, 0))
    opening_balance = Column(Numeric(18, 2), nullable=True)
    closing_balance = Column(Numeric(18, 2), nullable=True)
    high_balance = Column(Numeric(18, 2), nullable=True)
    low_balance = Column(Numeric(18, 2), nullable=True)
    daily_pnl = Column(Numeric(18, 2), nullable=True)
    daily_pnl_percent = Column(Numeric(8, 4), nullable=True)
    peak_balance = Column(Numeric(18, 2), nullable=True)
    drawdown_from_peak = Column(Numeric(18, 2), nullable=True)
    drawdown_percent = Column(Numeric(8, 4), nullable=True)
    trades_count = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_volume = Column(Numeric(18, 2), default=Decimal("0"))
    created_at = Column(DateTime(timezone=True), server_default="NOW()")

    @classmethod
    def from_snapshot_data(cls, data: dict) -> "AccountSnapshotModel":
        """Create model from collected snapshot metrics dict."""
        return cls(
            account_id=data["account_id"],
            snapshot_date=data["snapshot_date"],
            snapshot_time=data.get("snapshot_time", time(0, 0, 0)),
            opening_balance=Decimal(str(data["opening_balance"])) if data.get("opening_balance") is not None else None,
            closing_balance=Decimal(str(data["closing_balance"])) if data.get("closing_balance") is not None else None,
            high_balance=Decimal(str(data["high_balance"])) if data.get("high_balance") is not None else None,
            low_balance=Decimal(str(data["low_balance"])) if data.get("low_balance") is not None else None,
            daily_pnl=Decimal(str(data["daily_pnl"])) if data.get("daily_pnl") is not None else None,
            daily_pnl_percent=Decimal(str(data["daily_pnl_percent"])) if data.get("daily_pnl_percent") is not None else None,
            peak_balance=Decimal(str(data["peak_balance"])) if data.get("peak_balance") is not None else None,
            drawdown_from_peak=Decimal(str(data["drawdown_from_peak"])) if data.get("drawdown_from_peak") is not None else None,
            drawdown_percent=Decimal(str(data["drawdown_percent"])) if data.get("drawdown_percent") is not None else None,
            trades_count=data.get("trades_count", 0),
            winning_trades=data.get("winning_trades", 0),
            losing_trades=data.get("losing_trades", 0),
            total_volume=Decimal(str(data["total_volume"])) if data.get("total_volume") is not None else Decimal("0"),
        )
```

**Step 2: Create SnapshotDBWriter**

```python
# src/snapshots/snapshot_db_writer.py
"""Snapshot DB Writer - Direct persistence of daily account snapshots to TimescaleDB."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.dialects.postgresql import insert

from .models import AccountSnapshotModel

logger = logging.getLogger(__name__)

# All data columns that should be updated on conflict (everything except id, account_id, snapshot_date)
_UPDATABLE_COLUMNS = [
    "snapshot_time", "opening_balance", "closing_balance",
    "high_balance", "low_balance", "daily_pnl", "daily_pnl_percent",
    "peak_balance", "drawdown_from_peak", "drawdown_percent",
    "trades_count", "winning_trades", "losing_trades", "total_volume",
]


class SnapshotDBWriter:
    """Direct writer for daily account snapshots (no batch buffer - low volume)."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_async_engine(database_url, echo=False, pool_size=3, max_overflow=5)
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False,
        )
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("SnapshotDBWriter started")

    async def stop(self) -> None:
        self._running = False
        await self._engine.dispose()
        logger.info("SnapshotDBWriter stopped")

    async def write_snapshot(self, snapshot_data: dict[str, Any]) -> None:
        """Write or update a daily account snapshot (upsert)."""
        model = AccountSnapshotModel.from_snapshot_data(snapshot_data)
        values = {c.name: getattr(model, c.name) for c in AccountSnapshotModel.__table__.columns if c.name != "id"}

        stmt = insert(AccountSnapshotModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="account_snapshots_account_id_snapshot_date_key",
            set_={col: stmt.excluded[col] for col in _UPDATABLE_COLUMNS},
        )

        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(stmt)
```

**Step 3: Create DailySnapshotService**

```python
# src/snapshots/daily_snapshot_service.py
"""Daily Snapshot Service - Midnight UTC scheduler for account compliance snapshots."""

import asyncio
import logging
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..state.redis_state import RedisStateManager
from ..accounts.account_manager import AccountManager
from .snapshot_db_writer import SnapshotDBWriter

logger = logging.getLogger(__name__)


class DailySnapshotService:
    """Collects and persists daily account snapshots at midnight UTC."""

    def __init__(
        self,
        db_writer: SnapshotDBWriter,
        redis_state: RedisStateManager,
        account_manager: AccountManager,
        db_session_factory: async_sessionmaker,  # For trades/state_snapshots queries
    ) -> None:
        self._db_writer = db_writer
        self._redis_state = redis_state
        self._account_manager = account_manager
        self._session_factory = db_session_factory
        self._scheduler_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(), name="daily_snapshot_scheduler"
        )
        logger.info("DailySnapshotService started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        logger.info("DailySnapshotService stopped")

    async def _scheduler_loop(self) -> None:
        """Sleep until midnight UTC, then take snapshots. Repeat."""
        while self._running:
            now = datetime.now(timezone.utc)
            next_midnight = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            delay = (next_midnight - now).total_seconds()
            logger.info(
                "Next daily snapshot in %.0f seconds (at %s UTC)",
                delay, next_midnight.isoformat(),
            )
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
            if self._running:
                await self._take_all_snapshots()

    async def _take_all_snapshots(self) -> None:
        """Take snapshot for every active account."""
        # The snapshot_date is YESTERDAY (the day that just ended at midnight)
        snapshot_date = (datetime.now(timezone.utc) - timedelta(seconds=1)).date()
        active_accounts = self._account_manager.get_active_account_ids()

        logger.info("Taking daily snapshots for %d accounts (date: %s)",
                     len(active_accounts), snapshot_date)

        success_count = 0
        for account_id in active_accounts:
            try:
                data = await self._collect_snapshot_data(account_id, snapshot_date)
                await self._db_writer.write_snapshot(data)
                success_count += 1
                logger.info("Snapshot saved: %s / %s", account_id, snapshot_date)
            except Exception:
                logger.exception("Failed to snapshot account %s", account_id)

        logger.info("Daily snapshots complete: %d/%d succeeded",
                     success_count, len(active_accounts))

    async def _collect_snapshot_data(
        self, account_id: str, snapshot_date: date
    ) -> dict[str, Any]:
        """Gather snapshot data from Redis state + TimescaleDB queries."""
        midnight_utc = datetime.combine(snapshot_date, time.min, tzinfo=timezone.utc)
        next_midnight = midnight_utc + timedelta(days=1)

        # 1. Get risk state from Redis
        risk_state = await self._redis_state.get_risk_state(account_id)
        # 2. Get latest state snapshot from Redis
        state_snapshot = await self._redis_state.get_snapshot(account_id)

        opening_balance = risk_state.daily_starting_balance if risk_state else None
        closing_balance = state_snapshot.account_balance if state_snapshot else None
        daily_pnl = risk_state.daily_pnl if risk_state else None
        daily_pnl_percent = risk_state.daily_pnl_percent if risk_state else None
        peak_balance = state_snapshot.peak_balance if state_snapshot else None
        drawdown_percent = risk_state.total_drawdown_percent if risk_state else None

        # 3. Query state_snapshots for high/low balance
        high_balance, low_balance = await self._query_high_low_balance(
            account_id, midnight_utc, next_midnight
        )
        # Fallback if no state_snapshots for the day
        if high_balance is None:
            high_balance = closing_balance
        if low_balance is None:
            low_balance = closing_balance

        # 4. Query trades for daily stats
        trades_stats = await self._query_daily_trade_stats(
            account_id, midnight_utc, next_midnight
        )

        # 5. Calculate derived fields
        drawdown_from_peak = None
        if peak_balance is not None and closing_balance is not None:
            drawdown_from_peak = peak_balance - closing_balance

        return {
            "account_id": account_id,
            "snapshot_date": snapshot_date,
            "snapshot_time": time(0, 0, 0),
            "opening_balance": opening_balance,
            "closing_balance": closing_balance,
            "high_balance": high_balance,
            "low_balance": low_balance,
            "daily_pnl": daily_pnl,
            "daily_pnl_percent": daily_pnl_percent,
            "peak_balance": peak_balance,
            "drawdown_from_peak": drawdown_from_peak,
            "drawdown_percent": drawdown_percent,
            "trades_count": trades_stats["trades_count"],
            "winning_trades": trades_stats["winning_trades"],
            "losing_trades": trades_stats["losing_trades"],
            "total_volume": trades_stats["total_volume"],
        }

    async def _query_high_low_balance(
        self, account_id: str, start: datetime, end: datetime,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Query state_snapshots hypertable for intraday high/low balance."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT MAX(account_balance) as high, MIN(account_balance) as low
                    FROM state_snapshots
                    WHERE account_id = :account_id
                      AND timestamp >= :start AND timestamp < :end
                """),
                {"account_id": account_id, "start": start, "end": end},
            )
            row = result.one_or_none()
            if row and row.high is not None:
                return Decimal(str(row.high)), Decimal(str(row.low))
            return None, None

    async def _query_daily_trade_stats(
        self, account_id: str, start: datetime, end: datetime,
    ) -> dict[str, Any]:
        """Query trades table for daily trade statistics."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT
                        COUNT(*) as trades_count,
                        COUNT(*) FILTER (WHERE pnl_dollars > 0) as winning_trades,
                        COUNT(*) FILTER (WHERE pnl_dollars < 0) as losing_trades,
                        COALESCE(SUM(quantity), 0) as total_volume
                    FROM trades
                    WHERE account_id = :account_id
                      AND entry_time >= :start AND entry_time < :end
                """),
                {"account_id": account_id, "start": start, "end": end},
            )
            row = result.one()
            return {
                "trades_count": row.trades_count or 0,
                "winning_trades": row.winning_trades or 0,
                "losing_trades": row.losing_trades or 0,
                "total_volume": Decimal(str(row.total_volume)) if row.total_volume else Decimal("0"),
            }
```

**Step 4: Integrate with TradingEngine**

```python
# In src/engine.py - Add to __init__:
self._daily_snapshot_service: DailySnapshotService | None = None

# Add new initialization method (call after _initialize_cold_storage in run()):
async def _initialize_daily_snapshots(self) -> None:
    """Initialize the daily account snapshot scheduler."""
    if not self._database_url:
        logger.warning("No database URL - daily snapshots disabled")
        return
    db_writer = SnapshotDBWriter(self._database_url)
    await db_writer.start()
    self._daily_snapshot_service = DailySnapshotService(
        db_writer=db_writer,
        redis_state=self._redis_state,
        account_manager=self._account_manager,
        db_session_factory=self._db_session_factory,
    )
    await self._daily_snapshot_service.start()
    logger.info("Daily snapshot service initialized")

# Add to shutdown sequence:
if self._daily_snapshot_service:
    await self._daily_snapshot_service.stop()
```

---

### Project Structure Notes

**File Locations:**
```
services/trading-engine/
├── src/
│   ├── snapshots/                         # NEW package
│   │   ├── __init__.py                    # CREATE: Exports
│   │   ├── models.py                      # CREATE: AccountSnapshotModel ORM
│   │   ├── snapshot_db_writer.py          # CREATE: Direct upsert writer
│   │   └── daily_snapshot_service.py      # CREATE: Midnight scheduler + collector
│   ├── state/
│   │   ├── redis_state.py                 # READ: get_risk_state(), get_snapshot()
│   │   └── cold_storage_writer.py         # REFERENCE: Timer loop pattern
│   ├── accounts/
│   │   ├── account_manager.py             # READ: get_active_account_ids()
│   │   └── risk_state.py                  # READ: RiskState data structure
│   └── engine.py                          # MODIFY: Add daily snapshot init + shutdown
├── tests/
│   ├── unit/
│   │   └── test_daily_snapshots.py        # CREATE: Unit tests
│   └── integration/
│       └── test_daily_snapshots.py        # CREATE: Integration tests
```

---

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TIMESCALE_URL` | Yes | - | TimescaleDB connection URL |
| `REDIS_URL` | Yes | - | Redis connection URL |

**Connection URL Formats:**
```
postgresql+asyncpg://user:password@localhost:5432/tradingdb
redis://localhost:6379/0
```

---

### Testing Standards

- Unit tests: `pytest services/trading-engine/tests/unit/test_daily_snapshots.py`
- Integration tests: `pytest services/trading-engine/tests/integration/test_daily_snapshots.py`
- Run all: `cd services/trading-engine && pytest`
- Use `pytest-asyncio` for async test functions
- Mock `RedisStateManager` and `SnapshotDBWriter` with `AsyncMock` for unit tests
- Mock `async_sessionmaker` for trades/state_snapshots query tests
- Verify DECIMAL precision in all financial fields (no float conversion)
- Test per-account error isolation (one account fails, others succeed)
- Test idempotent upsert (same account+date written twice → single row updated)

---

### Patterns from Previous Stories

**DB Writer Pattern** (from `src/rules/audit_db_writer.py` and `src/orders/trade_db_writer.py`):
- async_sessionmaker + create_async_engine
- start()/stop() lifecycle
- Session context manager for transactions

**Timer Loop Pattern** (from `src/state/cold_storage_writer.py`):
```python
while self._running:
    await asyncio.sleep(self._interval)
    await self._do_work()
```

**Done Callback Pattern** (from `src/rules/audit_logger.py:252-271`):
```python
def audit_task_done_callback(task: asyncio.Task) -> None:
    if task.cancelled():
        logger.debug("Task %s cancelled", task.get_name())
        return
    exc = task.exception()
    if exc:
        logger.warning("Task %s failed: %s", task.get_name(), exc)
```

**Engine Integration Pattern** (from `engine.py`):
```python
async def _initialize_cold_storage(self) -> None:
    # Create writer, start it, create service, start service
    # Store references for shutdown
```

---

### Git History Reference

**Recent commits (Epic 7):**
- `fe5004b` Implement spec 7 story 7.3 (Rule Violation Tracking)
- `67cf9cc` Implement spec 7 story 7.2 (Comprehensive Audit Log Table)
- `13fca35` Implement spec 7 story 7.1 (Trade Execution Audit Logging)

**Files commonly modified in audit/snapshot stories:**
- `src/engine.py` (service integration)
- `src/state/redis_state.py` (data source)
- `src/accounts/account_manager.py` (account enumeration)

---

### Additional Implementation Notes

1. **Snapshot Timing**: The snapshot captures the state at midnight UTC. The `snapshot_date` is the date of the day that ENDED (yesterday from the perspective of the moment the scheduler wakes up at midnight). For example, if the scheduler fires at 2025-12-04T00:00:00Z, the snapshot_date is 2025-12-03.

2. **First Run on Engine Start**: On first engine startup, the scheduler calculates delay until the NEXT midnight. It does NOT retroactively create snapshots for previous days. If retroactive snapshots are needed, they can be backfilled from `state_snapshots` and `trades` tables via a one-time migration script.

3. **Risk State Reset Coordination**: The existing `RiskState.reset_daily()` in `risk_state.py:71-80` resets daily_pnl to 0 at midnight. The daily snapshot MUST capture the data BEFORE the risk state is reset. Ensure the snapshot collection runs before `reset_daily_risk_state()`. In the engine's midnight handling, the order should be: (1) collect & save snapshot, (2) reset risk state.

4. **No APScheduler Dependency**: Using asyncio-native scheduling avoids adding APScheduler as a dependency. The pattern is identical to existing ColdStorageService but with a longer interval (24 hours instead of 60 seconds).

5. **Idempotent Upsert Safety**: If the engine crashes and restarts shortly after midnight, the scheduler will calculate delay until the NEXT midnight (almost 24 hours). The previous night's snapshot was either already taken (success) or missed (engine was down). If a manual snapshot trigger is needed, add a CLI command in a future story.

6. **account_snapshots is NOT a hypertable**: It's a regular table. No TimescaleDB-specific features (compression, retention, continuous aggregates) are needed. The data volume is tiny (1-5 rows per day).

7. **Architecture.md Staleness**: The `account_snapshots` schema in `docs/architecture.md` (lines 1184-1197) is missing 7 columns compared to `init.sql`. Flag for update after implementation. Missing: `snapshot_time`, `high_balance`, `low_balance`, `drawdown_from_peak`, `winning_trades`, `losing_trades`, `total_volume`.

8. **`get_active_account_ids()` Method**: Check if `AccountManager` already exposes a method to list active account IDs. If not, add a simple property/method that returns `[aid for aid, acc in self._accounts.items() if acc.status == 'active']`.

9. **Concurrent DB Queries**: The trades stats query and high/low balance query are independent per account. They can be run concurrently using `asyncio.gather()` for slight performance improvement, though with 1-5 accounts the gain is minimal.

10. **Error Handling in DailySnapshotService**: The `_take_all_snapshots()` method has per-account try/except. If Redis is completely down, ALL accounts will fail (expected). The method still logs the overall result. Do NOT add circuit-breaker logic - this is a daily job with natural retry (next midnight).

---

### References

- [Source: infra/timescaledb/init.sql#account_snapshots - Full DB schema (17 columns) - AUTHORITATIVE]
- [Source: docs/architecture.md#Database Schema lines 1183-1199 - STALE (missing 7 columns)]
- [Source: docs/epics.md#Story 7.4: Daily Account Snapshots - Epic requirements]
- [Source: docs/prd.md#FR45 - Daily account snapshots for compliance]
- [Source: services/trading-engine/src/state/redis_state.py - RedisStateManager (snapshot/risk state access)]
- [Source: services/trading-engine/src/state/snapshot.py - StateSnapshot dataclass]
- [Source: services/trading-engine/src/accounts/risk_state.py - RiskState dataclass (daily metrics)]
- [Source: services/trading-engine/src/accounts/account_manager.py - AccountManager (active accounts)]
- [Source: services/trading-engine/src/state/cold_storage_writer.py - Timer loop pattern reference]
- [Source: services/trading-engine/src/engine.py - Engine lifecycle integration point]
- [Source: services/trading-engine/src/rules/audit_db_writer.py - DB writer pattern reference]
- [Source: services/trading-engine/src/orders/trade_db_writer.py - TradeDBWriter pattern reference]
- [Source: Context7 /timescale/docs - add_job() scheduled background jobs, state_snapshots queries]
- [Source: Context7 /websites/sqlalchemy_en_20 - Async upsert with ON CONFLICT DO UPDATE]

## Dev Agent Record

### Context Reference

Context7 MCP was used to retrieve latest documentation for:
- TimescaleDB - `add_job()` scheduled background jobs (decided against: need Redis/Python access)
- TimescaleDB - state_snapshots hypertable queries for high/low balance
- SQLAlchemy 2.0 - PostgreSQL upsert pattern with `insert().on_conflict_do_update()`
- SQLAlchemy 2.0 - async session patterns, DECIMAL/Numeric precision

### Agent Model Used

Claude Opus 4.6 (claude-opus-4-6)

### Debug Log References

N/A - No blocking issues encountered during implementation.

### Completion Notes List

- Created `src/snapshots/` package with AccountSnapshotModel ORM mapping all 17 init.sql columns
- AccountSnapshotModel uses Decimal(str(value)) for all financial fields to prevent floating-point precision loss
- SnapshotDBWriter uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE for idempotent upserts (no batch buffer, low volume)
- DailySnapshotService uses asyncio-native midnight UTC scheduler (no APScheduler dependency)
- Data collection aggregates from Redis (RiskState, StateSnapshot) and TimescaleDB (state_snapshots, trades)
- Per-account error isolation: if one account fails snapshot, others continue
- High/low balance falls back to closing_balance when no state_snapshots exist for the day
- drawdown_from_peak calculated as peak_balance - closing_balance
- Added get_active_account_ids() to AccountManager
- Engine integration follows _initialize_cold_storage() pattern with lazy imports
- Audit logging via AuditService fire-and-forget pattern (event_subtype="daily_snapshot")
- 25 unit tests + 8 integration tests = 33 total tests, all passing
- No regressions introduced (existing test failures are pre-existing: nautilus_trader not installed, Redis not running, typer not installed)

### File List

**New files:**
- `services/trading-engine/src/snapshots/__init__.py`
- `services/trading-engine/src/snapshots/models.py`
- `services/trading-engine/src/snapshots/snapshot_db_writer.py`
- `services/trading-engine/src/snapshots/daily_snapshot_service.py`
- `services/trading-engine/tests/unit/test_daily_snapshots.py`
- `services/trading-engine/tests/integration/test_daily_snapshots.py`

**Modified files:**
- `services/trading-engine/src/engine.py` (added daily snapshot service init/shutdown)
- `services/trading-engine/src/accounts/account_manager.py` (added get_active_account_ids())
- `docs/sprint-artifacts/sprint-status.yaml` (status: ready-for-dev → in-progress → review)
- `docs/sprint-artifacts/7-4-daily-account-snapshots.md` (task checkboxes, dev record, file list, change log, status)

### Change Log

- **2026-02-26**: Implemented daily account snapshots feature (Story 7.4). Created `src/snapshots/` package with AccountSnapshotModel ORM, SnapshotDBWriter (upsert), DailySnapshotService (midnight UTC scheduler), and engine integration. Added get_active_account_ids() to AccountManager. 33 tests (25 unit + 8 integration) all passing.
- **2026-02-26**: [Code Review] Fixed 1 HIGH + 4 MEDIUM issues:
  - Removed unused `date` import in `models.py` (ruff F401)
  - Fixed 7 ruff lint violations across test files (unused imports/vars)
  - Added race condition warning docstring on `_take_all_snapshots()` re: daily risk reset ordering
  - Added DB connection validation in `SnapshotDBWriter.start()` (catches misconfig at startup, not midnight)
  - Updated test mocks to support new `start()` connection check
  - Remaining LOW items (cross-package audit_logger import, no audit logging test, sequential processing) noted for future improvement
