# Story 5.2: Crash Detection and Recovery Initiation

Status: Done

## Story

As a **developer**,
I want **the engine to detect previous crashes and initiate recovery**,
So that **trading resumes safely after unexpected shutdowns**.

## Acceptance Criteria

1. **AC1**: Given the trading engine starts, when it checks for crash indicators, then it looks for:
   - Existing snapshots without clean shutdown flag
   - Stale heartbeat keys in Redis (key expired = previous instance crashed)
   - Process lock files (out of scope for this story - Redis lock sufficient)

2. **AC2**: Given crash indicators are found, when recovery mode is initiated, then the log shows: "Recovery mode: Previous session did not shut down cleanly" and normal startup is paused until recovery completes.

3. **AC3**: Given no crash indicators are found, when the engine starts, then normal startup proceeds and fresh state is initialized.

4. **AC4**: Given recovery mode is active, when the engine completes recovery, then the crash indicators are cleared and normal operation resumes.

5. **AC5**: Given a graceful shutdown occurs, when stop() is called, then the clean shutdown flag is set in Redis before process exits.

6. **AC6**: Given the engine starts and acquires the process lock, when another instance tries to start, then it fails with error message containing "Another instance is already running" and exits.

7. **AC7**: Given engine crash detection runs, when any account has a snapshot but no clean shutdown flag, then that account is flagged for recovery.

## Tasks / Subtasks

### Task 1: Create CrashRecovery Module (AC: 1, 2, 3, 4)

- [x] 1.1: Create `src/state/crash_recovery.py` with `CrashRecoveryManager` class
- [x] 1.2: Define crash indicator detection methods:
  ```python
  class CrashRecoveryManager:
      SHUTDOWN_FLAG_KEY = "engine:shutdown:clean"
      PROCESS_LOCK_KEY = "engine:lock:process"
      HEARTBEAT_TTL_SECONDS = 30
      LOCK_TTL_SECONDS = 60

      def __init__(
          self,
          redis_manager: RedisStateManager,
          account_manager: AccountManager,
      ):
          self._redis = redis_manager
          self._account_manager = account_manager
          self._recovery_mode = False

      async def check_crash_indicators(self) -> CrashIndicatorResult:
          """Check for indicators of previous unclean shutdown.

          Returns:
              CrashIndicatorResult with detected indicators
          """

      async def initiate_recovery(self, indicators: CrashIndicatorResult) -> None:
          """Start recovery process for detected crash indicators."""

      async def clear_crash_indicators(self) -> None:
          """Clear all crash indicators after successful recovery."""
  ```
- [x] 1.3: Implement `CrashIndicatorResult` dataclass:
  ```python
  @dataclass
  class CrashIndicatorResult:
      has_crash: bool
      missing_shutdown_flag: bool
      stale_heartbeat: bool
      orphan_snapshots: list[str]  # Account IDs with snapshots but no clean shutdown
      details: str
  ```
- [x] 1.4: Implement `_check_stale_heartbeat()` for detecting crashed instances:
  ```python
  async def _check_stale_heartbeat(self) -> bool:
      """Check for stale/missing heartbeat indicating previous instance died.

      Stale heartbeat detection logic:
      - If PROCESS_LOCK_KEY exists but we can't acquire it = another instance running (not crash)
      - If PROCESS_LOCK_KEY doesn't exist (TTL expired) AND shutdown flag missing = crash
      - The lock key has 60s TTL, refreshed every 15s by heartbeat
      - If process crashes, heartbeat stops, lock expires after 60s max

      Returns:
          True if stale heartbeat detected (crash indicator), False otherwise
      """
      lock_exists = await self._redis.client.exists(self.PROCESS_LOCK_KEY) > 0
      shutdown_clean = await self.has_clean_shutdown_flag()

      # If lock doesn't exist AND no clean shutdown = previous instance crashed
      # The lock expired because heartbeat stopped (crash)
      if not lock_exists and not shutdown_clean:
          return True
      return False
  ```
- [x] 1.5: Implement `check_crash_indicators()` method (use `_check_stale_heartbeat()` and `has_clean_shutdown_flag()`)
- [x] 1.6: Implement `initiate_recovery()` method with logging
- [x] 1.7: Implement `clear_crash_indicators()` method

