"""Bollinger-band mean-reversion strategy.

Enters long when close pierces the lower band, short on upper band
breach. Exits at the middle band (SMA) or SL/TP, whichever comes first.

Uses the Nautilus :class:`BollingerBands` indicator re-exported as
:class:`src.indicators.Bollinger`.
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.indicators import Bollinger
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


class BollingerMeanReversionConfig(BaseStrategyConfig, frozen=True, kw_only=True):
    period: int = 20
    num_std: float = 2.0
    atr_period: int = 14
    sl_atr_mult: Decimal = Decimal("1.0")
    tp_atr_mult: Decimal = Decimal("2.0")
    risk_percent: Decimal = Decimal("1.0")
    pip_size: Decimal = Decimal("0.01")
    pip_value_per_lot: Decimal = Decimal("1.0")
    initial_balance_fallback: Decimal = Decimal("100000")

    def __post_init__(self) -> None:
        if self.period <= 0:
            raise ValueError(f"period must be positive, got {self.period}")
        if self.num_std <= 0:
            raise ValueError(f"num_std must be positive, got {self.num_std}")


@register_strategy("bollinger_mean_reversion")
class BollingerMeanReversionStrategy(BaseStrategy, ATRStopMixin, RiskSizedMixin):
    """Mean-reversion — buy lower-band touch, sell upper-band touch."""

    def __init__(self, config: BollingerMeanReversionConfig) -> None:
        super().__init__(config)
        self._bb = Bollinger(period=config.period, k=config.num_std)
        self._atr = AverageTrueRange(config.atr_period)
        self.set_position_sizer(
            RiskBasedPositionSizer(
                RiskBasedSizerConfig(risk_percent=config.risk_percent)
            )
        )

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self._bb)
        self.register_indicator_for_bars(self.config.bar_type, self._atr)

    def on_reset(self) -> None:
        self._bb.reset()
        self._atr.reset()

    def generate_signal(self, bar: Bar) -> SignalType:
        if not self._bb.initialized or not self._atr.initialized:
            return SignalType.NONE

        close = bar.close.as_double()
        upper = self._bb.upper
        middle = self._bb.middle
        lower = self._bb.lower

        # Exit first — middle-band mean reversion target.
        if self.is_long and close >= middle:
            return SignalType.CLOSE
        if self.is_short and close <= middle:
            return SignalType.CLOSE

        if not self.is_flat:
            return SignalType.NONE

        if close < lower:
            return SignalType.BUY
        if close > upper:
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
