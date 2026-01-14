# Story 5.6: Graceful Shutdown with State Persistence

Status: done

## Story

As a **trader**,
I want **the engine to save all state before shutting down**,
So that **clean restarts have accurate state**.

## Acceptance Criteria

1. **AC1**: Given I run `trading-engine stop`, when the shutdown sequence begins, then the engine: (1) stops accepting new signals, (2) waits for in-flight orders up to 30 seconds, (3) saves final state snapshot for each account, (4) sets clean shutdown flag, (5) closes all connections, (6) exits with code 0.

2. **AC2**: Given there are pending orders, when graceful shutdown is initiated, then the engine waits for order confirmations AND logs: "Waiting for X pending orders..."

3. **AC3**: Given the wait timeout (30s) is exceeded, when pending orders remain, then shutdown continues AND a WARNING is logged about unconfirmed orders.

4. **AC4**: Given I send SIGTERM or SIGINT, when the signal is received, then graceful shutdown is initiated (same as `trading-engine stop`).

5. **AC5**: Given the engine is in the middle of shutdown, when the engine successfully completes shutdown, then exit code is 0 AND logs show "Shutdown complete".

6. **AC6**: Given the engine shuts down cleanly, when the engine restarts, then no crash recovery is triggered (clean shutdown flag was set).

## Tasks / Subtasks

### Task 1: Create GracefulShutdown Module (AC: 1, 4)

- [x] 1.1: Create `src/state/graceful_shutdown.py` with imports and module docstring:
  ```python
  """Graceful shutdown handler for trading engine.

  Handles orderly shutdown sequence:
  1. Stop accepting new signals
  2. Wait for in-flight orders
  3. Persist final state snapshots
  4. Set clean shutdown flag
  5. Close all connections
  6. Exit cleanly

  Supports both CLI stop command and OS signals (SIGTERM, SIGINT).
  """
  from __future__ import annotations

  import asyncio
  import logging
  import signal
  from dataclasses import dataclass
  from datetime import datetime, timezone
  from enum import Enum, auto
  from typing import TYPE_CHECKING

  if TYPE_CHECKING:
      from ..accounts.account_manager import AccountManager
      from ..adapters.zmq_adapter import ZmqAdapter
      from .crash_recovery import CrashRecoveryManager
      from .redis_state import RedisStateManager
      from .snapshot_service import SnapshotService

  logger = logging.getLogger(__name__)
  ```

- [x] 1.2: Define shutdown phase enum and result dataclass:
  ```python
  class ShutdownPhase(Enum):
      """Phases of graceful shutdown sequence."""
      NOT_STARTED = auto()
      STOPPING_SIGNALS = auto()
      WAITING_ORDERS = auto()
      PERSISTING_STATE = auto()
      CLOSING_CONNECTIONS = auto()
      COMPLETE = auto()

  @dataclass
  class ShutdownResult:
      """Result of graceful shutdown sequence.

      Attributes:
          success: True if shutdown completed cleanly
          phase_reached: Last phase completed
          pending_orders_at_timeout: Orders that didn't complete before timeout
          accounts_snapshot_count: Number of accounts with final snapshot saved
          duration_seconds: Total shutdown duration
          exit_code: Process exit code (0 for success)
      """
      success: bool
      phase_reached: ShutdownPhase
      pending_orders_at_timeout: int
      accounts_snapshot_count: int
      duration_seconds: float
      exit_code: int
  ```