### Task 2: Implement Clean Shutdown Flag (AC: 3, 4, 5)

- [x] 2.1: Implement `async def set_clean_shutdown_flag()`:
  ```python
  async def set_clean_shutdown_flag(self) -> None:
      """Set flag indicating clean shutdown in progress.

      Called during graceful shutdown to indicate clean exit.
      Key pattern: engine:shutdown:clean
      Value: timestamp of shutdown
      TTL: None (cleared at startup)
      """
      await self._redis.client.set(
          self.SHUTDOWN_FLAG_KEY,
          datetime.now(timezone.utc).isoformat(),
      )
  ```
- [x] 2.2: Implement `async def clear_clean_shutdown_flag()`:
  ```python
  async def clear_clean_shutdown_flag(self) -> None:
      """Clear clean shutdown flag at startup.

      If flag exists at startup, previous shutdown was clean.
      Absence of flag after startup = crash recovery needed.
      """
      await self._redis.client.delete(self.SHUTDOWN_FLAG_KEY)
  ```
- [x] 2.3: Implement `async def has_clean_shutdown_flag()`:
  ```python
  async def has_clean_shutdown_flag(self) -> bool:
      """Check if clean shutdown flag exists.

      Returns:
          True if previous shutdown was clean, False if crash/kill
      """
      return await self._redis.client.exists(self.SHUTDOWN_FLAG_KEY) > 0
  ```

### Task 3: Implement Process Lock (AC: 6)

- [x] 3.1: Implement `async def acquire_process_lock()`:
  ```python
  async def acquire_process_lock(self) -> bool:
      """Acquire exclusive process lock using Redis SET NX EX.

      Prevents multiple engine instances from running simultaneously.
      Lock auto-expires after LOCK_TTL_SECONDS if process dies.

      Returns:
          True if lock acquired, False if another instance running

      Key pattern: engine:lock:process
      Value: hostname:pid:timestamp
      TTL: 60 seconds (auto-renewed by heartbeat)
      """
      import os
      import socket

      lock_value = f"{socket.gethostname()}:{os.getpid()}:{datetime.now(timezone.utc).isoformat()}"
      result = await self._redis.client.set(
          self.PROCESS_LOCK_KEY,
          lock_value,
          nx=True,
          ex=self.LOCK_TTL_SECONDS,
      )
      return result is True
  ```
- [x] 3.2: Implement `async def release_process_lock()`:
  ```python
  async def release_process_lock(self) -> None:
      """Release process lock on graceful shutdown."""
      await self._redis.client.delete(self.PROCESS_LOCK_KEY)
  ```
- [x] 3.3: Implement `async def refresh_process_lock()`:
  ```python
  async def refresh_process_lock(self) -> bool:
      """Refresh process lock TTL (call from heartbeat loop).

      Returns:
          True if lock refreshed, False if lost (should exit)
      """
      result = await self._redis.client.expire(
          self.PROCESS_LOCK_KEY,
          self.LOCK_TTL_SECONDS,
      )
      return result > 0
  ```

### Task 4: Implement Heartbeat with Lock Renewal (AC: 1, 6)

- [x] 4.1: Implement `async def start_heartbeat()`:
  ```python
  async def start_heartbeat(self) -> None:
      """Start background heartbeat task that renews process lock.

      Heartbeat interval: HEARTBEAT_TTL_SECONDS / 2 (15 seconds)
      """
      self._heartbeat_running = True
      self._heartbeat_task = asyncio.create_task(
          self._heartbeat_loop(),
          name="crash-recovery-heartbeat",
      )
  ```
- [x] 4.2: Implement `async def stop_heartbeat()`:
  ```python
  async def stop_heartbeat(self) -> None:
      """Stop heartbeat task."""
      self._heartbeat_running = False
      if self._heartbeat_task:
          self._heartbeat_task.cancel()
          try:
              await self._heartbeat_task
          except asyncio.CancelledError:
              pass
  ```
- [x] 4.3: Implement `async def _heartbeat_loop()`:
  ```python
  async def _heartbeat_loop(self) -> None:
      """Background loop that refreshes process lock."""
      interval = self.HEARTBEAT_TTL_SECONDS / 2  # 15 seconds
      while self._heartbeat_running:
          try:
              if not await self.refresh_process_lock():
                  logger.critical("Lost process lock! Another instance may be running.")
                  # Trigger emergency shutdown
                  break
          except Exception as e:
              logger.error("Heartbeat failed: %s", e)
          await asyncio.sleep(interval)
  ```

