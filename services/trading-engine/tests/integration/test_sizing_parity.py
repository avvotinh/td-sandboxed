"""Sizing parity — realised loss must equal the designed risk budget.

Permanent regression gate for the lot-vs-unit sizing bug
(``docs/strategy-redesign-plan-2026-07-02.md`` §1): the
``RiskBasedPositionSizer`` returns **MT5 lots** (XAUUSD: 1 lot = 100 oz,
FX: 1 lot = 100 000 units) but the submit path feeds that number straight
into ``Instrument.make_qty``, where the backtest instruments define
1 quantity = 1 oz / 1 unit of base currency. The realised risk is
therefore ~1/100 (XAUUSD) or ~1/100 000 (FX) of the configured
``risk_percent``.

The contract under test: for a single trade that exits on its stop-loss,

    |realised price loss (USD)| ≈ risk_percent × account_balance   (±5%)

The probe strategy below is deliberately minimal but uses the REAL
production machinery for everything the bug touches — balance read,
ATR bracket math, ``RiskBasedPositionSizer``, ``_submit_bracket_order``
→ ``make_qty`` — driven through a real ``BacktestEngine`` on synthetic
bars. Only signal generation is stubbed (one SELL, then silence), so the
test is deterministic: trending-up bars walk price into the SHORT stop.

The loss is measured price-only (quote Δ × qty, excluding commissions):
fee-model correctness is a separate concern (redesign plan Track 1.4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, PositionSide
from nautilus_trader.model.objects import Money

from src.lab.engine import BacktestRunner, BacktestRunnerConfig
from src.lab.runner_facade import _build_instrument
from src.lab.synthetic_bars import generate_bars
from src.kernel.signal import SignalType
from src.kernel.strategies.base_strategy import BaseStrategy
from src.kernel.strategies.bracket_strategy import (
    BracketStrategyConfig,
    BracketStrategyMixin,
    is_atr_unsafe,
)
from src.kernel.strategies.mixins.atr_stop_mixin import ATRStopMixin
from src.kernel.strategies.mixins.risk_sized_mixin import RiskSizedMixin
from src.kernel.strategies.risk_based_position_sizer import (
    RiskBasedPositionSizer,
    RiskBasedSizerConfig,
)


pytestmark = pytest.mark.integration


_STARTING_BALANCE = Decimal("100000")
_RISK_PERCENT = Decimal("1.0")
_TOLERANCE = Decimal("0.05")


class _ProbeConfig(BracketStrategyConfig, frozen=True, kw_only=True):
    """Bracket config for the one-shot probe (no extra fields)."""


class _OneShotShortProbe(
    BaseStrategy,
    ATRStopMixin,
    RiskSizedMixin,
    BracketStrategyMixin,
):
    """Fires exactly one SELL bracket through the production submit path.

    Mirrors the concrete bracket strategies' composition (same MRO as
    Donchian/Supertrend minus scale-out) so the trade travels the exact
    chain under test: ``_read_account_balance`` →
    ``_compute_bracket_params`` (sizer) → ``_submit_bracket_order`` →
    ``make_qty``. Signal logic is replaced by "SELL on the first bar
    with an initialised ATR, then never again".
    """

    def __init__(self, config: _ProbeConfig) -> None:
        super().__init__(config)
        self._atr = AverageTrueRange(config.atr_period)
        self._fired = False
        self.set_position_sizer(
            RiskBasedPositionSizer(
                RiskBasedSizerConfig(risk_percent=config.risk_percent)
            )
        )

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self._atr)

    def generate_signal(self, bar: Bar) -> SignalType:
        if self._fired or not self._atr.initialized:
            return SignalType.NONE
        return SignalType.SELL

    def _execute_signal(self, signal: SignalType) -> None:
        if is_atr_unsafe(self._atr.value):
            return
        self._fired = True
        self._submit_bracket_for_entry(signal, Decimal(str(self._atr.value)))


class _SymbolCase:
    """Per-symbol scenario: synthetic-bar scale for the trade setup.

    Contract economics (contract size, quote currency, JPY conversion)
    are NOT parameterised here — they come from the production
    ``ContractSpec`` registry via the sizing chain under test.
    """

    def __init__(
        self,
        *,
        symbol: str,
        start_price: float,
        drift_scale: float,
        noise_scale: float,
    ) -> None:
        self.symbol = symbol
        self.start_price = start_price
        self.drift_scale = drift_scale
        self.noise_scale = noise_scale


_CASES = [
    pytest.param(
        _SymbolCase(
            symbol="XAUUSD",
            start_price=2400.0,
            drift_scale=1.0,
            noise_scale=1.0,
        ),
        id="XAUUSD",
    ),
    pytest.param(
        _SymbolCase(
            symbol="EURUSD",
            start_price=1.10,
            drift_scale=0.0008,
            noise_scale=0.001,
        ),
        id="EURUSD",
    ),
    pytest.param(
        _SymbolCase(
            symbol="USDJPY",
            start_price=150.0,
            drift_scale=0.2,
            noise_scale=0.2,
        ),
        id="USDJPY",
    ),
]


def _run_single_sl_trade(case: _SymbolCase) -> BacktestRunner:
    """Run one SHORT bracket to its stop-loss; return the runner (undisposed)."""
    instrument, _ = _build_instrument(case.symbol)
    bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")

    # Trending-up bars: the probe SELLs once ATR(14) initialises, price
    # keeps climbing, the SHORT stop (entry + 4×ATR) fills within a few
    # bars, and the TP (entry − 8×ATR, below) is never touched.
    start_ts = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
    bars = generate_bars(
        pattern="trending",
        count=120,
        start_price=case.start_price,
        seed=42,
        start_ts=start_ts,
        bar_type=bar_type,
        price_precision=instrument.price_precision,
        volume_precision=instrument.size_precision,
        drift_scale=case.drift_scale,
        noise_scale=case.noise_scale,
    )

    runner = BacktestRunner(
        config=BacktestRunnerConfig(
            strategy_name="sizing_parity_probe",
            initial_balance=_STARTING_BALANCE,
            currency="USD",
        )
    )
    runner.add_venue(
        venue=instrument.id.venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money(_STARTING_BALANCE, USD)],
        base_currency=USD,
    )
    runner.add_instrument(instrument)
    runner.add_data(bars)

    config = _ProbeConfig(
        instrument_id=instrument.id,
        bar_type=bar_type,
        trade_size=Decimal("1"),
        atr_period=14,
        # Wide stop so the design lot size stays inside the sizer's
        # [min_lot_size, max_lot_size] clamps for every symbol — the
        # clamp must not mask the parity being measured.
        sl_atr_mult=Decimal("4.0"),
        tp_atr_mult=Decimal("8.0"),
        risk_percent=_RISK_PERCENT,
    )
    runner.add_strategy(_OneShotShortProbe(config=config))
    runner.run()
    return runner


def _realized_price_loss_usd(runner: BacktestRunner, symbol: str) -> Decimal:
    """Price-only loss (USD) of the single closed SHORT position."""
    positions = list(runner._engine.cache.positions_closed())
    assert len(positions) == 1, (
        f"Expected exactly 1 closed position, got {len(positions)} — "
        "the probe should enter once and exit on its SL within the run."
    )
    pos = positions[0]
    assert pos.side == PositionSide.FLAT
    assert pos.entry == OrderSide.SELL

    qty = Decimal(str(pos.peak_qty.as_double()))
    open_px = Decimal(str(pos.avg_px_open))
    close_px = Decimal(str(pos.avg_px_close))
    loss_quote = (close_px - open_px) * qty  # SHORT: SL fills above entry
    assert loss_quote > 0, (
        f"Position closed in profit ({loss_quote=}) — expected the SL "
        "(not the TP) to close it; check the synthetic-bar drift setup."
    )
    if symbol.endswith("JPY"):
        # Quote currency is JPY; convert at the exit rate (the instrument
        # price IS the USDJPY rate).
        return loss_quote / close_px
    return loss_quote


@pytest.mark.parametrize("case", _CASES)
def test_sl_loss_matches_risk_budget(case: _SymbolCase) -> None:
    """One SL-hit trade must realise ≈ risk_percent × balance.

    This is the invariant every FTMO compliance number depends on. It
    fails on the current code because sizer lots reach the engine as
    raw units (see module docstring); it must pass — for ALL symbols,
    including the JPY quote-currency conversion — once the sizing fix
    (redesign plan Track 1.2/1.3) lands.
    """
    runner = _run_single_sl_trade(case)
    try:
        loss_usd = _realized_price_loss_usd(runner, case.symbol)
    finally:
        runner.dispose()

    expected = _STARTING_BALANCE * _RISK_PERCENT / Decimal("100")
    deviation = abs(loss_usd - expected) / expected
    assert deviation <= _TOLERANCE, (
        f"{case.symbol}: realised SL loss ${loss_usd:.2f} deviates "
        f"{deviation:.1%} from the designed risk budget ${expected:.2f} "
        f"(risk_percent={_RISK_PERCENT}% of ${_STARTING_BALANCE}). "
        "Lot-vs-unit sizing parity is broken (redesign plan §1)."
    )
