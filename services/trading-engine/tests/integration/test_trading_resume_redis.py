"""Integration tests for TradingResumer with real Redis.

Tests cover:
- Full recovery flow with real Redis
- Account status persistence after resume
- Notification published to Redis pub/sub
- AccountManager task spawning after resume

Requires Redis running on localhost:6379 (or REDIS_URL env var).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.state.redis_state import RedisStateManager
from src.state.trading_resumer import (
    TradingResumer,
)


def redis_available() -> bool:
    """Check if Redis is available."""
    import socket

    try:
        sock = socket.create_connection(("localhost", 6379), timeout=1)
        sock.close()
        return True
    except (socket.error, socket.timeout):
        return False


# Skip all tests if Redis not available
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not redis_available(), reason="Redis not available"),
]


@pytest.fixture
async def redis_manager() -> RedisStateManager:
    """Create and connect a real RedisStateManager."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    manager = RedisStateManager(redis_url)
    await manager.connect()

    # Clean up test keys before test
    await manager.client.delete("account:test-001:status")
    await manager.client.delete("account:test-002:status")
    await manager.client.delete("account:test-003:status")

    yield manager

    # Clean up after test
    await manager.client.delete("account:test-001:status")
    await manager.client.delete("account:test-002:status")
    await manager.client.delete("account:test-003:status")
    await manager.close()


@pytest.fixture
def mock_account_manager() -> MagicMock:
    """Create a mock AccountManager."""
    manager = MagicMock()
    manager._spawn_account_task = AsyncMock()
    return manager


def make_reconciliation_result(
    account_id: str,
    success: bool = True,
    requires_manual_intervention: bool = False,
) -> MagicMock:
    """Create a mock ReconciliationResult."""
    result = MagicMock()
    result.account_id = account_id
    result.success = success
    result.requires_manual_intervention = requires_manual_intervention
    result.error_message = None
    return result


def make_recalculation_result(
    account_id: str,
    success: bool = True,
) -> MagicMock:
    """Create a mock RecalculationResult."""
    result = MagicMock()
    result.account_id = account_id
    result.success = success
    result.error_message = None
    return result


# ============================================================================
# Task 9.2: Test full recovery flow with real Redis
# ============================================================================


@pytest.mark.asyncio
async def test_full_recovery_flow_with_redis(
    redis_manager: RedisStateManager,
    mock_account_manager: MagicMock,
) -> None:
    """Test complete recovery flow with real Redis."""
    # Arrange - Set initial account states
    await redis_manager.save_account_status("test-001", "active")
    await redis_manager.save_account_status("test-002", "paused")
    await redis_manager.save_account_status("test-003", "active")

    resumer = TradingResumer(
        redis_manager=redis_manager,
        account_manager=mock_account_manager,
    )

    recon_results = {
        "test-001": make_reconciliation_result("test-001", success=True),
        "test-002": make_reconciliation_result("test-002", success=True),
        "test-003": make_reconciliation_result("test-003", success=True),
    }
    pnl_results = {
        "test-001": make_recalculation_result("test-001", success=True),
        "test-002": make_recalculation_result("test-002", success=True),
        "test-003": make_recalculation_result("test-003", success=True),
    }
    start_time = datetime.now(timezone.utc) - timedelta(seconds=2)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results=recon_results,
        pnl_results=pnl_results,
        recovery_start_time=start_time,
    )

    # Assert
    assert result.success is True
    assert result.accounts_resumed == 2  # test-001 and test-003
    assert result.accounts_skipped == 1  # test-002 (paused)
    assert result.accounts_blocked == 0

    # Verify spawn was called for active accounts only
    assert mock_account_manager._spawn_account_task.await_count == 2


# ============================================================================
# Task 9.3: Test account status persistence after resume
# ============================================================================


@pytest.mark.asyncio
async def test_account_status_persistence_after_resume(
    redis_manager: RedisStateManager,
    mock_account_manager: MagicMock,
) -> None:
    """Account status should be correctly persisted in Redis after resume."""
    # Arrange - Set initial status
    await redis_manager.save_account_status("test-001", "active")

    resumer = TradingResumer(
        redis_manager=redis_manager,
        account_manager=mock_account_manager,
    )

    recon_results = {
        "test-001": make_reconciliation_result(
            "test-001", success=False, requires_manual_intervention=True
        ),
    }
    pnl_results = {
        "test-001": make_recalculation_result("test-001", success=True),
    }
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results=recon_results,
        pnl_results=pnl_results,
        recovery_start_time=start_time,
    )

    # Assert - blocked accounts should have error status
    assert result.accounts_blocked == 1
    status = await redis_manager.get_account_status("test-001")
    assert status == "error"


