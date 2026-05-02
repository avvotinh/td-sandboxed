"""Unit tests for MinTradingDaysRule (Story 4.5).

Tests cover:
- ALLOW when below requirement (with progress info)
- WARN when requirement is met (notification)
- NEVER returns BLOCK (informational only)
- RuleResult includes current_value and threshold_value
- Protocol method implementations (get_current_value, get_threshold, get_warning_thresholds)
- Custom required_days configurations
- Integer and float input handling
"""

from decimal import Decimal

import pytest

from src.rules.base_rule import RuleAction
from src.rules.types.targets import MinTradingDaysRule


class TestMinTradingDaysRuleInit:
    """Tests for MinTradingDaysRule initialization."""

    def test_default_required_days_is_4(self):
        """Default required_days should be 4."""
        rule = MinTradingDaysRule()
        assert rule.required_days == 4

    def test_custom_required_days(self):
        """Custom required_days should be configurable."""
        rule = MinTradingDaysRule(required_days=10)
        assert rule.required_days == 10

    def test_rule_type_is_min_trading_days(self):
        """Rule type should be 'min_trading_days'."""
        rule = MinTradingDaysRule()
        assert rule.rule_type == "min_trading_days"

    def test_priority_is_100(self):
        """Priority should be 100 (informational rule)."""
        rule = MinTradingDaysRule()
        assert rule.priority == 100

    def test_name_includes_required_days(self):
        """Name should include required_days."""
        rule = MinTradingDaysRule(required_days=4)
        assert rule.name == "Minimum Trading Days (4)"

    def test_accepts_yaml_action_field(self):
        """Should accept action field from YAML (for compatibility)."""
        rule = MinTradingDaysRule(action="notify")
        assert rule is not None
        assert rule.action_type == "notify"

    def test_accepts_extra_kwargs(self):
        """Should accept extra kwargs for forward compatibility."""
        rule = MinTradingDaysRule(future_field="future_value")
        assert rule is not None


class TestMinTradingDaysRuleValidateAllow:
    """Tests for ALLOW scenarios (below requirement)."""

    def test_allow_at_zero_days(self):
        """ALLOW at 0 trading days."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 0})

        assert result.action == RuleAction.ALLOW

    def test_allow_at_1_day(self):
        """ALLOW at 1 trading day (below 4 required)."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 1})

        assert result.action == RuleAction.ALLOW

    def test_allow_at_3_days(self):
        """ALLOW at 3 trading days (below 4 required)."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 3})

        assert result.action == RuleAction.ALLOW

    def test_allow_includes_progress_info_in_message(self):
        """ALLOW message should include progress info."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 2})

        assert "2" in result.message
        assert "4" in result.message
        assert "2 more" in result.message  # 2 remaining

    def test_allow_metadata_includes_requirement_met_false(self):
        """ALLOW metadata should indicate requirement not met."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 2})

        assert result.metadata["requirement_met"] is False
        assert result.metadata["remaining_days"] == 2

    def test_allow_current_value_in_result(self):
        """ALLOW result should include current_value."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 2})

        assert result.current_value == 2.0

    def test_allow_threshold_value_in_result(self):
        """ALLOW result should include threshold_value."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 2})

        assert result.threshold_value == 4.0


class TestMinTradingDaysRuleValidateWarn:
    """Tests for WARN scenarios (requirement met)."""

    def test_warn_at_exactly_4_days(self):
        """WARN at exactly 4 days (requirement met)."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 4})

        assert result.action == RuleAction.WARN

    def test_warn_above_requirement(self):
        """WARN above 4 day requirement (5 days)."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 5})

        assert result.action == RuleAction.WARN

    def test_warn_well_above_requirement(self):
        """WARN well above requirement (10 days)."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 10})

        assert result.action == RuleAction.WARN

    def test_warn_message_indicates_met(self):
        """WARN message should indicate requirement met."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 4})

        assert "met" in result.message.lower() or "requirement" in result.message.lower()
        assert "4" in result.message

    def test_warn_metadata_includes_requirement_met_true(self):
        """WARN metadata should indicate requirement met."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 4})

        assert result.metadata["requirement_met"] is True
        assert result.metadata["rule_type"] == "min_trading_days"

    def test_warn_current_value_in_result(self):
        """WARN result should include current_value."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 5})

        assert result.current_value == 5.0

    def test_warn_threshold_value_in_result(self):
        """WARN result should include threshold_value."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 5})

        assert result.threshold_value == 4.0


