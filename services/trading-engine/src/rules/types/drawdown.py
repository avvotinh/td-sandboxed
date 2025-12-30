"""Drawdown-related rule implementations.

This module contains rules for monitoring and limiting drawdown:
- DailyLossLimitRule: Blocks trades when daily loss exceeds threshold (Story 4.2)
- MaxDrawdownRule: Blocks trades when total drawdown exceeds threshold (Story 4.3)

Key differences between the rules:
- DailyLossLimitRule: Uses daily_pnl_percent (negative = loss), resets daily
- MaxDrawdownRule: Uses total_drawdown_percent (positive = drawdown), cumulative from peak
"""

import logging
from decimal import Decimal
from typing import Any

from ..base_rule import RuleAction, RuleResult

logger = logging.getLogger(__name__)


class DailyLossLimitRule:
    """Daily loss limit rule - blocks trades when daily loss threshold is reached.

    FTMO Default: 5% daily loss limit with warnings at 70%, 80%, 90%.

    This rule monitors the daily P&L percentage and:
    - BLOCKS trading when daily loss reaches or exceeds the threshold
    - WARNS when approaching the threshold (configurable warning levels)
    - ALLOWS trading when safely below all thresholds

    Attributes:
        rule_type: "daily_loss_limit"
        name: Human-readable name with threshold (e.g., "Daily Loss Limit 5%")
        priority: 1 (critical rule, evaluated first)
        threshold_percent: Maximum allowed daily loss as percentage
        reset_time: Time when daily P&L resets (default: "00:00")
        timezone: Timezone for reset (default: "UTC", FTMO uses "CET")
        warning_at: List of warning percentages (default: [70, 80, 90])

    Example:
        >>> rule = DailyLossLimitRule(threshold_percent=5.0)
        >>> context = {"daily_pnl_percent": -3.5}  # 3.5% loss
        >>> result = rule.validate(context)
        >>> result.action  # Returns WARN (at 70% of limit)
        <RuleAction.WARN: 'warn'>

        >>> context = {"daily_pnl_percent": -5.0}  # 5% loss (at limit)
        >>> result = rule.validate(context)
        >>> result.action  # Returns BLOCK
        <RuleAction.BLOCK: 'block'>
    """

    rule_type: str = "daily_loss_limit"
    priority: int = 1  # Critical rule - evaluate first

    def __init__(
        self,
        threshold_percent: float = 5.0,
        reset_time: str = "00:00",
        timezone: str = "UTC",
        warning_at: list[float] | None = None,
        action: str = "block_trading",  # From YAML, for documentation
        **kwargs: Any,  # Accept additional YAML fields
    ) -> None:
        """Initialize DailyLossLimitRule.

        Args:
            threshold_percent: Max daily loss as percentage (default: 5.0).
                FTMO uses 5% for all challenge phases.
            reset_time: Reset time in HH:MM format (default: "00:00").
            timezone: Timezone for reset (default: "UTC", FTMO uses "CET").
            warning_at: Warning thresholds as percentages of limit.
                Default: [70, 80, 90] means warn at 70%, 80%, 90% of the limit.
                For a 5% limit: warn at 3.5%, 4%, 4.5% actual loss.
            action: Action to take (for YAML compatibility, always blocks).
            **kwargs: Additional YAML fields (ignored for forward compatibility).
        """
        self.threshold_percent = float(threshold_percent)
        self.reset_time = reset_time
        self.timezone = timezone
        self.warning_at = sorted(
            warning_at if warning_at is not None else [70.0, 80.0, 90.0]
        )

        # Validate threshold - must be positive
        if self.threshold_percent <= 0:
            logger.warning(
                "DailyLossLimitRule created with invalid threshold_percent=%.2f. "
                "Threshold must be > 0. This will block all trades.",
                self.threshold_percent,
            )

    @property
    def name(self) -> str:
        """Human-readable name with threshold.

        Returns:
            Name like "Daily Loss Limit 5%"
        """
        return f"Daily Loss Limit {self.threshold_percent}%"

    def validate(self, context: dict[str, Any]) -> RuleResult:
        """Validate trading context against daily loss limit.

        Checks the current daily P&L percentage against the configured threshold
        and warning levels. Returns the appropriate action based on current state.

        Args:
            context: Trading context with daily_pnl_percent key.
                Expected keys:
                - daily_pnl_percent (float|Decimal): Current daily P&L as percentage.
                    Negative values indicate loss (e.g., -3.5 = 3.5% loss).

        Returns:
            RuleResult with:
            - BLOCK if loss >= threshold
            - WARN if approaching threshold (at warning level)
            - ALLOW if safely below all thresholds

        Note:
            The rule uses absolute value for comparison since losses are
            represented as negative percentages. A daily_pnl_percent of -3.5
            means a 3.5% loss.
        """
        # Get current daily P&L (negative = loss, positive = profit)
        daily_pnl_percent = context.get("daily_pnl_percent", 0.0)

        # Convert Decimal to float for consistent comparison
        if isinstance(daily_pnl_percent, Decimal):
            daily_pnl_percent = float(daily_pnl_percent)

        # If positive (profit) or zero, always allow - this is a LOSS limit rule
        if daily_pnl_percent >= 0:
            logger.debug(
                "Daily loss ALLOWED: P&L %.2f%% is profit/zero (no loss)",
                daily_pnl_percent,
            )
            return RuleResult(
                action=RuleAction.ALLOW,
                current_value=0.0,  # No loss
                threshold_value=self.threshold_percent,
            )

        # Use absolute value for loss comparison (daily_pnl_percent is negative here)
        current_loss_percent = abs(daily_pnl_percent)

        # Check if at or above threshold - BLOCK
        if current_loss_percent >= self.threshold_percent:
            logger.warning(
                "Daily loss limit BLOCKED: %.2f%% >= %.2f%% threshold",
                current_loss_percent,
                self.threshold_percent,
            )
            return RuleResult(
                action=RuleAction.BLOCK,
                message=(
                    f"Daily loss {current_loss_percent:.2f}% "
                    f"exceeds limit of {self.threshold_percent}%"
                ),
                current_value=current_loss_percent,
                threshold_value=self.threshold_percent,
                metadata={
                    "rule_type": self.rule_type,
                    "daily_pnl_percent": daily_pnl_percent,
                },
            )

        # Check warning thresholds (sorted descending to trigger highest applicable)
        usage_percent = (current_loss_percent / self.threshold_percent) * 100
        for warning_threshold in sorted(self.warning_at, reverse=True):
            if usage_percent >= warning_threshold:
                logger.warning(
                    "Daily loss WARNING: at %.1f%% of limit (%.2f%% of %.2f%%)",
                    usage_percent,
                    current_loss_percent,
                    self.threshold_percent,
                )
                return RuleResult(
                    action=RuleAction.WARN,
                    message=(
                        f"Daily loss at {usage_percent:.0f}% of "
                        f"{self.threshold_percent}% limit ({current_loss_percent:.2f}%)"
                    ),
                    current_value=current_loss_percent,
                    threshold_value=self.threshold_percent,
                    metadata={
                        "rule_type": self.rule_type,
                        "warning_threshold": warning_threshold,
                        "usage_percent": usage_percent,
                    },
                )

        # Below all thresholds - ALLOW
        logger.debug(
            "Daily loss ALLOWED: %.2f%% < %.2f%% threshold",
            current_loss_percent,
            self.threshold_percent,
        )
        return RuleResult(
            action=RuleAction.ALLOW,
            current_value=current_loss_percent,
            threshold_value=self.threshold_percent,
        )

    def get_current_value(self, context: dict[str, Any]) -> float:
        """Get current daily loss percentage from context.

        Args:
            context: Trading context with daily_pnl_percent key.

        Returns:
            Current loss as positive percentage (0.0 if in profit or no loss).
            Returns 0.0 if daily_pnl_percent not in context.
        """
        daily_pnl_percent = context.get("daily_pnl_percent", 0.0)
        if isinstance(daily_pnl_percent, Decimal):
            daily_pnl_percent = float(daily_pnl_percent)
        # Only return loss amount (positive), not profit
        # Losses are negative, so if >= 0, there's no loss
        if daily_pnl_percent >= 0:
            return 0.0
        return abs(daily_pnl_percent)

    def get_threshold(self) -> float:
        """Get the daily loss threshold percentage.

        Returns:
            Threshold percentage (e.g., 5.0 for 5% limit).
        """
        return self.threshold_percent

    def get_warning_thresholds(self) -> list[float]:
        """Get warning threshold percentages.

        Returns:
            List of percentages at which to warn (e.g., [70.0, 80.0, 90.0]).
            These are percentages of the limit, not of the balance.
        """
        return self.warning_at.copy()

    def __repr__(self) -> str:
        """Return string representation for debugging.

        Returns:
            String like "DailyLossLimitRule(threshold=5.0%, reset=00:00 UTC, warnings=[70, 80, 90])"
        """
        return (
            f"DailyLossLimitRule(threshold={self.threshold_percent}%, "
            f"reset={self.reset_time} {self.timezone}, "
            f"warnings={self.warning_at})"
        )


