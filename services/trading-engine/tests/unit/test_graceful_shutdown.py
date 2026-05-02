"""Unit tests for GracefulShutdown.

Tests cover:
- Shutdown sequence phases execute in order
- Signal handler registration and triggering
- Pending order wait with timeout
- Final snapshot is persisted
- Clean shutdown flag is set
- Connections are closed in order
- Duplicate shutdown is prevented
- Shutdown result metrics are accurate
- Exit codes for success and failure
- Error handling for each phase
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.state.graceful_shutdown import (
    GracefulShutdown,
    ShutdownPhase,
    ShutdownResult,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_redis_manager() -> MagicMock:
    """Create a mock RedisStateManager."""
    manager = MagicMock()
    manager.close = AsyncMock()
    return manager


@pytest.fixture
def mock_account_manager() -> MagicMock:
    """Create a mock AccountManager."""
    manager = MagicMock()
    manager.shutdown = AsyncMock()
    manager.get_all_accounts = MagicMock(return_value=["ftmo-001", "ftmo-002"])
    manager.get_account_status = AsyncMock(return_value="active")
    return manager


@pytest.fixture
def mock_snapshot_service() -> MagicMock:
    """Create a mock SnapshotService."""
    service = MagicMock()
    service.stop = AsyncMock()
    return service


@pytest.fixture
def mock_zmq_adapter() -> MagicMock:
    """Create a mock ZmqAdapter."""
    adapter = MagicMock()
    adapter.get_pending_order_count = MagicMock(return_value=0)
    adapter.close = AsyncMock()
    return adapter


@pytest.fixture
def mock_crash_recovery() -> MagicMock:
    """Create a mock CrashRecoveryManager."""
    manager = MagicMock()
    manager.shutdown_sequence = AsyncMock()
    return manager


@pytest.fixture
def graceful_shutdown(
    mock_redis_manager: MagicMock,
    mock_account_manager: MagicMock,
    mock_snapshot_service: MagicMock,
    mock_zmq_adapter: MagicMock,
    mock_crash_recovery: MagicMock,
) -> GracefulShutdown:
    """Create a GracefulShutdown with mocked dependencies."""
    return GracefulShutdown(
        redis_manager=mock_redis_manager,
        account_manager=mock_account_manager,
        snapshot_service=mock_snapshot_service,
        zmq_adapter=mock_zmq_adapter,
        crash_recovery=mock_crash_recovery,
    )


# ============================================================================
# Task 10.1: Test file creation and imports
# ============================================================================


def test_graceful_shutdown_imports() -> None:
    """Verify GracefulShutdown can be imported."""
    from src.state.graceful_shutdown import (
        GracefulShutdown,
        ShutdownPhase,
        ShutdownResult,
    )

    assert GracefulShutdown is not None
    assert ShutdownPhase is not None
    assert ShutdownResult is not None


def test_shutdown_phase_enum() -> None:
    """Verify ShutdownPhase enum values."""
    assert ShutdownPhase.NOT_STARTED is not None
    assert ShutdownPhase.STOPPING_SIGNALS is not None
    assert ShutdownPhase.WAITING_ORDERS is not None
    assert ShutdownPhase.PERSISTING_STATE is not None
    assert ShutdownPhase.CLOSING_CONNECTIONS is not None
    assert ShutdownPhase.COMPLETE is not None


def test_shutdown_result_dataclass() -> None:
    """Verify ShutdownResult can be instantiated."""
    result = ShutdownResult(
        success=True,
        phase_reached=ShutdownPhase.COMPLETE,
        pending_orders_at_timeout=0,
        accounts_snapshot_count=2,
        duration_seconds=1.5,
        exit_code=0,
    )
    assert result.success is True
    assert result.exit_code == 0


# ============================================================================
# Task 10.2: Test shutdown sequence phases execute in order
# ============================================================================


@pytest.mark.asyncio
async def test_shutdown_phases_execute_in_order(
    graceful_shutdown: GracefulShutdown,
    mock_account_manager: MagicMock,
    mock_snapshot_service: MagicMock,
    mock_crash_recovery: MagicMock,
    mock_zmq_adapter: MagicMock,
    mock_redis_manager: MagicMock,
) -> None:
    """Shutdown phases should execute in correct order."""
    call_order = []

    async def track_account_shutdown() -> None:
        call_order.append("account_manager")

    async def track_snapshot_stop() -> None:
        call_order.append("snapshot_service")

    async def track_crash_shutdown() -> None:
        call_order.append("crash_recovery")

    async def track_zmq_close() -> None:
        call_order.append("zmq_close")

    async def track_redis_close() -> None:
        call_order.append("redis_close")

    mock_account_manager.shutdown = AsyncMock(side_effect=track_account_shutdown)
    mock_snapshot_service.stop = AsyncMock(side_effect=track_snapshot_stop)
    mock_crash_recovery.shutdown_sequence = AsyncMock(side_effect=track_crash_shutdown)
    mock_zmq_adapter.close = AsyncMock(side_effect=track_zmq_close)
    mock_redis_manager.close = AsyncMock(side_effect=track_redis_close)

    # Act
    result = await graceful_shutdown.initiate()

    # Assert
    assert result.success is True
    assert call_order == [
        "account_manager",
        "snapshot_service",
        "crash_recovery",
        "zmq_close",
        "redis_close",
    ]


# ============================================================================
# Task 10.3: Test signal handler registration and triggering
# ============================================================================


@pytest.mark.asyncio
async def test_signal_handler_registration(
    graceful_shutdown: GracefulShutdown,
) -> None:
    """Signal handlers should be registered for SIGTERM and SIGINT."""
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop

        graceful_shutdown.register_signal_handlers()

        # Verify add_signal_handler was called for both signals
        assert mock_loop.add_signal_handler.call_count == 2


@pytest.mark.asyncio
async def test_signal_handler_triggers_shutdown(
    graceful_shutdown: GracefulShutdown,
) -> None:
    """Signal handler should set the shutdown event."""
    import signal

    graceful_shutdown._handle_signal(signal.SIGTERM)

    assert graceful_shutdown._shutdown_event.is_set() is True


@pytest.mark.asyncio
async def test_signal_handlers_unregistered_during_shutdown(
    graceful_shutdown: GracefulShutdown,
) -> None:
    """Signal handlers should be unregistered during shutdown."""
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop

        graceful_shutdown.unregister_signal_handlers()

        # Verify remove_signal_handler was called for both signals
        assert mock_loop.remove_signal_handler.call_count == 2


# ============================================================================
# Task 10.4: Test pending order wait with timeout
# ============================================================================


@pytest.mark.asyncio
async def test_pending_order_wait_no_orders(
    graceful_shutdown: GracefulShutdown,
    mock_zmq_adapter: MagicMock,
) -> None:
    """Should skip wait if no pending orders."""
    mock_zmq_adapter.get_pending_order_count.return_value = 0

    remaining = await graceful_shutdown._wait_for_pending_orders()

    assert remaining == 0


@pytest.mark.asyncio
async def test_pending_order_wait_orders_complete(
    graceful_shutdown: GracefulShutdown,
    mock_zmq_adapter: MagicMock,
) -> None:
    """Should wait until orders complete."""
    # Start with 2 pending, then 1, then 0
    call_count = 0

    def decreasing_orders() -> int:
        nonlocal call_count
        call_count += 1
        return max(0, 2 - call_count)

    mock_zmq_adapter.get_pending_order_count = MagicMock(side_effect=decreasing_orders)

    remaining = await graceful_shutdown._wait_for_pending_orders()

    assert remaining == 0


# ============================================================================
# Task 10.5: Test pending order completion before timeout
# ============================================================================


@pytest.mark.asyncio
async def test_pending_order_wait_timeout(
    graceful_shutdown: GracefulShutdown,
    mock_zmq_adapter: MagicMock,
) -> None:
    """Should return remaining orders after timeout."""
    # Override timeout for testing
    graceful_shutdown.PENDING_ORDER_TIMEOUT_SECONDS = 0.1

    # Always return 3 pending orders
    mock_zmq_adapter.get_pending_order_count.return_value = 3

    remaining = await graceful_shutdown._wait_for_pending_orders()

    assert remaining == 3


@pytest.mark.asyncio
async def test_pending_order_wait_timeout_logs_warning(
    graceful_shutdown: GracefulShutdown,
    mock_zmq_adapter: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC3: Should log WARNING when pending orders remain after timeout."""
    import logging

    # Override timeout for testing
    graceful_shutdown.PENDING_ORDER_TIMEOUT_SECONDS = 0.1

    # Always return 3 pending orders
    mock_zmq_adapter.get_pending_order_count.return_value = 3

    with caplog.at_level(logging.WARNING):
        remaining = await graceful_shutdown._wait_for_pending_orders()

    assert remaining == 3
    # Verify WARNING was logged about pending orders
    warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_logs) >= 1
    assert "orders still pending" in warning_logs[0].message


