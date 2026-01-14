# Story 5.5: Trading Resume After Recovery

Status: Done

## Story

As a **trader**,
I want **trading to automatically resume after successful recovery**,
So that **I don't miss trading opportunities during recovery**.

## Acceptance Criteria

1. **AC1**: Given all recovery steps complete successfully (snapshot loaded, MT5 connected, positions reconciled, P&L recalculated), when the recovery sequence finishes, then trading resumes for all previously active accounts.

2. **AC2**: Given Account A was "active" before crash, when recovery completes, then Account A status is set to "active" AND signal processing begins for Account A.

3. **AC3**: Given Account B was "paused" before crash, when recovery completes, then Account B remains "paused" AND no signal processing for Account B.

4. **AC4**: Given Account C required manual intervention during reconciliation, when recovery completes, then Account C remains in "error" state AND does NOT resume trading.

5. **AC5**: Given recovery completes, when I check account status, then I see: "Recovery successful. Trading resumed for X accounts" with recovery duration logged.

6. **AC6**: Given recovery completes successfully, when accounts resume, then a notification is sent via Redis pub/sub: "Recovery complete: X accounts resumed trading".

## Tasks / Subtasks

### Task 1: Create TradingResumer Module (AC: 1, 2, 3, 4)

- [x] 1.1: Create `src/state/trading_resumer.py` with `TradingResumer` class and required imports:
  ```python
  """Trading resume module for crash recovery.

  Handles resuming trading operations after successful crash recovery.
  """
  from __future__ import annotations

  import json
  import logging
  from dataclasses import dataclass
  from datetime import datetime, timedelta, timezone
  from typing import TYPE_CHECKING

  if TYPE_CHECKING:
      from ..accounts.account_manager import AccountManager
      from .daily_pnl_recalculator import RecalculationResult
      from .position_reconciler import ReconciliationResult
      from .redis_state import RedisStateManager

  logger = logging.getLogger(__name__)
  ```
- [x] 1.2: Define resume result data structures:
  ```python
  from dataclasses import dataclass
  from datetime import datetime, timedelta

  @dataclass
  class AccountResumeResult:
      """Result of attempting to resume a single account.

      Attributes:
          account_id: Account that was processed
          resumed: True if account was resumed to active trading
          previous_status: Status before crash (from snapshot)
          current_status: Status after resume attempt
          reason: Why account was/wasn't resumed
      """
      account_id: str
      resumed: bool
      previous_status: str
      current_status: str
      reason: str

  @dataclass
  class ResumeResult:
      """Result of trading resume operation after recovery.

      Attributes:
          success: True if resume completed without errors
          accounts_resumed: Number of accounts that resumed trading
          accounts_skipped: Number of accounts that remained paused/stopped
          accounts_blocked: Number of accounts blocked due to manual intervention
          recovery_duration: Time from crash detection to trading resume
          account_results: Per-account resume results
          notification_sent: True if notification was published
      """
      success: bool
      accounts_resumed: int
      accounts_skipped: int
      accounts_blocked: int
      recovery_duration: timedelta
      account_results: list[AccountResumeResult]
      notification_sent: bool
  ```
- [x] 1.3: Implement `TradingResumer` class skeleton:
  ```python
  class TradingResumer:
      """Resumes trading operations after successful crash recovery.

      This class handles the final step of the recovery sequence:
      1. Determine which accounts should resume trading
      2. Restore account status based on pre-crash state
      3. Start signal processing for active accounts
      4. Send notification about recovery completion

      CRITICAL: Only resumes accounts that:
      - Were "active" before crash (from snapshot)
      - Passed position reconciliation successfully
      - Passed P&L recalculation successfully

      Accounts that were "paused" or "stopped" before crash remain
      in their pre-crash state - they are NOT auto-started.

      Example:
          resumer = TradingResumer(
              redis_manager=redis_manager,
              account_manager=account_manager,
          )
          result = await resumer.resume_trading_after_recovery(
              reconciliation_results=recon_results,
              pnl_results=pnl_results,
              recovery_start_time=start_time,
          )
      """

      def __init__(
          self,
          redis_manager: RedisStateManager,
          account_manager: AccountManager,
      ) -> None:
          """Initialize TradingResumer.

          Args:
              redis_manager: Redis state manager for snapshot access and notifications
              account_manager: Account manager for starting account tasks
          """
          self._redis = redis_manager
          self._account_manager = account_manager
  ```

