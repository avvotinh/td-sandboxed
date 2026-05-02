"""Unit tests for MaxDrawdownRule (Story 4.3).

Tests cover:
- ALLOW when below threshold
- WARN at warning thresholds (50%, 70%, 85%)
- BLOCK when at or above threshold
- RuleResult includes current_value and threshold_value
- Protocol method implementations (get_current_value, get_threshold, get_warning_thresholds)
- Custom warning thresholds
- Zero/negative drawdown handling (profit scenario)
- Decimal input handling
"""

from decimal import Decimal

import pytest

from src.rules.base_rule import RuleAction
from src.rules.types.drawdown import MaxDrawdownRule


class TestMaxDrawdownRuleInit:
    """Tests for MaxDrawdownRule initialization."""

    def test_default_threshold_is_10_percent(self):
        """Default threshold should be 10%."""
        rule = MaxDrawdownRule()
        assert rule.threshold_percent == 10.0

    def test_custom_threshold(self):
        """Custom threshold should be configurable."""
        rule = MaxDrawdownRule(threshold_percent=5.0)
        assert rule.threshold_percent == 5.0

    def test_default_warning_thresholds(self):
        """Default warning thresholds should be [50, 70, 85]."""
        rule = MaxDrawdownRule()
        assert rule.warning_at == [50.0, 70.0, 85.0]

    def test_custom_warning_thresholds(self):
        """Custom warning thresholds should be configurable."""
        rule = MaxDrawdownRule(warning_at=[60.0, 80.0, 95.0])
        assert rule.warning_at == [60.0, 80.0, 95.0]

    def test_warning_thresholds_are_sorted(self):
        """Warning thresholds should be sorted ascending."""
        rule = MaxDrawdownRule(warning_at=[85.0, 50.0, 70.0])
        assert rule.warning_at == [50.0, 70.0, 85.0]

    def test_default_reference(self):
        """Default reference should be 'initial_balance'."""
        rule = MaxDrawdownRule()
        assert rule.reference == "initial_balance"

    def test_custom_reference(self):
        """Custom reference should be configurable."""
        rule = MaxDrawdownRule(reference="peak_equity")
        assert rule.reference == "peak_equity"

    def test_rule_type_is_max_drawdown(self):
        """Rule type should be 'max_drawdown'."""
        rule = MaxDrawdownRule()
        assert rule.rule_type == "max_drawdown"

    def test_priority_is_2(self):
        """Priority should be 2 (after daily loss limit)."""
        rule = MaxDrawdownRule()
        assert rule.priority == 2

    def test_name_includes_threshold(self):
        """Name should include threshold percentage."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        assert rule.name == "Max Drawdown 10.0%"

    def test_accepts_yaml_action_field(self):
        """Should accept action field from YAML (for compatibility)."""
        rule = MaxDrawdownRule(action="block_trading")
        assert rule is not None

    def test_accepts_extra_kwargs(self):
        """Should accept extra kwargs for forward compatibility."""
        rule = MaxDrawdownRule(future_field="future_value")
        assert rule is not None


class TestMaxDrawdownRuleValidateAllow:
    """Tests for ALLOW scenarios (below all thresholds)."""

    def test_allow_at_zero_drawdown(self):
        """ALLOW at 0% drawdown."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 0.0})

        assert result.action == RuleAction.ALLOW

    def test_allow_at_4_percent_drawdown(self):
        """ALLOW at 4% drawdown (well below 10% threshold, below 50% warning)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 4.0})

        assert result.action == RuleAction.ALLOW

    def test_allow_at_negative_drawdown(self):
        """ALLOW when above peak (negative drawdown = profit scenario)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": -2.0})

        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0  # No drawdown

    def test_allow_just_below_50_percent_warning(self):
        """ALLOW just below 50% warning (4.99% of 10% = 49.9%)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 4.99})

        assert result.action == RuleAction.ALLOW

    def test_allow_current_value_in_result(self):
        """ALLOW result should include current_value."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 4.0})

        assert result.current_value == 4.0

    def test_allow_threshold_value_in_result(self):
        """ALLOW result should include threshold_value."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 4.0})

        assert result.threshold_value == 10.0


class TestMaxDrawdownRuleValidateWarn:
    """Tests for WARN scenarios (at warning thresholds)."""

    def test_warn_at_50_percent_threshold(self):
        """WARN at 50% of limit (5% of 10% limit)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 5.0})

        assert result.action == RuleAction.WARN

    def test_warn_at_70_percent_threshold(self):
        """WARN at 70% of limit (7% of 10% limit)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 7.0})

        assert result.action == RuleAction.WARN

    def test_warn_at_85_percent_threshold(self):
        """WARN at 85% of limit (8.5% of 10% limit)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 8.5})

        assert result.action == RuleAction.WARN

    def test_warn_returns_highest_applicable_threshold(self):
        """WARN should return highest applicable warning threshold."""
        rule = MaxDrawdownRule(threshold_percent=10.0)

        # At 75% usage (7.5% drawdown) - should get 70% warning, not 50%
        result = rule.validate({"total_drawdown_percent": 7.5})

        assert result.action == RuleAction.WARN
        assert result.metadata["warning_threshold"] == 70.0

    def test_warn_metadata_includes_warning_threshold(self):
        """WARN result should include warning_threshold in metadata."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 5.0})

        assert "warning_threshold" in result.metadata
        assert result.metadata["warning_threshold"] == 50.0

    def test_warn_metadata_includes_usage_percent(self):
        """WARN result should include usage_percent in metadata."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 5.0})

        assert "usage_percent" in result.metadata
        assert result.metadata["usage_percent"] == 50.0

    def test_warn_message_format(self):
        """WARN message should include relevant info."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 7.0})

        assert "70%" in result.message
        assert "10.0%" in result.message

    def test_warn_current_value_in_result(self):
        """WARN result should include current_value."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 7.0})

        assert result.current_value == 7.0

    def test_warn_threshold_value_in_result(self):
        """WARN result should include threshold_value."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 7.0})

        assert result.threshold_value == 10.0


class TestMaxDrawdownRuleValidateBlock:
    """Tests for BLOCK scenarios (at or above threshold)."""

    def test_block_at_threshold(self):
        """BLOCK at exactly 10% drawdown (equals threshold)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 10.0})

        assert result.action == RuleAction.BLOCK

    def test_block_above_threshold(self):
        """BLOCK at 11% drawdown (above threshold)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 11.0})

        assert result.action == RuleAction.BLOCK

    def test_block_well_above_threshold(self):
        """BLOCK at 15% drawdown (well above threshold)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 15.0})

        assert result.action == RuleAction.BLOCK

    def test_block_message_format(self):
        """BLOCK message should include relevant info."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 10.5})

        assert "10.50%" in result.message
        assert "exceeds" in result.message.lower()
        assert "10.0%" in result.message

    def test_block_current_value_in_result(self):
        """BLOCK result should include current_value."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 10.5})

        assert result.current_value == 10.5

    def test_block_threshold_value_in_result(self):
        """BLOCK result should include threshold_value."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 10.5})

        assert result.threshold_value == 10.0

    def test_block_metadata_includes_rule_type(self):
        """BLOCK result should include rule_type in metadata."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 10.5})

        assert result.metadata["rule_type"] == "max_drawdown"

    def test_block_metadata_includes_reference(self):
        """BLOCK result should include reference in metadata."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 10.5})

        assert result.metadata["reference"] == "initial_balance"


class TestMaxDrawdownRuleProtocolMethods:
    """Tests for BaseRule protocol method implementations."""

    def test_get_current_value_extracts_from_context(self):
        """get_current_value should extract from context correctly."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        context = {"total_drawdown_percent": 7.0}

        assert rule.get_current_value(context) == 7.0

    def test_get_current_value_handles_negative(self):
        """get_current_value should return 0.0 for negative drawdown."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        context = {"total_drawdown_percent": -2.0}

        assert rule.get_current_value(context) == 0.0  # Never negative

    def test_get_current_value_defaults_to_zero(self):
        """get_current_value should default to 0.0 if missing."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        context = {}

        assert rule.get_current_value(context) == 0.0

    def test_get_current_value_handles_decimal(self):
        """get_current_value should handle Decimal input."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        context = {"total_drawdown_percent": Decimal("7.5")}

        assert rule.get_current_value(context) == 7.5

    def test_get_threshold_returns_configured_threshold(self):
        """get_threshold should return configured threshold."""
        rule = MaxDrawdownRule(threshold_percent=10.0)

        assert rule.get_threshold() == 10.0

    def test_get_threshold_with_custom_value(self):
        """get_threshold should return custom threshold."""
        rule = MaxDrawdownRule(threshold_percent=5.0)

        assert rule.get_threshold() == 5.0

    def test_get_warning_thresholds_returns_configured_list(self):
        """get_warning_thresholds should return configured list."""
        rule = MaxDrawdownRule(threshold_percent=10.0)

        assert rule.get_warning_thresholds() == [50.0, 70.0, 85.0]

    def test_get_warning_thresholds_returns_copy(self):
        """get_warning_thresholds should return a copy (not modify original)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        thresholds = rule.get_warning_thresholds()
        thresholds.append(95.0)

        assert rule.get_warning_thresholds() == [50.0, 70.0, 85.0]

    def test_get_warning_thresholds_with_custom_values(self):
        """get_warning_thresholds should return custom values."""
        rule = MaxDrawdownRule(warning_at=[60.0, 80.0, 95.0])

        assert rule.get_warning_thresholds() == [60.0, 80.0, 95.0]