# ============================================================================
# Task 10.6: Test final snapshot is persisted
# ============================================================================


@pytest.mark.asyncio
async def test_final_snapshot_persisted(
    graceful_shutdown: GracefulShutdown,
    mock_snapshot_service: MagicMock,
) -> None:
    """SnapshotService.stop() should be called for final snapshot."""
    result = await graceful_shutdown.initiate()

    mock_snapshot_service.stop.assert_awaited_once()
    assert result.success is True


@pytest.mark.asyncio
async def test_no_snapshot_service_skips_snapshot(
    mock_redis_manager: MagicMock,
    mock_account_manager: MagicMock,
    mock_crash_recovery: MagicMock,
) -> None:
    """Should skip final snapshot if no snapshot service."""
    shutdown = GracefulShutdown(
        redis_manager=mock_redis_manager,
        account_manager=mock_account_manager,
        snapshot_service=None,  # No snapshot service
        crash_recovery=mock_crash_recovery,
    )

    result = await shutdown.initiate()

    assert result.success is True
    assert result.accounts_snapshot_count == 0


# ============================================================================
# Task 10.7: Test clean shutdown flag is set
# ============================================================================


@pytest.mark.asyncio
async def test_clean_shutdown_flag_set(
    graceful_shutdown: GracefulShutdown,
    mock_crash_recovery: MagicMock,
) -> None:
    """CrashRecoveryManager.shutdown_sequence() should be called."""
    result = await graceful_shutdown.initiate()

    mock_crash_recovery.shutdown_sequence.assert_awaited_once()
    assert result.success is True


