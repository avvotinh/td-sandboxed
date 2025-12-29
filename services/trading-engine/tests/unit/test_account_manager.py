"""Tests for AccountManager class."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.accounts.account_manager import AccountManager
from src.accounts.models import (
    AccountConfig,
    AccountsConfig,
    AccountType,
    MT5Config,
)


@pytest.fixture
def mock_redis():
    """Create a mock RedisStateManager."""
    redis = MagicMock()
    redis.save_account_status = AsyncMock()
    redis.get_account_status = AsyncMock(return_value=None)
    redis.close = AsyncMock()
    # Add multi-account orchestration mocks
    redis.update_account_health = AsyncMock()
    redis.clear_account_health = AsyncMock()
    redis.save_account_last_error = AsyncMock()
    redis.publish_alert = AsyncMock()
    return redis


@pytest.fixture
def sample_accounts_config():
    """Create sample AccountsConfig for testing."""
    return AccountsConfig(
        accounts=[
            AccountConfig(
                id="test-account-001",
                name="Test Account 1",
                type=AccountType.PROP_FIRM,
                prop_firm="ftmo",
                mt5=MT5Config(
                    server="TestServer",
                    login=12345,
                    password_env="MT5_TEST_PASSWORD",
                ),
                strategy="ma_crossover",
            ),
            AccountConfig(
                id="test-account-002",
                name="Test Account 2",
                type=AccountType.DEMO,
                mt5=MT5Config(
                    server="DemoServer",
                    login=67890,
                    password_env="MT5_DEMO_PASSWORD",
                ),
                strategy="rsi_strategy",
            ),
        ]
    )


@pytest.fixture
def account_manager(mock_redis, sample_accounts_config):
    """Create AccountManager with mock Redis and sample config."""
    manager = AccountManager(mock_redis)
    manager.load_accounts(sample_accounts_config)
    return manager


class TestAccountManagerInit:
    """Tests for AccountManager initialization."""

    def test_init_with_redis(self, mock_redis):
        """Test AccountManager initializes with Redis manager."""
        manager = AccountManager(mock_redis)
        assert manager._redis == mock_redis
        assert manager._accounts == {}

    def test_load_accounts(self, mock_redis, sample_accounts_config):
        """Test loading accounts from config."""
        manager = AccountManager(mock_redis)
        manager.load_accounts(sample_accounts_config)
        assert len(manager._accounts) == 2
        assert "test-account-001" in manager._accounts
        assert "test-account-002" in manager._accounts


class TestAccountManagerValidation:
    """Tests for account validation."""

    def test_validate_existing_account(self, account_manager):
        """Test validation passes for existing account."""
        # Should not raise
        account_manager._validate_account_exists("test-account-001")

    def test_validate_nonexistent_account(self, account_manager):
        """Test validation fails for nonexistent account."""
        with pytest.raises(ValueError) as exc_info:
            account_manager._validate_account_exists("nonexistent")
        assert "not found in configuration" in str(exc_info.value)
        assert "Available accounts" in str(exc_info.value)


class TestAccountManagerStartAccount:
    """Tests for start_account method."""

    @pytest.mark.asyncio
    async def test_start_new_account(self, account_manager, mock_redis):
        """Test starting a new account (no prior state)."""
        mock_redis.get_account_status.return_value = None

        await account_manager.start_account("test-account-001")

        mock_redis.save_account_status.assert_called_once_with(
            "test-account-001", "active"
        )

    @pytest.mark.asyncio
    async def test_start_stopped_account(self, account_manager, mock_redis):
        """Test starting a stopped account."""
        mock_redis.get_account_status.return_value = "stopped"

        await account_manager.start_account("test-account-001")

        mock_redis.save_account_status.assert_called_once_with(
            "test-account-001", "active"
        )

    @pytest.mark.asyncio
    async def test_start_active_account_fails(self, account_manager, mock_redis):
        """Test starting an active account fails."""
        mock_redis.get_account_status.return_value = "active"

        with pytest.raises(ValueError) as exc_info:
            await account_manager.start_account("test-account-001")
        assert "Cannot transition" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_start_paused_account_succeeds(self, account_manager, mock_redis):
        """Test starting a paused account succeeds (paused → active is valid).

        Note: The state machine allows paused → active transition.
        While `resume` is the semantic command for paused accounts,
        `start` also works since the state machine permits this transition.
        """
        mock_redis.get_account_status.return_value = "paused"

        await account_manager.start_account("test-account-001")
        mock_redis.save_account_status.assert_called_once_with(
            "test-account-001", "active"
        )

    @pytest.mark.asyncio
    async def test_start_nonexistent_account(self, account_manager):
        """Test starting nonexistent account fails."""
        with pytest.raises(ValueError) as exc_info:
            await account_manager.start_account("nonexistent")
        assert "not found" in str(exc_info.value)


class TestAccountManagerStopAccount:
    """Tests for stop_account method."""

    @pytest.mark.asyncio
    async def test_stop_active_account(self, account_manager, mock_redis):
        """Test stopping an active account."""
        mock_redis.get_account_status.return_value = "active"

        await account_manager.stop_account("test-account-001")

        mock_redis.save_account_status.assert_called_once_with(
            "test-account-001", "stopped"
        )

    @pytest.mark.asyncio
    async def test_stop_paused_account(self, account_manager, mock_redis):
        """Test stopping a paused account."""
        mock_redis.get_account_status.return_value = "paused"

        await account_manager.stop_account("test-account-001")

        mock_redis.save_account_status.assert_called_once_with(
            "test-account-001", "stopped"
        )

    @pytest.mark.asyncio
    async def test_stop_already_stopped_idempotent(self, account_manager, mock_redis):
        """Test stopping already stopped account is idempotent."""
        mock_redis.get_account_status.return_value = "stopped"

        await account_manager.stop_account("test-account-001")

        # Should not call save since already stopped
        mock_redis.save_account_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_error_account(self, account_manager, mock_redis):
        """Test stopping an account in error state."""
        mock_redis.get_account_status.return_value = "error"

        await account_manager.stop_account("test-account-001")

        mock_redis.save_account_status.assert_called_once_with(
            "test-account-001", "stopped"
        )

    @pytest.mark.asyncio
    async def test_stop_nonexistent_account(self, account_manager):
        """Test stopping nonexistent account fails."""
        with pytest.raises(ValueError) as exc_info:
            await account_manager.stop_account("nonexistent")
        assert "not found" in str(exc_info.value)


class TestAccountManagerPauseAccount:
    """Tests for pause_account method."""

    @pytest.mark.asyncio
    async def test_pause_active_account(self, account_manager, mock_redis):
        """Test pausing an active account."""
        mock_redis.get_account_status.return_value = "active"

        await account_manager.pause_account("test-account-001")

        mock_redis.save_account_status.assert_called_once_with(
            "test-account-001", "paused"
        )

    @pytest.mark.asyncio
    async def test_pause_new_account_fails(self, account_manager, mock_redis):
        """Test pausing a new account (no state) fails."""
        mock_redis.get_account_status.return_value = None

        with pytest.raises(ValueError) as exc_info:
            await account_manager.pause_account("test-account-001")
        assert "no prior state" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_pause_stopped_account_fails(self, account_manager, mock_redis):
        """Test pausing a stopped account fails."""
        mock_redis.get_account_status.return_value = "stopped"

        with pytest.raises(ValueError) as exc_info:
            await account_manager.pause_account("test-account-001")
        assert "Cannot transition" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_pause_paused_account_fails(self, account_manager, mock_redis):
        """Test pausing already paused account fails."""
        mock_redis.get_account_status.return_value = "paused"

        with pytest.raises(ValueError) as exc_info:
            await account_manager.pause_account("test-account-001")
        assert "Cannot transition" in str(exc_info.value)


class TestAccountManagerResumeAccount:
    """Tests for resume_account method."""

    @pytest.mark.asyncio
    async def test_resume_paused_account(self, account_manager, mock_redis):
        """Test resuming a paused account."""
        mock_redis.get_account_status.return_value = "paused"

        await account_manager.resume_account("test-account-001")

        mock_redis.save_account_status.assert_called_once_with(
            "test-account-001", "active"
        )

    @pytest.mark.asyncio
    async def test_resume_active_account_fails(self, account_manager, mock_redis):
        """Test resuming an active account fails."""
        mock_redis.get_account_status.return_value = "active"

        with pytest.raises(ValueError) as exc_info:
            await account_manager.resume_account("test-account-001")
        assert "not paused" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_resume_stopped_account_fails(self, account_manager, mock_redis):
        """Test resuming a stopped account fails (use start instead)."""
        mock_redis.get_account_status.return_value = "stopped"

        with pytest.raises(ValueError) as exc_info:
            await account_manager.resume_account("test-account-001")
        assert "not paused" in str(exc_info.value)


class TestAccountManagerAcknowledgeError:
    """Tests for acknowledge_error method."""

    @pytest.mark.asyncio
    async def test_acknowledge_error_state(self, account_manager, mock_redis):
        """Test acknowledging error state moves to stopped."""
        mock_redis.get_account_status.return_value = "error"

        await account_manager.acknowledge_error("test-account-001")

        mock_redis.save_account_status.assert_called_once_with(
            "test-account-001", "stopped"
        )

    @pytest.mark.asyncio
    async def test_acknowledge_non_error_fails(self, account_manager, mock_redis):
        """Test acknowledging non-error state fails."""
        mock_redis.get_account_status.return_value = "active"

        with pytest.raises(ValueError) as exc_info:
            await account_manager.acknowledge_error("test-account-001")
        assert "not in error state" in str(exc_info.value)


class TestAccountManagerSetError:
    """Tests for set_error method."""

    @pytest.mark.asyncio
    async def test_set_error_from_active(self, account_manager, mock_redis):
        """Test setting error from active state."""
        await account_manager.set_error("test-account-001")

        mock_redis.save_account_status.assert_called_once_with(
            "test-account-001", "error"
        )

    @pytest.mark.asyncio
    async def test_set_error_nonexistent_account(self, account_manager):
        """Test setting error on nonexistent account fails."""
        with pytest.raises(ValueError) as exc_info:
            await account_manager.set_error("nonexistent")
        assert "not found" in str(exc_info.value)


class TestAccountManagerGetStatus:
    """Tests for status retrieval methods."""

    @pytest.mark.asyncio
    async def test_get_account_status(self, account_manager, mock_redis):
        """Test getting single account status."""
        mock_redis.get_account_status.return_value = "active"

        status = await account_manager.get_account_status("test-account-001")

        assert status == "active"
        mock_redis.get_account_status.assert_called_with("test-account-001")

    @pytest.mark.asyncio
    async def test_get_account_status_none(self, account_manager, mock_redis):
        """Test getting status for new account returns None."""
        mock_redis.get_account_status.return_value = None

        status = await account_manager.get_account_status("test-account-001")

        assert status is None

    @pytest.mark.asyncio
    async def test_get_all_statuses(self, account_manager, mock_redis):
        """Test getting all account statuses."""
        mock_redis.get_account_status.side_effect = ["active", "paused"]

        statuses = await account_manager.get_all_statuses()

        assert len(statuses) == 2
        assert statuses["test-account-001"] == "active"
        assert statuses["test-account-002"] == "paused"

    @pytest.mark.asyncio
    async def test_get_all_statuses_unknown(self, account_manager, mock_redis):
        """Test getting all statuses with unknown (None) status."""
        mock_redis.get_account_status.side_effect = [None, "active"]

        statuses = await account_manager.get_all_statuses()

        assert statuses["test-account-001"] == "unknown"
        assert statuses["test-account-002"] == "active"


class TestAccountManagerClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_calls_redis_close(self, account_manager, mock_redis):
        """Test close method closes Redis connection."""
        await account_manager.close()

        mock_redis.close.assert_called_once()


# ============================================================================
# Multi-Account Orchestration Tests (Story 3.2)
# ============================================================================


def create_config_with_n_accounts(n: int) -> AccountsConfig:
    """Create AccountsConfig with n test accounts."""
    accounts = []
    for i in range(1, n + 1):
        accounts.append(
            AccountConfig(
                id=f"test-account-{i:03d}",
                name=f"Test Account {i}",
                type=AccountType.DEMO,
                mt5=MT5Config(
                    server="TestServer",
                    login=10000 + i,
                    password_env=f"MT5_TEST_PASSWORD_{i}",
                ),
                strategy="ma_crossover",
                status="active",
            )
        )
    return AccountsConfig(accounts=accounts)


def create_config_with_new_account(account_id: str) -> AccountsConfig:
    """Create AccountsConfig with a new account for hot-reload testing."""
    return AccountsConfig(
        accounts=[
            AccountConfig(
                id=account_id,
                name=f"New Account {account_id}",
                type=AccountType.DEMO,
                mt5=MT5Config(
                    server="TestServer",
                    login=99999,
                    password_env="MT5_NEW_PASSWORD",
                ),
                strategy="ma_crossover",
                status="active",
            )
        ]
    )


@asynccontextmanager
async def create_test_account_manager(mock_redis, num_accounts: int = 2):
    """Context manager for creating and cleaning up AccountManager in tests.

    Usage:
        async with create_test_account_manager(mock_redis, 3) as manager:
            await manager.start_all_accounts()
            # ... test code ...
        # Cleanup happens automatically

    Args:
        mock_redis: Mock Redis manager.
        num_accounts: Number of test accounts to create.

    Yields:
        AccountManager instance.
    """
    manager = AccountManager(mock_redis)
    config = create_config_with_n_accounts(num_accounts)
    manager.load_accounts(config)

    try:
        yield manager
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
    async def test_start_all_accounts_concurrent(self, mock_redis):
        """AC1: All active accounts start concurrently."""
        async with create_test_account_manager(mock_redis, 3) as manager:
            mock_redis.get_account_status.return_value = None

            await manager.start_all_accounts()

            # Verify tasks created for each account
            assert len(manager._tasks) == 3
            assert "test-account-001" in manager._tasks
            assert "test-account-002" in manager._tasks
            assert "test-account-003" in manager._tasks

    @pytest.mark.asyncio
    async def test_stop_one_account_others_continue(self, mock_redis):
        """AC2: Stopping one account doesn't affect others."""
        async with create_test_account_manager(mock_redis, 2) as manager:
            # Start all accounts
            await manager.start_all_accounts()

            # Let tasks start running
            await asyncio.sleep(0.05)

            # Stop one account
            await manager.stop_account("test-account-001")

            # Verify only one stopped
            assert "test-account-001" not in manager._tasks
            assert "test-account-002" in manager._tasks

    @pytest.mark.asyncio
    async def test_error_isolation(self, mock_redis):
        """AC3: One account error doesn't crash others."""

        async def failing_handler(account_id: str) -> None:
            if account_id == "test-account-001":
                raise RuntimeError("Simulated error")

        async with create_test_account_manager(mock_redis, 2) as manager:
            manager.set_signal_handler(failing_handler)
            await manager.start_all_accounts()

            # Wait for error to propagate
            await asyncio.sleep(0.2)

            # Account 1 should be in error state, account 2 still running
            mock_redis.save_account_status.assert_any_call("test-account-001", "error")
            assert "test-account-002" in manager._tasks

    @pytest.mark.asyncio
    async def test_hot_reload_add_account(self, mock_redis):
        """AC4: Hot-reload adds new account without affecting existing."""
        async with create_test_account_manager(mock_redis, 2) as manager:
            # Start existing accounts
            await manager.start_all_accounts()
            initial_count = len(manager._tasks)

            # Create config with new account
            new_config = create_config_with_new_account("personal-002")

            # Hot-reload
            await manager.add_account("personal-002", new_config)

            # Verify new account added and running
            assert len(manager._tasks) == initial_count + 1
            assert "personal-002" in manager._tasks


