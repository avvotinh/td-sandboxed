# Story 5.3: Position Reconciliation with MT5

Status: Ready for Review

## Story

As a **trader**,
I want **my positions reconciled with MT5 after recovery**,
So that **I know my actual position state matches what the system believes**.

## Acceptance Criteria

1. **AC1**: Given recovery mode is active, when MT5 connection is established, then the engine queries MT5 for actual open positions.

2. **AC2**: Given snapshot shows position A but MT5 does not, when reconciliation runs, then position A is removed from local state and a WARNING is logged: "Orphan position removed: {details}".

3. **AC3**: Given MT5 shows position B but snapshot does not, when reconciliation runs, then position B is added to local state and a WARNING is logged: "Unknown position found: {details}".

4. **AC4**: Given snapshot and MT5 positions match, when reconciliation completes, then the log shows: "Reconciliation complete: X positions verified" and trading can resume.

5. **AC5**: Given critical discrepancies are found, when reconciliation identifies issues, then trading remains paused and an ALERT is sent: "Manual intervention required".

6. **AC6**: Given reconciliation succeeds for all accounts, when the recovery sequence completes, then crash indicators are cleared and normal operation resumes.

7. **AC7**: Given position volume differs between snapshot and MT5 (tolerance: 0.001 lots), when reconciliation runs, then the MT5 value is used as source of truth and a WARNING is logged.

## Tasks / Subtasks

### Task 1: Create PositionReconciler Module (AC: 1, 4, 6)

- [x] 1.1: Create `src/state/position_reconciler.py` with `PositionReconciler` class
- [x] 1.2: Define reconciliation data structures:
  ```python
  from dataclasses import dataclass
  from decimal import Decimal
  from enum import Enum
  from typing import Any

  class DiscrepancyType(Enum):
      ORPHAN_POSITION = "orphan_position"     # In snapshot, not in MT5
      UNKNOWN_POSITION = "unknown_position"   # In MT5, not in snapshot
      VOLUME_MISMATCH = "volume_mismatch"     # Volume differs
      SIDE_MISMATCH = "side_mismatch"         # Side differs (BUY vs SELL)

  @dataclass
  class PositionDiscrepancy:
      """Describes a mismatch between snapshot and MT5 positions."""
      discrepancy_type: DiscrepancyType
      account_id: str
      symbol: str
      snapshot_side: str | None      # "BUY" or "SELL" or None
      mt5_side: str | None           # "BUY" or "SELL" or None
      snapshot_volume: Decimal | None
      mt5_volume: Decimal | None
      snapshot_entry_price: Decimal | None
      mt5_entry_price: Decimal | None
      details: str

  @dataclass
  class ReconciliationResult:
      """Result of position reconciliation for an account."""
      account_id: str
      success: bool
      positions_verified: int
      discrepancies: list[PositionDiscrepancy]
      positions_added: int     # From MT5 (unknown to snapshot)
      positions_removed: int   # From snapshot (orphans)
      positions_updated: int   # Volume/side corrections
      requires_manual_intervention: bool
      error_message: str | None
  ```
- [x] 1.3: Implement `PositionReconciler` class skeleton:
  ```python
  class PositionReconciler:
      """Reconciles snapshot positions with MT5 actual positions.

      MT5 is ALWAYS the source of truth. This reconciler:
      1. Queries MT5 for current open positions
      2. Compares with snapshot positions
      3. Updates local state to match MT5
      4. Logs all discrepancies

      CRITICAL: Never duplicate orders during recovery.
      """

      # Volume tolerance for position matching (0.001 lots)
      VOLUME_TOLERANCE = Decimal("0.001")

      def __init__(
          self,
          zmq_adapter: ZmqAdapter,
          redis_manager: RedisStateManager,
      ):
          """Initialize PositionReconciler.

          Args:
              zmq_adapter: ZMQ adapter for MT5 position queries
              redis_manager: Redis state manager for alerts and snapshots
                           (uses publish_alert() for critical notifications)
          """
          self._zmq = zmq_adapter
          self._redis = redis_manager
  ```
- [x] 1.4: Implement position comparison logic with tolerance
- [x] 1.5: Implement result aggregation and logging

### Task 2: MT5 Position Query Protocol (AC: 1)

- [x] 2.1: Define MT5 position query message format:
  ```python
  # Request to mt5-bridge (sent via ZMQ)
  {
      "type": "get_positions",
      "account_id": "ftmo-gold-001",
      "request_id": "UUID"
  }

  # Response from mt5-bridge (received via ZMQ)
  {
      "type": "positions_result",
      "request_id": "UUID",
      "account_id": "ftmo-gold-001",
      "positions": [
          {
              "ticket": 12345678,
              "symbol": "XAUUSD",
              "side": "BUY",
              "volume": 0.1,
              "entry_price": 1850.45,
              "entry_time": "2026-01-03T10:15:30.000Z",
              "current_price": 1852.30,
              "profit": 185.00,
              "swap": -2.50,
              "commission": -1.00
          }
      ],
      "timestamp": "2026-01-03T14:32:15.123Z"
  }
  ```
