"""Target-related rule implementations for progress tracking.

This module contains informational rules that track progress toward goals:
- ProfitTargetRule: Tracks profit target achievement (Story 4.5)
- MinTradingDaysRule: Tracks minimum trading days requirement (Story 4.5)
- WeeklyTargetRule: Tracks weekly profit target (Epic 9 P0.8 — The5ers
  Bootstrap)

Key differences from blocking rules (drawdown.py, position.py):
- These rules NEVER return BLOCK - they are informational only
- They return WARN when targets are met (to notify user)
- They return ALLOW with progress info when targets are not yet met
- Priority is 100 (evaluated last, after all blocking rules)
"""

import logging
from decimal import Decimal
from typing import Any, ClassVar

from ..base_rule import RuleAction, RuleResult

logger = logging.getLogger(__name__)


class ProfitTargetRule:
    """Profit target rule - tracks progress toward profit goal.

    FTMO Default: 10% profit target for Challenge phase (informational only).

    This rule monitors the total P&L percentage and:
    - WARNS when profit target is reached (congratulatory notification)
    - ALLOWS trading at all times (never blocks - this is informational)

    Unlike blocking rules (DailyLossLimitRule, MaxDrawdownRule), this rule
    exists to track challenge completion progress, not to prevent trading.

    Attributes:
        rule_type: "profit_target"
        name: Human-readable name with target (e.g., "Profit Target 10%")
        priority: 100 (informational rule, evaluated last)
        threshold_percent: Profit target as percentage (default: 10.0)
        action: Always "notify" (for YAML compatibility)

    Example:
        >>> rule = ProfitTargetRule(threshold_percent=10.0)
        >>> context = {"total_pnl_percent": 8.5}  # 8.5% profit
        >>> result = rule.validate(context)
        >>> result.action  # Returns ALLOW (target not yet met)
        <RuleAction.ALLOW: 'allow'>

        >>> context = {"total_pnl_percent": 10.0}  # 10% profit (target met!)
        >>> result = rule.validate(context)
        >>> result.action  # Returns WARN (target met notification)
        <RuleAction.WARN: 'warn'>

    Note:
        This rule NEVER returns BLOCK - profit is good, we just notify!
    """

    rule_type: ClassVar[str] = "profit_target"
    priority: ClassVar[int] = 100  # Informational rule - evaluate last

    def __init__(
        self,
        threshold_percent: float = 10.0,
        action: str = "notify",  # From YAML, for documentation
        **kwargs: Any,  # Accept additional YAML fields
    ) -> None:
        """Initialize ProfitTargetRule.

        Args:
            threshold_percent: Profit target as percentage (default: 10.0).
                FTMO Challenge uses 10%, Verification uses 5%.
            action: Action to take (for YAML compatibility, always notifies).
            **kwargs: Additional YAML fields (ignored for forward compatibility).
        """
        self.threshold_percent = float(threshold_percent)
        self.action_type = action  # Store for reference, always notify

        # Validate threshold - must be positive
        if self.threshold_percent <= 0:
            logger.warning(
                "ProfitTargetRule created with invalid threshold_percent=%.2f. "
                "Threshold must be > 0.",
                self.threshold_percent,
            )

    @property
    def name(self) -> str:
        """Human-readable name with target.

        Returns:
            Name like "Profit Target 10%"
        """
        return f"Profit Target {self.threshold_percent}%"

    def validate(self, context: dict[str, Any]) -> RuleResult:
        """Validate trading context against profit target.

        Checks the current total P&L percentage against the configured target.
        This rule NEVER blocks trading - it only notifies when target is met.

        Args:
            context: Trading context with total_pnl_percent key.
                Expected keys:
                - total_pnl_percent (float|Decimal): Current total P&L as percentage
                    of initial balance. Positive values indicate profit
                    (e.g., 8.5 = 8.5% profit).

        Returns:
            RuleResult with:
            - WARN if profit >= target (congratulatory notification)
            - ALLOW if below target (with progress info)

        Note:
            This rule NEVER returns BLOCK - profit is always good!
        """
        # Get current total P&L (positive = profit, negative = loss)
        total_pnl_percent = context.get("total_pnl_percent", 0.0)

        # Convert Decimal to float for consistent comparison
        if isinstance(total_pnl_percent, Decimal):
            total_pnl_percent = float(total_pnl_percent)

        # Check if profit target is met - WARN (notify, don't block)
        if total_pnl_percent >= self.threshold_percent:
            logger.info(
                "Profit target REACHED: %.2f%% >= %.2f%% target",
                total_pnl_percent,
                self.threshold_percent,
            )
            return RuleResult(
                action=RuleAction.WARN,
                message=(
                    f"Profit target achieved! {total_pnl_percent:.2f}% "
                    f">= {self.threshold_percent}% target"
                ),
                current_value=total_pnl_percent,
                threshold_value=self.threshold_percent,
                metadata={
                    "rule_type": self.rule_type,
                    "target_met": True,
                },
            )

        # Below target - ALLOW with progress info
        progress_percent = (total_pnl_percent / self.threshold_percent) * 100 if self.threshold_percent > 0 else 0.0
        remaining = self.threshold_percent - total_pnl_percent

        logger.debug(
            "Profit target progress: %.2f%% of %.2f%% (%.1f%% complete, %.2f%% remaining)",
            total_pnl_percent,
            self.threshold_percent,
            progress_percent,
            remaining,
        )
        return RuleResult(
            action=RuleAction.ALLOW,
            message=(
                f"Profit target progress: {total_pnl_percent:.2f}% of "
                f"{self.threshold_percent}% ({progress_percent:.0f}% complete)"
            ),
            current_value=total_pnl_percent,
            threshold_value=self.threshold_percent,
            metadata={
                "rule_type": self.rule_type,
                "target_met": False,
                "progress_percent": progress_percent,
                "remaining_percent": remaining,
            },
        )

    def get_current_value(self, context: dict[str, Any]) -> float:
        """Get current total P&L percentage from context.

        Args:
            context: Trading context with total_pnl_percent key.

        Returns:
            Current P&L as percentage (can be positive or negative).
            Returns 0.0 if total_pnl_percent not in context.
        """
        total_pnl_percent = context.get("total_pnl_percent", 0.0)
        if isinstance(total_pnl_percent, Decimal):
            total_pnl_percent = float(total_pnl_percent)
        return total_pnl_percent

    def get_threshold(self) -> float:
        """Get the profit target threshold percentage.

        Returns:
            Threshold percentage (e.g., 10.0 for 10% target).
        """
        return self.threshold_percent

    def get_warning_thresholds(self) -> list[float]:
        """Get warning threshold percentages.

        For profit target, there are no warning thresholds - we only
        notify when the target is fully met.

        Returns:
            Empty list (no intermediate warnings for profit target).
        """
        return []

    def __repr__(self) -> str:
        """Return string representation for debugging.

        Returns:
            String like "ProfitTargetRule(threshold=10.0%)"
        """
        return f"ProfitTargetRule(threshold={self.threshold_percent}%)"