class TestMaxDrawdownRuleCustomWarningThresholds:
    """Tests for custom warning threshold configurations."""

    def test_custom_60_80_95_warns_at_60(self):
        """Custom [60, 80, 95] should warn at 60%."""
        rule = MaxDrawdownRule(
            threshold_percent=10.0,
            warning_at=[60.0, 80.0, 95.0],
        )
        result = rule.validate({"total_drawdown_percent": 6.0})  # 60% of 10%

        assert result.action == RuleAction.WARN
        assert result.metadata["warning_threshold"] == 60.0

    def test_custom_single_threshold(self):
        """Single warning threshold should work."""
        rule = MaxDrawdownRule(
            threshold_percent=10.0,
            warning_at=[80.0],
        )
        # 8.0% is 80% of 10%
        result = rule.validate({"total_drawdown_percent": 8.0})

        assert result.action == RuleAction.WARN

    def test_empty_warning_thresholds_no_warnings(self):
        """Empty warning list should never warn (ALLOW or BLOCK only)."""
        rule = MaxDrawdownRule(
            threshold_percent=10.0,
            warning_at=[],
        )
        # 9% is 90% of 10% - should ALLOW since no warnings configured
        result = rule.validate({"total_drawdown_percent": 9.0})

        assert result.action == RuleAction.ALLOW


