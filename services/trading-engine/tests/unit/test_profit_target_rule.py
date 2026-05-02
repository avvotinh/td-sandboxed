"""Unit tests for ProfitTargetRule (Story 4.5).

Tests cover:
- ALLOW when below target (with progress info)
- WARN when target is met (notification)
- NEVER returns BLOCK (informational only)
- RuleResult includes current_value and threshold_value
- Protocol method implementations (get_current_value, get_threshold, get_warning_thresholds)
- Custom threshold configurations
- Decimal input handling
"""

from decimal import Decimal

import pytest

from src.rules.base_rule import RuleAction
from src.rules.types.targets import ProfitTargetRule


class TestProfitTargetRuleInit:
    """Tests for ProfitTargetRule initialization."""

    def test_default_threshold_is_10_percent(self):
        """Default threshold should be 10%."""
        rule = ProfitTargetRule()
        assert rule.threshold_percent == 10.0

    def test_custom_threshold(self):
        """Custom threshold should be configurable."""
        rule = ProfitTargetRule(threshold_percent=5.0)
        assert rule.threshold_percent == 5.0

    def test_rule_type_is_profit_target(self):
        """Rule type should be 'profit_target'."""
        rule = ProfitTargetRule()
        assert rule.rule_type == "profit_target"

    def test_priority_is_100(self):
        """Priority should be 100 (informational rule)."""
        rule = ProfitTargetRule()
        assert rule.priority == 100

    def test_name_includes_threshold(self):
        """Name should include threshold percentage."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        assert rule.name == "Profit Target 10.0%"

    def test_accepts_yaml_action_field(self):
        """Should accept action field from YAML (for compatibility)."""
        rule = ProfitTargetRule(action="notify")
        assert rule is not None
        assert rule.action_type == "notify"

    def test_accepts_extra_kwargs(self):
        """Should accept extra kwargs for forward compatibility."""
        rule = ProfitTargetRule(future_field="future_value")
        assert rule is not None


class TestProfitTargetRuleValidateAllow:
    """Tests for ALLOW scenarios (below target)."""

    def test_allow_at_zero_profit(self):
        """ALLOW at 0% profit."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 0.0})

        assert result.action == RuleAction.ALLOW

    def test_allow_at_5_percent_profit(self):
        """ALLOW at 5% profit (below 10% target)."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 5.0})

        assert result.action == RuleAction.ALLOW

    def test_allow_at_negative_pnl(self):
        """ALLOW when in loss (negative P&L)."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": -3.0})

        assert result.action == RuleAction.ALLOW

    def test_allow_just_below_target(self):
        """ALLOW just below target (9.99%)."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 9.99})

        assert result.action == RuleAction.ALLOW

    def test_allow_includes_progress_info_in_message(self):
        """ALLOW message should include progress info."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 5.0})

        assert "5.00%" in result.message
        assert "10.0%" in result.message
        assert "50%" in result.message  # 50% progress

    def test_allow_metadata_includes_target_met_false(self):
        """ALLOW metadata should indicate target not met."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 5.0})

        assert result.metadata["target_met"] is False
        assert result.metadata["progress_percent"] == 50.0
        assert result.metadata["remaining_percent"] == 5.0

    def test_allow_current_value_in_result(self):
        """ALLOW result should include current_value."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 5.0})

        assert result.current_value == 5.0

    def test_allow_threshold_value_in_result(self):
        """ALLOW result should include threshold_value."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 5.0})

        assert result.threshold_value == 10.0


class TestProfitTargetRuleValidateWarn:
    """Tests for WARN scenarios (target met)."""

    def test_warn_at_exactly_10_percent(self):
        """WARN at exactly 10% profit (target met)."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 10.0})

        assert result.action == RuleAction.WARN

    def test_warn_above_target(self):
        """WARN above 10% target (12% profit)."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 12.0})

        assert result.action == RuleAction.WARN

    def test_warn_well_above_target(self):
        """WARN well above target (20% profit)."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 20.0})

        assert result.action == RuleAction.WARN

    def test_warn_message_is_congratulatory(self):
        """WARN message should be congratulatory."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 10.0})

        assert "achieved" in result.message.lower() or "target" in result.message.lower()
        assert "10.00%" in result.message
        assert "10.0%" in result.message

    def test_warn_metadata_includes_target_met_true(self):
        """WARN metadata should indicate target met."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 10.0})

        assert result.metadata["target_met"] is True
        assert result.metadata["rule_type"] == "profit_target"

    def test_warn_current_value_in_result(self):
        """WARN result should include current_value."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 12.0})

        assert result.current_value == 12.0

    def test_warn_threshold_value_in_result(self):
        """WARN result should include threshold_value."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 12.0})

        assert result.threshold_value == 10.0


