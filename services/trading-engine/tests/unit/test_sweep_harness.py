"""Unit tests for ``src.backtesting.dataset.sweep_harness``.

The harness wraps the Phase 12.B parameter sweep around a manifest
window with the Decision §3 / Risk R3 guards: cap ≤ 200 trials, fail
fast on unknown sampler, default early-stop on
``max_overall_dd_pct > 10%`` (skip-record, never aborts the sweep).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.backtesting.data_cache import ContentHashFingerprint
from src.backtesting.dataset.baseline_harness import (
    StrategySpec,
    timeframe_to_bar_suffix,
)
from src.backtesting.dataset.manifest import DatasetEntry, DatasetManifest
from src.backtesting.dataset.spec import WindowKind
from src.backtesting.dataset.sweep_harness import (
    ParamSpace,
    SweepBudget,
    SweepCapExceededError,
    default_max_dd_early_stop,
    render_sweep_section,
    run_parameter_sweep,
)
from src.backtesting.job_config import BacktestJobConfig, VenueSpec
from src.backtesting.metrics.schema import (
    DrawdownMetrics,
    PnlMetrics,
    PropFirmComplianceMetrics,
    PropFirmMetricsSchema,
    RiskMetrics,
    TradeMetrics,
)
from src.backtesting.parameter_sweep import CombinationResult, SweepResult
from src.backtesting.result import BacktestResult


pytestmark = pytest.mark.unit


# --- Builders ---------------------------------------------------------


def _entry(
    *,
    timeframe: str = "M5",
    parquet_path: Path = Path("/tmp/cache/XAUUSD/M5/in_sample.parquet"),
) -> DatasetEntry:
    return DatasetEntry(
        timeframe=timeframe,
        window_name="in_sample",
        window_kind=WindowKind.IN_SAMPLE,
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, tzinfo=UTC),
        parquet_path=parquet_path,
        fingerprint=ContentHashFingerprint(
            min_ts=1_000_000_000, max_ts=2_000_000_000, row_count=144_000
        ),
        row_count=144_000,
    )


def _manifest() -> DatasetManifest:
    return DatasetManifest(
        spec_name="xauusd-validation",
        dataset_version="1.0.0",
        symbol="XAUUSD",
        generated_at=datetime(2026, 5, 3, tzinfo=UTC),
        max_gap_hours=48.0,
        entries=(_entry(),),
    )


def _venue() -> VenueSpec:
    return VenueSpec(
        name="SIM",
        starting_balance=Decimal("100000"),
        currency="USD",
    )


def _spec() -> StrategySpec:
    return StrategySpec(
        name="ma_crossover",
        timeframe="M5",
        bar_type_suffix=timeframe_to_bar_suffix("M5"),
    )


def _metrics(*, max_dd: float = 5.0, sharpe: float = 1.0) -> PropFirmMetricsSchema:
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
            total_trades=50, winning_trades=27, losing_trades=23,
            win_rate=0.55, avg_win=0.0, avg_loss=0.0,
        ),
        prop_firm_compliance=PropFirmComplianceMetrics(
            daily_loss_breaches=0, max_dd_breach=False,
            profit_target_hit=False, min_trading_days_met=False,
        ),
    )


class _FakeRunner:
    """Captures dispatched jobs; returns canned results keyed by params."""

    def __init__(
        self,
        *,
        score_for: dict[tuple, float] | None = None,
        max_dd_for: dict[tuple, float] | None = None,
    ) -> None:
        self.calls: list[tuple[BacktestJobConfig, dict[str, Any]]] = []
        self._scores = score_for or {}
        self._max_dds = max_dd_for or {}

    def __call__(
        self,
        job: BacktestJobConfig,
        *,
        strategy_overrides: dict[str, Any] | None = None,
    ) -> BacktestResult:
        overrides = strategy_overrides or {}
        self.calls.append((job, dict(overrides)))
        key = tuple(sorted(overrides.items()))
        sharpe = self._scores.get(key, 1.0)
        max_dd = self._max_dds.get(key, 5.0)
        # Encode score into final_balance so the default objective
        # (net_pnl) reflects whatever the test asked for.
        final = Decimal("100000") + Decimal(str(sharpe * 1000))
        return BacktestResult(
            strategy_name=job.strategy,
            start=job.start or datetime(2024, 1, 1, tzinfo=UTC),
            end=job.end or datetime(2024, 2, 1, tzinfo=UTC),
            initial_balance=Decimal("100000"),
            final_balance=final,
            metrics=_metrics(max_dd=max_dd, sharpe=sharpe),
        )


# --- ParamSpace -------------------------------------------------------


class TestParamSpace:
    def test_yaml_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "ps.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "name": "ma_crossover",
                    "values": {
                        "fast_period": [3, 5, 7, 10, 14],
                        "slow_period": [20, 30, 50],
                    },
                }
            )
        )
        ps = ParamSpace.from_yaml(path)
        assert ps.name == "ma_crossover"
        assert ps.values["fast_period"] == [3, 5, 7, 10, 14]
        assert ps.values["slow_period"] == [20, 30, 50]

    def test_cartesian_size(self) -> None:
        ps = ParamSpace(name="x", values={"a": [1, 2], "b": [3, 4, 5]})
        assert ps.cartesian_size() == 6

    def test_empty_values_one_combo(self) -> None:
        # No params → one trivial "default" combination.
        ps = ParamSpace(name="x", values={})
        assert ps.cartesian_size() == 1

    def test_rejects_non_list_values(self) -> None:
        with pytest.raises(ValueError, match="list"):
            ParamSpace(name="x", values={"a": 7})  # type: ignore[arg-type]

    def test_rejects_empty_list(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            ParamSpace(name="x", values={"a": []})

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="name"):
            ParamSpace(name="", values={"a": [1]})

    def test_rejects_yaml_top_level_not_mapping(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("- a\n- b\n")
        with pytest.raises(ValueError, match="mapping"):
            ParamSpace.from_yaml(path)


# --- SweepBudget ------------------------------------------------------


class TestSweepBudget:
    def test_default_cap_is_200(self) -> None:
        # Decision §3 cap.
        b = SweepBudget()
        assert b.max_trials == 200

    def test_rejects_non_positive(self) -> None:
        with pytest.raises(ValueError, match="max_trials"):
            SweepBudget(max_trials=0)

    def test_is_frozen(self) -> None:
        b = SweepBudget()
        with pytest.raises((AttributeError, TypeError)):
            b.max_trials = 9999  # type: ignore[misc]


# --- default_max_dd_early_stop ----------------------------------------


class TestDefaultMaxDDEarlyStop:
    def test_default_threshold_is_10pct(self) -> None:
        # Risk R3 default — combos with > 10% drawdown are skip-recorded.
        es = default_max_dd_early_stop()
        # Probe via a constructed result: a 15% DD should trigger.
        bad = BacktestResult(
            strategy_name="x",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
            initial_balance=Decimal("100000"),
            final_balance=Decimal("85000"),
            metrics=_metrics(max_dd=15.0),
        )
        assert es.should_stop(bad) is True

    def test_skips_under_threshold(self) -> None:
        es = default_max_dd_early_stop()
        good = BacktestResult(
            strategy_name="x",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
            initial_balance=Decimal("100000"),
            final_balance=Decimal("105000"),
            metrics=_metrics(max_dd=5.0),
        )
        assert es.should_stop(good) is False

    def test_custom_threshold(self) -> None:
        es = default_max_dd_early_stop(threshold_pct=3.0)
        marginal = BacktestResult(
            strategy_name="x",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
            initial_balance=Decimal("100000"),
            final_balance=Decimal("96000"),
            metrics=_metrics(max_dd=4.0),
        )
        assert es.should_stop(marginal) is True

    def test_no_metrics_skip_recorded(self) -> None:
        # A combo with no metrics either crashed silently or never
        # traded; promoting it as a low-DD survivor would be wrong.
        # Sentinel +inf makes the > threshold check trip → skip-record.
        es = default_max_dd_early_stop()
        no_metrics = BacktestResult(
            strategy_name="x",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
            initial_balance=Decimal("100000"),
            final_balance=Decimal("100000"),
            metrics=None,
        )
        assert es.should_stop(no_metrics) is True


# --- run_parameter_sweep ----------------------------------------------


class TestRunParameterSweep:
    def test_dispatches_one_job_per_combo_random(self) -> None:
        ps = ParamSpace(
            name="ma_crossover",
            values={"fast_period": [5, 7], "slow_period": [20, 30]},
        )
        runner = _FakeRunner()
        result = run_parameter_sweep(
            spec=_spec(),
            manifest=_manifest(),
            window_name="in_sample",
            venue=_venue(),
            param_space=ps,
            sampler="random",
            seed=42,
            runner=runner,
        )
        # 4 combos × 1 trial each.
        assert len(result.combos) == 4
        # Every dispatched job has the same instrument_symbol and venue.
        for job, _ in runner.calls:
            assert job.instrument_symbol == "XAUUSD"
            assert job.venue == _venue()

    def test_caps_random_sample_at_budget(self) -> None:
        # 5 × 5 = 25 combos available; budget caps at 4.
        ps = ParamSpace(
            name="ma_crossover",
            values={
                "fast_period": [3, 5, 7, 10, 14],
                "slow_period": [20, 30, 40, 50, 60],
            },
        )
        runner = _FakeRunner()
        result = run_parameter_sweep(
            spec=_spec(),
            manifest=_manifest(),
            window_name="in_sample",
            venue=_venue(),
            param_space=ps,
            budget=SweepBudget(max_trials=4),
            sampler="random",
            seed=42,
            runner=runner,
        )
        assert len(result.combos) == 4
        assert len(runner.calls) == 4

    def test_grid_sweep_runs_full_cartesian_when_within_budget(self) -> None:
        ps = ParamSpace(name="x", values={"a": [1, 2], "b": [3, 4]})
        runner = _FakeRunner()
        result = run_parameter_sweep(
            spec=_spec(),
            manifest=_manifest(),
            window_name="in_sample",
            venue=_venue(),
            param_space=ps,
            sampler="grid",
            runner=runner,
        )
        assert len(result.combos) == 4

    def test_grid_sweep_refuses_when_over_budget(self) -> None:
        # 5 × 5 × 5 = 125 combos; budget caps at 50 — grid is exhaustive
        # so the harness must refuse rather than silently truncate.
        ps = ParamSpace(
            name="x",
            values={"a": [1, 2, 3, 4, 5], "b": [1, 2, 3, 4, 5],
                    "c": [1, 2, 3, 4, 5]},
        )
        with pytest.raises(SweepCapExceededError, match="125"):
            run_parameter_sweep(
                spec=_spec(),
                manifest=_manifest(),
                window_name="in_sample",
                venue=_venue(),
                param_space=ps,
                budget=SweepBudget(max_trials=50),
                sampler="grid",
                runner=_FakeRunner(),
            )

    def test_random_seed_deterministic(self) -> None:
        ps = ParamSpace(
            name="x",
            values={"a": list(range(10)), "b": list(range(10))},
        )
        runner_a = _FakeRunner()
        run_parameter_sweep(
            spec=_spec(),
            manifest=_manifest(),
            window_name="in_sample",
            venue=_venue(),
            param_space=ps,
            budget=SweepBudget(max_trials=20),
            sampler="random",
            seed=99,
            runner=runner_a,
        )
        runner_b = _FakeRunner()
        run_parameter_sweep(
            spec=_spec(),
            manifest=_manifest(),
            window_name="in_sample",
            venue=_venue(),
            param_space=ps,
            budget=SweepBudget(max_trials=20),
            sampler="random",
            seed=99,
            runner=runner_b,
        )
        # Same seed → same sampled combos in same order.
        assert (
            [overrides for _, overrides in runner_a.calls]
            == [overrides for _, overrides in runner_b.calls]
        )

    def test_early_stop_records_skip_status(self) -> None:
        ps = ParamSpace(name="x", values={"a": [1, 2]})
        runner = _FakeRunner(
            max_dd_for={(("a", 1),): 15.0, (("a", 2),): 4.0}
        )
        result = run_parameter_sweep(
            spec=_spec(),
            manifest=_manifest(),
            window_name="in_sample",
            venue=_venue(),
            param_space=ps,
            sampler="grid",
            runner=runner,
        )
        statuses = {tuple(sorted(c.params.items())): c.status for c in result.combos}
        # Combo with 15% DD is skip-recorded; the other runs normally.
        assert statuses[(("a", 1),)] == "early_stop"
        assert statuses[(("a", 2),)] == "ok"
        # Skip-record means the combo IS in the result list (not aborted).
        assert len(result.combos) == 2

    def test_runner_failure_recorded(self) -> None:
        ps = ParamSpace(name="x", values={"a": [1]})

        def crashy(
            job: BacktestJobConfig,
            *,
            strategy_overrides: dict[str, Any] | None = None,
        ) -> BacktestResult:
            raise RuntimeError("boom")

        result = run_parameter_sweep(
            spec=_spec(),
            manifest=_manifest(),
            window_name="in_sample",
            venue=_venue(),
            param_space=ps,
            sampler="grid",
            runner=crashy,
        )
        assert len(result.combos) == 1
        assert result.combos[0].status == "failed"
        assert "boom" in (result.combos[0].error or "")

    def test_unknown_sampler_raises(self) -> None:
        ps = ParamSpace(name="x", values={"a": [1]})
        with pytest.raises(ValueError, match="sampler"):
            run_parameter_sweep(
                spec=_spec(),
                manifest=_manifest(),
                window_name="in_sample",
                venue=_venue(),
                param_space=ps,
                sampler="weird",  # type: ignore[arg-type]
                runner=_FakeRunner(),
            )

    def test_unknown_window_raises(self) -> None:
        ps = ParamSpace(name="x", values={"a": [1]})
        with pytest.raises(KeyError, match="oos_reserve"):
            run_parameter_sweep(
                spec=_spec(),
                manifest=_manifest(),
                window_name="oos_reserve",
                venue=_venue(),
                param_space=ps,
                sampler="grid",
                runner=_FakeRunner(),
            )

    def test_non_finite_score_demoted_to_failed(self, monkeypatch) -> None:
        # If the objective ever returns NaN/inf the combo must be
        # demoted, not silently ranked. Patch the harness's local
        # ``_default_objective`` to force the path.
        from src.backtesting.dataset import sweep_harness as sh

        def nan_objective(_: BacktestResult) -> float:
            return float("nan")

        monkeypatch.setattr(sh, "_default_objective", nan_objective)
        ps = ParamSpace(name="x", values={"a": [1]})
        result = run_parameter_sweep(
            spec=_spec(),
            manifest=_manifest(),
            window_name="in_sample",
            venue=_venue(),
            param_space=ps,
            sampler="grid",
            runner=_FakeRunner(),
        )
        assert result.combos[0].status == "failed"
        assert "non-finite" in (result.combos[0].error or "")

    def test_optuna_unavailable_raises_helpful_error(self) -> None:
        # optuna is not in the project deps; the harness must fail
        # fast with a message pointing to the random fallback rather
        # than a bare ImportError.
        ps = ParamSpace(name="x", values={"a": [1]})
        with pytest.raises(RuntimeError, match="optuna"):
            run_parameter_sweep(
                spec=_spec(),
                manifest=_manifest(),
                window_name="in_sample",
                venue=_venue(),
                param_space=ps,
                sampler="optuna",
                runner=_FakeRunner(),
            )


# --- render_sweep_section ---------------------------------------------


class TestRenderSweepSection:
    def _result(self) -> SweepResult:
        # Three combos: one early-stopped, one failed, one ok with score.
        ok = CombinationResult(
            params={"fast_period": 5, "slow_period": 20},
            status="ok",
            result=None,
            score=1500.0,
        )
        skipped = CombinationResult(
            params={"fast_period": 7, "slow_period": 30},
            status="early_stop",
            result=None,
            score=float("-inf"),
        )
        failed = CombinationResult(
            params={"fast_period": 10, "slow_period": 50},
            status="failed",
            result=None,
            score=float("-inf"),
            error="boom",
        )
        return SweepResult(combos=[ok, skipped, failed])

    def test_includes_run_label_and_strategy(self) -> None:
        text = render_sweep_section(
            "ma_crossover", self._result(), top_n=3
        )
        assert "ma_crossover" in text
        assert "1500" in text or "1.50" in text or "1.5" in text

    def test_top_n_limits_rows(self) -> None:
        ok_a = CombinationResult(params={"a": 1}, status="ok",
                                 result=None, score=10.0)
        ok_b = CombinationResult(params={"a": 2}, status="ok",
                                 result=None, score=20.0)
        ok_c = CombinationResult(params={"a": 3}, status="ok",
                                 result=None, score=30.0)
        sweep = SweepResult(combos=[ok_a, ok_b, ok_c])
        text = render_sweep_section("x", sweep, top_n=2)
        # Only the top 2 by score are present in the table.
        # (a=3 score 30 > a=2 score 20 > a=1 score 10)
        assert "{'a': 3}" in text
        assert "{'a': 2}" in text
        assert "{'a': 1}" not in text

    def test_summary_counts_statuses(self) -> None:
        text = render_sweep_section("x", self._result(), top_n=3)
        # Footer reports ok / early_stop / failed counts.
        assert "ok" in text.lower()
        assert "early" in text.lower() or "skip" in text.lower()
        assert "fail" in text.lower()

    def test_no_results_yields_polite_message(self) -> None:
        empty = SweepResult(combos=[])
        text = render_sweep_section("x", empty, top_n=3)
        assert text.strip() != ""

    def test_pipe_in_strategy_name_sanitised(self) -> None:
        text = render_sweep_section("ma|c", self._result(), top_n=3)
        assert "ma\\|c" in text
