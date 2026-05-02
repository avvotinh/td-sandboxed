"""Tests for RuleEngine class (Story 4.1).

Tests cover:
- Priority ordering (lower priority first; stable sort for equal priorities)
- RuleEngine.validate() returns ALLOW when all rules pass
- RuleEngine.validate() returns BLOCK when any rule blocks
- Short-circuit behavior stops on first BLOCK
- Warning aggregation collects all WARNs
- Fail-safe: exception in rule = BLOCK result
"""

import pytest

from src.rules.base_rule import RuleAction, RuleResult
from src.rules.engine import RuleEngine, RuleValidationError


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
    ):
        self.rule_type = rule_type
        self.name = name
        self.priority = priority
        self._action = action
        self._message = message
        self._should_raise = should_raise
        self.validate_called = False
        self.validate_call_count = 0

    def validate(self, context: dict) -> RuleResult:
        """Return configured result or raise exception."""
        self.validate_called = True
        self.validate_call_count += 1
        if self._should_raise:
            raise ValueError("Test exception")
        return RuleResult(
            action=self._action,
            message=self._message,
        )

    def get_current_value(self, context: dict) -> float:
        return 0.0

    def get_threshold(self) -> float:
        return 100.0

    def get_warning_thresholds(self) -> list[float]:
        return [70.0, 80.0, 90.0]


class TestRuleEnginePriorityOrdering:
    """Tests for rule priority ordering."""

    def test_rules_sorted_by_priority_ascending(self):
        """Test rules are sorted by priority (lower first)."""
        rule_high = MockRule(rule_type="high", priority=100)
        rule_low = MockRule(rule_type="low", priority=1)
        rule_mid = MockRule(rule_type="mid", priority=50)

        engine = RuleEngine("test-001", [rule_high, rule_low, rule_mid])
        rules = engine.get_rules()

        assert rules[0].rule_type == "low"
        assert rules[1].rule_type == "mid"
        assert rules[2].rule_type == "high"

    def test_equal_priority_maintains_insertion_order(self):
        """Test stable sort: equal priorities maintain insertion order."""
        rule_a = MockRule(rule_type="rule_a", priority=50)
        rule_b = MockRule(rule_type="rule_b", priority=50)
        rule_c = MockRule(rule_type="rule_c", priority=50)

        engine = RuleEngine("test-001", [rule_a, rule_b, rule_c])
        rules = engine.get_rules()

        # Should maintain original insertion order
        assert rules[0].rule_type == "rule_a"
        assert rules[1].rule_type == "rule_b"
        assert rules[2].rule_type == "rule_c"

    def test_default_priority_is_50(self):
        """Test rules without priority attribute default to 50."""

        class NoPriorityRule:
            rule_type = "no_priority"
            name = "No Priority Rule"

            def validate(self, context):
                return RuleResult(action=RuleAction.ALLOW)

            def get_current_value(self, context):
                return 0.0

            def get_threshold(self):
                return 100.0

            def get_warning_thresholds(self):
                return []

        rule_low = MockRule(priority=10)
        no_priority = NoPriorityRule()
        rule_high = MockRule(priority=100)

        engine = RuleEngine("test-001", [rule_high, no_priority, rule_low])
        rules = engine.get_rules()

        # Low (10) < no_priority (50) < high (100)
        assert rules[0].priority == 10
        assert rules[2].priority == 100

    def test_rule_count_property(self):
        """Test rule_count returns correct number of rules."""
        rules = [MockRule() for _ in range(5)]
        engine = RuleEngine("test-001", rules)
        assert engine.rule_count == 5

    def test_get_rules_returns_copy(self):
        """Test get_rules returns a copy, not the original list."""
        rules = [MockRule()]
        engine = RuleEngine("test-001", rules)

        returned_rules = engine.get_rules()
        returned_rules.append(MockRule())

        assert engine.rule_count == 1

    def test_get_rules_returns_sorted_list(self):
        """Test get_rules returns rules in sorted priority order."""
        rule_high = MockRule(rule_type="high", priority=100)
        rule_low = MockRule(rule_type="low", priority=1)
        rule_mid = MockRule(rule_type="mid", priority=50)

        engine = RuleEngine("test-001", [rule_high, rule_low, rule_mid])
        returned_rules = engine.get_rules()

        # Verify returned list is sorted by priority
        assert returned_rules[0].rule_type == "low"
        assert returned_rules[1].rule_type == "mid"
        assert returned_rules[2].rule_type == "high"

        # Verify priorities are in ascending order
        priorities = [r.priority for r in returned_rules]
        assert priorities == sorted(priorities)