class TestMinTradingDaysRuleNeverBlocks:
    """Tests ensuring MinTradingDaysRule NEVER returns BLOCK."""

    def test_never_blocks_at_requirement(self):
        """Should NEVER return BLOCK at requirement."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 4})

        assert result.action != RuleAction.BLOCK
        assert result.action == RuleAction.WARN

    def test_never_blocks_above_requirement(self):
        """Should NEVER return BLOCK above requirement."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 10})

        assert result.action != RuleAction.BLOCK
        assert result.action == RuleAction.WARN

    def test_never_blocks_below_requirement(self):
        """Should NEVER return BLOCK below requirement."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 0})

        assert result.action != RuleAction.BLOCK
        assert result.action == RuleAction.ALLOW

    def test_never_blocks_at_any_value(self):
        """Should NEVER return BLOCK at any days value."""
        rule = MinTradingDaysRule(required_days=4)

        # Test a range of values
        for days in [0, 1, 2, 3, 4, 5, 10, 50, 100]:
            result = rule.validate({"trading_days_count": days})
            assert result.action != RuleAction.BLOCK, f"BLOCK returned for days={days}"


class TestMinTradingDaysRuleProtocolMethods:
    """Tests for BaseRule protocol method implementations."""

    def test_get_current_value_extracts_from_context(self):
        """get_current_value should extract from context correctly."""
        rule = MinTradingDaysRule(required_days=4)
        context = {"trading_days_count": 3}

        assert rule.get_current_value(context) == 3.0

    def test_get_current_value_handles_zero(self):
        """get_current_value should handle zero days."""
        rule = MinTradingDaysRule(required_days=4)
        context = {"trading_days_count": 0}

        assert rule.get_current_value(context) == 0.0

    def test_get_current_value_defaults_to_zero(self):
        """get_current_value should default to 0.0 if missing."""
        rule = MinTradingDaysRule(required_days=4)
        context = {}

        assert rule.get_current_value(context) == 0.0

    def test_get_current_value_handles_float(self):
        """get_current_value should handle float input."""
        rule = MinTradingDaysRule(required_days=4)
        context = {"trading_days_count": 3.0}

        assert rule.get_current_value(context) == 3.0

    def test_get_threshold_returns_configured_requirement(self):
        """get_threshold should return configured requirement."""
        rule = MinTradingDaysRule(required_days=4)

        assert rule.get_threshold() == 4.0

    def test_get_threshold_with_custom_value(self):
        """get_threshold should return custom requirement."""
        rule = MinTradingDaysRule(required_days=10)

        assert rule.get_threshold() == 10.0

    def test_get_warning_thresholds_returns_empty_list(self):
        """get_warning_thresholds should return empty list (no intermediate warnings)."""
        rule = MinTradingDaysRule(required_days=4)

        assert rule.get_warning_thresholds() == []


class TestMinTradingDaysRuleCustomRequirement:
    """Tests for custom required_days configurations."""

    def test_10_days_requirement(self):
        """10 days requirement should work."""
        rule = MinTradingDaysRule(required_days=10)
        assert rule.required_days == 10
        assert rule.name == "Minimum Trading Days (10)"

    def test_custom_requirement_warns_correctly(self):
        """Custom requirement should warn at correct level."""
        rule = MinTradingDaysRule(required_days=10)

        result_below = rule.validate({"trading_days_count": 9})
        result_at = rule.validate({"trading_days_count": 10})

        assert result_below.action == RuleAction.ALLOW
        assert result_at.action == RuleAction.WARN

    def test_single_day_requirement(self):
        """Single day requirement should work."""
        rule = MinTradingDaysRule(required_days=1)

        result_below = rule.validate({"trading_days_count": 0})
        result_at = rule.validate({"trading_days_count": 1})

        assert result_below.action == RuleAction.ALLOW
        assert result_at.action == RuleAction.WARN


class TestMinTradingDaysRuleInputHandling:
    """Tests for integer and float input handling."""

    def test_integer_input_in_context(self):
        """Integer in context should be handled correctly."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 4})

        assert result.action == RuleAction.WARN
        assert result.current_value == 4.0

    def test_float_input_in_context(self):
        """Float in context should be converted to int for comparison."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 4.0})

        assert result.action == RuleAction.WARN
        assert result.current_value == 4.0

    def test_float_required_days_converted_to_int(self):
        """Float required_days should be converted to int."""
        rule = MinTradingDaysRule(required_days=4.5)

        assert rule.required_days == 4
        assert isinstance(rule.required_days, int)


class TestMinTradingDaysRuleRepr:
    """Tests for __repr__ method."""

    def test_repr_includes_required_days(self):
        """Repr should include required_days."""
        rule = MinTradingDaysRule(required_days=4)

        assert "required_days=4" in repr(rule)

    def test_repr_class_name(self):
        """Repr should include class name."""
        rule = MinTradingDaysRule(required_days=4)

        assert "MinTradingDaysRule" in repr(rule)


class TestMinTradingDaysRuleRuleResultProperties:
    """Tests for RuleResult helper properties."""

    def test_allow_is_allowed_true(self):
        """ALLOW result is_allowed should be True."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 2})

        assert result.is_allowed is True

    def test_warn_is_allowed_true(self):
        """WARN result is_allowed should be True (allows with notification)."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 4})

        assert result.is_allowed is True

    def test_allow_is_blocked_false(self):
        """ALLOW result is_blocked should be False."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 2})

        assert result.is_blocked is False

    def test_warn_is_blocked_false(self):
        """WARN result is_blocked should be False."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 4})

        assert result.is_blocked is False


class TestMinTradingDaysRuleMissingContext:
    """Tests for handling missing context data."""

    def test_missing_trading_days_count_defaults_to_zero(self):
        """Missing trading_days_count should default to 0."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({})

        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0

    def test_empty_context_allows(self):
        """Empty context should ALLOW (0 days)."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({})

        assert result.action == RuleAction.ALLOW


class TestMinTradingDaysRuleInvalidConfig:
    """Tests for invalid configuration handling."""

    def test_zero_required_days_logs_warning(self, caplog):
        """Zero required_days should log a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            rule = MinTradingDaysRule(required_days=0)

        assert "invalid required_days=0" in caplog.text
        assert "must be > 0" in caplog.text

    def test_negative_required_days_logs_warning(self, caplog):
        """Negative required_days should log a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            rule = MinTradingDaysRule(required_days=-4)

        assert "invalid required_days=-4" in caplog.text


class TestMinTradingDaysRuleEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_days_handled(self):
        """Zero days should be handled correctly."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 0})

        assert result.current_value == 0.0
        assert result.action == RuleAction.ALLOW
        assert result.metadata["remaining_days"] == 4

    def test_exactly_at_requirement(self):
        """Exactly at requirement should warn (inclusive)."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 4})

        assert result.action == RuleAction.WARN

    def test_one_below_requirement(self):
        """One below requirement should allow."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 3})

        assert result.action == RuleAction.ALLOW
        assert result.metadata["remaining_days"] == 1

    def test_large_number_of_days(self):
        """Large number of days should work."""
        rule = MinTradingDaysRule(required_days=4)
        result = rule.validate({"trading_days_count": 100})

        assert result.action == RuleAction.WARN
        assert result.metadata["requirement_met"] is True
