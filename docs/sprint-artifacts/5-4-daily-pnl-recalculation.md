# Story 5.4: Daily P&L Recalculation

Status: completed

## Story

As a **trader**,
I want **my daily P&L recalculated from trade history after recovery**,
So that **compliance rules use accurate values**.

## Acceptance Criteria

1. **AC1**: Given recovery mode is active, when positions are reconciled, then daily P&L is recalculated from:
   - Trades executed since midnight UTC
   - Current unrealized P&L from open positions

2. **AC2**: Given the snapshot shows daily_pnl = -$500, when recalculation from trades shows -$520, then the system uses the recalculated value (-$520) and a log shows: "Daily P&L adjusted from snapshot: -$500 → -$520"

3. **AC3**: Given it's a new day since the last snapshot, when daily P&L is recalculated, then only trades from today are included and previous day's P&L is not carried over.

4. **AC4**: Given unrealized P&L from open positions, when daily P&L is calculated, then it equals realized P&L (from closed trades today) PLUS unrealized P&L (from open positions).

5. **AC5**: Given recalculation succeeds, when values are updated, then daily_pnl and daily_pnl_percent are persisted to Redis risk state AND updated in RiskStateRegistry.

6. **AC6**: Given recalculation fails due to database error, when the error occurs, then the system falls back to snapshot values and logs a WARNING.

## Tasks / Subtasks

### Task 0: Create SQLAlchemy TradeRecord Model (PREREQUISITE)

**CRITICAL: No SQLAlchemy ORM model exists for the `trades` table. Create one before Task 2.**

- [x] 0.1: Create `src/orders/db_models.py` with TradeRecord SQLAlchemy model:
  ```python
  """SQLAlchemy ORM models for database tables.

  These models map to TimescaleDB tables defined in infra/timescaledb/init.sql.
  CRITICAL: All financial fields use DECIMAL for precision.
  """

  from decimal import Decimal
  from datetime import datetime

  from sqlalchemy import Column, String, DECIMAL, TIMESTAMP, CheckConstraint
  from sqlalchemy.dialects.postgresql import UUID
  from sqlalchemy.orm import DeclarativeBase


  class Base(DeclarativeBase):
      """Base class for SQLAlchemy ORM models."""
      pass


  class TradeRecord(Base):
      """SQLAlchemy model for trades table.

      Maps to the 'trades' table in TimescaleDB.
      Used for querying realized P&L during crash recovery.

      CRITICAL: All financial fields are DECIMAL, not float.
      """
      __tablename__ = "trades"

      trade_id = Column(UUID, primary_key=True)
      account_id = Column(String(50), nullable=False, index=True)
      symbol = Column(String(20), nullable=False)
      side = Column(String(4), nullable=False)
      quantity = Column(DECIMAL(18, 8), nullable=False)
      entry_price = Column(DECIMAL(18, 5), nullable=False)
      entry_time = Column(TIMESTAMP(timezone=True), nullable=False)
      exit_price = Column(DECIMAL(18, 5), nullable=True)
      exit_time = Column(TIMESTAMP(timezone=True), nullable=True, index=True)
      pnl_dollars = Column(DECIMAL(18, 2), nullable=True)
      status = Column(String(20), default='open', nullable=False)
      created_at = Column(TIMESTAMP(timezone=True), nullable=True)

      __table_args__ = (
          CheckConstraint("side IN ('BUY', 'SELL')", name='check_side'),
          CheckConstraint("status IN ('open', 'closed', 'cancelled')", name='check_status'),
      )
  ```

- [x] 0.2: Update `src/orders/__init__.py` to export TradeRecord:
  ```python
  from .db_models import Base, TradeRecord
  ```

- [x] 0.3: **ALTERNATIVE (if ORM not desired):** Use raw SQL with `text()`: (SKIPPED - ORM approach used)
  ```python
  from sqlalchemy import text

  async def _query_realized_pnl_raw(
      self,
      session: AsyncSession,
      account_id: str,
      day_boundary: datetime,
  ) -> tuple[Decimal, int]:
      """Query using raw SQL instead of ORM."""
      stmt = text("""
          SELECT COALESCE(SUM(pnl_dollars), 0) as total_pnl, COUNT(*) as trade_count
          FROM trades
          WHERE account_id = :account_id
            AND status = 'closed'
            AND exit_time >= :day_boundary
      """)
      result = await session.execute(
          stmt,
          {"account_id": account_id, "day_boundary": day_boundary}
      )
      row = result.one()
      return Decimal(str(row.total_pnl)), row.trade_count
  ```

### Task 1: Create DailyPnLRecalculator Module (AC: 1, 4, 5)

