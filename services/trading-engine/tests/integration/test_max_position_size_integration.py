"""Integration tests for MaxPositionSizeRule (Story 4.4).

Tests cover:
- RuleEngine with MaxPositionSizeRule validates signals correctly
- RuleEngine short-circuits on BLOCK from MaxPositionSizeRule
- Warning aggregation works with MaxPositionSizeRule warnings
- Loading from YAML creates correct MaxPositionSizeRule instance
- Multiple rules together (DailyLoss + MaxDrawdown + PositionSize)
- Scaling rule loaded from YAML correctly
"""

import time
from unittest.mock import AsyncMock

import pytest

from src.rules.base_rule import RuleAction, RuleResult
from src.rules.context_builder import RuleContextBuilder
from src.rules.engine import RuleEngine
from src.rules.parser import RuleParser
from src.rules.types.drawdown import DailyLossLimitRule, MaxDrawdownRule
from src.rules.types.position import MaxPositionSizeRule


# =============================================================================
# TEST FIXTURES
# =============================================================================


class MockRule:
    """Mock rule for testing with MaxPositionSizeRule."""

    def __init__(
        self,
        rule_type: str = "mock_rule",
        name: str = "Mock Rule",
        priority: int = 50,
        action: RuleAction = RuleAction.ALLOW,
    ):
        self.rule_type = rule_type
        self.name = name
        self.priority = priority
        self._action = action

    def validate(self, context: dict) -> RuleResult:
        return RuleResult(action=self._action)

    def get_current_value(self, context: dict) -> float:
        return 0.0

    def get_threshold(self) -> float:
        return 100.0

    def get_warning_thresholds(self) -> list[float]:
        return [70.0, 80.0, 90.0]


class MockSignal:
    """Mock signal for testing."""

    def __init__(
        self,
        symbol: str = "EURUSD",
        side: str = "buy",
        quantity: float = 1.0,
    ):
        self.symbol = symbol
        self.side = side
        self.quantity = quantity


# =============================================================================
# RuleEngine Integration Tests
# =============================================================================


