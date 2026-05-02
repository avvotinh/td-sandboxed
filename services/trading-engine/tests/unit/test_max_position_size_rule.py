"""Unit tests for MaxPositionSizeRule (Story 4.4).

Tests cover:
- ALLOW when below limit
- ALLOW when exactly at limit
- BLOCK when above limit
- BLOCK when total exposure exceeds limit
- Scaling with per_10k_balance
- WARN at warning thresholds (70%, 80%, 90%)
- RuleResult includes current_value and threshold_value
- Protocol method implementations (get_current_value, get_threshold, get_warning_thresholds)
- Custom warning thresholds
- Decimal input handling
- Invalid configuration handling
"""

from decimal import Decimal

import pytest

from src.rules.base_rule import RuleAction
from src.rules.types.position import MaxPositionSizeRule


class TestMaxPositionSizeRuleInit:
    """Tests for MaxPositionSizeRule initialization."""

    def test_default_max_lots_is_1(self):
        """Default max_lots should be 1.0."""
        rule = MaxPositionSizeRule()
        assert rule.max_lots == 1.0

    def test_custom_max_lots(self):
        """Custom max_lots should be configurable."""
        rule = MaxPositionSizeRule(max_lots=5.0)
        assert rule.max_lots == 5.0

    def test_default_warning_thresholds(self):
        """Default warning thresholds should be [70, 80, 90]."""
        rule = MaxPositionSizeRule()
        assert rule.warning_at == [70.0, 80.0, 90.0]

    def test_custom_warning_thresholds(self):
        """Custom warning thresholds should be configurable."""
        rule = MaxPositionSizeRule(warning_at=[50.0, 75.0, 95.0])
        assert rule.warning_at == [50.0, 75.0, 95.0]

    def test_warning_thresholds_are_sorted(self):
        """Warning thresholds should be sorted ascending."""
        rule = MaxPositionSizeRule(warning_at=[90.0, 50.0, 75.0])
        assert rule.warning_at == [50.0, 75.0, 90.0]

    def test_default_scaling_is_none(self):
        """Default scaling should be None (fixed)."""
        rule = MaxPositionSizeRule()
        assert rule.scaling is None

    def test_custom_scaling_per_10k(self):
        """Scaling per_10k_balance should be configurable."""
        rule = MaxPositionSizeRule(scaling="per_10k_balance")
        assert rule.scaling == "per_10k_balance"

    def test_rule_type_is_max_position_size(self):
        """Rule type should be 'max_position_size'."""
        rule = MaxPositionSizeRule()
        assert rule.rule_type == "max_position_size"

    def test_priority_is_3(self):
        """Priority should be 3 (after daily loss and max drawdown)."""
        rule = MaxPositionSizeRule()
        assert rule.priority == 3

    def test_name_includes_max_lots(self):
        """Name should include max_lots."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        assert rule.name == "Position Size Limit 1.0 lots"

    def test_name_with_scaling_includes_scaling_info(self):
        """Name with scaling should include scaling info."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")
        assert "scaled" in rule.name.lower()
        assert "1.0" in rule.name

    def test_accepts_yaml_action_field(self):
        """Should accept action field from YAML (for compatibility)."""
        rule = MaxPositionSizeRule(action="block_trading")
        assert rule is not None

    def test_accepts_extra_kwargs(self):
        """Should accept extra kwargs for forward compatibility."""
        rule = MaxPositionSizeRule(future_field="future_value")
        assert rule is not None


