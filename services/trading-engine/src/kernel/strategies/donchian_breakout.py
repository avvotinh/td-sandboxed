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
from typing import TYPE_CHECKING

from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.data import Bar

from src.kernel.indicators import Donchian
from src.kernel.indicators.supertrend import Supertrend
from src.orders.signal import SignalType
from src.kernel.strategies.base_strategy import BaseStrategy
from src.kernel.strategies.bracket_scale_out import BracketScaleOutMixin
from src.kernel.strategies.bracket_strategy import (
    BracketStrategyConfig,
    BracketStrategyMixin,
    is_atr_unsafe,
)
from src.kernel.strategies.mixins.atr_stop_mixin import ATRStopMixin
from src.kernel.strategies.mixins.entry_filter_mixin import EntryFilterMixin
from src.kernel.strategies.mixins.risk_sized_mixin import RiskSizedMixin
from src.kernel.regime.states import RegimeState
from src.kernel.strategies.registry import register_strategy
from src.kernel.strategies.risk_based_position_sizer import (
    RiskBasedPositionSizer,
    RiskBasedSizerConfig,
)

if TYPE_CHECKING:
    from src.lab.recorder.indicator_recorder import IndicatorRecorder

logger = logging.getLogger(__name__)


class DonchianBreakoutConfig(BracketStrategyConfig, frozen=True, kw_only=True):
    channel_period: int = 20
    # Donchian defaults override the generic bracket config defaults
    sl_atr_mult: Decimal = Decimal("2.0")
    tp_atr_mult: Decimal = Decimal("4.0")
    # Track 5.1 crossing semantics: enter only on the FIRST bar of a
    # breakout episode (edge-triggered) instead of every bar whose close
    # sits outside the prior channel (level-triggered). Kills the
    # re-entry churn diagnosed in entry-exit-trailing analysis §1.2 —
    # after an SL/TP exit mid-episode there is no re-entry until the
    # close returns inside the channel and breaks out again.
    entry_on_cross_only: bool = False

    def __post_init__(self) -> None:
        """Validate config — delegate ATR + Phase 1 invariants to parent.

        ``super().__post_init__()`` enforces the full
        :class:`BracketStrategyConfig` invariant set (positive ATR /
        SL / TP, R:R > 1, safety_tp_atr_mult > 0, scale-out / trail
        cross-field guards). The Donchian-specific check below covers
        the channel period that the parent doesn't know about.
        """
        super().__post_init__()
        if self.channel_period <= 0:
            raise ValueError(f"channel_period must be positive, got {self.channel_period}")


@register_strategy(
    "donchian_breakout",
    regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN],
)
class DonchianBreakoutStrategy(
    BracketScaleOutMixin,
    EntryFilterMixin,
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
        self._init_entry_filters()
        self._prev_upper: float | None = None
        self._prev_lower: float | None = None
        # Crossing-semantics episode state: was the previous close
        # already outside the (then-prior) channel on each side?
        self._prev_breakout_up: bool = False
        self._prev_breakout_down: bool = False

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self._donchian)
        self.register_indicator_for_bars(self.config.bar_type, self._atr)
        if self._supertrend_trail is not None:
            self.register_indicator_for_bars(
                self.config.bar_type, self._supertrend_trail
            )
        self._register_entry_filter_indicators()

    def on_reset(self) -> None:
        self._donchian.reset()
        self._atr.reset()
        if self._supertrend_trail is not None:
            self._supertrend_trail.reset()
        self._reset_entry_filters()
        self._prev_upper = None
        self._prev_lower = None
        self._prev_breakout_up = False
        self._prev_breakout_down = False

    def generate_signal(self, bar: Bar) -> SignalType:
        if not self._donchian.initialized or not self._atr.initialized:
            return SignalType.NONE

        close = bar.close.as_double()
        prev_upper = self._prev_upper
        prev_lower = self._prev_lower

        # Capture current band as the "prior" reference for the next bar
        # BEFORE any return path — otherwise the seed bar never stores it.
        # Rolling references advance on EVERY bar, including session-gated
        # ones, so the first in-session bar after a gap compares against
        # the true prior bar rather than a frozen pre-gap snapshot.
        self._prev_upper = self._donchian.upper
        self._prev_lower = self._donchian.lower

        if prev_upper is None or prev_lower is None:
            return SignalType.NONE

        breakout_up = close > prev_upper
        breakout_down = close < prev_lower

        # Advance episode state before any gating so a suppressed,
        # session-gated, or ADX-blocked breakout bar still arms/disarms
        # the edge trigger — an episode that begins overnight must not
        # read as "first breakout bar" at session open.
        was_up = self._prev_breakout_up
        was_down = self._prev_breakout_down
        self._prev_breakout_up = breakout_up
        self._prev_breakout_down = breakout_down

        # Session filter (Track 5.1): after state upkeep, before entries.
        gated = self._session_gate(bar)
        if gated is not None:
            return gated

        if self.config.entry_on_cross_only:
            breakout_up = breakout_up and not was_up
            breakout_down = breakout_down and not was_down

        if not (breakout_up or breakout_down):
            return SignalType.NONE

        if self._adx_gate_blocks():
            return SignalType.NONE

        return SignalType.BUY if breakout_up else SignalType.SELL

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

    def _export_indicators(
        self, bar: Bar, recorder: IndicatorRecorder
    ) -> None:
        """Record the Donchian channel bands + optional trail line."""
        from src.lab.recorder.indicator_recorder import ns_to_utc

        dc = self._donchian
        if dc.initialized:
            if not recorder.is_registered("donchian_upper"):
                recorder.register(
                    "donchian_upper",
                    title="Donchian upper",
                    pane="overlay",
                    color="#2962ff",
                )
                recorder.register(
                    "donchian_lower",
                    title="Donchian lower",
                    pane="overlay",
                    color="#f57c00",
                )
                recorder.register(
                    "donchian_middle",
                    title="Donchian middle",
                    pane="overlay",
                    color="#9e9e9e",
                )
            ts = ns_to_utc(bar.ts_init)
            recorder.record("donchian_upper", ts, dc.upper)
            recorder.record("donchian_lower", ts, dc.lower)
            # Nautilus DonchianChannel computes a middle band; guard
            # with getattr in case a future indicator swap drops it.
            recorder.record("donchian_middle", ts, getattr(dc, "middle", None))
        self._export_trail_indicator(bar, recorder)

    # Story 13.10 originally inlined the scale-out wiring here per the
    # 13.5 Supertrend template. After Story 13.11 made Donchian the
    # third user, the five wiring methods were lifted into
    # ``BracketScaleOutMixin`` (see ``bracket_scale_out.py``). The
    # mixin is prepended in the MRO above so the inherited methods
    # are reachable unchanged.
