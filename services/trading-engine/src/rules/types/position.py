"""Position-related rule implementations.

This module contains rules for monitoring and limiting position sizes:
- MaxPositionSizeRule: Blocks trades when position size exceeds limit (Story 4.4)
"""

import logging
from decimal import Decimal
from typing import Any

from ..base_rule import RuleAction, RuleResult

logger = logging.getLogger(__name__)


class MaxPositionSizeRule:
    """Position size limit rule - blocks trades when position size exceeds limit.

    FTMO Default: 100 lots with scaling "per_10k_balance" (1 lot per $10k).

    This rule monitors requested trade sizes and total exposure, and:
    - BLOCKS trading when position size exceeds the calculated limit
    - WARNS when approaching the limit (configurable warning levels)
    - ALLOWS trading when safely below all thresholds

    Supports two modes:
    1. Fixed limit: max_lots is used directly
    2. Scaled limit: max_lots is adjusted based on account balance

    Attributes:
        rule_type: "max_position_size"
        name: Human-readable name with limit (e.g., "Position Size Limit 1.0 lots")
        priority: 3 (evaluated after drawdown rules)
        max_lots: Maximum allowed position size in lots
        scaling: Scaling mode ("per_10k_balance" or None for fixed)
        warning_at: List of warning percentages (default: [70, 80, 90])

    Example:
        >>> rule = MaxPositionSizeRule(max_lots=1.0)
        >>> context = {"requested_lots": 0.5, "current_position_lots": 0.0}
        >>> result = rule.validate(context)
        >>> result.action  # Returns ALLOW
        <RuleAction.ALLOW: 'allow'>

        >>> context = {"requested_lots": 1.5, "current_position_lots": 0.0}
        >>> result = rule.validate(context)
        >>> result.action  # Returns BLOCK
        <RuleAction.BLOCK: 'block'>
    """

    rule_type: str = "max_position_size"
    priority: int = 3  # After daily loss (1) and max drawdown (2)

    def __init__(
        self,
        max_lots: float = 1.0,
        scaling: str | None = None,
        warning_at: list[float] | None = None,
        action: str = "block_trading",  # From YAML, for documentation
        **kwargs: Any,  # Accept additional YAML fields
    ) -> None:
        """Initialize MaxPositionSizeRule.

        Args:
            max_lots: Maximum position size in lots (default: 1.0).
                For scaling mode, this is the base multiplier.
            scaling: Scaling mode for dynamic limits:
                - None or "fixed": Use max_lots directly
                - "per_10k_balance": Scale by account balance (1 lot per $10k)
            warning_at: Warning thresholds as percentages of limit.
                Default: [70, 80, 90] means warn at 70%, 80%, 90% of limit.
            action: Action to take (for YAML compatibility, always blocks).
            **kwargs: Additional YAML fields (ignored for forward compatibility).
        """
        self.max_lots = float(max_lots)
        self.scaling = scaling
        self.warning_at = sorted(
            warning_at if warning_at is not None else [70.0, 80.0, 90.0]
        )

        # Validate max_lots - must be positive
        if self.max_lots <= 0:
            logger.warning(
                "MaxPositionSizeRule created with invalid max_lots=%.2f. "
                "Limit must be > 0. This will block all trades.",
                self.max_lots,
            )

        # Validate scaling mode
        valid_scaling = [None, "fixed", "per_10k_balance"]
        if self.scaling is not None and self.scaling not in valid_scaling:
            logger.warning(
                "Unknown scaling mode '%s'. Supported: %s. Using fixed limit.",
                self.scaling,
                valid_scaling,
            )
            self.scaling = None

    @property
    def name(self) -> str:
        """Human-readable name with limit."""
        if self.scaling == "per_10k_balance":
            return f"Position Size Limit (scaled: {self.max_lots} lots per $10k)"
        return f"Position Size Limit {self.max_lots} lots"

    def _calculate_effective_max(self, context: dict[str, Any]) -> float:
        """Calculate effective max lots considering scaling.

        Args:
            context: Trading context with account_balance if scaling enabled.

        Returns:
            Effective max lots (scaled or fixed).
        """
        if self.scaling == "per_10k_balance":
            account_balance = context.get("account_balance", 0.0)
            if isinstance(account_balance, Decimal):
                account_balance = float(account_balance)

            if account_balance <= 0:
                logger.warning(
                    "Invalid account_balance %.2f for scaling. Using fixed limit.",
                    account_balance,
                )
                return self.max_lots

            # Scale: 1 lot per $10k of balance * base multiplier
            effective_max = (account_balance / 10000.0) * self.max_lots
            logger.debug(
                "Scaled position limit: $%.2f / $10k * %.2f = %.2f lots max",
                account_balance,
                self.max_lots,
                effective_max,
            )
            return effective_max

        return self.max_lots

    def validate(self, context: dict[str, Any]) -> RuleResult:
        """Validate trading context against position size limit.

        Checks both the requested order size and total exposure (existing + new)
        against the configured limit. Returns appropriate action.

        Args:
            context: Trading context with position size keys.
                Expected keys:
                - requested_lots (float|Decimal): Size of the order being validated
                - current_position_lots (float|Decimal): Existing open position size
                - account_balance (float|Decimal): For scaling calculation (optional)

        Returns:
            RuleResult with:
            - BLOCK if size exceeds limit
            - WARN if approaching limit (at warning level)
            - ALLOW if safely below all thresholds
        """
        # Extract values from context
        requested_lots = context.get("requested_lots", 0.0)
        current_position_lots = context.get("current_position_lots", 0.0)

        # Convert Decimal to float
        if isinstance(requested_lots, Decimal):
            requested_lots = float(requested_lots)
        if isinstance(current_position_lots, Decimal):
            current_position_lots = float(current_position_lots)

        # Calculate effective limit (may be scaled)
        effective_max = self._calculate_effective_max(context)

        # Calculate total exposure
        total_exposure = abs(current_position_lots) + abs(requested_lots)

        # If no request, always allow
        if requested_lots <= 0:
            logger.debug(
                "Position size ALLOWED: no position requested (%.2f lots)",
                requested_lots,
            )
            return RuleResult(
                action=RuleAction.ALLOW,
                current_value=total_exposure,
                threshold_value=effective_max,
            )

        # Check if single order exceeds limit (even without existing positions)
        if requested_lots > effective_max:
            logger.warning(
                "Position size BLOCKED: requested %.2f lots > %.2f lots limit",
                requested_lots,
                effective_max,
            )
            return RuleResult(
                action=RuleAction.BLOCK,
                message=(
                    f"Position size {requested_lots:.1f} exceeds limit {effective_max:.1f} lots"
                ),
                current_value=requested_lots,
                threshold_value=effective_max,
                metadata={
                    "rule_type": self.rule_type,
                    "requested_lots": requested_lots,
                    "effective_max": effective_max,
                    "scaling": self.scaling,
                },
            )

        # Check total exposure (existing + new)
        if total_exposure > effective_max:
            logger.warning(
                "Position size BLOCKED: total exposure %.2f lots > %.2f lots limit "
                "(current: %.2f + requested: %.2f)",
                total_exposure,
                effective_max,
                current_position_lots,
                requested_lots,
            )
            return RuleResult(
                action=RuleAction.BLOCK,
                message=(
                    f"Total exposure {total_exposure:.1f} lots would exceed limit "
                    f"of {effective_max:.1f} lots "
                    f"(current: {current_position_lots:.1f} + requested: {requested_lots:.1f})"
                ),
                current_value=total_exposure,
                threshold_value=effective_max,
                metadata={
                    "rule_type": self.rule_type,
                    "requested_lots": requested_lots,
                    "current_position_lots": current_position_lots,
                    "total_exposure": total_exposure,
                    "effective_max": effective_max,
                    "scaling": self.scaling,
                },
            )

        # Check warning thresholds based on total exposure
        usage_percent = (total_exposure / effective_max) * 100 if effective_max > 0 else 100
        for warning_threshold in sorted(self.warning_at, reverse=True):
            if usage_percent >= warning_threshold:
                logger.warning(
                    "Position size WARNING: at %.1f%% of limit (%.2f of %.2f lots)",
                    usage_percent,
                    total_exposure,
                    effective_max,
                )
                return RuleResult(
                    action=RuleAction.WARN,
                    message=(
                        f"Position size at {usage_percent:.0f}% of "
                        f"{effective_max:.1f} lots limit ({total_exposure:.1f} lots)"
                    ),
                    current_value=total_exposure,
                    threshold_value=effective_max,
                    metadata={
                        "rule_type": self.rule_type,
                        "warning_threshold": warning_threshold,
                        "usage_percent": usage_percent,
                    },
                )

        # Below all thresholds - ALLOW
        logger.debug(
            "Position size ALLOWED: %.2f lots < %.2f lots limit",
            total_exposure,
            effective_max,
        )
        return RuleResult(
            action=RuleAction.ALLOW,
            current_value=total_exposure,
            threshold_value=effective_max,
        )

    def get_current_value(self, context: dict[str, Any]) -> float:
        """Get total position exposure from context.

        Args:
            context: Trading context with position size keys.

        Returns:
            Total exposure in lots (current + requested).
        """
        requested_lots = context.get("requested_lots", 0.0)
        current_position_lots = context.get("current_position_lots", 0.0)

        if isinstance(requested_lots, Decimal):
            requested_lots = float(requested_lots)
        if isinstance(current_position_lots, Decimal):
            current_position_lots = float(current_position_lots)

        return abs(current_position_lots) + abs(requested_lots)

    def get_threshold(self) -> float:
        """Get the base position size limit.

        Returns:
            Base max_lots (not scaled). For scaled limit, use validate().
        """
        return self.max_lots

    def get_warning_thresholds(self) -> list[float]:
        """Get warning threshold percentages.

        Returns:
            List of percentages at which to warn (e.g., [70.0, 80.0, 90.0]).
        """
        return self.warning_at.copy()

    def __repr__(self) -> str:
        """Return string representation for debugging."""
        return (
            f"MaxPositionSizeRule(max_lots={self.max_lots}, "
            f"scaling={self.scaling}, "
            f"warnings={self.warning_at})"
        )