class TestMaxDrawdownRuleCustomThreshold:
    """Tests for custom threshold configurations (AC4)."""

    def test_5_percent_threshold_blocks_at_5(self):
        """5% threshold should block at 5% drawdown."""
        rule = MaxDrawdownRule(threshold_percent=5.0)
        result = rule.validate({"total_drawdown_percent": 5.0})

        assert result.action == RuleAction.BLOCK

    def test_5_percent_threshold_allows_at_4(self):
        """5% threshold should allow at 4% drawdown."""
        rule = MaxDrawdownRule(threshold_percent=5.0)
        result = rule.validate({"total_drawdown_percent": 4.0})

        # 4% is 80% of 5% - triggers 70% warning
        assert result.action == RuleAction.WARN

    def test_4_percent_threshold_for_the5ers(self):
        """The5ers uses 4% max drawdown limit."""
        rule = MaxDrawdownRule(threshold_percent=4.0)

        # At 4% - should BLOCK
        result = rule.validate({"total_drawdown_percent": 4.0})
        assert result.action == RuleAction.BLOCK

        # At 3% - should WARN (75% of limit)
        result = rule.validate({"total_drawdown_percent": 3.0})
        assert result.action == RuleAction.WARN


class TestMaxDrawdownRuleZeroDrawdownHandling:
    """Tests for zero and negative drawdown handling."""

    def test_zero_drawdown_allows(self):
        """Zero drawdown should allow."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 0.0})

        assert result.current_value == 0.0
        assert result.action == RuleAction.ALLOW

    def test_negative_drawdown_returns_zero_current(self):
        """Negative drawdown should report zero current value."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": -2.0})

        assert result.current_value == 0.0  # Never negative
        assert result.action == RuleAction.ALLOW


class TestMaxDrawdownRuleDecimalHandling:
    """Tests for Decimal input handling."""

    def test_decimal_input_for_threshold(self):
        """Decimal threshold should be converted to float."""
        rule = MaxDrawdownRule(threshold_percent=Decimal("10.0"))

        assert rule.threshold_percent == 10.0
        assert isinstance(rule.threshold_percent, float)

    def test_decimal_input_in_context(self):
        """Decimal in context should be handled correctly."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": Decimal("7.0")})

        assert result.action == RuleAction.WARN
        assert result.current_value == 7.0

    def test_decimal_block_at_threshold(self):
        """Decimal at threshold should BLOCK."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": Decimal("10.0")})

        assert result.action == RuleAction.BLOCK