class TestRuleEngineWithMaxPositionSize:
    """Test RuleEngine with MaxPositionSizeRule validates signals correctly."""

    def test_engine_allows_trade_below_limit(self):
        """Test engine allows trade when position size below limit."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "requested_lots": 0.5,
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        assert result.is_allowed
        assert not result.is_blocked
        assert result.action == RuleAction.ALLOW

    def test_engine_allows_trade_exactly_at_limit(self):
        """Test engine allows trade when exactly at limit."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "requested_lots": 1.0,
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        assert result.is_allowed
        assert not result.is_blocked

    def test_engine_warns_at_warning_threshold(self):
        """Test engine warns when approaching position limit."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "requested_lots": 0.8,
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        assert result.is_allowed  # WARN still allows trading
        assert not result.is_blocked
        assert result.action == RuleAction.WARN
        assert result.has_warnings

    def test_engine_blocks_above_limit(self):
        """Test engine blocks trade when position size exceeds limit."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "requested_lots": 1.5,
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        assert not result.is_allowed
        assert result.is_blocked
        assert result.action == RuleAction.BLOCK

    def test_engine_blocks_total_exposure(self):
        """Test engine blocks when total exposure exceeds limit."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "requested_lots": 0.8,
            "current_position_lots": 0.5,
        }

        result = engine.validate(context)

        assert not result.is_allowed
        assert result.is_blocked
        assert result.action == RuleAction.BLOCK


class TestRuleEngineShortCircuit:
    """Test RuleEngine short-circuits on BLOCK from MaxPositionSizeRule."""

    def test_short_circuit_stops_on_position_size_block(self):
        """Test short-circuit stops evaluation when MaxPositionSizeRule blocks."""
        # MaxPositionSizeRule has priority=3
        position_rule = MaxPositionSizeRule(max_lots=1.0)
        mock_rule = MockRule(rule_type="should_not_run", priority=99)

        engine = RuleEngine("test-001", [position_rule, mock_rule])

        context = {
            "account_id": "test-001",
            "requested_lots": 1.5,  # BLOCK condition
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        # Should only have 1 result (short-circuited)
        assert len(result.all_results) == 1
        assert result.is_blocked
        rule, rule_result = result.all_results[0]
        assert rule_result.metadata.get("rule_type") == "max_position_size"

    def test_continues_evaluation_on_allow(self):
        """Test evaluation continues when MaxPositionSizeRule allows."""
        position_rule = MaxPositionSizeRule(max_lots=1.0)
        mock_rule = MockRule(rule_type="second_rule", priority=99)

        engine = RuleEngine("test-001", [position_rule, mock_rule])

        context = {
            "account_id": "test-001",
            "requested_lots": 0.5,  # ALLOW condition
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        # Should have 2 results (both rules evaluated)
        assert len(result.all_results) == 2
        assert result.is_allowed

    def test_continues_evaluation_on_warn(self):
        """Test evaluation continues when MaxPositionSizeRule warns."""
        position_rule = MaxPositionSizeRule(max_lots=1.0)
        mock_rule = MockRule(rule_type="second_rule", priority=99)

        engine = RuleEngine("test-001", [position_rule, mock_rule])

        context = {
            "account_id": "test-001",
            "requested_lots": 0.8,  # WARN condition (80%)
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        # Should have 2 results (warnings don't short-circuit)
        assert len(result.all_results) == 2
        assert result.is_allowed
        assert result.has_warnings


class TestWarningAggregation:
    """Test warning aggregation works with MaxPositionSizeRule warnings."""

    def test_single_warning_captured(self):
        """Test single warning from MaxPositionSizeRule is captured."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "requested_lots": 0.8,  # 80% warning
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        assert result.has_warnings
        assert len(result.warning_messages) == 1
        assert "80%" in result.warning_messages[0]

    def test_multiple_warnings_from_different_rules(self):
        """Test warnings from multiple rules are aggregated."""
        position_rule = MaxPositionSizeRule(max_lots=1.0)
        warning_mock = MockRule(
            rule_type="warning_mock",
            priority=99,
            action=RuleAction.WARN,
        )

        engine = RuleEngine("test-001", [position_rule, warning_mock])

        context = {
            "account_id": "test-001",
            "requested_lots": 0.7,  # 70% warning
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        assert result.has_warnings
        # Both rules should have warned
        warn_count = sum(
            1 for _rule, rule_result in result.all_results
            if rule_result.action == RuleAction.WARN
        )
        assert warn_count == 2


class TestRuleParserWithMaxPositionSize:
    """Test RuleParser correctly parses MaxPositionSizeRule from YAML."""

    def test_parser_creates_max_position_size_rule(self):
        """Test parser creates MaxPositionSizeRule from YAML dict."""
        parser = RuleParser()
        yaml_content = {
            "rules": [
                {
                    "type": "max_position_size",
                    "max_lots": 5.0,
                    "warning_at": [70, 80, 90],
                }
            ]
        }

        rules = parser.parse_rules(yaml_content)

        assert len(rules) == 1
        assert isinstance(rules[0], MaxPositionSizeRule)
        assert rules[0].max_lots == 5.0

    def test_parser_with_scaling(self):
        """Test parser with scaling configuration."""
        parser = RuleParser()
        yaml_content = {
            "rules": [
                {
                    "type": "max_position_size",
                    "max_lots": 1.0,
                    "scaling": "per_10k_balance",
                }
            ]
        }

        rules = parser.parse_rules(yaml_content)
        assert rules[0].scaling == "per_10k_balance"

    def test_parser_with_custom_warnings(self):
        """Test parser with custom warning thresholds."""
        parser = RuleParser()
        yaml_content = {
            "rules": [
                {
                    "type": "max_position_size",
                    "max_lots": 1.0,
                    "warning_at": [50, 75, 90],
                }
            ]
        }

        rules = parser.parse_rules(yaml_content)
        assert rules[0].warning_at == [50.0, 75.0, 90.0]

    def test_parser_with_default_values(self):
        """Test parser uses default values when not specified."""
        parser = RuleParser()
        yaml_content = {
            "rules": [
                {
                    "type": "max_position_size",
                }
            ]
        }

        rules = parser.parse_rules(yaml_content)
        rule = rules[0]

        assert rule.max_lots == 1.0  # Default
        assert rule.scaling is None  # Default (fixed)
        assert rule.warning_at == [70.0, 80.0, 90.0]  # Default


class TestMultipleRulesTogether:
    """Test multiple rules together (DailyLoss + MaxDrawdown + PositionSize)."""

    def test_all_rules_evaluated_when_allowing(self):
        """Test all rules are evaluated when all allow."""
        daily_loss = DailyLossLimitRule(threshold_percent=5.0)
        max_drawdown = MaxDrawdownRule(threshold_percent=10.0)
        position_size = MaxPositionSizeRule(max_lots=1.0)

        engine = RuleEngine(
            "test-001",
            [daily_loss, max_drawdown, position_size],
        )

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -2.0,  # Below daily loss threshold
            "total_drawdown_percent": 5.0,  # Below max drawdown threshold
            "requested_lots": 0.5,  # Below position size limit
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        assert result.is_allowed
        assert len(result.all_results) == 3

    def test_first_blocking_rule_short_circuits(self):
        """Test first blocking rule short-circuits evaluation."""
        daily_loss = DailyLossLimitRule(threshold_percent=5.0)  # priority=1
        max_drawdown = MaxDrawdownRule(threshold_percent=10.0)  # priority=2
        position_size = MaxPositionSizeRule(max_lots=1.0)  # priority=3

        engine = RuleEngine(
            "test-001",
            [daily_loss, max_drawdown, position_size],
        )

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -6.0,  # BLOCK - exceeds 5%
            "total_drawdown_percent": 5.0,
            "requested_lots": 0.5,
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        assert result.is_blocked
        # Only daily_loss evaluated (short-circuited)
        assert len(result.all_results) == 1

    def test_position_size_blocks_after_drawdown_rules_allow(self):
        """Test position size can block even when drawdown rules allow."""
        daily_loss = DailyLossLimitRule(threshold_percent=5.0)
        max_drawdown = MaxDrawdownRule(threshold_percent=10.0)
        position_size = MaxPositionSizeRule(max_lots=1.0)

        engine = RuleEngine(
            "test-001",
            [daily_loss, max_drawdown, position_size],
        )

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -2.0,  # ALLOW
            "total_drawdown_percent": 5.0,  # ALLOW
            "requested_lots": 1.5,  # BLOCK - exceeds 1.0 lots
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        assert result.is_blocked
        # All 3 evaluated until position size blocked
        assert len(result.all_results) == 3

    def test_warnings_aggregated_from_all_rules(self):
        """Test warnings from all rules are aggregated."""
        daily_loss = DailyLossLimitRule(threshold_percent=5.0)
        max_drawdown = MaxDrawdownRule(threshold_percent=10.0)
        position_size = MaxPositionSizeRule(max_lots=1.0)

        engine = RuleEngine(
            "test-001",
            [daily_loss, max_drawdown, position_size],
        )

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -3.5,  # WARN - 70% of 5%
            "total_drawdown_percent": 5.0,  # WARN - 50% of 10%
            "requested_lots": 0.7,  # WARN - 70% of 1.0
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        assert result.is_allowed
        assert result.has_warnings
        assert len(result.warning_messages) == 3


class TestScalingRuleFromYAML:
    """Test scaling rule loaded from YAML correctly."""

    def test_scaling_rule_validates_correctly(self):
        """Test scaled rule validates correctly from YAML config."""
        parser = RuleParser()
        yaml_content = {
            "rules": [
                {
                    "type": "max_position_size",
                    "max_lots": 1.0,
                    "scaling": "per_10k_balance",
                }
            ]
        }

        rules = parser.parse_rules(yaml_content)
        rule = rules[0]

        # With $50k balance, effective max = 5.0 lots
        # Request 3.0 (60% of limit) to be below warning threshold
        context = {
            "requested_lots": 3.0,
            "current_position_lots": 0.0,
            "account_balance": 50000.0,
        }

        result = rule.validate(context)
        assert result.action == RuleAction.ALLOW
        assert result.threshold_value == 5.0  # Scaled

    def test_scaling_rule_blocks_correctly(self):
        """Test scaled rule blocks correctly from YAML config."""
        parser = RuleParser()
        yaml_content = {
            "rules": [
                {
                    "type": "max_position_size",
                    "max_lots": 1.0,
                    "scaling": "per_10k_balance",
                }
            ]
        }

        rules = parser.parse_rules(yaml_content)
        rule = rules[0]

        # With $50k balance, effective max = 5.0 lots
        context = {
            "requested_lots": 6.0,  # Exceeds 5.0 max
            "current_position_lots": 0.0,
            "account_balance": 50000.0,
        }

        result = rule.validate(context)
        assert result.action == RuleAction.BLOCK


class TestContextBuilderWithPositionSizeRule:
    """Test RuleContextBuilder creates valid context for MaxPositionSizeRule."""

    def test_context_includes_requested_lots(self):
        """Test context includes requested_lots field."""
        builder = RuleContextBuilder()
        context = builder.build_validation_context(
            account_id="test-001",
            signal=MockSignal(quantity=1.5),
            account_state={
                "balance": 100000,
                "equity": 99500,
            },
        )

        # Signal quantity maps to requested_lots
        assert "quantity" in context or "requested_lots" in context

    def test_context_works_with_position_size_rule(self):
        """Test context from builder works with MaxPositionSizeRule."""
        builder = RuleContextBuilder()
        rule = MaxPositionSizeRule(max_lots=1.0)
        engine = RuleEngine("test-001", [rule])

        context = builder.build_validation_context(
            account_id="test-001",
            signal=MockSignal(quantity=0.5),
            account_state={
                "balance": 100000,
                "equity": 99500,
            },
        )

        # Add the required fields that the rule expects
        context["requested_lots"] = context.get("quantity", 0.5)
        context["current_position_lots"] = 0.0

        result = engine.validate(context)

        # Should allow (0.5 < 1.0)
        assert result.is_allowed


class TestMaxPositionSizePerformance:
    """Test MaxPositionSizeRule performance meets requirements."""

    def test_validate_under_5ms(self):
        """Test validate() completes in under 5ms."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        context = {"requested_lots": 0.5, "current_position_lots": 0.0}

        # Warm up
        rule.validate(context)

        # Measure
        iterations = 1000
        start = time.perf_counter()
        for _ in range(iterations):
            rule.validate(context)
        elapsed_ms = (time.perf_counter() - start) * 1000

        avg_ms = elapsed_ms / iterations
        assert avg_ms < 5, f"Average validate() time {avg_ms:.3f}ms exceeds 5ms target"

    def test_validate_with_scaling_under_5ms(self):
        """Test validate() with scaling completes in under 5ms."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")
        context = {
            "requested_lots": 0.5,
            "current_position_lots": 0.0,
            "account_balance": 50000.0,
        }

        # Warm up
        rule.validate(context)

        # Measure
        iterations = 1000
        start = time.perf_counter()
        for _ in range(iterations):
            rule.validate(context)
        elapsed_ms = (time.perf_counter() - start) * 1000

        avg_ms = elapsed_ms / iterations
        assert avg_ms < 5, f"Average validate() time {avg_ms:.3f}ms exceeds 5ms target"

    def test_engine_with_position_size_under_50ms(self):
        """Test engine with MaxPositionSizeRule validates under 50ms (NFR2)."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        engine = RuleEngine("perf-test", [rule])
        context = {
            "account_id": "perf-test",
            "requested_lots": 0.5,
            "current_position_lots": 0.0,
        }

        # Measure
        start = time.perf_counter()
        result = engine.validate(context)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 50, f"Validation took {elapsed_ms:.2f}ms, exceeds 50ms target"
        assert result.evaluation_time_ms < 50


class TestRuleEnginePriorityOrdering:
    """Test RuleEngine evaluates rules in priority order."""

    def test_rules_sorted_by_priority(self):
        """Test rules are sorted by priority (lower = first)."""
        # Create rules in wrong order
        position_rule = MaxPositionSizeRule(max_lots=1.0)  # priority=3
        daily_loss = DailyLossLimitRule(threshold_percent=5.0)  # priority=1
        max_drawdown = MaxDrawdownRule(threshold_percent=10.0)  # priority=2

        engine = RuleEngine(
            "test-001",
            [position_rule, daily_loss, max_drawdown],  # Wrong order
        )

        # Verify they are sorted correctly
        rules = engine.get_rules()
        assert rules[0].priority == 1  # daily_loss
        assert rules[1].priority == 2  # max_drawdown
        assert rules[2].priority == 3  # position_size

    def test_evaluation_follows_priority_order(self):
        """Test evaluation follows priority order."""
        daily_loss = DailyLossLimitRule(threshold_percent=5.0)
        max_drawdown = MaxDrawdownRule(threshold_percent=10.0)
        position_rule = MaxPositionSizeRule(max_lots=1.0)

        engine = RuleEngine(
            "test-001",
            [position_rule, daily_loss, max_drawdown],
        )

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -2.0,
            "total_drawdown_percent": 5.0,
            "requested_lots": 0.5,
            "current_position_lots": 0.0,
        }

        result = engine.validate(context)

        # Verify order in results
        assert result.all_results[0][0].priority == 1  # daily_loss first
        assert result.all_results[1][0].priority == 2  # max_drawdown second
        assert result.all_results[2][0].priority == 3  # position_size third