- [x] 1.3: Implement `GracefulShutdown` class skeleton:
  ```python
  class GracefulShutdown:
      """Orchestrates graceful shutdown of trading engine.

      Handles the complete shutdown sequence when triggered by:
      - CLI command: `trading-engine stop`
      - OS signals: SIGTERM, SIGINT (Ctrl+C)

      The shutdown sequence follows architecture spec:
      1. Set shutdown flag (atomic) - prevents race conditions
      2. Stop accepting new signals - unsubscribe from Redis
      3. Wait for in-flight orders (up to 30s timeout)
      4. Persist final state snapshots for all accounts
      5. Close connections (ZMQ, Redis, TimescaleDB)
      6. Exit with code 0

      Example:
          shutdown = GracefulShutdown(
              redis_manager=redis,
              account_manager=accounts,
              snapshot_service=snapshots,
              zmq_adapter=zmq,
              crash_recovery=crash_mgr,
          )
          shutdown.register_signal_handlers()
          # ... engine runs ...
          result = await shutdown.initiate()  # Called on stop or signal
      """

      PENDING_ORDER_TIMEOUT_SECONDS = 30

      def __init__(
          self,
          redis_manager: RedisStateManager,
          account_manager: AccountManager,
          snapshot_service: SnapshotService,
          zmq_adapter: ZmqAdapter | None = None,
          crash_recovery: CrashRecoveryManager | None = None,
      ) -> None:
          """Initialize GracefulShutdown.

          Args:
              redis_manager: Redis client for pub/sub unsubscribe
              account_manager: Account manager to stop account tasks
              snapshot_service: For final state snapshots
              zmq_adapter: ZMQ adapter for pending order tracking (optional)
              crash_recovery: Crash recovery manager for clean shutdown flag
          """
          self._redis = redis_manager
          self._account_manager = account_manager
          self._snapshot_service = snapshot_service
          self._zmq = zmq_adapter
          self._crash_recovery = crash_recovery
          self._shutdown_event = asyncio.Event()
          self._shutdown_in_progress = False
          self._current_phase = ShutdownPhase.NOT_STARTED
          self._start_time: datetime | None = None
  ```

### Task 2: Signal Handler Registration (AC: 4)

**CRITICAL: asyncio signal handling patterns from Context7 research:**
- Use `loop.add_signal_handler()` for async compatibility
- Signal handlers run in main thread only
- Cannot use signal.signal() in async code safely

- [x] 2.1: Implement `register_signal_handlers()`:
  ```python
  def register_signal_handlers(self) -> None:
      """Register handlers for SIGTERM and SIGINT.

      Uses asyncio's add_signal_handler for proper async integration.
      Signal handlers set the shutdown event which triggers the
      shutdown sequence in the main event loop.

      CRITICAL: Must be called from main thread after event loop starts.
      """
      loop = asyncio.get_running_loop()

      for sig in (signal.SIGTERM, signal.SIGINT):
          loop.add_signal_handler(
              sig,
              lambda s=sig: self._handle_signal(s),
          )
          logger.debug("Registered handler for %s", sig.name)

      logger.info("Signal handlers registered for graceful shutdown")

  def _handle_signal(self, signum: signal.Signals) -> None:
      """Handle OS signal by triggering shutdown.

      Args:
          signum: The signal received (SIGTERM or SIGINT)
      """
      sig_name = signal.Signals(signum).name
      logger.info("Received %s, initiating graceful shutdown", sig_name)
      self._shutdown_event.set()
  ```

- [x] 2.2: Implement `unregister_signal_handlers()` for cleanup:
  ```python
  def unregister_signal_handlers(self) -> None:
      """Unregister signal handlers during shutdown.

      Prevents duplicate shutdown triggers and allows clean exit.
      """
      try:
          loop = asyncio.get_running_loop()
          for sig in (signal.SIGTERM, signal.SIGINT):
              loop.remove_signal_handler(sig)
          logger.debug("Signal handlers unregistered")
      except Exception as e:
          logger.warning("Failed to unregister signal handlers: %s", e)
  ```

### Task 3: Stop Signal Processing (AC: 1, 2)

- [x] 3.1: Implement `_stop_signal_processing()`:
  ```python
  async def _stop_signal_processing(self) -> None:
      """Stop accepting new trading signals.

      Actions:
      1. Unsubscribe from Redis market data channels
      2. Stop SignalRouter from processing new signals
      3. Stop all account tasks from processing

      After this step, no new trades will be initiated.
      """
      self._current_phase = ShutdownPhase.STOPPING_SIGNALS
      logger.info("Stopping signal processing...")

      # Stop account manager from processing new signals
      # This stops all account tasks gracefully
      # NOTE: Use shutdown() not stop_all() - verified in account_manager.py:645
      try:
          await self._account_manager.shutdown()
          logger.debug("Account manager stopped")
      except Exception as e:
          logger.error("Error stopping account manager: %s", e)

      # Future: Unsubscribe from Redis market data channels
      # await self._redis.unsubscribe_all()

      logger.info("Signal processing stopped - no new trades will be initiated")
  ```

### Task 4: Wait for In-Flight Orders (AC: 2, 3)

