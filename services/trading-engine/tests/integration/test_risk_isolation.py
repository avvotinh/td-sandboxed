"""Integration tests for risk isolation across multiple accounts.

These tests verify the CRITICAL requirement that each account's risk state
is completely isolated from other accounts.
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.accounts.risk_isolation import RiskIsolationService, RuleConfig
from src.accounts.risk_registry import RiskStateRegistry


@pytest.fixture
def mock_redis():
    """Create mock Redis state manager."""
    mock = MagicMock()
    mock.get_risk_state = AsyncMock(return_value=None)
    mock.save_risk_state = AsyncMock()
    mock.record_risk_violation = AsyncMock()
    mock.save_account_status = AsyncMock()
    mock.get_account_status = AsyncMock(return_value="active")
    mock.publish_alert = AsyncMock()
    return mock


@pytest.fixture
def mock_account_manager(mock_redis):
    """Create mock account manager."""
    mock = MagicMock()
    mock.pause_account = AsyncMock()
    mock.pause_for_rule_violation = AsyncMock()
    mock._publish_alert = AsyncMock()
    mock._redis = mock_redis
    return mock


@pytest.mark.integration
class TestRiskIsolationIntegration:
    """Integration tests for risk isolation across multiple accounts."""

    @pytest.mark.asyncio
    async def test_three_accounts_one_violates_others_continue(self, mock_redis, mock_account_manager):
        """
        Scenario (AC1):
        - Account A, B, C all active
        - Account A hits 5% daily loss limit
        - Account A gets paused
        - Accounts B and C continue trading normally
        """
        registry = RiskStateRegistry(mock_redis)

        # Initialize three accounts with starting balances
        for account_id in ["ftmo-001", "5ers-001", "personal-001"]:
            manager = await registry.get_or_create(account_id)
            manager._state.reset_daily(Decimal("100000"))

        # Simulate Account A losing 5.1%
        await registry.record_account_trade("ftmo-001", Decimal("-5100"))

        # Simulate Account B gaining 0.5%
        await registry.record_account_trade("5ers-001", Decimal("500"))

        # Simulate Account C small loss 1%
        await registry.record_account_trade("personal-001", Decimal("-1000"))

        # Check violations
        results = {}
        for account_id in ["ftmo-001", "5ers-001", "personal-001"]:
            violated, current = await registry.check_account_violation(
                account_id, "daily_loss", Decimal("5.0")
            )
            results[account_id] = {"violated": violated, "current": current}

        # Assert isolation (AC1: Account A violated, B and C continue)
        assert results["ftmo-001"]["violated"] is True  # Should pause
        assert results["5ers-001"]["violated"] is False  # Continue trading
        assert results["personal-001"]["violated"] is False  # Continue trading

    @pytest.mark.asyncio
    async def test_warning_isolated_per_account(self, mock_redis, mock_account_manager):
        """
        Scenario (AC2):
        - Account B has 80% warning level
        - Account A and C have no warnings
        - Warnings are calculated independently
        """
        registry = RiskStateRegistry(mock_redis)
        service = RiskIsolationService(mock_account_manager, registry)

        # Initialize three accounts
        for account_id in ["account-a", "account-b", "account-c"]:
            manager = await registry.get_or_create(account_id)
            manager._state.reset_daily(Decimal("100000"))

        # Account A: small profit
        await registry.record_account_trade("account-a", Decimal("500"))

        # Account B: 80% of 5% limit = 4% loss
        await registry.record_account_trade("account-b", Decimal("-4000"))

        # Account C: small loss
        await registry.record_account_trade("account-c", Decimal("-500"))

        # Get warning levels (5% limit)
        warning_a = await service.get_warning_level("account-a", Decimal("5.0"))
        warning_b = await service.get_warning_level("account-b", Decimal("5.0"))
        warning_c = await service.get_warning_level("account-c", Decimal("5.0"))

        # Assert isolation (AC2: Only Account B has warning)
        assert warning_a is None  # In profit
        assert warning_b == 80  # 4% = 80% of 5% limit
        assert warning_c is None  # 0.5% = 10% of limit (below 70%)

    @pytest.mark.asyncio
    async def test_drawdown_calculated_independently(self, mock_redis, mock_account_manager):
        """
        Scenario (AC3):
        - Account C's equity drops 5%
        - Only Account C's drawdown is updated
        - Accounts A and B's drawdown calculations are independent
        """
        registry = RiskStateRegistry(mock_redis)

        # Initialize three accounts at different equity levels
        manager_a = await registry.get_or_create("account-a")
        manager_a._state.current_equity = Decimal("100000")
        manager_a._state.peak_equity = Decimal("100000")

        manager_b = await registry.get_or_create("account-b")
        manager_b._state.current_equity = Decimal("100000")
        manager_b._state.peak_equity = Decimal("100000")

        manager_c = await registry.get_or_create("account-c")
        manager_c._state.current_equity = Decimal("100000")
        manager_c._state.peak_equity = Decimal("100000")

        # Account C equity drops 5%
        await registry.update_account_equity("account-c", Decimal("95000"))

        # Assert isolation (AC3: Only Account C has drawdown)
        state_a = registry.get_risk_state("account-a")
        state_b = registry.get_risk_state("account-b")
        state_c = registry.get_risk_state("account-c")

        assert state_a.total_drawdown_percent == Decimal("0")  # Unchanged
        assert state_b.total_drawdown_percent == Decimal("0")  # Unchanged
        assert state_c.total_drawdown_percent == Decimal("5")  # Updated

    @pytest.mark.asyncio
    async def test_concurrent_equity_updates_isolated(self, mock_redis, mock_account_manager):
        """Concurrent equity updates to different accounts are isolated."""
        registry = RiskStateRegistry(mock_redis)

        # Concurrent updates (simulates high-frequency trading)
        await asyncio.gather(
            registry.update_account_equity("account-a", Decimal("99000")),
            registry.update_account_equity("account-b", Decimal("101000")),
            registry.update_account_equity("account-c", Decimal("50000")),
        )

        # Verify each has correct equity
        assert registry.get_risk_state("account-a").current_equity == Decimal("99000")
        assert registry.get_risk_state("account-b").current_equity == Decimal("101000")
        assert registry.get_risk_state("account-c").current_equity == Decimal("50000")

    @pytest.mark.asyncio
    async def test_concurrent_trades_isolated(self, mock_redis, mock_account_manager):
        """
        Scenario (AC4): Concurrent trades across multiple accounts with independent P&L tracking.
        """
        registry = RiskStateRegistry(mock_redis)

        # Initialize accounts
        for account_id in ["account-a", "account-b", "account-c"]:
            manager = await registry.get_or_create(account_id)
            manager._state.reset_daily(Decimal("100000"))

        # Concurrent trades
        await asyncio.gather(
            registry.record_account_trade("account-a", Decimal("-1000")),
            registry.record_account_trade("account-b", Decimal("2000")),
            registry.record_account_trade("account-c", Decimal("-500")),
        )

        # Verify isolation
        assert registry.get_risk_state("account-a").daily_pnl == Decimal("-1000")
        assert registry.get_risk_state("account-b").daily_pnl == Decimal("2000")
        assert registry.get_risk_state("account-c").daily_pnl == Decimal("-500")

    @pytest.mark.asyncio
    async def test_per_account_metrics_display(self, mock_redis, mock_account_manager):
        """
        Scenario (AC4): Each account shows its own isolated metrics.
        """
        registry = RiskStateRegistry(mock_redis)

        # Set up accounts with different metrics
        manager_a = await registry.get_or_create("account-a")
        manager_a._state.daily_pnl = Decimal("-2000")
        manager_a._state.daily_pnl_percent = Decimal("-2.0")
        manager_a._state.current_equity = Decimal("98000")
        manager_a._state.peak_equity = Decimal("100000")
        manager_a._state.total_drawdown_percent = Decimal("2.0")

        manager_b = await registry.get_or_create("account-b")
        manager_b._state.daily_pnl = Decimal("1500")
        manager_b._state.daily_pnl_percent = Decimal("1.5")
        manager_b._state.current_equity = Decimal("101500")
        manager_b._state.peak_equity = Decimal("101500")
        manager_b._state.total_drawdown_percent = Decimal("0")

        # Query each account's metrics
        state_a = registry.get_risk_state("account-a")
        state_b = registry.get_risk_state("account-b")

        # Verify isolation (AC4: Each account shows its own metrics)
        assert state_a.daily_pnl == Decimal("-2000")
        assert state_a.total_drawdown_percent == Decimal("2.0")

        assert state_b.daily_pnl == Decimal("1500")
        assert state_b.total_drawdown_percent == Decimal("0")

    @pytest.mark.asyncio
    async def test_daily_reset_affects_only_target_account(self, mock_redis, mock_account_manager):
        """Daily reset affects only the target account."""
        registry = RiskStateRegistry(mock_redis)

        # Set up accounts with losses
        manager_a = await registry.get_or_create("account-a")
        manager_a._state.daily_pnl = Decimal("-3000")

        manager_b = await registry.get_or_create("account-b")
        manager_b._state.daily_pnl = Decimal("-2000")

        # Reset only Account A
        await manager_a.reset_daily(Decimal("97000"))

        # Verify isolation
        assert registry.get_risk_state("account-a").daily_pnl == Decimal("0")
        assert registry.get_risk_state("account-b").daily_pnl == Decimal("-2000")  # Unchanged


@pytest.mark.integration
class TestRiskIsolationServiceIntegration:
    """Integration tests for RiskIsolationService."""

    @pytest.mark.asyncio
    async def test_on_trade_completed_triggers_pause_only_for_violating_account(
        self, mock_redis, mock_account_manager
    ):
        """
        When a trade causes violation, only that account is paused.
        """
        registry = RiskStateRegistry(mock_redis)
        service = RiskIsolationService(mock_account_manager, registry)

        # Initialize accounts
        for account_id in ["account-a", "account-b"]:
            manager = await registry.get_or_create(account_id)
            manager._state.reset_daily(Decimal("100000"))

        # Account A: Already at 4% loss
        await registry.record_account_trade("account-a", Decimal("-4000"))

        # Account A: Trade that pushes over 5% limit
        await service.on_trade_completed(
            "account-a",
            realized_pnl=Decimal("-1500"),  # Total: 5.5%
            daily_loss_limit=Decimal("5.0"),
        )

        # Verify only Account A was paused
        mock_account_manager.pause_for_rule_violation.assert_called_once()
        call_args = mock_account_manager.pause_for_rule_violation.call_args[0]
        assert call_args[0] == "account-a"

    @pytest.mark.asyncio
    async def test_pre_trade_check_uses_only_target_account_state(
        self, mock_redis, mock_account_manager
    ):
        """
        Pre-trade check should only consider the target account's state.
        """
        registry = RiskStateRegistry(mock_redis)
        service = RiskIsolationService(mock_account_manager, registry)

        # Account A: Already violated (but we're checking Account B)
        manager_a = await registry.get_or_create("account-a")
        manager_a._state.daily_pnl = Decimal("-6000")
        manager_a._state.daily_pnl_percent = Decimal("-6.0")

        # Account B: Safe
        manager_b = await registry.get_or_create("account-b")
        manager_b._state.daily_pnl = Decimal("-1000")
        manager_b._state.daily_pnl_percent = Decimal("-1.0")

        rules = [RuleConfig(rule_type="daily_loss", limit=Decimal("5.0"))]

        # Pre-trade check for Account B (should pass even though A is violated)
        allowed = await service.check_pre_trade("account-b", rules)

        assert allowed is True  # Account B is fine

    @pytest.mark.asyncio
    async def test_on_equity_update_triggers_pause_for_max_drawdown(
        self, mock_redis, mock_account_manager
    ):
        """
        Equity update that causes max drawdown violation triggers pause.
        """
        registry = RiskStateRegistry(mock_redis)
        service = RiskIsolationService(mock_account_manager, registry)

        # Initialize account with peak equity
        manager = await registry.get_or_create("account-a")
        manager._state.peak_equity = Decimal("100000")

        # Equity update that causes 11% drawdown (over 10% limit)
        await service.on_equity_update(
            "account-a",
            equity=Decimal("89000"),
            max_drawdown_limit=Decimal("10.0"),
        )

        # Verify pause was triggered
        mock_account_manager.pause_for_rule_violation.assert_called_once()
        call_args = mock_account_manager.pause_for_rule_violation.call_args[0]
        assert call_args[0] == "account-a"
        assert call_args[1] == "max_drawdown"

    @pytest.mark.asyncio
    async def test_pre_trade_check_with_empty_rules_allows_trade(
        self, mock_redis, mock_account_manager
    ):
        """
        Pre-trade check with empty rules list should allow trade.
        """
        registry = RiskStateRegistry(mock_redis)
        service = RiskIsolationService(mock_account_manager, registry)

        # Initialize account (even with losses)
        manager = await registry.get_or_create("account-a")
        manager._state.daily_pnl = Decimal("-4000")
        manager._state.daily_pnl_percent = Decimal("-4.0")

        # Empty rules list should always allow
        allowed = await service.check_pre_trade("account-a", rules=[])

        assert allowed is True
