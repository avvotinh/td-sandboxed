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

from nautilus_trader.model.data import Bar

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
    from nautilus_trader.indicators.volatility import AverageTrueRange

    from src.backtesting.recorder.indicator_recorder import IndicatorRecorder

logger = logging.getLogger(__name__)


class SupertrendConfig(BracketStrategyConfig, frozen=True, kw_only=True):
    """Configuration for :class:`SupertrendStrategy`."""

    period: int = 10
    multiplier: float = 3.0

    def __post_init__(self) -> None:
        """Validate config — delegate ATR + Phase 1 invariants to parent.

        ``super().__post_init__()`` enforces the full
        :class:`BracketStrategyConfig` invariant set (R:R > 1,
        safety_tp_atr_mult > 0, scale-out / trail cross-field guards).
        The Supertrend-specific checks below cover the indicator
        params that the parent doesn't know about.
        """
        super().__post_init__()
        if self.period <= 0:
            raise ValueError(f"period must be positive, got {self.period}")
        if self.multiplier <= 0:
            raise ValueError(f"multiplier must be positive, got {self.multiplier}")


@register_strategy(
    "supertrend",
    regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN],
)
class SupertrendStrategy(
    BracketScaleOutMixin,
    EntryFilterMixin,
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
        # Phase 1 trail indicator — separate Supertrend instance with
        # the trailing_atr_period / trailing_atr_multiplier params so
        # the trail line can be tuned independently of the signal line.
        # None when trailing is off so we skip the indicator overhead.
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
        self._prev_trend: int | None = None

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self._supertrend)
        self.register_indicator_for_bars(self.config.bar_type, self._atr)
        if self._supertrend_trail is not None:
            self.register_indicator_for_bars(
                self.config.bar_type, self._supertrend_trail
            )
        self._register_entry_filter_indicators()
        self._log.info(
            f"Supertrend started period={self.config.period} mult={self.config.multiplier}"
        )

    def on_reset(self) -> None:
        self._supertrend.reset()
        self._atr.reset()
        if self._supertrend_trail is not None:
            self._supertrend_trail.reset()
        self._reset_entry_filters()
        self._prev_trend = None

    def generate_signal(self, bar: Bar) -> SignalType:
        # Session filter first (Track 5.1): out-of-session bars flatten
        # or no-op before any signal state is touched — at session open
        # the flip comparison runs against the last in-session trend, so
        # an overnight flip enters on the first eligible bar.
        gated = self._session_gate(bar)
        if gated is not None:
            return gated

        if not self._supertrend.initialized or not self._atr.initialized:
            return SignalType.NONE

        current_trend = self._supertrend.trend
        prev = self._prev_trend
        self._prev_trend = current_trend

        if prev is None:
            return SignalType.NONE  # First initialised bar — seed only.

        if current_trend == prev:
            return SignalType.NONE

        # Trend flipped — admit only when the ADX gate sees trend
        # strength. _prev_trend has already advanced, so a blocked flip
        # does not re-fire when ADX recovers bars later.
        if self._adx_gate_blocks():
            return SignalType.NONE

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

    def _export_indicators(
        self, bar: Bar, recorder: IndicatorRecorder
    ) -> None:
        """Record the Supertrend line (split up/down) + optional trail."""
        from src.backtesting.recorder.indicator_recorder import ns_to_utc

        st = self._supertrend
        if st.initialized and st.value is not None:
            if not recorder.is_registered("supertrend_up"):
                recorder.register(
                    "supertrend_up",
                    title="Supertrend (up)",
                    pane="overlay",
                    color="#26a69a",
                )
                recorder.register(
                    "supertrend_down",
                    title="Supertrend (down)",
                    pane="overlay",
                    color="#ef5350",
                )
            ts = ns_to_utc(bar.ts_init)
            recorder.record(
                "supertrend_up", ts, st.value if st.trend == 1 else None
            )
            recorder.record(
                "supertrend_down", ts, st.value if st.trend == -1 else None
            )
        self._export_trail_indicator(bar, recorder)

    # Story 13.5: scale-out lifecycle wiring lived here per-strategy
    # until Story 13.11 hit the rule of three. The five wiring methods
    # (``on_event`` / ``_dispatch_scale_out_event`` / ``_try_init_scale_state``
    # / ``on_bar`` / ``_evaluate_scale_out_for_bar``) now live on
    # ``BracketScaleOutMixin`` — see ``bracket_scale_out.py``. The mixin
    # is prepended in the MRO above so the methods are reachable
    # unchanged; override here only if a strategy needs custom dispatch.
