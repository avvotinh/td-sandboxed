"""End-to-end smoke test for parameter sweep + walk-forward (Story 8.8).

Runs real ``ParameterSweep`` + ``WalkForward`` on MACrossover + synthetic
trending bars via the ``run_backtest`` facade. No Nautilus mocks — proves
the entire pipeline composes correctly under the sweep/walk-forward
drivers.

Stays short (500 bars, 2×2 grid, 2 folds) to keep CI runtime bounded.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.backtesting.job_config import (
    BacktestJobConfig,
    SyntheticDataSpec,
    VenueSpec,
)
from src.backtesting.parameter_sweep import ParameterSweep
from src.backtesting.walk_forward import FoldSpec, WalkForward


pytestmark = pytest.mark.integration


def _job() -> BacktestJobConfig:
    return BacktestJobConfig(
        strategy="ma_crossover",
        strategy_params={
            "fast_period": 5,
            "slow_period": 20,
            "trade_size": "10000",
        },
        venue=VenueSpec(
            name="SIM", starting_balance=Decimal("100000"), currency="USD"
        ),
        instrument_symbol="EUR/USD",
        bar_type_suffix="1-MINUTE-BID-EXTERNAL",
        data=SyntheticDataSpec(
            pattern="trending",
            count=500,
            start_price=1.10,
            seed=42,
            drift_scale=0.0001,
            noise_scale=0.0005,
        ),
    )


def test_parameter_sweep_smoke() -> None:
    grid = {"fast_period": [3, 5], "slow_period": [15, 30]}
    sweep = ParameterSweep(
        job=_job(),
        param_grid=grid,
        search="grid",
    )

    t0 = time.monotonic()
    result = sweep.run(max_workers=1)
    elapsed = time.monotonic() - t0

    assert len(result.combos) == 4
    assert all(c.status != "failed" for c in result.combos), (
        [c.error for c in result.combos]
    )
    assert elapsed < 15.0, f"Sweep took too long: {elapsed:.2f}s"


def test_walkforward_smoke() -> None:
    # run_backtest stamps synthetic bars starting from 2024-01-01 UTC with
    # 1-minute spacing (500 bars ≈ 8h20). Fold boundaries are chosen to
    # match that window.
    base = datetime(2024, 1, 1, tzinfo=UTC)
    folds = [
        FoldSpec(
            train_start=base,
            train_end=base + timedelta(minutes=200),
            test_start=base + timedelta(minutes=200),
            test_end=base + timedelta(minutes=300),
        ),
        FoldSpec(
            train_start=base,
            train_end=base + timedelta(minutes=300),
            test_start=base + timedelta(minutes=300),
            test_end=base + timedelta(minutes=400),
        ),
    ]

    wf = WalkForward(
        job=_job(),
        folds=folds,
        param_grid={"fast_period": [3, 5]},
        mode="anchored",
    )

    t0 = time.monotonic()
    result = wf.run(max_workers=1)
    elapsed = time.monotonic() - t0

    assert len(result.folds) == 2
    assert elapsed < 20.0, f"Walk-forward took too long: {elapsed:.2f}s"
    for fr in result.folds:
        assert fr.best_params, "best_params should be populated when sweep succeeds"
