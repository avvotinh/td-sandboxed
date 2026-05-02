"""Unit tests for AccountRiskManager class."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.accounts.risk_manager import AccountRiskManager
from src.accounts.risk_state import RiskState


@pytest.fixture
def mock_redis():
    """Create mock Redis state manager."""
    mock = MagicMock()
    mock.save_risk_state = AsyncMock()
    mock.get_risk_state = AsyncMock(return_value=None)
    return mock


class TestAccountRiskManagerInit:
    """Tests for AccountRiskManager initialization."""

    def test_default_initialization(self, mock_redis):
        """Manager should initialize with empty RiskState."""
        manager = AccountRiskManager("test-account", mock_redis)

        assert manager.account_id == "test-account"
        assert manager.state.daily_pnl == Decimal("0")
        assert manager.state.current_equity == Decimal("0")

    def test_initialization_with_state(self, mock_redis):
        """Manager should accept initial state."""
        initial_state = RiskState(
            daily_pnl=Decimal("-1000"),
            current_equity=Decimal("99000"),
        )

        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        assert manager.state.daily_pnl == Decimal("-1000")
        assert manager.state.current_equity == Decimal("99000")


class TestUpdateEquity:
    """Tests for update_equity method."""

    @pytest.mark.asyncio
    async def test_update_equity(self, mock_redis):
        """Update equity should update state and persist."""
        manager = AccountRiskManager("test-account", mock_redis)

        await manager.update_equity(Decimal("100000"))

        assert manager.state.current_equity == Decimal("100000")
        assert manager.state.peak_equity == Decimal("100000")
        mock_redis.save_risk_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_equity_new_peak(self, mock_redis):
        """Update equity above peak should update peak."""
        initial_state = RiskState(
            current_equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        await manager.update_equity(Decimal("105000"))

        assert manager.state.current_equity == Decimal("105000")
        assert manager.state.peak_equity == Decimal("105000")

    @pytest.mark.asyncio
    async def test_update_equity_calculates_drawdown(self, mock_redis):
        """Update equity below peak should calculate drawdown."""
        initial_state = RiskState(
            current_equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        await manager.update_equity(Decimal("95000"))

        assert manager.state.total_drawdown_percent == Decimal("5")


class TestRecordTradePnl:
    """Tests for record_trade_pnl method."""

    @pytest.mark.asyncio
    async def test_record_trade_pnl(self, mock_redis):
        """Record trade P&L should update state and persist."""
        initial_state = RiskState(
            daily_starting_balance=Decimal("100000"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        await manager.record_trade_pnl(Decimal("-2500"))

        assert manager.state.daily_pnl == Decimal("-2500")
        assert manager.state.daily_pnl_percent == Decimal("-2.5")
        mock_redis.save_risk_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_multiple_trades(self, mock_redis):
        """Record multiple trades should accumulate."""
        initial_state = RiskState(
            daily_starting_balance=Decimal("100000"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        await manager.record_trade_pnl(Decimal("-1000"))
        await manager.record_trade_pnl(Decimal("500"))
        await manager.record_trade_pnl(Decimal("-2000"))

        assert manager.state.daily_pnl == Decimal("-2500")
        assert manager.state.daily_pnl_percent == Decimal("-2.5")


class TestCheckDailyLossLimit:
    """Tests for check_daily_loss_limit method."""

    def test_not_violated_no_loss(self, mock_redis):
        """No violation when no losses."""
        initial_state = RiskState(
            daily_pnl=Decimal("1000"),
            daily_pnl_percent=Decimal("1.0"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        violated, current = manager.check_daily_loss_limit(Decimal("5.0"))

        assert violated is False
        assert current == Decimal("1.0")

    def test_not_violated_small_loss(self, mock_redis):
        """No violation when loss below limit."""
        initial_state = RiskState(
            daily_pnl=Decimal("-3000"),
            daily_pnl_percent=Decimal("-3.0"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        violated, current = manager.check_daily_loss_limit(Decimal("5.0"))

        assert violated is False
        assert current == Decimal("-3.0")

    def test_violated_at_limit(self, mock_redis):
        """Violation when loss equals limit."""
        initial_state = RiskState(
            daily_pnl=Decimal("-5000"),
            daily_pnl_percent=Decimal("-5.0"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        violated, current = manager.check_daily_loss_limit(Decimal("5.0"))

        assert violated is True
        assert current == Decimal("-5.0")

    def test_violated_above_limit(self, mock_redis):
        """Violation when loss exceeds limit."""
        initial_state = RiskState(
            daily_pnl=Decimal("-6000"),
            daily_pnl_percent=Decimal("-6.0"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        violated, current = manager.check_daily_loss_limit(Decimal("5.0"))

        assert violated is True
        assert current == Decimal("-6.0")


class TestCheckMaxDrawdown:
    """Tests for check_max_drawdown method."""

    def test_not_violated_no_drawdown(self, mock_redis):
        """No violation when no drawdown."""
        initial_state = RiskState(
            current_equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            total_drawdown_percent=Decimal("0"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        violated, current = manager.check_max_drawdown(Decimal("10.0"))

        assert violated is False
        assert current == Decimal("0")

    def test_not_violated_small_drawdown(self, mock_redis):
        """No violation when drawdown below limit."""
        initial_state = RiskState(
            current_equity=Decimal("95000"),
            peak_equity=Decimal("100000"),
            total_drawdown_percent=Decimal("5"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        violated, current = manager.check_max_drawdown(Decimal("10.0"))

        assert violated is False
        assert current == Decimal("5")

    def test_violated_at_limit(self, mock_redis):
        """Violation when drawdown equals limit."""
        initial_state = RiskState(
            current_equity=Decimal("90000"),
            peak_equity=Decimal("100000"),
            total_drawdown_percent=Decimal("10"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        violated, current = manager.check_max_drawdown(Decimal("10.0"))

        assert violated is True
        assert current == Decimal("10")


class TestGetWarningLevel:
    """Tests for get_warning_level method."""

    def test_no_warning_for_profit(self, mock_redis):
        """No warning when in profit."""
        initial_state = RiskState(
            daily_pnl=Decimal("1000"),
            daily_pnl_percent=Decimal("1.0"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        warning = manager.get_warning_level(Decimal("5.0"))

        assert warning is None

    def test_no_warning_below_70_percent(self, mock_redis):
        """No warning when below 70% of limit."""
        initial_state = RiskState(
            daily_pnl=Decimal("-2000"),
            daily_pnl_percent=Decimal("-2.0"),  # 40% of 5% limit
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        warning = manager.get_warning_level(Decimal("5.0"))

        assert warning is None

    def test_warning_at_70_percent(self, mock_redis):
        """Warning at 70% of limit."""
        initial_state = RiskState(
            daily_pnl=Decimal("-3500"),
            daily_pnl_percent=Decimal("-3.5"),  # 70% of 5% limit
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        warning = manager.get_warning_level(Decimal("5.0"))

        assert warning == 70

    def test_warning_at_80_percent(self, mock_redis):
        """Warning at 80% of limit."""
        initial_state = RiskState(
            daily_pnl=Decimal("-4000"),
            daily_pnl_percent=Decimal("-4.0"),  # 80% of 5% limit
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        warning = manager.get_warning_level(Decimal("5.0"))

        assert warning == 80

    def test_warning_at_90_percent(self, mock_redis):
        """Warning at 90% of limit."""
        initial_state = RiskState(
            daily_pnl=Decimal("-4500"),
            daily_pnl_percent=Decimal("-4.5"),  # 90% of 5% limit
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        warning = manager.get_warning_level(Decimal("5.0"))

        assert warning == 90

    def test_no_warning_for_zero_limit(self, mock_redis):
        """No warning when limit is zero (invalid)."""
        initial_state = RiskState(
            daily_pnl=Decimal("-1000"),
            daily_pnl_percent=Decimal("-1.0"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        warning = manager.get_warning_level(Decimal("0"))

        assert warning is None


class TestResetDaily:
    """Tests for reset_daily method."""

    @pytest.mark.asyncio
    async def test_reset_daily(self, mock_redis):
        """Reset daily should clear P&L and persist."""
        initial_state = RiskState(
            daily_pnl=Decimal("-3000"),
            daily_pnl_percent=Decimal("-3.0"),
        )
        manager = AccountRiskManager("test-account", mock_redis, initial_state)

        await manager.reset_daily(Decimal("97000"))

        assert manager.state.daily_pnl == Decimal("0")
        assert manager.state.daily_pnl_percent == Decimal("0")
        assert manager.state.daily_starting_balance == Decimal("97000")
        mock_redis.save_risk_state.assert_called_once()
