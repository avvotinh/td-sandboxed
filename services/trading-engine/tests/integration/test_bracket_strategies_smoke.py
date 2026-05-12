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


# ---------------------------------------------------------------------------
# Story 13.7 — Supertrend scale-out + trail E2E on synthetic bars
# ---------------------------------------------------------------------------


def test_supertrend_scale_out_e2e_synthetic_bars() -> None:
    """Phase 1 lifecycle on a real Nautilus BacktestEngine.

    Drives SupertrendStrategy with scale_out_enabled + trailing_enabled
    through a strongly-trending synthetic series and verifies that the
    full 13.2-13.6 stack composes end-to-end:

    - The Phase 1 config fields load.
    - The mixin's ``__init__`` runs via cooperative super().
    - Position-lifecycle events flow through ``_dispatch_scale_out_event``.
    - On-bar evaluation triggers ``_close_partial`` (reduce_only) when
      the bar close crosses +1R.
    - The trail indicator wires up alongside the signal indicator.
    - Backtest completes without crashing.

    Hand-crafted bar sequences are kept out of scope — synthetic
    "trending" with stronger drift produces enough trend to fire the
    signal + the scale-out trigger reliably under seed=42 (regression-
    pinned via assertions below). Deterministic exact-PnL verification
    of each leg lands in story 13.9's backtest A/B harness once the
    XAUUSD dataset is fetched.
    """
    from datetime import UTC, datetime

    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.enums import AccountType, OmsType, OrderType
    from nautilus_trader.model.objects import Money
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    from src.backtesting.engine import BacktestRunner, BacktestRunnerConfig
    from src.backtesting.synthetic_bars import generate_bars
    from src.strategies.supertrend import SupertrendConfig, SupertrendStrategy

    # BTCUSDT has size_precision=6 (fractional units OK) and
    # price_precision=2 — closer to a XAUUSD-like setup where the
    # sizer can produce sub-unit lots without _make_qty rounding
    # them to zero. Fractional EUR/USD with size_precision=0 forces
    # the sizer to fail (0.45 lots → 0) under any realistic ATR.
    instrument = TestInstrumentProvider.btcusdt_binance()
    bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")

    # Mean-reverting pattern with strong noise so the price oscillates
    # enough to produce Supertrend trend flips. A pure unidirectional
    # trend never flips after the seed bar (signal only fires on
    # FLIPS, not on continued trend), so we use mean-reverting +
    # noise_scale=200 to swing the price ~$15K around start_price=50K
    # over 500 bars. That clears the 3.0 × ATR Supertrend band several
    # times, firing multiple BUY/SELL signals and at least one full
    # scale-out + trail lifecycle.
    start_ts = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
    bars = generate_bars(
        pattern="mean_reverting",
        count=500,
        start_price=50000.0,
        seed=42,
        start_ts=start_ts,
        price_precision=instrument.price_precision,
        volume_precision=instrument.size_precision,
        bar_type=bar_type,
        drift_scale=10.0,
        noise_scale=200.0,
    )

    runner = BacktestRunner(
        config=BacktestRunnerConfig(
            strategy_name="supertrend",
            initial_balance=Decimal("100000"),
            currency="USD",
        )
    )

    try:
        runner.add_venue(
            venue=instrument.id.venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(100000, USD)],
            base_currency=USD,
        )
        runner.add_instrument(instrument)
        runner.add_data(bars)

        # BTCUSDT pip economics: pip_size=1.0 (one dollar), value per
        # lot = 1.0 (one BTC = one dollar per pip). With $100K balance
        # and 1% risk, sizer returns ~6.67 BTC at typical ATR of ~$150
        # — well within BTCUSDT's 0.000001 size_increment.
        config = SupertrendConfig(
            instrument_id=instrument.id,
            bar_type=bar_type,
            trade_size=Decimal("0.1"),
            period=10,
            multiplier=3.0,
            atr_period=14,
            sl_atr_mult=Decimal("1.5"),
            tp_atr_mult=Decimal("3.0"),
            risk_percent=Decimal("1.0"),
            pip_size=Decimal("1.0"),
            pip_value_per_lot=Decimal("1.0"),
            # Phase 1 fields — feature flags ON.
            scale_out_enabled=True,
            scale_out_r_trigger=Decimal("1.0"),
            scale_out_close_fraction=Decimal("0.5"),
            breakeven_at_r=Decimal("1.0"),
            trailing_enabled=True,
            trailing_atr_period=7,
            trailing_atr_multiplier=Decimal("2.1"),
        )
        strategy = SupertrendStrategy(config=config)
        runner.add_strategy(strategy)

        t0 = time.monotonic()
        runner.run()
        elapsed = time.monotonic() - t0
        assert elapsed < 15.0, f"Backtest took {elapsed:.1f}s"

        # The trail indicator must be constructed when trailing_enabled.
        assert strategy._supertrend_trail is not None

        # Pull every order Nautilus saw during the run. cache.orders()
        # lives on the underlying engine — direct introspection mirrors
        # the test-internal pattern other integration suites use.
        all_orders = list(runner._engine.cache.orders())

        # Bracket entries are MARKET (reduce_only=False). Bracket SLs
        # are STOP_MARKET, TPs are LIMIT — both reduce_only=True. The
        # scale-out partial close emits a STANDALONE MARKET order with
        # reduce_only=True (no parent / no contingency), so filter on
        # the reduce_only + MARKET combo to isolate scale-out fires.
        # Direct attribute access (not getattr-with-default) so a
        # Nautilus rename surfaces as a loud AttributeError instead of
        # a silent miss.
        scale_out_partials = [
            o
            for o in all_orders
            if o.is_reduce_only and o.order_type == OrderType.MARKET
        ]
        bracket_entries = [
            o
            for o in all_orders
            if not o.is_reduce_only and o.order_type == OrderType.MARKET
        ]

        # Smoking-gun assertion: scale-out partial-close path fired.
        # This proves the full 13.2-13.6 stack (config → mixin → bar
        # evaluator → _close_partial → reduce_only market submission)
        # composed correctly under a real Nautilus BacktestEngine.
        assert len(scale_out_partials) >= 1, (
            "No scale-out partial-close orders found. Expected at "
            "least one reduce-only MARKET (not STOP_MARKET / LIMIT). "
            f"Total orders={len(all_orders)}, "
            f"bracket entries={len(bracket_entries)}. "
            "Verify _evaluate_scale_out_for_bar drives the mixin and "
            "the bar-driven init retry recovers from the SL race."
        )

        # Sanity check: at least one signal fired and produced a
        # bracket entry. Without this the test could pass on a
        # zero-trade run — defensive for future bar-noise tweaks.
        assert len(bracket_entries) >= 1, (
            "No bracket entry MARKET orders submitted — Supertrend "
            "produced zero signals on the synthetic series."
        )
    finally:
        runner.dispose()


