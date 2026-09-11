"""Mean-reversion band entry — ported from ``MeanReversionStrategy``.

Bollinger band pierce confirmed by an RSI extreme (Track 2.1 confluence).
Requiring both filters the two failure modes the solo strategies showed
in Phase 12.A: band touches during trends, where RSI is not extreme, and
RSI extremes far from a band, inside a drifting channel.

Two entry modes:

* ``pierce``  — enter on the bar whose close sits outside the band with
  RSI extreme. Catches falling knives.
* ``recross`` — enter on the snap-back bar: previous close outside the
  band, this close back inside, RSI still extreme.

Nautilus RSI is on a **0-1 scale**, so the thresholds are too.

One asymmetry worth knowing before tuning this: Nautilus ``BollingerBands``
is fed ``(high, low, close)`` and computes on the typical price
``(H+L+C)/3``, while the pierce test and the middle-band exit both compare
``bar.close``. So the bands are centred on a different series than the one
being tested against them, and on XAUUSD M5 — where H-L is a few dollars —
that makes which side pierces first systematically asymmetric. Pre-existing
and parity-preserved; changing it is a deliberate, re-baselined decision,
not a cleanup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.kernel.entries.base import EntryModel
from src.kernel.entries.intent import EntryIntent, EntrySide
from src.kernel.indicators import RSI, Bollinger

if TYPE_CHECKING:
    from nautilus_trader.indicators.base.indicator import Indicator
    from nautilus_trader.model.data import Bar

    from src.lab.recorder.indicator_recorder import IndicatorRecorder

logger = logging.getLogger(__name__)

ENTRY_MODES: tuple[str, ...] = ("pierce", "recross")


@dataclass(frozen=True, slots=True)
class _BandFacts:
    """One bar's close and bands, plus the prior bar's, for a re-cross."""

    close: float
    upper: float
    lower: float
    rsi: float
    prev_close: float | None
    prev_upper: float | None
    prev_lower: float | None


class MeanReversionBandEntry(EntryModel):
    """Band pierce (or snap-back) confirmed by an RSI extreme."""

    def __init__(
        self,
        *,
        bb_period: int,
        num_std: float,
        rsi_period: int,
        oversold: float,
        overbought: float,
        entry_mode: str = "pierce",
    ) -> None:
        if entry_mode not in ENTRY_MODES:
            raise ValueError(
                f"entry_mode must be one of {ENTRY_MODES}, got {entry_mode!r}"
            )
        self._bb = Bollinger(period=bb_period, k=num_std)
        self._rsi = RSI(rsi_period)
        self._rsi_period = rsi_period
        self._oversold = oversold
        self._overbought = overbought
        self._entry_mode = entry_mode
        self._prev_close: float | None = None
        self._prev_band_lower: float | None = None
        self._prev_band_upper: float | None = None
        self._facts: _BandFacts | None = None

    @property
    def ready(self) -> bool:
        return self._bb.initialized and self._rsi.initialized

    @property
    def middle(self) -> float:
        """The SMA the bands straddle — the mean-reversion exit target.

        Read by the strategy's middle-band exit today, and by
        ``ExitPolicy`` once roadmap task 3.5 lands.
        """
        return self._bb.middle

    def indicators(self) -> tuple[Indicator, ...]:
        return (self._bb, self._rsi)

    def update(self, bar: Bar) -> bool:
        close = bar.close.as_double()
        upper = self._bb.upper
        lower = self._bb.lower

        # Squeeze guard: a collapsed band (upper <= lower) makes both the
        # entry condition and the middle-band exit undefined. Warn + skip
        # so a backtest surfaces the broken state instead of idling
        # silently. Exact equality is the right boundary — when stdev==0
        # the C-extension produces upper == middle == lower in IEEE-754
        # with no ULP drift, so an epsilon would only obscure it.
        if upper <= lower:
            logger.warning(
                "Bollinger band collapsed (upper=%.4f lower=%.4f); skipping bar",
                upper,
                lower,
            )
            self._facts = None
            return False

        self._facts = _BandFacts(
            close=close,
            upper=upper,
            lower=lower,
            rsi=self._rsi.value,
            prev_close=self._prev_close,
            prev_upper=self._prev_band_upper,
            prev_lower=self._prev_band_lower,
        )
        # Advance the re-cross reference on every usable bar, so a pierce
        # that lands on a gated bar still arms the snap-back comparison
        # for the first bar that survives the gate.
        self._prev_close = close
        self._prev_band_lower = lower
        self._prev_band_upper = upper
        return True

    def evaluate(self) -> EntryIntent | None:
        facts = self._facts
        if facts is None:
            return None
        if self._entry_mode == "recross":
            return self._evaluate_recross(facts)
        return self._evaluate_pierce(facts)

    def _evaluate_pierce(self, facts: _BandFacts) -> EntryIntent | None:
        """Band pierce AND RSI extreme on the same bar.

        The RSI side is a static zone check with inclusive thresholds —
        deliberately NOT the archived RSI MR's momentum-cross, which
        would rarely coincide with the band pierce on one bar.
        """
        if facts.close < facts.lower and facts.rsi <= self._oversold:
            return EntryIntent.market(EntrySide.LONG, "bb_lower_pierce_rsi_oversold")
        if facts.close > facts.upper and facts.rsi >= self._overbought:
            return EntryIntent.market(EntrySide.SHORT, "bb_upper_pierce_rsi_overbought")
        return None

    def _evaluate_recross(self, facts: _BandFacts) -> EntryIntent | None:
        """Snap-back confirmation: enter on the reversal, not the knife."""
        if facts.prev_close is None:
            return None
        if (
            facts.prev_close < facts.prev_lower
            and facts.close >= facts.lower
            and facts.rsi <= self._oversold
        ):
            return EntryIntent.market(EntrySide.LONG, "bb_lower_recross_rsi_oversold")
        if (
            facts.prev_close > facts.prev_upper
            and facts.close <= facts.upper
            and facts.rsi >= self._overbought
        ):
            return EntryIntent.market(EntrySide.SHORT, "bb_upper_recross_rsi_overbought")
        return None

    def reset(self) -> None:
        self._bb.reset()
        self._rsi.reset()
        self._prev_close = None
        self._prev_band_lower = None
        self._prev_band_upper = None
        self._facts = None

    def export_indicators(self, bar: Bar, recorder: IndicatorRecorder) -> None:
        """Record Bollinger bands (overlay) + RSI (own pane, with levels)."""
        # Local import: kernel must stay importable without lab (see
        # EntryModel.export_indicators).
        from src.lab.recorder.indicator_recorder import ns_to_utc

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
                    title=f"RSI ({self._rsi_period})",
                    pane="rsi",
                    color="#ab47bc",
                    levels=(self._oversold, self._overbought),
                )
            recorder.record("rsi", ts, rsi.value)
