# Story 5.1: Redis State Snapshots

Status: Done

## Story

As a **trader**,
I want **the engine to snapshot account state every 5 seconds**,
So that **I have recent recovery data if the system crashes**.

## Acceptance Criteria

1. **AC1**: Given the engine is running with active accounts, when 5 seconds elapse, then a state snapshot is created for each account containing: positions, pending_orders, account_balance, equity, peak_balance, daily_starting_balance, and timestamp.

2. **AC2**: Given a snapshot is created, when I examine the Redis hash, then it is stored at key `snapshot:{account_id}:latest` with fields matching the snapshot data structure.

3. **AC3**: Given a snapshot is stored, when I check its TTL, then it expires in 1 hour (3600 seconds).

4. **AC4**: Given a snapshot is created, when I verify data integrity, then a SHA256 checksum field is included that validates all other fields.

5. **AC5**: Given multiple accounts are running, when a snapshot cycle executes, then all accounts are snapshotted concurrently with `asyncio.gather()`.

6. **AC6**: Given a snapshot from Redis, when I call `StateSnapshot.from_dict()`, then I can reconstruct the complete snapshot object with validated checksum.

7. **AC7**: Given snapshot interval timing, when I measure snapshot duration, then single account snapshot completes in under 10ms.

## Tasks / Subtasks

### Task 1: Create StateSnapshot Model (AC: 1, 4, 6)

- [x] 1.1: Create `src/state/snapshot.py` with `StateSnapshot` dataclass
- [x] 1.2: Define snapshot fields:
  ```python
  @dataclass
  class StateSnapshot:
      account_id: str
      timestamp: datetime
      positions: list[dict[str, Any]]  # List of position dicts
      pending_orders: list[dict[str, Any]]  # List of pending order dicts
      account_balance: Decimal
      equity: Decimal
      peak_balance: Decimal
      daily_starting_balance: Decimal
      checksum: str  # SHA256 of serialized content

      @classmethod
      def from_dict(cls, data: dict[str, str]) -> "StateSnapshot":
          """Deserialize from Redis hash data."""
          ...

      def to_dict(self) -> dict[str, str]:
          """Serialize to Redis hash-compatible dict (all values as strings)."""
          ...

      def compute_checksum(self) -> str:
          """Compute SHA256 checksum of all fields except checksum itself."""
          ...

      def validate_checksum(self) -> bool:
          """Validate stored checksum matches computed checksum."""
          ...
  ```
- [x] 1.3: Implement `to_dict()` with JSON serialization for lists, str() for Decimals
- [x] 1.4: Implement `from_dict()` with type conversion and validation
- [x] 1.5: Implement `compute_checksum()` using hashlib.sha256 over sorted field values
- [x] 1.6: Implement `validate_checksum()` comparing stored vs computed

### Task 2: Create SnapshotService (AC: 1, 2, 3, 5, 7)

- [x] 2.1: Create `src/state/snapshot_service.py` with `SnapshotService` class
- [x] 2.2: Implement `__init__()` with all required dependencies:
  ```python
  class SnapshotService:
      SNAPSHOT_TTL_SECONDS = 3600  # 1 hour

      def __init__(
          self,
          redis_manager: RedisStateManager,
          account_manager: AccountManager,
          position_tracker: PositionTracker,
          risk_registry: RiskStateRegistry,
          interval_seconds: float = 5.0,
      ):
          self._redis = redis_manager
          self._account_manager = account_manager
          self._position_tracker = position_tracker
          self._risk_registry = risk_registry
          self._interval = interval_seconds
          self._running = False
          self._task: asyncio.Task | None = None
  ```
- [x] 2.3: Implement `async def start()` to begin snapshot loop:
  ```python
  async def start(self) -> None:
      self._running = True
      self._task = asyncio.create_task(self._snapshot_loop())
  ```
- [x] 2.4: Implement `async def stop()` for graceful shutdown (final snapshot before stop)
- [x] 2.5: Implement `async def _snapshot_loop()` with interval timing:
  ```python
  async def _snapshot_loop(self) -> None:
      while self._running:
          try:
              await self._snapshot_all_accounts()
          except Exception as e:
              logger.error("Snapshot cycle failed: %s", e)
          await asyncio.sleep(self._interval)
  ```
