"""Trading Engine Service.

NautilusTrader-based trading engine with FTMO compliance.
Full implementation in Story 1.6.
"""

__version__ = "0.1.0"

# Execution module exports
from .execution import (
    OrderBlockedError,
    OrderValidator,
    ValidatedZmqAdapter,
    ValidationResult,
)

__all__ = [
    "OrderValidator",
    "ValidationResult",
    "ValidatedZmqAdapter",
    "OrderBlockedError",
]
