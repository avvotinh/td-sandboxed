"""Unit tests for TradingResumer.

Tests cover:
- Pre-crash status retrieval
- Resume eligibility determination
- Account resume execution
- Recovery notification
- Multi-account handling with mixed statuses
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.state.trading_resumer import (
    AccountResumeResult,
    ResumeResult,
    TradingResumer,
)

if TYPE_CHECKING:
    pass


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_redis_manager() -> MagicMock:
    """Create a mock RedisStateManager."""
    manager = MagicMock()
    manager.get_account_status = AsyncMock(return_value="active")
    manager.save_account_status = AsyncMock()
    manager.client = MagicMock()
    manager.client.publish = AsyncMock()
    return manager


@pytest.fixture
def mock_account_manager() -> MagicMock:
    """Create a mock AccountManager."""
    manager = MagicMock()
    manager._spawn_account_task = AsyncMock()
    return manager


@pytest.fixture
def resumer(
    mock_redis_manager: MagicMock, mock_account_manager: MagicMock
) -> TradingResumer:
    """Create a TradingResumer with mocked dependencies."""
    return TradingResumer(
        redis_manager=mock_redis_manager,
        account_manager=mock_account_manager,
    )


def make_reconciliation_result(
    account_id: str,
    success: bool = True,
    requires_manual_intervention: bool = False,
    error_message: str | None = None,
) -> MagicMock:
    """Create a mock ReconciliationResult."""
    result = MagicMock()
    result.account_id = account_id
    result.success = success
    result.requires_manual_intervention = requires_manual_intervention
    result.error_message = error_message
    return result


def make_recalculation_result(
    account_id: str,
    success: bool = True,
    error_message: str | None = None,
) -> MagicMock:
    """Create a mock RecalculationResult."""
    result = MagicMock()
    result.account_id = account_id
    result.success = success
    result.error_message = error_message
    return result


# ============================================================================
# Task 8.1: Test File Creation
# ============================================================================


def test_trading_resumer_imports() -> None:
    """Verify TradingResumer can be imported."""
    from src.state.trading_resumer import (
        TradingResumer,
    )

    assert TradingResumer is not None
    assert AccountResumeResult is not None
    assert ResumeResult is not None


# ============================================================================
# Task 8.2: Test account with "active" pre-crash status resumes
# ============================================================================


@pytest.mark.asyncio
async def test_active_account_resumes(resumer: TradingResumer) -> None:
    """Account with active status before crash should resume trading."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")
    recon_result = make_reconciliation_result("ftmo-001", success=True)
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc) - timedelta(seconds=5)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert
    assert result.success is True
    assert result.accounts_resumed == 1
    assert result.accounts_skipped == 0
    assert result.accounts_blocked == 0
    resumer._account_manager._spawn_account_task.assert_awaited_once_with("ftmo-001")


# ============================================================================
# Task 8.3: Test account with "paused" pre-crash status does NOT resume
# ============================================================================


@pytest.mark.asyncio
async def test_paused_account_does_not_resume(resumer: TradingResumer) -> None:
    """Account that was paused before crash should remain paused."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="paused")
    recon_result = make_reconciliation_result("ftmo-001", success=True)
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert
    assert result.accounts_resumed == 0
    assert result.accounts_skipped == 1
    assert result.accounts_blocked == 0
    resumer._account_manager._spawn_account_task.assert_not_awaited()

    # Verify account status was NOT changed
    resumer._redis.save_account_status.assert_not_called()


# ============================================================================
# Task 8.4: Test account with "stopped" pre-crash status does NOT resume
# ============================================================================


@pytest.mark.asyncio
async def test_stopped_account_does_not_resume(resumer: TradingResumer) -> None:
    """Account that was stopped before crash should remain stopped."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="stopped")
    recon_result = make_reconciliation_result("ftmo-001", success=True)
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert
    assert result.accounts_resumed == 0
    assert result.accounts_skipped == 1
    resumer._account_manager._spawn_account_task.assert_not_awaited()


