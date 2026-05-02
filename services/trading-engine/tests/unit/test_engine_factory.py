"""Tests for RuleEngineFactory class (Story 4.1).

Tests cover:
- RuleEngineFactory creates valid engines
- Protocol validation
- Error handling for invalid rules
"""

import pytest

from src.rules.base_rule import RuleAction, RuleResult
from src.rules.engine import RuleEngine
from src.rules.engine_factory import RuleEngineFactory


class ValidMockRule:
    """Valid mock rule that implements BaseRule protocol."""

    def __init__(self, rule_type: str = "mock_rule"):
        self.rule_type = rule_type
        self.name = "Mock Rule"
        self.priority = 50

    def validate(self, context: dict) -> RuleResult:
        return RuleResult(action=RuleAction.ALLOW)

    def get_current_value(self, context: dict) -> float:
        return 0.0

    def get_threshold(self) -> float:
        return 100.0

    def get_warning_thresholds(self) -> list[float]:
        return [70.0, 80.0, 90.0]


class TestRuleEngineFactoryCreation:
    """Tests for factory creation."""

    def test_create_for_account_returns_rule_engine(self):
        """Test create_for_account returns a RuleEngine."""
        rules = [ValidMockRule()]

        engine = RuleEngineFactory.create_for_account("test-001", rules)

        assert isinstance(engine, RuleEngine)

    def test_engine_has_correct_account_id(self):
        """Test created engine has correct account_id."""
        rules = [ValidMockRule()]

        engine = RuleEngineFactory.create_for_account("my-account", rules)

        assert engine.account_id == "my-account"

    def test_engine_has_all_rules(self):
        """Test created engine contains all provided rules."""
        rules = [ValidMockRule("rule1"), ValidMockRule("rule2")]

        engine = RuleEngineFactory.create_for_account("test", rules)

        assert engine.rule_count == 2

    def test_empty_rules_creates_engine(self):
        """Test factory creates engine even with empty rules list."""
        engine = RuleEngineFactory.create_for_account("test", [])

        assert engine.rule_count == 0

    def test_strict_mode_passed_to_engine(self):
        """Test strict_mode parameter is passed to engine."""
        engine = RuleEngineFactory.create_for_account(
            "test", [ValidMockRule()], strict_mode=False
        )

        assert engine.strict_mode is False

    def test_strict_mode_defaults_to_true(self):
        """Test strict_mode defaults to True."""
        engine = RuleEngineFactory.create_for_account("test", [ValidMockRule()])

        assert engine.strict_mode is True


class TestRuleEngineFactoryValidation:
    """Tests for protocol validation."""

    def test_validates_rule_type_attribute(self):
        """Test factory validates rule_type attribute exists."""

        class NoRuleType:
            name = "No Rule Type"
            priority = 50

            def validate(self, context):
                return RuleResult(action=RuleAction.ALLOW)

        with pytest.raises(TypeError) as exc_info:
            RuleEngineFactory.create_for_account("test", [NoRuleType()])

        # Factory should detect missing rule_type and raise TypeError
        assert "NoRuleType" in str(exc_info.value)

    def test_rejects_rule_missing_name_attribute(self):
        """Test factory rejects rule missing name attribute via protocol check."""

        class NoName:
            """Rule with all protocol methods but missing name attribute."""

            rule_type = "no_name_rule"
            priority = 50

            def validate(self, context):
                return RuleResult(action=RuleAction.ALLOW)

            def get_current_value(self, context):
                return 0.0

            def get_threshold(self):
                return 100.0

            def get_warning_thresholds(self):
                return [70.0, 80.0, 90.0]

        with pytest.raises(TypeError) as exc_info:
            RuleEngineFactory.create_for_account("test", [NoName()])

        # Factory rejects via isinstance check (protocol requires name attribute)
        assert "NoName" in str(exc_info.value)
        assert "BaseRule protocol" in str(exc_info.value)

    def test_accepts_valid_rule(self):
        """Test factory accepts valid rule without error."""
        valid_rule = ValidMockRule()

        # Should not raise
        engine = RuleEngineFactory.create_for_account("test", [valid_rule])
        assert engine is not None

    def test_error_includes_rule_index(self):
        """Test error message includes problematic rule index."""

        class InvalidRule:
            """Rule without rule_type."""

            name = "Invalid"

        with pytest.raises(TypeError) as exc_info:
            RuleEngineFactory.create_for_account(
                "test",
                [ValidMockRule(), InvalidRule()],  # Invalid at index 1
            )

        assert "index 1" in str(exc_info.value)

    def test_error_includes_rule_class_name(self):
        """Test error message includes rule class name."""

        class MyBadRule:
            """Rule without rule_type."""

            name = "Bad"

        with pytest.raises(TypeError) as exc_info:
            RuleEngineFactory.create_for_account("test", [MyBadRule()])

        assert "MyBadRule" in str(exc_info.value)


class TestRuleEngineFactoryStaticMethod:
    """Tests for factory being static."""

    def test_can_call_without_instance(self):
        """Test factory method can be called without instance."""
        # This should work without creating a RuleEngineFactory instance
        engine = RuleEngineFactory.create_for_account("test", [ValidMockRule()])
        assert engine is not None
