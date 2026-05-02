"""Integration tests for multi-account orchestration with Redis.

These tests require a running Redis instance on port 6380 (test Redis).
They test the full account orchestration flow including:
- Concurrent account startup
- Per-account stop without affecting others
- Error isolation between accounts
- Hot-reload of new accounts
- Health heartbeat tracking
"""

import asyncio
import os

import pytest

from src.accounts.account_manager import AccountManager
from src.accounts.models import AccountConfig, AccountsConfig, AccountType, MT5Config
from src.state.redis_state import RedisStateManager


# Skip all tests if Redis is not available
pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_REDIS_TESTS", "true").lower() == "true",
    reason="Redis integration tests disabled (set SKIP_REDIS_TESTS=false to enable)",
)


def create_test_accounts(n: int) -> AccountsConfig:
    """Create AccountsConfig with n test accounts."""
    accounts = []
    for i in range(1, n + 1):
        accounts.append(
            AccountConfig(
                id=f"orch-test-{i:03d}",
                name=f"Orchestration Test Account {i}",
                type=AccountType.DEMO,
                mt5=MT5Config(
                    server="TestServer",
                    login=20000 + i,
                    password_env=f"MT5_ORCH_TEST_{i}",
                ),
                strategy="ma_crossover",
                status="active",
            )
        )
    return AccountsConfig(accounts=accounts)


@pytest.fixture
async def redis_manager():
    """Create and connect Redis manager for tests."""
    redis_url = os.getenv("TEST_REDIS_URL", "redis://localhost:6380")
    manager = RedisStateManager(redis_url)
    await manager.connect()
    yield manager
    # Cleanup: delete all test keys
    async for key in manager.client.scan_iter("account:orch-test-*"):
        await manager.client.delete(key)
    await manager.close()


@pytest.fixture
async def account_manager(redis_manager):
    """Create AccountManager with test accounts."""
    manager = AccountManager(redis_manager)
    config = create_test_accounts(3)
    manager.load_accounts(config)
    yield manager
    # Cleanup: ensure all tasks are stopped
    await manager.shutdown()


class TestMultiAccountOrchestrationIntegration:
    """Integration tests for multi-account orchestration."""

    @pytest.mark.asyncio
    async def test_start_all_accounts_creates_tasks(self, account_manager, redis_manager):
        """AC1: All active accounts start concurrently with real Redis."""
        await account_manager.start_all_accounts()

        # Verify tasks are running
        assert len(account_manager._tasks) == 3

        # Verify Redis has status for all accounts
        for i in range(1, 4):
            account_id = f"orch-test-{i:03d}"
            status = await redis_manager.get_account_status(account_id)
            assert status == "active"

    @pytest.mark.asyncio
    async def test_stop_one_account_others_continue(self, account_manager, redis_manager):
        """AC2: Stopping one account doesn't affect others with real Redis."""
        await account_manager.start_all_accounts()
        await asyncio.sleep(0.1)  # Let tasks start

        # Stop first account
        await account_manager.stop_account("orch-test-001")

        # Verify first is stopped
        assert "orch-test-001" not in account_manager._tasks
        status = await redis_manager.get_account_status("orch-test-001")
        assert status == "stopped"

        # Verify others still running
        assert "orch-test-002" in account_manager._tasks
        assert "orch-test-003" in account_manager._tasks

    @pytest.mark.asyncio
    async def test_error_isolation_with_redis(self, account_manager, redis_manager):
        """AC3: One account error doesn't crash others with real Redis."""

        async def failing_handler(account_id: str) -> None:
            if account_id == "orch-test-001":
                raise RuntimeError("Simulated MT5 disconnect")

        account_manager.set_signal_handler(failing_handler)
        await account_manager.start_all_accounts()
        await asyncio.sleep(0.3)  # Let error propagate

        # Account 1 should be in error state
        status = await redis_manager.get_account_status("orch-test-001")
        assert status == "error"

        # Error should be recorded
        last_error = await redis_manager.get_account_last_error("orch-test-001")
        assert "Simulated MT5 disconnect" in last_error

        # Others should still be active
        assert "orch-test-002" in account_manager._tasks
        assert "orch-test-003" in account_manager._tasks

    @pytest.mark.asyncio
    async def test_hot_reload_add_account(self, account_manager, redis_manager):
        """AC4: Hot-reload adds new account without affecting existing."""
        await account_manager.start_all_accounts()
        initial_count = len(account_manager._tasks)

        # Create config with new account
        new_config = AccountsConfig(
            accounts=[
                AccountConfig(
                    id="orch-test-new",
                    name="Hot Reload Test",
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

        # Hot-reload new account
        await account_manager.add_account("orch-test-new", new_config)

        # Verify new account added
        assert len(account_manager._tasks) == initial_count + 1
        assert "orch-test-new" in account_manager._tasks

        # Verify Redis has status
        status = await redis_manager.get_account_status("orch-test-new")
        assert status == "active"


class TestHealthTrackingIntegration:
    """Integration tests for health heartbeat tracking."""

    @pytest.mark.asyncio
    async def test_health_heartbeat_written_to_redis(self, account_manager, redis_manager):
        """Health heartbeat is written to Redis with TTL."""
        await account_manager.start_all_accounts()
        await asyncio.sleep(0.2)  # Let a few heartbeats happen

        # Check health data exists
        health = await redis_manager.get_account_health("orch-test-001")
        assert health is not None
        assert "last_heartbeat" in health
        assert health["status"] == "healthy"
        assert "error_count" in health

        # Check TTL is set (should be ~60s)
        ttl = await redis_manager.client.ttl("account:orch-test-001:health")
        assert 0 < ttl <= 60

    @pytest.mark.asyncio
    async def test_health_cleared_on_stop(self, account_manager, redis_manager):
        """Health data is cleared when account stops."""
        await account_manager.start_all_accounts()
        await asyncio.sleep(0.15)  # Let health be written

        # Verify health exists
        health = await redis_manager.get_account_health("orch-test-001")
        assert health is not None

        # Stop account
        await account_manager.stop_account("orch-test-001")

        # Health should be cleared
        health = await redis_manager.get_account_health("orch-test-001")
        assert health is None


class TestAlertPublishingIntegration:
    """Integration tests for alert publishing via Redis pub/sub."""

    @pytest.mark.asyncio
    async def test_error_alert_published(self, account_manager, redis_manager):
        """Error alerts are published to Redis pub/sub channel."""
        received_alerts = []

        # Subscribe to alert channel
        pubsub = redis_manager.client.pubsub()
        await pubsub.subscribe("alerts:error:orch-test-001")

        async def failing_handler(account_id: str) -> None:
            if account_id == "orch-test-001":
                raise RuntimeError("Test error for alert")

        account_manager.set_signal_handler(failing_handler)
        await account_manager.start_all_accounts()

        # Wait for error and alert
        await asyncio.sleep(0.3)

        # Check for message (with timeout)
        message = await asyncio.wait_for(pubsub.get_message(timeout=1.0), timeout=2.0)
        while message and message["type"] == "subscribe":
            message = await asyncio.wait_for(pubsub.get_message(timeout=1.0), timeout=2.0)

        await pubsub.unsubscribe()
        await pubsub.aclose()

        # Verify alert was published
        assert message is not None
        assert message["type"] == "message"
        assert b"Test error for alert" in message["data"]
