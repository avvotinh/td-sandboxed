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
from nautilus_trader.model.data import Bar

from src.indicators import RSI
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


class RSIMeanReversionConfig(BracketStrategyConfig, frozen=True, kw_only=True):
    rsi_period: int = 14
    oversold: float = 0.3
    overbought: float = 0.7
    exit_neutral: float = 0.5
    # MR-specific defaults
    sl_atr_mult: Decimal = Decimal("1.0")
    tp_atr_mult: Decimal = Decimal("2.0")

    def __post_init__(self) -> None:
        if self.rsi_period <= 0:
            raise ValueError(f"rsi_period must be positive, got {self.rsi_period}")
        if not 0 <= self.oversold < self.exit_neutral < self.overbought <= 1:
            raise ValueError(
                "thresholds must satisfy 0 ≤ oversold < exit_neutral < overbought ≤ 1"
            )


@register_strategy("rsi_mean_reversion", regimes=[RegimeState.RANGING])
class RSIMeanReversionStrategy(
    BaseStrategy, ATRStopMixin, RiskSizedMixin, BracketStrategyMixin
):
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
        atr_value = Decimal(str(self._atr.value))
        self._submit_bracket_for_entry(signal, atr_value)