class TestMaxPositionSizeRuleValidateAllow:
    """Tests for ALLOW scenarios (AC: 2, 5 - below or at limit)."""

    def test_allow_below_limit(self):
        """AC2: ALLOW when requested 0.5 lots of 1.0 limit."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.5, "current_position_lots": 0.0})

        assert result.action == RuleAction.ALLOW

    def test_allow_exactly_at_limit(self):
        """AC5: ALLOW when requested exactly at limit (1.0 of 1.0).

        Note: At 100% usage, rule returns WARN (highest warning threshold).
        Per AC5, trade is ALLOWED (WARN action is_allowed=True).
        """
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 1.0, "current_position_lots": 0.0})

        # At exactly the limit, usage is 100% which triggers 90% warning
        # but the trade is still ALLOWED (WARN is_allowed=True)
        assert result.is_allowed
        assert result.action == RuleAction.WARN  # At 100% triggers warning

    def test_allow_zero_request(self):
        """ALLOW when no position requested."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.0, "current_position_lots": 0.0})

        assert result.action == RuleAction.ALLOW

    def test_allow_negative_request_treated_as_zero(self):
        """ALLOW with negative request (edge case)."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": -0.5, "current_position_lots": 0.0})

        assert result.action == RuleAction.ALLOW

    def test_allow_current_value_in_result(self):
        """ALLOW result should include current_value."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.5, "current_position_lots": 0.0})

        assert result.current_value == 0.5

    def test_allow_threshold_value_in_result(self):
        """ALLOW result should include threshold_value."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.5, "current_position_lots": 0.0})

        assert result.threshold_value == 1.0


class TestMaxPositionSizeRuleValidateBlock:
    """Tests for BLOCK scenarios (AC: 1, 4 - above limit)."""

    def test_block_above_limit(self):
        """AC1: BLOCK when requested 1.5 lots of 1.0 limit."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 1.5, "current_position_lots": 0.0})

        assert result.action == RuleAction.BLOCK

    def test_block_message_format_single_order(self):
        """BLOCK message should include requested and limit for single order."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 1.5, "current_position_lots": 0.0})

        assert "1.5" in result.message
        assert "1.0" in result.message
        assert "exceeds" in result.message.lower()

    def test_block_total_exposure(self):
        """AC4: BLOCK when total exposure exceeds limit (0.5 + 0.8 > 1.0)."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.8, "current_position_lots": 0.5})

        assert result.action == RuleAction.BLOCK

    def test_block_total_exposure_message_format(self):
        """BLOCK message for total exposure should include breakdown."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.8, "current_position_lots": 0.5})

        assert "1.3" in result.message  # total exposure
        assert "current" in result.message.lower()
        assert "requested" in result.message.lower()

    def test_block_current_value_in_result(self):
        """BLOCK result should include current_value."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 1.5, "current_position_lots": 0.0})

        assert result.current_value == 1.5

    def test_block_threshold_value_in_result(self):
        """BLOCK result should include threshold_value."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 1.5, "current_position_lots": 0.0})

        assert result.threshold_value == 1.0

    def test_block_metadata_includes_rule_type(self):
        """BLOCK result should include rule_type in metadata."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 1.5, "current_position_lots": 0.0})

        assert result.metadata["rule_type"] == "max_position_size"

    def test_block_well_above_limit(self):
        """BLOCK when well above limit."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 5.0, "current_position_lots": 0.0})

        assert result.action == RuleAction.BLOCK


class TestMaxPositionSizeRuleScaling:
    """Tests for scaling logic (AC: 3)."""

    def test_scaling_per_10k_balance_allow(self):
        """AC3: ALLOW with scaling - $50k balance = 5.0 lots max, request 3.0."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")
        result = rule.validate({
            "requested_lots": 3.0,  # 60% of 5.0 max - below 70% warning
            "current_position_lots": 0.0,
            "account_balance": 50000.0,
        })

        assert result.action == RuleAction.ALLOW

    def test_scaling_per_10k_balance_block(self):
        """AC3: BLOCK with scaling - $50k balance = 5.0 lots max, request 6.0."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")
        result = rule.validate({
            "requested_lots": 6.0,
            "current_position_lots": 0.0,
            "account_balance": 50000.0,
        })

        assert result.action == RuleAction.BLOCK

    def test_scaling_exactly_at_limit(self):
        """WARN with scaling exactly at limit (5.0 of 5.0 with $50k).

        At 100% usage, trade is allowed but with warning.
        """
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")
        result = rule.validate({
            "requested_lots": 5.0,
            "current_position_lots": 0.0,
            "account_balance": 50000.0,
        })

        # At exactly limit (100%) - triggers warning but is_allowed=True
        assert result.is_allowed
        assert result.action == RuleAction.WARN

    def test_scaling_with_10k_balance(self):
        """ALLOW with $10k balance = 1.0 lot max, request 0.5 (50%)."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")
        result = rule.validate({
            "requested_lots": 0.5,  # 50% of limit - below warning
            "current_position_lots": 0.0,
            "account_balance": 10000.0,
        })

        assert result.action == RuleAction.ALLOW

    def test_scaling_with_100k_balance(self):
        """ALLOW with $100k balance = 10.0 lots max, request 6.0 (60%)."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")
        result = rule.validate({
            "requested_lots": 6.0,  # 60% of 10.0 max - below warning
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
        })

        assert result.action == RuleAction.ALLOW

    def test_scaling_threshold_value_is_scaled(self):
        """Threshold value should reflect scaled limit."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")
        result = rule.validate({
            "requested_lots": 4.0,
            "current_position_lots": 0.0,
            "account_balance": 50000.0,
        })

        assert result.threshold_value == 5.0  # $50k / $10k * 1.0 = 5.0

    def test_scaling_with_zero_balance_uses_fixed(self):
        """Zero balance should fall back to fixed limit."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")
        result = rule.validate({
            "requested_lots": 0.5,
            "current_position_lots": 0.0,
            "account_balance": 0.0,
        })

        assert result.threshold_value == 1.0  # Falls back to fixed

    def test_scaling_with_negative_balance_uses_fixed(self):
        """Negative balance should fall back to fixed limit."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")
        result = rule.validate({
            "requested_lots": 0.5,
            "current_position_lots": 0.0,
            "account_balance": -10000.0,
        })

        assert result.threshold_value == 1.0  # Falls back to fixed

    def test_scaling_with_decimal_balance(self):
        """Decimal balance should be handled correctly."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")
        result = rule.validate({
            "requested_lots": 3.0,  # 60% of 5.0 max - below warning
            "current_position_lots": 0.0,
            "account_balance": Decimal("50000.0"),
        })

        assert result.action == RuleAction.ALLOW

    def test_fixed_scaling_mode(self):
        """Fixed scaling mode should use max_lots directly."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="fixed")
        result = rule.validate({
            "requested_lots": 0.5,
            "current_position_lots": 0.0,
            "account_balance": 50000.0,  # Should be ignored
        })

        assert result.threshold_value == 1.0  # Fixed, not scaled

    def test_unknown_scaling_mode_falls_back_to_fixed(self, caplog):
        """Unknown scaling mode should fall back to fixed and log warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            rule = MaxPositionSizeRule(max_lots=1.0, scaling="unknown_mode")

        assert "Unknown scaling mode" in caplog.text
        assert rule.scaling is None  # Reset to None


class TestMaxPositionSizeRuleValidateWarn:
    """Tests for WARN scenarios (AC: 6 - at warning thresholds)."""

    def test_warn_at_70_percent_threshold(self):
        """WARN at 70% of limit (0.7 of 1.0)."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.7, "current_position_lots": 0.0})

        assert result.action == RuleAction.WARN

    def test_warn_at_80_percent_threshold(self):
        """AC6: WARN at 80% of limit (0.8 of 1.0)."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.8, "current_position_lots": 0.0})

        assert result.action == RuleAction.WARN

    def test_warn_at_90_percent_threshold(self):
        """WARN at 90% of limit (0.9 of 1.0)."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.9, "current_position_lots": 0.0})

        assert result.action == RuleAction.WARN

    def test_warn_returns_highest_applicable_threshold(self):
        """WARN should return highest applicable warning threshold."""
        rule = MaxPositionSizeRule(max_lots=1.0)

        # At 85% usage - should get 80% warning, not 70%
        result = rule.validate({"requested_lots": 0.85, "current_position_lots": 0.0})

        assert result.action == RuleAction.WARN
        assert result.metadata["warning_threshold"] == 80.0

    def test_warn_metadata_includes_warning_threshold(self):
        """WARN result should include warning_threshold in metadata."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.7, "current_position_lots": 0.0})

        assert "warning_threshold" in result.metadata
        assert result.metadata["warning_threshold"] == 70.0

    def test_warn_metadata_includes_usage_percent(self):
        """WARN result should include usage_percent in metadata."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.7, "current_position_lots": 0.0})

        assert "usage_percent" in result.metadata
        assert result.metadata["usage_percent"] == 70.0

    def test_warn_message_format(self):
        """WARN message should include relevant info."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.8, "current_position_lots": 0.0})

        assert "80%" in result.message
        assert "1.0" in result.message

    def test_warn_with_total_exposure(self):
        """WARN based on total exposure (0.3 + 0.4 = 70%)."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.4, "current_position_lots": 0.3})

        assert result.action == RuleAction.WARN