- [x] 2.2: Extend `ZmqAdapter` with position query method:
  ```python
  # IMPORTANT: Use EXISTING PUB/SUB pattern with pending futures (like _pending_orders)
  # DO NOT add a new REQ socket - reuse the existing architecture

  # Add to ZmqAdapter.__init__:
  self._pending_positions: dict[str, asyncio.Future[list[MT5Position]]] = {}

  # Add subscription in connect():
  self._sub_socket.subscribe(b"positions_result:")

  async def query_positions(
      self,
      account_id: str,
      timeout: float = 10.0,
  ) -> list[MT5Position]:
      """Query MT5 for current open positions.

      Uses the existing PUB/SUB pattern with pending futures (same as orders).
      Publishes get_positions request and waits for positions_result response.

      ARCHITECTURE: Reuses existing PUB socket for requests, SUB socket for responses.
      This follows the same pattern as send_order_and_wait() with _pending_orders.

      Args:
          account_id: Account to query positions for
          timeout: Response timeout in seconds (default 10s for recovery)

      Returns:
          List of MT5Position objects representing current open positions

      Raises:
          asyncio.TimeoutError: If no response within timeout
          RuntimeError: If not connected
      """
      if not self._pub_socket:
          raise RuntimeError("Not connected - call connect() first")

      request_id = str(uuid.uuid4())
      loop = asyncio.get_running_loop()
      future: asyncio.Future[list[MT5Position]] = loop.create_future()
      self._pending_positions[request_id] = future

      try:
          # Publish position query request
          topic = f"get_positions:{account_id}"
          payload = json.dumps({"type": "get_positions", "account_id": account_id, "request_id": request_id})
          await self._pub_socket.send_multipart([topic.encode(), payload.encode()])

          result = await asyncio.wait_for(future, timeout=timeout)
          return result
      except asyncio.TimeoutError:
          self._pending_positions.pop(request_id, None)
          logger.error("Position query timeout for account %s", account_id)
          raise
  ```
- [x] 2.3: Add `MT5Position` model to `zmq_models.py`:
  ```python
  @dataclass
  class MT5Position:
      """Position data from MT5 via mt5-bridge."""
      ticket: int
      symbol: str
      side: str  # "BUY" or "SELL"
      volume: Decimal
      entry_price: Decimal
      entry_time: str  # ISO8601
      current_price: Decimal
      profit: Decimal
      swap: Decimal
      commission: Decimal
  ```
- [x] 2.4: Handle positions_result topic in ZmqAdapter receive loop

### Task 3: Reconciliation Logic (AC: 2, 3, 4, 7)

- [x] 3.1: Implement `reconcile_account()` method:
  ```python
  async def reconcile_account(
      self,
      account_id: str,
      snapshot: StateSnapshot,
  ) -> ReconciliationResult:
      """Reconcile snapshot positions with MT5 for a single account.

      Sequence:
      1. Query MT5 for actual positions (with timeout handling)
      2. Compare with snapshot positions
      3. Log discrepancies
      4. Update local state to match MT5

      MT5 is ALWAYS source of truth.

      Args:
          account_id: Account to reconcile
          snapshot: Loaded snapshot with positions to compare

      Returns:
          ReconciliationResult with verification status
          On timeout: returns result with success=False, error_message set
      """
      try:
          mt5_positions = await self._zmq.query_positions(account_id, timeout=10.0)
      except asyncio.TimeoutError:
          logger.error("MT5 query timeout for %s - marking for retry", account_id)
          return ReconciliationResult(
              account_id=account_id,
              success=False,
              positions_verified=0,
              discrepancies=[],
              positions_added=0,
              positions_removed=0,
              positions_updated=0,
              requires_manual_intervention=True,  # Block until MT5 reachable
              error_message="MT5 query timeout - unable to verify positions",
          )
      except RuntimeError as e:
          logger.error("ZMQ not connected for %s: %s", account_id, e)
          return ReconciliationResult(
              account_id=account_id,
              success=False,
              positions_verified=0,
              discrepancies=[],
              positions_added=0,
              positions_removed=0,
              positions_updated=0,
              requires_manual_intervention=True,
              error_message=f"ZMQ connection error: {e}",
          )

      # Continue with reconciliation logic...
  ```
