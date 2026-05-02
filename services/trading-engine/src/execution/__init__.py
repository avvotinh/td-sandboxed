"""Execution module for pre-trade validation and order execution.

This module provides:
- OrderValidator: Pre-trade rule validation
- ValidationResult: Result of validation check
- ValidatedZmqAdapter: ZmqAdapter wrapper with validation
- OrderBlockedError: Exception when order is blocked by rules

Example:
    from src.execution import OrderValidator, ValidatedZmqAdapter, OrderBlockedError

    validator = OrderValidator(rule_engine, redis_client)
    validated_adapter = ValidatedZmqAdapter(zmq_adapter, validator, risk_registry)

    try:
        await validated_adapter.send_order(order)
    except OrderBlockedError as e:
        print(f"Order blocked: {e.reason}")
"""

from .exceptions import OrderBlockedError
from .order_validator import OrderValidator, ValidationResult
from .validated_adapter import ValidatedZmqAdapter

__all__ = [
    "OrderValidator",
    "ValidationResult",
    "ValidatedZmqAdapter",
    "OrderBlockedError",
]