# ============================================================================
# Task 8.5: Test account requiring manual intervention does NOT resume
# ============================================================================


@pytest.mark.asyncio
async def test_manual_intervention_blocks_resume(resumer: TradingResumer) -> None:
    """Account requiring manual intervention should be blocked."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")
    recon_result = make_reconciliation_result(
        "ftmo-001", success=False, requires_manual_intervention=True
    )
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert
    assert result.accounts_resumed == 0
    assert result.accounts_blocked == 1
    resumer._account_manager._spawn_account_task.assert_not_awaited()


# ============================================================================
# Task 8.6: Test account with failed reconciliation does NOT resume
# ============================================================================


@pytest.mark.asyncio
async def test_failed_reconciliation_blocks_resume(resumer: TradingResumer) -> None:
    """Account with failed reconciliation should be blocked (not just skipped)."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")
    recon_result = make_reconciliation_result(
        "ftmo-001", success=False, error_message="ZMQ timeout"
    )
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert - failed recon should BLOCK account and set status to error
    assert result.accounts_resumed == 0
    assert result.accounts_blocked == 1  # Failed recon blocks account
    assert result.accounts_skipped == 0
    resumer._account_manager._spawn_account_task.assert_not_awaited()
    # Verify Redis status set to error
    resumer._redis.save_account_status.assert_awaited_once_with("ftmo-001", "error")


# ============================================================================
# Task 8.7: Test account with failed P&L recalculation still resumes
# ============================================================================


@pytest.mark.asyncio
async def test_failed_pnl_still_resumes(resumer: TradingResumer) -> None:
    """Account with failed P&L recalculation should still resume (uses fallback)."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")
    recon_result = make_reconciliation_result("ftmo-001", success=True)
    pnl_result = make_recalculation_result(
        "ftmo-001", success=False, error_message="DB error"
    )
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert
    assert result.accounts_resumed == 1
    assert result.accounts_blocked == 0
    resumer._account_manager._spawn_account_task.assert_awaited_once()


# ============================================================================
# Task 8.8: Test recovery duration calculation
# ============================================================================


@pytest.mark.asyncio
async def test_recovery_duration_calculation(resumer: TradingResumer) -> None:
    """Recovery duration should be calculated correctly."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")
    recon_result = make_reconciliation_result("ftmo-001", success=True)
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc) - timedelta(seconds=10)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert
    assert result.recovery_duration.total_seconds() >= 10


# ============================================================================
# Task 8.9: Test notification sent on successful recovery
# ============================================================================


@pytest.mark.asyncio
async def test_notification_sent_on_success(resumer: TradingResumer) -> None:
    """Notification should be sent on successful recovery."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")
    recon_result = make_reconciliation_result("ftmo-001", success=True)
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert
    assert result.notification_sent is True
    resumer._redis.client.publish.assert_awaited_once()

    # Verify notification channel
    call_args = resumer._redis.client.publish.call_args
    assert call_args[0][0] == "alerts:system"


# ============================================================================
# Task 8.10: Test notification failure doesn't block resume
# ============================================================================


@pytest.mark.asyncio
async def test_notification_failure_doesnt_block(resumer: TradingResumer) -> None:
    """Notification failure should not block account resume."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")
    resumer._redis.client.publish = AsyncMock(side_effect=Exception("Pub/sub error"))
    recon_result = make_reconciliation_result("ftmo-001", success=True)
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert
    assert result.success is True
    assert result.accounts_resumed == 1
    assert result.notification_sent is False


# ============================================================================
# Task 8.11: Test multiple accounts with mixed statuses
# ============================================================================