- [x] 3.2: Implement position matching by symbol and side:
  ```python
  # REQUIRED FIELDS in snapshot position dict (from StateSnapshot.positions):
  # - symbol: str (REQUIRED) - e.g., "XAUUSD"
  # - side: str (REQUIRED) - "BUY" or "SELL"
  # - volume: str (REQUIRED) - Decimal as string, e.g., "0.1"
  # - entry_price: str (OPTIONAL) - Decimal as string
  # - entry_time: str (OPTIONAL) - ISO8601 timestamp
  # - order_id: str (OPTIONAL) - Internal order ID

  def _validate_position_dict(self, position: dict) -> bool:
      """Validate position dict has required fields for matching.

      Returns:
          True if valid, False if missing required fields
      """
      required = {"symbol", "side", "volume"}
      return all(field in position for field in required)

  def _match_positions(
      self,
      snapshot_positions: list[dict],
      mt5_positions: list[MT5Position],
  ) -> tuple[list[tuple], list[PositionDiscrepancy]]:
      """Match snapshot positions to MT5 positions.

      IMPORTANT: Validates position dicts before matching.
      Invalid positions are logged and treated as orphans.

      Matching criteria:
      1. Same symbol (exact match)
      2. Same side (BUY/SELL)
      3. Volume within tolerance (0.001 lots)

      Returns:
          (matched_pairs, discrepancies)
          matched_pairs: List of (snapshot_pos, mt5_pos) tuples
          discrepancies: List of unmatched or mismatched positions
      """
      # First, validate all snapshot positions
      valid_positions = []
      for pos in snapshot_positions:
          if self._validate_position_dict(pos):
              valid_positions.append(pos)
          else:
              logger.warning("Invalid position dict, missing required fields: %s", pos)
      # ... matching logic using valid_positions ...
  ```
- [x] 3.3: Handle orphan positions (snapshot only):
  ```python
  async def _handle_orphan_position(
      self,
      account_id: str,
      position: dict,
  ) -> PositionDiscrepancy:
      """Handle position that exists in snapshot but not in MT5.

      This can happen if:
      - Position was closed while engine was down
      - Position data was corrupted

      Action: Remove from local state, log warning.

      Returns:
          PositionDiscrepancy describing the orphan
      """
  ```
- [x] 3.4: Handle unknown positions (MT5 only):
  ```python
  async def _handle_unknown_position(
      self,
      account_id: str,
      mt5_position: MT5Position,
  ) -> PositionDiscrepancy:
      """Handle position that exists in MT5 but not in snapshot.

      This can happen if:
      - Position was opened while engine was down
      - Snapshot is older than position entry

      Action: Add to local state, log warning.

      Returns:
          PositionDiscrepancy describing the unknown position
      """
  ```
- [x] 3.5: Handle volume mismatches:
  ```python
  async def _handle_volume_mismatch(
      self,
      account_id: str,
      snapshot_pos: dict,
      mt5_position: MT5Position,
  ) -> PositionDiscrepancy:
      """Handle position where volume differs between snapshot and MT5.

      MT5 is source of truth - update local state to match.
      Partial close during crash could cause this.

      Returns:
          PositionDiscrepancy describing the mismatch
      """
  ```

### Task 4: Critical Discrepancy Handling (AC: 5)

- [x] 4.1: Define critical discrepancy criteria:
  ```python
  def _is_critical_discrepancy(
      self,
      discrepancy: PositionDiscrepancy,
  ) -> bool:
      """Determine if discrepancy requires manual intervention.

      Critical conditions:
      - Side mismatch (BUY vs SELL for same symbol)
      - More than 3 orphan positions
      - Total exposure difference > 10%

      Returns:
          True if manual intervention required
      """
  ```
- [x] 4.2: Implement alert publishing for critical issues:
  ```python
  async def _publish_manual_intervention_alert(
      self,
      account_id: str,
      discrepancies: list[PositionDiscrepancy],
  ) -> None:
      """Publish alert requiring manual intervention.

      Uses existing RedisStateManager.publish_alert() method (from Epic 4).
      This publishes to Redis pub/sub channel for notification service.

      Alert format for notification service:
      {
          "type": "recovery_alert",
          "severity": "critical",
          "account_id": "ftmo-gold-001",
          "message": "Manual intervention required",
          "details": "Side mismatch detected: XAUUSD",
          "action": "Review positions before resuming trading"
      }
      """
      alert_data = {
          "type": "recovery_alert",
          "severity": "critical",
          "account_id": account_id,
          "message": "Manual intervention required",
          "details": self._format_discrepancy_details(discrepancies),
          "action": "Review positions before resuming trading",
      }
      # Use existing RedisStateManager.publish_alert() from Epic 4
      await self._redis.publish_alert(account_id, alert_data)
  ```
- [x] 4.3: Implement account pause on critical discrepancy

### Task 5: Local State Updates (AC: 2, 3, 7)