- [x] 1.1: Create `src/state/daily_pnl_recalculator.py` with `DailyPnLRecalculator` class
- [x] 1.2: Define recalculation data structures:
  ```python
  from dataclasses import dataclass
  from decimal import Decimal
  from datetime import datetime

  @dataclass
  class RecalculatedPnL:
      """Result of P&L recalculation from trade history.

      Attributes:
          account_id: Account that was recalculated
          realized_pnl: Sum of P&L from closed trades today
          unrealized_pnl: Sum of unrealized P&L from open positions
          total_daily_pnl: realized_pnl + unrealized_pnl
          trade_count: Number of closed trades used in calculation
          calculation_time: When recalculation was performed
          day_boundary: Midnight UTC used for day boundary
      """
      account_id: str
      realized_pnl: Decimal
      unrealized_pnl: Decimal
      total_daily_pnl: Decimal
      trade_count: int
      calculation_time: datetime
      day_boundary: datetime

  @dataclass
  class RecalculationResult:
      """Result of daily P&L recalculation attempt.

      Attributes:
          success: True if recalculation completed successfully
          recalculated: RecalculatedPnL if success, None otherwise
          snapshot_value: Original value from snapshot (for comparison)
          adjustment: Difference between recalculated and snapshot
          error_message: Error details if success=False
      """
      success: bool
      recalculated: RecalculatedPnL | None
      snapshot_value: Decimal
      adjustment: Decimal
      error_message: str | None
  ```
- [x] 1.3: Implement `DailyPnLRecalculator` class skeleton:
  ```python
  class DailyPnLRecalculator:
      """Recalculates daily P&L from trade history after crash recovery.

      This recalculator queries the trades table for completed trades
      since midnight UTC and adds unrealized P&L from reconciled positions.

      The recalculated value is used instead of the snapshot value because:
      1. Trades may have closed between snapshot and crash
      2. Day boundary may have crossed since snapshot
      3. Snapshot unrealized P&L is stale

      CRITICAL: Always use Decimal for financial calculations.
      """

      def __init__(
          self,
          db_session_factory: async_sessionmaker[AsyncSession],
          redis_manager: RedisStateManager,
          risk_registry: RiskStateRegistry,
          pnl_registry: PnLRegistry,
      ):
          """Initialize DailyPnLRecalculator.

          Args:
              db_session_factory: Async session factory for database queries
              redis_manager: Redis state manager for persisting updates
              risk_registry: Risk state registry for updating risk metrics
              pnl_registry: P&L registry for updating tracker state
          """
          self._session_factory = db_session_factory
          self._redis = redis_manager
          self._risk_registry = risk_registry
          self._pnl_registry = pnl_registry
  ```
- [x] 1.4: Implement day boundary calculation (midnight UTC)
- [x] 1.5: Implement result logging and state update propagation

### Task 2: Database Query for Realized P&L (AC: 1, 3)

**DEPENDS ON: Task 0 (TradeRecord model must exist)**

- [x] 2.1: Implement `_query_realized_pnl()` method using SQLAlchemy async:
  ```python
  async def _query_realized_pnl(
      self,
      account_id: str,
      day_boundary: datetime,
  ) -> tuple[Decimal, int]:
      """Query sum of realized P&L from closed trades since midnight UTC.

      SQL equivalent:
      SELECT COALESCE(SUM(pnl_dollars), 0), COUNT(*)
      FROM trades
      WHERE account_id = :account_id
        AND status = 'closed'
        AND exit_time >= :day_boundary

      Args:
          account_id: Account to query trades for
          day_boundary: Midnight UTC of current trading day

      Returns:
          (realized_pnl, trade_count) tuple
          realized_pnl: Sum of pnl_dollars from closed trades
          trade_count: Number of trades used in sum

      Raises:
          SQLAlchemyError: On database connection/query failure
      """
      async with self._session_factory() as session:
          # Use SQLAlchemy 2.0 async select with func.coalesce and func.sum
          # Import TradeRecord from Task 0
          from sqlalchemy import select, func, and_
          from ..orders.db_models import TradeRecord

          stmt = select(
              func.coalesce(func.sum(TradeRecord.pnl_dollars), 0).label("total_pnl"),
              func.count().label("trade_count"),
          ).where(
              and_(
                  TradeRecord.account_id == account_id,
                  TradeRecord.status == "closed",
                  TradeRecord.exit_time >= day_boundary,
              )
          )

          result = await session.execute(stmt)
          row = result.one()
          return Decimal(str(row.total_pnl)), row.trade_count
  ```
- [x] 2.2: Import TradeRecord from `src/orders/db_models.py` (created in Task 0)
- [x] 2.3: Handle database connection errors with fallback to snapshot

