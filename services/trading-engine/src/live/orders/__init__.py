"""Order execution module.

This module provides the complete order lifecycle management:
- Signal: Trading signals (BUY/SELL/CLOSE)
- InternalOrder: Order model with state tracking
- Trade: Trade record for audit trail
- PositionTracker: Position tracking per account/symbol
- OrderExecutionService: Order execution orchestration
- TradeRecord: SQLAlchemy model for trades table (database queries)
"""

from src.live.orders.db_models import Base, TradeRecord
from src.live.orders.execution_service import DuplicateOrderError, OrderExecutionService
from src.live.orders.order import InternalOrder, OrderState
from src.live.orders.order_gateway import OrderGateway
from src.live.orders.position_tracker import Position, PositionTracker
from src.kernel.signal import Signal, SignalType
from src.live.orders.trade import Trade

__all__ = [
    # Signal
    "Signal",
    "SignalType",
    # Order
    "OrderState",
    "InternalOrder",
    # Order gateway protocol (Epic 9 P0.12)
    "OrderGateway",
    # Trade
    "Trade",
    # Position
    "Position",
    "PositionTracker",
    # Execution
    "OrderExecutionService",
    "DuplicateOrderError",
    # Database Models
    "Base",
    "TradeRecord",
]