class MinTradingDaysRule:
    """Minimum trading days rule - tracks progress toward days requirement.

    FTMO Default: 4 trading days minimum for Challenge phase (informational only).

    This rule monitors the number of unique trading days and:
    - WARNS when minimum trading days requirement is met (notification)
    - ALLOWS trading at all times (never blocks - this is informational)

    A "trading day" is defined as any calendar day (in account timezone)
    where at least one trade was opened.

    Attributes:
        rule_type: "min_trading_days"
        name: Human-readable name with requirement (e.g., "Minimum Trading Days (4)")
        priority: 100 (informational rule, evaluated last)
        required_days: Minimum number of trading days required (default: 4)
        action: Always "notify" (for YAML compatibility)

    Example:
        >>> rule = MinTradingDaysRule(required_days=4)
        >>> context = {"trading_days_count": 3}  # 3 days so far
        >>> result = rule.validate(context)
        >>> result.action  # Returns ALLOW (requirement not yet met)
        <RuleAction.ALLOW: 'allow'>

        >>> context = {"trading_days_count": 4}  # 4 days (requirement met!)
        >>> result = rule.validate(context)
        >>> result.action  # Returns WARN (requirement met notification)
        <RuleAction.WARN: 'warn'>

    Note:
        This rule NEVER returns BLOCK - we just track progress!
    """

    rule_type: ClassVar[str] = "min_trading_days"
    priority: ClassVar[int] = 100  # Informational rule - evaluate last

    def __init__(
        self,
        required_days: int = 4,
        action: str = "notify",  # From YAML, for documentation
        **kwargs: Any,  # Accept additional YAML fields
    ) -> None:
        """Initialize MinTradingDaysRule.

        Args:
            required_days: Minimum number of trading days required (default: 4).
                FTMO requires 4 trading days for Challenge/Verification.
            action: Action to take (for YAML compatibility, always notifies).
            **kwargs: Additional YAML fields (ignored for forward compatibility).
        """
        self.required_days = int(required_days)
        self.action_type = action  # Store for reference, always notify

        # Validate required_days - must be positive
        if self.required_days <= 0:
            logger.warning(
                "MinTradingDaysRule created with invalid required_days=%d. "
                "Requirement must be > 0.",
                self.required_days,
            )

    @property
    def name(self) -> str:
        """Human-readable name with requirement.

        Returns:
            Name like "Minimum Trading Days (4)"
        """
        return f"Minimum Trading Days ({self.required_days})"

    def validate(self, context: dict[str, Any]) -> RuleResult:
        """Validate trading context against minimum trading days requirement.

        Checks the current trading days count against the configured requirement.
        This rule NEVER blocks trading - it only notifies when requirement is met.

        Args:
            context: Trading context with trading_days_count key.
                Expected keys:
                - trading_days_count (int): Number of unique days with at least
                    one trade opened. Calculated from trade history.

        Returns:
            RuleResult with:
            - WARN if days >= requirement (requirement met notification)
            - ALLOW if below requirement (with progress info)

        Note:
            This rule NEVER returns BLOCK - we just track progress!
        """
        # Get current trading days count
        trading_days_count = context.get("trading_days_count", 0)

        # Convert to int if needed
        if isinstance(trading_days_count, float):
            trading_days_count = int(trading_days_count)

        # Check if requirement is met - WARN (notify, don't block)
        if trading_days_count >= self.required_days:
            logger.info(
                "Minimum trading days REACHED: %d >= %d required",
                trading_days_count,
                self.required_days,
            )
            return RuleResult(
                action=RuleAction.WARN,
                message=(
                    f"Minimum trading days requirement met! {trading_days_count} "
                    f">= {self.required_days} days"
                ),
                current_value=float(trading_days_count),
                threshold_value=float(self.required_days),
                metadata={
                    "rule_type": self.rule_type,
                    "requirement_met": True,
                },
            )

        # Below requirement - ALLOW with progress info
        remaining = self.required_days - trading_days_count

        logger.debug(
            "Minimum trading days progress: %d of %d days (%d remaining)",
            trading_days_count,
            self.required_days,
            remaining,
        )
        return RuleResult(
            action=RuleAction.ALLOW,
            message=(
                f"Trading days progress: {trading_days_count} of "
                f"{self.required_days} days ({remaining} more needed)"
            ),
            current_value=float(trading_days_count),
            threshold_value=float(self.required_days),
            metadata={
                "rule_type": self.rule_type,
                "requirement_met": False,
                "remaining_days": remaining,
            },
        )

    def get_current_value(self, context: dict[str, Any]) -> float:
        """Get current trading days count from context.

        Args:
            context: Trading context with trading_days_count key.

        Returns:
            Current trading days count as float.
            Returns 0.0 if trading_days_count not in context.
        """
        trading_days_count = context.get("trading_days_count", 0)
        return float(trading_days_count)

    def get_threshold(self) -> float:
        """Get the minimum trading days requirement.

        Returns:
            Required days as float (e.g., 4.0 for 4 days requirement).
        """
        return float(self.required_days)

    def get_warning_thresholds(self) -> list[float]:
        """Get warning threshold percentages.

        For minimum trading days, there are no warning thresholds - we only
        notify when the requirement is fully met.

        Returns:
            Empty list (no intermediate warnings for trading days).
        """
        return []

    def __repr__(self) -> str:
        """Return string representation for debugging.

        Returns:
            String like "MinTradingDaysRule(required_days=4)"
        """
        return f"MinTradingDaysRule(required_days={self.required_days})"