# ============================================================================
# Task 10.8: Test connections are closed in order
# ============================================================================


@pytest.mark.asyncio
async def test_connections_closed_in_order(
    graceful_shutdown: GracefulShutdown,
    mock_zmq_adapter: MagicMock,
    mock_redis_manager: MagicMock,
) -> None:
    """ZMQ should close before Redis."""
    call_order = []

    async def track_zmq_close() -> None:
        call_order.append("zmq")

    async def track_redis_close() -> None:
        call_order.append("redis")

    mock_zmq_adapter.close = AsyncMock(side_effect=track_zmq_close)
    mock_redis_manager.close = AsyncMock(side_effect=track_redis_close)

    await graceful_shutdown.initiate()

    # ZMQ should close before Redis
    assert call_order.index("zmq") < call_order.index("redis")


# ============================================================================
# Task 10.9: Test duplicate shutdown is prevented
# ============================================================================


@pytest.mark.asyncio
async def test_duplicate_shutdown_prevented(
    graceful_shutdown: GracefulShutdown,
    mock_account_manager: MagicMock,
) -> None:
    """Second shutdown call should return immediately with failure."""
    # First shutdown
    result1 = await graceful_shutdown.initiate()
    assert result1.success is True

    # Second shutdown should be prevented
    result2 = await graceful_shutdown.initiate()
    assert result2.success is False
    assert result2.exit_code == 1

    # Account manager shutdown should only be called once
    assert mock_account_manager.shutdown.await_count == 1


# ============================================================================
# Task 10.10: Test shutdown result metrics are accurate
# ============================================================================