- [x] 4.1: Implement `_wait_for_pending_orders()`:
  ```python
  async def _wait_for_pending_orders(self) -> int:
      """Wait for pending orders to complete with timeout.

      Monitors ZmqAdapter for pending order count.
      Logs progress every 5 seconds during wait.
      Returns number of orders still pending at timeout.

      Returns:
          Number of orders that did NOT complete before timeout
      """
      self._current_phase = ShutdownPhase.WAITING_ORDERS

      if self._zmq is None:
          logger.debug("No ZMQ adapter - skipping pending order wait")
          return 0

      pending = self._zmq.get_pending_order_count()
      if pending == 0:
          logger.info("No pending orders to wait for")
          return 0

      logger.info("Waiting for %d pending orders...", pending)

      start = datetime.now(timezone.utc)
      timeout = self.PENDING_ORDER_TIMEOUT_SECONDS
      check_interval = 1.0  # Check every second
      log_interval = 5.0    # Log every 5 seconds

      last_log_time = start
      while True:
          elapsed = (datetime.now(timezone.utc) - start).total_seconds()

          if elapsed >= timeout:
              remaining = self._zmq.get_pending_order_count()
              if remaining > 0:
                  logger.warning(
                      "Shutdown timeout: %d orders still pending after %.1fs",
                      remaining,
                      timeout,
                  )
              return remaining

          pending = self._zmq.get_pending_order_count()
          if pending == 0:
              logger.info(
                  "All pending orders completed in %.1f seconds",
                  elapsed,
              )
              return 0

          # Log progress periodically
          now = datetime.now(timezone.utc)
          if (now - last_log_time).total_seconds() >= log_interval:
              logger.info(
                  "Waiting for %d pending orders... (%.1fs elapsed)",
                  pending,
                  elapsed,
              )
              last_log_time = now

          await asyncio.sleep(check_interval)
  ```

### Task 5: Persist Final State (AC: 1)

- [x] 5.1: Implement `_persist_final_state()`:
  ```python
  async def _persist_final_state(self) -> int:
      """Persist final state snapshot for all accounts.

      Uses SnapshotService.stop() which:
      1. Stops the periodic snapshot loop
      2. Creates one final snapshot for all active accounts
      3. Logs any snapshot failures

      Returns:
          Number of accounts with successful final snapshot
      """
      self._current_phase = ShutdownPhase.PERSISTING_STATE
      logger.info("Persisting final state snapshots...")

      try:
          # SnapshotService.stop() performs final snapshot for all accounts
          await self._snapshot_service.stop()

          # Count active accounts that were snapshotted
          active_accounts = await self._get_active_account_count()
          logger.info(
              "Final state persisted for %d accounts",
              active_accounts,
          )
          return active_accounts

      except Exception as e:
          logger.error("Failed to persist final state: %s", e)
          return 0

  async def _get_active_account_count(self) -> int:
      """Get count of active accounts for logging."""
      account_ids = self._account_manager.get_all_accounts()
      if not account_ids:
          return 0

      statuses = await asyncio.gather(
          *[self._account_manager.get_account_status(acc) for acc in account_ids]
      )
      return sum(1 for s in statuses if s in ("active", "paused"))
  ```

### Task 6: Close Connections (AC: 1)

**PREREQUISITE:** ZmqAdapter currently has no `close()` method. Add it before implementing this task.

- [x] 6.0: Add `close()` method to ZmqAdapter (`src/adapters/zmq_adapter.py`):
  ```python
  async def close(self) -> None:
      """Close ZMQ sockets and context gracefully.

      Closes all sockets and terminates the ZMQ context.
      Safe to call multiple times.
      """
      if self._closed:
          return

      logger.info("Closing ZMQ adapter...")

      # Close sockets first
      for socket in [self._req_socket, self._sub_socket, self._pub_socket]:
          if socket is not None:
              try:
                  socket.close(linger=0)
              except Exception as e:
                  logger.warning("Error closing ZMQ socket: %s", e)

      # Terminate context
      if self._context is not None:
          try:
              self._context.term()
          except Exception as e:
              logger.warning("Error terminating ZMQ context: %s", e)

      self._closed = True
      logger.info("ZMQ adapter closed")
  ```

- [x] 6.1: Implement `_close_connections()`:
  ```python
  async def _close_connections(self) -> None:
      """Close all service connections gracefully.

      Order matters - close in reverse dependency order:
      1. ZeroMQ (execution bridge)
      2. Redis (state and pub/sub)
      3. TimescaleDB (audit logs) - future

      Each close is wrapped in try/except to ensure
      subsequent closes happen even on error.
      """
      self._current_phase = ShutdownPhase.CLOSING_CONNECTIONS
      logger.info("Closing connections...")

      # 1. Close ZMQ adapter
      if self._zmq is not None:
          try:
              await self._zmq.close()
              logger.debug("ZMQ adapter closed")
          except Exception as e:
              logger.error("Error closing ZMQ adapter: %s", e)

      # 2. Close Redis connection
      try:
          await self._redis.close()
          logger.debug("Redis connection closed")
      except Exception as e:
          logger.error("Error closing Redis connection: %s", e)

      # Future: Close TimescaleDB connection
      # if self._db is not None:
      #     await self._db.close()

      logger.info("All connections closed")
  ```

