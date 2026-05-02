"""``RegimeDecision`` value object (Epic 11 story 11.3).

Produced by :class:`HysteresisFilter` (story 11.4) on every bar after
the warmup period; consumed by :class:`RegimeAuditAdapter` (story 11.5)
and :class:`RegimeAwareRouter` (story 11.7). The classifier itself
returns a bare :class:`RegimeState`; the surrounding fields here capture
the transition state and confidence the hysteresis filter computes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.regime.features import RegimeFeatures
from src.regime.states import RegimeState


@dataclass(frozen=True)
class RegimeDecision:
    """Snapshot of one bar's regime decision plus hysteresis state.

    ``current_state`` is what :class:`RegimeAwareRouter` matches against
    ``Strategy.allowed_regimes``; ``raw_state`` is what the classifier
    actually emitted this bar (may differ during hysteresis confirmation).
    ``pending_state`` and ``bars_in_pending`` record the ongoing
    confirmation count: when ``pending_state is None`` the regime is
    stable, otherwise the filter is N bars into a candidate transition.
    """

    timestamp: datetime
    bar_type: str
    current_state: RegimeState
    raw_state: RegimeState
    pending_state: RegimeState | None
    bars_in_pending: int
    features: RegimeFeatures
    confidence: float

    def __post_init__(self) -> None:
        if not self.bar_type:
            raise ValueError("RegimeDecision.bar_type must be non-empty")
        if self.timestamp.tzinfo is None:
            raise ValueError(
                "RegimeDecision.timestamp must be timezone-aware "
                "(audit logs are global; naive datetimes drift silently)"
            )
        if self.bars_in_pending < 0:
            raise ValueError(
                "RegimeDecision.bars_in_pending must be >= 0, "
                f"got {self.bars_in_pending}"
            )
        if self.pending_state is None and self.bars_in_pending != 0:
            raise ValueError(
                "RegimeDecision.bars_in_pending must be 0 when pending_state is None"
            )
        if self.pending_state is not None:
            if self.pending_state == self.current_state:
                raise ValueError(
                    "RegimeDecision.pending_state must differ from current_state"
                )
            if self.bars_in_pending <= 0:
                raise ValueError(
                    "RegimeDecision.bars_in_pending must be > 0 when pending_state is set"
                )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "RegimeDecision.confidence must be in [0, 1], "
                f"got {self.confidence}"
            )


__all__ = ["RegimeDecision"]
