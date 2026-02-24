"""Integration tests for rule violation tracking (Story 7.3).

Tests cover:
- Task 5: OrderValidator → ViolationService integration
- Task 7.9-7.12: End-to-end violation recording flow
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.execution.order_validator import OrderValidator, ValidationResult
from src.rules.base_rule import RuleAction, RuleResult
from src.rules.engine import RuleEngine, RuleEngineResult
from src.rules.violation import RuleViolation
from src.rules.violation_db_writer import ViolationDBWriter
from src.rules.violation_service import ViolationService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeRule:
    """Minimal rule satisfying BaseRule protocol."""

    def __init__(self, rule_type="daily_loss_limit", name="FTMO Daily Loss 5%", priority=1):
        self.rule_type = rule_type
        self.name = name
        self.priority = priority

    def validate(self, context):
        return RuleResult()

    def get_current_value(self, context):
        return 0.0

    def get_threshold(self):
        return 5.0

    def get_warning_thresholds(self):
        return [70.0, 80.0, 90.0]


class FakeOrder:
    """Minimal order object for OrderValidator."""

    def __init__(
        self,
        account_id="ftmo-gold-001",
        order_id="order-123",
        symbol="XAUUSD",
        volume=0.1,
        price=2650.0,
    ):
        self.account_id = account_id
        self.order_id = order_id
        self.symbol = symbol
        self.volume = volume
        self.price = price
        self.action = MagicMock()
        self.action.value = "buy"


ACCOUNT_ID = "ftmo-gold-001"


@pytest.fixture
def mock_violation_writer():
    """ViolationDBWriter mock that captures add_violation calls."""
    writer = AsyncMock(spec=ViolationDBWriter)
    writer.add_violation = AsyncMock()
    return writer


@pytest.fixture
def violation_service(mock_violation_writer):
    return ViolationService(mock_violation_writer)


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish = AsyncMock()
    return redis


@pytest.fixture
def block_rule():
    return FakeRule()


@pytest.fixture
def block_result(block_rule):
    return RuleResult(
        action=RuleAction.BLOCK,
        message="Trade blocked: daily loss 4.80% exceeds limit",
        current_value=4.8,
        threshold_value=5.0,
        metadata={"threshold_pct": 0.96},
    )


@pytest.fixture
def warn_rule():
    return FakeRule(rule_type="max_drawdown", name="FTMO Max Drawdown 10%")


@pytest.fixture
def warn_result(warn_rule):
    return RuleResult(
        action=RuleAction.WARN,
        message="Warning: drawdown at 85% of limit",
        current_value=8.5,
        threshold_value=10.0,
    )


@pytest.fixture
def allow_result():
    return RuleResult(action=RuleAction.ALLOW, message="OK")


# ===========================================================================
# Task 5 / 7.9: OrderValidator BLOCK → ViolationService
# ===========================================================================

class TestOrderValidatorBlockViolation:
    """7.9: OrderValidator BLOCK → ViolationService.record_block() → violation in buffer."""

    @pytest.mark.asyncio
    async def test_block_triggers_violation_recording(
        self, mock_redis, violation_service, mock_violation_writer, block_rule, block_result,
    ):
        """BLOCK result triggers ViolationService.record_block()."""
        # Set up RuleEngine mock
        rule_engine = MagicMock(spec=RuleEngine)
        engine_result = MagicMock(spec=RuleEngineResult)
        engine_result.is_blocked = True
        engine_result.has_warnings = False
        engine_result.blocked_by = block_rule
        engine_result.blocking_reason = block_result.message
        engine_result.all_results = [(block_rule, block_result)]
        rule_engine.validate.return_value = engine_result

        validator = OrderValidator(
            rule_engine=rule_engine,
            redis_client=mock_redis,
            violation_service=violation_service,
        )

        order = FakeOrder()
        result = await validator.validate_order(order, {"daily_loss_percent": 4.8})

        # Allow fire-and-forget tasks to complete
        await asyncio.sleep(0.05)

        assert result.is_blocked
        mock_violation_writer.add_violation.assert_awaited_once()
        violation = mock_violation_writer.add_violation.call_args[0][0]
        assert isinstance(violation, RuleViolation)
        assert violation.severity == "FATAL"
        assert violation.action_taken == "blocked"
        assert violation.order_blocked is True
        assert violation.account_id == ACCOUNT_ID


# ===========================================================================
# Task 5 / 7.10: OrderValidator WARN → ViolationService
# ===========================================================================

class TestOrderValidatorWarnViolation:
    """7.10: OrderValidator WARN → ViolationService.record_warning() → warning in buffer."""

    @pytest.mark.asyncio
    async def test_warn_triggers_violation_recording(
        self, mock_redis, violation_service, mock_violation_writer, warn_rule, warn_result,
    ):
        """WARN result triggers ViolationService.record_warning()."""
        rule_engine = MagicMock(spec=RuleEngine)
        engine_result = MagicMock(spec=RuleEngineResult)
        engine_result.is_blocked = False
        engine_result.has_warnings = True
        engine_result.warning_messages = [warn_result.message]
        engine_result.all_results = [(warn_rule, warn_result)]
        rule_engine.validate.return_value = engine_result

        validator = OrderValidator(
            rule_engine=rule_engine,
            redis_client=mock_redis,
            violation_service=violation_service,
        )

        order = FakeOrder()
        result = await validator.validate_order(order, {"drawdown_percent": 8.5})

        await asyncio.sleep(0.05)

        assert result.allowed
        mock_violation_writer.add_violation.assert_awaited_once()
        violation = mock_violation_writer.add_violation.call_args[0][0]
        assert violation.severity == "WARNING"  # 85% → WARNING
        assert violation.action_taken == "warned"
        assert violation.order_blocked is False


# ===========================================================================
# 7.11: Multiple violations create separate entries
# ===========================================================================

class TestMultipleViolations:
    """7.11: Multiple violations for same account create separate entries."""

    @pytest.mark.asyncio
    async def test_multiple_violations_separate_entries(
        self, mock_redis, violation_service, mock_violation_writer,
    ):
        """Two failing rules produce two separate violation entries."""
        rule1 = FakeRule(rule_type="daily_loss_limit", name="Daily Loss 5%")
        result1 = RuleResult(
            action=RuleAction.BLOCK,
            message="Daily loss exceeded",
            current_value=4.8,
            threshold_value=5.0,
        )

        rule2 = FakeRule(rule_type="max_drawdown", name="Max Drawdown 10%")
        result2 = RuleResult(
            action=RuleAction.WARN,
            message="Drawdown approaching limit",
            current_value=8.5,
            threshold_value=10.0,
        )

        rule_engine = MagicMock(spec=RuleEngine)
        engine_result = MagicMock(spec=RuleEngineResult)
        engine_result.is_blocked = True
        engine_result.has_warnings = True
        engine_result.blocked_by = rule1
        engine_result.blocking_reason = result1.message
        engine_result.all_results = [(rule1, result1), (rule2, result2)]
        rule_engine.validate.return_value = engine_result

        validator = OrderValidator(
            rule_engine=rule_engine,
            redis_client=mock_redis,
            violation_service=violation_service,
        )

        order = FakeOrder()
        await validator.validate_order(order, {})

        await asyncio.sleep(0.05)

        assert mock_violation_writer.add_violation.await_count == 2

        violations = [call[0][0] for call in mock_violation_writer.add_violation.call_args_list]
        rule_types = {v.rule_type for v in violations}
        assert "daily_loss_limit" in rule_types
        assert "max_drawdown" in rule_types


# ===========================================================================
# 7.12: Backward compatibility - ALLOW paths unaffected
# ===========================================================================

class TestBackwardCompatibility:
    """7.12: Existing ALLOW paths unaffected by violation tracking."""

    @pytest.mark.asyncio
    async def test_allow_does_not_trigger_violation(
        self, mock_redis, violation_service, mock_violation_writer,
    ):
        """ALLOW result does NOT trigger ViolationService."""
        rule = FakeRule()
        allow = RuleResult(action=RuleAction.ALLOW, message="OK")

        rule_engine = MagicMock(spec=RuleEngine)
        engine_result = MagicMock(spec=RuleEngineResult)
        engine_result.is_blocked = False
        engine_result.has_warnings = False
        engine_result.all_results = [(rule, allow)]
        rule_engine.validate.return_value = engine_result

        validator = OrderValidator(
            rule_engine=rule_engine,
            redis_client=mock_redis,
            violation_service=violation_service,
        )

        order = FakeOrder()
        result = await validator.validate_order(order, {})

        await asyncio.sleep(0.05)

        assert result.allowed
        mock_violation_writer.add_violation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_violation_service_still_works(self, mock_redis):
        """OrderValidator works without ViolationService (backward compat)."""
        rule = FakeRule()
        block = RuleResult(
            action=RuleAction.BLOCK,
            message="Blocked",
            current_value=4.8,
            threshold_value=5.0,
        )

        rule_engine = MagicMock(spec=RuleEngine)
        engine_result = MagicMock(spec=RuleEngineResult)
        engine_result.is_blocked = True
        engine_result.blocked_by = rule
        engine_result.blocking_reason = "Blocked"
        engine_result.all_results = [(rule, block)]
        rule_engine.validate.return_value = engine_result

        # No violation_service
        validator = OrderValidator(
            rule_engine=rule_engine,
            redis_client=mock_redis,
        )

        order = FakeOrder()
        result = await validator.validate_order(order, {})

        assert result.is_blocked

    @pytest.mark.asyncio
    async def test_signal_context_passed_to_violation(
        self, mock_redis, violation_service, mock_violation_writer,
    ):
        """Signal context from order is passed to violation."""
        rule = FakeRule()
        block = RuleResult(
            action=RuleAction.BLOCK,
            message="Blocked",
            current_value=4.8,
            threshold_value=5.0,
        )

        rule_engine = MagicMock(spec=RuleEngine)
        engine_result = MagicMock(spec=RuleEngineResult)
        engine_result.is_blocked = True
        engine_result.blocked_by = rule
        engine_result.blocking_reason = "Blocked"
        engine_result.all_results = [(rule, block)]
        rule_engine.validate.return_value = engine_result

        validator = OrderValidator(
            rule_engine=rule_engine,
            redis_client=mock_redis,
            violation_service=violation_service,
        )

        order = FakeOrder()
        await validator.validate_order(order, {})

        await asyncio.sleep(0.05)

        violation = mock_violation_writer.add_violation.call_args[0][0]
        assert violation.context["order_id"] == "order-123"
        assert violation.context["signal"] == "buy"
        assert violation.context["symbol"] == "XAUUSD"
        assert violation.context["size"] == 0.1
        assert violation.context["price"] == 2650.0
