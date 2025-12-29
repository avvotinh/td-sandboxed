# Story 3.2: Account Manager Multi-Account Orchestration

Status: Done

## Story

As a **developer**,
I want **the Account Manager to handle multiple account lifecycles**,
So that **each account operates independently**.

## Acceptance Criteria

1. **AC1:** Given the engine starts with 3 configured accounts, When all accounts have status "active", Then all 3 accounts are initialized and start processing signals

2. **AC2:** Given Account A is stopped, When I run `trading-engine accounts stop ftmo-gold-001`, Then Account A stops processing, And Accounts B and C continue operating normally

3. **AC3:** Given Account B encounters an error (e.g., MT5 disconnection), When the error is detected, Then Account B is set to "error" status, And Accounts A and C continue operating normally, And an alert is generated for Account B

4. **AC4:** Given I add a new account to accounts.yaml, When I run `trading-engine accounts add personal-002`, Then the new account is loaded and starts if status is "active", And existing accounts are not affected

## Tasks / Subtasks

- [x] Task 1: Extend AccountManager with async task orchestration (AC: #1)
  - [x] 1.1: Add `_tasks: dict[str, asyncio.Task]` to track per-account tasks
  - [x] 1.2: Implement `start_all_accounts()` method to initialize all active accounts concurrently
  - [x] 1.3: Each account runs in its own `asyncio.Task` with isolated try/except
  - [x] 1.4: Implement `_run_account_loop(account_id)` - the main async loop per account

- [x] Task 2: Implement per-account stop functionality (AC: #2)
  - [x] 2.1: Modify `stop_account()` to cancel the account's asyncio.Task
  - [x] 2.2: Implement graceful task cancellation with timeout (30s)
  - [x] 2.3: Verify other account tasks continue unaffected
  - [x] 2.4: Add logging for account stop events

- [x] Task 3: Implement isolated error handling per account (AC: #3)
  - [x] 3.1: Wrap account loops in try/except to catch all exceptions
  - [x] 3.2: On error: set account to "error" state, log error, generate alert
  - [x] 3.3: Implement `_publish_account_alert(account_id, alert_type, message)` using Redis pub/sub
  - [x] 3.4: Other accounts must NOT be affected by one account's error
  - [x] 3.5: Track error context in Redis: `account:{id}:last_error`

- [x] Task 4: Implement hot reload for new accounts (AC: #4)
  - [x] 4.1: Implement `add_account(account_id)` CLI command handler
  - [x] 4.2: Reload config from accounts.yaml, validate new account
  - [x] 4.3: Start new account task without affecting existing tasks
  - [x] 4.4: Add to `_accounts` dict and `_tasks` dict atomically

- [x] Task 5: Add account health tracking in Redis (AC: #1, #3)
  - [x] 5.1: Implement health heartbeat: `account:{id}:health` with TTL 60s
  - [x] 5.2: Health hash fields: `last_heartbeat`, `error_count`, `last_error`, `status`
  - [x] 5.3: Update health on each loop iteration
  - [x] 5.4: Clear health data on account stop

- [x] Task 6: Unit tests for multi-account orchestration (AC: #1-4)
  - [x] 6.1: Test concurrent startup of 3 accounts
  - [x] 6.2: Test stopping one account doesn't affect others
  - [x] 6.3: Test error isolation - one account error doesn't crash others
  - [x] 6.4: Test hot reload - adding account while others run
  - [x] 6.5: Test health heartbeat updates

## Dev Notes

### Technical Stack

- **Python:** 3.11+ (required by NautilusTrader)
- **Async:** asyncio with `asyncio.TaskGroup` or manual task management
- **State:** redis.asyncio (redis-py async client)
- **Pattern:** Actor-like lifecycle management (inspired by NautilusTrader Actor pattern)

### Key Architecture Patterns from NautilusTrader Research (Context7)

**Actor Lifecycle Pattern:**
```python
# NautilusTrader uses on_start/on_stop lifecycle hooks
def on_start(self) -> None:
    # Subscribe, initialize state
    pass

def on_stop(self) -> None:
    # Unsubscribe, cleanup
    pass
```

**Task Isolation with AnyIO/asyncio:**
```python
# From AnyIO research - proper error isolation
async with anyio.create_task_group() as tg:
    tg.start_soon(account_loop, account_id)
    # Each task has isolated error handling
```

### File Locations

| File | Action | Purpose |
|------|--------|---------|
| `src/accounts/account_manager.py` | MODIFY | Add multi-account task orchestration |
| `src/state/redis_state.py` | MODIFY | Add health tracking methods |
| `tests/unit/test_account_manager.py` | MODIFY | Add multi-account orchestration tests |
| `tests/integration/test_account_orchestration.py` | ADD | Integration tests with Redis |

### Existing Code Analysis

**Current AccountManager (src/accounts/account_manager.py:12-207):**
- Already has state machine transitions (start, stop, pause, resume, error)
- Uses `RedisStateManager` for persistence via `account:{id}:status` keys
- Missing: Task orchestration, concurrent account running, health tracking

**Current RedisStateManager (src/state/redis_state.py:1-101):**
- Has `save_account_status`, `get_account_status`, `delete_account_status`
- Missing: Health hash management, alert publishing

### Reference Implementation

**AccountManager Extensions:**

```python
# src/accounts/account_manager.py - ADD these methods

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Awaitable

from .models import AccountConfig, AccountsConfig

if TYPE_CHECKING:
    from ..state.redis_state import RedisStateManager

logger = logging.getLogger(__name__)


# Type alias for signal handler function
SignalHandler = Callable[[str], Awaitable[None]]
"""Signal handler receives account_id and processes pending signals for that account.

Example implementation:
    async def process_account_signals(account_id: str) -> None:
        '''Process pending signals for an account.'''
        # Get pending signals from Redis or message queue
        signals = await get_pending_signals(account_id)
        for signal in signals:
            await strategy.on_signal(account_id, signal)
"""


class AccountManager:
    # ... existing code ...

    def __init__(self, redis_manager: "RedisStateManager") -> None:
        self._redis = redis_manager
        self._accounts: dict[str, AccountConfig] = {}  # Account ID -> AccountConfig
        self._tasks: dict[str, asyncio.Task] = {}  # Account ID -> running asyncio.Task
        self._signal_handler: SignalHandler | None = None

    def set_signal_handler(self, handler: SignalHandler) -> None:
        """Set the signal processing callback for accounts.

        Args:
            handler: Async function that takes account_id and processes signals.
                     Called on each loop iteration for active accounts.
        """
        self._signal_handler = handler

    async def start_all_accounts(self) -> None:
        """Start all accounts with status 'active' concurrently.

        Each account runs in its own asyncio.Task with isolated error handling.

        Note: AccountConfig.status is an AccountStatus enum. Compare using .value
        for string comparison or directly against the enum constant.
        """
        for account_id, account in self._accounts.items():
            # Compare against enum value (AccountConfig.status is AccountStatus enum)
            if account.status.value == "active":
                await self._spawn_account_task(account_id)

        logger.info(f"Started {len(self._tasks)} account tasks")

    async def _spawn_account_task(self, account_id: str) -> None:
        """Spawn a new task for an account."""
        if account_id in self._tasks:
            logger.warning(f"Account {account_id} task already running")
            return

        task = asyncio.create_task(
            self._run_account_loop(account_id),
            name=f"account-{account_id}"
        )
        self._tasks[account_id] = task
        await self._redis.save_account_status(account_id, "active")
        logger.info(f"Spawned task for account {account_id}")

    async def _run_account_loop(self, account_id: str) -> None:
        """Main loop for a single account - runs until stopped or error.

        CRITICAL: This loop is isolated - errors here do NOT affect other accounts.
        """
        try:
            logger.info(f"Account {account_id} loop started")

            while True:
                # Update health heartbeat
                await self._update_health(account_id)

                # Check if we should stop
                status = await self._redis.get_account_status(account_id)
                if status in ("stopped", "paused"):
                    logger.info(f"Account {account_id} loop exiting: status={status}")
                    break

                # Process signals if handler is set
                if self._signal_handler:
                    await self._signal_handler(account_id)

                # Small sleep to prevent busy loop
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info(f"Account {account_id} task cancelled")
            raise
        except Exception as e:
            logger.exception(f"Account {account_id} error: {e}")
            await self._handle_account_error(account_id, e)
        finally:
            await self._clear_health(account_id)
            self._tasks.pop(account_id, None)

    async def _handle_account_error(self, account_id: str, error: Exception) -> None:
        """Handle account error - set error state and publish alert."""
        await self.set_error(account_id)
        await self._redis.save_account_last_error(account_id, str(error))
        await self._publish_alert(
            account_id,
            "error",
            f"Account {account_id} encountered error: {error}"
        )

    async def _update_health(self, account_id: str) -> None:
        """Update account health heartbeat in Redis."""
        await self._redis.update_account_health(
            account_id,
            {
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                "status": "healthy",
            }
        )

    async def _clear_health(self, account_id: str) -> None:
        """Clear account health data on stop."""
        await self._redis.clear_account_health(account_id)

    async def _publish_alert(self, account_id: str, alert_type: str, message: str) -> None:
        """Publish alert to Redis pub/sub channel."""
        await self._redis.publish_alert(account_id, alert_type, message)

    async def stop_account(self, account_id: str) -> None:
        """Stop a trading account - cancel task and update status.

        This method is safe to call even if the account task isn't running.
        """
        self._validate_account_exists(account_id)

        # Cancel the task if running
        if account_id in self._tasks:
            task = self._tasks[account_id]
            task.cancel()
            try:
                # Wait for task to complete cancellation (up to 30s)
                # Note: Don't use shield() here - we want the task to be cancelled
                await asyncio.wait_for(task, timeout=30.0)
            except asyncio.CancelledError:
                # Expected - task was cancelled successfully
                pass
            except asyncio.TimeoutError:
                # Task didn't respond to cancellation in time
                logger.warning(f"Account {account_id} task did not stop within timeout")
            finally:
                self._tasks.pop(account_id, None)

        current = await self.get_account_status(account_id)
        if current == "stopped":
            return  # Idempotent

        await self._redis.save_account_status(account_id, "stopped")
        logger.info(f"Account {account_id} stopped")

    async def add_account(self, account_id: str, config: "AccountsConfig") -> None:
        """Hot-reload: Add a new account while others are running.

        Args:
            account_id: Account ID to add.
            config: Fresh AccountsConfig with new account.
        """
        # Find the new account in config
        new_account = next(
            (acc for acc in config.accounts if acc.id == account_id),
            None
        )
        if not new_account:
            raise ValueError(f"Account {account_id} not found in config")

        if account_id in self._accounts:
            raise ValueError(f"Account {account_id} already loaded")

        # Add to accounts dict
        self._accounts[account_id] = new_account

        # Start if status is active
        if new_account.status == "active":
            await self._spawn_account_task(account_id)

        logger.info(f"Hot-loaded account {account_id}")

    async def shutdown(self) -> None:
        """Gracefully shutdown all account tasks and close connections.

        This is the preferred method for stopping the AccountManager.
        It replaces the existing close() method by:
        1. Stopping all account tasks gracefully
        2. Closing the Redis connection

        Note: The existing close() method only closes Redis. Use shutdown()
        for proper cleanup when running multi-account orchestration.
        """
        logger.info("Shutting down all account tasks...")

        # Cancel all tasks
        for account_id, task in list(self._tasks.items()):
            task.cancel()

        # Wait for all tasks to complete
        if self._tasks:
            await asyncio.gather(
                *self._tasks.values(),
                return_exceptions=True
            )

        self._tasks.clear()
        await self._redis.close()
        logger.info("All account tasks shut down")

    # Note: The existing close() method should be updated to call shutdown()
    # or deprecated in favor of shutdown() for clarity.
```

**RedisStateManager Extensions:**

```python
# src/state/redis_state.py - ADD these methods

import json
from datetime import datetime, timezone

class RedisStateManager:
    # ... existing code ...

    async def update_account_health(self, account_id: str, health_data: dict) -> None:
        """Update account health hash with TTL.

        Args:
            account_id: Account identifier.
            health_data: Health data dict (last_heartbeat, status, etc.)
        """
        key = f"account:{account_id}:health"
        await self.client.hset(key, mapping=health_data)
        await self.client.expire(key, 60)  # 60 second TTL

    async def get_account_health(self, account_id: str) -> dict | None:
        """Get account health data.

        Returns:
            Health data dict or None if not found.
        """
        key = f"account:{account_id}:health"
        data = await self.client.hgetall(key)
        return data if data else None

    async def clear_account_health(self, account_id: str) -> None:
        """Clear account health data."""
        key = f"account:{account_id}:health"
        await self.client.delete(key)

    async def save_account_last_error(self, account_id: str, error: str) -> None:
        """Save last error for account."""
        key = f"account:{account_id}:last_error"
        await self.client.set(key, error)

    async def get_account_last_error(self, account_id: str) -> str | None:
        """Get last error for account."""
        key = f"account:{account_id}:last_error"
        return await self.client.get(key)

    async def publish_alert(self, account_id: str, alert_type: str, message: str) -> None:
        """Publish alert to Redis pub/sub channel.

        Channel: alerts:{alert_type}:{account_id}
        """
        channel = f"alerts:{alert_type}:{account_id}"
        payload = json.dumps({
            "account_id": account_id,
            "alert_type": alert_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await self.client.publish(channel, payload)
```

### CLI Commands for Testing

Use these commands to manually test multi-account orchestration:

```bash
# Start the trading engine with multiple accounts
trading-engine start

# Check status of all accounts
trading-engine accounts list

# Stop a specific account (AC2 test)
trading-engine accounts stop ftmo-gold-001

# Check that other accounts continue running
trading-engine accounts list

# Add a new account at runtime (AC4 test - hot reload)
# First, add the account to accounts.yaml, then:
trading-engine accounts add personal-002

# Verify new account is running
trading-engine accounts list

# Simulate error recovery (AC3 test)
# This requires triggering an MT5 disconnection or similar error
```

### Testing Requirements

**Framework:** pytest + pytest-asyncio | **Location:** `tests/unit/` and `tests/integration/`

```python
# tests/unit/test_account_manager.py - ADD these tests

import pytest
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock


@asynccontextmanager
async def create_test_account_manager(num_accounts: int = 2):
    """Context manager for creating and cleaning up AccountManager in tests.

    Usage:
        async with create_test_account_manager(3) as (manager, mock_redis):
            await manager.start_all_accounts()
            # ... test code ...
        # Cleanup happens automatically

    Args:
        num_accounts: Number of test accounts to create.

    Yields:
        Tuple of (AccountManager, mock_redis).
    """
    mock_redis = AsyncMock(spec=RedisStateManager)
    mock_redis.get_account_status.return_value = None

    manager = AccountManager(mock_redis)
    config = create_config_with_n_accounts(num_accounts)
    manager.load_accounts(config)

    try:
        yield manager, mock_redis
    finally:
        # Cleanup: cancel any running tasks
        for task in manager._tasks.values():
            task.cancel()
        if manager._tasks:
            await asyncio.gather(*manager._tasks.values(), return_exceptions=True)
        manager._tasks.clear()


class TestMultiAccountOrchestration:
    """Tests for multi-account task orchestration."""

    @pytest.mark.asyncio
    async def test_start_all_accounts_concurrent(self, account_manager, mock_redis):
        """AC1: All active accounts start concurrently."""
        mock_redis.get_account_status.return_value = None

        await account_manager.start_all_accounts()

        # Verify tasks created for each account
        assert len(account_manager._tasks) == 2
        assert "test-account-001" in account_manager._tasks
        assert "test-account-002" in account_manager._tasks

    @pytest.mark.asyncio
    async def test_stop_one_account_others_continue(self, account_manager, mock_redis):
        """AC2: Stopping one account doesn't affect others."""
        # Start all accounts
        await account_manager.start_all_accounts()

        # Stop one account
        await account_manager.stop_account("test-account-001")

        # Verify only one stopped
        assert "test-account-001" not in account_manager._tasks
        assert "test-account-002" in account_manager._tasks

    @pytest.mark.asyncio
    async def test_error_isolation(self, account_manager, mock_redis):
        """AC3: One account error doesn't crash others."""
        # Simulate error in account loop
        async def failing_handler(account_id):
            if account_id == "test-account-001":
                raise RuntimeError("Simulated error")

        account_manager.set_signal_handler(failing_handler)
        await account_manager.start_all_accounts()

        # Wait for error to propagate
        await asyncio.sleep(0.2)

        # Account 1 should be in error state, account 2 still running
        mock_redis.save_account_status.assert_any_call("test-account-001", "error")
        assert "test-account-002" in account_manager._tasks

    @pytest.mark.asyncio
    async def test_hot_reload_add_account(self, account_manager, mock_redis):
        """AC4: Hot-reload adds new account without affecting existing."""
        # Start existing accounts
        await account_manager.start_all_accounts()
        initial_count = len(account_manager._tasks)

        # Create config with new account
        new_config = create_config_with_new_account("personal-002")

        # Hot-reload
        await account_manager.add_account("personal-002", new_config)

        # Verify new account added and running
        assert len(account_manager._tasks) == initial_count + 1
        assert "personal-002" in account_manager._tasks


class TestAccountHealth:
    """Tests for account health tracking."""

    @pytest.mark.asyncio
    async def test_health_heartbeat_updated(self, account_manager, mock_redis):
        """Health heartbeat updates during account loop."""
        await account_manager._spawn_account_task("test-account-001")
        await asyncio.sleep(0.2)  # Let loop run

        mock_redis.update_account_health.assert_called()

    @pytest.mark.asyncio
    async def test_health_cleared_on_stop(self, account_manager, mock_redis):
        """Health data cleared when account stops."""
        await account_manager._spawn_account_task("test-account-001")
        await account_manager.stop_account("test-account-001")

        mock_redis.clear_account_health.assert_called_with("test-account-001")


class TestEdgeCases:
    """Tests for edge cases and error paths."""

    @pytest.mark.asyncio
    async def test_stop_account_not_running(self, account_manager, mock_redis):
        """Stopping an account without a running task is safe (no-op for task)."""
        # Account exists but no task spawned
        await account_manager.stop_account("test-account-001")

        # Should still update status, just no task to cancel
        mock_redis.save_account_status.assert_called_with("test-account-001", "stopped")

    @pytest.mark.asyncio
    async def test_add_account_already_exists(self, account_manager):
        """Adding an account that already exists raises ValueError."""
        # Account already loaded
        with pytest.raises(ValueError, match="already loaded"):
            await account_manager.add_account("test-account-001", mock_config)

    @pytest.mark.asyncio
    async def test_start_accounts_no_signal_handler(self, account_manager, mock_redis):
        """Accounts start even without signal handler (handler is optional)."""
        # No signal handler set
        account_manager._signal_handler = None

        await account_manager.start_all_accounts()

        # Tasks should still be created
        assert len(account_manager._tasks) >= 1

    @pytest.mark.asyncio
    async def test_spawn_task_already_running(self, account_manager, mock_redis):
        """Spawning task for account with existing task logs warning."""
        await account_manager._spawn_account_task("test-account-001")

        # Try to spawn again
        await account_manager._spawn_account_task("test-account-001")

        # Should not create duplicate task
        assert len(account_manager._tasks) == 1
```

### Context from Previous Story (3.1)

**From Story 3.1 Implementation:**
- `MAX_ACCOUNTS = 5` limit enforced at config load
- `VALID_PROP_FIRMS = frozenset({"ftmo", "the5ers", "wmt"})`
- Pydantic validators auto-trigger on `AccountsConfig` instantiation
- `warn_missing_password_env()` warns about missing env vars (non-blocking)

**Key Files Created/Modified:**
- `src/accounts/models.py` - Account models with validation
- `src/config/loader.py` - Config loading with multi-account support
- `configs/accounts.yaml.example` - Multi-account examples

### Anti-Patterns (DO NOT)

- **DO NOT** use a single task for all accounts - each account MUST have its own task
- **DO NOT** let one account's exception propagate to others - wrap each loop in try/except
- **DO NOT** block the event loop - use async/await throughout
- **DO NOT** share mutable state between account tasks without proper synchronization
- **DO NOT** forget to cleanup tasks on shutdown - always cancel and await
- **DO NOT** use `asyncio.create_task` without storing the task reference (prevents GC)

### Redis Key Patterns (Per Architecture)

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `account:{id}:status` | String | None | Account state (active/paused/stopped/error) |
| `account:{id}:health` | Hash | 60s | Health heartbeat (last_heartbeat, status) |
| `account:{id}:last_error` | String | None | Last error message |
| `alerts:error:{id}` | Pub/Sub | N/A | Error alert channel |

### References

- [Source: docs/architecture.md#Multi-Account Architecture] - Account Manager design
- [Source: docs/architecture.md#Account Manager] - Lifecycle management
- [Source: docs/epics.md#Story 3.2] - Story requirements
- [Source: services/trading-engine/src/accounts/account_manager.py] - Existing implementation
- [Source: services/trading-engine/src/state/redis_state.py] - Redis state patterns
- [Source: NautilusTrader Actor Pattern] - Lifecycle hooks (on_start, on_stop)
- [Source: redis-py async docs] - Async pub/sub patterns
- [Source: AnyIO task groups] - Error isolation patterns

## Dev Agent Record

### Context Reference

Story created via create-story workflow with:
- NautilusTrader documentation research via MCP Context7 (Actor lifecycle patterns)
- redis-py async documentation research via MCP Context7 (pub/sub, health checks)
- AnyIO documentation research via MCP Context7 (task groups, error isolation)
- Architecture analysis from docs/architecture.md
- Previous story 3.1 implementation analysis
- Existing codebase analysis from services/trading-engine/src/accounts/

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A - Initial story creation

### Completion Notes List

- Story context created with comprehensive developer guidance
- Multi-account orchestration patterns documented from NautilusTrader Actor research
- Error isolation patterns documented from AnyIO task group research
- Redis async pub/sub patterns documented from redis-py research
- All technical requirements extracted from architecture
- Testing requirements specified with clear patterns
- Anti-patterns clearly documented to prevent common mistakes

### Validation Notes (2025-12-29)

**Story validated via validate-create-story workflow. Applied improvements:**

| ID | Type | Description |
|----|------|-------------|
| C1 | Critical | Added missing imports (Callable, Awaitable, TYPE_CHECKING) and model imports |
| C2 | Critical | Fixed type hint: `dict[str, AccountConfig]` instead of `dict[str, object]` |
| C3 | Critical | Added SignalHandler type alias with docstring explaining expected implementation |
| E1 | Enhancement | Fixed asyncio.shield() misuse - removed shield() from wait_for(), added proper comments |
| E2 | Enhancement | Added note clarifying AccountConfig.status is enum, use `.value` for string comparison |
| E3 | Enhancement | Clarified close() vs shutdown() relationship in docstring |
| E4 | Enhancement | Added TestEdgeCases class with 4 new edge case tests |
| O1 | Optimization | Added CLI Commands for Testing section with manual test commands |
| O2 | Optimization | Added asynccontextmanager fixture for test setup/teardown |

**Validation Score:** 22/28 (79%) -> Improved to address all identified issues

### Implementation Notes (2025-12-29)

**Implementation completed via dev-story workflow. Key accomplishments:**

| Task | Description |
|------|-------------|
| Task 1 | Extended AccountManager with `_tasks` dict, `start_all_accounts()`, `_spawn_account_task()`, and `_run_account_loop()` |
| Task 2 | Modified `stop_account()` to cancel asyncio tasks with 30s timeout, added logging |
| Task 3 | Implemented isolated error handling with `_handle_account_error()`, Redis pub/sub alerts |
| Task 4 | Implemented `add_account()` for hot-reload, validates and starts new accounts atomically |
| Task 5 | Added Redis health tracking methods: `update_account_health()`, `clear_account_health()`, `save_account_last_error()`, `publish_alert()` |
| Task 6 | Added 12 new unit tests covering all acceptance criteria plus edge cases |

**Test Results:**
- All 580 unit tests pass
- All 42 AccountManager tests pass (30 existing + 12 new)
- No regressions detected
- All linting checks pass

### File List

Files modified:
- `services/trading-engine/src/accounts/account_manager.py` - Added task orchestration, hot reload, shutdown method, error tracking, atomic locking
- `services/trading-engine/src/state/redis_state.py` - Added health tracking, error tracking, alert publishing
- `services/trading-engine/src/cli/accounts.py` - Added `add` command for hot-reload (code review fix)
- `services/trading-engine/tests/unit/test_account_manager.py` - Added 17 multi-account orchestration tests
- `services/trading-engine/tests/integration/test_account_orchestration.py` - Created with 7 integration tests (code review fix)

### Change Log

| Date | Change |
|------|--------|
| 2025-12-29 | Implemented multi-account orchestration: async task management, isolated error handling, health tracking, hot-reload support |
| 2025-12-30 | Code review fixes: Added CLI `add` command (H1), error_count in health tracking (H2), integration tests (H3), atomic hot-reload with lock (M3), additional edge case tests (M2, M4) |

### Code Review Fixes (2025-12-30)

**Issues Found and Fixed:**

| ID | Severity | Issue | Fix Applied |
|----|----------|-------|-------------|
| H1 | HIGH | Missing CLI `add` command - AC4 not testable | Added `@accounts_app.command("add")` to `cli/accounts.py` |
| H2 | HIGH | Missing `error_count` in health tracking | Added `_error_counts` dict and included in `_update_health()` |
| H3 | HIGH | Missing integration tests file | Created `tests/integration/test_account_orchestration.py` |
| M2 | MEDIUM | No test for alert payload format | Added `TestAlertPayloadValidation` class with 2 tests |
| M3 | MEDIUM | Race condition in `add_account()` | Added `asyncio.Lock` for atomic add+start operation |
| M4 | MEDIUM | No test for shutdown with no tasks | Added `test_shutdown_with_no_running_tasks` |

**Files Modified:**
- `services/trading-engine/src/cli/accounts.py` - Added `add` command
- `services/trading-engine/src/accounts/account_manager.py` - Added `_error_counts`, `_accounts_lock`, updated health tracking
- `services/trading-engine/tests/unit/test_account_manager.py` - Added 5 new tests
- `services/trading-engine/tests/integration/test_account_orchestration.py` - Created (7 integration tests)

**Test Results After Fixes:**
- 641 unit tests pass (+4 from review)
- 7 new integration tests (skipped without Redis)
- All linting passes
