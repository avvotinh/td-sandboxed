"""Typer ``backtest`` subcommand — run / sweep / walkforward.

Wired into the top-level trading-engine CLI via
``app.add_typer(backtest_app, name="backtest")``. Each subcommand reads
a ``BacktestJobConfig`` YAML file, dispatches the corresponding helper
(``run_backtest`` / ``ParameterSweep`` / ``WalkForward``), and prints a
human-readable summary by default or machine-readable JSON with
``--json`` / ``--out``.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from tabulate import tabulate
from typing_extensions import Annotated

from src.backtesting._cli_utils import (
    parse_date,
    parse_duration,
    read_yaml,
    result_to_json_dict,
    write_json,
)
from src.backtesting.job_config import BacktestJobConfig
from src.backtesting.parameter_sweep import (
    EarlyStopConfig,
    ParameterSweep,
    SweepResult,
)
from src.backtesting.result import BacktestResult
from src.backtesting.runner_facade import run_backtest
from src.backtesting.walk_forward import WalkForward, WalkForwardFolds, WalkForwardResult


backtest_app = typer.Typer(
    name="backtest",
    help="Run point backtests, parameter sweeps, and walk-forward analyses.",
    add_completion=False,
    no_args_is_help=True,
)


def _load_job_or_exit(job_path: Path) -> BacktestJobConfig:
    try:
        return BacktestJobConfig.from_yaml(job_path)
    except FileNotFoundError as exc:
        typer.echo(f"Job file not found: {job_path}", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"Invalid job config: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _load_grid_or_exit(grid_path: Path) -> dict[str, list[Any]]:
    try:
        data = read_yaml(grid_path)
    except FileNotFoundError as exc:
        typer.echo(f"Grid file not found: {grid_path}", err=True)
        raise typer.Exit(code=1) from exc
    if not isinstance(data, dict):
        typer.echo("Grid YAML must be a mapping of param_name -> list", err=True)
        raise typer.Exit(code=1)
    for key, values in data.items():
        if not isinstance(values, list):
            typer.echo(f"Grid value for {key!r} must be a list", err=True)
            raise typer.Exit(code=1)
    return data


# --- `backtest run` ---------------------------------------------------


@backtest_app.command("run")
def run_cmd(
    job: Annotated[
        Path, typer.Option("--job", "-j", help="Path to job YAML")
    ],
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON")
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help="Write JSON result to this file (implies --json)",
        ),
    ] = None,
) -> None:
    """Run a single point backtest."""
    cfg = _load_job_or_exit(job)
    try:
        result = run_backtest(cfg)
    except Exception as exc:
        typer.echo(f"Backtest failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    payload = result_to_json_dict(result)

    if out is not None:
        if out.suffix.lower() == ".html":
            from src.backtesting.reports.html_writer import write_html_report

            write_html_report(result, out)
        else:
            write_json(out, payload)
        typer.echo(f"Result written to {out}")
        return
    if json_output:
        typer.echo(json.dumps(payload, indent=2, default=str))
        return

    _print_run_summary(result)


def _print_run_summary(result: BacktestResult) -> None:
    net_pnl = result.final_balance - result.initial_balance
    typer.echo("Backtest Result")
    typer.echo("=" * 15)
    typer.echo(f"Strategy:        {result.strategy_name}")
    typer.echo(f"Window:          {result.start} → {result.end}")
    typer.echo(f"Initial balance: {result.initial_balance}")
    typer.echo(f"Final balance:   {result.final_balance}")
    typer.echo(f"Net PnL:         {net_pnl}")
    typer.echo(f"Trades:          {len(result.trades)}")
    typer.echo(f"Breaches:        {len(result.breaches)}")
    if result.metrics is not None:
        typer.echo(f"Win rate:        {result.metrics.trades.win_rate:.2%}")
        typer.echo(f"Max overall DD:  {result.metrics.drawdown.max_overall_dd_pct:.2f}%")


# --- `backtest sweep` -------------------------------------------------


@backtest_app.command("sweep")
def sweep_cmd(
    job: Annotated[Path, typer.Option("--job", "-j")],
    grid: Annotated[Path, typer.Option("--grid", "-g")],
    search: Annotated[
        str, typer.Option("--search", help="grid | random")
    ] = "grid",
    n_iter: Annotated[
        int | None, typer.Option("--n-iter", help="Random search iteration count")
    ] = None,
    workers: Annotated[
        int, typer.Option("--workers", help="Number of worker processes", min=1)
    ] = 1,
    seed: Annotated[int, typer.Option("--seed")] = 42,
    early_stop_metric: Annotated[
        str | None,
        typer.Option(
            "--early-stop-metric",
            help="Metric name (e.g. max_overall_dd_pct) — skip-record combos past threshold",
        ),
    ] = None,
    early_stop_threshold: Annotated[
        float | None,
        typer.Option("--early-stop-threshold"),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="Directory or file for JSON output")
    ] = None,
) -> None:
    """Grid or random parameter sweep."""
    cfg = _load_job_or_exit(job)
    param_grid = _load_grid_or_exit(grid)

    if search not in ("grid", "random"):
        typer.echo(f"Invalid search: {search!r}", err=True)
        raise typer.Exit(code=1)

    early_stop: EarlyStopConfig | None = None
    if early_stop_metric is not None and early_stop_threshold is not None:
        early_stop = EarlyStopConfig(
            metric_fn=_metric_extractor(early_stop_metric),
            threshold=early_stop_threshold,
            mode="gt",
        )

    sweep = ParameterSweep(
        job=cfg,
        param_grid=param_grid,
        search=search,  # type: ignore[arg-type]
        n_iter=n_iter,
        seed=seed,
        early_stop=early_stop,
    )
    try:
        sweep_result = sweep.run(max_workers=workers)
    except Exception as exc:
        typer.echo(f"Sweep failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    ok_count = sum(1 for c in sweep_result.combos if c.status == "ok")
    if ok_count == 0:
        typer.echo("All combos failed.", err=True)
        raise typer.Exit(code=2)

    _print_sweep_summary(sweep_result)
    if out is not None:
        payload = {
            "combos": [
                {
                    "params": c.params,
                    "status": c.status,
                    "score": c.score,
                    "error": c.error,
                    "result": (
                        result_to_json_dict(c.result) if c.result else None
                    ),
                }
                for c in sweep_result.combos
            ]
        }
        write_json(out if out.suffix == ".json" else out / "sweep.json", payload)


def _print_sweep_summary(sweep_result: SweepResult) -> None:
    ranked = sweep_result.ranked()
    rows = []
    for rank, combo in enumerate(ranked[:20], start=1):
        rows.append([rank, combo.score, _format_params(combo.params)])
    typer.echo("Parameter Sweep — Top Results")
    typer.echo("=" * 30)
    typer.echo(
        tabulate(rows, headers=["Rank", "Score", "Params"], tablefmt="simple")
    )
    fail = sum(1 for c in sweep_result.combos if c.status == "failed")
    early = sum(1 for c in sweep_result.combos if c.status == "early_stop")
    typer.echo("")
    typer.echo(f"Total: {len(sweep_result.combos)}  OK: {len(ranked)}  Failed: {fail}  Early-stop: {early}")


def _format_params(params: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(params.items()))


def _extract_named_metric(metric: str, res: BacktestResult) -> float:
    """Pull ``metric`` off ``result.metrics`` regardless of which section holds it.

    Must stay at module level so ``functools.partial`` wrappers pickle
    cleanly when the sweep runs with ``ProcessPoolExecutor``.
    """
    if res.metrics is None:
        return 0.0
    for section_name in ("drawdown", "pnl", "risk", "trades", "ftmo_compliance"):
        section = getattr(res.metrics, section_name, None)
        if section is None:
            continue
        if hasattr(section, metric):
            return float(getattr(section, metric))
    return 0.0


def _metric_extractor(metric: str) -> Callable[[BacktestResult], float]:
    """Return a picklable ``metric_fn`` bound to ``metric``."""
    return functools.partial(_extract_named_metric, metric)


# --- `backtest walkforward` ------------------------------------------


@backtest_app.command("walkforward")
def walkforward_cmd(
    job: Annotated[Path, typer.Option("--job", "-j")],
    grid: Annotated[Path, typer.Option("--grid", "-g")],
    start: Annotated[str, typer.Option("--start", help="ISO date")],
    end: Annotated[str, typer.Option("--end", help="ISO date")],
    train: Annotated[str, typer.Option("--train", help="e.g. 90d, 30d")],
    test: Annotated[str, typer.Option("--test")],
    step: Annotated[str, typer.Option("--step")],
    mode: Annotated[
        str, typer.Option("--mode", help="anchored | rolling")
    ] = "anchored",
    search: Annotated[str, typer.Option("--search")] = "grid",
    n_iter: Annotated[int | None, typer.Option("--n-iter")] = None,
    workers: Annotated[int, typer.Option("--workers", min=1)] = 1,
    seed: Annotated[int, typer.Option("--seed")] = 42,
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Walk-forward optimization + out-of-sample evaluation."""
    cfg = _load_job_or_exit(job)
    param_grid = _load_grid_or_exit(grid)

    if mode not in ("anchored", "rolling"):
        typer.echo(f"Invalid mode: {mode!r}", err=True)
        raise typer.Exit(code=1)
    if search not in ("grid", "random"):
        typer.echo(f"Invalid search: {search!r}", err=True)
        raise typer.Exit(code=1)

    try:
        total_start = parse_date(start)
        total_end = parse_date(end)
        folds = WalkForwardFolds.generate(
            total_start=total_start,
            total_end=total_end,
            train_window=parse_duration(train),
            test_window=parse_duration(test),
            step=parse_duration(step),
            mode=mode,  # type: ignore[arg-type]
        )
    except ValueError as exc:
        typer.echo(f"Invalid fold config: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    wf = WalkForward(
        job=cfg,
        folds=folds,
        param_grid=param_grid,
        search=search,  # type: ignore[arg-type]
        n_iter=n_iter,
        seed=seed,
        mode=mode,  # type: ignore[arg-type]
    )
    try:
        wf_result = wf.run(max_workers=workers)
    except Exception as exc:
        typer.echo(f"Walk-forward failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    _print_walkforward_summary(wf_result)
    if out is not None:
        payload = _walkforward_to_json(wf_result)
        target = out if out.suffix == ".json" else out / "walkforward.json"
        write_json(target, payload)


def _print_walkforward_summary(wf_result: WalkForwardResult) -> None:
    typer.echo(f"Walk-Forward ({wf_result.mode})")
    typer.echo("=" * 25)
    rows = []
    for i, fr in enumerate(wf_result.folds, start=1):
        test_pnl = (
            (fr.test_result.final_balance - fr.test_result.initial_balance)
            if fr.test_result is not None
            else "-"
        )
        rows.append(
            [
                i,
                fr.fold.train_start.date(),
                fr.fold.train_end.date(),
                fr.fold.test_end.date(),
                _format_params(fr.best_params),
                test_pnl,
            ]
        )
    typer.echo(
        tabulate(
            rows,
            headers=["Fold", "Train Start", "Train End", "Test End", "Best Params", "OOS PnL"],
            tablefmt="simple",
        )
    )


def _walkforward_to_json(wf_result: WalkForwardResult) -> dict[str, Any]:
    return {
        "mode": wf_result.mode,
        "folds": [
            {
                "fold": {
                    "train_start": fr.fold.train_start.isoformat(),
                    "train_end": fr.fold.train_end.isoformat(),
                    "test_start": fr.fold.test_start.isoformat(),
                    "test_end": fr.fold.test_end.isoformat(),
                },
                "best_params": fr.best_params,
                "train_score": fr.train_score,
                "train_result": (
                    result_to_json_dict(fr.train_result) if fr.train_result else None
                ),
                "test_result": (
                    result_to_json_dict(fr.test_result) if fr.test_result else None
                ),
            }
            for fr in wf_result.folds
        ],
    }