class TestRuleEngineValidateAllow:
    """Tests for ALLOW results."""

    def test_validate_returns_allow_when_all_rules_pass(self):
        """Test ALLOW returned when all rules pass."""
        rules = [
            MockRule(action=RuleAction.ALLOW),
            MockRule(action=RuleAction.ALLOW),
            MockRule(action=RuleAction.ALLOW),
        ]
        engine = RuleEngine("test-001", rules)

        result = engine.validate({})

        assert result.action == RuleAction.ALLOW
        assert result.is_allowed
        assert not result.is_blocked
        assert result.blocked_by is None
        assert result.blocking_reason is None

    def test_validate_calls_all_rules(self):
        """Test all rules are called during validation."""
        rules = [MockRule(), MockRule(), MockRule()]
        engine = RuleEngine("test-001", rules)

        engine.validate({})

        for rule in rules:
            assert rule.validate_called

    def test_validate_records_all_results(self):
        """Test all results are recorded for audit."""
        rules = [MockRule(), MockRule(), MockRule()]
        engine = RuleEngine("test-001", rules)

        result = engine.validate({})

        assert len(result.all_results) == 3

    def test_validate_measures_time(self):
        """Test evaluation time is measured."""
        engine = RuleEngine("test-001", [MockRule()])

        result = engine.validate({})

        assert result.evaluation_time_ms >= 0


class TestRuleEngineValidateBlock:
    """Tests for BLOCK results."""

    def test_validate_returns_block_when_rule_blocks(self):
        """Test BLOCK returned when any rule blocks."""
        rules = [
            MockRule(action=RuleAction.ALLOW),
            MockRule(action=RuleAction.BLOCK, message="Test block"),
            MockRule(action=RuleAction.ALLOW),
        ]
        engine = RuleEngine("test-001", rules)

        result = engine.validate({})

        assert result.action == RuleAction.BLOCK
        assert result.is_blocked
        assert not result.is_allowed
        assert result.blocked_by is not None
        assert result.blocking_reason == "Test block"

    def test_block_captures_blocking_rule(self):
        """Test the blocking rule is captured."""
        block_rule = MockRule(rule_type="blocker", action=RuleAction.BLOCK)
        rules = [MockRule(), block_rule]
        engine = RuleEngine("test-001", rules)

        result = engine.validate({})

        assert result.blocked_by.rule_type == "blocker"

    def test_default_blocking_reason(self):
        """Test default blocking reason when no message provided."""
        block_rule = MockRule(rule_type="blocker", action=RuleAction.BLOCK)
        rules = [block_rule]
        engine = RuleEngine("test-001", rules)

        result = engine.validate({})

        assert "Blocked by blocker" in result.blocking_reason


class TestRuleEngineShortCircuit:
    """Tests for short-circuit evaluation."""

    def test_short_circuit_stops_on_block(self):
        """Test evaluation stops on first BLOCK."""
        rule1 = MockRule(priority=1, action=RuleAction.ALLOW)
        rule2 = MockRule(priority=2, action=RuleAction.BLOCK)
        rule3 = MockRule(priority=3, action=RuleAction.ALLOW)
        engine = RuleEngine("test-001", [rule1, rule2, rule3])

        engine.validate({})

        assert rule1.validate_called
        assert rule2.validate_called
        assert not rule3.validate_called  # Should not be called

    def test_continue_after_block_evaluates_all(self):
        """Test continue_after_block=True evaluates all rules."""
        rule1 = MockRule(priority=1, action=RuleAction.ALLOW)
        rule2 = MockRule(priority=2, action=RuleAction.BLOCK)
        rule3 = MockRule(priority=3, action=RuleAction.ALLOW)
        engine = RuleEngine("test-001", [rule1, rule2, rule3])

        engine.validate({}, continue_after_block=True)

        assert rule1.validate_called
        assert rule2.validate_called
        assert rule3.validate_called  # Should be called with continue_after_block

    def test_short_circuit_returns_partial_results(self):
        """Test partial results are returned on short-circuit."""
        rules = [
            MockRule(priority=1, action=RuleAction.ALLOW),
            MockRule(priority=2, action=RuleAction.BLOCK),
            MockRule(priority=3, action=RuleAction.ALLOW),
        ]
        engine = RuleEngine("test-001", rules)

        result = engine.validate({})

        # Only 2 rules evaluated before short-circuit
        assert len(result.all_results) == 2