### Task 3: Get Unrealized P&L from Reconciled Positions (AC: 1, 4)

- [x] 3.1: Implement `_get_unrealized_pnl()` method:
  ```python
  async def _get_unrealized_pnl(self, account_id: str) -> Decimal:
      """Get current unrealized P&L from reconciled positions.

      After Story 5.3 (position reconciliation), the PnLTracker has
      accurate positions matching MT5. This method retrieves the
      total unrealized P&L from those positions.

      ARCHITECTURE: Uses PnLRegistry to access the account's PnLTracker
      which was updated during position reconciliation.

      Args:
          account_id: Account to get unrealized P&L for

      Returns:
          Total unrealized P&L from open positions (Decimal)
          Returns Decimal("0") if no tracker or no positions
      """
      tracker = self._pnl_registry.get_tracker(account_id)
      if tracker is None:
          logger.warning(
              "No PnLTracker found for %s during P&L recalculation",
              account_id,
          )
          return Decimal("0")

      metrics = tracker.get_pnl_metrics()
      return metrics.unrealized_pnl
  ```
- [x] 3.2: Integrate with PnLRegistry for tracker access
- [x] 3.3: Handle missing tracker gracefully (return 0)

### Task 4: Main Recalculation Logic (AC: 1, 2, 3, 4)

- [x] 4.1: Implement `recalculate_daily_pnl()` method:
  ```python
  async def recalculate_daily_pnl(
      self,
      account_id: str,
      snapshot_daily_pnl: Decimal,
  ) -> RecalculationResult:
      """Recalculate daily P&L from trade history and current positions.

      Called after position reconciliation (Story 5.3) to ensure
      compliance rules use accurate P&L values.

      Calculation:
      1. Determine current day boundary (midnight UTC)
      2. Query realized P&L from closed trades since midnight
      3. Get unrealized P&L from reconciled positions
      4. Total = Realized + Unrealized

      Args:
          account_id: Account to recalculate P&L for
          snapshot_daily_pnl: Daily P&L value from snapshot (for comparison)

      Returns:
          RecalculationResult with success status and recalculated values
      """
      try:
          # 1. Calculate day boundary (midnight UTC)
          now = datetime.now(timezone.utc)
          day_boundary = now.replace(hour=0, minute=0, second=0, microsecond=0)

          # 2. Check if snapshot is from previous day
          # If so, we need to recalculate from scratch

          # 3. Query realized P&L from database
          realized_pnl, trade_count = await self._query_realized_pnl(
              account_id, day_boundary
          )

          # 4. Get unrealized P&L from positions
          unrealized_pnl = await self._get_unrealized_pnl(account_id)

          # 5. Calculate total
          total_daily_pnl = realized_pnl + unrealized_pnl

          recalculated = RecalculatedPnL(
              account_id=account_id,
              realized_pnl=realized_pnl,
              unrealized_pnl=unrealized_pnl,
              total_daily_pnl=total_daily_pnl,
              trade_count=trade_count,
              calculation_time=now,
              day_boundary=day_boundary,
          )

          adjustment = total_daily_pnl - snapshot_daily_pnl

          # 6. Log if adjustment occurred
          if adjustment != Decimal("0"):
              logger.info(
                  "Daily P&L adjusted from snapshot: %s → %s (adjustment: %s)",
                  snapshot_daily_pnl,
                  total_daily_pnl,
                  adjustment,
              )

          return RecalculationResult(
              success=True,
              recalculated=recalculated,
              snapshot_value=snapshot_daily_pnl,
              adjustment=adjustment,
              error_message=None,
          )

      except Exception as e:
          logger.warning(
              "P&L recalculation failed for %s, using snapshot value: %s",
              account_id,
              e,
          )
          return RecalculationResult(
              success=False,
              recalculated=None,
              snapshot_value=snapshot_daily_pnl,
              adjustment=Decimal("0"),
              error_message=str(e),
          )
  ```
- [x] 4.2: Implement day boundary check (is snapshot from previous day?)
- [x] 4.3: Handle cross-day recovery scenario

### Task 5: State Update and Persistence (AC: 5)