### Task 7: Main Shutdown Orchestration (AC: 1, 5, 6)

- [x] 7.1: Implement `initiate()` main method:
  ```python
  async def initiate(self) -> ShutdownResult:
      """Execute graceful shutdown sequence.

      This is the main entry point called by:
      - Engine.shutdown() (from CLI stop command)
      - Signal handler (SIGTERM/SIGINT)

      Sequence (per Architecture doc):
      1. Set shutdown flag (atomic)
      2. Stop accepting new signals
      3. Wait for in-flight orders (30s timeout)
      4. Persist final state
      5. Set clean shutdown flag (CrashRecoveryManager)
      6. Close connections
      7. Exit with code 0

      Returns:
          ShutdownResult with status and metrics
      """
      # Prevent duplicate shutdown
      if self._shutdown_in_progress:
          logger.warning("Shutdown already in progress")
          return ShutdownResult(
              success=False,
              phase_reached=self._current_phase,
              pending_orders_at_timeout=0,
              accounts_snapshot_count=0,
              duration_seconds=0,
              exit_code=1,
          )

      self._shutdown_in_progress = True
      self._start_time = datetime.now(timezone.utc)
      logger.info("Initiating graceful shutdown...")

      # Unregister signal handlers to prevent re-entry
      self.unregister_signal_handlers()

      pending_orders_remaining = 0
      accounts_snapshotted = 0

      try:
          # Phase 1: Stop signal processing
          await self._stop_signal_processing()

          # Phase 2: Wait for pending orders
          pending_orders_remaining = await self._wait_for_pending_orders()

          # Phase 3: Persist final state
          accounts_snapshotted = await self._persist_final_state()

          # Phase 4: Run crash recovery shutdown sequence
          # This sets clean shutdown flag and releases process lock
          if self._crash_recovery is not None:
              await self._crash_recovery.shutdown_sequence()
              logger.debug("Crash recovery shutdown sequence completed")

          # Phase 5: Close connections
          await self._close_connections()

          self._current_phase = ShutdownPhase.COMPLETE

          duration = (datetime.now(timezone.utc) - self._start_time).total_seconds()

          logger.info(
              "Shutdown complete in %.2f seconds (accounts: %d, pending orders at timeout: %d)",
              duration,
              accounts_snapshotted,
              pending_orders_remaining,
          )

          return ShutdownResult(
              success=True,
              phase_reached=ShutdownPhase.COMPLETE,
              pending_orders_at_timeout=pending_orders_remaining,
              accounts_snapshot_count=accounts_snapshotted,
              duration_seconds=duration,
              exit_code=0,
          )

      except Exception as e:
          logger.error("Shutdown failed at phase %s: %s", self._current_phase.name, e)
          duration = (datetime.now(timezone.utc) - self._start_time).total_seconds()
          return ShutdownResult(
              success=False,
              phase_reached=self._current_phase,
              pending_orders_at_timeout=pending_orders_remaining,
              accounts_snapshot_count=accounts_snapshotted,
              duration_seconds=duration,
              exit_code=1,
          )
  ```

- [x] 7.2: Implement `wait_for_shutdown_signal()`:
  ```python
  async def wait_for_shutdown_signal(self) -> ShutdownResult:
      """Wait for shutdown signal then execute shutdown.

      Called by Engine.run() to wait for termination.
      Blocks until SIGTERM, SIGINT, or shutdown_event is set.

      Returns:
          ShutdownResult from initiate()
      """
      await self._shutdown_event.wait()
      return await self.initiate()

  def trigger_shutdown(self) -> None:
      """Programmatically trigger shutdown.

      Used by Engine.shutdown() to trigger from code
      rather than waiting for OS signal.
      """
      logger.info("Shutdown triggered programmatically")
      self._shutdown_event.set()
  ```

### Task 8: Engine Integration (AC: 1, 4, 5)

