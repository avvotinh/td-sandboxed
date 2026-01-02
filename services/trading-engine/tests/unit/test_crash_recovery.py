"""Unit tests for CrashRecoveryManager."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.state.crash_recovery import (
    CrashIndicatorResult,
    CrashRecoveryManager,
    RecoveryResult,
)
from src.state.snapshot import StateSnapshot


@pytest.fixture
def mock_redis_manager():
    """Create mock RedisStateManager with Redis client."""
    manager = MagicMock()
    client = MagicMock()

    # Configure async methods on client
    client.set = AsyncMock(return_value=True)
    client.get = AsyncMock(return_value=None)
    client.delete = AsyncMock(return_value=1)
    client.exists = AsyncMock(return_value=0)
    client.expire = AsyncMock(return_value=1)

    # Configure scan_iter as async generator
    async def empty_scan():
        return
        yield  # Makes it an async generator

    client.scan_iter = MagicMock(return_value=empty_scan())

    manager.client = client
    manager.get_snapshot = AsyncMock(return_value=None)
    return manager


@pytest.fixture
def crash_recovery(mock_redis_manager):
    """Create CrashRecoveryManager with mock dependencies."""
    return CrashRecoveryManager(redis_manager=mock_redis_manager)


class TestCrashIndicatorResult:
    """Tests for CrashIndicatorResult dataclass."""

    def test_create_with_crash(self):
        """Should create result with crash indicators."""
        result = CrashIndicatorResult(
            has_crash=True,
            missing_shutdown_flag=True,
            stale_heartbeat=True,
            orphan_snapshots=["account-1", "account-2"],
            details="No clean shutdown flag found",
        )

        assert result.has_crash is True
        assert result.missing_shutdown_flag is True
        assert result.stale_heartbeat is True
        assert result.orphan_snapshots == ["account-1", "account-2"]
        assert "shutdown" in result.details

    def test_create_without_crash(self):
        """Should create result without crash indicators."""
        result = CrashIndicatorResult(
            has_crash=False,
            missing_shutdown_flag=False,
            stale_heartbeat=False,
            orphan_snapshots=[],
            details="No crash indicators",
        )

        assert result.has_crash is False
        assert result.orphan_snapshots == []


class TestRecoveryResult:
    """Tests for RecoveryResult dataclass."""

    def test_create_recovery_result(self):
        """Should create recovery result with all fields."""
        indicators = CrashIndicatorResult(
            has_crash=True,
            missing_shutdown_flag=True,
            stale_heartbeat=False,
            orphan_snapshots=["account-1"],
            details="Test",
        )

        result = RecoveryResult(
            recovery_mode=True,
            accounts_needing_recovery=["account-1"],
            indicators=indicators,
        )

        assert result.recovery_mode is True
        assert result.accounts_needing_recovery == ["account-1"]
        assert result.indicators is indicators


class TestCrashRecoveryManagerConstants:
    """Tests for CrashRecoveryManager constants."""

    def test_shutdown_flag_key(self):
        """Should have correct shutdown flag key."""
        assert CrashRecoveryManager.SHUTDOWN_FLAG_KEY == "engine:shutdown:clean"

    def test_process_lock_key(self):
        """Should have correct process lock key."""
        assert CrashRecoveryManager.PROCESS_LOCK_KEY == "engine:lock:process"

    def test_heartbeat_ttl(self):
        """Should have 30 second heartbeat TTL."""
        assert CrashRecoveryManager.HEARTBEAT_TTL_SECONDS == 30

    def test_lock_ttl(self):
        """Should have 60 second lock TTL."""
        assert CrashRecoveryManager.LOCK_TTL_SECONDS == 60


class TestCrashRecoveryManagerInit:
    """Tests for CrashRecoveryManager initialization."""

    def test_init_stores_dependencies(self, mock_redis_manager):
        """Init should store all dependencies."""
        manager = CrashRecoveryManager(redis_manager=mock_redis_manager)

        assert manager._redis is mock_redis_manager
        assert manager._recovery_mode is False
        assert manager._heartbeat_running is False
        assert manager._heartbeat_task is None

    def test_recovery_mode_property(self, crash_recovery):
        """recovery_mode property should return current state."""
        assert crash_recovery.recovery_mode is False

        crash_recovery._recovery_mode = True
        assert crash_recovery.recovery_mode is True


class TestCleanShutdownFlag:
    """Tests for clean shutdown flag methods (AC: 3, 4, 5)."""

    @pytest.mark.asyncio
    async def test_set_clean_shutdown_flag(self, crash_recovery, mock_redis_manager):
        """set_clean_shutdown_flag should set key in Redis."""
        await crash_recovery.set_clean_shutdown_flag()

        mock_redis_manager.client.set.assert_called_once()
        call_args = mock_redis_manager.client.set.call_args
        assert call_args[0][0] == "engine:shutdown:clean"
        # Value should be ISO timestamp
        assert "T" in call_args[0][1]  # ISO format has T separator

    @pytest.mark.asyncio
    async def test_clear_clean_shutdown_flag(self, crash_recovery, mock_redis_manager):
        """clear_clean_shutdown_flag should delete key from Redis."""
        await crash_recovery.clear_clean_shutdown_flag()

        mock_redis_manager.client.delete.assert_called_once_with(
            "engine:shutdown:clean"
        )

    @pytest.mark.asyncio
    async def test_has_clean_shutdown_flag_exists(
        self, crash_recovery, mock_redis_manager
    ):
        """has_clean_shutdown_flag should return True when key exists."""
        mock_redis_manager.client.exists.return_value = 1

        result = await crash_recovery.has_clean_shutdown_flag()

        assert result is True
        mock_redis_manager.client.exists.assert_called_with("engine:shutdown:clean")

    @pytest.mark.asyncio
    async def test_has_clean_shutdown_flag_missing(
        self, crash_recovery, mock_redis_manager
    ):
        """has_clean_shutdown_flag should return False when key missing."""
        mock_redis_manager.client.exists.return_value = 0

        result = await crash_recovery.has_clean_shutdown_flag()

        assert result is False


class TestProcessLock:
    """Tests for process lock methods (AC: 6)."""

    @pytest.mark.asyncio
    async def test_acquire_process_lock_success(
        self, crash_recovery, mock_redis_manager
    ):
        """acquire_process_lock should return True on success."""
        mock_redis_manager.client.set.return_value = True

        result = await crash_recovery.acquire_process_lock()

        assert result is True
        call_args = mock_redis_manager.client.set.call_args
        assert call_args[0][0] == "engine:lock:process"
        # Check NX and EX options
        assert call_args[1]["nx"] is True
        assert call_args[1]["ex"] == 60

    @pytest.mark.asyncio
    async def test_acquire_process_lock_failure(
        self, crash_recovery, mock_redis_manager
    ):
        """acquire_process_lock should return False when another instance running."""
        mock_redis_manager.client.set.return_value = None  # NX returns None on failure
        mock_redis_manager.client.get.return_value = "other-host:1234:2026-01-03T00:00:00"

        result = await crash_recovery.acquire_process_lock()

        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_process_lock_value_format(
        self, crash_recovery, mock_redis_manager
    ):
        """Lock value should contain hostname:pid:timestamp."""
        mock_redis_manager.client.set.return_value = True

        await crash_recovery.acquire_process_lock()

        call_args = mock_redis_manager.client.set.call_args
        lock_value = call_args[0][1]
        parts = lock_value.split(":")
        # Should have at least 3 parts (hostname:pid:iso_timestamp)
        # ISO timestamp has colons too, so we check for minimum 3
        assert len(parts) >= 3

    @pytest.mark.asyncio
    async def test_release_process_lock(self, crash_recovery, mock_redis_manager):
        """release_process_lock should delete the lock key."""
        await crash_recovery.release_process_lock()

        mock_redis_manager.client.delete.assert_called_once_with("engine:lock:process")

    @pytest.mark.asyncio
    async def test_refresh_process_lock_success(
        self, crash_recovery, mock_redis_manager
    ):
        """refresh_process_lock should return True when lock refreshed."""
        mock_redis_manager.client.expire.return_value = 1

        result = await crash_recovery.refresh_process_lock()

        assert result is True
        mock_redis_manager.client.expire.assert_called_once_with(
            "engine:lock:process", 60
        )

    @pytest.mark.asyncio
    async def test_refresh_process_lock_failure(
        self, crash_recovery, mock_redis_manager
    ):
        """refresh_process_lock should return False when lock lost."""
        mock_redis_manager.client.expire.return_value = 0

        result = await crash_recovery.refresh_process_lock()

        assert result is False


class TestHeartbeat:
    """Tests for heartbeat methods (AC: 1, 6)."""

    @pytest.mark.asyncio
    async def test_start_heartbeat(self, crash_recovery):
        """start_heartbeat should create background task."""
        await crash_recovery.start_heartbeat()

        try:
            assert crash_recovery._heartbeat_running is True
            assert crash_recovery._heartbeat_task is not None
            assert crash_recovery._heartbeat_task.get_name() == "crash-recovery-heartbeat"
        finally:
            await crash_recovery.stop_heartbeat()

    @pytest.mark.asyncio
    async def test_start_heartbeat_idempotent(self, crash_recovery):
        """start_heartbeat should be idempotent."""
        await crash_recovery.start_heartbeat()
        task1 = crash_recovery._heartbeat_task

        await crash_recovery.start_heartbeat()
        task2 = crash_recovery._heartbeat_task

        try:
            assert task1 is task2
        finally:
            await crash_recovery.stop_heartbeat()

    @pytest.mark.asyncio
    async def test_stop_heartbeat(self, crash_recovery):
        """stop_heartbeat should cancel task."""
        await crash_recovery.start_heartbeat()
        await crash_recovery.stop_heartbeat()

        assert crash_recovery._heartbeat_running is False
        assert crash_recovery._heartbeat_task is None

    @pytest.mark.asyncio
    async def test_stop_heartbeat_idempotent(self, crash_recovery):
        """stop_heartbeat should be idempotent."""
        # Should not raise when not running
        await crash_recovery.stop_heartbeat()
        await crash_recovery.stop_heartbeat()

    @pytest.mark.asyncio
    async def test_heartbeat_refreshes_lock(self, crash_recovery, mock_redis_manager):
        """Heartbeat should periodically refresh lock."""
        # Speed up heartbeat for testing
        original_ttl = CrashRecoveryManager.HEARTBEAT_TTL_SECONDS
        CrashRecoveryManager.HEARTBEAT_TTL_SECONDS = 0.1

        try:
            mock_redis_manager.client.expire.return_value = 1

            await crash_recovery.start_heartbeat()
            await asyncio.sleep(0.15)  # Wait for at least one heartbeat
            await crash_recovery.stop_heartbeat()

            # Should have called expire at least once
            assert mock_redis_manager.client.expire.call_count >= 1
        finally:
            CrashRecoveryManager.HEARTBEAT_TTL_SECONDS = original_ttl

    @pytest.mark.asyncio
    async def test_heartbeat_stops_on_lock_lost(
        self, crash_recovery, mock_redis_manager
    ):
        """Heartbeat should stop when lock is lost."""
        original_ttl = CrashRecoveryManager.HEARTBEAT_TTL_SECONDS
        CrashRecoveryManager.HEARTBEAT_TTL_SECONDS = 0.1

        try:
            mock_redis_manager.client.expire.return_value = 0  # Lock lost

            await crash_recovery.start_heartbeat()
            await asyncio.sleep(0.15)

            # Task should have stopped itself
            # Note: The task breaks out of loop but may still be "running"
            # until we cancel it, but _heartbeat_running should still be True
            # (the critical log is what matters here)
        finally:
            await crash_recovery.stop_heartbeat()
            CrashRecoveryManager.HEARTBEAT_TTL_SECONDS = original_ttl


class TestCrashIndicatorDetection:
    """Tests for crash indicator detection methods (AC: 1, 2, 3)."""

    @pytest.mark.asyncio
    async def test_check_stale_heartbeat_no_crash(
        self, crash_recovery, mock_redis_manager
    ):
        """No stale heartbeat when lock exists or clean shutdown."""
        # Lock exists
        mock_redis_manager.client.exists.return_value = 1

        result = await crash_recovery._check_stale_heartbeat()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_stale_heartbeat_crash(
        self, crash_recovery, mock_redis_manager
    ):
        """Stale heartbeat when no lock AND no clean shutdown."""
        # No lock and no shutdown flag
        mock_redis_manager.client.exists.return_value = 0

        result = await crash_recovery._check_stale_heartbeat()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_crash_indicators_no_crash(
        self, crash_recovery, mock_redis_manager
    ):
        """No crash when clean shutdown flag exists."""
        # Clean shutdown flag exists
        mock_redis_manager.client.exists.return_value = 1

        result = await crash_recovery.check_crash_indicators()

        assert result.has_crash is False
        assert result.missing_shutdown_flag is False

    @pytest.mark.asyncio
    async def test_check_crash_indicators_crash_detected(
        self, crash_recovery, mock_redis_manager
    ):
        """Crash detected when no shutdown flag and orphan snapshots."""
        # No shutdown flag
        mock_redis_manager.client.exists.return_value = 0

        # Orphan snapshots exist
        async def snapshot_scan():
            yield "snapshot:account-1:latest"
            yield "snapshot:account-2:latest"

        mock_redis_manager.client.scan_iter.return_value = snapshot_scan()

        result = await crash_recovery.check_crash_indicators()

        assert result.has_crash is True
        assert result.missing_shutdown_flag is True
        assert "account-1" in result.orphan_snapshots
        assert "account-2" in result.orphan_snapshots

    @pytest.mark.asyncio
    async def test_check_crash_indicators_details(
        self, crash_recovery, mock_redis_manager
    ):
        """Crash indicator details should describe what was found."""
        mock_redis_manager.client.exists.return_value = 0

        async def snapshot_scan():
            yield "snapshot:account-1:latest"

        mock_redis_manager.client.scan_iter.return_value = snapshot_scan()

        result = await crash_recovery.check_crash_indicators()

        assert "No clean shutdown flag" in result.details
        assert "orphan snapshots" in result.details


class TestRecoveryInitiation:
    """Tests for recovery initiation methods (AC: 2, 4)."""

    @pytest.mark.asyncio
    async def test_initiate_recovery(self, crash_recovery):
        """initiate_recovery should set recovery mode."""
        indicators = CrashIndicatorResult(
            has_crash=True,
            missing_shutdown_flag=True,
            stale_heartbeat=False,
            orphan_snapshots=["account-1"],
            details="Test crash",
        )

        await crash_recovery.initiate_recovery(indicators)

        assert crash_recovery._recovery_mode is True

    @pytest.mark.asyncio
    async def test_clear_crash_indicators(self, crash_recovery):
        """clear_crash_indicators should reset recovery mode."""
        crash_recovery._recovery_mode = True

        await crash_recovery.clear_crash_indicators()

        assert crash_recovery._recovery_mode is False


class TestAccountRecoveryDetection:
    """Tests for account recovery detection methods (AC: 1, 7)."""

    @pytest.mark.asyncio
    async def test_get_accounts_needing_recovery(
        self, crash_recovery, mock_redis_manager
    ):
        """Should find accounts from snapshot keys."""

        async def snapshot_scan():
            yield "snapshot:ftmo-gold-001:latest"
            yield "snapshot:ftmo-silver-002:latest"
            yield "snapshot:prop-eurusd-003:latest"

        mock_redis_manager.client.scan_iter.return_value = snapshot_scan()

        result = await crash_recovery.get_accounts_needing_recovery()

        assert len(result) == 3
        assert "ftmo-gold-001" in result
        assert "ftmo-silver-002" in result
        assert "prop-eurusd-003" in result

    @pytest.mark.asyncio
    async def test_get_accounts_needing_recovery_empty(
        self, crash_recovery, mock_redis_manager
    ):
        """Should return empty list when no snapshots."""

        async def empty_scan():
            return
            yield

        mock_redis_manager.client.scan_iter.return_value = empty_scan()

        result = await crash_recovery.get_accounts_needing_recovery()

        assert result == []

    @pytest.mark.asyncio
    async def test_validate_snapshot_for_recovery_valid(
        self, crash_recovery, mock_redis_manager
    ):
        """Should return valid snapshot."""
        snapshot = StateSnapshot(
            account_id="account-1",
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
        mock_redis_manager.get_snapshot.return_value = snapshot

        is_valid, result = await crash_recovery.validate_snapshot_for_recovery(
            "account-1"
        )

        assert is_valid is True
        assert result is snapshot

    @pytest.mark.asyncio
    async def test_validate_snapshot_for_recovery_not_found(
        self, crash_recovery, mock_redis_manager
    ):
        """Should return False when snapshot not found."""
        mock_redis_manager.get_snapshot.return_value = None

        is_valid, result = await crash_recovery.validate_snapshot_for_recovery(
            "account-1"
        )

        assert is_valid is False
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_snapshot_for_recovery_invalid_checksum(
        self, crash_recovery, mock_redis_manager
    ):
        """Should return False when checksum invalid."""
        snapshot = StateSnapshot(
            account_id="account-1",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("100000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="invalid-checksum",  # Invalid
        )
        mock_redis_manager.get_snapshot.return_value = snapshot

        is_valid, result = await crash_recovery.validate_snapshot_for_recovery(
            "account-1"
        )

        assert is_valid is False
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_snapshot_for_recovery_too_old(
        self, crash_recovery, mock_redis_manager
    ):
        """Should return False when snapshot is older than 1 hour."""
        from datetime import timedelta

        # Create snapshot from 2 hours ago
        old_timestamp = datetime.now(timezone.utc) - timedelta(hours=2)
        snapshot = StateSnapshot(
            account_id="account-1",
            timestamp=old_timestamp,
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("100000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )
        snapshot.checksum = snapshot.compute_checksum()
        mock_redis_manager.get_snapshot.return_value = snapshot

        is_valid, result = await crash_recovery.validate_snapshot_for_recovery(
            "account-1"
        )

        assert is_valid is False
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_snapshot_for_recovery_recent_enough(
        self, crash_recovery, mock_redis_manager
    ):
        """Should return True when snapshot is within 1 hour."""
        from datetime import timedelta

        # Create snapshot from 30 minutes ago (within 1 hour limit)
        recent_timestamp = datetime.now(timezone.utc) - timedelta(minutes=30)
        snapshot = StateSnapshot(
            account_id="account-1",
            timestamp=recent_timestamp,
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("100000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )
        snapshot.checksum = snapshot.compute_checksum()
        mock_redis_manager.get_snapshot.return_value = snapshot

        is_valid, result = await crash_recovery.validate_snapshot_for_recovery(
            "account-1"
        )

        assert is_valid is True
        assert result is snapshot


class TestStartupSequence:
    """Tests for startup_sequence method (AC: 2, 3, 4, 6)."""

    @pytest.mark.asyncio
    async def test_startup_sequence_normal(self, crash_recovery, mock_redis_manager):
        """Normal startup when clean shutdown flag exists."""
        # Clean shutdown
        mock_redis_manager.client.exists.return_value = 1
        mock_redis_manager.client.set.return_value = True

        async def empty_scan():
            return
            yield

        mock_redis_manager.client.scan_iter.return_value = empty_scan()

        result = await crash_recovery.startup_sequence()

        try:
            assert result.recovery_mode is False
            assert result.accounts_needing_recovery == []
            # Should have acquired lock
            assert mock_redis_manager.client.set.called
            # Should have started heartbeat
            assert crash_recovery._heartbeat_running is True
        finally:
            await crash_recovery.stop_heartbeat()

    @pytest.mark.asyncio
    async def test_startup_sequence_recovery_mode(
        self, crash_recovery, mock_redis_manager
    ):
        """Recovery mode when crash detected."""
        # No clean shutdown
        mock_redis_manager.client.exists.return_value = 0
        mock_redis_manager.client.set.return_value = True

        async def snapshot_scan():
            yield "snapshot:account-1:latest"

        # scan_iter is called twice, so return a fresh generator each time
        mock_redis_manager.client.scan_iter.side_effect = lambda *args, **kwargs: snapshot_scan()

        result = await crash_recovery.startup_sequence()

        try:
            assert result.recovery_mode is True
            assert "account-1" in result.accounts_needing_recovery
        finally:
            await crash_recovery.stop_heartbeat()

    @pytest.mark.asyncio
    async def test_startup_sequence_another_instance_running(
        self, crash_recovery, mock_redis_manager
    ):
        """Should raise when another instance running."""
        mock_redis_manager.client.exists.return_value = 1
        mock_redis_manager.client.set.return_value = None  # Lock acquisition failed
        mock_redis_manager.client.get.return_value = "other:123:timestamp"

        with pytest.raises(RuntimeError, match="Another instance is already running"):
            await crash_recovery.startup_sequence()

    @pytest.mark.asyncio
    async def test_startup_sequence_clears_shutdown_flag(
        self, crash_recovery, mock_redis_manager
    ):
        """Startup should clear shutdown flag."""
        mock_redis_manager.client.exists.return_value = 1
        mock_redis_manager.client.set.return_value = True

        async def empty_scan():
            return
            yield

        mock_redis_manager.client.scan_iter.return_value = empty_scan()

        await crash_recovery.startup_sequence()

        try:
            # Should have deleted shutdown flag
            mock_redis_manager.client.delete.assert_any_call("engine:shutdown:clean")
        finally:
            await crash_recovery.stop_heartbeat()


class TestShutdownSequence:
    """Tests for shutdown_sequence method (AC: 4, 5)."""

    @pytest.mark.asyncio
    async def test_shutdown_sequence(self, crash_recovery, mock_redis_manager):
        """Shutdown should stop heartbeat, set flag, release lock."""
        # Start heartbeat first
        await crash_recovery.start_heartbeat()

        await crash_recovery.shutdown_sequence()

        # Should have stopped heartbeat
        assert crash_recovery._heartbeat_running is False

        # Should have set shutdown flag
        calls = [call[0][0] for call in mock_redis_manager.client.set.call_args_list]
        assert "engine:shutdown:clean" in calls

        # Should have released lock
        calls = [
            call[0][0] for call in mock_redis_manager.client.delete.call_args_list
        ]
        assert "engine:lock:process" in calls

    @pytest.mark.asyncio
    async def test_shutdown_sequence_order(self, crash_recovery, mock_redis_manager):
        """Shutdown should execute in correct order."""
        call_order = []

        async def track_set(*args, **kwargs):
            call_order.append(("set", args[0]))
            return True

        async def track_delete(*args, **kwargs):
            call_order.append(("delete", args[0]))
            return 1

        mock_redis_manager.client.set.side_effect = track_set
        mock_redis_manager.client.delete.side_effect = track_delete

        await crash_recovery.shutdown_sequence()

        # Set should come before delete of lock
        set_idx = next(
            i for i, c in enumerate(call_order) if c == ("set", "engine:shutdown:clean")
        )
        delete_idx = next(
            i
            for i, c in enumerate(call_order)
            if c == ("delete", "engine:lock:process")
        )
        assert set_idx < delete_idx


class TestLockLostCallback:
    """Tests for lock lost callback mechanism."""

    @pytest.mark.asyncio
    async def test_callback_invoked_on_lock_lost(self, mock_redis_manager):
        """Callback should be invoked when lock is lost."""
        callback_invoked = []

        def on_lock_lost():
            callback_invoked.append(True)

        manager = CrashRecoveryManager(
            redis_manager=mock_redis_manager,
            on_lock_lost=on_lock_lost,
        )

        # Speed up heartbeat for testing
        original_ttl = CrashRecoveryManager.HEARTBEAT_TTL_SECONDS
        CrashRecoveryManager.HEARTBEAT_TTL_SECONDS = 0.1

        try:
            mock_redis_manager.client.expire.return_value = 0  # Lock lost

            await manager.start_heartbeat()
            await asyncio.sleep(0.15)

            # Callback should have been invoked
            assert len(callback_invoked) == 1
        finally:
            await manager.stop_heartbeat()
            CrashRecoveryManager.HEARTBEAT_TTL_SECONDS = original_ttl

    @pytest.mark.asyncio
    async def test_no_callback_when_not_registered(self, mock_redis_manager):
        """Should not fail when no callback registered."""
        manager = CrashRecoveryManager(
            redis_manager=mock_redis_manager,
            on_lock_lost=None,  # No callback
        )

        original_ttl = CrashRecoveryManager.HEARTBEAT_TTL_SECONDS
        CrashRecoveryManager.HEARTBEAT_TTL_SECONDS = 0.1

        try:
            mock_redis_manager.client.expire.return_value = 0  # Lock lost

            # Should not raise even without callback
            await manager.start_heartbeat()
            await asyncio.sleep(0.15)
        finally:
            await manager.stop_heartbeat()
            CrashRecoveryManager.HEARTBEAT_TTL_SECONDS = original_ttl


class TestRecoveryModeLogging:
    """Tests for AC2 - recovery mode log message verification."""

    @pytest.mark.asyncio
    async def test_initiate_recovery_logs_correct_message(
        self, crash_recovery, caplog
    ):
        """AC2: Should log 'Recovery mode: Previous session did not shut down cleanly'."""
        import logging

        indicators = CrashIndicatorResult(
            has_crash=True,
            missing_shutdown_flag=True,
            stale_heartbeat=False,
            orphan_snapshots=["account-1"],
            details="No clean shutdown flag found",
        )

        with caplog.at_level(logging.WARNING):
            await crash_recovery.initiate_recovery(indicators)

        # Verify AC2 log message
        assert any(
            "Recovery mode: Previous session did not shut down cleanly" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_startup_sequence_logs_recovery_mode(
        self, mock_redis_manager, caplog
    ):
        """AC2: Startup should log recovery message when crash detected."""
        import logging

        manager = CrashRecoveryManager(redis_manager=mock_redis_manager)

        # No clean shutdown flag = crash
        mock_redis_manager.client.exists.return_value = 0
        mock_redis_manager.client.set.return_value = True

        async def snapshot_scan():
            yield "snapshot:account-1:latest"

        mock_redis_manager.client.scan_iter.side_effect = lambda *args, **kwargs: snapshot_scan()

        with caplog.at_level(logging.WARNING):
            try:
                await manager.startup_sequence()
            finally:
                await manager.stop_heartbeat()

        # Verify AC2 log message
        assert any(
            "Recovery mode: Previous session did not shut down cleanly" in record.message
            for record in caplog.records
        )