class TestMaxPositionSizeRuleProtocolMethods:
    """Tests for BaseRule protocol method implementations."""

    def test_get_current_value_extracts_from_context(self):
        """get_current_value should extract from context correctly."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        context = {"requested_lots": 0.5, "current_position_lots": 0.3}

        assert rule.get_current_value(context) == 0.8  # Total exposure

    def test_get_current_value_handles_only_requested(self):
        """get_current_value with only requested should work."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        context = {"requested_lots": 0.5}

        assert rule.get_current_value(context) == 0.5

    def test_get_current_value_defaults_to_zero(self):
        """get_current_value should default to 0.0 if missing."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        context = {}

        assert rule.get_current_value(context) == 0.0

    def test_get_current_value_handles_decimal(self):
        """get_current_value should handle Decimal input."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        context = {
            "requested_lots": Decimal("0.5"),
            "current_position_lots": Decimal("0.3"),
        }

        assert rule.get_current_value(context) == 0.8

    def test_get_current_value_uses_absolute_values(self):
        """get_current_value should use absolute values."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        context = {
            "requested_lots": -0.5,  # Negative edge case
            "current_position_lots": -0.3,  # Negative edge case
        }

        assert rule.get_current_value(context) == 0.8  # abs(0.5) + abs(0.3)

    def test_get_threshold_returns_configured_threshold(self):
        """get_threshold should return configured max_lots."""
        rule = MaxPositionSizeRule(max_lots=1.0)

        assert rule.get_threshold() == 1.0

    def test_get_threshold_with_custom_value(self):
        """get_threshold should return custom max_lots."""
        rule = MaxPositionSizeRule(max_lots=5.0)

        assert rule.get_threshold() == 5.0

    def test_get_threshold_returns_base_not_scaled(self):
        """get_threshold should return base max_lots, not scaled."""
        rule = MaxPositionSizeRule(max_lots=1.0, scaling="per_10k_balance")

        assert rule.get_threshold() == 1.0  # Base value, not scaled

    def test_get_warning_thresholds_returns_configured_list(self):
        """get_warning_thresholds should return configured list."""
        rule = MaxPositionSizeRule(max_lots=1.0)

        assert rule.get_warning_thresholds() == [70.0, 80.0, 90.0]

    def test_get_warning_thresholds_returns_copy(self):
        """get_warning_thresholds should return a copy (not modify original)."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        thresholds = rule.get_warning_thresholds()
        thresholds.append(95.0)

        assert rule.get_warning_thresholds() == [70.0, 80.0, 90.0]

    def test_get_warning_thresholds_with_custom_values(self):
        """get_warning_thresholds should return custom values."""
        rule = MaxPositionSizeRule(warning_at=[50.0, 75.0, 95.0])

        assert rule.get_warning_thresholds() == [50.0, 75.0, 95.0]


