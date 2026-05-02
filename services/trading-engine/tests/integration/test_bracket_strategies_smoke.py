"""End-to-end smoke tests for the 5 bracket strategies (Story 8.9).

Runs each strategy through the real ``run_backtest`` facade on 500
synthetic bars and asserts that the pipeline composes without crashing
and produces a well-formed ``BacktestResult``. These tests complement
the existing MACrossover smoke (``test_backtest_smoke.py``) by
exercising Supertrend / Donchian / RSI MR / Bollinger MR / ORB — the
four strategies that previously had no integration coverage.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from src.backtesting.job_config import (
    BacktestJobConfig,
    SyntheticDataSpec,
    VenueSpec,
)
from src.backtesting.result import BacktestResult
from src.backtesting.runner_facade import run_backtest


pytestmark = pytest.mark.integration


_VENUE = VenueSpec(
    name="SIM", starting_balance=Decimal("100000"), currency="USD"
)


def _common_bracket_params() -> dict:
    return {
        "atr_period": 14,
        "risk_percent": Decimal("1.0"),
        "pip_size": Decimal("0.0001"),
        "pip_value_per_lot": Decimal("10.0"),
        "trade_size": Decimal("10000"),
    }


def _base_job(strategy: str, params: dict) -> BacktestJobConfig:
    return BacktestJobConfig(
        strategy=strategy,
        strategy_params=params,
        venue=_VENUE,
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


def _assert_well_formed(result: BacktestResult, strategy: str) -> None:
    assert result.strategy_name == strategy
    assert result.initial_balance == Decimal("100000")
    assert isinstance(result.trades, list)
    assert isinstance(result.breaches, list)


def test_supertrend_smoke() -> None:
    job = _base_job(
        "supertrend",
        {
            **_common_bracket_params(),
            "period": 10,
            "multiplier": 3.0,
            "sl_atr_mult": Decimal("1.5"),
            "tp_atr_mult": Decimal("3.0"),
        },
    )
    t0 = time.monotonic()
    result = run_backtest(job)
    assert time.monotonic() - t0 < 10.0
    _assert_well_formed(result, "supertrend")


def test_donchian_smoke() -> None:
    job = _base_job(
        "donchian_breakout",
        {
            **_common_bracket_params(),
            "channel_period": 20,
            "sl_atr_mult": Decimal("2.0"),
            "tp_atr_mult": Decimal("4.0"),
        },
    )
    t0 = time.monotonic()
    result = run_backtest(job)
    assert time.monotonic() - t0 < 10.0
    _assert_well_formed(result, "donchian_breakout")


def test_rsi_mean_reversion_smoke() -> None:
    job = _base_job(
        "rsi_mean_reversion",
        {
            **_common_bracket_params(),
            "rsi_period": 14,
            "oversold": 0.3,
            "overbought": 0.7,
            "exit_neutral": 0.5,
            "sl_atr_mult": Decimal("1.0"),
            "tp_atr_mult": Decimal("2.0"),
        },
    )
    t0 = time.monotonic()
    result = run_backtest(job)
    assert time.monotonic() - t0 < 10.0
    _assert_well_formed(result, "rsi_mean_reversion")


def test_bollinger_mean_reversion_smoke() -> None:
    job = _base_job(
        "bollinger_mean_reversion",
        {
            **_common_bracket_params(),
            "period": 20,
            "num_std": 2.0,
            "sl_atr_mult": Decimal("1.0"),
            "tp_atr_mult": Decimal("2.0"),
        },
    )
    t0 = time.monotonic()
    result = run_backtest(job)
    assert time.monotonic() - t0 < 10.0
    _assert_well_formed(result, "bollinger_mean_reversion")


def test_orb_smoke() -> None:
    # Synthetic bars start at 2024-01-01 00:00 UTC; match the ORB session
    # to the full 24h UTC window so every bar is in-session.
    job = _base_job(
        "orb",
        {
            **_common_bracket_params(),
            "session_open_hour": 0,
            "session_open_minute": 0,
            "session_close_hour": 23,
            "session_close_minute": 59,
            "session_tz": "UTC",
            "opening_range_minutes": 30,
            "sl_atr_mult": Decimal("1.0"),
            "tp_atr_mult": Decimal("2.0"),
        },
    )
    t0 = time.monotonic()
    result = run_backtest(job)
    assert time.monotonic() - t0 < 10.0
    _assert_well_formed(result, "orb")