- [x] 5.1: Implement position removal from local state:
  ```python
  async def _remove_orphan_from_state(
      self,
      account_id: str,
      position: dict,
  ) -> None:
      """Remove orphan position from local state.

      Updates:
      - Account position list (remove position)
      - Snapshot (remove from positions array)

      Does NOT modify MT5 - read-only reconciliation.
      """
  ```
- [x] 5.2: Implement position addition to local state:
  ```python
  async def _add_unknown_to_state(
      self,
      account_id: str,
      mt5_position: MT5Position,
  ) -> None:
      """Add MT5 position to local state.

      Converts MT5Position to internal format and adds to:
      - Account position list
      - Snapshot positions array

      Used when MT5 has positions not in snapshot.
      """
  ```
- [x] 5.3: Implement snapshot update after reconciliation:
  ```python
  async def _save_reconciled_snapshot(
      self,
      account_id: str,
      reconciled_positions: list[dict],
  ) -> None:
      """Save updated snapshot after reconciliation.

      Creates new snapshot with:
      - Positions list from MT5 (source of truth)
      - Updated timestamp
      - New checksum

      Replaces old snapshot in Redis.
      """
  ```

### Task 6: Integration with CrashRecoveryManager (AC: 1, 4, 6)

- [x] 6.1: Add reconciliation step to recovery flow:
  ```python
  # In CrashRecoveryManager or Engine
  async def _run_position_reconciliation(
      self,
      accounts: list[str],
  ) -> dict[str, ReconciliationResult]:
      """Run reconciliation for all accounts needing recovery.

      Called after crash detection, before resuming trading.

      Args:
          accounts: List of account IDs from recovery result

      Returns:
          Dict mapping account_id to ReconciliationResult
      """
      results = {}
      for account_id in accounts:
          # Load snapshot
          valid, snapshot = await self._crash_recovery.validate_snapshot_for_recovery(account_id)
          if not valid or snapshot is None:
              # No valid snapshot - start fresh
              results[account_id] = ReconciliationResult(
                  account_id=account_id,
                  success=True,
                  positions_verified=0,
                  discrepancies=[],
                  positions_added=0,
                  positions_removed=0,
                  positions_updated=0,
                  requires_manual_intervention=False,
                  error_message=None,
              )
              continue

          # Reconcile with MT5
          result = await self._reconciler.reconcile_account(account_id, snapshot)
          results[account_id] = result

          if result.requires_manual_intervention:
              logger.warning(
                  "Account %s requires manual intervention: %s",
                  account_id,
                  result.error_message,
              )

      return results
  ```
- [x] 6.2: Update Engine startup to include reconciliation:
  ```python
  # In Engine.start()
  if recovery_result.recovery_mode:
      logger.warning(
          "Entering recovery mode for %d accounts",
          len(recovery_result.accounts_needing_recovery),
      )

      # Run position reconciliation (Story 5.3)
      reconciliation_results = await self._run_position_reconciliation(
          recovery_result.accounts_needing_recovery
      )

      # Check for any accounts requiring manual intervention
      blocked_accounts = [
          acc for acc, result in reconciliation_results.items()
          if result.requires_manual_intervention
      ]

      if blocked_accounts:
          logger.critical(
              "Accounts blocked pending manual intervention: %s",
              blocked_accounts,
          )
          # These accounts won't be started

      # Clear crash indicators after successful reconciliation
      await self._crash_recovery.clear_crash_indicators()
  ```
- [x] 6.3: Add position reconciler to Engine initialization

### Task 7: Unit Tests (AC: 1-7)

- [x] 7.1: Create `tests/unit/test_position_reconciler.py`
- [x] 7.2: Test matching positions - exact match
- [x] 7.3: Test matching positions - volume within tolerance
- [x] 7.4: Test orphan position detection (snapshot only)
- [x] 7.5: Test unknown position detection (MT5 only)
- [x] 7.6: Test volume mismatch handling
- [x] 7.7: Test side mismatch as critical discrepancy
- [x] 7.8: Test multiple orphans as critical discrepancy
- [x] 7.9: Test successful reconciliation logging
- [x] 7.10: Test manual intervention flag setting
- [x] 7.11: Test reconciliation with empty snapshot
- [x] 7.12: Test reconciliation with empty MT5 positions
- [x] 7.13: Test MT5 query timeout returns error result
- [x] 7.14: Test ZMQ not connected returns error result
- [x] 7.15: Test invalid position dict validation (missing required fields)

### Task 8: Integration Tests (AC: 1-7)

- [x] 8.1: Create `tests/integration/test_position_reconciler_redis.py`
- [x] 8.2: Test full reconciliation flow with Redis
- [x] 8.3: Test snapshot update after reconciliation
- [x] 8.4: Test MT5 position query via ZMQ (mocked bridge)
- [x] 8.5: Test alert publishing for critical discrepancies (uses RedisStateManager.publish_alert)
- [x] 8.6: Test engine startup with recovery and reconciliation
- [x] 8.7: Test positions_result handling in receive_ticks loop
- [x] 8.8: Test pending position future cleanup on timeout

