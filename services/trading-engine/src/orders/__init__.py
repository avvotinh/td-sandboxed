"""Order execution module.

This module provides the complete order lifecycle management:
- Signal: Trading signals (BUY/SELL/CLOSE)
- InternalOrder: Order model with state tracking
- Trade: Trade record for audit trail
- PositionTracker: Position tracking per account/symbol
- OrderExecutionService: Order execution orchestration
- TradeRecord: SQLAlchemy model for trades table (database queries)
"""

from src.orders.db_models import Base, TradeRecord
from src.orders.execution_service import DuplicateOrderError, OrderExecutionService
from src.orders.order import InternalOrder, OrderState
from src.orders.position_tracker import Position, PositionTracker
from src.orders.signal import Signal, SignalType
from src.orders.trade import Trade

__all__ = [
    # Signal
    "Signal",
    "SignalType",
    # Order
    "OrderState",
    "InternalOrder",
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