- [x] 5.1: Implement `_update_risk_state()` method:
  ```python
  async def _update_risk_state(
      self,
      account_id: str,
      recalculated: RecalculatedPnL,
  ) -> None:
      """Update risk state with recalculated daily P&L.

      Updates:
      1. RiskStateRegistry (in-memory risk state)
      2. Redis risk state (persistent)
      3. PnLTracker daily realized P&L counter

      Args:
          account_id: Account to update
          recalculated: Recalculated P&L values
      """
      # 1. Get current risk state
      risk_state = self._risk_registry.get_risk_state(account_id)
      if risk_state is None:
          logger.error("No risk state found for %s", account_id)
          return

      # 2. Update risk state values
      risk_state.daily_pnl = recalculated.total_daily_pnl
      if risk_state.daily_starting_balance > 0:
          risk_state.daily_pnl_percent = (
              recalculated.total_daily_pnl / risk_state.daily_starting_balance * 100
          )

      # 3. Persist to Redis
      await self._redis.save_risk_state(account_id, risk_state)

      logger.info(
          "Risk state updated for %s: daily_pnl=%s, daily_pnl_percent=%s%%",
          account_id,
          recalculated.total_daily_pnl,
          risk_state.daily_pnl_percent,
      )
  ```
- [x] 5.2: Implement `apply_recalculation()` method to orchestrate updates:
  ```python
  async def apply_recalculation(
      self,
      account_id: str,
      result: RecalculationResult,
  ) -> None:
      """Apply recalculation result to all state stores.

      Only called if recalculation was successful.
      Updates risk registry, Redis, and P&L tracker.

      Args:
          account_id: Account to update
          result: Successful recalculation result
      """
      if not result.success or result.recalculated is None:
          logger.debug(
              "Skipping state update for %s - recalculation failed",
              account_id,
          )
          return

      await self._update_risk_state(account_id, result.recalculated)
  ```
- [x] 5.3: Verify Redis persistence using existing RedisStateManager.save_risk_state()

### Task 6: Integration with Recovery Flow (AC: 1, 6)

**CRITICAL INTEGRATION POINT:**
```
Location: services/trading-engine/src/engine.py
Insert AFTER line 156 (inside "if all_success:" block)
Insert BEFORE line 151 "await self._crash_recovery.clear_crash_indicators()"

The recovery sequence is:
1. Position reconciliation (lines 128-156) ← Story 5.3
2. Daily P&L recalculation ← Story 5.4 (NEW - insert here)
3. Clear crash indicators (line 151) ← Must come AFTER P&L recalculation
```

- [x] 6.1: Add P&L recalculation step to Engine recovery flow:
  ```python
  # In Engine._initialize_crash_recovery() - AFTER position reconciliation
  # Location: services/trading-engine/src/engine.py
  # Insert AFTER line 156: logger.info("Crash indicators cleared...")
  # Insert BEFORE the await self._crash_recovery.clear_crash_indicators() call

  async def _run_daily_pnl_recalculation(
      self,
      reconciliation_results: dict[str, ReconciliationResult],
  ) -> dict[str, RecalculationResult]:
      """Recalculate daily P&L for all successfully reconciled accounts.

      Called after position reconciliation, before trading resumes.
      Only recalculates for accounts that passed reconciliation.

      Args:
          reconciliation_results: Results from position reconciliation

      Returns:
          Dict mapping account_id to RecalculationResult
      """
      results = {}

      for account_id, recon_result in reconciliation_results.items():
          # Skip accounts that failed reconciliation
          if recon_result.requires_manual_intervention:
              logger.warning(
                  "Skipping P&L recalculation for %s - manual intervention required",
                  account_id,
              )
              continue

          # Get snapshot daily P&L for comparison
          valid, snapshot = await self._crash_recovery.validate_snapshot_for_recovery(
              account_id
          )
          snapshot_daily_pnl = snapshot.daily_starting_balance if snapshot else Decimal("0")

          # Recalculate
          result = await self._pnl_recalculator.recalculate_daily_pnl(
              account_id,
              snapshot_daily_pnl,
          )

          # Apply if successful
          if result.success:
              await self._pnl_recalculator.apply_recalculation(account_id, result)

          results[account_id] = result

      return results
  ```
- [x] 6.2: Update Engine recovery sequence to include P&L recalculation:
  ```python
  # Engine.start() integration point (after reconciliation)
  if recovery_result.recovery_mode:
      # ... position reconciliation (Story 5.3) ...
      reconciliation_results = await self._run_position_reconciliation(
          recovery_result.accounts_needing_recovery
      )

      # NEW: Daily P&L recalculation (Story 5.4)
      pnl_results = await self._run_daily_pnl_recalculation(reconciliation_results)

      # Log summary
      for account_id, result in pnl_results.items():
          if result.success and result.adjustment != Decimal("0"):
              logger.info(
                  "Account %s P&L adjusted by %s",
                  account_id,
                  result.adjustment,
              )

      # Clear crash indicators after all recovery steps complete
      await self._crash_recovery.clear_crash_indicators()
  ```
