"""Moving Average Crossover strategy.

EMA-based trend-following: BUY on bullish cross (fast crosses above slow),
SELL on bearish cross. Position reversal is supported — an opposite
signal closes the open position and submits a fresh bracket in the
new direction on the same bar.

Story 13.11 upgraded the strategy from fixed-size market orders to
ATR-based bracket orders + Epic 13 Phase 1 scale-out + Supertrend
trail. ``scale_out_enabled`` defaults False so the legacy single-fill
behaviour (just without the explicit SL / TP previously missing) is
preserved when the operator hasn't opted in.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from nautilus_trader.core.message import Event
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide, PositionSide
from nautilus_trader.model.events import PositionClosed, PositionOpened

from src.indicators.supertrend import Supertrend
from src.orders.signal import SignalType
from src.strategies.base_strategy import BaseStrategy
from src.strategies.bracket_scale_out import BracketScaleOutMixin
from src.strategies.bracket_strategy import (
    BracketStrategyConfig,
    BracketStrategyMixin,
    is_atr_unsafe,
)
from src.strategies.mixins.atr_stop_mixin import ATRStopMixin
from src.strategies.mixins.risk_sized_mixin import RiskSizedMixin
from src.regime.states import RegimeState
from src.strategies.registry import register_strategy
from src.strategies.risk_based_position_sizer import (
    RiskBasedPositionSizer,
    RiskBasedSizerConfig,
)

logger = logging.getLogger(__name__)


class MACrossoverConfig(BracketStrategyConfig, frozen=True, kw_only=True):
    """Configuration for MA Crossover strategy.

    Inherits the full ATR-bracket + Phase 1 scale-out field set from
    :class:`BracketStrategyConfig` (Story 13.11 migration from
    ``BaseStrategyConfig``). The legacy ``trade_size`` field is
    preserved on the inherited surface but is unused by the new
    bracket flow — position size now comes from
    :class:`RiskBasedPositionSizer` keyed on ``risk_percent``.

    Attributes:
        fast_period: Period for fast EMA (default 20)
        slow_period: Period for slow EMA (default 50, must be > fast_period)
    """

    fast_period: int = 20
    slow_period: int = 50

    def __post_init__(self) -> None:
        """Validate configuration after initialization.

        Calls ``super().__post_init__()`` so the full
        :class:`BracketStrategyConfig` invariants (including the
        Phase 1 cross-field guards ``breakeven_at_r ≤
        scale_out_r_trigger`` and "trailing requires scale_out") are
        enforced for MA crossover configs. Supertrend / Donchian
        configs do NOT yet make this call — that's an outstanding
        consistency gap tracked as a follow-up; fixing it on all
        three at once is the natural next refactor.
        """
        super().__post_init__()
        if self.fast_period <= 0:
            raise ValueError(
                f"fast_period must be positive, got {self.fast_period}"
            )
        if self.slow_period <= 0:
            raise ValueError(
                f"slow_period must be positive, got {self.slow_period}"
            )
        if self.slow_period <= self.fast_period:
            raise ValueError(
                f"slow_period ({self.slow_period}) must be > fast_period ({self.fast_period})"
            )


@register_strategy(
    "ma_crossover",
    regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN],
)
class MACrossoverStrategy(
    BracketScaleOutMixin,
    BaseStrategy,
    ATRStopMixin,
    RiskSizedMixin,
    BracketStrategyMixin,
):
    """Moving Average Crossover with ATR brackets + Phase 1 scale-out.

    Generates BUY signal on bullish crossover (fast crosses above slow),
    SELL signal on bearish crossover. Position reversal is preserved
    from the pre-13.11 implementation: an opposite signal closes the
    open position before submitting a new bracket entry on the same bar.

    Phase 1 scale-out + trail tactics (Epic 13) compose via
    ``BracketScaleOutMixin`` — same Story 13.5 wiring as Supertrend
    and Story 13.10 Donchian. Default-OFF.
    """

    def __init__(self, config: MACrossoverConfig) -> None:
        super().__init__(config)
        self.fast_ema = ExponentialMovingAverage(config.fast_period)
        self.slow_ema = ExponentialMovingAverage(config.slow_period)
        self._atr = AverageTrueRange(config.atr_period)
        self._supertrend_trail: Supertrend | None = (
            Supertrend(
                period=config.trailing_atr_period,
                multiplier=float(config.trailing_atr_multiplier),
            )
            if config.trailing_enabled
            else None
        )
        self.set_position_sizer(
            RiskBasedPositionSizer(
                RiskBasedSizerConfig(risk_percent=config.risk_percent)
            )
        )
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
        self.register_indicator_for_bars(self.config.bar_type, self._atr)
        if self._supertrend_trail is not None:
            self.register_indicator_for_bars(
                self.config.bar_type, self._supertrend_trail
            )
        self._log.info(
            f"MACrossover started: fast={self.config.fast_period}, "
            f"slow={self.config.slow_period}"
        )

    def on_reset(self) -> None:
        self.fast_ema.reset()
        self.slow_ema.reset()
        self._atr.reset()
        if self._supertrend_trail is not None:
            self._supertrend_trail.reset()
        self._prev_fast = None
        self._prev_slow = None

    def generate_signal(self, bar: Bar) -> SignalType:
        if not self.fast_ema.initialized or not self.slow_ema.initialized:
            return SignalType.NONE

        fast = self.fast_ema.value
        slow = self.slow_ema.value

        signal = SignalType.NONE

        if self._prev_fast is not None and self._prev_slow is not None:
            if self._prev_fast <= self._prev_slow and fast > slow:
                signal = SignalType.BUY
                self._log.info(
                    f"Bullish crossover: fast={fast:.5f} > slow={slow:.5f}"
                )
            elif self._prev_fast >= self._prev_slow and fast < slow:
                signal = SignalType.SELL
                self._log.info(
                    f"Bearish crossover: fast={fast:.5f} < slow={slow:.5f}"
                )

        self._prev_fast = fast
        self._prev_slow = slow

        return signal

    def _execute_signal(self, signal: SignalType) -> None:
        """Execute signal: reversal-on-cross via bracket entries.

        Pattern mirrors SupertrendStrategy._execute_signal: an opposite
        signal closes the live position before submitting the new
        bracket entry. The bracket helper skips when ATR is unsafe so
        a single flat-bar can't take trading offline.
        """
        if signal == SignalType.NONE:
            return
        if signal == SignalType.CLOSE:
            self._close_position()
            return

        if signal == SignalType.BUY and self.is_short:
            self._log.info("Reversing: closing short, entering long")
            self._close_position()
        elif signal == SignalType.SELL and self.is_long:
            self._log.info("Reversing: closing long, entering short")
            self._close_position()

        atr_raw = self._atr.value
        if is_atr_unsafe(atr_raw):
            logger.warning(
                "MA crossover skipping signal: ATR=%s is non-positive or non-finite",
                atr_raw,
            )
            return
        atr_value = Decimal(str(atr_raw))
        self._submit_bracket_for_entry(signal, atr_value)

    # --- Story 13.11: scale-out lifecycle wiring -------------------------
    #
    # The four methods below are copy-equivalent to the Story 13.5
    # (Supertrend) and Story 13.10 (Donchian) wirings. Extraction of
    # this boilerplate into a shared host-side helper is queued now
    # that the rule of three has been satisfied — see Epic 13 memory.

    def on_event(self, event: Event) -> None:
        """Extend BaseStrategy.on_event to feed the scale-out mixin."""
        super().on_event(event)
        self._dispatch_scale_out_event(event)

    def _dispatch_scale_out_event(self, event: Event) -> None:
        """Forward position lifecycle events into the scale-out mixin."""
        if not self.config.scale_out_enabled:
            return
        if isinstance(event, PositionOpened):
            self._try_init_scale_state()
        elif isinstance(event, PositionClosed):
            self._clear_scale_state()

    def _try_init_scale_state(self) -> None:
        """Best-effort scale-out init; retried by the bar evaluator."""
        if self._scale_state is not None:
            return
        position = self._position
        if position is None:
            return
        sl_order = self._find_active_sl_order()
        if sl_order is None:
            return
        side = (
            OrderSide.BUY
            if position.side == PositionSide.LONG
            else OrderSide.SELL
        )
        self._init_scale_state(
            side=side,
            entry_price=Decimal(str(position.avg_px_open)),
            sl_price=Decimal(str(sl_order.trigger_price.as_double())),
            qty=Decimal(str(position.quantity.as_double())),
        )

    def on_bar(self, bar: Bar) -> None:
        """Extend BaseStrategy.on_bar to drive the scale-out evaluator."""
        super().on_bar(bar)
        self._evaluate_scale_out_for_bar(bar)

    def _evaluate_scale_out_for_bar(self, bar: Bar) -> None:
        """Drive the scale-out state machine off the latest bar close."""
        if not self.config.scale_out_enabled or self.is_flat:
            return
        if self._scale_state is None:
            self._try_init_scale_state()
            if self._scale_state is None:
                return
        self.evaluate_scale_out(Decimal(str(bar.close.as_double())))
