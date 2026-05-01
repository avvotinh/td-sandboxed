"""Integration tests for order validation flow (Story 4.6).

Tests cover:
- Full flow: Order -> Validator -> RuleEngine -> Result (AC1)
- FTMO preset with all 5 rules active (AC1-5)
- Order blocked when daily loss limit exceeded (AC3)
- Order blocked when max drawdown exceeded (AC3)
- Order blocked when position size too large (AC3)
- Order allowed with warnings from informational rules (AC4)
- ValidatedZmqAdapter integration (AC1-4)
- Performance test: 100 validations in < 5 seconds (AC6)
"""

import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.accounts.risk_registry import RiskStateRegistry
from src.accounts.risk_state import RiskState
from src.adapters.zmq_adapter import ZmqAdapter
from src.adapters.zmq_models import Order, OrderSide
from src.execution.exceptions import OrderBlockedError
from src.execution.order_validator import OrderValidator
from src.execution.validated_adapter import ValidatedZmqAdapter
from src.rules import RuleEngine
from pathlib import Path as _Path

import yaml as _yaml

from src.rules.parser import RuleParser as _RuleParser


# Story 10.13 — RulePresetLoader was removed. Tests that need the same
# rule set the old FTMO preset produced now load it directly from the
# backtest-local preset YAML and parse with :class:`RuleParser`.
_PRESETS_DIR = (
    _Path(__file__).resolve().parents[2] / "src" / "backtesting" / "presets"
)


def _load_preset_rules(name: str) -> list:
    """Build a rule list from a backtest-local preset YAML.

    Drop-in replacement for the deleted ``RulePresetLoader.load_preset``.
    Returns freshly parsed rule instances each call (no caching) — fine
    for integration tests, slightly slower than the old loader.
    """
    yaml_path = _PRESETS_DIR / f"{name.lower()}.yaml"
    data = _yaml.safe_load(yaml_path.read_text())
    return _RuleParser().parse_rules({"rules": data["rules"]})


def create_test_order(
    account_id: str = "test-account",
    symbol: str = "XAUUSD",
    volume: float = 0.1,
    order_id: str | None = None,
) -> Order:
    """Create a test order."""
    return Order(
        account_id=account_id,
        action=OrderSide.BUY,
        symbol=symbol,
        volume=volume,
        price=2000.0,
        order_id=order_id or f"order-{id(object())}",
    )


def create_test_account_state(
    balance: float = 100000.0,
    equity: float = 100000.0,
    daily_pnl_percent: float = 0.0,
    total_drawdown_percent: float = 0.0,
) -> dict:
    """Create a test account state with customizable values.

    Note: The RuleContextBuilder uses 'balance' and 'equity' keys, but rules
    may need additional context fields like 'account_balance', 'requested_lots', etc.
    The context builder passes 'current_balance' to rules.
    """
    return {
        # Fields used by RuleContextBuilder
        "balance": balance,
        "equity": equity,
        "initial_balance": balance,
        "peak_balance": balance,
        "daily_pnl": daily_pnl_percent * balance / 100,
        "daily_pnl_percent": daily_pnl_percent,
        "total_drawdown_percent": total_drawdown_percent,
        "open_positions_count": 0,
        "total_exposure": 0.0,
        # Additional fields expected directly by rules (not via context builder)
        # The context builder sets current_balance from balance
        "current_balance": balance,
        "account_balance": balance,
        "requested_lots": 0.1,
        "current_position_lots": 0.0,
        "total_pnl_percent": 0.0,
        "trading_days_count": 2,
    }