### Task 5: Recovery Account Detection (AC: 1, 7)

- [x] 5.1: Implement `async def get_accounts_needing_recovery()`:
  ```python
  async def get_accounts_needing_recovery(self) -> list[str]:
      """Get list of account IDs that have snapshots needing recovery.

      Scans for snapshot:*:latest keys and returns account IDs.
      These accounts had state at crash and need position reconciliation.

      Returns:
          List of account IDs with existing snapshots
      """
      account_ids = []
      async for key in self._redis.client.scan_iter("snapshot:*:latest"):
          # Extract account_id from key pattern snapshot:{id}:latest
          parts = key.split(":")
          if len(parts) == 3:
              account_ids.append(parts[1])
      return account_ids
  ```
- [x] 5.2: Implement snapshot validation during recovery:
  ```python
  async def validate_snapshot_for_recovery(
      self, account_id: str
  ) -> tuple[bool, StateSnapshot | None]:
      """Validate snapshot is usable for recovery.

      Checks:
      - Snapshot exists
      - Checksum is valid
      - Timestamp is recent enough (within 1 hour)

      Returns:
          (is_valid, snapshot) tuple
      """
      snapshot = await self._redis.get_snapshot(account_id)
      if snapshot is None:
          return False, None

      if not snapshot.validate_checksum():
          logger.warning(
              "Snapshot checksum invalid for %s, will need fresh state",
              account_id,
          )
          return False, None

      return True, snapshot
  ```

### Task 6: Integration with Engine Startup (AC: 2, 3, 4)

- [x] 6.1: Create startup sequence integration:
  ```python
  async def startup_sequence(self) -> RecoveryResult:
      """Execute full startup sequence with crash detection.

      Sequence:
      1. Check for crash indicators
      2. If crash detected, enter recovery mode
      3. Acquire process lock (fail if another instance)
      4. Clear old shutdown flag
      5. Start heartbeat
      6. Return recovery accounts list

      Returns:
          RecoveryResult with status and accounts needing recovery
      """
      # Check for crash indicators
      indicators = await self.check_crash_indicators()

      if indicators.has_crash:
          logger.warning(
              "Recovery mode: Previous session did not shut down cleanly. %s",
              indicators.details,
          )
          self._recovery_mode = True

      # Acquire process lock
      if not await self.acquire_process_lock():
          raise RuntimeError(
              "Another instance is already running. Cannot start engine."
          )

      # Clear shutdown flag (we're starting fresh)
      await self.clear_clean_shutdown_flag()

      # Start heartbeat
      await self.start_heartbeat()

      # Return recovery info
      recovery_accounts = await self.get_accounts_needing_recovery()

      return RecoveryResult(
          recovery_mode=self._recovery_mode,
          accounts_needing_recovery=recovery_accounts,
          indicators=indicators,
      )
  ```
- [x] 6.2: Create shutdown sequence integration:
  ```python
  async def shutdown_sequence(self) -> None:
      """Execute graceful shutdown sequence.

      Sequence:
      1. Stop heartbeat
      2. Set clean shutdown flag
      3. Release process lock
      """
      await self.stop_heartbeat()
      await self.set_clean_shutdown_flag()
      await self.release_process_lock()
      logger.info("Graceful shutdown completed with clean flag set")
  ```
- [x] 6.3: Create `RecoveryResult` dataclass:
  ```python
  @dataclass
  class RecoveryResult:
      recovery_mode: bool
      accounts_needing_recovery: list[str]
      indicators: CrashIndicatorResult
  ```

### Task 7: Unit Tests (AC: 1-7)

- [x] 7.1: Create `tests/unit/test_crash_recovery.py`
- [x] 7.2: Test crash indicator detection when no shutdown flag exists
- [x] 7.3: Test crash indicator detection when clean shutdown flag exists
- [x] 7.4: Test process lock acquisition success
- [x] 7.5: Test process lock acquisition failure (another instance)
- [x] 7.6: Test process lock refresh
- [x] 7.7: Test heartbeat loop starts and stops correctly
- [x] 7.8: Test accounts needing recovery detection from snapshots
- [x] 7.9: Test full startup sequence
- [x] 7.10: Test full shutdown sequence
- [x] 7.11: Test snapshot validation for recovery

