"""Composable strategy mixins.

These mixins provide cross-cutting capabilities that individual strategies
can opt into without inflating ``BaseStrategy``:

- ``ATRStopMixin``     — ATR-based stop-loss / take-profit math
- ``SessionFilterMixin`` — DST-safe trading-session windows
- ``RiskSizedMixin``   — position sizing via injected ``PositionSizerProtocol``
"""

from __future__ import annotations

from src.strategies.mixins.atr_stop_mixin import ATRStopMixin
from src.strategies.mixins.risk_sized_mixin import RiskSizedMixin
from src.strategies.mixins.session_filter_mixin import SessionFilterMixin

__all__ = ["ATRStopMixin", "RiskSizedMixin", "SessionFilterMixin"]
