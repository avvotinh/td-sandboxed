"""Supertrend trend-following strategy.

Goes long on a Supertrend flip from -1 (downtrend) to +1 (uptrend), short on
the mirror flip. Each entry is a market bracket order with:

- Stop-loss at ``entry ± sl_atr_mult * ATR``
- Take-profit at ``entry ± tp_atr_mult * ATR`` (opposite side)

Position size is risk-percent based — computed from live account balance
via the injected :class:`RiskBasedPositionSizer`. Returns ``Decimal(0)``
for insufficient capital; the bracket helper gracefully skips on ``<=0``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.indicators.supertrend import Supertrend
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

if TYPE_CHECKING:
    from nautilus_trader.indicators.volatility import AverageTrueRange


class SupertrendConfig(BaseStrategyConfig, frozen=True, kw_only=True):
    """Configuration for :class:`SupertrendStrategy`."""

    period: int = 10
    multiplier: float = 3.0
    atr_period: int = 14
    sl_atr_mult: Decimal = Decimal("1.5")
    tp_atr_mult: Decimal = Decimal("3.0")
    risk_percent: Decimal = Decimal("1.0")
    pip_size: Decimal = Decimal("0.01")  # XAUUSD default
    pip_value_per_lot: Decimal = Decimal("1.0")  # XAUUSD default
    initial_balance_fallback: Decimal = Decimal("100000")

    def __post_init__(self) -> None:
        if self.period <= 0:
            raise ValueError(f"period must be positive, got {self.period}")
        if self.multiplier <= 0:
            raise ValueError(f"multiplier must be positive, got {self.multiplier}")
        if self.atr_period <= 0:
            raise ValueError(f"atr_period must be positive, got {self.atr_period}")
        if self.sl_atr_mult <= 0:
            raise ValueError(f"sl_atr_mult must be positive, got {self.sl_atr_mult}")
        if self.tp_atr_mult <= 0:
            raise ValueError(f"tp_atr_mult must be positive, got {self.tp_atr_mult}")


@register_strategy("supertrend")
class SupertrendStrategy(BaseStrategy, ATRStopMixin, RiskSizedMixin):
    """Trend-following strategy driven by the Supertrend indicator."""

    def __init__(self, config: SupertrendConfig) -> None:
        super().__init__(config)
        self._supertrend = Supertrend(
            period=config.period, multiplier=config.multiplier
        )
        # Import inside __init__ to avoid circulars at module load.
        from nautilus_trader.indicators.volatility import AverageTrueRange

        self._atr: AverageTrueRange = AverageTrueRange(config.atr_period)
        self.set_position_sizer(
            RiskBasedPositionSizer(
                RiskBasedSizerConfig(risk_percent=config.risk_percent)
            )
        )
        self._prev_trend: int | None = None

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self._supertrend)
        self.register_indicator_for_bars(self.config.bar_type, self._atr)
        self._log.info(
            f"Supertrend started period={self.config.period} mult={self.config.multiplier}"
        )

    def on_reset(self) -> None:
        self._supertrend.reset()
        self._atr.reset()
        self._prev_trend = None

    def generate_signal(self, bar: Bar) -> SignalType:
        if not self._supertrend.initialized or not self._atr.initialized:
            return SignalType.NONE

        current_trend = self._supertrend.trend
        prev = self._prev_trend
        self._prev_trend = current_trend

        if prev is None:
            return SignalType.NONE  # First initialised bar — seed only.

        if current_trend == prev:
            return SignalType.NONE

        # Trend flipped
        if current_trend == 1:
            return SignalType.BUY
        if current_trend == -1:
            return SignalType.SELL
        return SignalType.NONE

    # on_bar is inherited from BaseStrategy and will call generate_signal;
    # we override _execute_signal to build bracket orders with live data.

    def _execute_signal(self, signal: SignalType) -> None:
        if signal == SignalType.NONE:
            return

        # Position reversal — close before entering the opposite side.
        if signal == SignalType.BUY and self.is_short:
            self._close_position()
        elif signal == SignalType.SELL and self.is_long:
            self._close_position()
        elif signal == SignalType.CLOSE:
            self._close_position()
            return

        if not self.is_flat:
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
        """Return ``(qty, sl_price, tp_price)`` — pure, deterministic."""
        sl_price = self.calculate_atr_stop(
            side=side,
            entry_price=entry_price,
            atr_value=atr_value,
            multiplier=self.config.sl_atr_mult,
        )
        tp_price = self.calculate_atr_take_profit(
            side=side,
            entry_price=entry_price,
            atr_value=atr_value,
            multiplier=self.config.tp_atr_mult,
        )
        qty = self.size_from_risk(
            account_balance=account_balance,
            entry_price=entry_price,
            stop_price=sl_price,
            pip_value_per_lot=self.config.pip_value_per_lot,
            pip_size=self.config.pip_size,
        )
        return qty, sl_price, tp_price

    def _last_bar(self) -> Bar | None:
        """Retrieve the most recent bar from Nautilus's cache."""
        try:
            return self.cache.bar(self.config.bar_type, index=0)
        except Exception:
            return None

    def _read_account_balance(self) -> Decimal:
        """Read current equity from the portfolio; fall back to config."""
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