class WeeklyTargetRule:
    """Weekly profit target — informational tracker (Epic 9 P0.8).

    Used by The5ers Bootstrap (default 1.25% per week) and any other
    product that scores progress on a rolling Monday-anchored window.

    Reads ``weekly_pnl_percent`` from context — the caller (a future
    weekly profit tracker, mirroring :class:`DailyProfitHistory`) is
    responsible for computing the rolling Mon-Sun value. The rule
    itself is window-agnostic: anything you label "this week" works.

    NEVER returns ``BLOCK``: the rule is purely informational so that
    a trader can see "target met" without trading being interrupted.
    """

    rule_type: ClassVar[str] = "weekly_target"
    priority: ClassVar[int] = 100  # informational

    def __init__(
        self,
        threshold_percent: float = 1.25,
        action: str = "notify",
        **kwargs: Any,
    ) -> None:
        self.threshold_percent = float(threshold_percent)
        self.action_type = action
        if self.threshold_percent <= 0:
            logger.warning(
                "WeeklyTargetRule created with invalid threshold_percent=%.2f. "
                "Threshold must be > 0.",
                self.threshold_percent,
            )

    @property
    def name(self) -> str:
        return f"Weekly Target {self.threshold_percent}%"

    @staticmethod
    def _coerce(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, Decimal):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            logger.warning(
                "WeeklyTargetRule: non-numeric weekly_pnl_percent=%r, "
                "defaulting to 0.0",
                value,
            )
            return 0.0

    def validate(self, context: dict[str, Any]) -> RuleResult:
        weekly_pnl_percent = self._coerce(context.get("weekly_pnl_percent", 0.0))

        if weekly_pnl_percent >= self.threshold_percent:
            logger.info(
                "Weekly target REACHED: %.2f%% >= %.2f%% target",
                weekly_pnl_percent, self.threshold_percent,
            )
            return RuleResult(
                action=RuleAction.WARN,
                message=(
                    f"Weekly profit target met: {weekly_pnl_percent:.2f}% "
                    f">= {self.threshold_percent}%"
                ),
                current_value=weekly_pnl_percent,
                threshold_value=self.threshold_percent,
                metadata={
                    "rule_type": self.rule_type,
                    "weekly_pnl_percent": weekly_pnl_percent,
                    "target_met": True,
                },
            )

        return RuleResult(
            action=RuleAction.ALLOW,
            current_value=weekly_pnl_percent,
            threshold_value=self.threshold_percent,
            metadata={
                "rule_type": self.rule_type,
                "weekly_pnl_percent": weekly_pnl_percent,
                "target_met": False,
            },
        )

    def get_current_value(self, context: dict[str, Any]) -> float:
        return max(0.0, self._coerce(context.get("weekly_pnl_percent", 0.0)))

    def get_threshold(self) -> float:
        return self.threshold_percent

    def get_warning_thresholds(self) -> list[float]:
        return []

    def __repr__(self) -> str:
        return f"WeeklyTargetRule(threshold={self.threshold_percent}%)"