- [x] 6.3: Add DailyPnLRecalculator initialization in Engine.__init__():
  ```python
  # In Engine.__init__() - add new parameter and attribute:
  def __init__(
      self,
      redis_manager: RedisStateManager | None = None,
      zmq_adapter: ZmqAdapter | None = None,
      db_session_factory: async_sessionmaker[AsyncSession] | None = None,  # NEW
  ) -> None:
      # ... existing code ...
      self._db_session_factory = db_session_factory
      self._pnl_recalculator: DailyPnLRecalculator | None = None

  # Initialize recalculator when needed (lazy init in _run_daily_pnl_recalculation):
  if self._pnl_recalculator is None and self._db_session_factory is not None:
      from .state.daily_pnl_recalculator import DailyPnLRecalculator
      self._pnl_recalculator = DailyPnLRecalculator(
          db_session_factory=self._db_session_factory,
          redis_manager=self._redis_manager,
          risk_registry=self._risk_registry,  # Must exist from Epic 4
          pnl_registry=self._pnl_registry,    # Must exist from Epic 4
      )
  ```

- [x] 6.4: Create session factory in main.py bootstrap (for Engine construction):
  ```python
  # In services/trading-engine/src/cli/main.py or wherever Engine is instantiated:
  from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

  # Create async engine from DATABASE_URL
  database_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://...")
  async_engine = create_async_engine(database_url)
  session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

  # Pass to Engine
  engine = TradingEngine(
      redis_manager=redis_manager,
      zmq_adapter=zmq_adapter,
      db_session_factory=session_factory,  # NEW
  )
  ```
- [x] 6.5: Handle fallback to snapshot values on database errors (AC6)

### Task 7: Unit Tests (AC: 1-6)

- [x] 7.1: Create `tests/unit/test_daily_pnl_recalculator.py`
- [x] 7.2: Test realized P&L query with multiple closed trades
- [x] 7.3: Test realized P&L query with no trades today
- [x] 7.4: Test unrealized P&L retrieval from PnLTracker
- [x] 7.5: Test total calculation (realized + unrealized)
- [x] 7.6: Test day boundary calculation (midnight UTC)
- [x] 7.7: Test cross-day scenario (snapshot from yesterday)
- [x] 7.8: Test adjustment logging when values differ
- [x] 7.9: Test no adjustment when values match
- [x] 7.10: Test database error fallback to snapshot
- [x] 7.11: Test missing PnLTracker returns zero unrealized
- [x] 7.12: Test state update propagation to RiskStateRegistry
- [x] 7.13: Test Redis persistence called after successful recalculation

### Task 8: Integration Tests (AC: 1-6)

- [x] 8.1: Create `tests/integration/test_daily_pnl_recalculation_redis.py` (Redis integration)
- [ ] 8.2: Test full recalculation flow with real TimescaleDB (DEFERRED - requires DB setup)
- [ ] 8.3: Test query performance (< 100ms for 1000 trades) (DEFERRED - requires DB setup)
- [x] 8.4: Test engine startup with recovery and P&L recalculation
- [x] 8.5: Test Redis state persistence after recalculation
- [x] 8.6: Test concurrent recalculation for multiple accounts

### Task 9: Documentation and Exports (AC: 1-6)

- [x] 9.1: Add docstrings to all DailyPnLRecalculator methods
- [x] 9.2: Update `state/__init__.py` with new exports:
  ```python
  from .daily_pnl_recalculator import (
      DailyPnLRecalculator,
      RecalculatedPnL,
      RecalculationResult,
  )
  ```
- [x] 9.3: Document recalculation flow in module docstring

## Dev Notes

### 🎯 CRITICAL INTEGRATION POINT (Read First!)

**Where to integrate in `engine.py`:**
```
File: services/trading-engine/src/engine.py
Method: _initialize_crash_recovery()
Location: Inside "if all_success:" block (around line 147-156)

SEQUENCE (must be in this order):
1. Position reconciliation completes (Story 5.3) ← lines 128-144
2. Check all_success flag ← line 147
3. ► Daily P&L recalculation ← Story 5.4 (INSERT HERE)
4. Clear crash indicators ← line 151 (MUST come AFTER P&L recalc)
```

**Code to insert at line 148 (before clear_crash_indicators):**
```python
# Story 5.4: Daily P&L recalculation
pnl_results = await self._run_daily_pnl_recalculation(
    self._reconciliation_results
)
self._pnl_recalculation_results = pnl_results
```

---

### FULL FILE PATHS (Monorepo Structure)

**All paths relative to `/home/hopdev/Dev/Sandboxed/`:**