class TestFullValidationFlow:
    """Tests for full validation flow: Order -> Validator -> RuleEngine -> Result (AC1)."""

    @pytest.fixture
    def ftmo_engine(self):
        """Create RuleEngine with FTMO rules."""
        # Story 10.13: preset loader replaced by _load_preset_rules
        
        rules = _load_preset_rules("ftmo")
        return RuleEngine(account_id="test-account", rules=rules)

    @pytest.fixture
    def redis_mock(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_compliant_order_allowed(self, ftmo_engine, redis_mock):
        """Test compliant order is allowed through validation."""
        validator = OrderValidator(ftmo_engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.allowed is True
        assert result.is_blocked is False
        assert result.blocked_by_rule is None

    @pytest.mark.asyncio
    async def test_all_5_rules_evaluated(self, ftmo_engine, redis_mock):
        """Test all 5 FTMO rules are evaluated before decision."""
        # Use the RuleEngine directly to check all rules were evaluated
        account_state = create_test_account_state()
        result = ftmo_engine.validate(account_state, continue_after_block=True)

        assert len(result.all_results) == 5


class TestDailyLossLimitBlocking:
    """Tests for order blocked when daily loss limit exceeded (AC3)."""

    @pytest.fixture
    def ftmo_engine(self):
        """Create RuleEngine with FTMO rules."""
        # Story 10.13: preset loader replaced by _load_preset_rules
        
        rules = _load_preset_rules("ftmo")
        return RuleEngine(account_id="test-account", rules=rules)

    @pytest.fixture
    def redis_mock(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_order_blocked_at_5_percent_loss(self, ftmo_engine, redis_mock):
        """Test order is blocked when daily loss is at 5%."""
        validator = OrderValidator(ftmo_engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state(daily_pnl_percent=-5.0)

        result = await validator.validate_order(order, account_state)

        assert result.is_blocked is True
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_order_blocked_above_5_percent_loss(self, ftmo_engine, redis_mock):
        """Test order is blocked when daily loss exceeds 5%."""
        validator = OrderValidator(ftmo_engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state(daily_pnl_percent=-5.5)

        result = await validator.validate_order(order, account_state)

        assert result.is_blocked is True
        assert "daily" in (result.blocked_by_rule or "").lower()


class TestMaxDrawdownBlocking:
    """Tests for order blocked when max drawdown exceeded (AC3)."""

    @pytest.fixture
    def ftmo_engine(self):
        """Create RuleEngine with FTMO rules."""
        # Story 10.13: preset loader replaced by _load_preset_rules
        
        rules = _load_preset_rules("ftmo")
        return RuleEngine(account_id="test-account", rules=rules)

    @pytest.fixture
    def redis_mock(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_order_blocked_at_10_percent_drawdown(self, ftmo_engine, redis_mock):
        """Test order is blocked when drawdown is at 10%."""
        validator = OrderValidator(ftmo_engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state(total_drawdown_percent=10.0)

        result = await validator.validate_order(order, account_state)

        assert result.is_blocked is True

    @pytest.mark.asyncio
    async def test_order_blocked_above_10_percent_drawdown(
        self, ftmo_engine, redis_mock
    ):
        """Test order is blocked when drawdown exceeds 10%."""
        validator = OrderValidator(ftmo_engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state(total_drawdown_percent=11.0)

        result = await validator.validate_order(order, account_state)

        assert result.is_blocked is True
        assert "drawdown" in (result.blocked_by_rule or "").lower()


class TestPositionSizeBlocking:
    """Tests for order blocked when position size too large (AC3).

    Note: MaxPositionSizeRule expects 'account_balance' and 'requested_lots'
    fields in the context. The RuleContextBuilder passes 'current_balance'
    but not 'account_balance'. This test validates the rule directly, showing
    the integration works when context is correctly formed.
    """

    @pytest.fixture
    def ftmo_engine(self):
        """Create RuleEngine with FTMO rules."""
        # Story 10.13: preset loader replaced by _load_preset_rules
        
        rules = _load_preset_rules("ftmo")
        return RuleEngine(account_id="test-account", rules=rules)

    @pytest.mark.asyncio
    async def test_large_position_blocked_direct_context(self, ftmo_engine):
        """Test very large position is blocked (using direct context).

        This test validates the rule engine behavior directly since the
        OrderValidator's context builder may not pass all required fields
        for position size validation.

        FTMO preset: max_lots=100 with per_10k_balance scaling.
        For $10k account: 100 * (10000/10000) = 100 lots max.
        Requesting 150 lots should be blocked.
        """
        # Test the RuleEngine directly with correct context format
        # On $10k account, max is 100 * 1 = 100 lots
        context = {
            "daily_pnl_percent": 0.0,
            "total_drawdown_percent": 0.0,
            "requested_lots": 150.0,  # Over 100 lot limit
            "current_position_lots": 0.0,
            "account_balance": 10000.0,  # $10k = 100 lots max with scaling
            "total_pnl_percent": 0.0,
            "trading_days_count": 2,
        }

        result = ftmo_engine.validate(context)

        assert result.is_blocked is True
        assert "position" in (result.blocked_by.rule_type if result.blocked_by else "").lower()


class TestWarningsFromInformationalRules:
    """Tests for order allowed with warnings from informational rules (AC4).

    Note: Informational rules (profit_target, min_trading_days) return WARN
    when their targets are met. These are informational notifications, not
    blocking warnings.
    """

    @pytest.fixture
    def ftmo_engine(self):
        """Create RuleEngine with FTMO rules."""
        # Story 10.13: preset loader replaced by _load_preset_rules
        
        rules = _load_preset_rules("ftmo")
        return RuleEngine(account_id="test-account", rules=rules)

    @pytest.fixture
    def redis_mock(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_order_allowed_with_profit_target_met(
        self, ftmo_engine, redis_mock
    ):
        """Test order is allowed when profit target is met.

        Note: The RuleContextBuilder may not pass all fields needed for
        informational rules. This test validates the rule engine directly.
        """
        # Test the RuleEngine directly with correct context format
        context = {
            "daily_pnl_percent": 0.0,
            "total_drawdown_percent": 0.0,
            "requested_lots": 0.1,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": 10.0,  # Profit target met
            "trading_days_count": 2,
        }

        result = ftmo_engine.validate(context)

        # Should be allowed (informational rules don't block)
        assert result.is_allowed is True
        # Should have warning for profit target met
        assert result.has_warnings is True

    @pytest.mark.asyncio
    async def test_order_allowed_with_min_days_warning(self, ftmo_engine, redis_mock):
        """Test order is allowed with min trading days warning."""
        validator = OrderValidator(ftmo_engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()
        account_state["trading_days_count"] = 4  # Min days met

        result = await validator.validate_order(order, account_state)

        # Should be allowed
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_approaching_limit_generates_warning(self, ftmo_engine, redis_mock):
        """Test approaching daily loss limit generates warning."""
        validator = OrderValidator(ftmo_engine, redis_mock)
        order = create_test_order()
        # 70% of 5% limit = 3.5% loss
        account_state = create_test_account_state(daily_pnl_percent=-3.5)

        result = await validator.validate_order(order, account_state)

        # Should be allowed with warning
        assert result.allowed is True
        assert result.has_warnings is True


class TestValidatedZmqAdapterIntegration:
    """Tests for ValidatedZmqAdapter integration (AC1-4)."""

    @pytest.fixture
    def setup_validated_adapter(self):
        """Set up ValidatedZmqAdapter with mocks."""
        # Create FTMO engine
        # Story 10.13: preset loader replaced by _load_preset_rules
        
        rules = _load_preset_rules("ftmo")
        engine = RuleEngine(account_id="test-account", rules=rules)

        # Create mocks
        redis_mock = AsyncMock()
        zmq_adapter_mock = AsyncMock(spec=ZmqAdapter)
        zmq_adapter_mock.is_connected = True

        # Create mock RiskStateRegistry
        registry_mock = MagicMock(spec=RiskStateRegistry)
        risk_state = RiskState(
            daily_pnl=Decimal("0"),
            daily_pnl_percent=Decimal("0"),
            current_equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            total_drawdown_percent=Decimal("0"),
            daily_starting_balance=Decimal("100000"),
        )
        registry_mock.get_risk_state.return_value = risk_state

        # Create validator and adapter
        validator = OrderValidator(engine, redis_mock)
        validated_adapter = ValidatedZmqAdapter(zmq_adapter_mock, validator, registry_mock)

        return {
            "adapter": validated_adapter,
            "zmq_mock": zmq_adapter_mock,
            "registry_mock": registry_mock,
            "redis_mock": redis_mock,
            "risk_state": risk_state,
        }

    @pytest.mark.asyncio
    async def test_compliant_order_sent_to_zmq(self, setup_validated_adapter):
        """Test compliant order is forwarded to ZmqAdapter."""
        adapter = setup_validated_adapter["adapter"]
        zmq_mock = setup_validated_adapter["zmq_mock"]

        order = create_test_order()

        await adapter.send_order(order)

        # Verify order was sent to ZmqAdapter
        zmq_mock.send_order.assert_called_once_with(order)

    @pytest.mark.asyncio
    async def test_blocked_order_not_sent(self, setup_validated_adapter):
        """Test blocked order is NOT sent to ZmqAdapter."""
        adapter = setup_validated_adapter["adapter"]
        zmq_mock = setup_validated_adapter["zmq_mock"]
        risk_state = setup_validated_adapter["risk_state"]

        # Set daily loss to trigger block
        risk_state.daily_pnl_percent = Decimal("-5.5")

        order = create_test_order()

        with pytest.raises(OrderBlockedError):
            await adapter.send_order(order)

        # Verify order was NOT sent
        zmq_mock.send_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_blocked_order_raises_correct_exception(self, setup_validated_adapter):
        """Test blocked order raises OrderBlockedError with details."""
        adapter = setup_validated_adapter["adapter"]
        risk_state = setup_validated_adapter["risk_state"]

        # Set daily loss to trigger block
        risk_state.daily_pnl_percent = Decimal("-5.5")

        order = create_test_order()

        with pytest.raises(OrderBlockedError) as exc_info:
            await adapter.send_order(order)

        error = exc_info.value
        assert error.blocked_by_rule is not None
        assert error.reason is not None

    @pytest.mark.asyncio
    async def test_send_order_and_wait_validates_first(self, setup_validated_adapter):
        """Test send_order_and_wait validates before sending."""
        adapter = setup_validated_adapter["adapter"]
        zmq_mock = setup_validated_adapter["zmq_mock"]
        zmq_mock.send_order_and_wait.return_value = MagicMock(is_filled=True)

        order = create_test_order()

        await adapter.send_order_and_wait(order)

        # Verify validation happened and order was sent
        zmq_mock.send_order_and_wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_order_and_wait_blocked_not_sent(self, setup_validated_adapter):
        """Test send_order_and_wait doesn't send when blocked."""
        adapter = setup_validated_adapter["adapter"]
        zmq_mock = setup_validated_adapter["zmq_mock"]
        risk_state = setup_validated_adapter["risk_state"]

        # Set drawdown to trigger block
        risk_state.total_drawdown_percent = Decimal("11.0")

        order = create_test_order()

        with pytest.raises(OrderBlockedError):
            await adapter.send_order_and_wait(order)

        # Verify order was NOT sent
        zmq_mock.send_order_and_wait.assert_not_called()


class TestValidationPerformance:
    """Tests for validation performance (AC6)."""

    @pytest.fixture
    def ftmo_engine(self):
        """Create RuleEngine with FTMO rules."""
        # Story 10.13: preset loader replaced by _load_preset_rules
        
        rules = _load_preset_rules("ftmo")
        return RuleEngine(account_id="test-account", rules=rules)

    @pytest.fixture
    def redis_mock(self):
        """Create mock Redis client that returns immediately."""
        mock = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_single_validation_under_50ms(self, ftmo_engine, redis_mock):
        """Test single validation completes in < 50ms (AC6)."""
        validator = OrderValidator(ftmo_engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.evaluation_time_ms < 50.0

    @pytest.mark.asyncio
    async def test_100_validations_under_5_seconds(self, ftmo_engine, redis_mock):
        """Test 100 validations complete in < 5 seconds."""
        validator = OrderValidator(ftmo_engine, redis_mock)
        account_state = create_test_account_state()

        start_time = time.perf_counter()

        for i in range(100):
            order = create_test_order(order_id=f"order-{i}")
            await validator.validate_order(order, account_state)

        elapsed = time.perf_counter() - start_time

        assert elapsed < 5.0, f"100 validations took {elapsed:.2f}s (limit: 5s)"

    @pytest.mark.asyncio
    async def test_average_validation_time(self, ftmo_engine, redis_mock):
        """Test average validation time is reasonable."""
        validator = OrderValidator(ftmo_engine, redis_mock)
        account_state = create_test_account_state()
        times = []

        for i in range(100):
            order = create_test_order(order_id=f"order-{i}")
            result = await validator.validate_order(order, account_state)
            times.append(result.evaluation_time_ms)

        avg_time = sum(times) / len(times)

        # Average should be well under 50ms (typically < 5ms)
        assert avg_time < 50.0, f"Average validation time: {avg_time:.2f}ms"

        # Log for visibility
        print("\nValidation Performance:")
        print(f"  Average: {avg_time:.3f}ms")
        print(f"  Min: {min(times):.3f}ms")
        print(f"  Max: {max(times):.3f}ms")


class TestValidationWithNoRiskState:
    """Tests for validation when RiskState is not available."""

    @pytest.fixture
    def setup_adapter_no_risk_state(self):
        """Set up ValidatedZmqAdapter with no risk state."""
        # Create FTMO engine
        # Story 10.13: preset loader replaced by _load_preset_rules
        
        rules = _load_preset_rules("ftmo")
        engine = RuleEngine(account_id="test-account", rules=rules)

        # Create mocks
        redis_mock = AsyncMock()
        zmq_adapter_mock = AsyncMock(spec=ZmqAdapter)
        zmq_adapter_mock.is_connected = True

        # Create mock RiskStateRegistry that returns None
        registry_mock = MagicMock(spec=RiskStateRegistry)
        registry_mock.get_risk_state.return_value = None

        # Create validator and adapter
        validator = OrderValidator(engine, redis_mock)
        validated_adapter = ValidatedZmqAdapter(zmq_adapter_mock, validator, registry_mock)

        return {
            "adapter": validated_adapter,
            "zmq_mock": zmq_adapter_mock,
        }

    @pytest.mark.asyncio
    async def test_no_risk_state_uses_minimal_state(self, setup_adapter_no_risk_state):
        """Test validation proceeds with minimal state when no risk state available."""
        adapter = setup_adapter_no_risk_state["adapter"]

        order = create_test_order()

        # Should not raise - minimal state is used
        # May be blocked or allowed depending on how minimal state is evaluated
        try:
            await adapter.send_order(order)
        except OrderBlockedError:
            # Blocked due to minimal state is acceptable
            pass

        # Test completed without unexpected errors


class TestPositionSizeViaAdapter:
    """Tests for position size blocking through ValidatedZmqAdapter (Review fix MEDIUM-1)."""

    @pytest.fixture
    def setup_position_test_adapter(self):
        """Set up ValidatedZmqAdapter for position size testing."""
        # Create FTMO engine
        # Story 10.13: preset loader replaced by _load_preset_rules
        
        rules = _load_preset_rules("ftmo")
        engine = RuleEngine(account_id="test-account", rules=rules)

        # Create mocks
        redis_mock = AsyncMock()
        zmq_adapter_mock = AsyncMock(spec=ZmqAdapter)
        zmq_adapter_mock.is_connected = True

        # Create mock RiskStateRegistry with $10k balance
        # FTMO preset: max_lots=100 with per_10k_balance scaling
        # For $10k account: 100 * (10000/10000) = 100 lots max
        registry_mock = MagicMock(spec=RiskStateRegistry)
        risk_state = RiskState(
            daily_pnl=Decimal("0"),
            daily_pnl_percent=Decimal("0"),
            current_equity=Decimal("10000"),
            peak_equity=Decimal("10000"),
            total_drawdown_percent=Decimal("0"),
            daily_starting_balance=Decimal("10000"),
        )
        registry_mock.get_risk_state.return_value = risk_state

        # Create validator and adapter
        validator = OrderValidator(engine, redis_mock)
        validated_adapter = ValidatedZmqAdapter(zmq_adapter_mock, validator, registry_mock)

        return {
            "adapter": validated_adapter,
            "zmq_mock": zmq_adapter_mock,
            "risk_state": risk_state,
        }

    @pytest.mark.asyncio
    async def test_large_position_blocked_via_adapter(self, setup_position_test_adapter):
        """Test oversized position is blocked through full adapter flow.

        On $10k account with FTMO preset:
        - max_lots=100 with per_10k_balance scaling
        - 100 * (10000/10000) = 100 lots max
        - Order for 150 lots should be blocked
        """
        adapter = setup_position_test_adapter["adapter"]
        zmq_mock = setup_position_test_adapter["zmq_mock"]

        # Create order with 150 lots (over 100 lot limit for $10k account)
        order = create_test_order(volume=150.0)

        with pytest.raises(OrderBlockedError) as exc_info:
            await adapter.send_order(order)

        # Verify order was NOT sent to ZMQ
        zmq_mock.send_order.assert_not_called()

        # Verify error contains position-related info
        error = exc_info.value
        assert error.blocked_by_rule is not None

    @pytest.mark.asyncio
    async def test_valid_position_allowed_via_adapter(self, setup_position_test_adapter):
        """Test valid position size is allowed through adapter."""
        adapter = setup_position_test_adapter["adapter"]
        zmq_mock = setup_position_test_adapter["zmq_mock"]

        # Create order with 50 lots (under 100 lot limit)
        order = create_test_order(volume=50.0)

        await adapter.send_order(order)

        # Verify order was sent
        zmq_mock.send_order.assert_called_once_with(order)


class TestWarningsWithBlock:
    """Tests for warnings being captured even when BLOCK occurs (Review fix MEDIUM-2)."""

    @pytest.fixture
    def ftmo_engine(self):
        """Create RuleEngine with FTMO rules."""
        # Story 10.13: preset loader replaced by _load_preset_rules
        
        rules = _load_preset_rules("ftmo")
        return RuleEngine(account_id="test-account", rules=rules)

    @pytest.fixture
    def redis_mock(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_warnings_captured_with_block(self, ftmo_engine, redis_mock):
        """Test that warnings are captured for audit even when BLOCK occurs.

        Uses continue_after_block=True to ensure we see both warnings and blocks.
        """
        # Test with daily loss at 5% (BLOCK) and drawdown at 7% (approaching WARN threshold)
        context = {
            "daily_pnl_percent": -5.0,  # At limit - BLOCK
            "total_drawdown_percent": 7.0,  # Approaching 10% limit - may WARN
            "requested_lots": 0.1,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": 0.0,
            "trading_days_count": 2,
        }

        # Evaluate with continue_after_block to see all results
        result = ftmo_engine.validate(context, continue_after_block=True)

        # Should be blocked
        assert result.is_blocked is True
        assert result.blocked_by is not None

        # Verify we can still access all_results for audit
        assert len(result.all_results) >= 1

        # Log results for visibility
        print("\nRule Results with BLOCK:")
        for rule, rule_result in result.all_results:
            print(f"  {rule.name}: {rule_result.action.name} - {rule_result.message}")

    @pytest.mark.asyncio
    async def test_engine_result_properties_with_mixed_results(self, ftmo_engine):
        """Test RuleEngineResult properties correctly report mixed scenarios."""
        # Scenario: Approaching daily loss (WARN) + Over drawdown (BLOCK)
        context = {
            "daily_pnl_percent": -3.5,  # 70% of 5% limit - WARN
            "total_drawdown_percent": 11.0,  # Over 10% limit - BLOCK
            "requested_lots": 0.1,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": 0.0,
            "trading_days_count": 2,
        }

        result = ftmo_engine.validate(context, continue_after_block=True)

        # Should be blocked due to drawdown
        assert result.is_blocked is True
        assert "drawdown" in (result.blocked_by.rule_type if result.blocked_by else "").lower()

        # All 5 rules should have been evaluated
        assert len(result.all_results) == 5
