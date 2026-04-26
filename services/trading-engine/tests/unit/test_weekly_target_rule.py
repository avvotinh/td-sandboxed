"""Unit tests for WeeklyTargetRule (Epic 9 Phase 0, task P0.8).

Informational rule: tracks weekly profit target. Never blocks. WARNs once
the target is met so the trader / ops dashboards know progress without
the rule getting in the way of trading.

Reads ``weekly_pnl_percent`` from context — caller (a future weekly
profit tracker) is responsible for computing the rolling Mon-Sun value.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.rules.base_rule import RuleAction
from src.rules.types.targets import WeeklyTargetRule


class TestWeeklyTargetRuleInit:
    def test_default_threshold_is_1_25_percent(self):
        # The5ers Bootstrap default
        rule = WeeklyTargetRule()
        assert rule.threshold_percent == 1.25

    def test_custom_threshold(self):
        rule = WeeklyTargetRule(threshold_percent=2.0)
        assert rule.threshold_percent == 2.0

    def test_rule_type_is_weekly_target(self):
        assert WeeklyTargetRule.rule_type == "weekly_target"

    def test_priority_is_100(self):
        # Informational — evaluated after all blocking rules.
        assert WeeklyTargetRule.priority == 100

    def test_name_includes_threshold(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        assert "1.25" in rule.name

    def test_zero_or_negative_threshold_logs_warning(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            WeeklyTargetRule(threshold_percent=0.0)
        assert any("threshold" in rec.message.lower() for rec in caplog.records)

    def test_accepts_yaml_action_field(self):
        rule = WeeklyTargetRule(action="notify")
        assert rule is not None

    def test_accepts_extra_kwargs(self):
        rule = WeeklyTargetRule(future_field="future_value")
        assert rule is not None


class TestWeeklyTargetRuleValidate:
    def test_allow_when_below_target(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        ctx = {"weekly_pnl_percent": 0.5}
        result = rule.validate(ctx)
        assert result.action == RuleAction.ALLOW

    def test_warn_when_at_target(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        ctx = {"weekly_pnl_percent": 1.25}
        result = rule.validate(ctx)
        assert result.action == RuleAction.WARN

    def test_warn_when_above_target(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        ctx = {"weekly_pnl_percent": 2.5}
        result = rule.validate(ctx)
        assert result.action == RuleAction.WARN

    def test_allow_when_in_loss(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        ctx = {"weekly_pnl_percent": -0.8}
        result = rule.validate(ctx)
        assert result.action == RuleAction.ALLOW

    def test_never_returns_block(self):
        # Informational rule: even at 1000% weekly profit, no BLOCK.
        rule = WeeklyTargetRule(threshold_percent=1.25)
        for value in [-50.0, 0.0, 1.0, 1.25, 5.0, 1000.0]:
            ctx = {"weekly_pnl_percent": value}
            assert rule.validate(ctx).action != RuleAction.BLOCK

    def test_decimal_input(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        ctx = {"weekly_pnl_percent": Decimal("1.5")}
        assert rule.validate(ctx).action == RuleAction.WARN

    def test_missing_key_defaults_to_zero(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        result = rule.validate({})
        assert result.action == RuleAction.ALLOW

    def test_metadata_records_rule_type_and_threshold(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        result = rule.validate({"weekly_pnl_percent": 1.5})
        assert result.metadata["rule_type"] == "weekly_target"
        assert result.metadata["weekly_pnl_percent"] == pytest.approx(1.5)

    def test_current_value_reports_weekly_pnl_percent(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        result = rule.validate({"weekly_pnl_percent": 1.5})
        assert result.current_value == pytest.approx(1.5)
        assert result.threshold_value == pytest.approx(1.25)


class TestWeeklyTargetRuleCoerce:
    """``_coerce`` must accept the messy types YAML/runtime can throw at it."""

    def test_string_numeric_input_coerced(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        ctx = {"weekly_pnl_percent": "1.5"}
        assert rule.validate(ctx).action == RuleAction.WARN

    def test_none_input_treated_as_zero(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        ctx = {"weekly_pnl_percent": None}
        assert rule.validate(ctx).action == RuleAction.ALLOW

    def test_garbage_input_logs_warning_and_allows(self, caplog):
        import logging

        rule = WeeklyTargetRule(threshold_percent=1.25)
        with caplog.at_level(logging.WARNING):
            result = rule.validate({"weekly_pnl_percent": "not-a-number"})
        assert result.action == RuleAction.ALLOW
        assert any("non-numeric" in r.message for r in caplog.records)


class TestWeeklyTargetRuleProtocol:
    def test_get_current_value(self):
        rule = WeeklyTargetRule(threshold_percent=1.25)
        assert rule.get_current_value({"weekly_pnl_percent": 1.5}) == pytest.approx(1.5)

    def test_get_current_value_clips_negative_to_zero(self):
        # Progress toward a target can't be negative — losses report as 0
        rule = WeeklyTargetRule(threshold_percent=1.25)
        assert rule.get_current_value({"weekly_pnl_percent": -0.5}) == 0.0

    def test_get_threshold(self):
        rule = WeeklyTargetRule(threshold_percent=2.0)
        assert rule.get_threshold() == 2.0

    def test_get_warning_thresholds_returns_empty_list(self):
        # Single-target informational rule has no intermediate warnings
        rule = WeeklyTargetRule()
        assert rule.get_warning_thresholds() == []
