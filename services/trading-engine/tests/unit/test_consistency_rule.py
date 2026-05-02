"""Unit tests for ConsistencyRule (Epic 9 Phase 0, task P0.7).

The consistency rule guards against FTMO-style "single best day" violations:

    today_pnl / (today_pnl + sum(positive prior days)) > block_at

Real-time variant — context provides ``current_day_pnl`` plus
``daily_profits_history`` (a dict of *prior* days only, today excluded).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.rules.base_rule import RuleAction
from src.rules.types.consistency import ConsistencyRule


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestConsistencyRuleInit:
    def test_default_block_is_50(self):
        rule = ConsistencyRule()
        assert rule.block_at == 50.0

    def test_default_warn_thresholds(self):
        rule = ConsistencyRule()
        assert rule.warn_at == [40.0, 45.0, 48.0]

    def test_custom_block(self):
        rule = ConsistencyRule(block_at=45.0)
        assert rule.block_at == 45.0

    def test_custom_warn(self):
        rule = ConsistencyRule(warn_at=[30.0, 35.0])
        assert rule.warn_at == [30.0, 35.0]

    def test_warn_thresholds_sorted(self):
        rule = ConsistencyRule(warn_at=[48.0, 40.0, 45.0])
        assert rule.warn_at == [40.0, 45.0, 48.0]

    def test_rule_type_is_consistency(self):
        assert ConsistencyRule.rule_type == "consistency"

    def test_block_at_zero_is_invalid(self):
        with pytest.raises(ValueError, match="block_at"):
            ConsistencyRule(block_at=0.0)

    def test_block_at_above_100_is_invalid(self):
        with pytest.raises(ValueError, match="block_at"):
            ConsistencyRule(block_at=101.0)

    def test_warn_at_or_above_block_is_invalid(self):
        with pytest.raises(ValueError, match="warn_at"):
            ConsistencyRule(warn_at=[40.0, 50.0], block_at=50.0)

    def test_accepts_yaml_action_field(self):
        rule = ConsistencyRule(action="block_trading")
        assert rule is not None

    def test_accepts_extra_kwargs(self):
        rule = ConsistencyRule(future_field="future_value")
        assert rule is not None

    def test_name_includes_block_threshold(self):
        rule = ConsistencyRule(block_at=45.0)
        assert "45" in rule.name


# ---------------------------------------------------------------------------
# validate() — non-applicable cases (return ALLOW)
# ---------------------------------------------------------------------------


class TestConsistencyRuleNonApplicable:
    """Rule short-circuits to ALLOW when there's nothing to evaluate."""

    def test_loss_day_returns_allow(self):
        rule = ConsistencyRule()
        ctx = {"current_day_pnl": -100.0, "daily_profits_history": {}}
        assert rule.validate(ctx).action == RuleAction.ALLOW

    def test_zero_today_returns_allow(self):
        rule = ConsistencyRule()
        ctx = {"current_day_pnl": 0.0, "daily_profits_history": {}}
        assert rule.validate(ctx).action == RuleAction.ALLOW

    def test_missing_current_day_pnl_returns_allow(self):
        rule = ConsistencyRule()
        # Defensive: missing key → treat as 0 → ALLOW
        ctx = {"daily_profits_history": {}}
        assert rule.validate(ctx).action == RuleAction.ALLOW


# ---------------------------------------------------------------------------
# validate() — applicable cases
# ---------------------------------------------------------------------------


