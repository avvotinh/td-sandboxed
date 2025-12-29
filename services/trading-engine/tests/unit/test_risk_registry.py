"""Unit tests for RiskStateRegistry class."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.accounts.risk_registry import RiskStateRegistry
from src.accounts.risk_state import RiskState


@pytest.fixture
def mock_redis():
    """Create mock Redis state manager."""
    mock = MagicMock()
    mock.get_risk_state = AsyncMock(return_value=None)
    mock.save_risk_state = AsyncMock()
    mock.record_risk_violation = AsyncMock()
    return mock


class TestRiskStateRegistryInit:
    """Tests for RiskStateRegistry initialization."""

    def test_initialization(self, mock_redis):
        """Registry should initialize with empty managers."""
        registry = RiskStateRegistry(mock_redis)

        assert registry._risk_managers == {}


class TestGetOrCreate:
    """Tests for get_or_create method."""

    @pytest.mark.asyncio
    async def test_creates_new_manager(self, mock_redis):
        """get_or_create should create manager for new account."""
        registry = RiskStateRegistry(mock_redis)

        manager = await registry.get_or_create("account-a")

        assert manager.account_id == "account-a"
        assert "account-a" in registry._risk_managers

    @pytest.mark.asyncio
    async def test_returns_existing_manager(self, mock_redis):
        """get_or_create should return existing manager."""
        registry = RiskStateRegistry(mock_redis)

        manager1 = await registry.get_or_create("account-a")
        manager2 = await registry.get_or_create("account-a")

        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_loads_existing_state_from_redis(self, mock_redis):
        """get_or_create should load existing state from Redis."""
        existing_state = RiskState(
            daily_pnl=Decimal("-2000"),
            current_equity=Decimal("98000"),
        )
        mock_redis.get_risk_state = AsyncMock(return_value=existing_state)
        registry = RiskStateRegistry(mock_redis)

        manager = await registry.get_or_create("account-a")

        assert manager.state.daily_pnl == Decimal("-2000")
        assert manager.state.current_equity == Decimal("98000")


class TestRiskStateIsolation:
    """Tests for complete risk state isolation between accounts."""

    @pytest.mark.asyncio
    async def test_separate_managers_per_account(self, mock_redis):
        """Each account gets its own risk manager."""
        registry = RiskStateRegistry(mock_redis)

        manager_a = await registry.get_or_create("account-a")
        manager_b = await registry.get_or_create("account-b")

        assert manager_a is not manager_b
        assert manager_a.account_id == "account-a"
        assert manager_b.account_id == "account-b"

    @pytest.mark.asyncio
    async def test_equity_update_isolated(self, mock_redis):
        """Updating Account A equity does NOT affect Account B."""
        registry = RiskStateRegistry(mock_redis)

        # Initialize both accounts with same starting equity
        await registry.update_account_equity("account-a", Decimal("100000"))
        await registry.update_account_equity("account-b", Decimal("100000"))

        # Update only Account A
        await registry.update_account_equity("account-a", Decimal("95000"))

        # Verify isolation
        state_a = registry.get_risk_state("account-a")
        state_b = registry.get_risk_state("account-b")

        assert state_a.current_equity == Decimal("95000")
        assert state_b.current_equity == Decimal("100000")  # Unchanged!

    @pytest.mark.asyncio
    async def test_trade_pnl_isolated(self, mock_redis):
        """Recording trade on Account A does NOT affect Account B."""
        registry = RiskStateRegistry(mock_redis)

        # Initialize both accounts
        manager_a = await registry.get_or_create("account-a")
        manager_b = await registry.get_or_create("account-b")

        # Set starting balances
        manager_a._state.reset_daily(Decimal("100000"))
        manager_b._state.reset_daily(Decimal("100000"))

        # Record loss only on Account A
        await registry.record_account_trade("account-a", Decimal("-2500"))

        # Verify isolation
        assert registry.get_risk_state("account-a").daily_pnl == Decimal("-2500")
        assert registry.get_risk_state("account-b").daily_pnl == Decimal("0")  # Unchanged!

    @pytest.mark.asyncio
    async def test_violation_check_isolated(self, mock_redis):
        """Checking Account A violation uses only Account A's state."""
        registry = RiskStateRegistry(mock_redis)

        # Account A has 4.5% loss, Account B has 0% loss
        manager_a = await registry.get_or_create("account-a")
        manager_a._state.daily_pnl = Decimal("-4500")
        manager_a._state.daily_pnl_percent = Decimal("-4.5")
        manager_a._state.daily_starting_balance = Decimal("100000")

        manager_b = await registry.get_or_create("account-b")
        manager_b._state.daily_pnl = Decimal("0")
        manager_b._state.daily_pnl_percent = Decimal("0")

        # Check 5% limit - Account A not violated, Account B not violated
        violated_a, _ = await registry.check_account_violation(
            "account-a", "daily_loss", Decimal("5.0")
        )
        violated_b, _ = await registry.check_account_violation(
            "account-b", "daily_loss", Decimal("5.0")
        )

        assert not violated_a  # 4.5% < 5%
        assert not violated_b  # 0% < 5%

    @pytest.mark.asyncio
    async def test_account_a_violation_does_not_affect_account_b(self, mock_redis):
        """When Account A violates limit, Account B continues trading."""
        registry = RiskStateRegistry(mock_redis)

        # Account A has 5.1% loss (violated)
        manager_a = await registry.get_or_create("account-a")
        manager_a._state.daily_pnl = Decimal("-5100")
        manager_a._state.daily_pnl_percent = Decimal("-5.1")

        # Account B is fine
        manager_b = await registry.get_or_create("account-b")
        manager_b._state.daily_pnl = Decimal("500")
        manager_b._state.daily_pnl_percent = Decimal("0.5")

        # Check violations
        violated_a, _ = await registry.check_account_violation(
            "account-a", "daily_loss", Decimal("5.0")
        )
        violated_b, _ = await registry.check_account_violation(
            "account-b", "daily_loss", Decimal("5.0")
        )

        assert violated_a  # Account A should be paused
        assert not violated_b  # Account B continues trading!