### Task 2: Get Pre-Crash Account Status (AC: 2, 3)

**⚠️ CRITICAL NOTE ON PRE-CRASH STATUS:**
The account status in Redis (`account:{account_id}:status`) represents the CURRENT status,
which is preserved through crash recovery. Since recovery does NOT modify account status
until trading resumes (this story), the current Redis status IS the pre-crash status.

However, if a future story modifies status during recovery, this assumption breaks.
For robustness, consider storing pre-crash status at recovery start.

- [x] 2.1: Implement `_get_pre_crash_status()` method:
  ```python
  async def _get_pre_crash_status(self, account_id: str) -> str | None:
      """Get account status from before crash.

      IMPORTANT: This reads the current Redis status, which represents
      the pre-crash state because:
      1. Story 5.3 (reconciliation) does NOT modify account status
      2. Story 5.4 (P&L recalc) does NOT modify account status
      3. Account status is only modified by THIS story during resume

      If this assumption changes, consider:
      - Storing pre-crash status in CrashRecoveryManager at recovery start
      - Adding account_status field to StateSnapshot

      Args:
          account_id: Account to get pre-crash status for

      Returns:
          Pre-crash status string ("active", "paused", "stopped", "error")
          Returns "stopped" if status cannot be determined
      """
      status = await self._redis.get_account_status(account_id)
      if status is None:
          logger.warning(
              "No pre-crash status found for %s, defaulting to 'stopped'",
              account_id,
          )
          return "stopped"
      return status
  ```
- [x] 2.2: Handle case where status is missing (default to "stopped")

### Task 3: Determine Resume Eligibility (AC: 1, 2, 3, 4)

- [x] 3.1: Implement `_should_resume_account()` method:
  ```python
  async def _should_resume_account(
      self,
      account_id: str,
      reconciliation_result: ReconciliationResult | None,
      pnl_result: RecalculationResult | None,
  ) -> tuple[bool, str]:
      """Determine if account should resume trading.

      Resume conditions (ALL must be true):
      1. Pre-crash status was "active"
      2. Position reconciliation succeeded (no manual intervention)
      3. P&L recalculation succeeded (or was skipped with valid reason)

      Args:
          account_id: Account to evaluate
          reconciliation_result: Result from position reconciliation (Story 5.3)
          pnl_result: Result from P&L recalculation (Story 5.4)

      Returns:
          (should_resume, reason) tuple
      """
      # Check pre-crash status
      pre_crash_status = await self._get_pre_crash_status(account_id)

      if pre_crash_status != "active":
          return False, f"Pre-crash status was '{pre_crash_status}', not 'active'"

      # Check reconciliation result
      if reconciliation_result is not None:
          if reconciliation_result.requires_manual_intervention:
              return False, "Requires manual intervention after reconciliation"
          if not reconciliation_result.success:
              return False, f"Reconciliation failed: {reconciliation_result.discrepancies}"

      # Check P&L recalculation result
      if pnl_result is not None:
          if not pnl_result.success:
              # P&L failure uses fallback - still safe to resume
              logger.warning(
                  "P&L recalculation failed for %s, using snapshot values",
                  account_id,
              )

      return True, "All recovery checks passed"
  ```
- [x] 3.2: Log detailed reason for each skip/block decision

### Task 4: Resume Account Trading (AC: 2, 5)

**NOTE ON PRIVATE METHOD ACCESS:**
This task uses `AccountManager._spawn_account_task()` which is a private method.
This is acceptable because:
1. No public equivalent exists for spawning a single account task
2. The method is stable and well-documented in AccountManager
3. TradingResumer is part of the same codebase/package

Consider adding a public `resume_account_after_recovery()` method to AccountManager
in a future refactoring story for cleaner API design.

