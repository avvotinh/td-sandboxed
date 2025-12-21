"""Adapters module - External integrations.

This module handles:
- ZeroMQ adapter for MT5 bridge communication
- Redis adapter for market data and state (planned)
- Database adapter for TimescaleDB (planned)
"""

from .zmq_adapter import ZmqAdapter, ZmqConfig
from .zmq_models import Order, OrderResult, OrderSide, OrderStatus, Tick

__all__ = [
    "ZmqAdapter",
    "ZmqConfig",
    "Tick",
    "Order",
    "OrderResult",
    "OrderSide",
    "OrderStatus",
]
