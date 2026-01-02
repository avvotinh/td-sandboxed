"""Integration tests for CrashRecoveryManager with Redis.

These tests require a running Redis instance. Set TEST_REDIS_URL
environment variable to point to your test Redis instance.

Run with:
    # Using standard Redis port (default):
    uv run pytest tests/integration/test_crash_recovery_redis.py -v -m integration

    # Or with Docker:
    docker run -d --name test-redis -p 6380:6379 redis:7-alpine
    TEST_REDIS_URL=redis://localhost:6380 uv run pytest tests/integration/test_crash_recovery_redis.py -v -m integration
    docker stop test-redis && docker rm test-redis
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.state.crash_recovery import CrashRecoveryManager
from src.state.redis_state import RedisStateManager
from src.state.snapshot import StateSnapshot


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
    except Exception:
        pass
    await manager.close()


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


@pytest.mark.integration
class TestShutdownFlagPersistence:
    """Tests for shutdown flag persistence in Redis (AC: 5)."""

    @pytest.mark.asyncio
    async def test_set_shutdown_flag_persists(self, crash_recovery, redis_manager):
        """Shutdown flag should persist in Redis."""
        await crash_recovery.set_clean_shutdown_flag()

        # Verify key exists in Redis
        exists = await redis_manager.client.exists("engine:shutdown:clean")
        assert exists == 1

    @pytest.mark.asyncio
    async def test_shutdown_flag_value_is_timestamp(
        self, crash_recovery, redis_manager
    ):
        """Shutdown flag value should be ISO timestamp."""
        await crash_recovery.set_clean_shutdown_flag()

        value = await redis_manager.client.get("engine:shutdown:clean")
        assert value is not None
        # Should parse as ISO timestamp
        parsed = datetime.fromisoformat(value)
        assert parsed.tzinfo is not None

    @pytest.mark.asyncio
    async def test_clear_shutdown_flag_deletes(self, crash_recovery, redis_manager):
        """clear_clean_shutdown_flag should remove key."""
        await crash_recovery.set_clean_shutdown_flag()
        await crash_recovery.clear_clean_shutdown_flag()

        exists = await redis_manager.client.exists("engine:shutdown:clean")
        assert exists == 0

    @pytest.mark.asyncio
    async def test_has_shutdown_flag_detects_presence(
        self, crash_recovery, redis_manager
    ):
        """has_clean_shutdown_flag should detect key presence."""
        # Initially no flag
        assert await crash_recovery.has_clean_shutdown_flag() is False

        # Set flag
        await crash_recovery.set_clean_shutdown_flag()
        assert await crash_recovery.has_clean_shutdown_flag() is True

        # Clear flag
        await crash_recovery.clear_clean_shutdown_flag()
        assert await crash_recovery.has_clean_shutdown_flag() is False


@pytest.mark.integration
class TestProcessLockAtomicity:
    """Tests for process lock atomic acquisition with SET NX EX (AC: 6)."""

    @pytest.mark.asyncio
    async def test_acquire_lock_success(self, crash_recovery, redis_manager):
        """First lock acquisition should succeed."""
        # Ensure no existing lock
        await redis_manager.client.delete("engine:lock:process")

        result = await crash_recovery.acquire_process_lock()

        assert result is True
        exists = await redis_manager.client.exists("engine:lock:process")
        assert exists == 1

    @pytest.mark.asyncio
    async def test_acquire_lock_blocked_by_existing(self, redis_manager):
        """Second instance should fail to acquire lock."""
        # First instance acquires lock
        manager1 = CrashRecoveryManager(redis_manager=redis_manager)
        await redis_manager.client.delete("engine:lock:process")
        result1 = await manager1.acquire_process_lock()
        assert result1 is True

        # Second instance tries to acquire
        manager2 = CrashRecoveryManager(redis_manager=redis_manager)
        result2 = await manager2.acquire_process_lock()

        assert result2 is False

    @pytest.mark.asyncio
    async def test_lock_has_correct_ttl(self, crash_recovery, redis_manager):
        """Lock should have 60 second TTL."""
        await redis_manager.client.delete("engine:lock:process")
        await crash_recovery.acquire_process_lock()

        ttl = await redis_manager.client.ttl("engine:lock:process")

        # TTL should be close to 60 (within 2 seconds)
        assert 58 <= ttl <= 60

    @pytest.mark.asyncio
    async def test_lock_value_format(self, crash_recovery, redis_manager):
        """Lock value should contain hostname:pid:timestamp."""
        await redis_manager.client.delete("engine:lock:process")
        await crash_recovery.acquire_process_lock()

        value = await redis_manager.client.get("engine:lock:process")

        assert value is not None
        parts = value.split(":")
        # Should have hostname, pid, and ISO timestamp (which has colons)
        assert len(parts) >= 3
        # Second part should be numeric (PID)
        assert parts[1].isdigit()

    @pytest.mark.asyncio
    async def test_release_lock_deletes_key(self, crash_recovery, redis_manager):
        """release_process_lock should delete the key."""
        await redis_manager.client.delete("engine:lock:process")
        await crash_recovery.acquire_process_lock()
        await crash_recovery.release_process_lock()

        exists = await redis_manager.client.exists("engine:lock:process")
        assert exists == 0


@pytest.mark.integration
class TestLockTTLExpiration:
    """Tests for lock TTL expiration behavior (AC: 1, 6)."""

    @pytest.mark.asyncio
    async def test_lock_expires_without_refresh(self, redis_manager):
        """Lock should expire if not refreshed."""
        manager = CrashRecoveryManager(redis_manager=redis_manager)

        # Temporarily use short TTL for testing
        original_ttl = CrashRecoveryManager.LOCK_TTL_SECONDS
        CrashRecoveryManager.LOCK_TTL_SECONDS = 1  # 1 second

        try:
            await redis_manager.client.delete("engine:lock:process")
            await manager.acquire_process_lock()

            # Verify lock exists
            assert await redis_manager.client.exists("engine:lock:process") == 1

            # Wait for expiration
            await asyncio.sleep(1.5)

            # Lock should be gone
            assert await redis_manager.client.exists("engine:lock:process") == 0
        finally:
            CrashRecoveryManager.LOCK_TTL_SECONDS = original_ttl

    @pytest.mark.asyncio
    async def test_refresh_extends_ttl(self, crash_recovery, redis_manager):
        """refresh_process_lock should extend TTL."""
        # Temporarily use short TTL
        original_ttl = CrashRecoveryManager.LOCK_TTL_SECONDS
        CrashRecoveryManager.LOCK_TTL_SECONDS = 2

        try:
            await redis_manager.client.delete("engine:lock:process")
            await crash_recovery.acquire_process_lock()

            # Wait a bit
            await asyncio.sleep(1)

            # Refresh
            result = await crash_recovery.refresh_process_lock()
            assert result is True

            # TTL should be back to full
            ttl = await redis_manager.client.ttl("engine:lock:process")
            assert ttl >= 1  # Should be close to 2
        finally:
            CrashRecoveryManager.LOCK_TTL_SECONDS = original_ttl

    @pytest.mark.asyncio
    async def test_refresh_fails_if_lock_lost(self, crash_recovery, redis_manager):
        """refresh_process_lock should return False if lock expired."""
        await redis_manager.client.delete("engine:lock:process")
        await crash_recovery.acquire_process_lock()

        # Manually delete lock (simulating expiration)
        await redis_manager.client.delete("engine:lock:process")

        result = await crash_recovery.refresh_process_lock()
        assert result is False


@pytest.mark.integration
class TestSnapshotScanForRecovery:
    """Tests for snapshot scanning for recovery accounts (AC: 1, 7)."""

    @pytest.mark.asyncio
    async def test_finds_accounts_with_snapshots(self, crash_recovery, redis_manager):
        """Should find accounts from snapshot keys."""
        # Create test snapshots
        snapshot1 = StateSnapshot(
            account_id="test-recovery-001",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("100000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )
        snapshot1.checksum = snapshot1.compute_checksum()

        snapshot2 = StateSnapshot(
            account_id="test-recovery-002",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("50000"),
            equity=Decimal("50000"),
            peak_balance=Decimal("50000"),
            daily_starting_balance=Decimal("50000"),
            checksum="",
        )
        snapshot2.checksum = snapshot2.compute_checksum()

        await redis_manager.save_snapshot("test-recovery-001", snapshot1)
        await redis_manager.save_snapshot("test-recovery-002", snapshot2)

        accounts = await crash_recovery.get_accounts_needing_recovery()

        assert "test-recovery-001" in accounts
        assert "test-recovery-002" in accounts

    @pytest.mark.asyncio
    async def test_empty_when_no_snapshots(self, crash_recovery, redis_manager):
        """Should return empty list when no snapshots exist."""
        # Ensure no test snapshots
        async for key in redis_manager.client.scan_iter("snapshot:test-*:latest"):
            await redis_manager.client.delete(key)

        accounts = await crash_recovery.get_accounts_needing_recovery()

        # Filter to only test accounts
        test_accounts = [a for a in accounts if a.startswith("test-")]
        assert test_accounts == []


@pytest.mark.integration
class TestFullStartupShutdownCycle:
    """Tests for complete startup/shutdown cycle with Redis (AC: 2, 3, 4, 5)."""

    @pytest.mark.asyncio
    async def test_startup_acquires_lock_and_starts_heartbeat(self, redis_manager):
        """Startup should acquire lock and start heartbeat."""
        # Clean state
        await redis_manager.client.delete("engine:shutdown:clean")
        await redis_manager.client.delete("engine:lock:process")

        manager = CrashRecoveryManager(redis_manager=redis_manager)
        # Set clean shutdown to avoid recovery mode
        await redis_manager.client.set("engine:shutdown:clean", "test")

        try:
            result = await manager.startup_sequence()

            # Should have acquired lock
            assert await redis_manager.client.exists("engine:lock:process") == 1

            # Should have started heartbeat
            assert manager._heartbeat_running is True

            # Should not be in recovery mode (clean shutdown existed)
            assert result.recovery_mode is False
        finally:
            await manager.stop_heartbeat()
            await redis_manager.client.delete("engine:lock:process")

    @pytest.mark.asyncio
    async def test_startup_detects_crash_and_enters_recovery(self, redis_manager):
        """Startup should detect crash and enter recovery mode."""
        # Clean state - no shutdown flag = crash
        await redis_manager.client.delete("engine:shutdown:clean")
        await redis_manager.client.delete("engine:lock:process")

        # Create orphan snapshot
        snapshot = StateSnapshot(
            account_id="test-orphan-001",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("100000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )
        snapshot.checksum = snapshot.compute_checksum()
        await redis_manager.save_snapshot("test-orphan-001", snapshot)

        manager = CrashRecoveryManager(redis_manager=redis_manager)

        try:
            result = await manager.startup_sequence()

            assert result.recovery_mode is True
            assert "test-orphan-001" in result.accounts_needing_recovery
        finally:
            await manager.stop_heartbeat()
            await redis_manager.client.delete("engine:lock:process")

    @pytest.mark.asyncio
    async def test_shutdown_sets_flag_and_releases_lock(self, redis_manager):
        """Shutdown should set flag and release lock."""
        await redis_manager.client.delete("engine:shutdown:clean")
        await redis_manager.client.delete("engine:lock:process")
        await redis_manager.client.set("engine:shutdown:clean", "test")

        manager = CrashRecoveryManager(redis_manager=redis_manager)
        await manager.startup_sequence()

        # Now shutdown
        await manager.shutdown_sequence()

        # Should have set shutdown flag
        assert await redis_manager.client.exists("engine:shutdown:clean") == 1

        # Should have released lock
        assert await redis_manager.client.exists("engine:lock:process") == 0

    @pytest.mark.asyncio
    async def test_full_cycle_clean(self, redis_manager):
        """Complete clean startup -> run -> shutdown cycle."""
        # Initial clean state
        await redis_manager.client.delete("engine:shutdown:clean")
        await redis_manager.client.delete("engine:lock:process")
        await redis_manager.client.set("engine:shutdown:clean", "initial")

        manager = CrashRecoveryManager(redis_manager=redis_manager)

        # Startup
        result = await manager.startup_sequence()
        assert result.recovery_mode is False

        # Simulate work
        await asyncio.sleep(0.1)

        # Shutdown
        await manager.shutdown_sequence()

        # Verify clean state for next startup
        assert await redis_manager.client.exists("engine:shutdown:clean") == 1
        assert await redis_manager.client.exists("engine:lock:process") == 0


@pytest.mark.integration
class TestConcurrentInstancePrevention:
    """Tests for preventing concurrent engine instances (AC: 6)."""

    @pytest.mark.asyncio
    async def test_second_instance_fails_to_start(self, redis_manager):
        """Second instance should fail with RuntimeError."""
        await redis_manager.client.delete("engine:shutdown:clean")
        await redis_manager.client.delete("engine:lock:process")
        await redis_manager.client.set("engine:shutdown:clean", "test")

        # First instance starts
        manager1 = CrashRecoveryManager(redis_manager=redis_manager)
        result1 = await manager1.startup_sequence()
        assert result1 is not None

        try:
            # Second instance tries to start
            manager2 = CrashRecoveryManager(redis_manager=redis_manager)
            with pytest.raises(RuntimeError, match="Another instance is already running"):
                await manager2.startup_sequence()
        finally:
            await manager1.shutdown_sequence()

    @pytest.mark.asyncio
    async def test_instance_can_start_after_previous_shutdown(self, redis_manager):
        """New instance should start after previous instance shuts down."""
        await redis_manager.client.delete("engine:shutdown:clean")
        await redis_manager.client.delete("engine:lock:process")
        await redis_manager.client.set("engine:shutdown:clean", "test")

        # First instance
        manager1 = CrashRecoveryManager(redis_manager=redis_manager)
        await manager1.startup_sequence()
        await manager1.shutdown_sequence()

        # Second instance after shutdown
        manager2 = CrashRecoveryManager(redis_manager=redis_manager)
        try:
            result = await manager2.startup_sequence()
            assert result is not None
        finally:
            await manager2.shutdown_sequence()

    @pytest.mark.asyncio
    async def test_instance_can_start_after_lock_expiration(self, redis_manager):
        """New instance should start after crashed instance lock expires."""
        original_ttl = CrashRecoveryManager.LOCK_TTL_SECONDS
        CrashRecoveryManager.LOCK_TTL_SECONDS = 1

        try:
            await redis_manager.client.delete("engine:shutdown:clean")
            await redis_manager.client.delete("engine:lock:process")

            # Simulate crashed instance (lock but no heartbeat, no shutdown flag)
            await redis_manager.client.set(
                "engine:lock:process",
                "crashed:123:timestamp",
                ex=1,  # 1 second TTL
            )

            # Wait for lock to expire
            await asyncio.sleep(1.5)

            # New instance should be able to start (and detect crash)
            manager = CrashRecoveryManager(redis_manager=redis_manager)
            try:
                result = await manager.startup_sequence()
                # Should have detected crash (no shutdown flag)
                assert result.recovery_mode is True
            finally:
                await manager.shutdown_sequence()
        finally:
            CrashRecoveryManager.LOCK_TTL_SECONDS = original_ttl


@pytest.mark.integration
class TestPerformance:
    """Tests for crash detection performance requirements."""

    @pytest.mark.asyncio
    async def test_crash_detection_under_50ms(self, crash_recovery, redis_manager):
        """Crash detection should complete in under 50ms."""
        # Warm up
        await crash_recovery.check_crash_indicators()

        start = time.perf_counter()
        await crash_recovery.check_crash_indicators()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 50, f"Crash detection took {elapsed_ms:.2f}ms"

    @pytest.mark.asyncio
    async def test_lock_acquisition_under_10ms(self, crash_recovery, redis_manager):
        """Lock acquisition should complete in under 10ms."""
        await redis_manager.client.delete("engine:lock:process")

        start = time.perf_counter()
        await crash_recovery.acquire_process_lock()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"Lock acquisition took {elapsed_ms:.2f}ms"
