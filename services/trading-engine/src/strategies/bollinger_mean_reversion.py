"""Bollinger-band mean-reversion strategy.

Enters long when close pierces the lower band, short on upper band
breach. Exits at the middle band (SMA) or SL/TP, whichever comes first.

Uses the Nautilus :class:`BollingerBands` indicator re-exported as
:class:`src.indicators.Bollinger`.
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.data import Bar

from src.indicators import Bollinger
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


class BollingerMeanReversionConfig(BracketStrategyConfig, frozen=True, kw_only=True):
    period: int = 20
    num_std: float = 2.0
    sl_atr_mult: Decimal = Decimal("1.0")
    tp_atr_mult: Decimal = Decimal("2.0")

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.period <= 0:
            raise ValueError(f"period must be positive, got {self.period}")
        if self.num_std <= 0:
            raise ValueError(f"num_std must be positive, got {self.num_std}")
        # Sanity cap to catch misconfigured YAML; not a tunable threshold.
        # Typical Bollinger usage sits at 1.5–3.0σ. Anything above 5σ
        # produces bands so wide that price never touches them, silently
        # yielding zero-trade backtests with no error. Per
        # `sandboxed-domain.md`, business thresholds load from YAML —
        # this is a structural guardrail, not a tunable.
        if self.num_std > 5.0:
            raise ValueError(
                "num_std must be <= 5.0 (typical range 1.5–3.0); "
                f"got {self.num_std}"
            )


@register_strategy(
    "bollinger_mean_reversion",
    regimes=[RegimeState.RANGING],
)
class BollingerMeanReversionStrategy(
    BaseStrategy, ATRStopMixin, RiskSizedMixin, BracketStrategyMixin
):
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
        atr_value = Decimal(str(self._atr.value))
        self._submit_bracket_for_entry(signal, atr_value)
