"""Unit tests for ``src.backtesting.dataset.walk_forward_harness``.

The harness layers manifest-driven fold generation and OOS aggregation
on top of the existing :mod:`src.backtesting.walk_forward` primitives.
12.5's responsibility is the wrapper plus the Decision §4 ratio check
(``mean(OOS sharpe) ≥ 0.7 × IS sharpe`` and ``std/mean ≤ 0.5``);
12.6/12.7 swap the fixed-params driver here for the parameter sweep.
"""

from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.backtesting.data_cache import ContentHashFingerprint
from src.backtesting.dataset.baseline_harness import (
    StrategySpec,
    timeframe_to_bar_suffix,
)
from src.backtesting.dataset.manifest import DatasetEntry, DatasetManifest
from src.backtesting.dataset.spec import WindowKind
from src.backtesting.dataset.walk_forward_harness import (
    FoldGenerationConfig,
    OOSAcceptance,
    OOSAggregate,
    OOSVerdict,
    WalkForwardOutcome,
    aggregate_oos,
    evaluate_oos,
    generate_folds_from_manifest,
    render_walk_forward_section,
    run_walk_forward_fixed_params,
)
from src.backtesting.job_config import (
    BacktestJobConfig,
    ParquetDataSpec,
    VenueSpec,
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


def _entry(
    *,
    timeframe: str = "M5",
    window_name: str = "in_sample",
    kind: WindowKind = WindowKind.IN_SAMPLE,
    start: datetime = datetime(2024, 1, 1, tzinfo=UTC),
    end: datetime = datetime(2026, 1, 1, tzinfo=UTC),
    parquet_path: Path = Path("/tmp/cache/XAUUSD/M5/in_sample.parquet"),
) -> DatasetEntry:
    return DatasetEntry(
        timeframe=timeframe,
        window_name=window_name,
        window_kind=kind,
        start=start,
        end=end,
        parquet_path=parquet_path,
        fingerprint=ContentHashFingerprint(
            min_ts=1_000_000_000, max_ts=2_000_000_000, row_count=144_000
        ),
        row_count=144_000,
    )


def _manifest(entries: tuple[DatasetEntry, ...]) -> DatasetManifest:
    return DatasetManifest(
        spec_name="xauusd-validation",
        dataset_version="1.0.0",
        symbol="XAUUSD",
        generated_at=datetime(2026, 5, 3, tzinfo=UTC),
        max_gap_hours=48.0,
        entries=entries,
    )


def _venue() -> VenueSpec:
    return VenueSpec(
        name="SIM",
        starting_balance=Decimal("100000"),
        currency="USD",
    )


def _spec(timeframe: str = "M5", **params: Any) -> StrategySpec:
    return StrategySpec(
        name="ma_crossover",
        timeframe=timeframe,
        bar_type_suffix=timeframe_to_bar_suffix(timeframe),
        params=params,
    )


def _metrics(*, sharpe: float, max_dd: float = 5.0, trades: int = 50,
             win_rate: float = 0.55) -> PropFirmMetricsSchema:
    return PropFirmMetricsSchema(
        strategy_name="x",
        pnl=PnlMetrics(
            gross_pnl=0.0, net_pnl=0.0, return_pct=0.0,
            profit_factor=1.4, expectancy=0.0, avg_r_multiple=0.0,
        ),
        drawdown=DrawdownMetrics(
            max_overall_dd_pct=max_dd, max_overall_dd_abs=0.0,
            max_daily_dd_pct=0.0, avg_daily_dd_pct=0.0,
            recovery_factor=0.0,
        ),
        risk=RiskMetrics(
            sharpe_ratio=sharpe, sortino_ratio=sharpe + 0.2,
            calmar_ratio=0.0, max_consecutive_losses=0,
        ),
        trades=TradeMetrics(
            total_trades=trades, winning_trades=int(trades * win_rate),
            losing_trades=trades - int(trades * win_rate),
            win_rate=win_rate, avg_win=0.0, avg_loss=0.0,
        ),
        prop_firm_compliance=PropFirmComplianceMetrics(
            daily_loss_breaches=0, max_dd_breach=False,
            profit_target_hit=False, min_trading_days_met=False,
        ),
    )


# --- FoldGenerationConfig --------------------------------------------


class TestFoldGenerationConfig:
    def test_defaults_match_decision_section_4(self) -> None:
        # 6m rolling: train 6m / test 1m / step 1m, mode=rolling.
        cfg = FoldGenerationConfig()
        assert cfg.train_window == timedelta(days=6 * 30)
        assert cfg.test_window == timedelta(days=30)
        assert cfg.step == timedelta(days=30)
        assert cfg.mode == "rolling"

    def test_rejects_non_positive_train_window(self) -> None:
        with pytest.raises(ValueError, match="train_window"):
            FoldGenerationConfig(train_window=timedelta(0))

    def test_rejects_non_positive_test_window(self) -> None:
        with pytest.raises(ValueError, match="test_window"):
            FoldGenerationConfig(test_window=timedelta(0))

    def test_rejects_non_positive_step(self) -> None:
        with pytest.raises(ValueError, match="step"):
            FoldGenerationConfig(step=timedelta(0))

    def test_rejects_unknown_mode(self) -> None:
        with pytest.raises(ValueError, match="mode"):
            FoldGenerationConfig(mode="weird")  # type: ignore[arg-type]

    def test_is_frozen(self) -> None:
        cfg = FoldGenerationConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.train_window = timedelta(days=1)  # type: ignore[misc]


# --- generate_folds_from_manifest ------------------------------------


class TestGenerateFoldsFromManifest:
    def test_uses_manifest_window_boundaries(self) -> None:
        manifest = _manifest((_entry(),))
        folds = generate_folds_from_manifest(
            manifest,
            window_name="in_sample",
            config=FoldGenerationConfig(),
        )
        # Test windows must lie within the IS window.
        for fold in folds:
            assert fold.test_start >= datetime(2024, 1, 1, tzinfo=UTC)
            assert fold.test_end <= datetime(2026, 1, 1, tzinfo=UTC)

    def test_default_2y_window_yields_about_18_folds(self) -> None:
        # 2y - 6m train = 18m test space; step 1m → ~18 folds.
        manifest = _manifest((_entry(),))
        folds = generate_folds_from_manifest(
            manifest,
            window_name="in_sample",
            config=FoldGenerationConfig(),
        )
        # Allow ±1 due to month-of-30-days approximation in the default.
        assert 17 <= len(folds) <= 19

    def test_unknown_window_raises(self) -> None:
        manifest = _manifest((_entry(),))
        with pytest.raises(KeyError, match="oos_reserve"):
            generate_folds_from_manifest(
                manifest,
                window_name="oos_reserve",
                config=FoldGenerationConfig(),
            )

    def test_picks_first_entry_for_window(self) -> None:
        # Multiple timeframes share the same window boundaries — picking
        # any one is fine; the harness only needs the (start, end).
        m5 = _entry(timeframe="M5")
        m15 = _entry(timeframe="M15")
        manifest = _manifest((m5, m15))
        folds = generate_folds_from_manifest(
            manifest,
            window_name="in_sample",
            config=FoldGenerationConfig(),
        )
        assert len(folds) > 0


# --- OOSAggregate ----------------------------------------------------


class TestOOSAggregate:
    def _outcomes(self, sharpes: list[float]) -> WalkForwardOutcome:
        from src.backtesting.dataset.walk_forward_harness import FoldOutcome
        from src.backtesting.walk_forward import FoldSpec

        outcomes: list[FoldOutcome] = []
        for i, sh in enumerate(sharpes):
            fold = FoldSpec(
                train_start=datetime(2024, 1, 1, tzinfo=UTC),
                train_end=datetime(2024, 7, 1, tzinfo=UTC) + timedelta(days=30 * i),
                test_start=datetime(2024, 7, 1, tzinfo=UTC) + timedelta(days=30 * i),
                test_end=datetime(2024, 8, 1, tzinfo=UTC) + timedelta(days=30 * i),
            )
            result = BacktestResult(
                strategy_name="x",
                start=fold.test_start,
                end=fold.test_end,
                initial_balance=Decimal("100000"),
                final_balance=Decimal("100000"),
                metrics=_metrics(sharpe=sh),
            )
            outcomes.append(
                FoldOutcome(
                    fold=fold,
                    fold_index=i,
                    oos_result=result,
                    error=None,
                )
            )
        return WalkForwardOutcome(label="ma_crossover", fold_outcomes=tuple(outcomes))

    def test_aggregates_mean_sharpe(self) -> None:
        agg = aggregate_oos(self._outcomes([1.0, 1.4, 1.6, 1.2]))
        assert agg.mean_oos_sharpe == pytest.approx(1.3)
        assert agg.n_folds_with_metrics == 4

    def test_aggregates_std_sharpe(self) -> None:
        sharpes = [1.0, 1.4, 1.6, 1.2]
        agg = aggregate_oos(self._outcomes(sharpes))
        assert agg.std_oos_sharpe == pytest.approx(statistics.pstdev(sharpes))

    def test_zero_folds_with_metrics_handled(self) -> None:
        # All folds errored → metrics are NaN sentinels rather than crash.
        from src.backtesting.dataset.walk_forward_harness import FoldOutcome
        from src.backtesting.walk_forward import FoldSpec

        fold = FoldSpec(
            train_start=datetime(2024, 1, 1, tzinfo=UTC),
            train_end=datetime(2024, 7, 1, tzinfo=UTC),
            test_start=datetime(2024, 7, 1, tzinfo=UTC),
            test_end=datetime(2024, 8, 1, tzinfo=UTC),
        )
        outcome = WalkForwardOutcome(
            label="x",
            fold_outcomes=(
                FoldOutcome(
                    fold=fold,
                    fold_index=0,
                    oos_result=None,
                    error="strategy crashed",
                ),
            ),
        )
        agg = aggregate_oos(outcome)
        assert agg.n_folds_with_metrics == 0
        assert math.isnan(agg.mean_oos_sharpe)
        assert math.isnan(agg.std_oos_sharpe)

    def test_aggregates_max_dd(self) -> None:
        sharpes = [1.0, 1.0]
        outcome = self._outcomes(sharpes)
        # All have max_dd=5.0 by builder default.
        agg = aggregate_oos(outcome)
        assert agg.mean_oos_max_dd_pct == pytest.approx(5.0)

    def test_total_trades_summed(self) -> None:
        outcome = self._outcomes([1.0, 1.0, 1.0])
        agg = aggregate_oos(outcome)
        # 3 folds × 50 trades each.
        assert agg.total_oos_trades == 150

    def test_mean_trades_is_nan_when_no_folds_have_metrics(self) -> None:
        from src.backtesting.dataset.walk_forward_harness import FoldOutcome
        from src.backtesting.walk_forward import FoldSpec

        fold = FoldSpec(
            train_start=datetime(2024, 1, 1, tzinfo=UTC),
            train_end=datetime(2024, 7, 1, tzinfo=UTC),
            test_start=datetime(2024, 7, 1, tzinfo=UTC),
            test_end=datetime(2024, 8, 1, tzinfo=UTC),
        )
        outcome = WalkForwardOutcome(
            label="x",
            fold_outcomes=(
                FoldOutcome(
                    fold=fold, fold_index=0, oos_result=None, error="boom"
                ),
            ),
        )
        agg = aggregate_oos(outcome)
        # NaN sentinel — caller can distinguish "no data" from a
        # degenerate strategy that ran with zero trades.
        assert math.isnan(agg.mean_oos_trades)
        assert agg.total_oos_trades == 0


# --- evaluate_oos ----------------------------------------------------


class TestEvaluateOOS:
    def _agg(self, *, mean_sh: float, std_sh: float, n: int = 12,
             trades: int = 600) -> OOSAggregate:
        return OOSAggregate(
            label="ma_crossover",
            n_folds=n,
            n_folds_with_metrics=n,
            mean_oos_sharpe=mean_sh,
            std_oos_sharpe=std_sh,
            mean_oos_max_dd_pct=5.0,
            mean_oos_trades=int(trades / n),
            total_oos_trades=trades,
            mean_oos_profit_factor=1.4,
            mean_oos_win_rate=0.55,
        )

    def test_passes_when_ratio_and_cv_clear(self) -> None:
        # IS sharpe = 1.0; mean OOS = 0.9 → ratio 0.9 > 0.7
        # std/mean = 0.2/0.9 = 0.22 < 0.5
        agg = self._agg(mean_sh=0.9, std_sh=0.2)
        verdict = evaluate_oos(agg, is_sharpe=1.0)
        assert verdict.passed is True

    def test_fails_low_ratio(self) -> None:
        # mean OOS / IS = 0.4 / 1.0 = 0.4 < 0.7
        agg = self._agg(mean_sh=0.4, std_sh=0.1)
        verdict = evaluate_oos(agg, is_sharpe=1.0)
        assert verdict.passed is False
        assert any("ratio" in r.lower() for r in verdict.reasons)

    def test_fails_high_cv(self) -> None:
        # std/mean = 0.6/1.0 = 0.6 > 0.5
        agg = self._agg(mean_sh=1.0, std_sh=0.6)
        verdict = evaluate_oos(agg, is_sharpe=1.0)
        assert verdict.passed is False
        assert any("cv" in r.lower() or "stability" in r.lower()
                   for r in verdict.reasons)

    def test_fails_when_zero_folds_have_metrics(self) -> None:
        agg = OOSAggregate(
            label="x", n_folds=12, n_folds_with_metrics=0,
            mean_oos_sharpe=float("nan"), std_oos_sharpe=float("nan"),
            mean_oos_max_dd_pct=float("nan"), mean_oos_trades=0,
            total_oos_trades=0, mean_oos_profit_factor=float("nan"),
            mean_oos_win_rate=float("nan"),
        )
        verdict = evaluate_oos(agg, is_sharpe=1.0)
        assert verdict.passed is False

    def test_fails_when_mean_oos_sharpe_negative(self) -> None:
        # ratio with negative mean → CV check ill-defined; the ratio
        # check alone must reject.
        agg = self._agg(mean_sh=-0.2, std_sh=0.3)
        verdict = evaluate_oos(agg, is_sharpe=1.0)
        assert verdict.passed is False

    def test_custom_thresholds_apply(self) -> None:
        # Tightened: ratio ≥ 0.9 instead of 0.7.
        agg = self._agg(mean_sh=0.8, std_sh=0.1)
        strict = OOSAcceptance(oos_to_is_sharpe_ratio_min=0.9)
        verdict = evaluate_oos(agg, is_sharpe=1.0, acceptance=strict)
        assert verdict.passed is False

    def test_fails_when_is_sharpe_not_positive(self) -> None:
        # ratio undefined when IS sharpe is 0 or negative.
        agg = self._agg(mean_sh=0.5, std_sh=0.1)
        verdict = evaluate_oos(agg, is_sharpe=0.0)
        assert verdict.passed is False


# --- run_walk_forward_fixed_params -----------------------------------


class _FakeBaselineRunner:
    """Captures BacktestJobConfig per fold; returns canned results."""

    def __init__(self, *, sharpe_per_fold: list[float]) -> None:
        self._sharpes = list(sharpe_per_fold)
        self.calls: list[BacktestJobConfig] = []
        self._idx = 0

    def __call__(
        self,
        job: BacktestJobConfig,
        *,
        strategy_overrides: dict[str, Any] | None = None,
    ) -> BacktestResult:
        self.calls.append(job)
        sh = self._sharpes[self._idx]
        self._idx += 1
        return BacktestResult(
            strategy_name=job.strategy,
            start=job.start or datetime(2024, 1, 1, tzinfo=UTC),
            end=job.end or datetime(2024, 2, 1, tzinfo=UTC),
            initial_balance=Decimal(job.venue.starting_balance),
            final_balance=Decimal(job.venue.starting_balance),
            metrics=_metrics(sharpe=sh),
        )


class TestRunWalkForwardFixedParams:
    def test_dispatches_one_job_per_fold(self) -> None:
        manifest = _manifest((_entry(),))
        spec = _spec(fast_period=5, slow_period=20)
        runner = _FakeBaselineRunner(sharpe_per_fold=[1.0] * 18)
        outcome = run_walk_forward_fixed_params(
            spec=spec,
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            fold_config=FoldGenerationConfig(),
            runner=runner,
        )
        assert len(outcome.fold_outcomes) == len(runner.calls)
        for fc in outcome.fold_outcomes:
            assert fc.error is None

    def test_uses_test_slice_dates(self) -> None:
        manifest = _manifest((_entry(),))
        spec = _spec()
        runner = _FakeBaselineRunner(sharpe_per_fold=[0.5] * 18)
        run_walk_forward_fixed_params(
            spec=spec,
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            fold_config=FoldGenerationConfig(),
            runner=runner,
        )
        # Each dispatched job has start/end matching a test slice.
        for job in runner.calls:
            assert job.start is not None and job.end is not None
            assert (job.end - job.start) <= timedelta(days=31)

    def test_uses_parquet_data_spec_from_manifest(self) -> None:
        manifest = _manifest((_entry(parquet_path=Path("/tmp/M5.parquet")),))
        runner = _FakeBaselineRunner(sharpe_per_fold=[1.0] * 18)
        run_walk_forward_fixed_params(
            spec=_spec(),
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            fold_config=FoldGenerationConfig(),
            runner=runner,
        )
        for job in runner.calls:
            assert isinstance(job.data, ParquetDataSpec)
            assert job.data.path == Path("/tmp/M5.parquet")

    def test_propagates_fixed_params_to_every_fold(self) -> None:
        manifest = _manifest((_entry(),))
        runner = _FakeBaselineRunner(sharpe_per_fold=[1.0] * 18)
        run_walk_forward_fixed_params(
            spec=_spec(fast_period=7, slow_period=21),
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            fold_config=FoldGenerationConfig(),
            runner=runner,
        )
        for job in runner.calls:
            assert job.strategy_params == {"fast_period": 7, "slow_period": 21}

    def test_isolates_fold_failures(self) -> None:
        manifest = _manifest((_entry(),))

        def crashy_runner(
            job: BacktestJobConfig,
            *,
            strategy_overrides: dict[str, Any] | None = None,
        ) -> BacktestResult:
            raise RuntimeError("simulated crash")

        outcome = run_walk_forward_fixed_params(
            spec=_spec(),
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            fold_config=FoldGenerationConfig(),
            runner=crashy_runner,
        )
        # Every fold reports an error rather than aborting the whole run.
        assert all(fc.error is not None for fc in outcome.fold_outcomes)
        assert all(fc.oos_result is None for fc in outcome.fold_outcomes)


# --- render_walk_forward_section -------------------------------------


class TestRenderWalkForwardSection:
    def _agg(self, label: str, *, mean_sh: float, std_sh: float,
             n: int = 12) -> OOSAggregate:
        return OOSAggregate(
            label=label, n_folds=n, n_folds_with_metrics=n,
            mean_oos_sharpe=mean_sh, std_oos_sharpe=std_sh,
            mean_oos_max_dd_pct=5.0, mean_oos_trades=50,
            total_oos_trades=600, mean_oos_profit_factor=1.4,
            mean_oos_win_rate=0.55,
        )

    def test_includes_columns(self) -> None:
        text = render_walk_forward_section(
            [(self._agg("ma_crossover", mean_sh=0.9, std_sh=0.2), 1.0)],
        )
        for col in ("Strategy", "Folds", "OOS Sharpe", "Std", "OOS/IS",
                    "Max DD", "Trades", "Verdict"):
            assert col in text

    def test_pass_marker_for_strategy_above_thresholds(self) -> None:
        text = render_walk_forward_section(
            [(self._agg("ma_crossover", mean_sh=0.9, std_sh=0.1), 1.0)],
        )
        assert "PASS" in text

    def test_fail_marker_for_strategy_below_thresholds(self) -> None:
        text = render_walk_forward_section(
            [(self._agg("supertrend", mean_sh=0.4, std_sh=0.5), 1.0)],
        )
        assert "FAIL" in text

    def test_empty_input_renders_polite_message(self) -> None:
        text = render_walk_forward_section([])
        assert text.strip() != ""

    def test_deterministic_for_same_input(self) -> None:
        rows = [(self._agg("a", mean_sh=0.8, std_sh=0.1), 1.0)]
        assert render_walk_forward_section(rows) == render_walk_forward_section(rows)

    def test_label_pipe_sanitised(self) -> None:
        rows = [(self._agg("ma|c", mean_sh=0.8, std_sh=0.1), 1.0)]
        text = render_walk_forward_section(rows)
        assert "ma\\|c" in text


# --- OOSVerdict + OOSAcceptance ---------------------------------------


class TestOOSAcceptance:
    def test_defaults_match_decision_section_4(self) -> None:
        a = OOSAcceptance()
        assert a.oos_to_is_sharpe_ratio_min == 0.7
        assert a.oos_sharpe_cv_max == 0.5
        assert a.min_folds_for_stability == 3

    def test_is_frozen(self) -> None:
        a = OOSAcceptance()
        with pytest.raises((AttributeError, TypeError)):
            a.oos_to_is_sharpe_ratio_min = 0.5  # type: ignore[misc]

    def test_rejects_non_positive_ratio_min(self) -> None:
        with pytest.raises(ValueError, match="ratio_min"):
            OOSAcceptance(oos_to_is_sharpe_ratio_min=0.0)

    def test_rejects_nan_ratio_min(self) -> None:
        with pytest.raises(ValueError, match="ratio_min"):
            OOSAcceptance(oos_to_is_sharpe_ratio_min=float("nan"))

    def test_rejects_non_positive_cv_max(self) -> None:
        with pytest.raises(ValueError, match="cv_max"):
            OOSAcceptance(oos_sharpe_cv_max=0.0)

    def test_rejects_min_folds_below_one(self) -> None:
        with pytest.raises(ValueError, match="min_folds_for_stability"):
            OOSAcceptance(min_folds_for_stability=0)


class TestMinFoldsGuard:
    """A single-fold walk-forward must not silently pass the CV gate."""

    def _agg(self, n_with_metrics: int) -> OOSAggregate:
        return OOSAggregate(
            label="x",
            n_folds=n_with_metrics,
            n_folds_with_metrics=n_with_metrics,
            mean_oos_sharpe=1.0,
            std_oos_sharpe=0.0,  # pstdev of 1 sample
            mean_oos_max_dd_pct=5.0,
            mean_oos_trades=50.0,
            total_oos_trades=50,
            mean_oos_profit_factor=1.4,
            mean_oos_win_rate=0.55,
        )

    def test_one_fold_fails_min_folds_check(self) -> None:
        verdict = evaluate_oos(self._agg(1), is_sharpe=1.0)
        assert verdict.passed is False
        assert any("fold" in r.lower() for r in verdict.reasons)

    def test_three_folds_meets_default_min(self) -> None:
        verdict = evaluate_oos(self._agg(3), is_sharpe=1.0)
        assert verdict.passed is True


class TestOOSVerdict:
    def test_passing_verdict_has_no_reasons(self) -> None:
        v = OOSVerdict(passed=True, reasons=())
        assert v.passed and v.reasons == ()