### Task 9: Documentation and Exports (AC: 1-7)

- [x] 9.1: Add docstrings to all PositionReconciler methods
- [x] 9.2: Update `state/__init__.py` with new exports
- [x] 9.3: Update `adapters/__init__.py` with MT5Position
- [x] 9.4: Document reconciliation flow in module docstring

## Dev Notes

### CRITICAL: FULL FILE PATHS (Monorepo Structure)

**All paths are relative to project root `/home/hopdev/Dev/Sandboxed/`:**

| Full Path | Action | Purpose |
|-----------|--------|---------|
| **New Files** | | |
| `services/trading-engine/src/state/position_reconciler.py` | CREATE | PositionReconciler class |
| `services/trading-engine/tests/unit/test_position_reconciler.py` | CREATE | Unit tests |
| `services/trading-engine/tests/integration/test_position_reconciler_redis.py` | CREATE | Integration tests |
| **Modify Files** | | |
| `services/trading-engine/src/adapters/zmq_adapter.py` | MODIFY | Add query_positions method |
| `services/trading-engine/src/adapters/zmq_models.py` | MODIFY | Add MT5Position model |
| `services/trading-engine/src/state/__init__.py` | MODIFY | Add reconciler exports |
| `services/trading-engine/src/engine.py` | MODIFY | Integrate reconciliation in recovery |

### PREREQUISITES (Story 5.2 Complete)

**From Story 5.2:**
- `CrashRecoveryManager` at `src/state/crash_recovery.py` - crash detection and recovery initiation
- `validate_snapshot_for_recovery()` method for snapshot validation
- `startup_sequence()` returns `RecoveryResult` with accounts needing recovery
- `clear_crash_indicators()` method to call after successful recovery

**From Story 5.1:**
- `StateSnapshot` at `src/state/snapshot.py` - snapshot model with positions array
- `StateSnapshot.from_dict()` - deserialize from Redis HGETALL data
- `SnapshotService` at `src/state/snapshot_service.py` - for saving updated snapshots
- Redis key pattern: `snapshot:{account_id}:latest` (Hash type)

**Key integration points:**
- `ZmqAdapter` → extend with `query_positions()` using existing PUB/SUB pattern
- `CrashRecoveryManager.startup_sequence()` → returns accounts needing recovery
- `CrashRecoveryManager.validate_snapshot_for_recovery()` → validates and returns snapshot
- `StateSnapshot.positions` → list of position dicts to reconcile
- `RedisStateManager.publish_alert()` → for critical discrepancy alerts (from Epic 4)

### CONTEXT7 RESEARCH SUMMARY (NautilusTrader & PyZMQ 2026-01-03)

**NautilusTrader Position State Snapshot:**
```python
# From nautilus_trader cache API
snapshot_position_state(
    position=position,
    ts_snapshot=unix_timestamp_ns,
    unrealized_pnl=Money("50.25", "USD"),
    open_only=True  # Avoid race conditions
)
```

**Key patterns from NautilusTrader:**
- `open_only=True` flag prevents race conditions during snapshot
- Position state includes unrealized PnL at snapshot time
- Recovery sequence: Start → Load State → Reconcile → Resume

**PyZMQ Async Patterns (ADAPTED for existing architecture):**
```python
# NOTE: Our ZmqAdapter uses PUB/SUB, NOT REQ/REP
# Reuse the existing pending futures pattern from send_order_and_wait()

# Existing pattern in ZmqAdapter:
self._pending_orders: dict[str, asyncio.Future[OrderResult]] = {}

# New pattern for positions (same approach):
self._pending_positions: dict[str, asyncio.Future[list[MT5Position]]] = {}

async def query_positions():
    # Publish request, wait for response via future
    await self._pub_socket.send_multipart([topic, payload])
    result = await asyncio.wait_for(future, timeout=10.0)
    return result
```

**PUB/SUB pattern for position queries (NOT REQ/REP):**
- Reuse existing PUB socket for request (`get_positions:{account_id}` topic)
- Reuse existing SUB socket for response (`positions_result:{account_id}` topic)
- Use pending futures pattern like `_pending_orders`
- Timeout handling with `asyncio.wait_for()`

### MT5-BRIDGE PROTOCOL EXTENSION

The mt5-bridge needs to support position queries via existing PUB/SUB sockets:

```
trading-engine                    mt5-bridge                    MT5 EA
     |                                |                            |
     |--[PUB: get_positions:acct]--->|                            |
     |                                |---[GetPositions()]-------->|
     |                                |<--[positions_list]---------|
     |<-[PUB: positions_result:acct]-|                            |
     |                                |                            |
```