class TestAccountHealth:
    """Tests for account health tracking."""

    @pytest.mark.asyncio
    async def test_health_heartbeat_updated(self, mock_redis):
        """Health heartbeat updates during account loop."""
        async with create_test_account_manager(mock_redis, 1) as manager:
            await manager._spawn_account_task("test-account-001")
            await asyncio.sleep(0.15)  # Let loop run a couple iterations

            mock_redis.update_account_health.assert_called()

    @pytest.mark.asyncio
    async def test_health_cleared_on_stop(self, mock_redis):
        """Health data cleared when account stops."""
        async with create_test_account_manager(mock_redis, 1) as manager:
            await manager._spawn_account_task("test-account-001")
            await asyncio.sleep(0.05)  # Let task start
            await manager.stop_account("test-account-001")

            mock_redis.clear_account_health.assert_called_with("test-account-001")


class TestAlertPayloadValidation:
    """Tests for alert publishing payload format."""

    @pytest.mark.asyncio
    async def test_error_alert_payload_format(self, mock_redis):
        """Verify alert payload contains required fields."""
        async with create_test_account_manager(mock_redis, 1) as manager:

            async def failing_handler(account_id: str) -> None:
                raise RuntimeError("Test error message")

            manager.set_signal_handler(failing_handler)
            await manager.start_all_accounts()
            await asyncio.sleep(0.2)  # Let error propagate

            # Verify publish_alert was called with correct arguments
            mock_redis.publish_alert.assert_called()
            call_args = mock_redis.publish_alert.call_args

            # Check positional arguments
            assert call_args[0][0] == "test-account-001"  # account_id
            assert call_args[0][1] == "error"  # alert_type
            assert "Test error message" in call_args[0][2]  # message contains error

    @pytest.mark.asyncio
    async def test_health_includes_error_count(self, mock_redis):
        """Verify health data includes error_count field."""
        async with create_test_account_manager(mock_redis, 1) as manager:
            await manager._spawn_account_task("test-account-001")
            await asyncio.sleep(0.15)

            # Verify update_account_health was called
            mock_redis.update_account_health.assert_called()
            call_args = mock_redis.update_account_health.call_args

            # Check health data contains error_count
            health_data = call_args[0][1]
            assert "error_count" in health_data
            assert "last_heartbeat" in health_data
            assert "status" in health_data


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
        mock_config = create_config_with_new_account("test-account-001")

        with pytest.raises(ValueError, match="already loaded"):
            await account_manager.add_account("test-account-001", mock_config)

    @pytest.mark.asyncio
    async def test_add_account_not_in_config(self, account_manager):
        """Adding an account not in config raises ValueError."""
        mock_config = create_config_with_new_account("different-account")

        with pytest.raises(ValueError, match="not found in config"):
            await account_manager.add_account("nonexistent-account", mock_config)

    @pytest.mark.asyncio
    async def test_start_accounts_no_signal_handler(self, mock_redis):
        """Accounts start even without signal handler (handler is optional)."""
        async with create_test_account_manager(mock_redis, 1) as manager:
            # No signal handler set
            manager._signal_handler = None

            await manager.start_all_accounts()

            # Tasks should still be created
            assert len(manager._tasks) >= 1

    @pytest.mark.asyncio
    async def test_spawn_task_already_running(self, mock_redis):
        """Spawning task for account with existing task logs warning."""
        async with create_test_account_manager(mock_redis, 1) as manager:
            await manager._spawn_account_task("test-account-001")

            # Try to spawn again
            await manager._spawn_account_task("test-account-001")

            # Should not create duplicate task
            assert len(manager._tasks) == 1

    @pytest.mark.asyncio
    async def test_shutdown_cancels_all_tasks(self, mock_redis):
        """Shutdown cancels all running tasks and closes Redis."""
        manager = AccountManager(mock_redis)
        config = create_config_with_n_accounts(2)
        manager.load_accounts(config)

        await manager.start_all_accounts()
        await asyncio.sleep(0.05)  # Let tasks start

        await manager.shutdown()

        assert len(manager._tasks) == 0
        mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_with_no_running_tasks(self, mock_redis):
        """Shutdown is safe when no tasks are running."""
        manager = AccountManager(mock_redis)
        config = create_config_with_n_accounts(2)
        manager.load_accounts(config)

        # Don't start any tasks, just shutdown immediately
        await manager.shutdown()

        assert len(manager._tasks) == 0
        mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_count_increments_on_repeated_errors(self, mock_redis):
        """Error count increments correctly on repeated errors."""
        manager = AccountManager(mock_redis)
        config = create_config_with_n_accounts(1)
        manager.load_accounts(config)

        # Manually trigger error handling multiple times
        await manager._handle_account_error("test-account-001", RuntimeError("Error 1"))
        await manager._handle_account_error("test-account-001", RuntimeError("Error 2"))

        # Error count should be 2
        assert manager._error_counts.get("test-account-001") == 2