@pytest.mark.asyncio
async def test_paused_account_status_preserved(
    redis_manager: RedisStateManager,
    mock_account_manager: MagicMock,
) -> None:
    """Paused account should keep its paused status."""
    # Arrange
    await redis_manager.save_account_status("test-001", "paused")

    resumer = TradingResumer(
        redis_manager=redis_manager,
        account_manager=mock_account_manager,
    )

    recon_results = {
        "test-001": make_reconciliation_result("test-001", success=True),
    }
    pnl_results = {
        "test-001": make_recalculation_result("test-001", success=True),
    }
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results=recon_results,
        pnl_results=pnl_results,
        recovery_start_time=start_time,
    )

    # Assert - paused status should be preserved
    assert result.accounts_skipped == 1
    status = await redis_manager.get_account_status("test-001")
    assert status == "paused"


# ============================================================================
# Task 9.4: Test notification published to Redis pub/sub
# ============================================================================


@pytest.mark.asyncio
async def test_notification_published_to_redis(
    redis_manager: RedisStateManager,
    mock_account_manager: MagicMock,
) -> None:
    """Recovery notification should be published to Redis pub/sub."""
    # Arrange
    await redis_manager.save_account_status("test-001", "active")

    resumer = TradingResumer(
        redis_manager=redis_manager,
        account_manager=mock_account_manager,
    )

    # Create a subscriber to receive the notification
    pubsub = redis_manager.client.pubsub()
    await pubsub.subscribe("alerts:system")

    recon_results = {
        "test-001": make_reconciliation_result("test-001", success=True),
    }
    pnl_results = {
        "test-001": make_recalculation_result("test-001", success=True),
    }
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results=recon_results,
        pnl_results=pnl_results,
        recovery_start_time=start_time,
    )

    # Give pub/sub a moment to deliver
    await asyncio.sleep(0.1)

    # Get messages
    messages = []
    while True:
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg is None:
            break
        messages.append(msg)

    # Clean up
    await pubsub.unsubscribe("alerts:system")
    await pubsub.close()

    # Assert
    assert result.notification_sent is True
    assert len(messages) >= 1

    # Parse the notification
    notification = json.loads(messages[0]["data"])
    assert notification["type"] == "recovery_complete"
    assert notification["accounts_resumed"] == 1
    assert "Recovery complete" in notification["message"]


# ============================================================================
# Task 9.5: Test AccountManager task spawning after resume
# ============================================================================


@pytest.mark.asyncio
async def test_account_manager_task_spawning(
    redis_manager: RedisStateManager,
    mock_account_manager: MagicMock,
) -> None:
    """AccountManager._spawn_account_task should be called for resumed accounts."""
    # Arrange
    await redis_manager.save_account_status("test-001", "active")
    await redis_manager.save_account_status("test-002", "active")

    resumer = TradingResumer(
        redis_manager=redis_manager,
        account_manager=mock_account_manager,
    )

    recon_results = {
        "test-001": make_reconciliation_result("test-001", success=True),
        "test-002": make_reconciliation_result("test-002", success=True),
    }
    pnl_results = {
        "test-001": make_recalculation_result("test-001", success=True),
        "test-002": make_recalculation_result("test-002", success=True),
    }
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results=recon_results,
        pnl_results=pnl_results,
        recovery_start_time=start_time,
    )

    # Assert
    assert result.accounts_resumed == 2
    assert mock_account_manager._spawn_account_task.await_count == 2

    # Verify correct accounts were spawned
    spawn_calls = mock_account_manager._spawn_account_task.await_args_list
    spawned_accounts = {call.args[0] for call in spawn_calls}
    assert spawned_accounts == {"test-001", "test-002"}


# ============================================================================
# Additional Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_recovery_with_missing_status(
    redis_manager: RedisStateManager,
    mock_account_manager: MagicMock,
) -> None:
    """Account with no status in Redis should default to stopped."""
    # Arrange - don't set any status for test-001
    resumer = TradingResumer(
        redis_manager=redis_manager,
        account_manager=mock_account_manager,
    )

    recon_results = {
        "test-001": make_reconciliation_result("test-001", success=True),
    }
    pnl_results = {
        "test-001": make_recalculation_result("test-001", success=True),
    }
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results=recon_results,
        pnl_results=pnl_results,
        recovery_start_time=start_time,
    )

    # Assert - should be skipped (defaults to stopped)
    assert result.accounts_resumed == 0
    assert result.accounts_skipped == 1
    mock_account_manager._spawn_account_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_duration_logged(
    redis_manager: RedisStateManager,
    mock_account_manager: MagicMock,
) -> None:
    """Recovery duration should be accurately calculated."""
    # Arrange
    await redis_manager.save_account_status("test-001", "active")

    resumer = TradingResumer(
        redis_manager=redis_manager,
        account_manager=mock_account_manager,
    )

    recon_results = {
        "test-001": make_reconciliation_result("test-001", success=True),
    }
    pnl_results = {
        "test-001": make_recalculation_result("test-001", success=True),
    }
    # Start time 5 seconds ago
    start_time = datetime.now(timezone.utc) - timedelta(seconds=5)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results=recon_results,
        pnl_results=pnl_results,
        recovery_start_time=start_time,
    )

    # Assert - duration should be at least 5 seconds
    assert result.recovery_duration.total_seconds() >= 5
