"""Rule type implementations for prop-firm compliance.

This module contains concrete rule implementations:
- DailyLossLimitRule: Blocks trades when daily loss exceeds threshold (Story 4.2)
- MaxDrawdownRule: Blocks trades when total drawdown exceeds threshold (Story 4.3)
- MaxPositionSizeRule: Limits position sizes (Story 4.4)
- ProfitTargetRule: Tracks profit target achievement (Story 4.5)
- MinTradingDaysRule: Tracks minimum trading days requirement (Story 4.5)
- ConsistencyRule: Blocks trades when single-day profit concentration exceeds
  the firm's consistency limit (Epic 9 P0.7 — FTMO 50%)
"""

from .consistency import ConsistencyRule
from .drawdown import DailyLossLimitRule, MaxDrawdownRule
from .position import MaxPositionSizeRule
from .targets import MinTradingDaysRule, ProfitTargetRule

__all__ = [
    "ConsistencyRule",
    "DailyLossLimitRule",
    "MaxDrawdownRule",
    "MaxPositionSizeRule",
    "ProfitTargetRule",
    "MinTradingDaysRule",
]
