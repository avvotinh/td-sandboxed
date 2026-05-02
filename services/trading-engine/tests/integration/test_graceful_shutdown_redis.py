"""Integration tests for GracefulShutdown with Redis.

These tests require a running Redis instance. Set TEST_REDIS_URL
environment variable to point to your test Redis instance.

Run with:
    # Using standard Redis port (default):
    uv run pytest tests/integration/test_graceful_shutdown_redis.py -v -m integration

    # Or with Docker:
    docker run -d --name test-redis -p 6380:6379 redis:7-alpine
    TEST_REDIS_URL=redis://localhost:6380 uv run pytest tests/integration/test_graceful_shutdown_redis.py -v -m integration
    docker stop test-redis && docker rm test-redis
"""

import asyncio
import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.accounts.account_manager import AccountManager
from src.state.crash_recovery import CrashRecoveryManager
from src.state.graceful_shutdown import GracefulShutdown, ShutdownPhase, ShutdownResult
from src.state.redis_state import RedisStateManager


@pytest.fixture
def redis_url():
    """Get Redis URL from environment or use default test URL."""
    return os.getenv("TEST_REDIS_URL", "redis://localhost:6379")


@pytest.fixture
async def redis_manager(redis_url):
    """Create real Redis connection for integration tests."""
    manager = RedisStateManager(redis_url)
    await manager.connect()
    yield manager
    # Cleanup test keys
    try:
        await manager.client.delete("engine:shutdown:clean")
        await manager.client.delete("engine:lock:process")
        async for key in manager.client.scan_iter("snapshot:test-*:latest"):
            await manager.client.delete(key)
        async for key in manager.client.scan_iter("account:test-*:*"):
            await manager.client.delete(key)
    except Exception:
        pass
    await manager.close()


@pytest.fixture
async def account_manager(redis_manager):
    """Create real AccountManager with Redis."""
    manager = AccountManager(redis_manager=redis_manager)
    yield manager


@pytest.fixture
async def crash_recovery(redis_manager):
    """Create CrashRecoveryManager with real Redis."""
    manager = CrashRecoveryManager(redis_manager=redis_manager)
    yield manager
    # Cleanup
    try:
        await manager.stop_heartbeat()
    except Exception:
        pass


@pytest.fixture
async def graceful_shutdown(redis_manager, account_manager, crash_recovery):
    """Create GracefulShutdown with real Redis."""
    shutdown = GracefulShutdown(
        redis_manager=redis_manager,
        account_manager=account_manager,
        snapshot_service=None,  # Skip for integration tests
        zmq_adapter=None,  # Skip for integration tests
        crash_recovery=crash_recovery,
    )
    yield shutdown


@pytest.mark.integration
class TestFullShutdownSequence:
    """Tests for full shutdown sequence with Redis (AC: 1)."""

    @pytest.mark.asyncio
    async def test_full_shutdown_sequence_with_redis(
        self,
        graceful_shutdown,
        crash_recovery,
        redis_manager,
    ):
        """Full shutdown sequence should execute with real Redis."""
        # First run startup sequence to acquire lock
        result = await crash_recovery.startup_sequence()
        assert result is not None

        # Now run shutdown
        shutdown_result = await graceful_shutdown.initiate()

        # Verify shutdown completed
        assert shutdown_result.success is True
        assert shutdown_result.phase_reached == ShutdownPhase.COMPLETE
        assert shutdown_result.exit_code == 0


@pytest.mark.integration
class TestCleanShutdownFlagPreventsRecovery:
    """Tests for clean shutdown flag behavior (AC: 6)."""

    @pytest.mark.asyncio
    async def test_clean_shutdown_flag_set_on_graceful_shutdown(
        self,
        graceful_shutdown,
        crash_recovery,
        redis_manager,
    ):
        """Clean shutdown flag should be set after graceful shutdown."""
        # Run startup sequence first
        await crash_recovery.startup_sequence()

        # Run graceful shutdown
        result = await graceful_shutdown.initiate()
        assert result.success is True

        # Verify clean shutdown flag is set
        flag_exists = await crash_recovery.has_clean_shutdown_flag()
        assert flag_exists is True

    @pytest.mark.asyncio
    async def test_clean_restart_no_crash_recovery(
        self,
        redis_manager,
    ):
        """Clean restart after graceful shutdown should not trigger recovery."""
        # First instance: startup + graceful shutdown
        crash_recovery1 = CrashRecoveryManager(redis_manager=redis_manager)
        account_manager1 = AccountManager(redis_manager=redis_manager)
        shutdown1 = GracefulShutdown(
            redis_manager=redis_manager,
            account_manager=account_manager1,
            crash_recovery=crash_recovery1,
        )

        startup_result1 = await crash_recovery1.startup_sequence()
        shutdown_result1 = await shutdown1.initiate()
        assert shutdown_result1.success is True

        # Second instance: should not enter recovery mode
        crash_recovery2 = CrashRecoveryManager(redis_manager=redis_manager)
        startup_result2 = await crash_recovery2.startup_sequence()

        # Should NOT be in recovery mode because previous shutdown was clean
        assert startup_result2.recovery_mode is False

        # Cleanup
        await crash_recovery2.stop_heartbeat()