class TestRuleEngineWarnings:
    """Tests for warning aggregation."""

    def test_warn_result_collected(self):
        """Test WARN results are collected."""
        rules = [
            MockRule(action=RuleAction.WARN, message="Warning 1"),
            MockRule(action=RuleAction.ALLOW),
        ]
        engine = RuleEngine("test-001", rules)

        result = engine.validate({})

        assert result.action == RuleAction.WARN
        assert result.has_warnings
        assert len(result.warnings) == 1
        assert result.warnings[0].message == "Warning 1"

    def test_multiple_warnings_collected(self):
        """Test multiple warnings are collected."""
        rules = [
            MockRule(action=RuleAction.WARN, message="Warning 1"),
            MockRule(action=RuleAction.WARN, message="Warning 2"),
            MockRule(action=RuleAction.ALLOW),
        ]
        engine = RuleEngine("test-001", rules)

        result = engine.validate({})

        assert len(result.warnings) == 2
        assert result.warning_messages == ["Warning 1", "Warning 2"]

    def test_warnings_collected_before_block(self):
        """Test warnings are collected even when block occurs later."""
        rules = [
            MockRule(priority=1, action=RuleAction.WARN, message="Warning"),
            MockRule(priority=2, action=RuleAction.BLOCK, message="Block"),
        ]
        engine = RuleEngine("test-001", rules)

        result = engine.validate({})

        assert result.is_blocked
        assert result.has_warnings
        assert len(result.warnings) == 1

    def test_warn_allows_trading(self):
        """Test WARN result still allows trading."""
        engine = RuleEngine(
            "test-001", [MockRule(action=RuleAction.WARN)]
        )

        result = engine.validate({})

        assert result.is_allowed


class TestRuleEngineFailSafe:
    """Tests for fail-safe error handling."""

    def test_exception_in_rule_causes_block_in_strict_mode(self):
        """Test exception in rule results in BLOCK when strict_mode=True."""
        error_rule = MockRule(rule_type="error_rule", should_raise=True)
        engine = RuleEngine("test-001", [error_rule], strict_mode=True)

        result = engine.validate({})

        assert result.is_blocked
        assert result.blocked_by is error_rule
        assert "Error in error_rule" in result.blocking_reason

    def test_exception_includes_error_details(self):
        """Test exception details are included in result."""
        error_rule = MockRule(should_raise=True)
        engine = RuleEngine("test-001", [error_rule], strict_mode=True)

        result = engine.validate({})

        # Check last result contains error metadata
        _, last_result = result.all_results[-1]
        assert "error" in last_result.metadata
        assert "Test exception" in last_result.metadata["error"]

    def test_non_strict_mode_continues_after_error(self):
        """Test non-strict mode doesn't block on error."""
        error_rule = MockRule(priority=1, should_raise=True)
        allow_rule = MockRule(priority=2, action=RuleAction.ALLOW)
        engine = RuleEngine("test-001", [error_rule, allow_rule], strict_mode=False)

        result = engine.validate({})

        # In non-strict mode, should continue to next rule
        assert allow_rule.validate_called
        # Final action depends on non-error rules
        assert result.action == RuleAction.ALLOW

    def test_strict_mode_is_default(self):
        """Test strict_mode is True by default."""
        engine = RuleEngine("test-001", [])
        assert engine.strict_mode is True


class TestRuleEngineAccountId:
    """Tests for account_id handling."""

    def test_account_id_stored(self):
        """Test account_id is stored correctly."""
        engine = RuleEngine("my-account", [])
        assert engine.account_id == "my-account"


class TestRuleValidationError:
    """Tests for RuleValidationError exception."""

    def test_exception_is_subclass_of_exception(self):
        """Test RuleValidationError is an Exception."""
        assert issubclass(RuleValidationError, Exception)

    def test_exception_can_be_raised(self):
        """Test RuleValidationError can be raised and caught."""
        with pytest.raises(RuleValidationError):
            raise RuleValidationError("Test error")