- [x] 2.6: Implement `async def _get_active_account_ids()` helper and `_snapshot_all_accounts()`:
  ```python
  async def _get_active_account_ids(self) -> list[str]:
      """Get IDs of accounts with 'active' status."""
      active_ids = []
      for account_id in self._account_manager.get_all_accounts():
          status = await self._account_manager.get_account_status(account_id)
          if status == "active":
              active_ids.append(account_id)
      return active_ids

  async def _snapshot_all_accounts(self) -> None:
      """Snapshot all active accounts concurrently."""
      account_ids = await self._get_active_account_ids()
      if not account_ids:
          return
      await asyncio.gather(
          *[self._snapshot_account(acc_id) for acc_id in account_ids],
          return_exceptions=True,
      )
  ```
- [x] 2.7: Implement `async def _snapshot_account(account)` to create and save snapshot

### Task 3: Extend RedisStateManager (AC: 2, 3)

- [x] 3.1: Import StateSnapshot in redis_state.py (TTL constant lives in SnapshotService)
- [x] 3.2: Implement `async def save_snapshot()` using atomic pipeline:
  ```python
  async def save_snapshot(
      self, account_id: str, snapshot: "StateSnapshot", ttl_seconds: int = 3600
  ) -> None:
      """Save snapshot atomically with TTL using pipeline."""
      from .snapshot import StateSnapshot  # Avoid circular import

      key = f"snapshot:{account_id}:latest"
      async with self.client.pipeline(transaction=True) as pipe:
          await pipe.hset(key, mapping=snapshot.to_dict())
          await pipe.expire(key, ttl_seconds)
          await pipe.execute()
  ```
- [x] 3.3: Implement `async def get_snapshot(account_id) -> StateSnapshot | None`:
  ```python
  async def get_snapshot(self, account_id: str) -> StateSnapshot | None:
      key = f"snapshot:{account_id}:latest"
      data = await self.client.hgetall(key)
      if not data:
          return None
      return StateSnapshot.from_dict(data)
  ```
- [x] 3.4: Implement `async def get_snapshot_ttl(account_id) -> int | None` for verification

### Task 4: Integrate Position and Order Data (AC: 1)

- [x] 4.1: Extend `PositionTracker` (src/orders/position_tracker.py) with `get_positions_dict()`:
  ```python
  def get_positions_dict(self, account_id: str | None = None) -> list[dict[str, Any]]:
      """Return positions as list of dicts for snapshot.

      Args:
          account_id: Optional filter by account. If None, returns all.

      Returns:
          List of position dicts with string values for Redis storage.

      Note: Position uses 'quantity' (float), stored as 'volume' (string) for snapshot.
      """
      positions = self.get_all_positions(account_id)
      return [
          {
              "symbol": pos.symbol,
              "side": pos.side.value,
              "volume": str(pos.quantity),  # Position.quantity -> snapshot volume
              "entry_price": str(pos.entry_price),
              "entry_time": pos.entry_time.isoformat(),
              "order_id": pos.order_id,
          }
          for pos in positions
      ]
  ```
- [x] 4.2: Add pending orders tracking if not already present (may be empty list for MVP)
- [x] 4.3: Create snapshot collector function in SnapshotService:
  ```python
  async def _collect_snapshot_data(self, account_id: str) -> StateSnapshot:
      """Collect all data needed for account snapshot.

      Sources:
      - positions: from PositionTracker (injected)
      - balance: from Redis account balance
      - equity, peak_equity, daily_starting_balance: from RiskStateRegistry (injected)
      """
      # Get positions for this account
      positions = self._position_tracker.get_positions_dict(account_id)
      pending_orders: list[dict[str, Any]] = []  # Future: from order manager

      # Get balance from Redis
      balance = await self._redis.get_account_balance(account_id) or Decimal("0")

      # Get risk metrics from RiskStateRegistry
      risk_state = self._risk_registry.get_risk_state(account_id)
      if risk_state:
          equity = risk_state.current_equity
          peak_equity = risk_state.peak_equity  # Note: RiskState uses peak_equity
          daily_starting_balance = risk_state.daily_starting_balance
      else:
          # Fallback if no risk state available
          equity = balance
          peak_equity = balance
          daily_starting_balance = balance

      snapshot = StateSnapshot(
          account_id=account_id,
          timestamp=datetime.now(timezone.utc),
          positions=positions,
          pending_orders=pending_orders,
          account_balance=balance,
          equity=equity,
          peak_balance=peak_equity,  # Stored as peak_balance in snapshot
          daily_starting_balance=daily_starting_balance,
          checksum="",  # Will be computed below
      )
      snapshot.checksum = snapshot.compute_checksum()
      return snapshot
  ```

### Task 5: Unit Tests (AC: 1-7)

