"""Adapters module - External integrations.

This module handles:
- ZeroMQ adapter for MT5 bridge communication
- MT5 Connection Manager for per-account connections
- Redis adapter for market data subscription
- Database adapter for TimescaleDB (planned)
"""

from .mt5_connection_manager import ConnectionHealth, MT5ConnectionManager
from .redis_adapter import MaxReconnectAttemptsError, RedisAdapter
from .redis_config import RedisConfig
from .redis_models import Bar
from .zmq_adapter import ZmqAdapter, ZmqConfig
from .zmq_models import MT5Position, Order, OrderResult, OrderSide, OrderStatus, Tick

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
    "MT5Position",
    # MT5 Connection Manager
    "MT5ConnectionManager",
    "ConnectionHealth",
]
