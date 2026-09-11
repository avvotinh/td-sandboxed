"""Supertrend flip entry — ported from ``SupertrendStrategy``.

Long on a flip from -1 (downtrend) to +1, short on the mirror flip. Only
the transition trades: a bar that merely *continues* the trend is not an
entry, and the very first initialised bar seeds the comparison without
trading.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.kernel.entries.base import EntryModel
from src.kernel.entries.intent import EntryIntent, EntrySide
from src.kernel.indicators.supertrend import Supertrend

if TYPE_CHECKING:
    from nautilus_trader.indicators.base.indicator import Indicator
    from nautilus_trader.model.data import Bar

    from src.lab.recorder.indicator_recorder import IndicatorRecorder


class SupertrendFlipEntry(EntryModel):
    """Trend-following entry driven by Supertrend direction changes."""

    def __init__(self, *, period: int, multiplier: float) -> None:
        self._supertrend = Supertrend(period=period, multiplier=multiplier)
        self._prev_trend: int | None = None
        # The trend just flipped TO, or None when this bar was not a flip.
        self._flipped_to: int | None = None

    @property
    def ready(self) -> bool:
        return self._supertrend.initialized

    def indicators(self) -> tuple[Indicator, ...]:
        return (self._supertrend,)

    def update(self, bar: Bar) -> bool:
        current_trend = self._supertrend.trend
        prev = self._prev_trend
        self._prev_trend = current_trend
        # First initialised bar seeds the comparison; an unchanged trend
        # is not an entry. Either way _prev_trend has already advanced,
        # so a flip a gate later suppresses does not re-fire on the next
        # bar once the gate reopens.
        self._flipped_to = None if prev is None or current_trend == prev else current_trend
        return True

    def evaluate(self) -> EntryIntent | None:
        if self._flipped_to == 1:
            return EntryIntent.market(EntrySide.LONG, "supertrend_flip_up")
        if self._flipped_to == -1:
            return EntryIntent.market(EntrySide.SHORT, "supertrend_flip_down")
        return None

    def reset(self) -> None:
        self._supertrend.reset()
        self._prev_trend = None
        self._flipped_to = None

    def export_indicators(self, bar: Bar, recorder: IndicatorRecorder) -> None:
        """Record the Supertrend line, split into up/down coloured series."""
        # Local import: kernel must stay importable without lab (see
        # EntryModel.export_indicators).
        from src.lab.recorder.indicator_recorder import ns_to_utc

        st = self._supertrend
        if not (st.initialized and st.value is not None):
            return
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
        recorder.record("supertrend_up", ts, st.value if st.trend == 1 else None)
        recorder.record("supertrend_down", ts, st.value if st.trend == -1 else None)