- [x] 5.1: Create `tests/unit/test_snapshot.py`
- [x] 5.2: Test StateSnapshot dataclass creation
- [x] 5.3: Test to_dict() serialization (all values as strings)
- [x] 5.4: Test from_dict() deserialization with type conversion
- [x] 5.5: Test checksum computation is deterministic
- [x] 5.6: Test validate_checksum() returns True for valid, False for tampered
- [x] 5.7: Test Decimal precision preserved through serialization
- [x] 5.8: Create `tests/unit/test_snapshot_service.py`
- [x] 5.9: Test snapshot interval timing (mock asyncio.sleep)
- [x] 5.10: Test concurrent snapshots with asyncio.gather
- [x] 5.11: Test graceful stop with final snapshot
- [x] 5.12: Test error handling in snapshot loop (continues on error)

### Task 6: Integration Tests (AC: 2, 3, 5, 7)

- [x] 6.1: Create `tests/integration/test_snapshot_redis.py`
- [x] 6.2: Test save_snapshot writes to Redis with correct key
- [x] 6.3: Test TTL is set to 3600 seconds
- [x] 6.4: Test get_snapshot retrieves and deserializes correctly
- [x] 6.5: Test round-trip: save -> get -> validate_checksum
- [x] 6.6: Test concurrent saves for multiple accounts
- [x] 6.7: Test performance: single snapshot < 10ms
- [x] 6.8: Test snapshot service full cycle with mock account manager

### Task 7: Documentation (AC: 1-7)

- [x] 7.1: Add docstrings to StateSnapshot class and all methods
- [x] 7.2: Add docstrings to SnapshotService class and all methods
- [x] 7.3: Document Redis key pattern and TTL strategy
- [x] 7.4: Update state/__init__.py with exports
- [x] 7.5: Document snapshot data structure in comments

## Dev Notes

### CRITICAL: FULL FILE PATHS (Monorepo Structure)

**All paths are relative to project root `/home/hopdev/Dev/Sandboxed/`:**

| Full Path | Action | Purpose |
|-----------|--------|---------|
| **New Files** | | |
| `services/trading-engine/src/state/snapshot.py` | CREATE | StateSnapshot dataclass |
| `services/trading-engine/src/state/snapshot_service.py` | CREATE | SnapshotService with interval loop |
| `services/trading-engine/tests/unit/test_snapshot.py` | CREATE | Unit tests for snapshot model |
| `services/trading-engine/tests/unit/test_snapshot_service.py` | CREATE | Unit tests for service |
| `services/trading-engine/tests/integration/test_snapshot_redis.py` | CREATE | Redis integration tests |
| **Modify Files** | | |
| `services/trading-engine/src/state/__init__.py` | MODIFY | Add snapshot exports |
| `services/trading-engine/src/state/redis_state.py` | MODIFY | Add save_snapshot, get_snapshot methods |
| `services/trading-engine/src/orders/position_tracker.py` | MODIFY | Add get_positions_dict() method |

### PREREQUISITES (Epic 4 Complete, Risk State Available)

**From Epic 3-4:**
- `RedisStateManager` at `src/state/redis_state.py` with async operations
- `AccountManager` at `src/accounts/account_manager.py` for account list
- `PositionTracker` at `src/orders/position_tracker.py` for position data
- `RiskState` at `src/accounts/risk_state.py` for peak_equity, daily P&L
- `RiskStateRegistry` at `src/accounts/risk_registry.py` for per-account risk state access

**Key integration points:**
- `AccountManager.get_all_accounts()` → list of account IDs
- `AccountManager.get_account_status(account_id)` → account status string
- `RedisStateManager.client` → async Redis client
- `RiskStateRegistry.get_risk_state(account_id)` → RiskState for account
- `RiskState.peak_equity` (not peak_balance), `RiskState.daily_starting_balance`
- `PositionTracker.get_all_positions(account_id)` → positions for account

### EXISTING CODE PATTERNS

**RedisStateManager (src/state/redis_state.py):**
```python
# Existing hash operations pattern (lines 196-227):
async def save_risk_state(self, account_id: str, state: RiskState) -> None:
    key = f"risk:{account_id}:state"
    await self.client.hset(key, mapping=state.to_dict())
    await self.client.expire(key, self.RISK_STATE_TTL_SECONDS)

async def get_risk_state(self, account_id: str) -> RiskState | None:
    key = f"risk:{account_id}:state"
    data = await self.client.hgetall(key)
    if not data:
        return None
    return RiskState.from_dict(data)
# REUSE: Same pattern for snapshots
```

