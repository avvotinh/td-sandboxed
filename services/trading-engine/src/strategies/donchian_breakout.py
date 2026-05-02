"""Donchian breakout (Turtle-style) trend-following strategy.

Generates a BUY when the current close pierces the **prior** bar's N-bar
Donchian upper band, SELL on prior lower-band breakdown. Using the prior
band is critical: the current bar is always inside its own channel, so
comparing to current-bar bands never triggers.

Orders are submitted as market brackets with ATR-based SL / TP. Position
size is risk-percent based via :class:`RiskBasedPositionSizer`. Position
reversal is not supported here (breakouts rarely reverse cleanly); a
fresh entry only fires when flat.
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.data import Bar

from src.indicators import Donchian
from src.orders.signal import SignalType
from src.strategies.base_strategy import BaseStrategy
from src.strategies.bracket_strategy import (
    BracketStrategyConfig,
    BracketStrategyMixin,
)
from src.strategies.mixins.atr_stop_mixin import ATRStopMixin
from src.strategies.mixins.risk_sized_mixin import RiskSizedMixin
from src.regime.states import RegimeState
from src.strategies.registry import register_strategy
from src.strategies.risk_based_position_sizer import (
    RiskBasedPositionSizer,
    RiskBasedSizerConfig,
)


class DonchianBreakoutConfig(BracketStrategyConfig, frozen=True, kw_only=True):
    channel_period: int = 20
    # Donchian defaults override the generic bracket config defaults
    sl_atr_mult: Decimal = Decimal("2.0")
    tp_atr_mult: Decimal = Decimal("4.0")

    def __post_init__(self) -> None:
        if self.channel_period <= 0:
            raise ValueError(f"channel_period must be positive, got {self.channel_period}")
        if self.atr_period <= 0:
            raise ValueError(f"atr_period must be positive, got {self.atr_period}")
        if self.sl_atr_mult <= 0 or self.tp_atr_mult <= 0:
            raise ValueError("ATR multipliers must be positive")


@register_strategy(
    "donchian_breakout",
    regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN],
)
class DonchianBreakoutStrategy(
    BaseStrategy, ATRStopMixin, RiskSizedMixin, BracketStrategyMixin
):
    """Classical Turtle-style channel breakout strategy."""

    def __init__(self, config: DonchianBreakoutConfig) -> None:
        super().__init__(config)
        self._donchian = Donchian(config.channel_period)
        self._atr = AverageTrueRange(config.atr_period)
        self.set_position_sizer(
            RiskBasedPositionSizer(
                RiskBasedSizerConfig(risk_percent=config.risk_percent)
            )
        )
        self._prev_upper: float | None = None
        self._prev_lower: float | None = None

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self._donchian)
        self.register_indicator_for_bars(self.config.bar_type, self._atr)

    def on_reset(self) -> None:
        self._donchian.reset()
        self._atr.reset()
        self._prev_upper = None
        self._prev_lower = None

    def generate_signal(self, bar: Bar) -> SignalType:
        if not self._donchian.initialized or not self._atr.initialized:
            return SignalType.NONE

        close = bar.close.as_double()
        prev_upper = self._prev_upper
        prev_lower = self._prev_lower

        # Capture current band as the "prior" reference for the next bar
        # BEFORE any return path — otherwise the seed bar never stores it.
        self._prev_upper = self._donchian.upper
        self._prev_lower = self._donchian.lower

        if prev_upper is None or prev_lower is None:
            return SignalType.NONE

        if close > prev_upper:
            return SignalType.BUY
        if close < prev_lower:
            return SignalType.SELL
        return SignalType.NONE

    def _execute_signal(self, signal: SignalType) -> None:
        if signal == SignalType.CLOSE:
            self._close_position()
            return
        atr_value = Decimal(str(self._atr.value))
        self._submit_bracket_for_entry(signal, atr_value)
