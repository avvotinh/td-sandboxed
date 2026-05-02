"""Unit tests for DailyLossLimitRule (Story 4.2).

Tests cover:
- ALLOW when below threshold
- WARN at warning thresholds (70%, 80%, 90%)
- BLOCK when at or above threshold
- RuleResult includes current_value and threshold_value
- Protocol method implementations (get_current_value, get_threshold, get_warning_thresholds)
- Custom warning thresholds
- Negative daily_pnl_percent handling (absolute value)
- Decimal input handling
"""

from decimal import Decimal

import pytest

from src.rules.base_rule import RuleAction
from src.rules.types.drawdown import DailyLossLimitRule


class TestDailyLossLimitRuleInit:
    """Tests for DailyLossLimitRule initialization."""

    def test_default_threshold_is_5_percent(self):
        """Default threshold should be 5%."""
        rule = DailyLossLimitRule()
        assert rule.threshold_percent == 5.0

    def test_custom_threshold(self):
        """Custom threshold should be configurable."""
        rule = DailyLossLimitRule(threshold_percent=3.0)
        assert rule.threshold_percent == 3.0

    def test_default_warning_thresholds(self):
        """Default warning thresholds should be [70, 80, 90]."""
        rule = DailyLossLimitRule()
        assert rule.warning_at == [70.0, 80.0, 90.0]

    def test_custom_warning_thresholds(self):
        """Custom warning thresholds should be configurable."""
        rule = DailyLossLimitRule(warning_at=[50.0, 75.0, 90.0])
        assert rule.warning_at == [50.0, 75.0, 90.0]

    def test_warning_thresholds_are_sorted(self):
        """Warning thresholds should be sorted ascending."""
        rule = DailyLossLimitRule(warning_at=[90.0, 50.0, 75.0])
        assert rule.warning_at == [50.0, 75.0, 90.0]

    def test_default_reset_time(self):
        """Default reset time should be 00:00."""
        rule = DailyLossLimitRule()
        assert rule.reset_time == "00:00"

    def test_default_timezone(self):
        """Default timezone should be UTC."""
        rule = DailyLossLimitRule()
        assert rule.timezone == "UTC"

    def test_custom_timezone_cet(self):
        """FTMO uses CET timezone."""
        rule = DailyLossLimitRule(timezone="CET")
        assert rule.timezone == "CET"

    def test_rule_type_is_daily_loss_limit(self):
        """Rule type should be 'daily_loss_limit'."""
        rule = DailyLossLimitRule()
        assert rule.rule_type == "daily_loss_limit"

    def test_priority_is_1(self):
        """Priority should be 1 (critical rule)."""
        rule = DailyLossLimitRule()
        assert rule.priority == 1

    def test_name_includes_threshold(self):
        """Name should include threshold percentage."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        assert rule.name == "Daily Loss Limit 5.0%"

    def test_accepts_yaml_action_field(self):
        """Should accept action field from YAML (for compatibility)."""
        rule = DailyLossLimitRule(action="block_trading")
        assert rule is not None

    def test_accepts_extra_kwargs(self):
        """Should accept extra kwargs for forward compatibility."""
        rule = DailyLossLimitRule(future_field="future_value")
        assert rule is not None


class TestDailyLossLimitRuleValidateAllow:
    """Tests for ALLOW scenarios (below all thresholds)."""

    def test_allow_at_zero_loss(self):
        """ALLOW at 0% loss."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": 0.0})

        assert result.action == RuleAction.ALLOW

    def test_allow_at_2_percent_loss(self):
        """ALLOW at 2% loss (well below 5% threshold)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -2.0})

        assert result.action == RuleAction.ALLOW

    def test_allow_at_positive_pnl(self):
        """ALLOW when in profit (positive P&L)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": 2.0})

        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0  # No loss when in profit

    def test_allow_at_positive_pnl_at_threshold_value(self):
        """ALLOW when profit equals threshold value (5% profit != 5% loss)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": 5.0})  # +5% PROFIT

        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0  # No loss when in profit

    def test_allow_at_positive_pnl_above_threshold_value(self):
        """ALLOW when profit exceeds threshold value (10% profit is good!)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": 10.0})  # +10% PROFIT

        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0  # No loss when in profit

    def test_allow_just_below_warning(self):
        """ALLOW just below 70% warning (3.49% of 5% = 69.8%)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -3.49})

        assert result.action == RuleAction.ALLOW

    def test_allow_current_value_in_result(self):
        """ALLOW result should include current_value."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -2.0})

        assert result.current_value == 2.0  # Absolute value

    def test_allow_threshold_value_in_result(self):
        """ALLOW result should include threshold_value."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -2.0})

        assert result.threshold_value == 5.0


class TestDailyLossLimitRuleValidateWarn:
    """Tests for WARN scenarios (at warning thresholds)."""

    def test_warn_at_70_percent_threshold(self):
        """WARN at 70% of limit (3.5% of 5% limit)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -3.5})

        assert result.action == RuleAction.WARN

    def test_warn_at_80_percent_threshold(self):
        """WARN at 80% of limit (4.0% of 5% limit)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -4.0})

        assert result.action == RuleAction.WARN

    def test_warn_at_90_percent_threshold(self):
        """WARN at 90% of limit (4.5% of 5% limit)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -4.5})

        assert result.action == RuleAction.WARN

    def test_warn_returns_highest_applicable_threshold(self):
        """WARN should return highest applicable warning threshold."""
        rule = DailyLossLimitRule(threshold_percent=5.0)

        # At 85% usage (4.25% loss) - should get 80% warning, not 70%
        result = rule.validate({"daily_pnl_percent": -4.25})

        assert result.action == RuleAction.WARN
        assert result.metadata["warning_threshold"] == 80.0

    def test_warn_metadata_includes_warning_threshold(self):
        """WARN result should include warning_threshold in metadata."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -3.5})

        assert "warning_threshold" in result.metadata
        assert result.metadata["warning_threshold"] == 70.0

    def test_warn_metadata_includes_usage_percent(self):
        """WARN result should include usage_percent in metadata."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -3.5})

        assert "usage_percent" in result.metadata
        assert result.metadata["usage_percent"] == 70.0

    def test_warn_message_format(self):
        """WARN message should include relevant info."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -3.5})

        assert "70%" in result.message
        assert "5.0%" in result.message

    def test_warn_current_value_in_result(self):
        """WARN result should include current_value."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -3.5})

        assert result.current_value == 3.5  # Absolute value

    def test_warn_threshold_value_in_result(self):
        """WARN result should include threshold_value."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -3.5})

        assert result.threshold_value == 5.0


class TestDailyLossLimitRuleValidateBlock:
    """Tests for BLOCK scenarios (at or above threshold)."""

    def test_block_at_threshold(self):
        """BLOCK at exactly 5% loss (equals threshold)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -5.0})

        assert result.action == RuleAction.BLOCK

    def test_block_above_threshold(self):
        """BLOCK at 5.5% loss (above threshold)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -5.5})

        assert result.action == RuleAction.BLOCK

    def test_block_well_above_threshold(self):
        """BLOCK at 7% loss (well above threshold)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -7.0})

        assert result.action == RuleAction.BLOCK

    def test_block_message_format(self):
        """BLOCK message should include relevant info."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -5.5})

        assert "5.50%" in result.message
        assert "exceeds" in result.message.lower()
        assert "5.0%" in result.message

    def test_block_current_value_in_result(self):
        """BLOCK result should include current_value."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -5.5})

        assert result.current_value == 5.5  # Absolute value

    def test_block_threshold_value_in_result(self):
        """BLOCK result should include threshold_value."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -5.5})

        assert result.threshold_value == 5.0

    def test_block_metadata_includes_rule_type(self):
        """BLOCK result should include rule_type in metadata."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -5.5})

        assert result.metadata["rule_type"] == "daily_loss_limit"

    def test_block_metadata_includes_original_pnl(self):
        """BLOCK result should include original daily_pnl_percent in metadata."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -5.5})

        assert result.metadata["daily_pnl_percent"] == -5.5


class TestDailyLossLimitRuleProtocolMethods:
    """Tests for BaseRule protocol method implementations."""

    def test_get_current_value_extracts_from_context(self):
        """get_current_value should extract from context correctly."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        context = {"daily_pnl_percent": -3.0}

        assert rule.get_current_value(context) == 3.0  # Absolute value

    def test_get_current_value_handles_positive(self):
        """get_current_value should return 0.0 for positive pnl (profit = no loss)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        context = {"daily_pnl_percent": 2.0}

        assert rule.get_current_value(context) == 0.0  # No loss when in profit

    def test_get_current_value_defaults_to_zero(self):
        """get_current_value should default to 0.0 if missing."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        context = {}

        assert rule.get_current_value(context) == 0.0

    def test_get_current_value_handles_decimal(self):
        """get_current_value should handle Decimal input."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        context = {"daily_pnl_percent": Decimal("-3.5")}

        assert rule.get_current_value(context) == 3.5

    def test_get_threshold_returns_configured_threshold(self):
        """get_threshold should return configured threshold."""
        rule = DailyLossLimitRule(threshold_percent=5.0)

        assert rule.get_threshold() == 5.0

    def test_get_threshold_with_custom_value(self):
        """get_threshold should return custom threshold."""
        rule = DailyLossLimitRule(threshold_percent=3.0)

        assert rule.get_threshold() == 3.0

    def test_get_warning_thresholds_returns_configured_list(self):
        """get_warning_thresholds should return configured list."""
        rule = DailyLossLimitRule(threshold_percent=5.0)

        assert rule.get_warning_thresholds() == [70.0, 80.0, 90.0]

    def test_get_warning_thresholds_returns_copy(self):
        """get_warning_thresholds should return a copy (not modify original)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        thresholds = rule.get_warning_thresholds()
        thresholds.append(95.0)

        assert rule.get_warning_thresholds() == [70.0, 80.0, 90.0]

    def test_get_warning_thresholds_with_custom_values(self):
        """get_warning_thresholds should return custom values."""
        rule = DailyLossLimitRule(warning_at=[50.0, 75.0, 90.0])

        assert rule.get_warning_thresholds() == [50.0, 75.0, 90.0]