class TestCheckAccountViolation:
    """Tests for check_account_violation method."""

    @pytest.mark.asyncio
    async def test_daily_loss_violation(self, mock_redis):
        """Check daily loss violation."""
        registry = RiskStateRegistry(mock_redis)
        manager = await registry.get_or_create("test")
        manager._state.daily_pnl = Decimal("-5100")
        manager._state.daily_pnl_percent = Decimal("-5.1")

        violated, current = await registry.check_account_violation(
            "test", "daily_loss", Decimal("5.0")
        )

        assert violated is True
        assert current == Decimal("-5.1")

    @pytest.mark.asyncio
    async def test_max_drawdown_violation(self, mock_redis):
        """Check max drawdown violation."""
        registry = RiskStateRegistry(mock_redis)
        manager = await registry.get_or_create("test")
        manager._state.total_drawdown_percent = Decimal("10.5")

        violated, current = await registry.check_account_violation(
            "test", "max_drawdown", Decimal("10.0")
        )

        assert violated is True
        assert current == Decimal("10.5")

    @pytest.mark.asyncio
    async def test_unknown_rule_type_raises(self, mock_redis):
        """Unknown rule type should raise ValueError."""
        registry = RiskStateRegistry(mock_redis)
        await registry.get_or_create("test")

        with pytest.raises(ValueError, match="Unknown rule type"):
            await registry.check_account_violation(
                "test", "unknown_rule", Decimal("5.0")
            )


class TestGetRiskState:
    """Tests for get_risk_state method."""

    @pytest.mark.asyncio
    async def test_returns_state_for_existing_account(self, mock_redis):
        """get_risk_state should return state for existing account."""
        registry = RiskStateRegistry(mock_redis)
        await registry.get_or_create("account-a")
        await registry.update_account_equity("account-a", Decimal("100000"))

        state = registry.get_risk_state("account-a")

        assert state is not None
        assert state.current_equity == Decimal("100000")

    def test_returns_none_for_unknown_account(self, mock_redis):
        """get_risk_state should return None for unknown account."""
        registry = RiskStateRegistry(mock_redis)

        state = registry.get_risk_state("unknown")

        assert state is None


class TestResetDailyAll:
    """Tests for reset_daily_all method."""

    @pytest.mark.asyncio
    async def test_resets_all_accounts(self, mock_redis):
        """reset_daily_all should reset all accounts."""
        registry = RiskStateRegistry(mock_redis)

        # Initialize accounts with losses
        manager_a = await registry.get_or_create("account-a")
        manager_a._state.daily_pnl = Decimal("-2000")

        manager_b = await registry.get_or_create("account-b")
        manager_b._state.daily_pnl = Decimal("-1500")

        # Reset all
        await registry.reset_daily_all({
            "account-a": Decimal("98000"),
            "account-b": Decimal("98500"),
        })

        # Verify both reset
        assert registry.get_risk_state("account-a").daily_pnl == Decimal("0")
        assert registry.get_risk_state("account-b").daily_pnl == Decimal("0")


class TestRecordViolation:
    """Tests for record_violation method."""

    @pytest.mark.asyncio
    async def test_records_violation_to_redis(self, mock_redis):
        """record_violation should persist to Redis."""
        registry = RiskStateRegistry(mock_redis)

        await registry.record_violation(
            "account-a",
            "daily_loss",
            Decimal("5.5"),
            Decimal("5.0"),
        )

        mock_redis.record_risk_violation.assert_called_once_with(
            "account-a",
            "daily_loss",
            "5.5",
            "5.0",
        )


class TestRedisIsolation:
    """Tests for Redis key isolation."""

    @pytest.mark.asyncio
    async def test_redis_save_uses_correct_account_id(self, mock_redis):
        """Redis save should use account-specific keys."""
        registry = RiskStateRegistry(mock_redis)

        await registry.update_account_equity("account-a", Decimal("100000"))
        await registry.update_account_equity("account-b", Decimal("50000"))

        # Verify Redis was called with correct account IDs
        calls = mock_redis.save_risk_state.call_args_list
        account_ids = [call[0][0] for call in calls]

        assert "account-a" in account_ids
        assert "account-b" in account_ids