### Task 8: Integration Tests (AC: 1-7)

- [x] 8.1: Create `tests/integration/test_crash_recovery_redis.py`
- [x] 8.2: Test shutdown flag persistence in Redis
- [x] 8.3: Test process lock atomic acquisition with SET NX EX
- [x] 8.4: Test lock TTL expiration behavior
- [x] 8.5: Test snapshot scan for recovery accounts
- [x] 8.6: Test full startup/shutdown cycle with Redis
- [x] 8.7: Test concurrent instance prevention

### Task 9: Documentation and Exports (AC: 1-7)

- [x] 9.1: Add docstrings to all CrashRecoveryManager methods
- [x] 9.2: Update `state/__init__.py` with new exports
- [x] 9.3: Document Redis key patterns for crash detection
- [x] 9.4: Create recovery flow diagram in docstrings

## Dev Notes

### CRITICAL: FULL FILE PATHS (Monorepo Structure)

**All paths are relative to project root `/home/hopdev/Dev/Sandboxed/`:**

| Full Path | Action | Purpose |
|-----------|--------|---------|
| **New Files** | | |
| `services/trading-engine/src/state/crash_recovery.py` | CREATE | CrashRecoveryManager class |
| `services/trading-engine/tests/unit/test_crash_recovery.py` | CREATE | Unit tests for crash detection |
| `services/trading-engine/tests/integration/test_crash_recovery_redis.py` | CREATE | Redis integration tests |
| **Modify Files** | | |
| `services/trading-engine/src/state/__init__.py` | MODIFY | Add crash recovery exports |
| `services/trading-engine/src/engine.py` | MODIFY | Integrate startup/shutdown sequences |

### PREREQUISITES (Story 5.1 Complete)

**From Story 5.1:**
- `RedisStateManager` at `src/state/redis_state.py` with async operations
- `StateSnapshot` at `src/state/snapshot.py` for snapshot model
- `get_snapshot()` method on RedisStateManager for snapshot retrieval
- `validate_checksum()` method on StateSnapshot for integrity check

**Key integration points:**
- `RedisStateManager.client` → async Redis client for SET NX EX operations
- `AccountManager.get_all_accounts()` → list of account IDs
- `StateSnapshot.validate_checksum()` → verify snapshot integrity

**Required imports for CrashRecoveryManager:**
```python
from src.state.redis_state import RedisStateManager
from src.state.snapshot import StateSnapshot
from src.accounts.account_manager import AccountManager
```

### CONTEXT7 RESEARCH SUMMARY (Redis-py 2026-01-03)

**Distributed Lock Pattern (SET NX EX):**
```python
import redis.asyncio as aioredis

# Atomic lock acquisition with expiration
result = await r.set(
    "engine:lock:process",
    "hostname:pid:timestamp",
    nx=True,  # Only set if key doesn't exist
    ex=60,    # Auto-expire after 60 seconds
)
if result:
    print("Lock acquired")
else:
    print("Another instance running")
```

**Lock Renewal (Heartbeat):**
```python
# Refresh lock TTL from heartbeat loop
success = await r.expire("engine:lock:process", 60)
if not success:
    # Lost the lock - emergency shutdown needed
    raise RuntimeError("Lost process lock")
```

**Python-Redis-Lock Pattern (Reference):**
```python
# From ionelmc/python-redis-lock - auto-renewal pattern
lock = redis_lock.Lock(conn, "name", expire=60, auto_renewal=True)
with lock:
    # Lock auto-renewed while held
    do_work()
```

**Crash Recovery Best Practices:**
```python
# On startup: check for clean shutdown flag
clean_shutdown = await r.exists("engine:shutdown:clean") > 0
if not clean_shutdown:
    # Previous instance crashed - enter recovery mode
    logger.warning("Recovery mode: Previous session crashed")

# On graceful shutdown: set flag and release lock
await r.set("engine:shutdown:clean", datetime.now().isoformat())
await r.delete("engine:lock:process")
```

