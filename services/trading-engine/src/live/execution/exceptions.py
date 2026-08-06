"""Execution module exceptions.

This module provides exception classes for the execution module:
- OrderBlockedError: Raised when an order is blocked by compliance rules
"""


class OrderBlockedError(Exception):
    """Exception raised when an order is blocked by compliance rules.

    This exception is raised by ValidatedZmqAdapter when pre-trade validation
    blocks an order. It contains details about why the order was blocked.

    Attributes:
        reason: Human-readable explanation of why the order was blocked.
        blocked_by_rule: Name of the rule that blocked the trade.
        current_value: Current metric value that caused the block.
        threshold_value: Threshold value that was exceeded.

    Example:
        try:
            await validated_adapter.send_order(order)
        except OrderBlockedError as e:
            print(f"Order blocked by {e.blocked_by_rule}: {e.reason}")
    """

    def __init__(
        self,
        reason: str,
        blocked_by_rule: str | None = None,
        current_value: float | None = None,
        threshold_value: float | None = None,
    ) -> None:
        """Initialize OrderBlockedError.

        Args:
            reason: Human-readable explanation of the block.
            blocked_by_rule: Name of the blocking rule (optional).
            current_value: Current metric value (optional).
            threshold_value: Threshold that was exceeded (optional).
        """
        super().__init__(reason)
        self.reason = reason
        self.blocked_by_rule = blocked_by_rule
        self.current_value = current_value
        self.threshold_value = threshold_value

    def __str__(self) -> str:
        """Return string representation of the error."""
        if self.blocked_by_rule:
            return f"[{self.blocked_by_rule}] {self.reason}"
        return self.reason

    def __repr__(self) -> str:
        """Return detailed representation of the error."""
        return (
            f"OrderBlockedError(reason={self.reason!r}, "
            f"blocked_by_rule={self.blocked_by_rule!r}, "
            f"current_value={self.current_value}, "
            f"threshold_value={self.threshold_value})"
        )
