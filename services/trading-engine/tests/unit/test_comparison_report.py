"""Unit tests for ``src.backtesting.dataset.comparison_report``.

The report renders one markdown table for the list of
:class:`BacktestResult` produced by the baseline harness, applies the
in-sample filter from Decision §2 (sharpe ≥ 0.8, max_dd ≤ 8 pp,
trades ≥ 200, zero breaches), and cites the dataset fingerprint so the
report is reproducible.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.backtesting.dataset.comparison_report import (
    BaselineFilter,
    FilterVerdict,
    FingerprintMismatchError,
    evaluate_filter,
    render_comparison_report,
)
from src.backtesting.metrics.schema import (
    DrawdownMetrics,
    PnlMetrics,
    PropFirmComplianceMetrics,
    PropFirmMetricsSchema,
    RiskMetrics,
    TradeMetrics,
)
from src.backtesting.result import BacktestResult


pytestmark = pytest.mark.unit


# --- Builders ---------------------------------------------------------


def _metrics(
    *,
    strategy_name: str = "ma_crossover",
    sharpe: float = 1.2,
    sortino: float = 1.5,
    max_dd: float = 5.0,
    profit_factor: float = 1.6,
    total_trades: int = 250,
    win_rate: float = 0.55,
    expectancy: float = 12.5,
    daily_loss_breaches: int = 0,
    max_dd_breach: bool = False,
) -> PropFirmMetricsSchema:
    return PropFirmMetricsSchema(
        strategy_name=strategy_name,
        pnl=PnlMetrics(
            gross_pnl=10000.0,
            net_pnl=8500.0,
            return_pct=8.5,
            profit_factor=profit_factor,
            expectancy=expectancy,
            avg_r_multiple=1.4,
        ),
        drawdown=DrawdownMetrics(
            max_overall_dd_pct=max_dd,
            max_overall_dd_abs=2500.0,
            max_daily_dd_pct=2.0,
            avg_daily_dd_pct=0.6,
            recovery_factor=3.0,
        ),
        risk=RiskMetrics(
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=2.0,
            max_consecutive_losses=4,
        ),
        trades=TradeMetrics(
            total_trades=total_trades,
            winning_trades=int(total_trades * win_rate),
            losing_trades=total_trades - int(total_trades * win_rate),
            win_rate=win_rate,
            avg_win=20.0,
            avg_loss=-12.0,
        ),
        prop_firm_compliance=PropFirmComplianceMetrics(
            daily_loss_breaches=daily_loss_breaches,
            max_dd_breach=max_dd_breach,
            profit_target_hit=True,
            min_trading_days_met=True,
        ),
    )


def _snapshot(
    *,
    label: str = "ma_crossover",
    timeframe: str = "M5",
    sha: str = "abc123def4567890",
    spec_name: str = "xauusd-validation",
    dataset_version: str = "1.0.0",
    window_name: str = "in_sample",
    run_label: str = "phase-12a",
) -> dict[str, Any]:
    return {
        "run_label": run_label,
        "dataset": {
            "spec_name": spec_name,
            "dataset_version": dataset_version,
            "symbol": "XAUUSD",
            "timeframe": timeframe,
            "window_name": window_name,
            "window_kind": "in_sample",
            "fingerprint": {
                "min_ts": 1_000_000_000,
                "max_ts": 2_000_000_000,
                "row_count": 144_000,
                "sha256_short": sha,
            },
            "row_count": 144_000,
        },
        "strategy": {
            "name": label,
            "label": label,
            "timeframe": timeframe,
            "bar_type_suffix": "5-MINUTE-LAST-EXTERNAL",
            "params": {},
        },
        "venue": {
            "name": "SIM",
            "starting_balance": "100000",
            "currency": "USD",
            "commission_per_lot_usd": "7.0",
        },
        "prop_firm": None,
        "regime_classifier_enabled": False,
    }


_DEFAULT = object()


def _result(
    *,
    label: str = "ma_crossover",
    snapshot_overrides: dict[str, Any] | None = None,
    metrics: PropFirmMetricsSchema | None | object = _DEFAULT,
    final_balance: Decimal = Decimal("108500"),
) -> BacktestResult:
    snap = _snapshot(label=label)
    if snapshot_overrides:
        snap = {**snap, **snapshot_overrides}
    if metrics is _DEFAULT:
        metrics_value: PropFirmMetricsSchema | None = _metrics(strategy_name=label)
    else:
        metrics_value = metrics  # type: ignore[assignment]
    return BacktestResult(
        strategy_name=label,
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, tzinfo=UTC),
        initial_balance=Decimal("100000"),
        final_balance=final_balance,
        metrics=metrics_value,
        config_snapshot=snap,
    )


# --- Filter -----------------------------------------------------------


class TestBaselineFilter:
    def test_default_thresholds_match_decision_section_2(self) -> None:
        # Decision §2 in docs/epic-12-context.md.
        f = BaselineFilter()
        assert f.min_sharpe == 0.8
        assert f.max_drawdown_pct == 8.0
        assert f.min_trades == 200
        assert f.max_daily_loss_breaches == 0

    def test_is_frozen(self) -> None:
        f = BaselineFilter()
        with pytest.raises((AttributeError, TypeError)):
            f.min_sharpe = 0.5  # type: ignore[misc]


class TestEvaluateFilter:
    def _eval(self, result: BacktestResult) -> FilterVerdict:
        return evaluate_filter(result, BaselineFilter())

    def test_passes_when_all_thresholds_clear(self) -> None:
        verdict = self._eval(_result())
        assert verdict.passed is True
        assert verdict.reasons == ()

    def test_fails_low_sharpe(self) -> None:
        verdict = self._eval(_result(metrics=_metrics(sharpe=0.4)))
        assert verdict.passed is False
        assert any("sharpe" in r.lower() for r in verdict.reasons)

    def test_fails_high_drawdown(self) -> None:
        verdict = self._eval(_result(metrics=_metrics(max_dd=12.0)))
        assert verdict.passed is False
        assert any("drawdown" in r.lower() for r in verdict.reasons)

    def test_fails_few_trades(self) -> None:
        verdict = self._eval(_result(metrics=_metrics(total_trades=50)))
        assert verdict.passed is False
        assert any("trade" in r.lower() for r in verdict.reasons)

    def test_fails_daily_loss_breach(self) -> None:
        verdict = self._eval(
            _result(metrics=_metrics(daily_loss_breaches=1))
        )
        assert verdict.passed is False
        assert any("daily" in r.lower() for r in verdict.reasons)

    def test_fails_max_dd_breach_flag(self) -> None:
        verdict = self._eval(_result(metrics=_metrics(max_dd_breach=True)))
        assert verdict.passed is False
        assert any("max" in r.lower() and "drawdown" in r.lower()
                   for r in verdict.reasons)

    def test_fails_when_metrics_absent(self) -> None:
        verdict = self._eval(_result(metrics=None))  # type: ignore[arg-type]
        assert verdict.passed is False
        assert any("metric" in r.lower() for r in verdict.reasons)

    def test_collects_multiple_reasons(self) -> None:
        verdict = self._eval(
            _result(metrics=_metrics(sharpe=0.4, max_dd=12.0, total_trades=50))
        )
        assert verdict.passed is False
        assert len(verdict.reasons) >= 3


# --- Render -----------------------------------------------------------


class TestRenderComparisonReport:
    def test_includes_run_label_and_fingerprint_in_header(self) -> None:
        text = render_comparison_report([_result()])
        assert "phase-12a" in text
        assert "abc123def4567890" in text  # fingerprint
        assert "xauusd-validation" in text  # spec name
        assert "1.0.0" in text  # dataset version

    def test_table_has_one_row_per_strategy(self) -> None:
        text = render_comparison_report(
            [
                _result(label="ma_crossover"),
                _result(label="supertrend"),
                _result(label="orb"),
            ]
        )
        # Each strategy label appears in a table row body.
        for label in ("ma_crossover", "supertrend", "orb"):
            assert f"| {label} " in text or f"|{label}|" in text or label in text

    def test_table_includes_required_metric_columns(self) -> None:
        text = render_comparison_report([_result()])
        # Decision §2 + epic context columns.
        for header in (
            "Strategy",
            "Sharpe",
            "Sortino",
            "Max DD",
            "Profit Factor",
            "Win Rate",
            "Trades",
            "Breaches",
            "Verdict",
        ):
            assert header in text, f"missing header: {header}"

    def test_pass_verdict_marker_present(self) -> None:
        text = render_comparison_report([_result()])
        assert "PASS" in text

    def test_fail_verdict_marker_present(self) -> None:
        text = render_comparison_report(
            [_result(metrics=_metrics(sharpe=0.4))]
        )
        assert "FAIL" in text

    def test_missing_metrics_render_dash(self) -> None:
        text = render_comparison_report([_result(metrics=None)])  # type: ignore[arg-type]
        # Cell placeholder for missing metric values.
        assert "—" in text or "-" in text

    def test_filter_summary_at_bottom_lists_passes(self) -> None:
        text = render_comparison_report(
            [
                _result(label="ma_crossover"),  # passes
                _result(label="supertrend",
                        metrics=_metrics(sharpe=0.4)),  # fails
            ]
        )
        # Footer must enumerate passing strategies (Phase 12.B input).
        assert "ma_crossover" in text
        assert "Pass" in text or "PASS" in text

    def test_deterministic_output_for_same_input(self) -> None:
        result = _result()
        a = render_comparison_report([result])
        b = render_comparison_report([result])
        assert a == b

    def test_empty_list_returns_nonempty_report(self) -> None:
        # Edge: caller passed no results — report must not crash but
        # should make clear nothing was evaluated.
        text = render_comparison_report([])
        assert text.strip() != ""
        assert "no results" in text.lower() or "empty" in text.lower()

    def test_rejects_fingerprint_mismatch(self) -> None:
        a = _result(label="ma_crossover")
        b = _result(label="supertrend", snapshot_overrides=None)
        # Mutate b's snapshot to have a different fingerprint.
        snap_b = dict(b.config_snapshot or {})
        snap_b["dataset"] = {**snap_b["dataset"], "fingerprint": {
            **snap_b["dataset"]["fingerprint"],
            "sha256_short": "differentfingerp",
        }}
        b = dataclasses.replace(b, config_snapshot=snap_b)
        with pytest.raises(FingerprintMismatchError):
            render_comparison_report([a, b])

    def test_skips_fingerprint_check_when_snapshot_missing(self) -> None:
        # A result without config_snapshot (legacy path) renders gracefully.
        no_snap = dataclasses.replace(_result(), config_snapshot=None)
        text = render_comparison_report([no_snap])
        # Should still render but the header notes the missing fingerprint.
        assert "fingerprint" in text.lower()

    def test_custom_filter_thresholds_apply(self) -> None:
        # A stricter filter (sharpe ≥ 1.5) flips the default-passing case.
        text = render_comparison_report(
            [_result()], baseline_filter=BaselineFilter(min_sharpe=1.5)
        )
        assert "FAIL" in text

    def test_block_on_max_dd_breach_can_be_disabled(self) -> None:
        # Decision §2 fifth condition is configurable.
        result = _result(metrics=_metrics(max_dd_breach=True))
        # Default filter blocks: result fails.
        verdict_default = evaluate_filter(result, BaselineFilter())
        assert verdict_default.passed is False
        # Disabling makes the same result pass.
        verdict_relaxed = evaluate_filter(
            result, BaselineFilter(block_on_max_dd_breach=False)
        )
        assert verdict_relaxed.passed is True

    def test_header_reflects_block_on_max_dd_breach_flag(self) -> None:
        text_default = render_comparison_report([_result()])
        assert "max-DD breach blocks" in text_default
        text_relaxed = render_comparison_report(
            [_result()],
            baseline_filter=BaselineFilter(block_on_max_dd_breach=False),
        )
        assert "max-DD breach ignored" in text_relaxed

    def test_pipe_in_strategy_label_sanitised(self) -> None:
        # A pipe character in the label would otherwise split the cell
        # and corrupt the markdown table.
        snapshot = _snapshot(label="ma|crossover")
        snapshot["strategy"] = {**snapshot["strategy"], "label": "ma|crossover"}
        result = dataclasses.replace(
            _result(label="ma|crossover"), config_snapshot=snapshot
        )
        text = render_comparison_report([result])
        # Pipe escaped, table row count unchanged.
        assert "ma\\|crossover" in text
        # Header row + separator + 1 data row → 3 lines starting with '|'.
        table_lines = [ln for ln in text.splitlines() if ln.startswith("|")]
        assert len(table_lines) == 3

    def test_newline_in_strategy_label_sanitised(self) -> None:
        snapshot = _snapshot(label="ma\nshort")
        snapshot["strategy"] = {**snapshot["strategy"], "label": "ma\nshort"}
        result = dataclasses.replace(
            _result(label="ma\nshort"), config_snapshot=snapshot
        )
        text = render_comparison_report([result])
        table_lines = [ln for ln in text.splitlines() if ln.startswith("|")]
        # Still exactly 3 table lines (header + sep + 1 data row).
        assert len(table_lines) == 3

    def test_runtime_error_when_run_labels_diverge(self) -> None:
        # Each result should belong to the same campaign run; differing
        # run_labels mean the caller mixed two campaigns by mistake.
        a = _result(label="ma_crossover")
        b = _result(label="supertrend",
                    snapshot_overrides={
                        **(_result(label="supertrend").config_snapshot or {}),
                        "run_label": "phase-12b",
                    })
        with pytest.raises(ValueError, match="run_label"):
            render_comparison_report([a, b])
