"""Unit tests for ``src.backtesting.dataset.compliance``.

The compliance harness wires the prop-firm rule set into the backtest
with **timezone-aware daily reset** (Epic 9.5) and the
**ConsistencyRule** (Epic 9.7) — Decision §4 / Risk R4 in
``docs/epic-12-context.md``. It also exposes assertion helpers that
12.7's experiment uses to refuse passing strategies that breached any
rule during simulation.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.backtesting.dataset.compliance import (
    BreachSummary,
    ComplianceBreachError,
    ComplianceProfile,
    assert_no_breaches,
    build_compliance_rule_engine,
    summarize_breaches,
)
from src.backtesting.metrics.schema import (
    DrawdownMetrics,
    PnlMetrics,
    PropFirmComplianceMetrics,
    PropFirmMetricsSchema,
    RiskMetrics,
    TradeMetrics,
)
from src.backtesting.prop_firm_preset import PropFirmPreset
from src.backtesting.result import BacktestResult, BreachEvent
from src.rules.types.consistency import ConsistencyRule
from src.rules.types.drawdown import DailyLossLimitRule, MaxDrawdownRule


pytestmark = pytest.mark.unit


# --- ComplianceProfile -------------------------------------------------


class TestComplianceProfile:
    def test_for_ftmo_matches_decision_section_4(self) -> None:
        # Decision §4 wires the FTMO-specific rule set: daily loss 5% CET,
        # max DD 10% (challenge), consistency 50% block. These match
        # configs/firms/ftmo.yaml exactly.
        profile = ComplianceProfile.for_ftmo()
        assert profile.daily_loss_pct == 5.0
        assert profile.max_drawdown_pct == 10.0
        assert profile.session_timezone == "CET"
        assert profile.daily_reset_time == "00:00"
        assert profile.consistency_block_at == 50.0
        assert profile.max_drawdown_method == "balance_based"

    def test_from_preset_uses_preset_thresholds(self) -> None:
        preset = PropFirmPreset(
            name="FTMO Challenge",
            daily_loss_pct=5.0,
            max_drawdown_pct=10.0,
            profit_target_pct=10.0,
            min_trading_days=4,
            max_position_lots=100.0,
        )
        profile = ComplianceProfile.from_preset(
            preset,
            session_timezone="CET",
            consistency_block_at=50.0,
        )
        assert profile.daily_loss_pct == 5.0
        assert profile.max_drawdown_pct == 10.0
        assert profile.session_timezone == "CET"
        assert profile.consistency_block_at == 50.0

    def test_default_session_timezone_is_utc(self) -> None:
        # An over-wide default is dangerous (a CET firm running with UTC
        # daily reset would drop the last 2h of trading into the wrong
        # session). UTC is the conservative no-op default for non-FTMO
        # callers; FTMO wiring must override explicitly.
        preset = PropFirmPreset(
            name="x",
            daily_loss_pct=5.0,
            max_drawdown_pct=10.0,
            profit_target_pct=10.0,
            min_trading_days=4,
            max_position_lots=100.0,
        )
        profile = ComplianceProfile.from_preset(preset)
        assert profile.session_timezone == "UTC"
        assert profile.consistency_block_at is None

    def test_is_frozen(self) -> None:
        profile = ComplianceProfile.for_ftmo()
        with pytest.raises((AttributeError, TypeError)):
            profile.daily_loss_pct = 999.0  # type: ignore[misc]

    def test_rejects_non_positive_daily_loss(self) -> None:
        with pytest.raises(ValueError, match="daily_loss_pct"):
            ComplianceProfile(daily_loss_pct=0.0, max_drawdown_pct=10.0)

    def test_rejects_non_positive_max_dd(self) -> None:
        with pytest.raises(ValueError, match="max_drawdown_pct"):
            ComplianceProfile(daily_loss_pct=5.0, max_drawdown_pct=0.0)

    def test_rejects_unknown_dd_method(self) -> None:
        with pytest.raises(ValueError, match="max_drawdown_method"):
            ComplianceProfile(
                daily_loss_pct=5.0,
                max_drawdown_pct=10.0,
                max_drawdown_method="weird",
            )

    def test_rejects_nan_daily_loss(self) -> None:
        with pytest.raises(ValueError, match="daily_loss_pct"):
            ComplianceProfile(
                daily_loss_pct=float("nan"),
                max_drawdown_pct=10.0,
            )

    def test_rejects_inf_daily_loss(self) -> None:
        # +inf would silently disable the daily-loss gate.
        with pytest.raises(ValueError, match="daily_loss_pct"):
            ComplianceProfile(
                daily_loss_pct=float("inf"),
                max_drawdown_pct=10.0,
            )

    def test_rejects_nan_max_dd(self) -> None:
        with pytest.raises(ValueError, match="max_drawdown_pct"):
            ComplianceProfile(
                daily_loss_pct=5.0,
                max_drawdown_pct=float("nan"),
            )

    def test_rejects_inf_max_dd(self) -> None:
        with pytest.raises(ValueError, match="max_drawdown_pct"):
            ComplianceProfile(
                daily_loss_pct=5.0,
                max_drawdown_pct=float("inf"),
            )


# --- Rule-engine builder ----------------------------------------------


class TestBuildComplianceRuleEngine:
    def test_includes_daily_loss_max_dd_consistency_when_full_ftmo(self) -> None:
        engine = build_compliance_rule_engine(
            ComplianceProfile.for_ftmo(), account_id="ftmo-1"
        )
        rule_types = {type(r) for r in engine.get_rules()}
        assert DailyLossLimitRule in rule_types
        assert MaxDrawdownRule in rule_types
        assert ConsistencyRule in rule_types

    def test_omits_consistency_when_block_at_none(self) -> None:
        profile = dataclasses.replace(
            ComplianceProfile.for_ftmo(), consistency_block_at=None
        )
        engine = build_compliance_rule_engine(profile, account_id="x")
        rule_types = {type(r) for r in engine.get_rules()}
        assert ConsistencyRule not in rule_types
        assert DailyLossLimitRule in rule_types
        assert MaxDrawdownRule in rule_types

    def test_daily_loss_rule_uses_profile_timezone(self) -> None:
        profile = ComplianceProfile.for_ftmo()
        engine = build_compliance_rule_engine(profile, account_id="x")
        rule = next(
            r for r in engine.get_rules() if isinstance(r, DailyLossLimitRule)
        )
        assert rule.timezone == "CET"
        assert rule.reset_time == "00:00"
        assert rule.threshold_percent == 5.0

    def test_max_dd_rule_uses_profile_method(self) -> None:
        profile = ComplianceProfile.for_ftmo()
        engine = build_compliance_rule_engine(profile, account_id="x")
        rule = next(
            r for r in engine.get_rules() if isinstance(r, MaxDrawdownRule)
        )
        assert rule.method == "balance_based"
        assert rule.threshold_percent == 10.0

    def test_consistency_rule_uses_profile_block_at(self) -> None:
        profile = ComplianceProfile.for_ftmo()
        engine = build_compliance_rule_engine(profile, account_id="x")
        rule = next(
            r for r in engine.get_rules() if isinstance(r, ConsistencyRule)
        )
        assert rule.block_at == 50.0

    def test_engine_account_id_threaded(self) -> None:
        engine = build_compliance_rule_engine(
            ComplianceProfile.for_ftmo(), account_id="my-account"
        )
        assert engine.account_id == "my-account"


# --- Breach summarisation ---------------------------------------------


def _metrics(
    *,
    daily_loss_breaches: int = 0,
    max_dd_breach: bool = False,
) -> PropFirmMetricsSchema:
    return PropFirmMetricsSchema(
        strategy_name="x",
        pnl=PnlMetrics(
            gross_pnl=0.0, net_pnl=0.0, return_pct=0.0,
            profit_factor=1.0, expectancy=0.0, avg_r_multiple=0.0,
        ),
        drawdown=DrawdownMetrics(
            max_overall_dd_pct=0.0, max_overall_dd_abs=0.0,
            max_daily_dd_pct=0.0, avg_daily_dd_pct=0.0,
            recovery_factor=0.0,
        ),
        risk=RiskMetrics(
            sharpe_ratio=0.0, sortino_ratio=0.0, calmar_ratio=0.0,
            max_consecutive_losses=0,
        ),
        trades=TradeMetrics(
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0.0, avg_win=0.0, avg_loss=0.0,
        ),
        prop_firm_compliance=PropFirmComplianceMetrics(
            daily_loss_breaches=daily_loss_breaches,
            max_dd_breach=max_dd_breach,
            profit_target_hit=False,
            min_trading_days_met=False,
        ),
    )


def _result(
    *,
    label: str = "ma_crossover",
    metrics: PropFirmMetricsSchema | None = None,
    breaches: list[BreachEvent] | None = None,
) -> BacktestResult:
    snap: dict[str, Any] = {
        "strategy": {"label": label, "name": label},
    }
    return BacktestResult(
        strategy_name=label,
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 4, 1, tzinfo=UTC),
        initial_balance=Decimal("100000"),
        final_balance=Decimal("100000"),
        breaches=breaches or [],
        metrics=metrics if metrics is not None else _metrics(),
        config_snapshot=snap,
    )


def _breach(rule: str = "daily_loss_limit") -> BreachEvent:
    return BreachEvent(
        ts=datetime(2024, 1, 5, 12, tzinfo=UTC),
        rule_name=rule,
        current_value=5.5,
        threshold_value=5.0,
        message="x",
    )


class TestSummarizeBreaches:
    def test_clean_run_zero_counts(self) -> None:
        summary = summarize_breaches([_result()])
        assert summary[0].label == "ma_crossover"
        assert summary[0].daily_loss_breaches == 0
        assert summary[0].max_dd_breach is False
        assert summary[0].breach_event_count == 0
        assert summary[0].is_clean

    def test_counts_metrics_breaches(self) -> None:
        summary = summarize_breaches(
            [_result(metrics=_metrics(daily_loss_breaches=2, max_dd_breach=True))]
        )
        assert summary[0].daily_loss_breaches == 2
        assert summary[0].max_dd_breach is True
        assert summary[0].is_clean is False

    def test_counts_breach_events(self) -> None:
        summary = summarize_breaches(
            [_result(breaches=[_breach(), _breach("max_drawdown")])]
        )
        assert summary[0].breach_event_count == 2
        assert summary[0].is_clean is False

    def test_handles_missing_metrics(self) -> None:
        # A result that didn't run the actor (or zero-trade run with
        # metrics=None) should still summarise without crashing.
        no_metrics = dataclasses.replace(_result(), metrics=None)
        summary = summarize_breaches([no_metrics])
        assert summary[0].daily_loss_breaches == 0
        assert summary[0].max_dd_breach is False
        assert summary[0].is_clean is True

    def test_uses_strategy_label_from_snapshot(self) -> None:
        summary = summarize_breaches([_result(label="my_label")])
        assert summary[0].label == "my_label"

    def test_falls_back_to_strategy_name_when_snapshot_missing(self) -> None:
        no_snap = dataclasses.replace(_result(label="bare"), config_snapshot=None)
        summary = summarize_breaches([no_snap])
        assert summary[0].label == "bare"


# --- assert_no_breaches -----------------------------------------------


class TestAssertNoBreaches:
    def test_passes_for_clean_results(self) -> None:
        # Should not raise.
        assert_no_breaches([_result(), _result(label="orb")])

    def test_raises_on_metric_breach(self) -> None:
        bad = _result(
            label="supertrend",
            metrics=_metrics(daily_loss_breaches=1),
        )
        with pytest.raises(ComplianceBreachError, match="supertrend"):
            assert_no_breaches([_result(), bad])

    def test_raises_on_max_dd_flag(self) -> None:
        bad = _result(label="orb", metrics=_metrics(max_dd_breach=True))
        with pytest.raises(ComplianceBreachError, match="orb"):
            assert_no_breaches([bad])

    def test_raises_on_breach_event(self) -> None:
        bad = _result(label="rsi", breaches=[_breach()])
        with pytest.raises(ComplianceBreachError, match="rsi"):
            assert_no_breaches([bad])

    def test_allow_list_skips_named_strategies(self) -> None:
        bad = _result(
            label="known_breaker",
            metrics=_metrics(daily_loss_breaches=1),
        )
        # Allow lets the breach pass without raising.
        assert_no_breaches([bad], allow=("known_breaker",))

    def test_error_message_lists_every_offender(self) -> None:
        bad_a = _result(
            label="a", metrics=_metrics(daily_loss_breaches=1)
        )
        bad_b = _result(label="b", breaches=[_breach()])
        with pytest.raises(ComplianceBreachError) as excinfo:
            assert_no_breaches([bad_a, bad_b])
        msg = str(excinfo.value)
        assert "a" in msg and "b" in msg

    def test_returns_breach_summaries_on_error(self) -> None:
        bad = _result(label="x", metrics=_metrics(daily_loss_breaches=1))
        with pytest.raises(ComplianceBreachError) as excinfo:
            assert_no_breaches([bad])
        # Error carries structured details for caller logging.
        assert isinstance(excinfo.value.summaries, tuple)
        assert all(isinstance(s, BreachSummary) for s in excinfo.value.summaries)
        assert excinfo.value.summaries[0].label == "x"

    def test_does_not_inherit_assertion_error(self) -> None:
        # A broad ``except AssertionError:`` in an experiment harness
        # must not silently eat compliance breaches.
        bad = _result(label="x", metrics=_metrics(daily_loss_breaches=1))
        try:
            assert_no_breaches([bad])
        except AssertionError:  # pragma: no cover — must not match
            pytest.fail("ComplianceBreachError must not subclass AssertionError")
        except ComplianceBreachError:
            pass


# --- BreachSummary ----------------------------------------------------


class TestBreachSummary:
    def test_is_clean_when_all_zero(self) -> None:
        s = BreachSummary(
            label="x",
            daily_loss_breaches=0,
            max_dd_breach=False,
            breach_event_count=0,
        )
        assert s.is_clean

    def test_is_frozen(self) -> None:
        s = BreachSummary(
            label="x",
            daily_loss_breaches=0,
            max_dd_breach=False,
            breach_event_count=0,
        )
        with pytest.raises((AttributeError, TypeError)):
            s.label = "other"  # type: ignore[misc]