class TestConsistencyRuleApplicable:
    """When today is profitable, the rule computes the ratio."""

    def test_first_profitable_day_with_no_history_allows(self):
        # FTMO consistency only applies once at least one prior profitable
        # day exists — a green day-1 would otherwise show 100% concentration
        # and spuriously BLOCK on the very first profitable bar.
        rule = ConsistencyRule()
        ctx = {"current_day_pnl": 500.0, "daily_profits_history": {}}
        result = rule.validate(ctx)
        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0

    def test_history_with_only_negative_days_treated_as_no_history(self):
        # All prior days were losses → still no positive prior history → ALLOW.
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 500.0,
            "daily_profits_history": {
                date(2026, 4, 1): -200.0,
                date(2026, 4, 2): -300.0,
            },
        }
        result = rule.validate(ctx)
        assert result.action == RuleAction.ALLOW
        assert result.current_value == 0.0

    def test_today_50_percent_of_total_blocks(self):
        # Today $500, history $500 → today is 50% → BLOCK at default threshold
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 500.0,
            "daily_profits_history": {date(2026, 4, 1): 500.0},
        }
        result = rule.validate(ctx)
        assert result.action == RuleAction.BLOCK

    def test_today_just_above_block_threshold_blocks(self):
        # Today $501, history $500 → today is ~50.05% → BLOCK
        rule = ConsistencyRule(block_at=50.0)
        ctx = {
            "current_day_pnl": 501.0,
            "daily_profits_history": {date(2026, 4, 1): 500.0},
        }
        assert rule.validate(ctx).action == RuleAction.BLOCK

    def test_today_below_lowest_warn_allows(self):
        # Today $100, history $1000 → today is ~9% → ALLOW
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 100.0,
            "daily_profits_history": {
                date(2026, 4, 1): 500.0,
                date(2026, 4, 2): 500.0,
            },
        }
        result = rule.validate(ctx)
        assert result.action == RuleAction.ALLOW

    def test_today_at_lowest_warn_threshold(self):
        # Today $400, history $600 → today is 40% → WARN at 40 threshold
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 400.0,
            "daily_profits_history": {date(2026, 4, 1): 600.0},
        }
        result = rule.validate(ctx)
        assert result.action == RuleAction.WARN
        assert result.metadata["warn_threshold"] == 40.0

    def test_today_at_45_warn_uses_highest_applicable(self):
        # Today $450, history $550 → 45% → WARN at 45 (not 40)
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 450.0,
            "daily_profits_history": {date(2026, 4, 1): 550.0},
        }
        result = rule.validate(ctx)
        assert result.action == RuleAction.WARN
        assert result.metadata["warn_threshold"] == 45.0

    def test_today_at_48_warn_uses_highest_applicable(self):
        # Today $480, history $520 → 48% → WARN at 48 (highest)
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 480.0,
            "daily_profits_history": {date(2026, 4, 1): 520.0},
        }
        result = rule.validate(ctx)
        assert result.action == RuleAction.WARN
        assert result.metadata["warn_threshold"] == 48.0

    def test_negative_history_days_ignored(self):
        # History has both positive and negative days; only positive sum matters.
        # Today $300, history positive sum $500 (700 + (-200) ignored) → ratio 37.5%
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 300.0,
            "daily_profits_history": {
                date(2026, 4, 1): 500.0,
                date(2026, 4, 2): -200.0,  # ignored
            },
        }
        result = rule.validate(ctx)
        assert result.action == RuleAction.ALLOW
        assert result.current_value == pytest.approx(37.5, abs=0.001)

    def test_zero_history_days_ignored(self):
        # Days with zero pnl don't affect the sum either.
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 200.0,
            "daily_profits_history": {
                date(2026, 4, 1): 800.0,
                date(2026, 4, 2): 0.0,  # ignored
                date(2026, 4, 3): -100.0,  # ignored
            },
        }
        result = rule.validate(ctx)
        # Today $200 / total $1000 = 20% → ALLOW
        assert result.action == RuleAction.ALLOW
        assert result.current_value == pytest.approx(20.0, abs=0.001)

    def test_decimal_inputs(self):
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": Decimal("500"),
            "daily_profits_history": {
                date(2026, 4, 1): Decimal("500"),
            },
        }
        assert rule.validate(ctx).action == RuleAction.BLOCK


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestConsistencyRuleMetadata:
    def test_block_metadata_records_ratio_and_block_threshold(self):
        rule = ConsistencyRule(block_at=50.0)
        ctx = {
            "current_day_pnl": 500.0,
            "daily_profits_history": {date(2026, 4, 1): 500.0},
        }
        result = rule.validate(ctx)
        assert result.metadata["rule_type"] == "consistency"
        assert result.metadata["ratio_percent"] == pytest.approx(50.0, abs=0.001)
        assert result.metadata["block_at"] == 50.0

    def test_warn_metadata_records_ratio(self):
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 400.0,
            "daily_profits_history": {date(2026, 4, 1): 600.0},
        }
        result = rule.validate(ctx)
        assert result.metadata["ratio_percent"] == pytest.approx(40.0, abs=0.001)


# ---------------------------------------------------------------------------
# Protocol methods
# ---------------------------------------------------------------------------


class TestConsistencyRuleProtocol:
    def test_get_current_value_returns_ratio(self):
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 250.0,
            "daily_profits_history": {date(2026, 4, 1): 750.0},
        }
        assert rule.get_current_value(ctx) == pytest.approx(25.0, abs=0.001)

    def test_get_current_value_zero_for_loss_day(self):
        rule = ConsistencyRule()
        ctx = {"current_day_pnl": -100.0, "daily_profits_history": {}}
        assert rule.get_current_value(ctx) == 0.0

    def test_get_threshold_returns_block_at(self):
        rule = ConsistencyRule(block_at=45.0)
        assert rule.get_threshold() == 45.0

    def test_get_warning_thresholds_returns_copy(self):
        rule = ConsistencyRule(warn_at=[30.0, 35.0])
        # Returned list mutation does not affect the rule
        thresholds = rule.get_warning_thresholds()
        thresholds.append(99.0)
        assert rule.warn_at == [30.0, 35.0]