class TestMaxDrawdownRuleRepr:
    """Tests for __repr__ method."""

    def test_repr_includes_threshold(self):
        """Repr should include threshold."""
        rule = MaxDrawdownRule(threshold_percent=10.0)

        assert "10.0%" in repr(rule)

    def test_repr_includes_reference(self):
        """Repr should include reference."""
        rule = MaxDrawdownRule(reference="initial_balance")

        assert "initial_balance" in repr(rule)

    def test_repr_includes_warnings(self):
        """Repr should include warning thresholds."""
        rule = MaxDrawdownRule(warning_at=[50.0, 70.0, 85.0])

        assert "[50.0, 70.0, 85.0]" in repr(rule)


class TestMaxDrawdownRuleRuleResultProperties:
    """Tests for RuleResult helper properties."""

    def test_allow_is_allowed_true(self):
        """ALLOW result is_allowed should be True."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 4.0})

        assert result.is_allowed is True

    def test_warn_is_allowed_true(self):
        """WARN result is_allowed should be True (allows with warning)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 7.0})

        assert result.is_allowed is True

    def test_block_is_allowed_false(self):
        """BLOCK result is_allowed should be False."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 10.0})

        assert result.is_allowed is False

    def test_allow_is_blocked_false(self):
        """ALLOW result is_blocked should be False."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 4.0})

        assert result.is_blocked is False

    def test_warn_is_blocked_false(self):
        """WARN result is_blocked should be False."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 7.0})

        assert result.is_blocked is False

    def test_block_is_blocked_true(self):
        """BLOCK result is_blocked should be True."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 10.0})

        assert result.is_blocked is True


class TestMaxDrawdownRuleMissingContext:
    """Tests for handling missing context data."""

    def test_missing_total_drawdown_percent_defaults_to_zero(self):
        """Missing total_drawdown_percent should default to 0.0."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({})

        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0

    def test_empty_context_allows(self):
        """Empty context should ALLOW (no drawdown)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({})

        assert result.action == RuleAction.ALLOW


class TestMaxDrawdownRuleInvalidConfig:
    """Tests for invalid configuration handling."""

    def test_zero_threshold_logs_warning(self, caplog):
        """Zero threshold should log a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            rule = MaxDrawdownRule(threshold_percent=0.0)

        assert "invalid threshold_percent=0.00" in caplog.text
        assert "must be > 0" in caplog.text

    def test_negative_threshold_logs_warning(self, caplog):
        """Negative threshold should log a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            rule = MaxDrawdownRule(threshold_percent=-10.0)

        assert "invalid threshold_percent=-10.00" in caplog.text

    def test_zero_threshold_blocks_any_drawdown(self):
        """Zero threshold blocks any drawdown (edge case behavior)."""
        rule = MaxDrawdownRule(threshold_percent=0.0)
        result = rule.validate({"total_drawdown_percent": 0.01})

        # Any drawdown >= 0 threshold triggers block
        assert result.action == RuleAction.BLOCK


class TestMaxDrawdownRuleEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_exactly_at_50_percent_warns(self):
        """Exactly at 50% should warn (inclusive)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        # Exactly 50% of 10% = 5%
        result = rule.validate({"total_drawdown_percent": 5.0})

        assert result.action == RuleAction.WARN

    def test_just_under_50_percent_allows(self):
        """Just under 50% should allow."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        # 49.9% of 10% = 4.99%
        result = rule.validate({"total_drawdown_percent": 4.99})

        assert result.action == RuleAction.ALLOW

    def test_exactly_at_threshold_blocks(self):
        """Exactly at threshold should block (inclusive)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        result = rule.validate({"total_drawdown_percent": 10.0})

        assert result.action == RuleAction.BLOCK

    def test_just_under_threshold_warns(self):
        """Just under threshold should warn (85%)."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        # 9.99% is 99.9% of 10% - should warn at 85%
        result = rule.validate({"total_drawdown_percent": 9.99})

        assert result.action == RuleAction.WARN

    def test_very_small_threshold(self):
        """Very small threshold should work."""
        rule = MaxDrawdownRule(threshold_percent=0.5)
        result = rule.validate({"total_drawdown_percent": 0.5})

        assert result.action == RuleAction.BLOCK

    def test_very_large_threshold(self):
        """Very large threshold should work."""
        rule = MaxDrawdownRule(threshold_percent=50.0)
        result = rule.validate({"total_drawdown_percent": 20.0})  # 40% of limit

        assert result.action == RuleAction.ALLOW


