"""Donchian channel breakout entry — ported from ``DonchianBreakoutStrategy``.

Long when the close pierces the **prior** bar's N-bar upper band, short on
the prior lower band. Comparing against the prior band is the whole trick:
the current bar is always inside its own channel, so a current-bar
comparison never triggers.

``entry_on_cross_only`` switches the trigger from level to edge — enter
only on the first bar of a breakout episode (Track 5.1), which kills the
re-entry churn diagnosed in ``docs/research/entry-exit-trailing`` §1.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.kernel.entries.base import EntryModel
from src.kernel.entries.intent import EntryIntent, EntrySide
from src.kernel.indicators import Donchian

if TYPE_CHECKING:
    from nautilus_trader.indicators.base.indicator import Indicator
    from nautilus_trader.model.data import Bar

    from src.lab.recorder.indicator_recorder import IndicatorRecorder


@dataclass(frozen=True, slots=True)
class _BreakoutFacts:
    """What one bar said, relative to the band that preceded it."""

    breakout_up: bool
    breakout_down: bool
    was_up: bool
    was_down: bool


class DonchianCrossEntry(EntryModel):
    """Turtle-style channel breakout against the prior bar's band."""

    def __init__(self, *, channel_period: int, entry_on_cross_only: bool = False) -> None:
        self._donchian = Donchian(channel_period)
        self._entry_on_cross_only = entry_on_cross_only
        self._prev_upper: float | None = None
        self._prev_lower: float | None = None
        # Episode state: was the previous close already outside the
        # (then-prior) channel on each side?
        self._prev_breakout_up: bool = False
        self._prev_breakout_down: bool = False
        self._facts: _BreakoutFacts | None = None

    @property
    def ready(self) -> bool:
        return self._donchian.initialized

    def indicators(self) -> tuple[Indicator, ...]:
        return (self._donchian,)

    def update(self, bar: Bar) -> bool:
        close = bar.close.as_double()
        prev_upper = self._prev_upper
        prev_lower = self._prev_lower

        # Capture the current band as the "prior" reference for the next
        # bar BEFORE any early return — otherwise the seed bar never
        # stores it. Rolling references advance on EVERY bar, including
        # gated ones, so the first bar after a gap compares against the
        # true prior bar rather than a frozen pre-gap snapshot.
        self._prev_upper = self._donchian.upper
        self._prev_lower = self._donchian.lower

        if prev_upper is None or prev_lower is None:
            # Seed bar: no prior band to compare against. Episode state
            # stays untouched — there was no breakout to remember.
            self._facts = None
            return True

        breakout_up = close > prev_upper
        breakout_down = close < prev_lower

        # Advance episode state here, in update, so a breakout that a
        # session or ADX gate later suppresses still arms/disarms the
        # edge trigger — an episode that begins overnight must not read
        # as "first breakout bar" at session open.
        self._facts = _BreakoutFacts(
            breakout_up=breakout_up,
            breakout_down=breakout_down,
            was_up=self._prev_breakout_up,
            was_down=self._prev_breakout_down,
        )
        self._prev_breakout_up = breakout_up
        self._prev_breakout_down = breakout_down
        return True

    def evaluate(self) -> EntryIntent | None:
        facts = self._facts
        if facts is None:
            return None

        breakout_up = facts.breakout_up
        breakout_down = facts.breakout_down
        if self._entry_on_cross_only:
            breakout_up = breakout_up and not facts.was_up
            breakout_down = breakout_down and not facts.was_down

        if breakout_up:
            return EntryIntent.market(EntrySide.LONG, "donchian_upper_cross")
        if breakout_down:
            return EntryIntent.market(EntrySide.SHORT, "donchian_lower_cross")
        return None

    def reset(self) -> None:
        self._donchian.reset()
        self._prev_upper = None
        self._prev_lower = None
        self._prev_breakout_up = False
        self._prev_breakout_down = False
        self._facts = None

    def export_indicators(self, bar: Bar, recorder: IndicatorRecorder) -> None:
        """Record the three Donchian bands as chart overlays."""
        # Local import: kernel must stay importable without lab (see
        # EntryModel.export_indicators).
        from src.lab.recorder.indicator_recorder import ns_to_utc

        dc = self._donchian
        if not dc.initialized:
            return
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
        # Nautilus DonchianChannel computes a middle band; guard with
        # getattr in case a future indicator swap drops it.
        recorder.record("donchian_middle", ts, getattr(dc, "middle", None))