class TestMaxPositionSizeRuleCustomWarningThresholds:
    """Tests for custom warning threshold configurations."""

    def test_custom_50_75_95_warns_at_50(self):
        """Custom [50, 75, 95] should warn at 50%."""
        rule = MaxPositionSizeRule(
            max_lots=1.0,
            warning_at=[50.0, 75.0, 95.0],
        )
        result = rule.validate({"requested_lots": 0.5, "current_position_lots": 0.0})

        assert result.action == RuleAction.WARN
        assert result.metadata["warning_threshold"] == 50.0

    def test_custom_single_threshold(self):
        """Single warning threshold should work."""
        rule = MaxPositionSizeRule(
            max_lots=1.0,
            warning_at=[80.0],
        )
        result = rule.validate({"requested_lots": 0.8, "current_position_lots": 0.0})

        assert result.action == RuleAction.WARN

    def test_empty_warning_thresholds_no_warnings(self):
        """Empty warning list should never warn (ALLOW or BLOCK only)."""
        rule = MaxPositionSizeRule(
            max_lots=1.0,
            warning_at=[],
        )
        # 90% usage - should ALLOW since no warnings configured
        result = rule.validate({"requested_lots": 0.9, "current_position_lots": 0.0})

        assert result.action == RuleAction.ALLOW


class TestMaxPositionSizeRuleDecimalHandling:
    """Tests for Decimal input handling."""

    def test_decimal_input_for_max_lots(self):
        """Decimal max_lots should be converted to float."""
        rule = MaxPositionSizeRule(max_lots=Decimal("1.0"))

        assert rule.max_lots == 1.0
        assert isinstance(rule.max_lots, float)

    def test_decimal_input_in_context(self):
        """Decimal in context should be handled correctly."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({
            "requested_lots": Decimal("0.5"),
            "current_position_lots": Decimal("0.0"),
        })

        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.5

    def test_decimal_block_at_threshold(self):
        """Decimal exceeding threshold should BLOCK."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({
            "requested_lots": Decimal("1.5"),
            "current_position_lots": Decimal("0.0"),
        })

        assert result.action == RuleAction.BLOCK


class TestMaxPositionSizeRuleRepr:
    """Tests for __repr__ method."""

    def test_repr_includes_max_lots(self):
        """Repr should include max_lots."""
        rule = MaxPositionSizeRule(max_lots=1.0)

        assert "1.0" in repr(rule)

    def test_repr_includes_scaling(self):
        """Repr should include scaling."""
        rule = MaxPositionSizeRule(scaling="per_10k_balance")

        assert "per_10k_balance" in repr(rule)

    def test_repr_includes_warnings(self):
        """Repr should include warning thresholds."""
        rule = MaxPositionSizeRule(warning_at=[70.0, 80.0, 90.0])

        assert "[70.0, 80.0, 90.0]" in repr(rule)