**Bridge must handle:**
1. Subscribe to `get_positions:*` topic on its SUB socket (connects to engine PUB)
2. Forward to appropriate MT5 EA instance based on account_id
3. Collect position data via EA's GetPositions() call
4. Publish response on its PUB socket with `positions_result:{account_id}` topic

### POSITION MATCHING ALGORITHM

```
For each snapshot position:
    1. Find MT5 positions with same symbol
    2. Match by side (BUY/SELL)
    3. If multiple matches, use entry_time as tiebreaker
    4. Compare volumes with tolerance

Tolerance: 0.001 lots (handles float precision)
Example: snapshot=0.1, mt5=0.0999 → MATCH
Example: snapshot=0.1, mt5=0.08 → VOLUME_MISMATCH
```

### RECONCILIATION STATE MACHINE

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Position Reconciliation Flow                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   1. Load validated snapshot for account                             │
│      └── If no valid snapshot: skip reconciliation (fresh start)    │
│                                                                      │
│   2. Query MT5 for current positions                                 │
│      └── Timeout: 10 seconds (longer for recovery)                   │
│      └── On failure: mark account for retry                          │
│                                                                      │
│   3. Compare positions                                               │
│      ├── Match by symbol + side                                      │
│      ├── Detect orphans (snapshot only)                              │
│      ├── Detect unknown (MT5 only)                                   │
│      └── Detect volume mismatches                                    │
│                                                                      │
│   4. Update local state                                              │
│      ├── Remove orphans from snapshot                                │
│      ├── Add unknown positions from MT5                              │
│      └── Update volumes to match MT5                                 │
│                                                                      │
│   5. Check for critical discrepancies                                │
│      ├── Side mismatch → CRITICAL                                    │
│      ├── >3 orphans → CRITICAL                                       │
│      └── >10% exposure difference → CRITICAL                         │
│                                                                      │
│   6. Finalize                                                        │
│      ├── Save reconciled snapshot to Redis                           │
│      ├── Log reconciliation summary                                  │
│      └── Set requires_manual_intervention if critical                │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### ANTI-PATTERNS (What NOT to Do)

| Anti-Pattern | Why It's Wrong | Instead, Do This |
|--------------|----------------|------------------|
| Trust snapshot over MT5 | MT5 is ground truth | Always use MT5 positions |
| Auto-close orphan positions | Data loss risk | Just remove from local state |
| Skip reconciliation on timeout | Stale state persists | Retry or block account |
| Ignore volume differences | P&L tracking breaks | Update to MT5 value |
| Silent discrepancy handling | Audit trail missing | Log every discrepancy |
| Resume on critical mismatch | Risk of duplicates | Require manual intervention |

### EXISTING CODE PATTERNS TO REUSE

**From ZmqAdapter (src/adapters/zmq_adapter.py):**
```python
# Pending request pattern (reuse for position queries)
self._pending_positions: dict[str, asyncio.Future[list[MT5Position]]] = {}

async def query_positions(self, account_id: str, timeout: float = 10.0):
    request_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    self._pending_positions[request_id] = future

    try:
        await self._send_position_query(account_id, request_id)
        result = await asyncio.wait_for(future, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        # CLEANUP: Remove stale pending request on timeout
        self._pending_positions.pop(request_id, None)
        raise

# Handle positions_result in receive_ticks() loop:
elif topic.startswith("positions_result:"):
    data = json.loads(payload)
    request_id = data["request_id"]
    positions = [MT5Position(**p) for p in data["positions"]]
    future = self._pending_positions.pop(request_id, None)
    if future and not future.done():
        future.set_result(positions)
```

**From CrashRecoveryManager (src/state/crash_recovery.py):**
```python
# Snapshot validation pattern
valid, snapshot = await self._crash_recovery.validate_snapshot_for_recovery(account_id)
if not valid or snapshot is None:
    # Handle missing/invalid snapshot
    pass
```

**From StateSnapshot (src/state/snapshot.py):**
```python
# Position dict format in snapshots
positions=[
    {
        "symbol": "XAUUSD",
        "side": "BUY",
        "volume": "0.1",
        "entry_price": "1850.45",
        "entry_time": "2026-01-03T10:15:30.000Z",
        "order_id": "ORDER-123"
    }
]
```

### ENGINE INTEGRATION GUIDE

**Reconciliation integration in Engine.start():**