@pytest.mark.asyncio
async def test_multiple_accounts_mixed_statuses(resumer: TradingResumer) -> None:
    """Multiple accounts with different statuses should be handled correctly."""
    # Arrange - 3 accounts with different pre-crash statuses
    status_map = {
        "ftmo-001": "active",  # Should resume
        "ftmo-002": "paused",  # Should skip
        "ftmo-003": "active",  # Should resume
    }
    resumer._redis.get_account_status = AsyncMock(
        side_effect=lambda acc: status_map[acc]
    )

    recon_results = {
        "ftmo-001": make_reconciliation_result("ftmo-001", success=True),
        "ftmo-002": make_reconciliation_result("ftmo-002", success=True),
        "ftmo-003": make_reconciliation_result("ftmo-003", success=True),
    }
    pnl_results = {
        "ftmo-001": make_recalculation_result("ftmo-001", success=True),
        "ftmo-002": make_recalculation_result("ftmo-002", success=True),
        "ftmo-003": make_recalculation_result("ftmo-003", success=True),
    }
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results=recon_results,
        pnl_results=pnl_results,
        recovery_start_time=start_time,
    )

    # Assert
    assert result.accounts_resumed == 2  # ftmo-001 and ftmo-003
    assert result.accounts_skipped == 1  # ftmo-002
    assert result.accounts_blocked == 0
    assert len(result.account_results) == 3


# ============================================================================
# Task 8.12: Test resume failure for one account doesn't block others
# ============================================================================


@pytest.mark.asyncio
async def test_one_resume_failure_doesnt_block_others(resumer: TradingResumer) -> None:
    """Failure to resume one account should not block others."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")

    # Make spawning fail for first account but succeed for second
    call_count = 0

    async def spawn_with_failure(account_id: str) -> None:
        nonlocal call_count
        call_count += 1
        if account_id == "ftmo-001":
            raise Exception("Spawn failed")

    resumer._account_manager._spawn_account_task = AsyncMock(
        side_effect=spawn_with_failure
    )

    recon_results = {
        "ftmo-001": make_reconciliation_result("ftmo-001", success=True),
        "ftmo-002": make_reconciliation_result("ftmo-002", success=True),
    }
    pnl_results = {
        "ftmo-001": make_recalculation_result("ftmo-001", success=True),
        "ftmo-002": make_recalculation_result("ftmo-002", success=True),
    }
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results=recon_results,
        pnl_results=pnl_results,
        recovery_start_time=start_time,
    )

    # Assert - both accounts were attempted
    assert call_count == 2
    # One succeeded, one blocked due to error
    assert result.accounts_resumed == 1  # ftmo-002
    assert result.accounts_blocked == 1  # ftmo-001 (failed to spawn)


# ============================================================================
# Task 8.13: Test ResumeResult summary counts are accurate
# ============================================================================


@pytest.mark.asyncio
async def test_resume_result_counts_accurate(resumer: TradingResumer) -> None:
    """ResumeResult should have accurate counts."""
    # Arrange - 4 accounts with different outcomes
    status_map = {
        "acc-1": "active",  # Resume
        "acc-2": "paused",  # Skip
        "acc-3": "active",  # Block (manual intervention)
        "acc-4": "stopped",  # Skip
    }
    resumer._redis.get_account_status = AsyncMock(side_effect=lambda acc: status_map[acc])

    recon_results = {
        "acc-1": make_reconciliation_result("acc-1", success=True),
        "acc-2": make_reconciliation_result("acc-2", success=True),
        "acc-3": make_reconciliation_result(
            "acc-3", success=False, requires_manual_intervention=True
        ),
        "acc-4": make_reconciliation_result("acc-4", success=True),
    }
    pnl_results = {
        "acc-1": make_recalculation_result("acc-1", success=True),
        "acc-2": make_recalculation_result("acc-2", success=True),
        "acc-3": make_recalculation_result("acc-3", success=True),
        "acc-4": make_recalculation_result("acc-4", success=True),
    }
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results=recon_results,
        pnl_results=pnl_results,
        recovery_start_time=start_time,
    )

    # Assert
    assert result.accounts_resumed == 1  # acc-1
    assert result.accounts_skipped == 2  # acc-2, acc-4
    assert result.accounts_blocked == 1  # acc-3
    assert len(result.account_results) == 4


# ============================================================================
# Task 8.14: Test race condition - status change during resume loop
# ============================================================================


@pytest.mark.asyncio
async def test_handles_concurrent_status_changes(resumer: TradingResumer) -> None:
    """Should handle status changes during resume loop gracefully."""
    # Arrange - status changes after first call
    call_count = 0

    async def changing_status(account_id: str) -> str:
        nonlocal call_count
        call_count += 1
        # First call returns active, subsequent calls return paused
        if call_count <= 2:  # First account gets 2 calls
            return "active"
        return "paused"

    resumer._redis.get_account_status = AsyncMock(side_effect=changing_status)

    recon_results = {
        "acc-1": make_reconciliation_result("acc-1", success=True),
    }
    pnl_results = {
        "acc-1": make_recalculation_result("acc-1", success=True),
    }
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results=recon_results,
        pnl_results=pnl_results,
        recovery_start_time=start_time,
    )

    # Assert - should complete without error
    assert result.success is True


# ============================================================================
# Task 8.15: Test blocked account has Redis status set to "error"
# ============================================================================


@pytest.mark.asyncio
async def test_blocked_account_status_set_to_error(resumer: TradingResumer) -> None:
    """Blocked accounts should have Redis status set to error."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")
    recon_result = make_reconciliation_result(
        "ftmo-001", success=False, requires_manual_intervention=True
    )
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert
    assert result.accounts_blocked == 1
    resumer._redis.save_account_status.assert_awaited_once_with("ftmo-001", "error")

    # Verify account result has error status
    account_result = result.account_results[0]
    assert account_result.current_status == "error"