@pytest.mark.asyncio
async def test_shutdown_result_metrics(
    graceful_shutdown: GracefulShutdown,
    mock_account_manager: MagicMock,
) -> None:
    """ShutdownResult should contain accurate metrics."""
    mock_account_manager.get_all_accounts.return_value = ["acc-1", "acc-2", "acc-3"]
    mock_account_manager.get_account_status = AsyncMock(return_value="active")

    result = await graceful_shutdown.initiate()

    assert result.success is True
    assert result.phase_reached == ShutdownPhase.COMPLETE
    assert result.pending_orders_at_timeout == 0
    assert result.accounts_snapshot_count == 3
    assert result.duration_seconds >= 0
    assert result.exit_code == 0


# ============================================================================
# Task 10.11: Test exit code is 0 on success
# ============================================================================


@pytest.mark.asyncio
async def test_exit_code_zero_on_success(
    graceful_shutdown: GracefulShutdown,
) -> None:
    """Exit code should be 0 on successful shutdown."""
    result = await graceful_shutdown.initiate()

    assert result.success is True
    assert result.exit_code == 0


# ============================================================================
# Task 10.12: Test exit code is 1 on failure
# ============================================================================


@pytest.mark.asyncio
async def test_exit_code_one_on_fatal_error(
    graceful_shutdown: GracefulShutdown,
    mock_crash_recovery: MagicMock,
) -> None:
    """Exit code should be 1 on fatal unrecoverable error."""
    # Fatal error in crash recovery shutdown (not caught)
    mock_crash_recovery.shutdown_sequence = AsyncMock(
        side_effect=Exception("Fatal error")
    )

    result = await graceful_shutdown.initiate()

    assert result.success is False
    assert result.exit_code == 1
    assert result.phase_reached == ShutdownPhase.PERSISTING_STATE


# ============================================================================
# Task 10.13: Test shutdown continues when account_manager.shutdown() raises
# ============================================================================


@pytest.mark.asyncio
async def test_shutdown_continues_after_account_manager_error(
    graceful_shutdown: GracefulShutdown,
    mock_account_manager: MagicMock,
    mock_snapshot_service: MagicMock,
    mock_crash_recovery: MagicMock,
) -> None:
    """Shutdown should continue if account_manager.shutdown() fails."""
    mock_account_manager.shutdown = AsyncMock(side_effect=Exception("Account error"))

    result = await graceful_shutdown.initiate()

    # Snapshot and crash recovery should still be called
    mock_snapshot_service.stop.assert_awaited_once()
    mock_crash_recovery.shutdown_sequence.assert_awaited_once()
    # But result indicates failure since exception propagated
    # Actually, the exception is caught in _stop_signal_processing
    assert result.success is True  # Continues despite error


# ============================================================================
# Task 10.14: Test shutdown continues when snapshot_service.stop() raises
# ============================================================================


@pytest.mark.asyncio
async def test_shutdown_continues_after_snapshot_error(
    graceful_shutdown: GracefulShutdown,
    mock_snapshot_service: MagicMock,
    mock_crash_recovery: MagicMock,
    mock_redis_manager: MagicMock,
) -> None:
    """Shutdown should continue if snapshot_service.stop() fails."""
    mock_snapshot_service.stop = AsyncMock(side_effect=Exception("Snapshot error"))

    result = await graceful_shutdown.initiate()

    # Crash recovery and redis close should still be called
    mock_crash_recovery.shutdown_sequence.assert_awaited_once()
    mock_redis_manager.close.assert_awaited_once()
    assert result.accounts_snapshot_count == 0  # No snapshots due to error


# ============================================================================
# Task 10.15: Test shutdown continues when zmq.close() raises
# ============================================================================


@pytest.mark.asyncio
async def test_shutdown_continues_after_zmq_close_error(
    graceful_shutdown: GracefulShutdown,
    mock_zmq_adapter: MagicMock,
    mock_redis_manager: MagicMock,
) -> None:
    """Shutdown should continue if zmq.close() fails."""
    mock_zmq_adapter.close = AsyncMock(side_effect=Exception("ZMQ close error"))

    result = await graceful_shutdown.initiate()

    # Redis close should still be called
    mock_redis_manager.close.assert_awaited_once()
    assert result.success is True  # Still succeeds despite ZMQ error


