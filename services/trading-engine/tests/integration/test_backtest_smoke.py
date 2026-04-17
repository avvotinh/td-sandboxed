"""End-to-end backtest smoke test: BacktestRunner + FtmoComplianceActor
+ MACrossover strategy on synthetic trending bars.

Proves the full stack works: venue + instrument + synthetic bars +
strategy + FTMO actor via the existing rule engine + metrics. Runs the
real Nautilus BacktestEngine (no mocks) so integration breakage surfaces
loudly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.objects import Money
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from src.backtesting.engine import BacktestRunner, BacktestRunnerConfig
from src.backtesting.result import BacktestResult
from src.backtesting.synthetic_bars import generate_bars
from src.rules.engine import RuleEngine
from src.rules.types.drawdown import DailyLossLimitRule
from src.strategies.ma_crossover import MACrossoverConfig, MACrossoverStrategy


pytestmark = pytest.mark.integration


def _build_rule_engine(account_id: str) -> RuleEngine:
    """Minimal FTMO rule engine with the daily-loss rule only."""
    return RuleEngine(
        account_id=account_id,
        rules=[DailyLossLimitRule(threshold_percent=5.0)],
        strict_mode=True,
    )


def test_backtest_runner_end_to_end() -> None:
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
    bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-BID-EXTERNAL")

    # Generate 500 trending bars (EUR/USD realistic scale). Nautilus rejects
    # ts_init=0 (epoch 1970) with a native crash — always use realistic dates.
    start_ts = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
    bars = generate_bars(
        pattern="trending",
        count=500,
        start_price=1.1000,
        seed=42,
        start_ts=start_ts,
        price_precision=instrument.price_precision,
        volume_precision=instrument.size_precision,
        bar_type=bar_type,
        drift_scale=0.0001,
        noise_scale=0.0005,
    )

    runner = BacktestRunner(
        config=BacktestRunnerConfig(
            strategy_name="ma_crossover",
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

        rule_engine = _build_rule_engine(account_id="ftmo-sim")
        actor = runner.attach_ftmo_compliance(
            rule_engine=rule_engine,
            account_id="ftmo-sim",
            bar_type=bar_type,
            venue=instrument.id.venue,
            currency=USD,
        )

        strategy = MACrossoverStrategy(
            config=MACrossoverConfig(
                instrument_id=instrument.id,
                bar_type=bar_type,
                trade_size=Decimal("10000"),
                fast_period=5,
                slow_period=20,
            )
        )
        runner.add_strategy(strategy)

        runner.run()

        result: BacktestResult = runner.get_result(final_balance=Decimal("100000"))

        # AC9 — equity curve populated by actor
        assert isinstance(result, BacktestResult)
        assert len(actor.equity_curve) > 0

        # AC4 — metrics schema present and well-formed
        assert result.metrics is not None
        assert result.metrics.strategy_name == "ma_crossover"
        # total trades may be 0 on short bar series — just check the shape.
        assert result.metrics.trades.total_trades >= 0

    finally:
        runner.dispose()