class TestDailyLossLimitRuleCustomWarningThresholds:
    """Tests for custom warning threshold configurations."""

    def test_custom_50_75_90_warns_at_50(self):
        """Custom [50, 75, 90] should warn at 50%."""
        rule = DailyLossLimitRule(
            threshold_percent=5.0,
            warning_at=[50.0, 75.0, 90.0],
        )
        result = rule.validate({"daily_pnl_percent": -2.5})  # 50% of 5%

        assert result.action == RuleAction.WARN
        assert result.metadata["warning_threshold"] == 50.0

    def test_custom_single_threshold(self):
        """Single warning threshold should work."""
        rule = DailyLossLimitRule(
            threshold_percent=5.0,
            warning_at=[80.0],
        )
        # 4.0% is 80% of 5%
        result = rule.validate({"daily_pnl_percent": -4.0})

        assert result.action == RuleAction.WARN

    def test_empty_warning_thresholds_no_warnings(self):
        """Empty warning list should never warn (ALLOW or BLOCK only)."""
        rule = DailyLossLimitRule(
            threshold_percent=5.0,
            warning_at=[],
        )
        # 4.5% is 90% of 5% - should ALLOW since no warnings configured
        result = rule.validate({"daily_pnl_percent": -4.5})

        assert result.action == RuleAction.ALLOW