```python
from src.state.position_reconciler import PositionReconciler, ReconciliationResult

class Engine:
    def __init__(self, ...):
        # ...existing init...
        self._reconciler: PositionReconciler | None = None

    async def start(self) -> None:
        """Start the trading engine with crash recovery check.

        INTEGRATION POINT: Insert reconciliation AFTER ZMQ connect,
        BEFORE _initialize_components(). This matches Story 5.2 pattern.

        Location in existing engine.py (approximate line numbers):
        - After: await self._zmq_adapter.connect()
        - Before: await self._initialize_components()
        """
        # 1. Run crash recovery startup sequence (from Story 5.2)
        recovery_result = await self._crash_recovery.startup_sequence()

        # 2. Connect ZMQ BEFORE reconciliation (needs it for MT5 queries)
        await self._zmq_adapter.connect()

        # 3. Initialize reconciler (Story 5.3 - NEW)
        self._reconciler = PositionReconciler(
            zmq_adapter=self._zmq_adapter,
            redis_manager=self._redis_state,  # Uses existing RedisStateManager
        )

        # 4. Run reconciliation if in recovery mode (Story 5.3 - NEW)
        if recovery_result.recovery_mode:
            reconciliation_results = await self._run_position_reconciliation(
                recovery_result.accounts_needing_recovery
            )

            # Block accounts with critical discrepancies
            for account_id, result in reconciliation_results.items():
                if result.requires_manual_intervention:
                    await self._account_manager.set_status(account_id, "blocked")

            # Clear crash indicators ONLY after reconciliation completes
            await self._crash_recovery.clear_crash_indicators()

        # 5. Continue normal startup (existing code)
        await self._initialize_components()
```

**Snapshot Loading Pattern (uses StateSnapshot.from_dict):**
```python
# In _run_position_reconciliation or PositionReconciler
async def _load_snapshot(self, account_id: str) -> StateSnapshot | None:
    """Load snapshot from Redis using existing patterns.

    Uses StateSnapshot.from_dict() with Redis HGETALL.
    """
    key = f"snapshot:{account_id}:latest"
    data = await self._redis.client.hgetall(key)
    if not data:
        return None
    return StateSnapshot.from_dict(data)
```

### TESTING COMMANDS

```bash
cd services/trading-engine

# Run unit tests
uv run pytest tests/unit/test_position_reconciler.py -v

# Run integration tests (requires Redis)
uv run pytest tests/integration/test_position_reconciler_redis.py -v

# Run with coverage
uv run pytest tests/unit/test_position_reconciler.py --cov=src/state

# Lint check
uv run ruff check src/state/position_reconciler.py
```

### TASK DEPENDENCIES (Execute in Order)

```
Task 1 (PositionReconciler) ──► Task 2 (MT5 Query Protocol)
         │                              │
         ▼                              ▼
   Task 3 (Reconciliation Logic) ◄──────┘
         │
         ▼
   Task 4 (Critical Handling) ──► Task 5 (State Updates)
         │                              │
         ▼                              ▼
   Task 6 (Engine Integration) ◄────────┘
         │
         ▼
   Tasks 7-8 (Tests) ──► Task 9 (Docs)
```

### PERFORMANCE REQUIREMENTS

- MT5 position query: < 10 seconds (network + MT5 response)
- Position matching: < 10ms per account (local computation)
- Snapshot update: < 50ms (Redis write)
- Full reconciliation: < 15 seconds per account (including MT5 query)

### REFERENCES