- [x] 8.1: Update Engine.__init__ to accept GracefulShutdown:
  ```python
  # In Engine.__init__(), add:
  self._graceful_shutdown: GracefulShutdown | None = None
  ```

- [x] 8.2: Create `_initialize_graceful_shutdown()` in Engine:
  ```python
  def _initialize_graceful_shutdown(self) -> None:
      """Initialize graceful shutdown handler.

      Called after all engine components are initialized.
      Registers signal handlers for SIGTERM/SIGINT.
      """
      from .state.graceful_shutdown import GracefulShutdown

      self._graceful_shutdown = GracefulShutdown(
          redis_manager=self._redis_manager,
          account_manager=self._account_manager,
          snapshot_service=self._snapshot_service,
          zmq_adapter=self._zmq_adapter,
          crash_recovery=self._crash_recovery,
      )
      self._graceful_shutdown.register_signal_handlers()
      logger.info("Graceful shutdown handler initialized")
  ```

- [x] 8.3: Update Engine.run() to use GracefulShutdown:
  ```python
  async def run(self) -> None:
      """Run the trading engine until shutdown."""
      # ... existing initialization code ...

      # Initialize graceful shutdown after components
      self._initialize_graceful_shutdown()

      logger.info("Trading Engine v0.1.0 running")
      self._running = True

      # Wait for shutdown signal
      if self._graceful_shutdown is not None:
          result = await self._graceful_shutdown.wait_for_shutdown_signal()
          if not result.success:
              logger.error("Shutdown completed with errors")
      else:
          # Fallback to simple event wait
          await self._shutdown_event.wait()

      self._running = False
      logger.info("Trading Engine stopped")
  ```

- [x] 8.4: Update Engine.shutdown() to use GracefulShutdown:
  ```python
  async def shutdown(self) -> None:
      """Gracefully shutdown the trading engine.

      Triggers the shutdown sequence which:
      1. Stops signal processing
      2. Waits for pending orders
      3. Persists final state
      4. Closes connections
      """
      if not self._running:
          return

      logger.info("Shutdown requested via Engine.shutdown()")

      if self._graceful_shutdown is not None:
          self._graceful_shutdown.trigger_shutdown()
          # The actual shutdown is handled by run() waiting on the event
      else:
          # Fallback for backward compatibility
          self._running = False
          self._shutdown_event.set()
          if self._crash_recovery is not None:
              await self._crash_recovery.shutdown_sequence()
  ```

### Task 9: CLI Integration (AC: 1)

- [x] 9.1: Verify CLI `trading-engine stop` triggers proper shutdown:
  ```python
  # In cli/main.py, the stop command should:
  # 1. Send shutdown signal via Redis or
  # 2. Find and signal the running process

  # Existing stop() in CLI uses Redis engine state
  # Ensure it sets "stopping" state which Engine monitors
  ```

### Task 10: Unit Tests (AC: 1-6)

- [x] 10.1: Create `tests/unit/test_graceful_shutdown.py`
- [x] 10.2: Test shutdown sequence phases execute in order
- [x] 10.3: Test signal handler registration and triggering
- [x] 10.4: Test pending order wait with timeout
- [x] 10.5: Test pending order completion before timeout
- [x] 10.6: Test final snapshot is persisted
- [x] 10.7: Test clean shutdown flag is set
- [x] 10.8: Test connections are closed in order
- [x] 10.9: Test duplicate shutdown is prevented
- [x] 10.10: Test shutdown result metrics are accurate
- [x] 10.11: Test exit code is 0 on success
- [x] 10.12: Test exit code is 1 on failure
- [x] 10.13: Test shutdown continues when account_manager.shutdown() raises exception
- [x] 10.14: Test shutdown continues when snapshot_service.stop() raises exception
- [x] 10.15: Test shutdown continues when zmq.close() raises exception
- [x] 10.16: Test shutdown continues when redis.close() raises exception

### Task 11: Integration Tests (AC: 1-6)

- [x] 11.1: Create `tests/integration/test_graceful_shutdown_redis.py`
- [x] 11.2: Test full shutdown sequence with real Redis
- [x] 11.3: Test clean shutdown flag prevents crash recovery on restart
- [x] 11.4: Test SIGTERM triggers proper shutdown
- [x] 11.5: Test state snapshots are persisted to Redis

### Task 12: Documentation and Exports

- [x] 12.1: Add docstrings to all GracefulShutdown methods
- [x] 12.2: Update `state/__init__.py` with exports:
  ```python
  from .graceful_shutdown import (
      GracefulShutdown,
      ShutdownPhase,
      ShutdownResult,
  )
  ```