**PositionTracker (src/orders/position_tracker.py):**
```python
# Current position storage (key is tuple of account_id, symbol):
self._positions: dict[tuple[str, str], Position] = {}

# Existing method to reuse:
def get_all_positions(self, account_id: str | None = None) -> list[Position]:
    """Get all positions, optionally filtered by account."""
    ...

# Method to add (see Task 4.1 for full implementation):
def get_positions_dict(self, account_id: str | None = None) -> list[dict[str, Any]]:
    """Return positions as dicts for snapshot. Uses get_all_positions()."""
    ...
```
**Note:** Position dataclass does NOT have to_dict() - manually create dicts in get_positions_dict().

### CONTEXT7 RESEARCH SUMMARY (Redis-py v6.x)

**Hash Operations for State Snapshots:**
```python
import redis.asyncio as aioredis

# Write snapshot as hash
await r.hset('snapshot:ftmo-gold-001:latest', mapping={
    'timestamp': '2026-01-03T14:32:15.123456Z',
    'positions': json.dumps([{"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"}]),
    'account_balance': '100000.00',
    'checksum': 'sha256_hash_here'
})

# Set TTL
await r.expire('snapshot:ftmo-gold-001:latest', 3600)

# Read snapshot
data = await r.hgetall('snapshot:ftmo-gold-001:latest')
# Returns: {'timestamp': '...', 'positions': '[...]', ...}
```

**TTL Management:**
```python
# Set TTL after write
await r.expire(key, 3600)  # 1 hour

# Check remaining TTL
ttl = await r.ttl(key)  # Returns seconds remaining, -2 if expired/not exists
```

**Async Pipeline for Performance:**
```python
# Use pipeline for atomic hset + expire
async with r.pipeline(transaction=True) as pipe:
    await pipe.hset(key, mapping=snapshot.to_dict())
    await pipe.expire(key, 3600)
    await pipe.execute()
```

### SNAPSHOT DATA STRUCTURE

**Redis Key Pattern:**
```
snapshot:{account_id}:latest
Example: snapshot:ftmo-gold-001:latest
TTL: 3600 seconds (1 hour)
```

**IMPORTANT - Field Naming Convention:**
- RiskState uses `peak_equity` internally
- StateSnapshot stores it as `peak_balance` (matches architecture doc)
- When collecting data: `peak_balance = risk_state.peak_equity`

**Hash Fields:**
```json
{
  "timestamp": "2026-01-03T14:32:15.123456Z",
  "positions": "[{\"symbol\": \"XAUUSD\", \"side\": \"BUY\", \"volume\": \"0.1\", \"entry_price\": \"1850.25\", \"entry_time\": \"2026-01-03T10:00:00Z\"}]",
  "pending_orders": "[]",
  "account_balance": "100000.00",
  "equity": "99850.00",
  "peak_balance": "102500.00",
  "daily_starting_balance": "100500.00",
  "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```

**Checksum Calculation:**
```python
import hashlib
import json

def compute_checksum(self) -> str:
    # Create deterministic string from sorted fields (excluding checksum)
    content = {
        "timestamp": self.timestamp.isoformat(),
        "positions": json.dumps(self.positions, sort_keys=True),
        "pending_orders": json.dumps(self.pending_orders, sort_keys=True),
        "account_balance": str(self.account_balance),
        "equity": str(self.equity),
        "peak_balance": str(self.peak_balance),
        "daily_starting_balance": str(self.daily_starting_balance),
    }
    serialized = json.dumps(content, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()
```

### PERFORMANCE REQUIREMENTS

**From Architecture NFR:** State snapshot < 10ms per account

**Concurrent snapshot pattern with timing:**
```python
async def _snapshot_all_accounts(self) -> None:
    """Snapshot all active accounts concurrently with performance logging."""
    account_ids = await self._get_active_account_ids()
    if not account_ids:
        return

    start = time.perf_counter()
    results = await asyncio.gather(
        *[self._snapshot_account(acc_id) for acc_id in account_ids],
        return_exceptions=True,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.debug(
        "Snapshot cycle completed in %.2fms for %d accounts",
        elapsed_ms, len(account_ids)
    )

    # Log any errors but don't fail the loop
    for acc_id, result in zip(account_ids, results):
        if isinstance(result, Exception):
            logger.error("Snapshot failed for %s: %s", acc_id, result)
```

### ANTI-PATTERNS (What NOT to Do)

