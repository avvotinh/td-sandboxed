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
from src.strategies.mixins.risk_sized_mixin import RiskSizedMixin
from src.strategies.registry import register_strategy
from src.strategies.risk_based_position_sizer import (
    RiskBasedPositionSizer,
    RiskBasedSizerConfig,
)

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


@register_strategy("mean_reversion", regimes=[RegimeState.RANGING])
class MeanReversionStrategy(
    BaseStrategy, ATRStopMixin, RiskSizedMixin, BracketStrategyMixin
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

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self._bb)
        self.register_indicator_for_bars(self.config.bar_type, self._rsi)
        self.register_indicator_for_bars(self.config.bar_type, self._atr)

    def on_reset(self) -> None:
        super().on_reset()
        self._bb.reset()
        self._rsi.reset()
        self._atr.reset()

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

        # Exit first — middle-band mean-reversion target wins the
        # same-bar race against a fresh opposite-side entry.
        if self.is_long and close >= middle:
            return SignalType.CLOSE
        if self.is_short and close <= middle:
            return SignalType.CLOSE

        if not self.is_flat:
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