### REDIS KEY PATTERNS FOR CRASH DETECTION

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `engine:shutdown:clean` | String | None | Clean shutdown flag (ISO timestamp) |
| `engine:lock:process` | String | 60s | Process lock (hostname:pid:timestamp) |
| `snapshot:{account_id}:latest` | Hash | 3600s | State snapshots (from 5.1) |

### CRASH DETECTION FLOW

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Engine Startup Sequence                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   1. Check engine:shutdown:clean exists?                             │
│      ├── YES: Previous shutdown was clean → Normal startup          │
│      └── NO: Previous session crashed → Enter recovery mode         │
│                                                                      │
│   2. Try SET engine:lock:process NX EX 60                           │
│      ├── SUCCESS: Lock acquired → Continue                          │
│      └── FAILURE: Another instance running → Exit with error        │
│                                                                      │
│   3. DELETE engine:shutdown:clean (clear for next cycle)            │
│                                                                      │
│   4. Start heartbeat (EXPIRE lock every 15 seconds)                 │
│                                                                      │
│   5. SCAN snapshot:*:latest → Get accounts needing recovery         │
│                                                                      │
│   6. Return RecoveryResult for caller to handle                     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### GRACEFUL SHUTDOWN FLOW

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Graceful Shutdown Sequence                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   1. Stop heartbeat task                                             │
│                                                                      │
│   2. SET engine:shutdown:clean (timestamp)                          │
│      → Signals next startup that shutdown was clean                 │
│                                                                      │
│   3. DELETE engine:lock:process                                     │
│      → Release lock for next instance                               │
│                                                                      │
│   4. Log "Graceful shutdown completed"                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### ANTI-PATTERNS (What NOT to Do)

| Anti-Pattern | Why It's Wrong | Instead, Do This |
|--------------|----------------|------------------|
| Lock without TTL | Dead process = stuck lock forever | Always use SET NX EX with TTL |
| Check-then-set for lock | Race condition | Use SET NX (atomic) |
| Skip heartbeat | Lock expires during long operations | Heartbeat at TTL/2 interval |
| Ignore lost lock | Multiple instances corrupt state | Exit immediately if lock lost |
| Clear shutdown flag on crash | Flag used to detect crash | Only clear at startup |
| Store lock value without identity | Can't verify ownership | Include hostname:pid |
| Silently handle Redis connection failures | Crash detection impossible without Redis | Fail fast with clear error; Redis is required for startup |
| Retry indefinitely on Redis unavailable | Blocks startup forever | Set connection timeout (5s), fail with actionable error message |

### EXISTING CODE PATTERNS TO REUSE

**From SnapshotService (src/state/snapshot_service.py):**
```python
# Background task pattern (reuse for heartbeat)
self._task = asyncio.create_task(
    self._heartbeat_loop(),
    name="crash-recovery-heartbeat",
)

# Graceful stop pattern
self._running = False
if self._task is not None:
    self._task.cancel()
    try:
        await self._task
    except asyncio.CancelledError:
        pass
```

**From RedisStateManager (src/state/redis_state.py):**
```python
# Pattern for scanning keys (REUSE in get_accounts_needing_recovery)
# This pattern is established in Story 5.1 - use it for snapshot scanning
async for key in self.client.scan_iter("snapshot:*:latest"):
    parts = key.split(":")
    if len(parts) == 3:
        account_id = parts[1]
```

### ENGINE.PY INTEGRATION GUIDE

**Integration Location:** `services/trading-engine/src/engine.py`

**In the Engine class `start()` method, add crash recovery FIRST:**
```python
from src.state.crash_recovery import CrashRecoveryManager, RecoveryResult
from src.accounts.account_manager import AccountManager

class Engine:
    async def start(self) -> None:
        """Start the trading engine with crash recovery check."""
        # 1. Initialize CrashRecoveryManager BEFORE other components
        self._crash_recovery = CrashRecoveryManager(
            redis_manager=self._redis_state,
            account_manager=self._account_manager,
        )

        # 2. Run startup sequence - this checks for crashes and acquires lock
        try:
            recovery_result = await self._crash_recovery.startup_sequence()
        except RuntimeError as e:
            # Another instance running - exit immediately
            logger.critical("Engine startup failed: %s", e)
            raise SystemExit(1)

        # 3. Handle recovery mode if needed
        if recovery_result.recovery_mode:
            logger.warning("Entering recovery mode for %d accounts",
                          len(recovery_result.accounts_needing_recovery))
            # Story 5.3 will implement position reconciliation here

        # 4. Continue normal startup (strategies, adapters, etc.)
        await self._initialize_components()
```

