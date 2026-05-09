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

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from nautilus_trader.core.message import Event
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

if TYPE_CHECKING:
    from nautilus_trader.indicators.volatility import AverageTrueRange

logger = logging.getLogger(__name__)


class SupertrendConfig(BracketStrategyConfig, frozen=True, kw_only=True):
    """Configuration for :class:`SupertrendStrategy`."""

    period: int = 10
    multiplier: float = 3.0

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


@register_strategy(
    "supertrend",
    regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN],
)
class SupertrendStrategy(
    BracketScaleOutMixin,
    BaseStrategy,
    ATRStopMixin,
    RiskSizedMixin,
    BracketStrategyMixin,
):
    """Trend-following strategy driven by the Supertrend indicator.

    Phase 1 scale-out + trail tactics (Epic 13) compose via
    ``BracketScaleOutMixin``. Default-off — strategies built from a
    config with ``scale_out_enabled=False`` keep the legacy single-fill
    + hard-TP behaviour. When enabled, ``_dispatch_scale_out_event``
    forwards Nautilus position-lifecycle events into the mixin's state
    machine, and ``_evaluate_scale_out_for_bar`` drives the per-bar
    transitions off the latest close.
    """

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

        # ATR-safety guard: a flat-bar (H=L=C) drives ATR to zero,
        # which ATRStopMixin._validated_offset rejects with ValueError —
        # propagating that exception through the bar callback halts the
        # engine. Skip the signal instead so a single noisy bar cannot
        # take trading offline. The shared predicate also covers None
        # (warmup), NaN/inf (synthetic ticks), and negative (rollover
        # gaps) — all single-bar transient states from which the
        # indicator typically recovers.
        atr_raw = self._atr.value
        if is_atr_unsafe(atr_raw):
            logger.warning(
                "Supertrend skipping signal: ATR=%s is non-positive or non-finite",
                atr_raw,
            )
            return

        atr_value = Decimal(str(atr_raw))
        self._submit_bracket_for_entry(signal, atr_value)

    # --- Story 13.5: scale-out lifecycle wiring ---------------------------

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

        Separated from ``on_event`` so unit tests can drive the dispatch
        logic with stubbed ``_position`` / ``_find_active_sl_order``
        without booting a Nautilus cache (super().on_event reads
        ``self.cache.position(...)`` which is read-only on Actor).
        """
        if not self.config.scale_out_enabled:
            return
        # Nautilus Logger.warning(message, color) takes a single
        # str message — no %-style lazy formatting like stdlib. So
        # f-strings are unavoidable on this surface; keep them short.
        if isinstance(event, PositionOpened):
            position = self._position
            if position is None:
                # Cache miss / race: super().on_event could not resolve
                # the position. Skip rather than pass None into the
                # mixin — next bar the position should be visible.
                self._log.warning(
                    "PositionOpened received but _position not set; "
                    "skipping scale-out init"
                )
                return
            sl_order = self._find_active_sl_order()
            if sl_order is None:
                # SL leg may register slightly after fill on some paths;
                # without it we can't compute risk_per_unit, so skip
                # cleanly rather than init with a bogus SL.
                self._log.warning(
                    "No active SL order at PositionOpened; "
                    "scale-out init skipped (race?)"
                )
                return
            side = (
                OrderSide.BUY
                if position.side == PositionSide.LONG
                else OrderSide.SELL
            )
            # .as_double() for Nautilus Price / Quantity types matches
            # the project pattern in bracket_strategy.py:154,207. Going
            # through .as_double() makes the float-rounding explicit
            # rather than relying on Price.__str__ stability across
            # Nautilus versions.
            self._init_scale_state(
                side=side,
                entry_price=Decimal(str(position.avg_px_open)),
                sl_price=Decimal(str(sl_order.trigger_price.as_double())),
                qty=Decimal(str(position.quantity.as_double())),
            )
        elif isinstance(event, PositionClosed):
            self._clear_scale_state()

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

        No-op when scale_out is disabled or the strategy is flat — the
        mixin only has work to do while a position is open.
        """
        if not self.config.scale_out_enabled or self.is_flat:
            return
        self.evaluate_scale_out(Decimal(str(bar.close.as_double())))