- [x] 12.3: Document signal handling in module docstring

### Review Follow-ups (AI)

**Code Review Date:** 2026-01-15
**Reviewer:** Claude Opus 4.5 (code-review workflow)

**Issues Fixed During Review:**
- [x] [MEDIUM] Fixed ZmqAdapter.close() docstring - was claiming to terminate context but uses singleton [zmq_adapter.py:564-572]
- [x] [MEDIUM] Added test for AC3 WARNING log on timeout - test_pending_order_wait_timeout_logs_warning [test_graceful_shutdown.py:299-321]
- [x] [LOW] Removed unused imports in test file [test_graceful_shutdown.py:19]

**Known Limitations (Not Fixed):**
- [MEDIUM] Integration tests simulate signals via _handle_signal() rather than actual OS signal delivery. True signal delivery testing requires subprocess infrastructure which is out of scope for this story.

## Dev Notes

### CRITICAL: Integration with Existing Shutdown Code

**File: `services/trading-engine/src/engine.py`**
The Engine already has:
- `_shutdown_event: asyncio.Event()` - line 67
- `shutdown()` method - line 429
- `_crash_recovery.shutdown_sequence()` - line 446

This story EXTENDS the existing shutdown with proper sequencing:
```
CURRENT (minimal):
1. Set _running = False
2. Set _shutdown_event
3. Call crash_recovery.shutdown_sequence()

NEW (graceful):
1. Register signal handlers on startup
2. On signal/stop:
   a. Stop signal processing
   b. Wait for pending orders (30s timeout)
   c. Persist final snapshots (via SnapshotService.stop())
   d. Call crash_recovery.shutdown_sequence() (sets clean flag)
   e. Close connections
   f. Exit with code 0
```

### CONTEXT7 RESEARCH SUMMARY (2026-01-15)

**Python asyncio Signal Handling (AnyIO docs):**
```python
# Correct pattern for async signal handling
loop = asyncio.get_running_loop()
loop.add_signal_handler(signal.SIGTERM, handler)
loop.add_signal_handler(signal.SIGINT, handler)

# Handler sets event, actual shutdown runs in async context
def handler():
    shutdown_event.set()
```

**Redis Async Client Cleanup (redis-py docs):**
```python
# Proper async Redis cleanup
async def cleanup():
    await pubsub.unsubscribe()
    await pubsub.close()
    await redis_client.aclose()
```

### FULL FILE PATHS (Monorepo Structure)

**All paths relative to `/home/hopdev/Dev/Sandboxed/`:**

| Full Path | Action | Purpose |
|-----------|--------|---------|
| **New Files** | | |
| `services/trading-engine/src/state/graceful_shutdown.py` | CREATE | GracefulShutdown class |
| `services/trading-engine/tests/unit/test_graceful_shutdown.py` | CREATE | Unit tests |
| `services/trading-engine/tests/integration/test_graceful_shutdown_redis.py` | CREATE | Integration tests |
| **Modify Files** | | |
| `services/trading-engine/src/state/__init__.py` | MODIFY | Export GracefulShutdown |
| `services/trading-engine/src/engine.py` | MODIFY | Integrate GracefulShutdown |
| `services/trading-engine/src/adapters/zmq_adapter.py` | MODIFY | Add close() method |

### PREREQUISITES (Stories 5.1-5.5 Complete)

**From Story 5.5 (Trading Resume):**
- TradingResumer integrated in Engine
- AccountManager._spawn_account_task() for resuming

**From Story 5.1 (Redis Snapshots):**
- SnapshotService with start()/stop() methods
- SnapshotService.stop() performs final snapshot before stopping

**From Story 5.2 (Crash Detection):**
- CrashRecoveryManager.shutdown_sequence() sets clean shutdown flag
- Clean shutdown flag prevents crash recovery on next startup

**Existing Engine Components:**
- `_shutdown_event: asyncio.Event` - already exists
- `shutdown()` method - already exists, needs enhancement
- `_crash_recovery` - already initialized

### EXISTING CODE PATTERNS TO REUSE