**In the Engine class `stop()` method, add graceful shutdown:**
```python
    async def stop(self) -> None:
        """Stop the engine with graceful shutdown."""
        logger.info("Initiating graceful shutdown...")

        # 1. Stop accepting new signals
        await self._signal_router.stop()

        # 2. Wait for in-flight orders (if any)
        # ... existing shutdown logic ...

        # 3. Run crash recovery shutdown sequence LAST
        if self._crash_recovery:
            await self._crash_recovery.shutdown_sequence()

        logger.info("Engine stopped successfully")
```

### TESTING COMMANDS

```bash
cd services/trading-engine

# Run unit tests
uv run pytest tests/unit/test_crash_recovery.py -v

# Run integration tests (requires Redis)
uv run pytest tests/integration/test_crash_recovery_redis.py -v

# Run with coverage
uv run pytest tests/unit/test_crash_recovery.py --cov=src/state

# Lint check
uv run ruff check src/state/crash_recovery.py
```

### TASK DEPENDENCIES (Execute in Order)

```
Task 1 (CrashRecoveryManager) ──► Task 2 (Shutdown Flag)
         │                              │
         ▼                              ▼
   Task 3 (Process Lock) ◄──────────────┘
         │
         ▼
   Task 4 (Heartbeat) ──► Task 5 (Account Detection)
         │                         │
         ▼                         ▼
   Task 6 (Engine Integration) ◄───┘
         │
         ▼
   Tasks 7-8 (Tests) ──► Task 9 (Docs)
```

### PERFORMANCE REQUIREMENTS

- Crash detection: < 50ms (Redis key checks only)
- Process lock acquisition: < 10ms (single SET NX)
- Snapshot scan for recovery: < 100ms (SCAN with small result set)
- Heartbeat interval: 15 seconds (half of 30s lock TTL)

### REFERENCES