class TestProfitTargetRuleNeverBlocks:
    """Tests ensuring ProfitTargetRule NEVER returns BLOCK."""

    def test_never_blocks_at_target(self):
        """Should NEVER return BLOCK at target."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 10.0})

        assert result.action != RuleAction.BLOCK
        assert result.action == RuleAction.WARN

    def test_never_blocks_above_target(self):
        """Should NEVER return BLOCK above target."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 50.0})

        assert result.action != RuleAction.BLOCK
        assert result.action == RuleAction.WARN

    def test_never_blocks_with_extreme_profit(self):
        """Should NEVER return BLOCK even with extreme profit."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 100.0})

        assert result.action != RuleAction.BLOCK

    def test_never_blocks_at_any_value(self):
        """Should NEVER return BLOCK at any P&L value."""
        rule = ProfitTargetRule(threshold_percent=10.0)

        # Test a range of values
        for pnl in [-50.0, -10.0, 0.0, 5.0, 10.0, 15.0, 50.0, 100.0]:
            result = rule.validate({"total_pnl_percent": pnl})
            assert result.action != RuleAction.BLOCK, f"BLOCK returned for P&L={pnl}%"


class TestProfitTargetRuleProtocolMethods:
    """Tests for BaseRule protocol method implementations."""

    def test_get_current_value_extracts_from_context(self):
        """get_current_value should extract from context correctly."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        context = {"total_pnl_percent": 7.5}

        assert rule.get_current_value(context) == 7.5

    def test_get_current_value_handles_negative(self):
        """get_current_value should handle negative P&L (loss)."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        context = {"total_pnl_percent": -3.0}

        assert rule.get_current_value(context) == -3.0

    def test_get_current_value_defaults_to_zero(self):
        """get_current_value should default to 0.0 if missing."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        context = {}

        assert rule.get_current_value(context) == 0.0

    def test_get_current_value_handles_decimal(self):
        """get_current_value should handle Decimal input."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        context = {"total_pnl_percent": Decimal("7.5")}

        assert rule.get_current_value(context) == 7.5

    def test_get_threshold_returns_configured_threshold(self):
        """get_threshold should return configured threshold."""
        rule = ProfitTargetRule(threshold_percent=10.0)

        assert rule.get_threshold() == 10.0

    def test_get_threshold_with_custom_value(self):
        """get_threshold should return custom threshold."""
        rule = ProfitTargetRule(threshold_percent=5.0)

        assert rule.get_threshold() == 5.0

    def test_get_warning_thresholds_returns_empty_list(self):
        """get_warning_thresholds should return empty list (no intermediate warnings)."""
        rule = ProfitTargetRule(threshold_percent=10.0)

        assert rule.get_warning_thresholds() == []


class TestProfitTargetRuleCustomThreshold:
    """Tests for custom threshold configurations."""

    def test_5_percent_target_for_verification(self):
        """5% target for FTMO Verification phase."""
        rule = ProfitTargetRule(threshold_percent=5.0)
        assert rule.threshold_percent == 5.0
        assert rule.name == "Profit Target 5.0%"

    def test_custom_threshold_warns_correctly(self):
        """Custom threshold should warn at correct level."""
        rule = ProfitTargetRule(threshold_percent=5.0)

        result_below = rule.validate({"total_pnl_percent": 4.0})
        result_at = rule.validate({"total_pnl_percent": 5.0})

        assert result_below.action == RuleAction.ALLOW
        assert result_at.action == RuleAction.WARN


class TestProfitTargetRuleDecimalHandling:
    """Tests for Decimal input handling."""

    def test_decimal_input_for_threshold(self):
        """Decimal threshold should be converted to float."""
        rule = ProfitTargetRule(threshold_percent=Decimal("10.0"))

        assert rule.threshold_percent == 10.0
        assert isinstance(rule.threshold_percent, float)

    def test_decimal_input_in_context(self):
        """Decimal in context should be handled correctly."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": Decimal("10.0")})

        assert result.action == RuleAction.WARN
        assert result.current_value == 10.0

    def test_decimal_allow_below_target(self):
        """Decimal below target should ALLOW."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": Decimal("5.0")})

        assert result.action == RuleAction.ALLOW


class TestProfitTargetRuleRepr:
    """Tests for __repr__ method."""

    def test_repr_includes_threshold(self):
        """Repr should include threshold."""
        rule = ProfitTargetRule(threshold_percent=10.0)

        assert "10.0%" in repr(rule)

    def test_repr_class_name(self):
        """Repr should include class name."""
        rule = ProfitTargetRule(threshold_percent=10.0)

        assert "ProfitTargetRule" in repr(rule)


class TestProfitTargetRuleRuleResultProperties:
    """Tests for RuleResult helper properties."""

    def test_allow_is_allowed_true(self):
        """ALLOW result is_allowed should be True."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 5.0})

        assert result.is_allowed is True

    def test_warn_is_allowed_true(self):
        """WARN result is_allowed should be True (allows with notification)."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 10.0})

        assert result.is_allowed is True

    def test_allow_is_blocked_false(self):
        """ALLOW result is_blocked should be False."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 5.0})

        assert result.is_blocked is False

    def test_warn_is_blocked_false(self):
        """WARN result is_blocked should be False."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 10.0})

        assert result.is_blocked is False


class TestProfitTargetRuleMissingContext:
    """Tests for handling missing context data."""

    def test_missing_total_pnl_percent_defaults_to_zero(self):
        """Missing total_pnl_percent should default to 0.0."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({})

        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0

    def test_empty_context_allows(self):
        """Empty context should ALLOW (0% profit)."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({})

        assert result.action == RuleAction.ALLOW


class TestProfitTargetRuleInvalidConfig:
    """Tests for invalid configuration handling."""

    def test_zero_threshold_logs_warning(self, caplog):
        """Zero threshold should log a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            rule = ProfitTargetRule(threshold_percent=0.0)

        assert "invalid threshold_percent=0.00" in caplog.text
        assert "must be > 0" in caplog.text

    def test_negative_threshold_logs_warning(self, caplog):
        """Negative threshold should log a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            rule = ProfitTargetRule(threshold_percent=-10.0)

        assert "invalid threshold_percent=-10.00" in caplog.text


class TestProfitTargetRuleEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_pnl_handled(self):
        """Zero P&L should be handled correctly."""
        rule = ProfitTargetRule(threshold_percent=10.0)
        result = rule.validate({"total_pnl_percent": 0.0})

        assert result.current_value == 0.0
        assert result.action == RuleAction.ALLOW

    def test_very_small_target(self):
        """Very small target should work."""
        rule = ProfitTargetRule(threshold_percent=0.5)
        result = rule.validate({"total_pnl_percent": 0.5})

        assert result.action == RuleAction.WARN

    def test_very_large_target(self):
        """Very large target should work."""
        rule = ProfitTargetRule(threshold_percent=50.0)
        result = rule.validate({"total_pnl_percent": 25.0})

        assert result.action == RuleAction.ALLOW
        # 25% is 50% of 50% target
        assert result.metadata["progress_percent"] == 50.0
