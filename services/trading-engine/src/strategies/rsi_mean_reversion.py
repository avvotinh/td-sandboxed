"""RSI mean-reversion strategy.

Enters long when RSI crosses up from the oversold zone (was ≤ threshold,
now rising), short on symmetric overbought cross-down. Exits on RSI
mean-crossover (default 0.5) or at SL/TP.

Nautilus RSI returns a **0–1 scale** (not 0–100) — config thresholds are
specified on the same scale.
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.indicators import RSI
from src.orders.signal import SignalType
from src.strategies.base_strategy import BaseStrategy
from src.strategies.config import BaseStrategyConfig
from src.strategies.mixins.atr_stop_mixin import ATRStopMixin
from src.strategies.mixins.risk_sized_mixin import RiskSizedMixin
from src.strategies.registry import register_strategy
from src.strategies.risk_based_position_sizer import (
    RiskBasedPositionSizer,
    RiskBasedSizerConfig,
)


class RSIMeanReversionConfig(BaseStrategyConfig, frozen=True, kw_only=True):
    rsi_period: int = 14
    oversold: float = 0.3
    overbought: float = 0.7
    exit_neutral: float = 0.5
    atr_period: int = 14
    sl_atr_mult: Decimal = Decimal("1.0")
    tp_atr_mult: Decimal = Decimal("2.0")
    risk_percent: Decimal = Decimal("1.0")
    pip_size: Decimal = Decimal("0.01")
    pip_value_per_lot: Decimal = Decimal("1.0")
    initial_balance_fallback: Decimal = Decimal("100000")

    def __post_init__(self) -> None:
        if self.rsi_period <= 0:
            raise ValueError(f"rsi_period must be positive, got {self.rsi_period}")
        if not 0 <= self.oversold < self.exit_neutral < self.overbought <= 1:
            raise ValueError(
                "thresholds must satisfy 0 ≤ oversold < exit_neutral < overbought ≤ 1"
            )


@register_strategy("rsi_mean_reversion")
class RSIMeanReversionStrategy(BaseStrategy, ATRStopMixin, RiskSizedMixin):
    """Mean-reversion — buy oversold cross-up, sell overbought cross-down."""

    def __init__(self, config: RSIMeanReversionConfig) -> None:
        super().__init__(config)
        self._rsi = RSI(config.rsi_period)
        self._atr = AverageTrueRange(config.atr_period)
        self.set_position_sizer(
            RiskBasedPositionSizer(
                RiskBasedSizerConfig(risk_percent=config.risk_percent)
            )
        )
        self._prev_rsi: float | None = None

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self._rsi)
        self.register_indicator_for_bars(self.config.bar_type, self._atr)

    def on_reset(self) -> None:
        self._rsi.reset()
        self._atr.reset()
        self._prev_rsi = None

    def generate_signal(self, bar: Bar) -> SignalType:
        if not self._rsi.initialized or not self._atr.initialized:
            return SignalType.NONE

        rsi = self._rsi.value
        prev = self._prev_rsi
        self._prev_rsi = rsi

        if prev is None:
            return SignalType.NONE

        # Exit at neutral zone first — priority over new entries.
        if self.is_long and prev < self.config.exit_neutral <= rsi:
            return SignalType.CLOSE
        if self.is_short and prev > self.config.exit_neutral >= rsi:
            return SignalType.CLOSE

        if not self.is_flat:
            return SignalType.NONE

        # Oversold cross-up: previous bar was in oversold, now rising.
        if prev <= self.config.oversold < rsi:
            return SignalType.BUY
        # Overbought cross-down: previous bar was in overbought, now falling.
        if prev >= self.config.overbought > rsi:
            return SignalType.SELL
        return SignalType.NONE

    def _execute_signal(self, signal: SignalType) -> None:
        if signal == SignalType.CLOSE:
            self._close_position()
            return
        if signal == SignalType.NONE or not self.is_flat:
            return

        side = OrderSide.BUY if signal == SignalType.BUY else OrderSide.SELL
        last_bar = self._last_bar()
        if last_bar is None:
            return
        entry_price = Decimal(str(last_bar.close.as_double()))
        atr_value = Decimal(str(self._atr.value))
        balance = self._read_account_balance()
        qty, sl, tp = self._compute_bracket_params(
            side=side,
            entry_price=entry_price,
            atr_value=atr_value,
            account_balance=balance,
        )
        self._submit_bracket_order(side=side, quantity=qty, sl_price=sl, tp_price=tp)

    def _compute_bracket_params(
        self,
        *,
        side: OrderSide,
        entry_price: Decimal,
        atr_value: Decimal,
        account_balance: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal]:
        sl_price = self.calculate_atr_stop(
            side=side, entry_price=entry_price, atr_value=atr_value,
            multiplier=self.config.sl_atr_mult,
        )
        tp_price = self.calculate_atr_take_profit(
            side=side, entry_price=entry_price, atr_value=atr_value,
            multiplier=self.config.tp_atr_mult,
        )
        qty = self.size_from_risk(
            account_balance=account_balance,
            entry_price=entry_price, stop_price=sl_price,
            pip_value_per_lot=self.config.pip_value_per_lot,
            pip_size=self.config.pip_size,
        )
        return qty, sl_price, tp_price

    def _last_bar(self) -> Bar | None:
        try:
            return self.cache.bar(self.config.bar_type, index=0)
        except Exception:
            return None

    def _read_account_balance(self) -> Decimal:
        venue = self.config.bar_type.instrument_id.venue
        try:
            account = self.portfolio.account(venue)
        except Exception:
            return self.config.initial_balance_fallback
        if account is None:
            return self.config.initial_balance_fallback
        balance = account.balance_total(USD)
        if balance is None:
            return self.config.initial_balance_fallback
        return Decimal(str(balance.as_double()))