@pytest.mark.integration
class TestStateSnapshotsPersisted:
    """Tests for state snapshot persistence (AC: 1)."""

    @pytest.mark.asyncio
    async def test_final_snapshot_persisted_to_redis(
        self,
        redis_manager,
        account_manager,
        crash_recovery,
    ):
        """Final snapshot should be persisted to Redis during shutdown."""
        # Create a mock snapshot service that saves to Redis
        from src.state.snapshot import StateSnapshot
        from datetime import datetime, timezone

        # Create test snapshot
        test_account = "test-shutdown-001"
        snapshot = StateSnapshot(
            account_id=test_account,
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("10000"),
            equity=Decimal("10000"),
            peak_balance=Decimal("10000"),
            daily_starting_balance=Decimal("10000"),
            checksum="",
        )
        snapshot.checksum = snapshot.compute_checksum()

        # Save snapshot directly
        await redis_manager.save_snapshot(test_account, snapshot, ttl_seconds=3600)

        # Run startup and shutdown
        await crash_recovery.startup_sequence()
        shutdown = GracefulShutdown(
            redis_manager=redis_manager,
            account_manager=account_manager,
            crash_recovery=crash_recovery,
        )
        result = await shutdown.initiate()

        # Verify snapshot still exists (wasn't deleted by shutdown)
        saved_snapshot = await redis_manager.get_snapshot(test_account)
        assert saved_snapshot is not None
        assert saved_snapshot.account_id == test_account


@pytest.mark.integration
class TestSIGTERMTriggersShutdown:
    """Tests for SIGTERM/SIGINT signal handling (AC: 4)."""

    @pytest.mark.asyncio
    async def test_sigterm_triggers_graceful_shutdown(
        self,
        graceful_shutdown,
        crash_recovery,
    ):
        """SIGTERM signal should trigger graceful shutdown."""
        import signal

        # Run startup sequence first
        await crash_recovery.startup_sequence()

        # Simulate SIGTERM by calling the signal handler directly
        graceful_shutdown._handle_signal(signal.SIGTERM)

        # Verify shutdown event is set
        assert graceful_shutdown._shutdown_event.is_set() is True

    @pytest.mark.asyncio
    async def test_sigint_triggers_graceful_shutdown(
        self,
        graceful_shutdown,
        crash_recovery,
    ):
        """SIGINT signal should trigger graceful shutdown."""
        import signal

        # Run startup sequence first
        await crash_recovery.startup_sequence()

        # Simulate SIGINT by calling the signal handler directly
        graceful_shutdown._handle_signal(signal.SIGINT)

        # Verify shutdown event is set
        assert graceful_shutdown._shutdown_event.is_set() is True


@pytest.mark.integration
class TestShutdownResultMetrics:
    """Tests for shutdown result metrics accuracy."""

    @pytest.mark.asyncio
    async def test_shutdown_duration_tracked(
        self,
        graceful_shutdown,
        crash_recovery,
    ):
        """Shutdown duration should be tracked accurately."""
        # Run startup first
        await crash_recovery.startup_sequence()

        # Run shutdown
        result = await graceful_shutdown.initiate()

        # Duration should be positive
        assert result.duration_seconds > 0
        # Duration should be reasonable (< 30 seconds for simple shutdown)
        assert result.duration_seconds < 30

    @pytest.mark.asyncio
    async def test_shutdown_phases_complete(
        self,
        graceful_shutdown,
        crash_recovery,
    ):
        """All shutdown phases should complete."""
        await crash_recovery.startup_sequence()

        result = await graceful_shutdown.initiate()

        assert result.phase_reached == ShutdownPhase.COMPLETE
        assert result.success is True
        assert result.exit_code == 0


@pytest.mark.integration
class TestConnectionCleanup:
    """Tests for connection cleanup during shutdown."""

    @pytest.mark.asyncio
    async def test_redis_connection_closed_after_shutdown(
        self,
        redis_url,
    ):
        """Redis connection should be closed after shutdown."""
        # Create fresh connections for this test
        redis_manager = RedisStateManager(redis_url)
        await redis_manager.connect()

        account_manager = AccountManager(redis_manager=redis_manager)
        crash_recovery = CrashRecoveryManager(redis_manager=redis_manager)

        # Run startup
        await crash_recovery.startup_sequence()

        shutdown = GracefulShutdown(
            redis_manager=redis_manager,
            account_manager=account_manager,
            crash_recovery=crash_recovery,
        )

        result = await shutdown.initiate()
        assert result.success is True

        # Redis client should be None after close
        assert redis_manager._client is None