| File | Method/Class | Use For |
|------|--------------|---------|
| `src/state/snapshot_service.py:105` | `stop()` | Final snapshot on shutdown |
| `src/state/crash_recovery.py:473` | `shutdown_sequence()` | Sets clean shutdown flag |
| `src/state/redis_state.py:194` | `close()` | Graceful Redis close |
| `src/execution/validated_adapter.py:331` | `get_pending_order_count()` | Check pending orders |
| `src/accounts/account_manager.py:645` | `shutdown()` | Stop all account tasks (NOT stop_all!) |
| `src/adapters/zmq_adapter.py` | `close()` | **ADD THIS METHOD** - ZMQ cleanup |

### SHUTDOWN SEQUENCE DIAGRAM

```
CLI `stop` or SIGTERM/SIGINT
         │
         ▼
┌─────────────────────────────────┐
│ 1. Set shutdown flag (atomic)   │ ← Prevents race conditions
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ 2. Stop signal processing       │ ← AccountManager.stop_all()
│    - Stop account tasks         │   No new trades initiated
│    - Unsubscribe from Redis     │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ 3. Wait for pending orders      │ ← ZmqAdapter.get_pending_order_count()
│    - Timeout: 30 seconds        │   Log progress every 5s
│    - Log warning if timeout     │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ 4. Persist final state          │ ← SnapshotService.stop()
│    - Final snapshot all accounts│   Redis snapshot:{account}:latest
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ 5. Set clean shutdown flag      │ ← CrashRecoveryManager.shutdown_sequence()
│    - engine:shutdown:clean = ts │   Prevents crash recovery on restart
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ 6. Close connections            │ ← ZMQ, Redis, (future: TimescaleDB)
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ 7. Exit with code 0             │ ← sys.exit(0) or return
└─────────────────────────────────┘
```

### REDIS KEY PATTERNS

```
# Clean Shutdown Flag (existing - from Story 5.2)
Key: engine:shutdown:clean
Value: ISO timestamp of shutdown
TTL: None (cleared at startup)

# State Snapshot (existing - from Story 5.1)
Key: snapshot:{account_id}:latest
TTL: 1 hour (3600 seconds)

# Account Status (existing - from Epic 2)
Key: account:{account_id}:status
Value: "active" | "paused" | "stopped" | "error"
```

### ANTI-PATTERNS (What NOT to Do)

| Anti-Pattern | Why It's Wrong | Instead, Do This |
|--------------|----------------|------------------|
| Use signal.signal() in async | Not async-safe, may deadlock | Use loop.add_signal_handler() |
| Skip pending order wait | Orders may be partially executed | Always wait with timeout |
| Close Redis before snapshot | Snapshot fails without Redis | Persist state BEFORE closing |
| Exit without clean flag | Next startup triggers recovery | Always set clean shutdown flag |
| Ignore shutdown errors | Hard to debug issues | Log all errors, continue sequence |
| Block forever on pending orders | Shutdown never completes | Use 30s timeout |
| Assume method names without checking | AttributeError crashes at runtime | Verify methods exist in actual codebase via grep |
| Call undefined close() methods | Adapter may not have cleanup method | Add close() method or use correct existing method |

### TESTING COMMANDS

```bash
cd services/trading-engine

# Run unit tests
uv run pytest tests/unit/test_graceful_shutdown.py -v

# Run integration tests (requires Redis)
uv run pytest tests/integration/test_graceful_shutdown_redis.py -v

# Test signal handling manually
uv run python -c "
import asyncio
import signal
from src.state.graceful_shutdown import GracefulShutdown
# ... test setup ...
"

# Run with coverage
uv run pytest tests/unit/test_graceful_shutdown.py --cov=src/state

# Lint check
uv run ruff check src/state/graceful_shutdown.py
```

### TASK DEPENDENCIES

```
Task 1 (Module + Dataclasses) ──► Task 2 (Signal Handlers)
         │                               │
         ▼                               ▼
   Task 3 (Stop Signals) ──► Task 4 (Wait Orders)
                                    │
                                    ▼
                             Task 5 (Persist State)
                                    │
                                    ▼
                             Task 6 (Close Connections)
                                    │
                                    ▼
                             Task 7 (Orchestration)
                                    │
                                    ▼
                             Task 8 (Engine Integration)
                                    │
                                    ▼
                       Tasks 9-11 (CLI, Tests) ──► Task 12 (Docs)
```

### PERFORMANCE REQUIREMENTS

- Signal handler invocation: < 1ms (just sets event)
- Stop signal processing: < 5 seconds (stop account tasks)
- Pending order wait: configurable, default 30s max
- Final snapshot: < 2 seconds for 10 accounts
- Connection close: < 1 second total
- Full shutdown sequence: < 40 seconds worst case

### REFERENCES