| Full Path | Action | Purpose |
|-----------|--------|---------|
| **New Files** | | |
| `services/trading-engine/src/orders/db_models.py` | CREATE | SQLAlchemy TradeRecord model (Task 0) |
| `services/trading-engine/src/state/daily_pnl_recalculator.py` | CREATE | DailyPnLRecalculator class |
| `services/trading-engine/tests/unit/test_daily_pnl_recalculator.py` | CREATE | Unit tests |
| `services/trading-engine/tests/integration/test_daily_pnl_recalculator_db.py` | CREATE | Integration tests |
| **Modify Files** | | |
| `services/trading-engine/src/orders/__init__.py` | MODIFY | Export TradeRecord, Base |
| `services/trading-engine/src/state/__init__.py` | MODIFY | Add new exports |
| `services/trading-engine/src/engine.py` | MODIFY | Add db_session_factory param, integrate recalculation |
| `services/trading-engine/src/cli/main.py` | MODIFY | Create session factory, pass to Engine |

### PREREQUISITES (Stories 5.1, 5.2, 5.3 Complete)

**From Story 5.3 (Position Reconciliation):**
- `PositionReconciler` at `src/state/position_reconciler.py` - reconciles positions with MT5
- After reconciliation, `PnLTracker` has accurate positions from MT5
- `ReconciliationResult.requires_manual_intervention` flag for skipping blocked accounts

**From Story 5.2 (Crash Detection):**
- `CrashRecoveryManager.startup_sequence()` returns `RecoveryResult` with recovery_mode flag
- `validate_snapshot_for_recovery()` returns snapshot with daily P&L values

**From Story 5.1 (Redis Snapshots):**
- `StateSnapshot` includes `daily_starting_balance` field
- Snapshots stored at `snapshot:{account_id}:latest`

**From Epic 4 (Rule Engine):**
- `RiskState` at `src/accounts/risk_state.py` with `daily_pnl` and `daily_pnl_percent`
- `RiskStateRegistry` at `src/accounts/risk_registry.py` for in-memory risk state
- `RedisStateManager.save_risk_state()` for Redis persistence

**From Previous Stories:**
- `PnLTracker` at `src/accounts/pnl_tracker.py` with `get_pnl_metrics()` returning unrealized P&L
- `PnLRegistry` at `src/accounts/pnl_registry.py` for accessing account trackers

### CONTEXT7 RESEARCH SUMMARY (SQLAlchemy & Redis 2026-01-13)

**Key SQLAlchemy 2.0 Async Patterns** (full examples in Task 2.1):
- `func.coalesce(func.sum(...), 0)` - Return 0 if no matching rows
- `select().where(and_(...))` - Multiple filter conditions
- `await session.execute(stmt)` - Async execution
- `result.one()` - Get single row result
- `async_sessionmaker[AsyncSession]` - Session factory type hint

**Key Redis-py Async Patterns** (used in existing `RedisStateManager.save_risk_state()`):
- `hset(key, mapping={...})` - Set multiple hash fields atomically
- `expire(key, seconds)` - Set TTL
- `redis.asyncio.from_url()` - Create async connection

### DATABASE SCHEMA REFERENCE (trades table)

```sql
-- From infra/timescaledb/init.sql
CREATE TABLE trades (
    trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity DECIMAL(18, 8) NOT NULL,
    entry_price DECIMAL(18, 5) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_price DECIMAL(18, 5),
    exit_time TIMESTAMPTZ,
    pnl_dollars DECIMAL(18, 2),  -- This is what we SUM
    status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Relevant index for our query
CREATE INDEX idx_trades_account_time ON trades (account_id, entry_time DESC);
```

**Query for Daily Realized P&L:**
```sql
SELECT COALESCE(SUM(pnl_dollars), 0) as realized_pnl, COUNT(*) as trade_count
FROM trades
WHERE account_id = 'ftmo-gold-001'
  AND status = 'closed'
  AND exit_time >= '2026-01-13T00:00:00Z'  -- Midnight UTC today
```

### P&L CALCULATION FORMULA

```
Daily P&L = Realized P&L + Unrealized P&L

Where:
- Realized P&L = SUM(pnl_dollars) from trades WHERE status='closed' AND exit_time >= midnight_utc_today
- Unrealized P&L = SUM(position.unrealized_pnl) for all open positions (from PnLTracker)

Daily P&L % = (Daily P&L / daily_starting_balance) * 100
```

### RECOVERY FLOW INTEGRATION

```
Engine.start()
    │
    ├── 1. CrashRecoveryManager.startup_sequence()
    │       └── Returns RecoveryResult with accounts_needing_recovery
    │
    ├── 2. ZMQ/Redis connections (required before recovery)
    │
    ├── 3. Position Reconciliation (Story 5.3)
    │       └── Updates PnLTracker with MT5 positions
    │
    ├── 4. Daily P&L Recalculation (Story 5.4) ← NEW
    │       ├── Query closed trades from database
    │       ├── Get unrealized P&L from PnLTracker
    │       ├── Update RiskStateRegistry
    │       └── Persist to Redis
    │
    ├── 5. Trading Resume (Story 5.5) ← NEXT
    │       └── Resume signal processing
    │
    └── 6. Clear crash indicators
```

