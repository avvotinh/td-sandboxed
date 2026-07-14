"""Consolidated mean-reversion strategy — Bollinger × RSI confluence.

Track 2.1 of ``docs/strategy-redesign-plan-2026-07-02.md``: replaces the
archived ``rsi_mean_reversion`` / ``bollinger_mean_reversion`` pair
(which were structurally identical apart from ``generate_signal`` — the
``MeanReversionMixin`` debt from ``strategy-review-2026-05-02.md`` is
paid off by the merge itself).

Signal:
    ENTRY LONG   close < lower Bollinger band AND RSI ≤ oversold
    ENTRY SHORT  close > upper Bollinger band AND RSI ≥ overbought
    EXIT         close reverts to the middle band (SMA), or SL/TP

Requiring BOTH conditions filters the two failure modes the solo
strategies showed in Phase 12.A: band touches during trends (Bollinger
MR's losing entries — RSI is not extreme there) and RSI extremes far
from a band (RSI MR firing inside a drifting channel).

Nautilus RSI returns a **0–1 scale** (not 0–100) — config thresholds
are specified on the same scale.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.data import Bar

from src.indicators import RSI, Bollinger
from src.orders.signal import SignalType
from src.regime.states import RegimeState
from src.strategies.base_strategy import BaseStrategy
from src.strategies.bracket_strategy import (
    BracketStrategyConfig,
    BracketStrategyMixin,
    is_atr_unsafe,
)
from src.strategies.mixins.atr_stop_mixin import ATRStopMixin
from src.strategies.mixins.entry_filter_mixin import EntryFilterMixin
from src.strategies.mixins.risk_sized_mixin import RiskSizedMixin
from src.strategies.registry import register_strategy
from src.strategies.risk_based_position_sizer import (
    RiskBasedPositionSizer,
    RiskBasedSizerConfig,
)

if TYPE_CHECKING:
    from src.backtesting.recorder.indicator_recorder import IndicatorRecorder

logger = logging.getLogger(__name__)


class MeanReversionConfig(BracketStrategyConfig, frozen=True, kw_only=True):
    bb_period: int = 20
    num_std: float = 2.0
    rsi_period: int = 14
    oversold: float = 0.3
    overbought: float = 0.7
    # MR-specific defaults (same as the archived pair, so Phase 12.A
    # cross-strategy comparisons carry over cleanly).
    sl_atr_mult: Decimal = Decimal("1.0")
    tp_atr_mult: Decimal = Decimal("2.0")
    # Track 5.1 entry semantics:
    #   "pierce"  — legacy: enter on the bar whose close sits outside
    #               the band with RSI extreme (catches falling knives).
    #   "recross" — enter on the snap-back bar: previous close outside
    #               the band, current close back inside, RSI still in
    #               the extreme zone (entry-exit-trailing analysis §7.3).
    entry_mode: str = "pierce"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.bb_period <= 0:
            raise ValueError(f"bb_period must be positive, got {self.bb_period}")
        if self.rsi_period <= 0:
            raise ValueError(f"rsi_period must be positive, got {self.rsi_period}")
        if self.num_std <= 0:
            raise ValueError(f"num_std must be positive, got {self.num_std}")
        # Structural guardrail, not a tunable: bands beyond 5σ are never
        # touched, silently yielding zero-trade backtests (see the same
        # guard rationale in the archived bollinger_mean_reversion).
        if self.num_std > 5.0:
            raise ValueError(
                "num_std must be <= 5.0 (typical range 1.5–3.0); "
                f"got {self.num_std}"
            )
        if not 0 <= self.oversold < self.overbought <= 1:
            raise ValueError(
                "thresholds must satisfy 0 ≤ oversold < overbought ≤ 1; "
                f"got oversold={self.oversold} overbought={self.overbought}"
            )
        if self.entry_mode not in ("pierce", "recross"):
            raise ValueError(
                f"entry_mode must be 'pierce' or 'recross', got {self.entry_mode!r}"
            )


@register_strategy("mean_reversion", regimes=[RegimeState.RANGING])
class MeanReversionStrategy(
    EntryFilterMixin, BaseStrategy, ATRStopMixin, RiskSizedMixin, BracketStrategyMixin
):
    """Mean-reversion — band pierce confirmed by an RSI extreme."""

    def __init__(self, config: MeanReversionConfig) -> None:
        super().__init__(config)
        self._bb = Bollinger(period=config.bb_period, k=config.num_std)
        self._rsi = RSI(config.rsi_period)
        self._atr = AverageTrueRange(config.atr_period)
        self.set_position_sizer(
            RiskBasedPositionSizer(
                RiskBasedSizerConfig(risk_percent=config.risk_percent)
            )
        )
        self._init_entry_filters()
        # Recross entry state: previous bar's close and band values.
        self._prev_close: float | None = None
        self._prev_band_lower: float | None = None
        self._prev_band_upper: float | None = None

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self._bb)
        self.register_indicator_for_bars(self.config.bar_type, self._rsi)
        self.register_indicator_for_bars(self.config.bar_type, self._atr)
        self._register_entry_filter_indicators()

    def on_reset(self) -> None:
        super().on_reset()
        self._bb.reset()
        self._rsi.reset()
        self._atr.reset()
        self._reset_entry_filters()
        self._prev_close = None
        self._prev_band_lower = None
        self._prev_band_upper = None

    def generate_signal(self, bar: Bar) -> SignalType:
        if not (
            self._bb.initialized
            and self._rsi.initialized
            and self._atr.initialized
        ):
            return SignalType.NONE

        close = bar.close.as_double()
        upper = self._bb.upper
        middle = self._bb.middle
        lower = self._bb.lower
        rsi = self._rsi.value

        # Squeeze guard: a collapsed band (upper <= lower) makes both the
        # entry condition and the middle-band exit semantically undefined.
        # Warn + NONE so backtests surface the broken state instead of
        # idling silently (same rationale as the archived Bollinger MR).
        if upper <= lower:
            logger.warning(
                "Bollinger band collapsed (upper=%.4f lower=%.4f); skipping bar",
                upper,
                lower,
            )
            return SignalType.NONE

        # Advance recross state BEFORE any exit/entry/session return
        # path so the previous-bar reference is never stale (bands are
        # valid here — the squeeze guard above already returned). A
        # pierce that lands on a session-gated bar still arms the
        # snap-back reference for the first in-session bar.
        prev_close = self._prev_close
        prev_lower = self._prev_band_lower
        prev_upper = self._prev_band_upper
        self._prev_close = close
        self._prev_band_lower = lower
        self._prev_band_upper = upper

        # Session filter (Track 5.1), after state upkeep. With the
        # MR-shaped "block_entry" policy the gate passes through while a
        # position is open, so the middle-band exit below keeps managing
        # open trades out-of-session; fresh entries are blocked.
        gated = self._session_gate(bar)
        if gated is not None:
            return gated

        # Exit first — middle-band mean-reversion target wins the
        # same-bar race against a fresh opposite-side entry.
        if self.is_long and close >= middle:
            return SignalType.CLOSE
        if self.is_short and close <= middle:
            return SignalType.CLOSE

        if not self.is_flat:
            return SignalType.NONE

        if self.config.entry_mode == "recross":
            # Snap-back confirmation: previous close pierced the band,
            # this close is back inside, RSI still extreme — enter on
            # the reversal evidence, not the falling knife.
            if prev_close is None:
                return SignalType.NONE
            if (
                prev_close < prev_lower
                and close >= lower
                and rsi <= self.config.oversold
            ):
                return SignalType.BUY
            if (
                prev_close > prev_upper
                and close <= upper
                and rsi >= self.config.overbought
            ):
                return SignalType.SELL
            return SignalType.NONE

        # Confluence entry: band pierce AND RSI extreme. The RSI side is
        # a static zone check (inclusive thresholds) — deliberately NOT
        # the archived RSI MR's momentum-cross requirement, which would
        # rarely coincide with the band pierce on the same bar.
        if close < lower and rsi <= self.config.oversold:
            return SignalType.BUY
        if close > upper and rsi >= self.config.overbought:
            return SignalType.SELL
        return SignalType.NONE

    def _execute_signal(self, signal: SignalType) -> None:
        if signal == SignalType.CLOSE:
            self._close_position()
            return
        atr_raw = self._atr.value
        if is_atr_unsafe(atr_raw):
            logger.warning(
                "Mean reversion skipping entry: ATR=%s is non-positive or non-finite",
                atr_raw,
            )
            return
        self._submit_bracket_for_entry(signal, Decimal(str(atr_raw)))

    def _export_indicators(
        self, bar: Bar, recorder: IndicatorRecorder
    ) -> None:
        """Record Bollinger bands (overlay) + RSI (own pane, with levels)."""
        from src.backtesting.recorder.indicator_recorder import ns_to_utc

        ts = ns_to_utc(bar.ts_init)
        bb = self._bb
        if bb.initialized:
            if not recorder.is_registered("bb_upper"):
                recorder.register(
                    "bb_upper", title="BB upper", pane="overlay", color="#2962ff"
                )
                recorder.register(
                    "bb_middle", title="BB middle", pane="overlay", color="#9e9e9e"
                )
                recorder.register(
                    "bb_lower", title="BB lower", pane="overlay", color="#2962ff"
                )
            recorder.record("bb_upper", ts, bb.upper)
            recorder.record("bb_middle", ts, bb.middle)
            recorder.record("bb_lower", ts, bb.lower)
        rsi = self._rsi
        if rsi.initialized:
            if not recorder.is_registered("rsi"):
                recorder.register(
                    "rsi",
                    title=f"RSI ({self.config.rsi_period})",
                    pane="rsi",
                    color="#ab47bc",
                    levels=(self.config.oversold, self.config.overbought),
                )
            recorder.record("rsi", ts, rsi.value)