| Anti-Pattern | Why It's Wrong | Instead, Do This |
|--------------|----------------|------------------|
| Sequential account snapshots | Slow with many accounts | Use asyncio.gather for concurrency |
| Skip checksum on save | Can't detect corruption | Always compute and store checksum |
| Float for Decimal fields | Precision loss | Use str() for Decimal serialization |
| Bare except in loop | Hides errors | Log exceptions, continue loop |
| Block on snapshot in trade flow | Adds latency | Run snapshots in background task |
| Separate hset + expire calls | Race condition if crash between | Use pipeline(transaction=True) for atomic ops |
| Call non-existent methods | Runtime error | Check AccountManager has get_all_accounts() not get_active_accounts() |

### TESTING COMMANDS

```bash
cd services/trading-engine

# Run unit tests
uv run pytest tests/unit/test_snapshot.py -v
uv run pytest tests/unit/test_snapshot_service.py -v

# Run integration tests (requires Redis)
uv run pytest tests/integration/test_snapshot_redis.py -v

# Run with coverage
uv run pytest tests/unit/test_snapshot.py tests/unit/test_snapshot_service.py --cov=src/state

# Lint check
uv run ruff check src/state/snapshot.py src/state/snapshot_service.py
```

### TASK DEPENDENCIES (Execute in Order)

```
Task 1 (StateSnapshot) ──► Task 3 (RedisStateManager) ──► Task 4 (Position Integration)
         │                          │                              │
         ▼                          ▼                              ▼
   Task 2 (SnapshotService) ◄───────┴──────────────────────────────┘
         │
         ▼
   Tasks 5-6 (Tests) ──► Task 7 (Docs)
```

### REFERENCES

