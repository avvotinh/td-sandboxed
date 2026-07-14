"""Integration — pin the real Nautilus bracket contract for TradeRecord levels.

The unit tests for ``_extract_bracket_levels`` mock the cache, so they
pin OUR parsing logic but not Nautilus's actual event shapes. This test
runs a real bracket strategy with the trailing tactic through a real
``BacktestEngine`` and asserts that

* every closed trade recovers an initial SL + TP from the bracket legs,
* trailed trades report an ``sl_price`` (initial) that differs from the
  final trailed level — i.e. ``OrderInitialized.options["trigger_price"]``
  still carries the ORIGINAL trigger. A Nautilus upgrade that renames
  that key would silently fall back to the latest trigger and fail here.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.backtesting.job_config import (
    BacktestJobConfig,
    SyntheticDataSpec,
    VenueSpec,
)
from src.backtesting.runner_facade import run_backtest

pytestmark = pytest.mark.integration


def test_bracket_levels_recovered_from_real_engine_cache() -> None:
    job = BacktestJobConfig(
        strategy="donchian_breakout",
        strategy_params={
            "scale_out_enabled": True,
            "trailing_enabled": True,
        },
        venue=VenueSpec(
            starting_balance=Decimal("100000"),
            oms_type="HEDGING",
        ),
        instrument_symbol="XAUUSD",
        bar_type_suffix="5-MINUTE-LAST-EXTERNAL",
        data=SyntheticDataSpec(
            pattern="trending", count=800, start_price=2000.0
        ),
    )

    result = run_backtest(job)

    assert result.trades, "trending synthetic run should produce trades"
    with_levels = [
        t for t in result.trades if t.sl_price is not None and t.tp_price is not None
    ]
    assert len(with_levels) == len(result.trades), (
        "every bracket-managed trade must recover SL + TP legs"
    )

    # Level directions must match the trade side.
    for t in with_levels:
        if t.side == "BUY":
            assert t.sl_price < t.entry_price < t.tp_price
        else:
            assert t.tp_price < t.entry_price < t.sl_price

    trailed = [t for t in result.trades if t.sl_updates]
    assert trailed, "trailing tactic should modify at least one SL"
    # Initial SL must be the ORIGINAL trigger, not the last trailed value.
    moved = [t for t in trailed if t.sl_updates[-1].price != t.sl_price]
    assert moved, (
        "expected at least one trade whose trailed SL differs from the "
        "initial bracket SL — OrderInitialized.options['trigger_price'] "
        "may have changed shape in this Nautilus version"
    )
    # Update history must be chronological.
    for t in trailed:
        stamps = [u.ts for u in t.sl_updates]
        assert stamps == sorted(stamps)


def _synthetic_trending_job() -> BacktestJobConfig:
    """Shared donchian-on-trending-synthetic job for Contract v2 tests."""
    return BacktestJobConfig(
        strategy="donchian_breakout",
        strategy_params={
            "scale_out_enabled": True,
            "trailing_enabled": True,
        },
        venue=VenueSpec(
            starting_balance=Decimal("100000"),
            oms_type="HEDGING",
        ),
        instrument_symbol="XAUUSD",
        bar_type_suffix="5-MINUTE-LAST-EXTERNAL",
        data=SyntheticDataSpec(
            pattern="trending", count=800, start_price=2000.0
        ),
    )


def test_equity_and_indicators_recorded_without_prop_firm() -> None:
    """Contract v2 P1: a job WITHOUT a prop_firm block still yields a
    populated equity curve (gap G2) and run-recorded indicator series
    (gap G6)."""
    job = _synthetic_trending_job()

    result = run_backtest(job)

    assert job.prop_firm is None
    assert result.equity_curve, "equity curve must populate without prop_firm"
    assert all(ts.tzinfo is not None for ts, _ in result.equity_curve)
    assert result.metrics is not None
    assert result.metrics.drawdown is not None

    keys = {series.key for series in result.indicators}
    assert {"donchian_upper", "donchian_lower"} <= keys
    assert "supertrend_trail" in keys, "trailing enabled → trail series"
    for series in result.indicators:
        stamps = [ts for ts, _ in series.points]
        assert stamps == sorted(stamps)
        assert series.points, f"series {series.key} recorded no points"


def test_equity_curve_marks_to_market_while_position_open() -> None:
    """HIGH-1 acceptance: the recorded equity curve must MOVE while a
    position is open (balance + unrealized PnL), not stay flat at the
    realized balance until the close fills."""
    result = run_backtest(_synthetic_trending_job())

    assert result.trades and result.equity_curve

    moved_intra_trade = False
    differs_from_flat_balance = False
    for trade in result.trades:
        # Equity points strictly inside the trade's open window.
        mids = [
            equity
            for ts, equity in result.equity_curve
            if trade.entry_ts < ts < trade.exit_ts
        ]
        if len(mids) < 2:
            continue  # single-bar trades can't show movement
        if len(set(mids)) > 1:
            moved_intra_trade = True
        # The flat (realized) balance just before entry — mark-to-market
        # equity while open must deviate from it at some point.
        before = [
            equity
            for ts, equity in result.equity_curve
            if ts < trade.entry_ts
        ]
        if before and any(mid != before[-1] for mid in mids):
            differs_from_flat_balance = True
        if moved_intra_trade and differs_from_flat_balance:
            break

    assert moved_intra_trade, (
        "no trade showed intra-trade equity movement — the recorder is "
        "logging realized balance, not mark-to-market equity"
    )
    assert differs_from_flat_balance, (
        "intra-trade equity never deviated from the pre-entry balance"
    )