- [docs/epic-5-context.md] - Epic 5 technical context
- [docs/architecture.md#Position-Safety] - Position recovery rules
- [docs/architecture.md#ADR-007] - State recovery priority decision
- [docs/epics.md#Story-5.3] - Story requirements and acceptance criteria
- [src/state/crash_recovery.py] - CrashRecoveryManager integration point
- [src/state/snapshot.py] - StateSnapshot position format
- [src/adapters/zmq_adapter.py] - ZMQ communication patterns
- [Context7 NautilusTrader 2026-01-03] - Position snapshot patterns
- [Context7 PyZMQ 2026-01-03] - Async REQ/REP patterns

## Dev Agent Record

**Story created:** 2026-01-03 via create-story workflow

**Context Analysis:**
- Story 5.3 depends on Story 5.2 (Crash Detection and Recovery Initiation) - COMPLETED
- Story 5.3 depends on Story 5.1 (Redis State Snapshots) - COMPLETED
- Epic 5 focused on State Persistence & Crash Recovery
- This story implements the position reconciliation phase
- Story 5.4 (Daily P&L Recalculation) depends on this story

**Context7 Research Summary:**
- NautilusTrader: snapshot_position_state() with open_only flag for race condition prevention
- PyZMQ: async REQ/REP pattern for synchronous position queries
- Recovery sequence: Start → Load State → Reconcile → Resume

**Previous Story Learnings (Story 5.2):**
- CrashRecoveryManager.startup_sequence() returns RecoveryResult with accounts_needing_recovery
- validate_snapshot_for_recovery() checks checksum and timestamp recency (1 hour max)
- clear_crash_indicators() should be called after successful recovery
- Background heartbeat pattern works well for long-running operations

**Git Intelligence (Recent Commits):**
- b8aca3a: Implement spec 5 story 5.2 (Crash Detection)
- 08609a6: Implement spec 5 story 5.1 (Redis State Snapshots)
- Pattern: create service class with async methods, comprehensive unit tests

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Context Reference

- Epic 5 context document (docs/epic-5-context.md)
- Story 5.2 (previous story) for recovery flow integration
- Story 5.1 for snapshot patterns
- Context7 NautilusTrader and PyZMQ research (2026-01-03)
- Architecture document crash recovery section

### Validation Review (2026-01-03)

**Validator:** Claude Opus 4.5 (via validate-create-story workflow)

**Issues Fixed:**

| ID | Severity | Issue | Fix Applied |
|----|----------|-------|-------------|
| C1 | CRITICAL | ZmqAdapter uses PUB/SUB, not REQ/REP | Updated Task 2.2 to use existing pending futures pattern |
| C2 | CRITICAL | AlertPublisher doesn't exist | Replaced with RedisStateManager.publish_alert() |
| C3 | CRITICAL | Position dict field requirements unclear | Added explicit validation in Task 3.2 |
| E1 | ENHANCEMENT | Engine.py integration location unclear | Added detailed insertion point comments |
| E2 | ENHANCEMENT | MT5 query timeout not handled | Added error handling in Task 3.1 |
| E3 | ENHANCEMENT | RedisStateManager.get_snapshot() unclear | Clarified using StateSnapshot.from_dict() |
| E4 | ENHANCEMENT | Pending position cleanup missing | Added cleanup pattern to existing code section |

**Tests Added:** 7.13-7.15, 8.7-8.8

### Debug Log References

N/A - No critical issues encountered during implementation.

### Completion Notes List

**Implementation completed: 2026-01-03**

- Created PositionReconciler class with full reconciliation logic
- Added MT5Position model to zmq_models.py for position data
- Extended ZmqAdapter with query_positions() using existing PUB/SUB pattern
- Added positions_result topic handling in receive_ticks loop
- Implemented position matching with 0.001 lot tolerance
- Implemented critical discrepancy detection (side mismatch, >3 orphans, >10% exposure diff)
- Integrated reconciliation into Engine startup during recovery mode
- Created 23 unit tests covering all acceptance criteria
- Created 10 integration tests for Redis and ZMQ flows (skip when Redis unavailable)
- All exports updated in state/__init__.py and adapters/__init__.py
- Full documentation in module docstrings

### File List

**Files to CREATE:**
| File | Purpose |
|------|---------|
| `services/trading-engine/src/state/position_reconciler.py` | PositionReconciler class |
| `services/trading-engine/tests/unit/test_position_reconciler.py` | Unit tests |
| `services/trading-engine/tests/integration/test_position_reconciler_redis.py` | Integration tests |

**Files to MODIFY:**
| File | Changes |
|------|---------|
| `services/trading-engine/src/adapters/zmq_adapter.py` | Add query_positions() method |
| `services/trading-engine/src/adapters/zmq_models.py` | Add MT5Position model |
| `services/trading-engine/src/state/__init__.py` | Export PositionReconciler, ReconciliationResult |
| `services/trading-engine/src/engine.py` | Integrate reconciliation in recovery flow |

---

## Definition of Done

**Core Implementation:**
- [x] PositionReconciler class created with reconciliation logic
- [x] MT5Position model defined for position data
- [x] query_positions() method added to ZmqAdapter (using existing PUB/SUB pattern)
- [x] positions_result topic handling in receive_ticks loop
- [x] Position matching algorithm with tolerance implemented
- [x] Position dict validation (required fields: symbol, side, volume)

**Reconciliation Logic:**
- [x] Orphan position detection and removal
- [x] Unknown position detection and addition
- [x] Volume mismatch handling (MT5 as source of truth)
- [x] Side mismatch detected as critical

**Critical Handling:**
- [x] Critical discrepancy criteria defined
- [x] Manual intervention alert publishing (via RedisStateManager.publish_alert)
- [x] Account blocking on critical discrepancies
- [x] MT5 query timeout handling (returns error result, blocks account)

**Engine Integration:**
- [x] Reconciliation runs during recovery mode
- [x] Results logged per account
- [x] Crash indicators cleared after success
- [x] Blocked accounts excluded from startup

**Testing:**
- [x] Unit tests for matching algorithm
- [x] Unit tests for discrepancy detection
- [x] Unit tests for critical conditions
- [x] Integration tests with Redis
- [x] Integration tests with mocked MT5 bridge

**Acceptance Criteria Verification:**
- [x] AC1: MT5 queried on recovery
- [x] AC2: Orphan positions removed with warning
- [x] AC3: Unknown positions added with warning
- [x] AC4: Successful reconciliation logged
- [x] AC5: Critical discrepancies pause trading
- [x] AC6: Crash indicators cleared on success
- [x] AC7: Volume tolerance applied correctly

---