- [docs/epic-5-context.md] - Epic 5 technical context with Context7 research
- [docs/architecture.md#State-Persistence-Flow] - State persistence architecture
- [docs/architecture.md#Redis-Data-Structures] - Redis key patterns
- [docs/epics.md#Story-5.1] - Story requirements and acceptance criteria
- [src/state/redis_state.py] - Existing Redis state management patterns
- [src/accounts/risk_state.py] - RiskState with to_dict/from_dict pattern
- [src/orders/position_tracker.py] - Position tracking for snapshot data
- [Context7 redis-py 2026-01-03] - Async hash operations, TTL management

## Dev Agent Record

**Story created:** 2026-01-03 via create-story workflow

**Context Analysis:**
- Epic 5 contexted with Redis-py and NautilusTrader research via Context7
- This is the FIRST story in Epic 5 (State Persistence & Crash Recovery)
- Prerequisites satisfied: RedisStateManager, AccountManager, PositionTracker ready
- Existing to_dict/from_dict patterns in RiskState provide template for StateSnapshot

**Context7 Research Summary:**
- redis-py v6.x: Async hash operations with HSET/HGETALL, TTL with expire()
- Pipeline pattern for atomic hset + expire operations
- NautilusTrader: CacheConfig with Redis backend, position snapshot methods

**Previous Epic Learnings (Epic 4):**
- Fire-and-forget pattern works well for background operations
- Per-account registry pattern proven (PnLTrackerRegistry, AuditLoggerRegistry)
- Decimal precision critical - always use str() for serialization
- asyncio.gather with return_exceptions=True for concurrent operations

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Context Reference

- Epic 5 context document (docs/epic-5-context.md)
- Context7 redis-py and NautilusTrader research (2026-01-03)
- Architecture document state persistence section
- Existing RedisStateManager, RiskState patterns

### Debug Log References

N/A - No issues encountered during implementation.

### Completion Notes List

- ✅ Created StateSnapshot dataclass with full serialization/deserialization
- ✅ Implemented SnapshotService with 5-second interval loop and asyncio.gather for concurrency
- ✅ Extended RedisStateManager with save_snapshot, get_snapshot, get_snapshot_ttl methods
- ✅ Added get_positions_dict() to PositionTracker for snapshot data collection
- ✅ All 43 unit tests pass (20 for StateSnapshot, 23 for SnapshotService)
- ✅ All 18 integration tests pass (Redis persistence, TTL, round-trip, performance)
- ✅ Performance verified: single snapshot < 10ms
- ✅ Linting passes with ruff check

### Code Review Record (2026-01-03)

**Reviewed by:** Claude Opus 4.5 (Adversarial Code Review Workflow)

**Issues Found:** 1 High, 4 Medium, 2 Low → **All Fixed**

| Issue | Severity | Resolution |
|-------|----------|------------|
| H1: Missing unit tests for `get_positions_dict()` | HIGH | Added 10 new tests to `test_position_tracker.py` |
| M1: No error handling in `get_snapshot()` for corrupt data | MEDIUM | Added try/catch with logging in `redis_state.py` |
| M2: `get_snapshot_ttl()` TTL=-1 case not handled | MEDIUM | Fixed to return None for both -1 and -2 |
| M3: No logging in StateSnapshot class | MEDIUM | Added logger and checksum validation warning |
| M4: `_get_active_account_ids()` sequential calls | MEDIUM | Refactored to use `asyncio.gather()` for concurrency |
| L1: Integration tests hardcoded port 6380 | LOW | Changed default to 6379 (standard Redis port) |
| L2: Test count verification | LOW | Verified 20 tests match story claims |

**Post-Review Test Results:** 78 unit tests passing, ruff lint clean

### File List

**Files CREATED:**
| File | Purpose |
|------|---------|
| `services/trading-engine/src/state/snapshot.py` | StateSnapshot dataclass with serialization |
| `services/trading-engine/src/state/snapshot_service.py` | SnapshotService with 5-second interval loop |
| `services/trading-engine/tests/unit/test_snapshot.py` | Unit tests for snapshot model (20 tests) |
| `services/trading-engine/tests/unit/test_snapshot_service.py` | Unit tests for snapshot service (23 tests) |
| `services/trading-engine/tests/integration/test_snapshot_redis.py` | Redis integration tests (18 tests) |

**Files MODIFIED:**
| File | Changes |
|------|---------|
| `services/trading-engine/src/state/__init__.py` | Added StateSnapshot, SnapshotService exports |
| `services/trading-engine/src/state/redis_state.py` | Added save_snapshot(), get_snapshot(), get_snapshot_ttl() with pipeline + error handling |
| `services/trading-engine/src/orders/position_tracker.py` | Added get_positions_dict(account_id) method |
| `services/trading-engine/tests/unit/test_position_tracker.py` | Added 10 tests for get_positions_dict() (Code Review) |
| `services/trading-engine/tests/integration/test_snapshot_redis.py` | Fixed default Redis port to 6379 (Code Review) |

**Dependencies to inject into SnapshotService:**
| Dependency | Source | Purpose |
|------------|--------|---------|
| `RedisStateManager` | `src/state/redis_state.py` | Save/load snapshots |
| `AccountManager` | `src/accounts/account_manager.py` | Get account list and status |
| `PositionTracker` | `src/orders/position_tracker.py` | Get positions for snapshot |
| `RiskStateRegistry` | `src/accounts/risk_registry.py` | Get equity, peak_equity, daily_starting_balance |

---

## Definition of Done

**Core Implementation:**
- [x] StateSnapshot dataclass created with all required fields
- [x] to_dict() and from_dict() methods for serialization
- [x] Checksum computation and validation methods
- [x] SnapshotService with configurable interval (default 5 seconds)
- [x] Background loop with graceful start/stop

**Redis Integration:**
- [x] Snapshots saved to `snapshot:{account_id}:latest` key
- [x] TTL of 3600 seconds set on each snapshot
- [x] get_snapshot() retrieves and deserializes correctly

**Data Collection:**
- [x] Positions collected from PositionTracker.get_positions_dict(account_id)
- [x] Balance from RedisStateManager.get_account_balance()
- [x] Equity from RiskStateRegistry.get_risk_state().current_equity
- [x] Peak equity from RiskState.peak_equity (stored as peak_balance in snapshot)
- [x] Daily starting balance from RiskState.daily_starting_balance

**Performance:**
- [x] Single account snapshot < 10ms
- [x] Concurrent snapshots using asyncio.gather
- [x] Non-blocking background operation

**Testing:**
- [x] Unit tests for StateSnapshot serialization/deserialization
- [x] Unit tests for checksum computation and validation
- [x] Unit tests for SnapshotService timing and concurrency
- [x] Integration tests for Redis persistence
- [x] Performance tests confirming < 10ms

**Acceptance Criteria Verification:**
- [x] AC1: Snapshot created every 5 seconds with all fields
- [x] AC2: Stored at correct Redis key pattern
- [x] AC3: TTL of 1 hour verified
- [x] AC4: Checksum included and validates correctly
- [x] AC5: Multiple accounts snapshotted concurrently
- [x] AC6: from_dict() reconstructs valid snapshot
- [x] AC7: Snapshot duration < 10ms

---