class MaxDrawdownRule:
    """Max drawdown rule - blocks trades when total drawdown threshold is reached.

    FTMO Default: 10% max drawdown with warnings at 50%, 70%, 85%.

    This rule monitors the total drawdown percentage (from peak equity) and:
    - BLOCKS trading when drawdown reaches or exceeds the threshold
    - WARNS when approaching the threshold (configurable warning levels)
    - ALLOWS trading when safely below all thresholds

    Attributes:
        rule_type: "max_drawdown"
        name: Human-readable name with threshold (e.g., "Max Drawdown 10%")
        priority: 2 (critical rule, evaluated after daily loss limit)
        threshold_percent: Maximum allowed drawdown as percentage
        reference: Reference point for drawdown ("initial_balance")
        warning_at: List of warning percentages (default: [50, 70, 85])

    Example:
        >>> rule = MaxDrawdownRule(threshold_percent=10.0)
        >>> context = {"total_drawdown_percent": 7.0}  # 7% drawdown
        >>> result = rule.validate(context)
        >>> result.action  # Returns WARN (at 70% of limit)
        <RuleAction.WARN: 'warn'>

        >>> context = {"total_drawdown_percent": 10.0}  # 10% drawdown (at limit)
        >>> result = rule.validate(context)
        >>> result.action  # Returns BLOCK
        <RuleAction.BLOCK: 'block'>
    """

    rule_type: str = "max_drawdown"
    priority: int = 2  # Evaluated after daily loss limit

    def __init__(
        self,
        threshold_percent: float = 10.0,
        reference: str = "initial_balance",
        warning_at: list[float] | None = None,
        action: str = "block_trading",  # From YAML, for documentation
        **kwargs: Any,  # Accept additional YAML fields
    ) -> None:
        """Initialize MaxDrawdownRule.

        Args:
            threshold_percent: Max drawdown as percentage (default: 10.0).
                FTMO uses 10% for all challenge phases.
            reference: Reference point for drawdown calculation.
                Default: "initial_balance" (FTMO style).
                NOTE: The current implementation uses peak_equity (high water mark)
                via RiskState.total_drawdown_percent. The reference parameter is
                accepted for YAML compatibility but does not change calculation
                behavior in this implementation.
            warning_at: Warning thresholds as percentages of limit.
                Default: [50, 70, 85] means warn at 50%, 70%, 85% of the limit.
                For a 10% limit: warn at 5%, 7%, 8.5% actual drawdown.
            action: Action to take (for YAML compatibility, always blocks).
            **kwargs: Additional YAML fields (ignored for forward compatibility).
        """
        self.threshold_percent = float(threshold_percent)
        self.reference = reference
        self.warning_at = sorted(
            warning_at if warning_at is not None else [50.0, 70.0, 85.0]
        )

        # Validate threshold - must be positive
        if self.threshold_percent <= 0:
            logger.warning(
                "MaxDrawdownRule created with invalid threshold_percent=%.2f. "
                "Threshold must be > 0. This will block all trades.",
                self.threshold_percent,
            )

    @property
    def name(self) -> str:
        """Human-readable name with threshold.

        Returns:
            Name like "Max Drawdown 10%"
        """
        return f"Max Drawdown {self.threshold_percent}%"

    def validate(self, context: dict[str, Any]) -> RuleResult:
        """Validate trading context against max drawdown limit.

        Checks the current total drawdown percentage against the configured
        threshold and warning levels. Returns the appropriate action based
        on current state.

        Args:
            context: Trading context with total_drawdown_percent key.
                Expected keys:
                - total_drawdown_percent (float|Decimal): Current drawdown from
                    peak as percentage. Positive values indicate drawdown
                    (e.g., 7.0 = 7% drawdown from peak).

        Returns:
            RuleResult with:
            - BLOCK if drawdown >= threshold
            - WARN if approaching threshold (at warning level)
            - ALLOW if safely below all thresholds

        Note:
            Unlike DailyLossLimitRule which uses negative values for loss,
            total_drawdown_percent is already positive (drawdown is measured
            as percentage below peak equity).
        """
        # Get current total drawdown (positive = drawdown, 0 or negative = no drawdown)
        total_drawdown_percent = context.get("total_drawdown_percent", 0.0)

        # Convert Decimal to float for consistent comparison
        if isinstance(total_drawdown_percent, Decimal):
            total_drawdown_percent = float(total_drawdown_percent)

        # If no drawdown or zero, always allow (defensive edge case)
        if total_drawdown_percent <= 0:
            logger.debug(
                "Max drawdown ALLOWED: drawdown %.2f%% <= 0 (no drawdown)",
                total_drawdown_percent,
            )
            return RuleResult(
                action=RuleAction.ALLOW,
                current_value=0.0,
                threshold_value=self.threshold_percent,
            )

        # Check if at or above threshold - BLOCK
        if total_drawdown_percent >= self.threshold_percent:
            logger.warning(
                "Max drawdown BLOCKED: %.2f%% >= %.2f%% threshold",
                total_drawdown_percent,
                self.threshold_percent,
            )
            return RuleResult(
                action=RuleAction.BLOCK,
                message=(
                    f"Max drawdown {total_drawdown_percent:.2f}% "
                    f"exceeds limit of {self.threshold_percent}%"
                ),
                current_value=total_drawdown_percent,
                threshold_value=self.threshold_percent,
                metadata={
                    "rule_type": self.rule_type,
                    "reference": self.reference,
                },
            )

        # Check warning thresholds (sorted descending to trigger highest applicable)
        usage_percent = (total_drawdown_percent / self.threshold_percent) * 100
        for warning_threshold in sorted(self.warning_at, reverse=True):
            if usage_percent >= warning_threshold:
                logger.warning(
                    "Max drawdown WARNING: at %.1f%% of limit (%.2f%% of %.2f%%)",
                    usage_percent,
                    total_drawdown_percent,
                    self.threshold_percent,
                )
                return RuleResult(
                    action=RuleAction.WARN,
                    message=(
                        f"Drawdown at {usage_percent:.0f}% of "
                        f"{self.threshold_percent}% limit ({total_drawdown_percent:.2f}%)"
                    ),
                    current_value=total_drawdown_percent,
                    threshold_value=self.threshold_percent,
                    metadata={
                        "rule_type": self.rule_type,
                        "warning_threshold": warning_threshold,
                        "usage_percent": usage_percent,
                    },
                )

        # Below all thresholds - ALLOW
        logger.debug(
            "Max drawdown ALLOWED: %.2f%% < %.2f%% threshold",
            total_drawdown_percent,
            self.threshold_percent,
        )
        return RuleResult(
            action=RuleAction.ALLOW,
            current_value=total_drawdown_percent,
            threshold_value=self.threshold_percent,
        )

    def get_current_value(self, context: dict[str, Any]) -> float:
        """Get current drawdown percentage from context.

        Args:
            context: Trading context with total_drawdown_percent key.

        Returns:
            Current drawdown as positive percentage (0.0 if no drawdown).
            Returns 0.0 if total_drawdown_percent not in context.
        """
        total_drawdown_percent = context.get("total_drawdown_percent", 0.0)
        if isinstance(total_drawdown_percent, Decimal):
            total_drawdown_percent = float(total_drawdown_percent)
        return max(0.0, total_drawdown_percent)  # Never return negative

    def get_threshold(self) -> float:
        """Get the max drawdown threshold percentage.

        Returns:
            Threshold percentage (e.g., 10.0 for 10% limit).
        """
        return self.threshold_percent

    def get_warning_thresholds(self) -> list[float]:
        """Get warning threshold percentages.

        Returns:
            List of percentages at which to warn (e.g., [50.0, 70.0, 85.0]).
            These are percentages of the limit, not of the balance.
        """
        return self.warning_at.copy()

    def __repr__(self) -> str:
        """Return string representation for debugging.

        Returns:
            String like "MaxDrawdownRule(threshold=10.0%, reference=initial_balance, warnings=[50.0, 70.0, 85.0])"
        """
        return (
            f"MaxDrawdownRule(threshold={self.threshold_percent}%, "
            f"reference={self.reference}, "
            f"warnings={self.warning_at})"
        )
