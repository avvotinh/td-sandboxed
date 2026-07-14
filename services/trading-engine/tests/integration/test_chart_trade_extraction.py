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