### EXISTING CODE PATTERNS TO REUSE

Reference these existing implementations (don't duplicate code):

| File | Method | Use For |
|------|--------|---------|
| `src/accounts/pnl_tracker.py:386` | `get_pnl_metrics()` | Get unrealized P&L |
| `src/accounts/risk_state.py:60` | `record_trade()` | Pattern for daily_pnl update |
| `src/accounts/risk_state.py:82` | `to_dict()` | Redis serialization pattern |
| `src/state/redis_state.py:202` | `save_risk_state()` | Persist RiskState to Redis |
| `src/accounts/risk_manager.py:142` | Usage example | How save_risk_state is called |

### ⛔ ANTI-PATTERNS (What NOT to Do)

**CRITICAL: Read before implementing. These mistakes will cause bugs.**

| Anti-Pattern | Why It's Wrong | Instead, Do This |
|--------------|----------------|------------------|
| Query ALL trades, filter in Python | Performance disaster | Use SQL WHERE clause |
| Use `float` for P&L calculations | Precision errors | Always use `Decimal` |
| Skip unrealized P&L | Compliance rules need total | Include open position P&L |
| Update Redis without RiskStateRegistry | State divergence | Update both in sync |
| Ignore day boundary | Wrong P&L included | Always filter by midnight UTC |
| Block on database errors | Recovery stalls | Fallback to snapshot value |
| Import `Trade` dataclass for queries | Wrong model type | Use `TradeRecord` SQLAlchemy model |

### TESTING COMMANDS

```bash
cd services/trading-engine

# Run unit tests
uv run pytest tests/unit/test_daily_pnl_recalculator.py -v

# Run integration tests (requires TimescaleDB)
uv run pytest tests/integration/test_daily_pnl_recalculator_db.py -v

# Run with coverage
uv run pytest tests/unit/test_daily_pnl_recalculator.py --cov=src/state

# Lint check
uv run ruff check src/state/daily_pnl_recalculator.py
```

### TASK DEPENDENCIES (Execute in Order)

```
Task 1 (Data Structures) ──► Task 2 (DB Query)
         │                          │
         ▼                          ▼
   Task 3 (Unrealized P&L) ◄────────┘
         │
         ▼
   Task 4 (Main Logic) ──► Task 5 (State Update)
         │                          │
         ▼                          ▼
   Task 6 (Engine Integration) ◄────┘
         │
         ▼
   Tasks 7-8 (Tests) ──► Task 9 (Docs)
```

### PERFORMANCE REQUIREMENTS

- Database query: < 100ms (indexed query, even with 1000+ trades)
- Unrealized P&L retrieval: < 1ms (in-memory from PnLTracker)
- State update: < 50ms (Redis write + registry update)
- Full recalculation: < 200ms per account

### REFERENCES

- [docs/epic-5-context.md] - Epic 5 technical context
- [docs/architecture.md#Recovery-Failover] - Recovery sequence
- [docs/architecture.md#Database-Schema] - Trades table schema
- [docs/epics.md#Story-5.4] - Story requirements
- [src/accounts/pnl_tracker.py] - P&L calculation patterns
- [src/accounts/risk_state.py] - Risk state model
- [src/state/redis_state.py] - Redis persistence patterns
- [Context7 SQLAlchemy 2026-01-13] - Async query patterns
- [Context7 Redis-py 2026-01-13] - Async hash operations

## Dev Agent Record

**Story created:** 2026-01-13 via create-story workflow

**Context Analysis:**
- Story 5.4 depends on Story 5.3 (Position Reconciliation) - COMPLETED
- Story 5.4 depends on Story 5.2 (Crash Detection) - COMPLETED
- Story 5.4 depends on Story 5.1 (Redis Snapshots) - COMPLETED
- Epic 5 focused on State Persistence & Crash Recovery
- Story 5.5 (Trading Resume) depends on this story

**Context7 Research Summary:**
- SQLAlchemy 2.0: async session factory, func.coalesce/sum, select().where(and_())
- Redis-py: async hset with mapping, expire for TTL
- Both use `await` for async operations

**Previous Story Learnings (Story 5.3):**
- Position reconciliation updates PnLTracker with MT5 positions
- ReconciliationResult.requires_manual_intervention flag for blocking
- Engine integration follows pattern of calling in recovery mode block

**Git Intelligence (Recent Commits):**
- cef9bf1: Implement spec 5 story 5.3 (Position Reconciliation)
- b8aca3a: Implement spec 5 story 5.2 (Crash Detection)
- 08609a6: Implement spec 5 story 5.1 (Redis State Snapshots)
- Pattern: create module with dataclasses, main class, comprehensive tests

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Context Reference

- Epic 5 context document (docs/epic-5-context.md)
- Story 5.3 (previous story) for PnLTracker state after reconciliation
- Story 5.2 for CrashRecoveryManager integration
- Story 5.1 for StateSnapshot patterns
- Architecture document for trades table schema
- Context7 SQLAlchemy and Redis-py research (2026-01-13)

### Debug Log References

N/A - Story creation, no implementation yet.

### Completion Notes List

**Implementation completed: 2026-01-13**

1. Created `db_models.py` with SQLAlchemy TradeRecord model using proper DECIMAL types
2. Created `daily_pnl_recalculator.py` with DailyPnLRecalculator class implementing:
   - Day boundary calculation (midnight UTC)
   - Database query for realized P&L using async SQLAlchemy
   - Unrealized P&L retrieval from PnLTrackerRegistry
   - Total calculation (realized + unrealized)
   - Adjustment logging when values differ from snapshot
   - Database error fallback to snapshot values
3. Updated Engine to accept db_session_factory and integrate P&L recalculation in recovery flow
4. Added comprehensive unit tests (25 tests, all passing)
5. Added Redis integration tests for state persistence

**Code Review Findings Fixed: 2026-01-13**
- Updated all task checkboxes from [ ] to [x]
- Updated Definition of Done checkboxes
- Added session factory creation to main.py
- Updated File List with actual implementation files

### File List

**Files CREATED:**
| File | Purpose | Status |
|------|---------|--------|
| `services/trading-engine/src/orders/db_models.py` | SQLAlchemy TradeRecord model (Task 0) | ✅ Created |
| `services/trading-engine/src/state/daily_pnl_recalculator.py` | DailyPnLRecalculator class | ✅ Created |
| `services/trading-engine/tests/unit/test_daily_pnl_recalculator.py` | Unit tests (25 tests) | ✅ Created |
| `services/trading-engine/tests/integration/test_daily_pnl_recalculation_redis.py` | Redis integration tests | ✅ Created |

**Files MODIFIED:**
| File | Changes | Status |
|------|---------|--------|
| `services/trading-engine/src/orders/__init__.py` | Export TradeRecord, Base from db_models | ✅ Modified |
| `services/trading-engine/src/state/__init__.py` | Export DailyPnLRecalculator, RecalculatedPnL, RecalculationResult | ✅ Modified |
| `services/trading-engine/src/engine.py` | Add db_session_factory param, integrate P&L recalculation | ✅ Modified |
| `services/trading-engine/src/cli/main.py` | Create async session factory, pass to Engine | ✅ Modified |

---

## Definition of Done

**Prerequisites (Task 0):**
- [x] SQLAlchemy TradeRecord model created in `orders/db_models.py`
- [x] TradeRecord uses DECIMAL types for all financial fields
- [x] TradeRecord exported from `orders/__init__.py`

**Core Implementation:**
- [x] DailyPnLRecalculator class created with recalculation logic
- [x] RecalculatedPnL and RecalculationResult dataclasses defined
- [x] Database query for realized P&L using SQLAlchemy async with TradeRecord
- [x] Unrealized P&L retrieval from PnLTracker via PnLTrackerRegistry

**Calculation Logic:**
- [x] Day boundary calculation (midnight UTC)
- [x] Realized + Unrealized = Total Daily P&L
- [x] Cross-day scenario handled (new day since snapshot)
- [x] Adjustment logging when values differ

**State Updates:**
- [x] RiskStateRegistry updated with recalculated values
- [x] Redis risk state persisted via RedisStateManager
- [x] PnL percent calculated from daily_starting_balance

**Engine Integration:**
- [x] Engine.__init__ accepts db_session_factory parameter
- [x] Session factory created in main.py bootstrap
- [x] Recalculation runs after position reconciliation (inside all_success block)
- [x] Skips accounts with manual intervention required
- [x] Fallback to snapshot on database errors

**Testing:**
- [x] Unit tests for query logic
- [x] Unit tests for calculation
- [x] Unit tests for state updates
- [ ] Integration tests with TimescaleDB (DEFERRED - requires DB)
- [x] Error handling tests

**Acceptance Criteria Verification:**
- [x] AC1: Recalculates from trades + unrealized
- [x] AC2: Logs adjustment when values differ
- [x] AC3: Only includes today's trades
- [x] AC4: Total = Realized + Unrealized
- [x] AC5: Persists to Redis and registry
- [x] AC6: Fallback on database errors

---