# ============================================================================
# Additional Edge Case Tests
# ============================================================================


@pytest.mark.asyncio
async def test_empty_accounts_list(resumer: TradingResumer) -> None:
    """Should handle empty accounts list gracefully."""
    start_time = datetime.now(timezone.utc)

    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={},
        pnl_results={},
        recovery_start_time=start_time,
    )

    assert result.success is True
    assert result.accounts_resumed == 0
    assert result.accounts_skipped == 0
    assert result.accounts_blocked == 0
    assert len(result.account_results) == 0


@pytest.mark.asyncio
async def test_missing_pnl_result_still_resumes(resumer: TradingResumer) -> None:
    """Account with missing P&L result should still resume if eligible."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")
    recon_result = make_reconciliation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc)

    # Act - pass reconciliation result but no P&L result
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={},  # No P&L result
        recovery_start_time=start_time,
    )

    # Assert - should still resume
    assert result.accounts_resumed == 1
    resumer._account_manager._spawn_account_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_reconciliation_result_still_resumes(
    resumer: TradingResumer,
) -> None:
    """Account with missing reconciliation result should still resume if eligible."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc)

    # Act - pass P&L result but no reconciliation result
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={},  # No recon result
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert - should still resume
    assert result.accounts_resumed == 1
    resumer._account_manager._spawn_account_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_status_defaults_to_stopped(resumer: TradingResumer) -> None:
    """Account with missing status should default to stopped."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value=None)  # No status
    recon_result = make_reconciliation_result("ftmo-001", success=True)
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert - should be skipped (status defaults to stopped)
    assert result.accounts_resumed == 0
    assert result.accounts_skipped == 1
    resumer._account_manager._spawn_account_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_resume_result_data(resumer: TradingResumer) -> None:
    """AccountResumeResult should contain correct data."""
    # Arrange
    resumer._redis.get_account_status = AsyncMock(return_value="active")
    recon_result = make_reconciliation_result("ftmo-001", success=True)
    pnl_result = make_recalculation_result("ftmo-001", success=True)
    start_time = datetime.now(timezone.utc)

    # Act
    result = await resumer.resume_trading_after_recovery(
        reconciliation_results={"ftmo-001": recon_result},
        pnl_results={"ftmo-001": pnl_result},
        recovery_start_time=start_time,
    )

    # Assert
    assert len(result.account_results) == 1
    account_result = result.account_results[0]
    assert account_result.account_id == "ftmo-001"
    assert account_result.resumed is True
    assert account_result.previous_status == "active"
    assert account_result.current_status == "active"
    assert account_result.reason == "Resumed successfully"
