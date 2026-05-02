"""Discrete market regime states used by the rule-based classifier.

These four states partition every bar into one bucket plus an ``UNKNOWN``
sentinel for the warmup period before enough bars are available to
compute features. Strategies declare which regime states they accept via
``register_strategy(..., regimes=[...])``; the router matches on these
exact values.
"""

from __future__ import annotations

from enum import Enum


class RegimeState(str, Enum):
    """Market regime classification.

    Inherits from ``str`` so values serialise cleanly into audit log
    JSON without a custom encoder.
    """

    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    UNKNOWN = "unknown"