- [docs/epic-5-context.md] - Epic 5 technical context
- [docs/architecture.md#Crash-Recovery-Sequence] - Recovery flow diagram
- [docs/architecture.md#Redis-Data-Structures] - Redis key patterns
- [docs/epics.md#Story-5.2] - Story requirements and acceptance criteria
- [src/state/redis_state.py] - Existing Redis patterns
- [src/state/snapshot_service.py] - Background task patterns
- [Context7 redis-py 2026-01-03] - SET NX EX, lock patterns
- [Context7 python-redis-lock] - Auto-renewal, reset patterns

## Dev Agent Record

**Story created:** 2026-01-03 via create-story workflow

**Context Analysis:**
- Story 5.2 depends on Story 5.1 (Redis State Snapshots) - COMPLETED
- Epic 5 focused on State Persistence & Crash Recovery
- This story implements the detection and initiation phase
- Story 5.3 (Position Reconciliation) depends on this story

**Context7 Research Summary:**
- redis-py: SET with NX and EX for atomic lock acquisition
- Lock renewal via EXPIRE command in heartbeat loop
- python-redis-lock: auto_renewal pattern for long-running locks
- Crash detection via absence of clean shutdown flag

**Previous Story Learnings (Story 5.1):**
- asyncio.create_task pattern works well for background services
- SCAN with pattern matching for finding snapshot keys
- StateSnapshot.validate_checksum() for integrity verification
- Graceful stop pattern with task cancellation

**Git Intelligence (Recent Commits):**
- 08609a6: Implement spec 5 story 5.1 (Redis State Snapshots)
- Pattern: create service class with start/stop, background loop, graceful shutdown

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Context Reference

- Epic 5 context document (docs/epic-5-context.md)
- Story 5.1 (previous story) for patterns and integration points
- Context7 redis-py and python-redis-lock research (2026-01-03)
- Architecture document crash recovery section

### Debug Log References

No blocking issues encountered during implementation.

### Completion Notes List

- ✅ Created CrashRecoveryManager with full crash detection and recovery initiation
- ✅ Implemented Redis-based process lock with SET NX EX (atomic acquisition with TTL)
- ✅ Implemented heartbeat task that refreshes lock every 15 seconds (half of 30s TTL)
- ✅ Clean shutdown flag mechanism to detect clean vs crash exits
- ✅ Startup sequence integrates crash detection before other engine components
- ✅ Shutdown sequence sets clean flag and releases lock
- ✅ Engine integration via optional redis_manager parameter for backwards compatibility
- ✅ 49 unit tests passing for all crash recovery functionality (6 added in review)
- ✅ 23 integration tests for real Redis operations (require live Redis instance)
- ✅ Full regression suite passes (1389+ unit tests)

### Code Review Fixes Applied (2026-01-03)

| Issue | Severity | Fix Applied |
|-------|----------|-------------|
| Missing timestamp recency check in `validate_snapshot_for_recovery` | HIGH | Added 1-hour max age check with `SNAPSHOT_MAX_AGE_SECONDS` constant |
| Heartbeat did not trigger emergency shutdown | HIGH | Added `on_lock_lost` callback to CrashRecoveryManager, engine registers handler |
| Double SCAN in startup_sequence | MEDIUM | Reused `orphan_snapshots` from `check_crash_indicators()` instead of calling `get_accounts_needing_recovery()` again |
| Engine raised RuntimeError instead of SystemExit(1) | MEDIUM | Changed to `raise SystemExit(1) from e` per story spec |
| Missing log message verification tests for AC2 | MEDIUM | Added 2 new tests in `TestRecoveryModeLogging` class |
| Missing tests for timestamp recency | LOW | Added 2 new tests for too-old and recent-enough snapshots |
| Missing tests for lock lost callback | LOW | Added 2 new tests in `TestLockLostCallback` class |

### File List

**Files CREATED:**
| File | Purpose |
|------|---------|
| `services/trading-engine/src/state/crash_recovery.py` | CrashRecoveryManager with lock, heartbeat, detection |
| `services/trading-engine/tests/unit/test_crash_recovery.py` | 43 unit tests for crash detection logic |
| `services/trading-engine/tests/integration/test_crash_recovery_redis.py` | 23 Redis integration tests |

**Files MODIFIED:**
| File | Changes |
|------|---------|
| `services/trading-engine/src/state/__init__.py` | Added CrashRecoveryManager, CrashIndicatorResult, RecoveryResult exports |
| `services/trading-engine/src/engine.py` | Added crash recovery integration with startup_sequence() and shutdown_sequence() |

**Dependencies injected into CrashRecoveryManager:**
| Dependency | Source | Purpose |
|------------|--------|---------|
| `RedisStateManager` | `src/state/redis_state.py` | Redis client for lock/flag operations |

---

## Definition of Done

**Core Implementation:**
- [x] CrashRecoveryManager class created with all detection methods
- [x] Clean shutdown flag set/clear/check methods implemented
- [x] Process lock acquire/release/refresh methods implemented
- [x] Heartbeat task with lock renewal implemented

**Crash Detection:**
- [x] Detects missing clean shutdown flag
- [x] Detects stale process lock
- [x] Scans for accounts with existing snapshots
- [x] Returns structured CrashIndicatorResult

**Engine Integration:**
- [x] startup_sequence() method for engine initialization
- [x] shutdown_sequence() method for graceful exit
- [x] RecoveryResult returned with recovery accounts

**Single Instance Enforcement:**
- [x] SET NX EX for atomic lock acquisition
- [x] Heartbeat renews lock TTL
- [x] Lost lock triggers emergency handling
- [x] Another instance blocked from starting

**Testing:**
- [x] Unit tests for all detection methods
- [x] Unit tests for lock operations
- [x] Unit tests for heartbeat task
- [x] Integration tests with Redis
- [x] Concurrent instance prevention test

**Acceptance Criteria Verification:**
- [x] AC1: Crash indicators detected (shutdown flag, heartbeat, snapshots)
- [x] AC2: Recovery mode logged when crash detected
- [x] AC3: Normal startup when no crash
- [x] AC4: Crash indicators cleared after recovery
- [x] AC5: Clean shutdown flag set on graceful exit
- [x] AC6: Second instance fails to start
- [x] AC7: Per-account recovery flagging from snapshots

---