class TestDailyLossLimitRuleNegativePnlHandling:
    """Tests for negative daily_pnl_percent handling."""

    def test_negative_pnl_uses_absolute_value(self):
        """Negative pnl should use absolute value for comparison."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -3.0})

        assert result.current_value == 3.0

    def test_positive_pnl_returns_zero_loss(self):
        """Positive pnl (profit) should report zero loss."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": 3.0})

        assert result.current_value == 0.0  # No loss when in profit
        assert result.action == RuleAction.ALLOW

    def test_zero_pnl_handled(self):
        """Zero pnl should be handled correctly."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": 0.0})

        assert result.current_value == 0.0
        assert result.action == RuleAction.ALLOW


class TestDailyLossLimitRuleDecimalHandling:
    """Tests for Decimal input handling."""

    def test_decimal_input_for_threshold(self):
        """Decimal threshold should be converted to float."""
        rule = DailyLossLimitRule(threshold_percent=Decimal("5.0"))

        assert rule.threshold_percent == 5.0
        assert isinstance(rule.threshold_percent, float)

    def test_decimal_input_in_context(self):
        """Decimal in context should be handled correctly."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": Decimal("-3.5")})

        assert result.action == RuleAction.WARN
        assert result.current_value == 3.5

    def test_decimal_block_at_threshold(self):
        """Decimal at threshold should BLOCK."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": Decimal("-5.0")})

        assert result.action == RuleAction.BLOCK


class TestDailyLossLimitRuleRepr:
    """Tests for __repr__ method."""

    def test_repr_includes_threshold(self):
        """Repr should include threshold."""
        rule = DailyLossLimitRule(threshold_percent=5.0)

        assert "5.0%" in repr(rule)

    def test_repr_includes_reset_time(self):
        """Repr should include reset time."""
        rule = DailyLossLimitRule(reset_time="00:00")

        assert "00:00" in repr(rule)

    def test_repr_includes_timezone(self):
        """Repr should include timezone."""
        rule = DailyLossLimitRule(timezone="CET")

        assert "CET" in repr(rule)

    def test_repr_includes_warnings(self):
        """Repr should include warning thresholds."""
        rule = DailyLossLimitRule(warning_at=[70.0, 80.0, 90.0])

        assert "[70.0, 80.0, 90.0]" in repr(rule)


class TestDailyLossLimitRuleRuleResultProperties:
    """Tests for RuleResult helper properties."""

    def test_allow_is_allowed_true(self):
        """ALLOW result is_allowed should be True."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -2.0})

        assert result.is_allowed is True

    def test_warn_is_allowed_true(self):
        """WARN result is_allowed should be True (allows with warning)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -3.5})

        assert result.is_allowed is True

    def test_block_is_allowed_false(self):
        """BLOCK result is_allowed should be False."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -5.0})

        assert result.is_allowed is False

    def test_allow_is_blocked_false(self):
        """ALLOW result is_blocked should be False."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -2.0})

        assert result.is_blocked is False

    def test_warn_is_blocked_false(self):
        """WARN result is_blocked should be False."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -3.5})

        assert result.is_blocked is False

    def test_block_is_blocked_true(self):
        """BLOCK result is_blocked should be True."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -5.0})

        assert result.is_blocked is True


class TestDailyLossLimitRuleMissingContext:
    """Tests for handling missing context data."""

    def test_missing_daily_pnl_percent_defaults_to_zero(self):
        """Missing daily_pnl_percent should default to 0.0."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({})

        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0

    def test_empty_context_allows(self):
        """Empty context should ALLOW (no loss)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({})

        assert result.action == RuleAction.ALLOW


class TestDailyLossLimitRuleInvalidConfig:
    """Tests for invalid configuration handling."""

    def test_zero_threshold_logs_warning(self, caplog):
        """Zero threshold should log a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            rule = DailyLossLimitRule(threshold_percent=0.0)

        assert "invalid threshold_percent=0.00" in caplog.text
        assert "must be > 0" in caplog.text

    def test_negative_threshold_logs_warning(self, caplog):
        """Negative threshold should log a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            rule = DailyLossLimitRule(threshold_percent=-5.0)

        assert "invalid threshold_percent=-5.00" in caplog.text

    def test_zero_threshold_blocks_any_loss(self):
        """Zero threshold blocks any loss (edge case behavior)."""
        rule = DailyLossLimitRule(threshold_percent=0.0)
        result = rule.validate({"daily_pnl_percent": -0.01})

        # Any loss >= 0 threshold triggers block
        assert result.action == RuleAction.BLOCK


class TestDailyLossLimitRuleEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_exactly_at_70_percent_warns(self):
        """Exactly at 70% should warn (inclusive)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        # Exactly 70% of 5% = 3.5%
        result = rule.validate({"daily_pnl_percent": -3.5})

        assert result.action == RuleAction.WARN

    def test_just_under_70_percent_allows(self):
        """Just under 70% should allow."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        # 69.9% of 5% = 3.495%
        result = rule.validate({"daily_pnl_percent": -3.495})

        assert result.action == RuleAction.ALLOW

    def test_exactly_at_threshold_blocks(self):
        """Exactly at threshold should block (inclusive)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        result = rule.validate({"daily_pnl_percent": -5.0})

        assert result.action == RuleAction.BLOCK

    def test_just_under_threshold_warns(self):
        """Just under threshold should warn (90%)."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        # 4.99% is 99.8% of 5% - should warn at 90%
        result = rule.validate({"daily_pnl_percent": -4.99})

        assert result.action == RuleAction.WARN

    def test_very_small_threshold(self):
        """Very small threshold should work."""
        rule = DailyLossLimitRule(threshold_percent=0.5)
        result = rule.validate({"daily_pnl_percent": -0.5})

        assert result.action == RuleAction.BLOCK

    def test_very_large_threshold(self):
        """Very large threshold should work."""
        rule = DailyLossLimitRule(threshold_percent=50.0)
        result = rule.validate({"daily_pnl_percent": -25.0})  # 50% of limit

        assert result.action == RuleAction.ALLOW
