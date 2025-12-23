"""Adapters module - External integrations.

This module handles:
- ZeroMQ adapter for MT5 bridge communication
- Redis adapter for market data subscription
- Database adapter for TimescaleDB (planned)
"""

from .redis_adapter import MaxReconnectAttemptsError, RedisAdapter
from .redis_config import RedisConfig
from .redis_models import Bar
from .zmq_adapter import ZmqAdapter, ZmqConfig
from .zmq_models import Order, OrderResult, OrderSide, OrderStatus, Tick

__all__ = [
    # Redis adapter
    "RedisAdapter",
    "RedisConfig",
    "Bar",
    "MaxReconnectAttemptsError",
    # ZMQ adapter
    "ZmqAdapter",
    "ZmqConfig",
    "Tick",
    "Order",
    "OrderResult",
    "OrderSide",
    "OrderStatus",
]
