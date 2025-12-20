"""Tests for AccountManager class."""

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