- [x] 4.1: Implement `_resume_account()` method:
  ```python
  async def _resume_account(self, account_id: str) -> AccountResumeResult:
      """Resume trading for a single account.

      Steps:
      1. Spawn account task via AccountManager (sets status to active)
      2. Log successful resume

      CRITICAL: Uses AccountManager._spawn_account_task() which:
      - Initializes rules for the account
      - Creates asyncio task for account loop
      - Sets up signal processing
      - Sets account status to "active" in Redis

      Args:
          account_id: Account to resume

      Returns:
          AccountResumeResult with details
      """
      try:
          # Get pre-crash status for logging
          pre_crash_status = await self._get_pre_crash_status(account_id)

          # Spawn account task (this also sets status to active)
          await self._account_manager._spawn_account_task(account_id)

          logger.info(
              "Account %s resumed trading (was '%s' before crash)",
              account_id,
              pre_crash_status,
          )

          return AccountResumeResult(
              account_id=account_id,
              resumed=True,
              previous_status=pre_crash_status or "unknown",
              current_status="active",
              reason="Resumed successfully",
          )

      except Exception as e:
          logger.error("Failed to resume account %s: %s", account_id, e)
          return AccountResumeResult(
              account_id=account_id,
              resumed=False,
              previous_status=pre_crash_status or "unknown",
              current_status="error",
              reason=f"Resume failed: {e}",
          )
  ```
