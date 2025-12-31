"""Tests for OrderValidator class (Story 4.6).

Tests cover:
- validate_order() returns allowed=True when all rules pass (AC2)
- validate_order() returns allowed=False when any rule blocks (AC3)
- validate_order() returns allowed=True with warnings when WARN only (AC4)
- Mixed BLOCK and WARN: BLOCK wins (AC3)
- Fail-safe: exception in rule = allowed=False (AC5)
- Fail-safe: missing context field = allowed=False (AC5)
- Notification publisher called on BLOCK (AC3)
- Notification publisher called on WARN (AC4)
- Performance timing is recorded (AC6)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.zmq_models import Order, OrderSide
from src.execution.order_validator import OrderValidator, ValidationResult
from src.rules.base_rule import RuleAction, RuleResult
from src.rules.engine import RuleEngine


class MockRule:
    """Mock rule for testing."""

    def __init__(
        self,
        rule_type: str = "mock_rule",
        name: str = "Mock Rule",
        priority: int = 50,
        action: RuleAction = RuleAction.ALLOW,
        message: str | None = None,
        should_raise: bool = False,
        current_value: float | None = None,
        threshold_value: float | None = None,
    ):
        self.rule_type = rule_type
        self.name = name
        self.priority = priority
        self._action = action
        self._message = message
        self._should_raise = should_raise
        self._current_value = current_value
        self._threshold_value = threshold_value

    def validate(self, context: dict) -> RuleResult:
        """Return configured result or raise exception."""
        if self._should_raise:
            raise ValueError("Test exception")
        return RuleResult(
            action=self._action,
            message=self._message,
            current_value=self._current_value,
            threshold_value=self._threshold_value,
        )

    def get_current_value(self, context: dict) -> float:
        return self._current_value or 0.0

    def get_threshold(self) -> float:
        return self._threshold_value or 100.0

    def get_warning_thresholds(self) -> list[float]:
        return [70.0, 80.0, 90.0]


def create_test_order(
    account_id: str = "test-account",
    symbol: str = "XAUUSD",
    volume: float = 0.1,
) -> Order:
    """Create a test order."""
    return Order(
        account_id=account_id,
        action=OrderSide.BUY,
        symbol=symbol,
        volume=volume,
        price=2000.0,
        order_id="order-001",
    )


def create_test_account_state() -> dict:
    """Create a test account state."""
    return {
        "balance": 100000.0,
        "equity": 99500.0,
        "initial_balance": 100000.0,
        "peak_balance": 100000.0,
        "daily_pnl": -500.0,
        "daily_pnl_percent": -0.5,
        "total_drawdown_percent": 0.5,
        "open_positions_count": 1,
        "total_exposure": 0.1,
    }


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_allowed_true_properties(self):
        """Test properties when allowed=True."""
        result = ValidationResult(allowed=True)

        assert result.allowed is True
        assert result.is_blocked is False
        assert result.has_warnings is False

    def test_allowed_false_properties(self):
        """Test properties when allowed=False."""
        result = ValidationResult(allowed=False, reason="Test block")

        assert result.allowed is False
        assert result.is_blocked is True
        assert result.has_warnings is False

    def test_has_warnings_property(self):
        """Test has_warnings property."""
        result = ValidationResult(allowed=True, warnings=["Warning 1", "Warning 2"])

        assert result.has_warnings is True

    def test_empty_warnings_property(self):
        """Test has_warnings is False when no warnings."""
        result = ValidationResult(allowed=True)

        assert result.has_warnings is False

    def test_to_log_dict(self):
        """Test to_log_dict returns correct structure."""
        result = ValidationResult(
            allowed=False,
            reason="Daily loss limit exceeded",
            warnings=["Approaching limit"],
            evaluation_time_ms=15.5,
            blocked_by_rule="daily_loss_limit",
            current_value=4.8,
            threshold_value=5.0,
        )

        log_dict = result.to_log_dict()

        assert log_dict["allowed"] is False
        assert log_dict["reason"] == "Daily loss limit exceeded"
        assert log_dict["warnings"] == ["Approaching limit"]
        assert log_dict["evaluation_time_ms"] == 15.5
        assert log_dict["blocked_by_rule"] == "daily_loss_limit"
        assert log_dict["current_value"] == 4.8
        assert log_dict["threshold_value"] == 5.0


class TestOrderValidatorAllRulesPass:
    """Tests for validate_order() when all rules pass (AC2)."""

    @pytest.mark.asyncio
    async def test_returns_allowed_true(self):
        """Test returns allowed=True when all rules pass."""
        rules = [
            MockRule(action=RuleAction.ALLOW),
            MockRule(action=RuleAction.ALLOW),
        ]
        engine = RuleEngine("test-account", rules)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.allowed is True
        assert result.is_blocked is False
        assert result.reason is None
        assert result.blocked_by_rule is None

    @pytest.mark.asyncio
    async def test_no_notifications_published(self):
        """Test no notifications published when all rules pass."""
        rules = [MockRule(action=RuleAction.ALLOW)]
        engine = RuleEngine("test-account", rules)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        await validator.validate_order(order, account_state)

        # Give async task time to run
        await asyncio.sleep(0.01)

        # No publish calls for ALLOW without warnings
        redis_mock.publish.assert_not_called()


class TestOrderValidatorBlockRule:
    """Tests for validate_order() when any rule blocks (AC3)."""

    @pytest.mark.asyncio
    async def test_returns_allowed_false(self):
        """Test returns allowed=False when any rule blocks."""
        rules = [
            MockRule(action=RuleAction.ALLOW),
            MockRule(
                name="Daily Loss Limit 5%",
                action=RuleAction.BLOCK,
                message="Daily loss 4.8% exceeds limit 5%",
                current_value=4.8,
                threshold_value=5.0,
            ),
        ]
        engine = RuleEngine("test-account", rules)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.allowed is False
        assert result.is_blocked is True
        assert "Daily loss 4.8% exceeds limit 5%" in result.reason
        assert result.blocked_by_rule == "Daily Loss Limit 5%"
        assert result.current_value == 4.8
        assert result.threshold_value == 5.0

    @pytest.mark.asyncio
    async def test_block_notification_published(self):
        """Test BLOCK notification is published to Redis."""
        rules = [
            MockRule(
                name="Daily Loss Limit",
                action=RuleAction.BLOCK,
                message="Blocked",
            ),
        ]
        engine = RuleEngine("test-account", rules)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order(account_id="ftmo-001")
        account_state = create_test_account_state()

        await validator.validate_order(order, account_state)

        # Give async task time to run
        await asyncio.sleep(0.01)

        # Verify publish was called with correct channel
        redis_mock.publish.assert_called_once()
        call_args = redis_mock.publish.call_args
        assert call_args[0][0] == "alerts:risk:ftmo-001"


class TestOrderValidatorWarnOnly:
    """Tests for validate_order() with WARN rules only (AC4)."""

    @pytest.mark.asyncio
    async def test_returns_allowed_true_with_warnings(self):
        """Test returns allowed=True with warnings when WARN only."""
        rules = [
            MockRule(
                action=RuleAction.WARN,
                message="Approaching daily loss limit (70%)",
            ),
            MockRule(action=RuleAction.ALLOW),
        ]
        engine = RuleEngine("test-account", rules)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.allowed is True
        assert result.has_warnings is True
        assert "Approaching daily loss limit (70%)" in result.warnings

    @pytest.mark.asyncio
    async def test_warn_notification_published(self):
        """Test WARN notification is published to Redis."""
        rules = [
            MockRule(action=RuleAction.WARN, message="Warning"),
        ]
        engine = RuleEngine("test-account", rules)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order(account_id="ftmo-001")
        account_state = create_test_account_state()

        await validator.validate_order(order, account_state)

        # Give async task time to run
        await asyncio.sleep(0.01)

        # Verify publish was called
        redis_mock.publish.assert_called_once()
        call_args = redis_mock.publish.call_args
        assert call_args[0][0] == "alerts:risk:ftmo-001"


class TestOrderValidatorMixedBlockWarn:
    """Tests for mixed BLOCK and WARN rules."""

    @pytest.mark.asyncio
    async def test_block_wins_over_warn(self):
        """Test BLOCK takes precedence over WARN."""
        rules = [
            MockRule(
                priority=1,
                action=RuleAction.WARN,
                message="Warning",
            ),
            MockRule(
                priority=2,
                name="Blocker",
                action=RuleAction.BLOCK,
                message="Blocked",
            ),
        ]
        engine = RuleEngine("test-account", rules)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.allowed is False
        assert result.is_blocked is True
        assert result.blocked_by_rule == "Blocker"


class TestOrderValidatorFailSafe:
    """Tests for fail-safe error handling (AC5)."""

    @pytest.mark.asyncio
    async def test_exception_in_rule_returns_blocked(self):
        """Test exception in rule returns allowed=False (fail-safe)."""
        rules = [
            MockRule(rule_type="error_rule", should_raise=True),
        ]
        engine = RuleEngine("test-account", rules, strict_mode=True)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.allowed is False
        assert result.blocked_by_rule is not None

    @pytest.mark.asyncio
    async def test_missing_context_field_returns_blocked(self):
        """Test missing context field returns allowed=False (fail-safe)."""

        class ContextAccessingRule:
            rule_type = "accessor"
            name = "Context Accessor"
            priority = 50

            def validate(self, context: dict) -> RuleResult:
                # Access a field that doesn't exist
                _ = context["nonexistent_field"]
                return RuleResult(action=RuleAction.ALLOW)

            def get_current_value(self, context: dict) -> float:
                return 0.0

            def get_threshold(self) -> float:
                return 100.0

            def get_warning_thresholds(self) -> list[float]:
                return []

        engine = RuleEngine("test-account", [ContextAccessingRule()], strict_mode=True)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.allowed is False
        assert result.blocked_by_rule is not None

    @pytest.mark.asyncio
    async def test_type_error_returns_blocked(self):
        """Test TypeError returns allowed=False (fail-safe)."""

        class TypeErrorRule:
            rule_type = "type_error"
            name = "Type Error Rule"
            priority = 50

            def validate(self, context: dict) -> RuleResult:
                # Cause a TypeError
                _ = 1 + "string"
                return RuleResult(action=RuleAction.ALLOW)

            def get_current_value(self, context: dict) -> float:
                return 0.0

            def get_threshold(self) -> float:
                return 100.0

            def get_warning_thresholds(self) -> list[float]:
                return []

        engine = RuleEngine("test-account", [TypeErrorRule()], strict_mode=True)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.allowed is False
        assert result.blocked_by_rule is not None

    @pytest.mark.asyncio
    async def test_generic_exception_returns_blocked(self):
        """Test generic exception returns allowed=False (fail-safe)."""
        # Mock the RuleEngine to raise an exception
        engine = MagicMock(spec=RuleEngine)
        engine.validate.side_effect = RuntimeError("Unexpected error")
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.allowed is False
        assert "Validation error" in result.reason
        assert result.blocked_by_rule == "error"


class TestOrderValidatorPerformance:
    """Tests for performance timing (AC6)."""

    @pytest.mark.asyncio
    async def test_evaluation_time_recorded(self):
        """Test evaluation time is recorded in result."""
        rules = [MockRule(action=RuleAction.ALLOW)]
        engine = RuleEngine("test-account", rules)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.evaluation_time_ms >= 0

    @pytest.mark.asyncio
    async def test_evaluation_time_recorded_on_block(self):
        """Test evaluation time is recorded even on BLOCK."""
        rules = [MockRule(action=RuleAction.BLOCK, message="Blocked")]
        engine = RuleEngine("test-account", rules)
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.evaluation_time_ms >= 0

    @pytest.mark.asyncio
    async def test_evaluation_time_recorded_on_error(self):
        """Test evaluation time is recorded even on error."""
        engine = MagicMock(spec=RuleEngine)
        engine.validate.side_effect = RuntimeError("Error")
        redis_mock = AsyncMock()

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        result = await validator.validate_order(order, account_state)

        assert result.evaluation_time_ms >= 0


class TestOrderValidatorNotificationFailure:
    """Tests for notification failure handling."""

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_affect_result(self):
        """Test notification failure doesn't affect validation result."""
        rules = [MockRule(action=RuleAction.BLOCK, message="Blocked")]
        engine = RuleEngine("test-account", rules)
        redis_mock = AsyncMock()
        redis_mock.publish.side_effect = Exception("Redis error")

        validator = OrderValidator(engine, redis_mock)
        order = create_test_order()
        account_state = create_test_account_state()

        # Should not raise - notification is fire-and-forget
        result = await validator.validate_order(order, account_state)

        # Give async task time to fail
        await asyncio.sleep(0.01)

        # Result should still be correct
        assert result.allowed is False
        assert result.is_blocked is True
