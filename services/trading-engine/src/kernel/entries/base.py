"""``EntryModel`` — the entry half of a strategy, isolated from execution.

Roadmap task 3.3 (`docs/v2/02-roadmap.md`). A strategy used to fuse four
concerns into one ``generate_signal``: indicator upkeep, rolling-state
upkeep, the entry decision, and the gates/exits around it. The model owns
the first three; the strategy keeps the gates, the exits, and the order.

## The two-phase call

Entry logic carries rolling state (the *prior* Donchian band, the *previous*
Supertrend trend, the *previous* close for a re-cross). That state must
advance on **every** bar — including bars a session or regime gate throws
away — or the first bar after a gap compares against a frozen pre-gap
snapshot and the model silently trades on stale evidence. But the gates
themselves sit at different points in different strategies: Supertrend
gates before its state upkeep, Donchian and mean-reversion gate after.

So the call splits in two, and **the strategy decides where its gates go**:

* ``update(bar)`` — advance rolling state, capture this bar's facts.
  Called exactly once per bar, always before ``evaluate``.
* ``evaluate()`` — decide, from the facts ``update`` just captured.
  Called only on bars that survive the gates.

Gate placement relative to ``update`` is a per-strategy decision, and the
three ported strategies genuinely differ: Donchian and mean-reversion
gate *after* upkeep (a gated breakout must still close its episode),
Supertrend gates *before* it (an out-of-session bar must not consume the
flip, so an overnight flip still enters on the first eligible bar). Both
are deliberate and both are covered by the parity gate — do not "unify"
them without re-running it.

``evaluate`` reads no bar of its own, which is what keeps the seam
honest: a model physically cannot see past the bar handed to ``update``.

## Warmup

``ready`` covers only the indicators the *model* owns. A strategy whose
SL sizing needs ATR checks that separately — ATR is an exit concern and
does not belong here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nautilus_trader.indicators.base.indicator import Indicator
    from nautilus_trader.model.data import Bar

    from src.kernel.entries.intent import EntryIntent
    from src.lab.recorder.indicator_recorder import IndicatorRecorder


class EntryModel(ABC):
    """Bar-driven entry decision with its own indicators and rolling state."""

    @property
    @abstractmethod
    def ready(self) -> bool:
        """True once every indicator this model owns is initialised."""

    @abstractmethod
    def indicators(self) -> tuple[Indicator, ...]:
        """Indicators the host must register for bars, in registration order."""

    @abstractmethod
    def update(self, bar: Bar) -> bool:
        """Advance rolling state for ``bar`` and capture its facts.

        Call exactly once per bar, before :meth:`evaluate`, and only
        once :attr:`ready` holds. Where the host's gates sit relative to
        this call is the host's decision — see the module docstring.

        Returns:
            ``False`` when the bar is unusable — a degenerate indicator
            state (a collapsed band, say) that makes the decision
            undefined. State is left untouched and the caller should
            skip the bar; the model has already logged why — meaning the
            model's rolling references stay frozen for that bar, as if it
            had never arrived. ``True`` otherwise, including on a warmup
            bar that simply has no prior reference to compare against
            yet. Of the three ported models only
            :class:`~src.kernel.entries.mr_band.MeanReversionBandEntry`
            can return ``False``; the other two have no degenerate state
            to detect, so that branch of the contract is exercised by one
            model alone.

        Callers **must** check the return value, even against a model
        that cannot currently return ``False``. Two of the three ported
        models never do, and a host written by copying one of them
        would silently trade through the degenerate bars of a model
        that does.
        """

    @abstractmethod
    def evaluate(self) -> EntryIntent | None:
        """The entry decision for the bar ``update`` last captured.

        Returns ``None`` when this bar offers no entry — no evidence, or
        no ``update`` has run yet.
        """

    @abstractmethod
    def reset(self) -> None:
        """Clear indicators and rolling state back to construction state."""

    def export_indicators(self, bar: Bar, recorder: IndicatorRecorder) -> None:
        """Record this model's series for Contract v2. Default: nothing.

        Implementations import from ``src.lab`` *inside* the method
        body, never at module level: ``kernel`` must stay importable
        without ``lab``, and today no module under ``src/kernel/`` has a
        runtime import of ``src.lab``. Keep it that way.
        """