- [x] 4.2: Handle resume failures gracefully (don't block other accounts)

### Task 5: Main Resume Orchestration (AC: 1, 5, 6)

- [x] 5.1: Implement `resume_trading_after_recovery()` method:
  ```python
  async def resume_trading_after_recovery(
      self,
      reconciliation_results: dict[str, ReconciliationResult],
      pnl_results: dict[str, RecalculationResult],
      recovery_start_time: datetime,
  ) -> ResumeResult:
      """Resume trading for all eligible accounts after recovery.

      Called as the final step of crash recovery sequence:
      1. Story 5.1: Snapshot loaded
      2. Story 5.2: Crash detected, recovery initiated
      3. Story 5.3: Positions reconciled with MT5
      4. Story 5.4: Daily P&L recalculated
      5. Story 5.5: Trading resumed (THIS METHOD)

      Args:
          reconciliation_results: Results from Story 5.3 position reconciliation
          pnl_results: Results from Story 5.4 P&L recalculation
          recovery_start_time: When crash detection started (for duration calc)

      Returns:
          ResumeResult with summary and per-account details
      """
      account_results: list[AccountResumeResult] = []
      accounts_resumed = 0
      accounts_skipped = 0
      accounts_blocked = 0

      # Process all accounts that went through recovery
      all_accounts = set(reconciliation_results.keys()) | set(pnl_results.keys())

      for account_id in all_accounts:
          recon_result = reconciliation_results.get(account_id)
          pnl_result = pnl_results.get(account_id)

          should_resume, reason = await self._should_resume_account(
              account_id, recon_result, pnl_result
          )

          if should_resume:
              result = await self._resume_account(account_id)
              if result.resumed:
                  accounts_resumed += 1
              else:
                  accounts_blocked += 1
              account_results.append(result)
          else:
              # Account not resumed - log why
              pre_status = await self._get_pre_crash_status(account_id)

              if recon_result and recon_result.requires_manual_intervention:
                  accounts_blocked += 1
                  current_status = "error"
                  # CRITICAL: Actually set Redis status to error so account is blocked
                  await self._redis.save_account_status(account_id, "error")
                  logger.warning(
                      "Account %s blocked - set to error state due to manual intervention",
                      account_id,
                  )
              else:
                  accounts_skipped += 1
                  current_status = pre_status or "stopped"
                  # Don't modify Redis status - account keeps its pre-crash status

              account_results.append(AccountResumeResult(
                  account_id=account_id,
                  resumed=False,
                  previous_status=pre_status or "unknown",
                  current_status=current_status,
                  reason=reason,
              ))
              logger.info(
                  "Account %s not resumed: %s",
                  account_id,
                  reason,
              )

      # Calculate recovery duration
      recovery_duration = datetime.now(timezone.utc) - recovery_start_time

      # Send notification
      notification_sent = await self._send_recovery_notification(
          accounts_resumed, accounts_skipped, accounts_blocked, recovery_duration
      )

      # Log summary
      logger.info(
          "Recovery successful. Trading resumed for %d accounts "
          "(skipped: %d, blocked: %d) in %.2f seconds",
          accounts_resumed,
          accounts_skipped,
          accounts_blocked,
          recovery_duration.total_seconds(),
      )

      return ResumeResult(
          success=True,
          accounts_resumed=accounts_resumed,
          accounts_skipped=accounts_skipped,
          accounts_blocked=accounts_blocked,
          recovery_duration=recovery_duration,
          account_results=account_results,
          notification_sent=notification_sent,
      )
  ```
- [x] 5.2: Calculate and log recovery duration
- [x] 5.3: Handle partial failures (some accounts resume, others don't)

### Task 6: Recovery Notification (AC: 6)

- [x] 6.1: Implement `_send_recovery_notification()` method:
  ```python
  async def _send_recovery_notification(
      self,
      accounts_resumed: int,
      accounts_skipped: int,
      accounts_blocked: int,
      recovery_duration: timedelta,
  ) -> bool:
      """Send notification about recovery completion via Redis pub/sub.

      Publishes to channel: alerts:system
      Message format: JSON with recovery details

      Args:
          accounts_resumed: Number of accounts that resumed trading
          accounts_skipped: Number of accounts that remained paused/stopped
          accounts_blocked: Number of accounts blocked due to errors
          recovery_duration: Time taken for recovery

      Returns:
          True if notification sent successfully
      """
      try:
          message = {
              "type": "recovery_complete",
              "accounts_resumed": accounts_resumed,
              "accounts_skipped": accounts_skipped,
              "accounts_blocked": accounts_blocked,
              "recovery_duration_seconds": recovery_duration.total_seconds(),
              "timestamp": datetime.now(timezone.utc).isoformat(),
              "message": f"Recovery complete: {accounts_resumed} accounts resumed trading",
          }

          await self._redis.client.publish(
              "alerts:system",
              json.dumps(message),
          )

          logger.info("Recovery notification sent")
          return True

      except Exception as e:
          logger.warning("Failed to send recovery notification: %s", e)
          return False
  ```
- [x] 6.2: Use existing Redis pub/sub pattern from RedisStateManager

### Task 7: Engine Integration (AC: 1, 5)

**⚠️ TASK EXECUTION ORDER:**
Execute Task 7.4 FIRST (add account_manager parameter) before implementing Tasks 7.2-7.3,
as those tasks reference `self._account_manager` which doesn't exist until 7.4 is complete.

**CRITICAL INTEGRATION POINT:**
```
Location: services/trading-engine/src/engine.py
Method: _initialize_crash_recovery()
Insert AFTER: P&L recalculation (line ~186-189)
Insert BEFORE: await self._crash_recovery.clear_crash_indicators()

The recovery sequence is:
1. Position reconciliation (Story 5.3) ← lines 156-193
2. Daily P&L recalculation (Story 5.4) ← lines 181-186
3. Trading resume (Story 5.5) ← NEW - insert here
4. Clear crash indicators ← line 188 (MUST come AFTER resume)
```

- [x] 7.1: Add TradingResumer to Engine:
  ```python
  # In Engine.__init__() - add attribute:
  self._trading_resumer: TradingResumer | None = None

  # In Engine - add property:
  @property
  def resume_result(self) -> ResumeResult | None:
      """Get the trading resume result from startup.

      Returns:
          ResumeResult if trading resume ran, None otherwise.
      """
      return self._resume_result
  ```
- [x] 7.2: Add `_run_trading_resume()` method to Engine:
  ```python
  async def _run_trading_resume(
      self,
      reconciliation_results: dict[str, ReconciliationResult],
      pnl_results: dict[str, RecalculationResult],
      recovery_start_time: datetime,
  ) -> ResumeResult:
      """Resume trading for all eligible accounts after recovery.

      Called after P&L recalculation, before clearing crash indicators.
      Only resumes accounts that:
      - Were "active" before crash
      - Passed reconciliation successfully
      - Passed P&L recalculation (or fallback)

      Args:
          reconciliation_results: Results from position reconciliation
          pnl_results: Results from P&L recalculation
          recovery_start_time: When crash recovery started

      Returns:
          ResumeResult with resume details
      """
      from .state.trading_resumer import TradingResumer

      # Initialize resumer (lazy init)
      if self._trading_resumer is None:
          if self._redis_manager is None or self._account_manager is None:
              logger.warning(
                  "Skipping trading resume - missing redis_manager or account_manager"
              )
              return ResumeResult(
                  success=False,
                  accounts_resumed=0,
                  accounts_skipped=0,
                  accounts_blocked=0,
                  recovery_duration=timedelta(0),
                  account_results=[],
                  notification_sent=False,
              )

          self._trading_resumer = TradingResumer(
              redis_manager=self._redis_manager,
              account_manager=self._account_manager,
          )

      return await self._trading_resumer.resume_trading_after_recovery(
          reconciliation_results=reconciliation_results,
          pnl_results=pnl_results,
          recovery_start_time=recovery_start_time,
      )
  ```
- [x] 7.3: Update `_initialize_crash_recovery()` to call trading resume:
  ```python
  # In _initialize_crash_recovery(), inside "if all_success:" block
  # AFTER P&L recalculation (line ~186):

  # Story 5.5: Resume trading for eligible accounts
  # NOTE: recovery_start_time should ideally come from CrashRecoveryManager.
  # If RecoveryResult exposes detection_time, use it. Otherwise, use current time
  # as a fallback (duration will be slightly underestimated).
  recovery_start = (
      result.indicators.detection_time
      if hasattr(result, 'indicators') and hasattr(result.indicators, 'detection_time')
      else datetime.now(timezone.utc)
  )
  self._resume_result = await self._run_trading_resume(
      reconciliation_results=self._reconciliation_results,
      pnl_results=self._pnl_recalculation_results or {},
      recovery_start_time=recovery_start,
  )
  ```
- [x] 7.4: Add `_account_manager` parameter to Engine.__init__():
  ```python
  def __init__(
      self,
      redis_manager: RedisStateManager | None = None,
      zmq_adapter: ZmqAdapter | None = None,
      db_session_factory: async_sessionmaker[AsyncSession] | None = None,
      risk_registry: RiskStateRegistry | None = None,
      pnl_registry: PnLTrackerRegistry | None = None,
      account_manager: AccountManager | None = None,  # NEW
  ) -> None:
      # ... existing code ...
      self._account_manager = account_manager
      self._trading_resumer: TradingResumer | None = None
      self._resume_result: ResumeResult | None = None
  ```
- [x] 7.5: Store recovery_start_time in CrashIndicatorResult for accurate duration

### Task 8: Unit Tests (AC: 1-6)

- [x] 8.1: Create `tests/unit/test_trading_resumer.py`
- [x] 8.2: Test account with "active" pre-crash status resumes
- [x] 8.3: Test account with "paused" pre-crash status does NOT resume
- [x] 8.4: Test account with "stopped" pre-crash status does NOT resume
- [x] 8.5: Test account requiring manual intervention does NOT resume
- [x] 8.6: Test account with failed reconciliation does NOT resume
- [x] 8.7: Test account with failed P&L recalculation still resumes (fallback used)
- [x] 8.8: Test recovery duration calculation
- [x] 8.9: Test notification sent on successful recovery
- [x] 8.10: Test notification failure doesn't block resume
- [x] 8.11: Test multiple accounts with mixed statuses
- [x] 8.12: Test resume failure for one account doesn't block others
- [x] 8.13: Test ResumeResult summary counts are accurate
- [x] 8.14: Test race condition: account status change during resume loop
- [x] 8.15: Test blocked account has Redis status set to "error"

### Task 9: Integration Tests (AC: 1-6)

- [x] 9.1: Create `tests/integration/test_trading_resume_redis.py`
- [x] 9.2: Test full recovery flow with real Redis
- [x] 9.3: Test account status persistence after resume
- [x] 9.4: Test notification published to Redis pub/sub
- [x] 9.5: Test AccountManager task spawning after resume

### Task 10: Documentation and Exports (AC: 1-6)

- [x] 10.1: Add docstrings to all TradingResumer methods
- [x] 10.2: Update `state/__init__.py` with new exports:
  ```python
  from .trading_resumer import (
      TradingResumer,
      AccountResumeResult,
      ResumeResult,
  )
  ```
- [x] 10.3: Document resume flow in module docstring

## Dev Notes

### CRITICAL INTEGRATION POINT (Read First!)

**Where to integrate in `engine.py`:**
```
File: services/trading-engine/src/engine.py
Method: _initialize_crash_recovery()
Location: Inside "if all_success:" block (around line 180-189)

SEQUENCE (must be in this order):
1. Position reconciliation completes (Story 5.3) ← lines 156-175
2. Check all_success flag ← line 177
3. Daily P&L recalculation (Story 5.4) ← lines 181-186
4. Trading resume (Story 5.5) ← INSERT HERE
5. Clear crash indicators ← line 188 (MUST come AFTER resume)
```

**Code to insert at line ~187 (after P&L recalculation, before clear_crash_indicators):**
```python
# Story 5.5: Resume trading for eligible accounts
self._resume_result = await self._run_trading_resume(
    reconciliation_results=self._reconciliation_results,
    pnl_results=self._pnl_recalculation_results or {},
    recovery_start_time=datetime.now(timezone.utc),  # TODO: use actual start time
)
```

---

### FULL FILE PATHS (Monorepo Structure)

**All paths relative to `/home/hopdev/Dev/Sandboxed/`:**

| Full Path | Action | Purpose |
|-----------|--------|---------|
| **New Files** | | |
| `services/trading-engine/src/state/trading_resumer.py` | CREATE | TradingResumer class |
| `services/trading-engine/tests/unit/test_trading_resumer.py` | CREATE | Unit tests |
| `services/trading-engine/tests/integration/test_trading_resume_redis.py` | CREATE | Redis integration tests |
| **Modify Files** | | |
| `services/trading-engine/src/state/__init__.py` | MODIFY | Add new exports |
| `services/trading-engine/src/engine.py` | MODIFY | Add account_manager param, integrate resume |

### PREREQUISITES (Stories 5.1-5.4 Complete)

**From Story 5.4 (Daily P&L Recalculation):**
- `DailyPnLRecalculator` at `src/state/daily_pnl_recalculator.py`
- `RecalculationResult` with `success` field
- Engine integration pattern established

**From Story 5.3 (Position Reconciliation):**
- `PositionReconciler` at `src/state/position_reconciler.py`
- `ReconciliationResult.requires_manual_intervention` flag for blocking
- `ReconciliationResult.success` field

**From Story 5.2 (Crash Detection):**
- `CrashRecoveryManager.startup_sequence()` returns `RecoveryResult`
- `recovery_mode` flag indicates crash recovery in progress

**From Story 5.1 (Redis Snapshots):**
- `StateSnapshot` with account state at crash time
- Snapshots stored at `snapshot:{account_id}:latest`

**From Epic 3 (Account Management):**
- `AccountManager` at `src/accounts/account_manager.py`
- `_spawn_account_task()` method for starting account tasks
- `get_account_status()` for reading Redis status
- Account status stored at `account:{account_id}:status`

### CONTEXT7 RESEARCH SUMMARY (NautilusTrader 2026-01-13)

**Key NautilusTrader Lifecycle Patterns:**
```python
# Strategy lifecycle methods
def on_start(self) -> None:
    pass  # Called when strategy starts
def on_stop(self) -> None:
    pass  # Called when strategy stops
def on_resume(self) -> None:
    pass  # Called when strategy resumes after pause
def on_save(self) -> dict[str, bytes]:
    return {}  # Returns state to be saved
def on_load(self, state: dict[str, bytes]) -> None:
    pass  # Loads state on startup
```

**Component State Management:**
- States: PRE_INITIALIZED, READY, STARTING, RUNNING, STOPPING, STOPPED, etc.
- Transitional states (STARTING, RESUMING) should be brief
- Use proper lifecycle methods for state changes

**Live Trading Node Pattern:**
```python
node = TradingNode(config=config)
node.build()
try:
    node.run()
finally:
    node.dispose()
```

### ACCOUNT STATUS DETERMINATION LOGIC

```
Pre-Crash Status    Reconciliation    P&L Recalc    Resume?
----------------    --------------    ----------    -------
active              success           success       YES - resume trading
active              success           failed        YES - uses fallback values
active              manual_interv     any           NO - blocked, set to error
active              failed            any           NO - blocked, set to error
paused              any               any           NO - remains paused
stopped             any               any           NO - remains stopped
error               any               any           NO - remains error
unknown/missing     any               any           NO - default to stopped
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
    │       └── Returns dict[account_id, ReconciliationResult]
    │
    ├── 4. Daily P&L Recalculation (Story 5.4)
    │       └── Returns dict[account_id, RecalculationResult]
    │
    ├── 5. Trading Resume (Story 5.5) ← THIS STORY
    │       ├── Check pre-crash status for each account
    │       ├── Determine eligibility (active + no manual intervention)
    │       ├── Call AccountManager._spawn_account_task() for eligible
    │       ├── Send recovery notification
    │       └── Returns ResumeResult
    │
    ├── 6. Clear crash indicators
    │
    └── 7. Normal operation begins
```

### EXISTING CODE PATTERNS TO REUSE

Reference these existing implementations (don't duplicate code):

| File | Method | Use For |
|------|--------|---------|
| `src/accounts/account_manager.py:278` | `_spawn_account_task()` | Starting account tasks |
| `src/accounts/account_manager.py:559` | `get_account_status()` | Reading account status from Redis |
| `src/state/redis_state.py:95` | `get_account_status()` | Redis account status access |
| `src/state/redis_state.py:130` | `publish_alert()` | Publishing to Redis pub/sub |
| `src/state/crash_recovery.py:340` | `initiate_recovery()` | Pattern for logging recovery |

### REDIS KEY PATTERNS

```
# Account Status (existing - from Epic 2)
Key: account:{account_id}:status
Value: "active" | "paused" | "stopped" | "error"
TTL: None (persistent)

# System Alerts (existing - from Epic 3)
Channel: alerts:system
Message: JSON { type, message, timestamp, ... }

# Snapshot (existing - from Story 5.1)
Key: snapshot:{account_id}:latest
Fields: account_id, timestamp, positions, etc.
TTL: 1 hour
```

### ANTI-PATTERNS (What NOT to Do)

| Anti-Pattern | Why It's Wrong | Instead, Do This |
|--------------|----------------|------------------|
| Resume ALL accounts blindly | Paused accounts should stay paused | Check pre-crash status |
| Block on one account failure | Other accounts can still resume | Process each independently |
| Skip notification on failure | User needs to know resume status | Always attempt notification |
| Ignore manual intervention flag | Account has reconciliation issues | Block account, set to error |
| Resume before P&L recalc | Compliance rules may be incorrect | Wait for P&L to complete |
| Resume after clearing crash flag | Crash indicators track recovery | Resume BEFORE clearing |

### TESTING COMMANDS

```bash
cd services/trading-engine

# Run unit tests
uv run pytest tests/unit/test_trading_resumer.py -v

# Run integration tests (requires Redis)
uv run pytest tests/integration/test_trading_resume_redis.py -v

# Run with coverage
uv run pytest tests/unit/test_trading_resumer.py --cov=src/state

# Lint check
uv run ruff check src/state/trading_resumer.py
```

### TASK DEPENDENCIES (Execute in Order)

```
Task 1 (Data Structures) ──► Task 2 (Pre-Crash Status)
         │                          │
         ▼                          ▼
   Task 3 (Eligibility) ◄──────────┘
         │
         ▼
   Task 4 (Resume Account) ──► Task 5 (Orchestration)
         │                            │
         ▼                            ▼
   Task 6 (Notification) ◄────────────┘
         │
         ▼
   Task 7 (Engine Integration)
         │
         ▼
   Tasks 8-9 (Tests) ──► Task 10 (Docs)
```

### PERFORMANCE REQUIREMENTS

- Pre-crash status lookup: < 5ms (Redis GET)
- Account resume: < 50ms per account (task spawn)
- Notification publish: < 10ms (Redis PUBLISH)
- Full resume for 10 accounts: < 1 second

### REFERENCES

- [docs/epic-5-context.md] - Epic 5 technical context
- [docs/architecture.md#Recovery-Failover] - Recovery sequence
- [docs/architecture.md#Graceful-Shutdown] - Shutdown/resume patterns
- [docs/epics.md#Story-5.5] - Story requirements
- [src/accounts/account_manager.py] - Account task management
- [src/state/crash_recovery.py] - Recovery flow patterns
- [Context7 NautilusTrader 2026-01-13] - Lifecycle management patterns

## Dev Agent Record

**Story created:** 2026-01-13 via create-story workflow

**Context Analysis:**
- Story 5.5 depends on Story 5.4 (Daily P&L Recalculation) - COMPLETED
- Story 5.5 depends on Story 5.3 (Position Reconciliation) - COMPLETED
- Story 5.5 depends on Story 5.2 (Crash Detection) - COMPLETED
- Story 5.5 depends on Story 5.1 (Redis Snapshots) - COMPLETED
- Epic 5 focused on State Persistence & Crash Recovery
- Story 5.6 (Graceful Shutdown) and 5.7 (Cold Storage) are independent from this

**Context7 Research Summary:**
- NautilusTrader uses lifecycle methods: on_start, on_stop, on_resume, on_load
- Component states follow finite state machine pattern
- Live trading nodes follow build → run → dispose pattern

**Previous Story Learnings (Story 5.4):**
- Engine integration follows pattern of calling in recovery mode block
- Lazy initialization of module when needed
- Results stored as Engine property for access
- Fallback to safe values on partial failures

**Git Intelligence (Recent Commits):**
- 4678558: Implement spec 5 story 5.4 (Daily P&L Recalculation)
- cef9bf1: Implement spec 5 story 5.3 (Position Reconciliation)
- b8aca3a: Implement spec 5 story 5.2 (Crash Detection)
- 08609a6: Implement spec 5 story 5.1 (Redis State Snapshots)
- Pattern: create module with dataclasses, main class, comprehensive tests, engine integration

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Context Reference

- Epic 5 context document (docs/epic-5-context.md)
- Story 5.4 for Engine integration pattern and dependencies
- Story 5.3 for ReconciliationResult structure
- Story 5.2 for CrashRecoveryManager patterns
- Architecture document for recovery flow sequence
- Context7 NautilusTrader research (2026-01-13) for lifecycle patterns

### Debug Log References

N/A - No debugging required during implementation.

### Completion Notes List

**Implementation completed:** 2026-01-13

**Implementation Summary:**
1. Created TradingResumer module with all required components
2. Integrated into Engine._initialize_crash_recovery() after P&L recalculation
3. All 20 unit tests pass
4. 7 integration tests (skipped when Redis unavailable)
5. Full test suite (1471 tests) passes without regressions

**Key Implementation Decisions:**
- Used existing Redis status as pre-crash status (Stories 5.3-5.4 don't modify it)
- P&L recalculation failure allows resume (uses fallback values)
- Notification failure doesn't block resume (logged as warning)
- Blocked accounts get Redis status set to "error" for visibility

**Test Coverage:**
- Unit tests: 20 tests covering all acceptance criteria
- Integration tests: 7 tests with Redis (skipped if unavailable)
- Edge cases: Empty accounts, missing status, concurrent changes

**Code Review Fixes (2026-01-13):**
- Fixed recovery duration calculation to capture start time at recovery mode entry
- Fixed failed reconciliation handling: now blocks account (sets error status) instead of skipping
- Updated log message from "Recovery successful" to "Recovery complete" with WARNING level when accounts blocked
- Updated test to validate correct blocking behavior for failed reconciliation

### File List

**Files to CREATE:**
| File | Purpose |
|------|---------|
| `services/trading-engine/src/state/trading_resumer.py` | TradingResumer class with resume logic |
| `services/trading-engine/tests/unit/test_trading_resumer.py` | Unit tests |
| `services/trading-engine/tests/integration/test_trading_resume_redis.py` | Redis integration tests |

**Files to MODIFY:**
| File | Changes |
|------|---------|
| `services/trading-engine/src/state/__init__.py` | Export TradingResumer, AccountResumeResult, ResumeResult |
| `services/trading-engine/src/engine.py` | Add account_manager param, integrate trading resume |

---

## Definition of Done

**Prerequisites:**
- [x] Stories 5.1-5.4 are complete and passing tests
- [x] AccountManager exists with _spawn_account_task() method
- [x] Redis account status persistence works

**Core Implementation:**
- [x] TradingResumer class created with resume logic
- [x] AccountResumeResult and ResumeResult dataclasses defined
- [x] Pre-crash status lookup from Redis implemented
- [x] Resume eligibility determination implemented

**Resume Logic:**
- [x] Active accounts resume trading
- [x] Paused accounts remain paused
- [x] Stopped accounts remain stopped
- [x] Manual intervention accounts blocked and Redis status set to "error"
- [x] Failed reconciliation accounts blocked

**Engine Integration:**
- [x] Engine.__init__ accepts account_manager parameter
- [x] Resume runs after P&L recalculation
- [x] Resume runs before clearing crash indicators
- [x] ResumeResult stored as Engine property

**Notification:**
- [x] Recovery notification published to Redis pub/sub
- [x] Notification includes resume counts and duration
- [x] Notification failure doesn't block resume

**Testing:**
- [x] Unit tests for each resume scenario
- [x] Unit tests for notification
- [x] Integration tests with Redis
- [x] All tests passing

**Acceptance Criteria Verification:**
- [x] AC1: All recovery steps complete → trading resumes
- [x] AC2: Active account before crash → resumes trading
- [x] AC3: Paused account before crash → remains paused
- [x] AC4: Manual intervention required → remains blocked
- [x] AC5: Recovery message logged with duration
- [x] AC6: Notification sent via Redis pub/sub

---