class TestMaxPositionSizeRuleRuleResultProperties:
    """Tests for RuleResult helper properties."""

    def test_allow_is_allowed_true(self):
        """ALLOW result is_allowed should be True."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.5, "current_position_lots": 0.0})

        assert result.is_allowed is True

    def test_warn_is_allowed_true(self):
        """WARN result is_allowed should be True (allows with warning)."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.8, "current_position_lots": 0.0})

        assert result.is_allowed is True

    def test_block_is_allowed_false(self):
        """BLOCK result is_allowed should be False."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 1.5, "current_position_lots": 0.0})

        assert result.is_allowed is False

    def test_allow_is_blocked_false(self):
        """ALLOW result is_blocked should be False."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.5, "current_position_lots": 0.0})

        assert result.is_blocked is False

    def test_warn_is_blocked_false(self):
        """WARN result is_blocked should be False."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.8, "current_position_lots": 0.0})

        assert result.is_blocked is False

    def test_block_is_blocked_true(self):
        """BLOCK result is_blocked should be True."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 1.5, "current_position_lots": 0.0})

        assert result.is_blocked is True


class TestMaxPositionSizeRuleMissingContext:
    """Tests for handling missing context data."""

    def test_missing_requested_lots_defaults_to_zero(self):
        """Missing requested_lots should default to 0.0."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"current_position_lots": 0.5})

        assert result.action == RuleAction.ALLOW

    def test_missing_current_position_lots_defaults_to_zero(self):
        """Missing current_position_lots should default to 0.0."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.5})

        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.5

    def test_empty_context_allows(self):
        """Empty context should ALLOW (no position)."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({})

        assert result.action == RuleAction.ALLOW


class TestMaxPositionSizeRuleInvalidConfig:
    """Tests for invalid configuration handling."""

    def test_zero_max_lots_logs_warning(self, caplog):
        """Zero max_lots should log a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            rule = MaxPositionSizeRule(max_lots=0.0)

        assert "invalid max_lots=0.00" in caplog.text
        assert "must be > 0" in caplog.text

    def test_negative_max_lots_logs_warning(self, caplog):
        """Negative max_lots should log a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            rule = MaxPositionSizeRule(max_lots=-1.0)

        assert "invalid max_lots=-1.00" in caplog.text


class TestMaxPositionSizeRuleEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_exactly_at_70_percent_warns(self):
        """Exactly at 70% should warn (inclusive)."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.7, "current_position_lots": 0.0})

        assert result.action == RuleAction.WARN

    def test_just_under_70_percent_allows(self):
        """Just under 70% should allow."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.69, "current_position_lots": 0.0})

        assert result.action == RuleAction.ALLOW

    def test_exactly_at_limit_allows(self):
        """Exactly at limit should allow with warning (AC5).

        At 100% usage, trade is allowed but with warning.
        """
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 1.0, "current_position_lots": 0.0})

        # At exactly limit, is_allowed=True but with warning
        assert result.is_allowed
        assert result.action == RuleAction.WARN

    def test_just_above_limit_blocks(self):
        """Just above limit should block."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 1.01, "current_position_lots": 0.0})

        assert result.action == RuleAction.BLOCK

    def test_very_small_max_lots(self):
        """Very small max_lots should work."""
        rule = MaxPositionSizeRule(max_lots=0.01)
        # Request 60% of limit to be below warning threshold
        result = rule.validate({"requested_lots": 0.006, "current_position_lots": 0.0})

        assert result.action == RuleAction.ALLOW

    def test_very_large_max_lots(self):
        """Very large max_lots should work."""
        rule = MaxPositionSizeRule(max_lots=1000.0)
        result = rule.validate({"requested_lots": 500.0, "current_position_lots": 0.0})

        assert result.action == RuleAction.ALLOW

    def test_total_exposure_exactly_at_limit(self):
        """Total exposure exactly at limit should allow with warning.

        At 100% usage, trade is allowed but with warning.
        """
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.5, "current_position_lots": 0.5})

        # At exactly limit, is_allowed=True but with warning
        assert result.is_allowed
        assert result.action == RuleAction.WARN

    def test_total_exposure_just_over_limit(self):
        """Total exposure just over limit should block."""
        rule = MaxPositionSizeRule(max_lots=1.0)
        result = rule.validate({"requested_lots": 0.51, "current_position_lots": 0.5})

        assert result.action == RuleAction.BLOCK
