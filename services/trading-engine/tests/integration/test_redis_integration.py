"""Integration tests for Redis state persistence.

These tests require a running Redis instance. Set TEST_REDIS_URL
environment variable to point to your test Redis instance.

Run with:
    docker run -d --name test-redis -p 6380:6379 redis:7-alpine
    TEST_REDIS_URL=redis://localhost:6380 uv run pytest tests/integration/ -v -m integration
    docker stop test-redis && docker rm test-redis
"""

import os

import pytest

from src.accounts.account_manager import AccountManager
from src.accounts.models import AccountConfig, AccountsConfig, AccountType, MT5Config
from src.accounts.state import AccountState
from src.state.redis_state import RedisStateManager


@pytest.fixture
def redis_url():
    """Get Redis URL from environment or use default test URL."""
    return os.getenv("TEST_REDIS_URL", "redis://localhost:6380")


@pytest.fixture
async def redis_manager(redis_url):
    """Create real Redis connection for integration tests."""
    manager = RedisStateManager(redis_url)
    await manager.connect()
    yield manager
    # Cleanup test keys
    try:
        async for key in manager.client.scan_iter("account:test-*:status"):
            await manager.client.delete(key)
    except Exception:
        pass
    await manager.close()


@pytest.fixture
def sample_config():
    """Create sample AccountsConfig for testing."""
    return AccountsConfig(
        accounts=[
            AccountConfig(
                id="test-integration-001",
                name="Integration Test Account 1",
                type=AccountType.DEMO,
                mt5=MT5Config(
                    server="TestServer",
                    login=12345,
                    password_env="TEST_PASSWORD",
                ),
                strategy="test_strategy",
            ),
            AccountConfig(
                id="test-integration-002",
                name="Integration Test Account 2",
                type=AccountType.DEMO,
                mt5=MT5Config(
                    server="TestServer",
                    login=67890,
                    password_env="TEST_PASSWORD",
                ),
                strategy="test_strategy",
            ),
        ]
    )


@pytest.fixture
async def account_manager(redis_manager, sample_config):
    """Create AccountManager with real Redis connection."""
    manager = AccountManager(redis_manager)
    manager.load_accounts(sample_config)
    return manager


@pytest.mark.integration
class TestRedisStateManagerIntegration:
    """Integration tests for RedisStateManager."""

    @pytest.mark.asyncio
    async def test_save_and_get_status(self, redis_manager):
        """Test Redis persistence roundtrip."""
        await redis_manager.save_account_status("test-int-001", AccountState.ACTIVE.value)
        status = await redis_manager.get_account_status("test-int-001")
        assert status == "active"

    @pytest.mark.asyncio
    async def test_get_nonexistent_status(self, redis_manager):
        """Test getting status for nonexistent account."""
        status = await redis_manager.get_account_status("test-nonexistent")
        assert status is None

    @pytest.mark.asyncio
    async def test_update_status(self, redis_manager):
        """Test updating existing status."""
        await redis_manager.save_account_status("test-int-001", "active")
        await redis_manager.save_account_status("test-int-001", "paused")
        status = await redis_manager.get_account_status("test-int-001")
        assert status == "paused"

    @pytest.mark.asyncio
    async def test_get_all_statuses(self, redis_manager):
        """Test scanning all account statuses."""
        await redis_manager.save_account_status("test-int-001", "active")
        await redis_manager.save_account_status("test-int-002", "paused")

        statuses = await redis_manager.get_all_account_statuses()

        # Filter to only our test accounts
        test_statuses = {k: v for k, v in statuses.items() if k.startswith("test-int-")}
        assert len(test_statuses) >= 2
        assert test_statuses.get("test-int-001") == "active"
        assert test_statuses.get("test-int-002") == "paused"

    @pytest.mark.asyncio
    async def test_delete_status(self, redis_manager):
        """Test deleting account status."""
        await redis_manager.save_account_status("test-int-001", "active")
        await redis_manager.delete_account_status("test-int-001")
        status = await redis_manager.get_account_status("test-int-001")
        assert status is None


@pytest.mark.integration
class TestAccountManagerIntegration:
    """Integration tests for AccountManager with real Redis."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, account_manager, redis_manager):
        """Test complete account lifecycle: start → pause → resume → stop."""
        account_id = "test-integration-001"

        # Start account
        await account_manager.start_account(account_id)
        status = await redis_manager.get_account_status(account_id)
        assert status == "active"

        # Pause account
        await account_manager.pause_account(account_id)
        status = await redis_manager.get_account_status(account_id)
        assert status == "paused"

        # Resume account
        await account_manager.resume_account(account_id)
        status = await redis_manager.get_account_status(account_id)
        assert status == "active"

        # Stop account
        await account_manager.stop_account(account_id)
        status = await redis_manager.get_account_status(account_id)
        assert status == "stopped"

        # Restart stopped account
        await account_manager.start_account(account_id)
        status = await redis_manager.get_account_status(account_id)
        assert status == "active"

    @pytest.mark.asyncio
    async def test_error_workflow(self, account_manager, redis_manager):
        """Test error state workflow: active → error → acknowledge → stopped."""
        account_id = "test-integration-001"

        # Start account
        await account_manager.start_account(account_id)

        # Simulate error
        await account_manager.set_error(account_id)
        status = await redis_manager.get_account_status(account_id)
        assert status == "error"

        # Acknowledge error
        await account_manager.acknowledge_error(account_id)
        status = await redis_manager.get_account_status(account_id)
        assert status == "stopped"

    @pytest.mark.asyncio
    async def test_get_all_statuses(self, account_manager, redis_manager):
        """Test getting all configured account statuses."""
        # Start first account
        await account_manager.start_account("test-integration-001")
        # Pause second account after starting
        await account_manager.start_account("test-integration-002")
        await account_manager.pause_account("test-integration-002")

        statuses = await account_manager.get_all_statuses()

        assert statuses["test-integration-001"] == "active"
        assert statuses["test-integration-002"] == "paused"

    @pytest.mark.asyncio
    async def test_invalid_transition_rejected(self, account_manager):
        """Test that invalid state transitions are rejected."""
        account_id = "test-integration-001"

        # Start and stop account
        await account_manager.start_account(account_id)
        await account_manager.stop_account(account_id)

        # Cannot pause a stopped account
        with pytest.raises(ValueError) as exc_info:
            await account_manager.pause_account(account_id)
        assert "Cannot transition" in str(exc_info.value)
