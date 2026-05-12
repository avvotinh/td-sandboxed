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

import logging
from decimal import Decimal

from nautilus_trader.core.message import Event
from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide, PositionSide
from nautilus_trader.model.events import PositionClosed, PositionOpened

from src.indicators import Donchian
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
    BracketScaleOutMixin,
    BaseStrategy,
    ATRStopMixin,
    RiskSizedMixin,
    BracketStrategyMixin,
):
    """Classical Turtle-style channel breakout strategy.

    Phase 1 scale-out + trail tactics (Epic 13) compose via
    ``BracketScaleOutMixin`` — same wiring as ``SupertrendStrategy``
    (Story 13.5). Default-OFF: when ``scale_out_enabled=False`` the
    strategy keeps the legacy single-fill + hard-TP behaviour. When
    enabled, ``_dispatch_scale_out_event`` forwards Nautilus position
    lifecycle events into the mixin's state machine and
    ``_evaluate_scale_out_for_bar`` drives per-bar transitions off the
    latest close.
    """

    def __init__(self, config: DonchianBreakoutConfig) -> None:
        super().__init__(config)
        self._donchian = Donchian(config.channel_period)
        self._atr = AverageTrueRange(config.atr_period)
        # Phase 1 trail indicator — separate Supertrend instance keyed on
        # trailing_atr_period / trailing_atr_multiplier so the trail line
        # can be tuned independently of the Donchian channel. ``None``
        # when trailing is off so we skip the indicator overhead.
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
        self._prev_upper: float | None = None
        self._prev_lower: float | None = None

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self._donchian)
        self.register_indicator_for_bars(self.config.bar_type, self._atr)
        if self._supertrend_trail is not None:
            self.register_indicator_for_bars(
                self.config.bar_type, self._supertrend_trail
            )

    def on_reset(self) -> None:
        self._donchian.reset()
        self._atr.reset()
        if self._supertrend_trail is not None:
            self._supertrend_trail.reset()
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
        # Mirror the supertrend / bollinger / rsi guard: a flat-bar
        # (H=L=C) collapses ATR to zero, which ATRStopMixin rejects with
        # ValueError — letting that propagate through the bar callback
        # would halt the engine. Skip the bar instead.
        atr_raw = self._atr.value
        if is_atr_unsafe(atr_raw):
            logger.warning(
                "Donchian breakout skipping signal: ATR=%s is non-positive or non-finite",
                atr_raw,
            )
            return
        atr_value = Decimal(str(atr_raw))
        self._submit_bracket_for_entry(signal, atr_value)

    # --- Story 13.10: scale-out lifecycle wiring --------------------------
    #
    # The four methods below are intentionally copy-equivalent to the
    # Story 13.5 wiring in ``supertrend.py``. Extracting them into a
    # shared host-side helper is queued for after Story 13.11 lands a
    # third user (MA crossover) — the rule of three.

    def on_event(self, event: Event) -> None:
        """Extend BaseStrategy.on_event to feed the scale-out mixin.

        ``super().on_event`` updates ``self._position`` from the cache;
        we then dispatch the event into the scale-out state machine via
        the testable seam ``_dispatch_scale_out_event``.
        """
        super().on_event(event)
        self._dispatch_scale_out_event(event)

    def _dispatch_scale_out_event(self, event: Event) -> None:
        """Forward position lifecycle events into the scale-out mixin.

        See ``supertrend.py`` for the race note on PositionOpened firing
        before the bracket's SL leg lands in cache; ``_try_init_scale_state``
        no-ops cleanly and the bar evaluator retries.
        """
        if not self.config.scale_out_enabled:
            return
        if isinstance(event, PositionOpened):
            self._try_init_scale_state()
        elif isinstance(event, PositionClosed):
            self._clear_scale_state()

    def _try_init_scale_state(self) -> None:
        """Best-effort scale-out init from the live position + SL leg.

        Skips silently when ``_scale_state`` is already set, ``_position``
        is missing, or the SL leg is not yet in cache (PENDING after a
        fresh PositionOpened). Retried each bar by
        ``_evaluate_scale_out_for_bar`` until the bracket's SL is visible.
        """
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
        """Extend BaseStrategy.on_bar to drive the scale-out evaluator.

        ``super().on_bar`` runs the existing signal logic (generate +
        execute). The scale-out evaluator runs AFTER signals so a flip
        signal that closes the position clears state via the resulting
        PositionClosed event before the next bar's evaluator runs.
        """
        super().on_bar(bar)
        self._evaluate_scale_out_for_bar(bar)

    def _evaluate_scale_out_for_bar(self, bar: Bar) -> None:
        """Drive the scale-out state machine off the latest bar close.

        No-op when scale-out is disabled or the strategy is flat. When
        in position but ``_scale_state`` is None, retry init — covers
        the PositionOpened-vs-SL-leg race.
        """
        if not self.config.scale_out_enabled or self.is_flat:
            return
        if self._scale_state is None:
            self._try_init_scale_state()
            if self._scale_state is None:
                return
        self.evaluate_scale_out(Decimal(str(bar.close.as_double())))