# ============================================================================
# Task 10.16: Test shutdown continues when redis.close() raises
# ============================================================================


@pytest.mark.asyncio
async def test_shutdown_continues_after_redis_close_error(
    graceful_shutdown: GracefulShutdown,
    mock_redis_manager: MagicMock,
) -> None:
    """Shutdown should complete even if redis.close() fails."""
    mock_redis_manager.close = AsyncMock(side_effect=Exception("Redis close error"))

    result = await graceful_shutdown.initiate()

    # Should still complete
    assert result.phase_reached == ShutdownPhase.COMPLETE
    assert result.success is True


# ============================================================================
# Additional Tests
# ============================================================================


@pytest.mark.asyncio
async def test_wait_for_shutdown_signal(
    graceful_shutdown: GracefulShutdown,
) -> None:
    """wait_for_shutdown_signal should block until shutdown event."""
    # Set up a task that will trigger shutdown after a delay
    async def trigger_after_delay() -> None:
        await asyncio.sleep(0.1)
        graceful_shutdown.trigger_shutdown()

    trigger_task = asyncio.create_task(trigger_after_delay())

    # wait_for_shutdown_signal should return after trigger
    result = await graceful_shutdown.wait_for_shutdown_signal()

    await trigger_task
    assert result.success is True


@pytest.mark.asyncio
async def test_trigger_shutdown(
    graceful_shutdown: GracefulShutdown,
) -> None:
    """trigger_shutdown should set the shutdown event."""
    assert graceful_shutdown._shutdown_event.is_set() is False

    graceful_shutdown.trigger_shutdown()

    assert graceful_shutdown._shutdown_event.is_set() is True


@pytest.mark.asyncio
async def test_no_zmq_adapter_skips_pending_order_wait(
    mock_redis_manager: MagicMock,
    mock_account_manager: MagicMock,
    mock_crash_recovery: MagicMock,
) -> None:
    """Should skip pending order wait if no ZMQ adapter."""
    shutdown = GracefulShutdown(
        redis_manager=mock_redis_manager,
        account_manager=mock_account_manager,
        zmq_adapter=None,  # No ZMQ adapter
        crash_recovery=mock_crash_recovery,
    )

    result = await shutdown.initiate()

    assert result.success is True
    assert result.pending_orders_at_timeout == 0


@pytest.mark.asyncio
async def test_no_crash_recovery_skips_shutdown_sequence(
    mock_redis_manager: MagicMock,
    mock_account_manager: MagicMock,
) -> None:
    """Should skip crash recovery shutdown if not configured."""
    shutdown = GracefulShutdown(
        redis_manager=mock_redis_manager,
        account_manager=mock_account_manager,
        crash_recovery=None,  # No crash recovery
    )

    result = await shutdown.initiate()

    assert result.success is True


@pytest.mark.asyncio
async def test_get_active_account_count(
    graceful_shutdown: GracefulShutdown,
    mock_account_manager: MagicMock,
) -> None:
    """Should count only active and paused accounts."""
    mock_account_manager.get_all_accounts.return_value = ["a1", "a2", "a3", "a4"]

    status_map = {
        "a1": "active",
        "a2": "paused",
        "a3": "stopped",
        "a4": "error",
    }
    mock_account_manager.get_account_status = AsyncMock(
        side_effect=lambda acc: status_map[acc]
    )

    count = await graceful_shutdown._get_active_account_count()

    assert count == 2  # Only active and paused


@pytest.mark.asyncio
async def test_shutdown_phase_tracking(
    graceful_shutdown: GracefulShutdown,
) -> None:
    """Shutdown phase should be tracked through the sequence."""
    assert graceful_shutdown._current_phase == ShutdownPhase.NOT_STARTED

    await graceful_shutdown.initiate()

    assert graceful_shutdown._current_phase == ShutdownPhase.COMPLETE


@pytest.mark.asyncio
async def test_shutdown_duration_calculated(
    graceful_shutdown: GracefulShutdown,
) -> None:
    """Shutdown duration should be calculated."""
    result = await graceful_shutdown.initiate()

    assert result.duration_seconds >= 0
    assert isinstance(result.duration_seconds, float)