- [docs/architecture.md#Graceful-Shutdown] - Shutdown sequence specification
- [docs/architecture.md#Signal-Handling] - Signal handler code pattern
- [docs/epics.md#Story-5.6] - Story requirements
- [src/state/crash_recovery.py:473] - shutdown_sequence() implementation
- [src/state/snapshot_service.py:105] - stop() method for final snapshot
- [Context7 AnyIO Signal Handling] - asyncio signal handler patterns
- [Context7 redis-py Async] - Async Redis cleanup patterns

## Dev Agent Record

**Story created:** 2026-01-15 via create-story workflow

**Context Analysis:**
- Story 5.6 is the 6th story in Epic 5 (State Persistence & Crash Recovery)
- Previous stories 5.1-5.5 are all DONE
- Story 5.7 (TimescaleDB Cold Storage) is next in backlog
- Engine already has basic shutdown() method that needs enhancement

**Context7 Research Summary (2026-01-15):**
- AnyIO/asyncio: Use `loop.add_signal_handler()` for async-safe signals
- redis-py: Use `await client.aclose()` for graceful Redis cleanup
- Pub/sub requires explicit unsubscribe before close

**Previous Story Learnings (Story 5.5):**
- Engine integration follows established pattern
- Lazy initialization of modules when needed
- Results stored as Engine properties
- Recovery sequence has specific order requirements

**Git Intelligence (Recent Commits):**
- 05ec4ef: Implement spec 5 story 5.5 (Trading Resume)
- 4678558: Implement spec 5 story 5.4 (Daily P&L Recalculation)
- Pattern: Create module, dataclasses, comprehensive tests, engine integration

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Context Reference

- Epic 5 context (State Persistence & Crash Recovery)
- Story 5.5 for Engine integration patterns
- Story 5.2 for CrashRecoveryManager.shutdown_sequence()
- Story 5.1 for SnapshotService.stop() pattern
- Architecture document for graceful shutdown sequence
- Context7 AnyIO/asyncio signal handling research (2026-01-15)
- Context7 redis-py async cleanup patterns (2026-01-15)

### Debug Log References

N/A - Story creation phase

### Completion Notes List

N/A - Ready for development

### File List

**Files to CREATE:**
| File | Purpose |
|------|---------|
| `services/trading-engine/src/state/graceful_shutdown.py` | GracefulShutdown class |
| `services/trading-engine/tests/unit/test_graceful_shutdown.py` | Unit tests |
| `services/trading-engine/tests/integration/test_graceful_shutdown_redis.py` | Integration tests |

**Files to MODIFY:**
| File | Changes |
|------|---------|
| `services/trading-engine/src/state/__init__.py` | Export GracefulShutdown, ShutdownPhase, ShutdownResult |
| `services/trading-engine/src/engine.py` | Integrate GracefulShutdown, update run() and shutdown() |
| `services/trading-engine/src/adapters/zmq_adapter.py` | Add close() method for graceful ZMQ cleanup |

---

## Definition of Done

**Prerequisites:**
- [x] Stories 5.1-5.5 complete and passing tests
- [x] SnapshotService.stop() method exists and works
- [x] CrashRecoveryManager.shutdown_sequence() exists

**Core Implementation:**
- [x] GracefulShutdown class created with all methods
- [x] ShutdownPhase enum and ShutdownResult dataclass defined
- [x] Signal handlers (SIGTERM, SIGINT) registered properly

**Shutdown Sequence:**
- [x] Stop signal processing works
- [x] Pending order wait with 30s timeout works
- [x] Final state snapshot persisted
- [x] Clean shutdown flag set via CrashRecoveryManager
- [x] All connections closed properly

**Engine Integration:**
- [x] Engine.run() uses GracefulShutdown.wait_for_shutdown_signal()
- [x] Engine.shutdown() triggers GracefulShutdown
- [x] Signal handlers registered after engine initialization

**Testing:**
- [x] Unit tests for all shutdown phases
- [x] Integration tests with Redis
- [x] Clean restart after shutdown doesn't trigger recovery
- [x] All tests passing

**Acceptance Criteria Verification:**
- [x] AC1: Full shutdown sequence executes in order
- [x] AC2: Pending orders logged and waited for
- [x] AC3: Timeout triggers warning and continues
- [x] AC4: SIGTERM/SIGINT triggers same shutdown as CLI
- [x] AC5: Exit code 0 on success
- [x] AC6: Clean restart has no crash recovery

---