def test_donchian_scale_out_e2e_synthetic_bars() -> None:
    """Story 13.10 mirror of the Supertrend scale-out e2e test.

    Drives ``DonchianBreakoutStrategy`` with ``scale_out_enabled`` +
    ``trailing_enabled`` on a synthetic series rich enough to produce
    breakouts past the prior 20-bar channel and at least one +1R
    favorable move so the partial-close path fires. The assertion is
    the same smoking gun: at least one reduce-only MARKET order
    (the standalone scale-out partial), distinct from the bracket SL
    (STOP_MARKET) and bracket TP (LIMIT) child legs.
    """
    from datetime import UTC, datetime

    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.enums import AccountType, OmsType, OrderType
    from nautilus_trader.model.objects import Money
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    from src.backtesting.engine import BacktestRunner, BacktestRunnerConfig
    from src.backtesting.synthetic_bars import generate_bars
    from src.strategies.donchian_breakout import (
        DonchianBreakoutConfig,
        DonchianBreakoutStrategy,
    )

    instrument = TestInstrumentProvider.btcusdt_binance()
    bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")

    # Mean-reverting + heavy noise mirrors the Supertrend e2e setup:
    # large swings produce closes that pierce the prior 20-bar channel
    # bands several times across 500 bars. Donchian only enters on flat
    # (no reversal logic), so the test catches a single trade cycle
    # rather than many flips — fine for the smoking-gun assertion.
    start_ts = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
    bars = generate_bars(
        pattern="mean_reverting",
        count=500,
        start_price=50000.0,
        seed=42,
        start_ts=start_ts,
        price_precision=instrument.price_precision,
        volume_precision=instrument.size_precision,
        bar_type=bar_type,
        drift_scale=10.0,
        noise_scale=200.0,
    )

    runner = BacktestRunner(
        config=BacktestRunnerConfig(
            strategy_name="donchian_breakout",
            initial_balance=Decimal("100000"),
            currency="USD",
        )
    )

    try:
        runner.add_venue(
            venue=instrument.id.venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(100000, USD)],
            base_currency=USD,
        )
        runner.add_instrument(instrument)
        runner.add_data(bars)

        config = DonchianBreakoutConfig(
            instrument_id=instrument.id,
            bar_type=bar_type,
            trade_size=Decimal("0.1"),
            channel_period=20,
            atr_period=14,
            sl_atr_mult=Decimal("2.0"),
            tp_atr_mult=Decimal("4.0"),
            risk_percent=Decimal("1.0"),
            pip_size=Decimal("1.0"),
            pip_value_per_lot=Decimal("1.0"),
            # Phase 1 fields — feature flags ON.
            scale_out_enabled=True,
            scale_out_r_trigger=Decimal("1.0"),
            scale_out_close_fraction=Decimal("0.5"),
            breakeven_at_r=Decimal("1.0"),
            trailing_enabled=True,
            trailing_atr_period=7,
            trailing_atr_multiplier=Decimal("2.1"),
        )
        strategy = DonchianBreakoutStrategy(config=config)
        runner.add_strategy(strategy)

        t0 = time.monotonic()
        runner.run()
        elapsed = time.monotonic() - t0
        assert elapsed < 15.0, f"Backtest took {elapsed:.1f}s"

        assert strategy._supertrend_trail is not None

        all_orders = list(runner._engine.cache.orders())
        scale_out_partials = [
            o
            for o in all_orders
            if o.is_reduce_only and o.order_type == OrderType.MARKET
        ]
        bracket_entries = [
            o
            for o in all_orders
            if not o.is_reduce_only and o.order_type == OrderType.MARKET
        ]

        assert len(scale_out_partials) >= 1, (
            "No scale-out partial-close orders found. Expected at least "
            "one reduce-only MARKET (not STOP_MARKET / LIMIT). "
            f"Total orders={len(all_orders)}, "
            f"bracket entries={len(bracket_entries)}."
        )
        assert len(bracket_entries) >= 1, (
            "No bracket entry MARKET orders — Donchian produced zero "
            "signals on the synthetic series."
        )
    finally:
        runner.dispose()
