"""Recorder package — per-bar equity + indicator capture (Contract v2, P1).

``EquityRecorderActor`` decouples the equity curve from the prop-firm
compliance actor (gap G2); ``IndicatorRecorder`` captures indicator
series while the strategy runs instead of recomputing them afterwards
(gap G6).
"""

from src.lab.recorder.equity_recorder import (
    EquityRecorderActor,
    EquityRecorderActorConfig,
)
from src.lab.recorder.indicator_recorder import IndicatorRecorder, ns_to_utc

__all__ = [
    "EquityRecorderActor",
    "EquityRecorderActorConfig",
    "IndicatorRecorder",
    "ns_to_utc",
]
