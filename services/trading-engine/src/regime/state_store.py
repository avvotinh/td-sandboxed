"""Shared regime publication object (Epic 15 story 15.2).

The ``RegimeActor`` (story 15.5) runs the classify → hysteresis pipeline in
``on_bar`` and **publishes** the confirmed regime here; strategies **read** it
at their entry-only order seam (story 15.7) and suppress disallowed entries.
This replaces the Epic-11 "withhold the bar" model — a Nautilus ``Actor``
cannot withhold a bar, so the gate moves into the strategy and this store is
the single source of truth it consults.

Single-threaded by construction: written only by ``RegimeActor.on_bar`` and
read on the same Nautilus event loop, so no locking is needed. Snapshots are
immutable — ``publish`` replaces the per-``bar_type`` entry, never mutates it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.regime.decision import RegimeDecision
from src.regime.features import RegimeFeatures
from src.regime.states import RegimeState


@dataclass(frozen=True)
class RegimeSnapshot:
    """The latest confirmed regime for one ``bar_type``.

    ``features`` is carried so the future meta-label gate (signal-quality epic)
    can read the exact feature vector the regime decision was made on, without
    recomputation — keeping the model input identical to the audited decision.
    """

    bar_type: str
    current_state: RegimeState
    confidence: float
    ts: datetime
    features: RegimeFeatures


class RegimeStateStore:
    """Latest confirmed :class:`RegimeSnapshot` per ``bar_type``."""

    def __init__(self) -> None:
        self._snapshots: dict[str, RegimeSnapshot] = {}

    def publish(self, decision: RegimeDecision) -> None:
        """Record the decision as the current snapshot for its ``bar_type``.

        Replaces any prior snapshot (a new frozen object) rather than mutating
        it, so a strategy holding an earlier snapshot sees a stable value.
        """
        self._snapshots[decision.bar_type] = RegimeSnapshot(
            bar_type=decision.bar_type,
            current_state=decision.current_state,
            confidence=decision.confidence,
            ts=decision.timestamp,
            features=decision.features,
        )

    def current(self, bar_type: str) -> RegimeSnapshot | None:
        """Return the latest snapshot for ``bar_type``, or ``None`` if none yet.

        ``None`` means "no confirmed regime" (e.g. warmup) — strategies treat
        that as *suppress entry*, not *allow*.
        """
        return self._snapshots.get(bar_type)


__all__ = ["RegimeSnapshot", "RegimeStateStore"]
