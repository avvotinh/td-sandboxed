"""Unit tests for the `backtest` CLI subcommand (Story 8.8)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.backtesting import cli as backtest_cli
from src.backtesting.parameter_sweep import CombinationResult, SweepResult
from src.backtesting.result import BacktestResult
from src.backtesting.walk_forward import FoldResult, FoldSpec, WalkForwardResult


runner = CliRunner()


_SAMPLE_JOB_YAML = """\
strategy: ma_crossover
instrument_symbol: EUR/USD
bar_type_suffix: 1-MINUTE-BID-EXTERNAL
venue:
  name: SIM
  starting_balance: "100000"
  currency: USD
strategy_params:
  fast_period: 5
  slow_period: 20
  trade_size: "10000"
data:
  kind: synthetic
  pattern: trending
  count: 200
  start_price: 1.10
  seed: 7
"""


def _write_job(tmp_path: Path) -> Path:
    p = tmp_path / "job.yaml"
    p.write_text(_SAMPLE_JOB_YAML)
    return p


def _fake_result(balance: float = 100500) -> BacktestResult:
    return BacktestResult(
        strategy_name="ma_crossover",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
        initial_balance=Decimal("100000"),
        final_balance=Decimal(str(balance)),
    )


@pytest.mark.unit
class TestBacktestRun:
    def test_run_ok_prints_summary(self, tmp_path: Path) -> None:
        job_path = _write_job(tmp_path)
        with patch.object(backtest_cli, "run_backtest", return_value=_fake_result()):
            result = runner.invoke(
                backtest_cli.backtest_app, ["run", "--job", str(job_path)]
            )
        assert result.exit_code == 0, result.output
        assert "ma_crossover" in result.output
        assert "100500" in result.output or "500" in result.output

    def test_run_json_flag_emits_json(self, tmp_path: Path) -> None:
        job_path = _write_job(tmp_path)
        with patch.object(backtest_cli, "run_backtest", return_value=_fake_result()):
            result = runner.invoke(
                backtest_cli.backtest_app,
                ["run", "--job", str(job_path), "--json"],
            )
        assert result.exit_code == 0, result.output
        assert '"strategy_name"' in result.output
        assert '"final_balance"' in result.output

    def test_run_bad_job_exits_one(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("not a valid job mapping\n- 1\n- 2\n")
        result = runner.invoke(
            backtest_cli.backtest_app, ["run", "--job", str(bad)]
        )
        assert result.exit_code == 1

    def test_run_missing_job_file_exits_one(self, tmp_path: Path) -> None:
        result = runner.invoke(
            backtest_cli.backtest_app,
            ["run", "--job", str(tmp_path / "nope.yaml")],
        )
        assert result.exit_code == 1


@pytest.mark.unit
class TestBacktestSweep:
    def test_sweep_dispatches_parameter_sweep(self, tmp_path: Path) -> None:
        job_path = _write_job(tmp_path)
        grid_path = tmp_path / "grid.yaml"
        grid_path.write_text("fast_period: [3, 5]\nslow_period: [10, 20]\n")

        combos = [
            CombinationResult(
                params={"fast_period": 3, "slow_period": 10},
                status="ok",
                result=_fake_result(100500),
                score=500.0,
            ),
            CombinationResult(
                params={"fast_period": 5, "slow_period": 20},
                status="ok",
                result=_fake_result(101000),
                score=1000.0,
            ),
        ]
        with patch.object(backtest_cli, "ParameterSweep") as sweep_cls:
            sweep_cls.return_value.run.return_value = SweepResult(combos=combos)

            result = runner.invoke(
                backtest_cli.backtest_app,
                [
                    "sweep",
                    "--job",
                    str(job_path),
                    "--grid",
                    str(grid_path),
                    "--workers",
                    "1",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "fast_period" in result.output

    def test_sweep_returns_exit_two_on_all_failed(self, tmp_path: Path) -> None:
        job_path = _write_job(tmp_path)
        grid_path = tmp_path / "grid.yaml"
        grid_path.write_text("fast_period: [3]\n")

        combos = [
            CombinationResult(
                params={"fast_period": 3},
                status="failed",
                result=None,
                score=float("-inf"),
                error="boom",
            ),
        ]
        with patch.object(backtest_cli, "ParameterSweep") as sweep_cls:
            sweep_cls.return_value.run.return_value = SweepResult(combos=combos)
            result = runner.invoke(
                backtest_cli.backtest_app,
                [
                    "sweep",
                    "--job",
                    str(job_path),
                    "--grid",
                    str(grid_path),
                ],
            )
        assert result.exit_code == 2


@pytest.mark.unit
class TestBacktestWalkForward:
    def test_walkforward_summary(self, tmp_path: Path) -> None:
        job_path = _write_job(tmp_path)
        grid_path = tmp_path / "grid.yaml"
        grid_path.write_text("fast_period: [3, 5]\n")

        fold = FoldSpec(
            train_start=datetime(2024, 1, 1, tzinfo=UTC),
            train_end=datetime(2024, 2, 1, tzinfo=UTC),
            test_start=datetime(2024, 2, 1, tzinfo=UTC),
            test_end=datetime(2024, 3, 1, tzinfo=UTC),
        )
        wf_result = WalkForwardResult(
            folds=[
                FoldResult(
                    fold=fold,
                    best_params={"fast_period": 3},
                    train_score=500.0,
                    train_result=_fake_result(100500),
                    test_result=_fake_result(100300),
                )
            ],
            mode="anchored",
        )
        with patch.object(backtest_cli, "WalkForward") as wf_cls:
            wf_cls.return_value.run.return_value = wf_result
            result = runner.invoke(
                backtest_cli.backtest_app,
                [
                    "walkforward",
                    "--job",
                    str(job_path),
                    "--grid",
                    str(grid_path),
                    "--start",
                    "2024-01-01",
                    "--end",
                    "2024-04-01",
                    "--train",
                    "30d",
                    "--test",
                    "30d",
                    "--step",
                    "30d",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "fast_period" in result.output


@pytest.mark.unit
class TestDurationParser:
    def test_days(self) -> None:
        from src.backtesting._cli_utils import parse_duration

        assert parse_duration("30d").days == 30

    def test_hours(self) -> None:
        from src.backtesting._cli_utils import parse_duration

        assert parse_duration("6h").total_seconds() == 6 * 3600

    def test_bad_format_raises(self) -> None:
        from src.backtesting._cli_utils import parse_duration

        with pytest.raises(ValueError):
            parse_duration("xyz")