class TestMaxDrawdownRuleAcceptanceCriteria:
    """Tests specifically for the story acceptance criteria."""

    def test_ac1_allow_at_9_percent_drawdown(self):
        """AC1: Given 10% max drawdown, at 9% drawdown, trading is ALLOWED."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        # $100,000 initial balance, equity at $91,000 = 9% drawdown
        result = rule.validate({"total_drawdown_percent": 9.0})

        assert result.action == RuleAction.WARN  # 9% is 90% of limit, triggers 85% warning
        assert result.is_allowed  # But still allowed to trade

    def test_ac2_block_at_10_percent_drawdown(self):
        """AC2: Given equity at 10% drawdown, trading is BLOCKED."""
        rule = MaxDrawdownRule(threshold_percent=10.0)
        # $100,000 initial balance, equity at $90,000 = 10% drawdown
        result = rule.validate({"total_drawdown_percent": 10.0})

        assert result.action == RuleAction.BLOCK
        assert "Max drawdown" in result.message

    def test_ac3_warning_at_70_percent_of_limit(self):
        """AC3: At 7% drawdown (70% of 10% limit), WARNING is generated."""
        rule = MaxDrawdownRule(threshold_percent=10.0, warning_at=[50, 70, 85])
        # $100,000 peak, equity at $93,000 = 7% drawdown
        result = rule.validate({"total_drawdown_percent": 7.0})

        assert result.action == RuleAction.WARN
        assert "70%" in result.message

    def test_ac4_custom_5_percent_limit(self):
        """AC4: Custom 5% max drawdown blocks at 5%."""
        rule = MaxDrawdownRule(threshold_percent=5.0)
        result = rule.validate({"total_drawdown_percent": 5.0})

        assert result.action == RuleAction.BLOCK

    def test_ac5_multiple_warning_thresholds(self):
        """AC5: Multiple warning thresholds generate separate warnings."""
        rule = MaxDrawdownRule(threshold_percent=10.0, warning_at=[50, 70, 85])

        # At 50% usage (5% drawdown)
        result = rule.validate({"total_drawdown_percent": 5.0})
        assert result.action == RuleAction.WARN
        assert result.metadata["warning_threshold"] == 50.0

        # At 70% usage (7% drawdown)
        result = rule.validate({"total_drawdown_percent": 7.0})
        assert result.action == RuleAction.WARN
        assert result.metadata["warning_threshold"] == 70.0

        # At 85% usage (8.5% drawdown)
        result = rule.validate({"total_drawdown_percent": 8.5})
        assert result.action == RuleAction.WARN
        assert result.metadata["warning_threshold"] == 85.0

    def test_ac6_reference_configuration_accepted(self):
        """AC6: reference: 'initial_balance' is accepted."""
        rule = MaxDrawdownRule(
            threshold_percent=10.0,
            reference="initial_balance",
        )
        assert rule.reference == "initial_balance"

        # Verify it's included in BLOCK metadata
        result = rule.validate({"total_drawdown_percent": 10.0})
        assert result.metadata["reference"] == "initial_balance"


# ===========================================================================
# Epic 9 P0.6: drawdown method (equity_peak vs balance_based)
# ===========================================================================


class TestMaxDrawdownRuleMethodInit:
    """Tests for the new ``method`` parameter introduced by P0.6."""

    def test_default_method_is_equity_peak(self):
        # Preserves existing behaviour for callers that don't specify a method.
        rule = MaxDrawdownRule()
        assert rule.method == "equity_peak"

    def test_custom_method_balance_based(self):
        rule = MaxDrawdownRule(method="balance_based")
        assert rule.method == "balance_based"

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError, match="method"):
            MaxDrawdownRule(method="from_atlantis")


class TestMaxDrawdownRuleEquityPeakMethod:
    """``method='equity_peak'`` reads ``total_drawdown_percent`` from context."""

    def test_block_above_threshold(self):
        rule = MaxDrawdownRule(threshold_percent=10.0, method="equity_peak")
        result = rule.validate({"total_drawdown_percent": 10.5})
        assert result.action == RuleAction.BLOCK

    def test_ignores_balance_fields(self):
        # Even if initial_balance / current_equity disagree, equity_peak relies
        # only on total_drawdown_percent. This is the load-bearing invariant.
        rule = MaxDrawdownRule(threshold_percent=10.0, method="equity_peak")
        ctx = {
            "total_drawdown_percent": 2.0,
            "initial_balance": 100000.0,
            "current_equity": 50000.0,  # Would be 50% balance_based
        }
        result = rule.validate(ctx)
        assert result.action == RuleAction.ALLOW

    def test_metadata_records_method(self):
        rule = MaxDrawdownRule(threshold_percent=10.0, method="equity_peak")
        result = rule.validate({"total_drawdown_percent": 10.5})
        assert result.metadata["method"] == "equity_peak"


class TestMaxDrawdownRuleBalanceBasedMethod:
    """``method='balance_based'`` computes drawdown vs ``initial_balance``."""

    def _ctx(self, **kw):
        # Total_drawdown_percent intentionally absent / wrong to prove it's not used.
        base = {"initial_balance": 100000.0, "current_equity": 100000.0}
        base.update(kw)
        return base

    def test_allow_at_par_equity(self):
        rule = MaxDrawdownRule(threshold_percent=10.0, method="balance_based")
        result = rule.validate(self._ctx(current_equity=100000.0))
        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0

    def test_allow_when_in_profit(self):
        rule = MaxDrawdownRule(threshold_percent=10.0, method="balance_based")
        # Equity above initial_balance → no drawdown
        result = rule.validate(self._ctx(current_equity=108000.0))
        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0

    def test_warn_at_70_percent_of_threshold(self):
        rule = MaxDrawdownRule(threshold_percent=10.0, method="balance_based")
        # 7% drawdown = 70% of 10% threshold → WARN at 70 warning level
        result = rule.validate(self._ctx(current_equity=93000.0))
        assert result.action == RuleAction.WARN
        assert result.current_value == pytest.approx(7.0, abs=0.001)

    def test_block_at_threshold(self):
        rule = MaxDrawdownRule(threshold_percent=10.0, method="balance_based")
        # 10% drawdown exactly
        result = rule.validate(self._ctx(current_equity=90000.0))
        assert result.action == RuleAction.BLOCK
        assert result.current_value == pytest.approx(10.0, abs=0.001)

    def test_balance_based_ignores_total_drawdown_percent(self):
        # Even if total_drawdown_percent says 50, balance_based only looks at
        # the current_equity vs initial_balance ratio.
        rule = MaxDrawdownRule(threshold_percent=10.0, method="balance_based")
        ctx = self._ctx(current_equity=99000.0, total_drawdown_percent=50.0)
        result = rule.validate(ctx)
        assert result.action == RuleAction.ALLOW  # Only 1% balance_based DD
        assert result.current_value == pytest.approx(1.0, abs=0.001)

    def test_zero_initial_balance_returns_allow(self):
        # Defensive: avoid div-by-zero. No way to compute a meaningful DD,
        # so pass through as ALLOW rather than crash.
        rule = MaxDrawdownRule(threshold_percent=10.0, method="balance_based")
        ctx = self._ctx(initial_balance=0.0, current_equity=0.0)
        result = rule.validate(ctx)
        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0

    def test_decimal_inputs(self):
        rule = MaxDrawdownRule(threshold_percent=10.0, method="balance_based")
        ctx = {
            "initial_balance": Decimal("100000"),
            "current_equity": Decimal("89000"),  # 11% DD
        }
        result = rule.validate(ctx)
        assert result.action == RuleAction.BLOCK

    def test_metadata_records_method(self):
        rule = MaxDrawdownRule(threshold_percent=10.0, method="balance_based")
        ctx = self._ctx(current_equity=89000.0)
        result = rule.validate(ctx)
        assert result.metadata["method"] == "balance_based"

    def test_get_current_value_uses_balance_based(self):
        rule = MaxDrawdownRule(threshold_percent=10.0, method="balance_based")
        ctx = self._ctx(current_equity=95000.0)
        assert rule.get_current_value(ctx) == pytest.approx(5.0, abs=0.001)

    def test_get_current_value_returns_zero_in_profit(self):
        rule = MaxDrawdownRule(threshold_percent=10.0, method="balance_based")
        ctx = self._ctx(current_equity=110000.0)
        assert rule.get_current_value(ctx) == 0.0
