"""Order execution service.

This module provides the OrderExecutionService which orchestrates the complete
order lifecycle from signal to execution.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from src.adapters.zmq_adapter import ZmqAdapter
from src.adapters.zmq_models import Order, OrderResult, OrderSide
from src.orders.order import InternalOrder, OrderState
from src.orders.position_tracker import PositionTracker
from src.orders.signal import Signal, SignalType
from src.orders.trade import Trade

logger = logging.getLogger(__name__)


class DuplicateOrderError(Exception):
    """Raised when attempting to submit a duplicate order."""

    pass


class NoPositionError(Exception):
    """Raised when attempting to close a non-existent position."""

    pass


class OrderExecutionService:
    """Service for executing orders via mt5-bridge.

    Handles the complete order lifecycle:
    1. Signal -> Order creation
    2. Idempotency check
    3. Order submission via ZMQ
    4. Result handling and position updates
    5. Trade record creation

    Attributes:
        SLIPPAGE_WARNING_THRESHOLD: Threshold for slippage warnings (0.5%)

    Usage:
        service = OrderExecutionService(zmq_adapter, position_tracker)

        # Execute a BUY signal
        signal = Signal(SignalType.BUY, symbol="XAUUSD", strategy_name="ma_cross")
        order = await service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
        )

        if order.is_filled:
            print(f"Filled at {order.fill_price}")
    """

    # Slippage warning threshold (0.5%)
    SLIPPAGE_WARNING_THRESHOLD = 0.005

    def __init__(
        self,
        zmq_adapter: ZmqAdapter,
        position_tracker: PositionTracker,
        order_timeout: float = 5.0,
    ) -> None:
        """Initialize the order execution service.

        Args:
            zmq_adapter: ZMQ adapter for order communication
            position_tracker: Position tracker for managing positions
            order_timeout: Timeout for order execution in seconds
        """
        self._zmq = zmq_adapter
        self._positions = position_tracker
        self._order_timeout = order_timeout
        self._pending_order_ids: set[str] = set()
        self._trades: list[Trade] = []

    @property
    def position_tracker(self) -> PositionTracker:
        """Get the position tracker."""
        return self._positions

    @property
    def trades(self) -> list[Trade]:
        """Get all trades (copy)."""
        return self._trades.copy()

    async def execute_signal(
        self,
        signal: Signal,
        account_id: str,
        volume: float,
        price: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> InternalOrder:
        """Execute a trading signal as an order.

        Args:
            signal: Trading signal (BUY/SELL/CLOSE)
            account_id: Account to execute on
            volume: Lot size (0 for CLOSE uses position volume)
            price: Requested execution price
            sl: Optional stop loss
            tp: Optional take profit

        Returns:
            InternalOrder with final state

        Raises:
            DuplicateOrderError: If order_id already pending
            NoPositionError: If CLOSE signal without position
            asyncio.TimeoutError: If order times out
        """
        # Create order from signal
        order = self._create_order(signal, account_id, volume, price, sl, tp)

        # Idempotency check
        if order.order_id in self._pending_order_ids:
            raise DuplicateOrderError(f"Order {order.order_id} already pending")

        self._pending_order_ids.add(order.order_id)

        try:
            # Submit order
            order.transition_to(OrderState.SUBMITTED)
            order.submitted_at = datetime.now(timezone.utc)

            logger.info(
                "Submitting order: %s %s %s @ %.4f (id=%s)",
                order.action.value,
                order.symbol,
                order.volume,
                order.price,
                order.order_id[:8],
            )

            # Send via ZMQ and wait for result
            zmq_order = Order(
                account_id=order.account_id,
                action=order.action,
                symbol=order.symbol,
                volume=order.volume,
                price=order.price,
                sl=order.sl,
                tp=order.tp,
                order_id=order.order_id,
            )

            result = await self._zmq.send_order_and_wait(
                zmq_order,
                timeout=self._order_timeout,
            )

            # Handle result
            self._handle_result(order, result)

        except asyncio.TimeoutError:
            order.transition_to(OrderState.ERROR)
            order.rejection_reason = "Order timeout"
            logger.error("Order timeout: %s", order.order_id[:8])
            raise

        except Exception as e:
            order.transition_to(OrderState.ERROR)
            order.rejection_reason = str(e)
            logger.error("Order error: %s - %s", order.order_id[:8], e)
            raise

        finally:
            self._pending_order_ids.discard(order.order_id)

        return order

    def _create_order(
        self,
        signal: Signal,
        account_id: str,
        volume: float,
        price: float,
        sl: Optional[float],
        tp: Optional[float],
    ) -> InternalOrder:
        """Create internal order from signal.

        CRITICAL: Handles BUY, SELL, and CLOSE signals differently:
        - BUY/SELL: Direct mapping to order side
        - CLOSE: Determines opposite side from existing position

        Args:
            signal: Trading signal
            account_id: Account to execute on
            volume: Lot size (0 for CLOSE uses position volume)
            price: Requested price
            sl: Stop loss
            tp: Take profit

        Returns:
            InternalOrder ready for submission

        Raises:
            NoPositionError: If CLOSE signal without position
        """
        if signal.signal_type == SignalType.CLOSE:
            # CLOSE signal: determine side from existing position
            position = self._positions.get_position(account_id, signal.symbol)
            if not position:
                raise NoPositionError(
                    f"No position to close for {account_id}/{signal.symbol}"
                )

            # Close by taking opposite side
            action = (
                OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
            )

            # Use position volume if not specified
            if volume == 0 or volume is None:
                volume = position.quantity

            logger.debug(
                "CLOSE signal: closing %s position with %s order",
                position.side.value,
                action.value,
            )

        elif signal.signal_type == SignalType.BUY:
            action = OrderSide.BUY
        else:
            action = OrderSide.SELL

        return InternalOrder(
            account_id=account_id,
            symbol=signal.symbol,
            action=action,
            volume=volume,
            price=price,
            sl=sl,
            tp=tp,
            signal_type=signal.signal_type,
        )

    def _handle_result(self, order: InternalOrder, result: OrderResult) -> None:
        """Handle order execution result.

        CRITICAL: Handles position updates and trade recording:
        - CLOSE orders: Close position, create closed trade with PnL
        - BUY/SELL orders: Open position, create open trade

        Args:
            order: The internal order
            result: Result from mt5-bridge
        """
        if result.is_filled:
            order.transition_to(OrderState.FILLED)
            order.filled_at = datetime.now(timezone.utc)
            order.fill_price = result.fill_price
            order.slippage = result.slippage
            order.filled_quantity = order.volume

            # Log slippage
            self._log_slippage(order, result)

            # CRITICAL: Handle position updates based on signal type
            if order.is_close_order:
                self._handle_close_fill(order)
            else:
                self._handle_entry_fill(order)

            logger.info(
                "Order FILLED: %s %s %s %.2f @ %.4f (slippage=%.4f)",
                order.order_id[:8],
                order.action.value,
                order.symbol,
                order.volume,
                order.fill_price or 0,
                order.slippage or 0,
            )

        elif result.is_rejected:
            order.transition_to(OrderState.REJECTED)
            order.rejection_reason = result.error

            logger.warning(
                "Order REJECTED: %s - %s",
                order.order_id[:8],
                result.error,
            )

    def _handle_entry_fill(self, order: InternalOrder) -> None:
        """Handle entry order fill (BUY/SELL).

        Opens a new position and creates an open trade record.

        Args:
            order: The filled entry order
        """
        # Open position
        self._positions.open_position(order)

        # Create open trade
        trade = Trade(
            order_id=order.order_id,
            account_id=order.account_id,
            symbol=order.symbol,
            side=order.action,
            quantity=order.volume,
            entry_price=order.fill_price or order.price,
            entry_time=order.filled_at or datetime.now(timezone.utc),
            slippage=order.slippage,
        )
        self._trades.append(trade)

        logger.debug(
            "Trade opened: %s %s @ %.4f",
            trade.side.value,
            trade.symbol,
            trade.entry_price,
        )

    def _handle_close_fill(self, order: InternalOrder) -> None:
        """Handle close order fill.

        Closes the position and creates a closed trade with PnL.

        Args:
            order: The filled close order
        """
        # Close position
        closed_position = self._positions.close_position(
            order.account_id, order.symbol
        )

        if not closed_position:
            logger.warning(
                "Position not found for close order: %s/%s",
                order.account_id,
                order.symbol,
            )
            return

        # Calculate PnL
        exit_price = order.fill_price or order.price
        price_diff = exit_price - closed_position.entry_price
        if closed_position.side == OrderSide.SELL:
            price_diff = -price_diff  # Short position
        pnl_dollars = price_diff * closed_position.quantity
        pnl_percent = (
            (price_diff / closed_position.entry_price) * 100
            if closed_position.entry_price
            else 0
        )

        # Create closed trade
        trade = Trade(
            trade_id=str(uuid.uuid4()),
            order_id=closed_position.order_id,  # Original entry order
            account_id=order.account_id,
            symbol=order.symbol,
            side=closed_position.side,
            quantity=closed_position.quantity,
            entry_price=closed_position.entry_price,
            entry_time=closed_position.entry_time,
            exit_price=exit_price,
            exit_time=order.filled_at,
            pnl_dollars=pnl_dollars,
            pnl_percent=pnl_percent,
            slippage=order.slippage,
        )
        self._trades.append(trade)

        logger.info(
            "Position CLOSED: %s %s PnL: $%.2f (%.2f%%)",
            order.symbol,
            closed_position.side.value,
            pnl_dollars,
            pnl_percent,
        )

    def _log_slippage(self, order: InternalOrder, result: OrderResult) -> None:
        """Log slippage with warning if above threshold.

        Args:
            order: The order
            result: Order result
        """
        if result.slippage is None:
            return

        slippage_pct = abs(result.slippage) / order.price if order.price else 0

        if slippage_pct > self.SLIPPAGE_WARNING_THRESHOLD:
            logger.warning(
                "HIGH SLIPPAGE on order %s: %.4f (%.2f%%)",
                order.order_id[:8],
                result.slippage,
                slippage_pct * 100,
            )
        else:
            logger.debug(
                "Order %s slippage: %.4f (%.2f%%)",
                order.order_id[:8],
                result.slippage,
                slippage_pct * 100,
            )

    # Trade retrieval methods for audit/reporting

    def get_trades(self) -> list[Trade]:
        """Get all trades."""
        return self._trades.copy()

    def get_trades_by_account(self, account_id: str) -> list[Trade]:
        """Get trades for a specific account."""
        return [t for t in self._trades if t.account_id == account_id]

    def get_trade_by_order_id(self, order_id: str) -> Optional[Trade]:
        """Get trade by order ID."""
        for trade in self._trades:
            if trade.order_id == order_id:
                return trade
        return None

    def get_open_trades(self) -> list[Trade]:
        """Get all open trades (without exit)."""
        return [t for t in self._trades if t.is_open]

    def get_closed_trades(self) -> list[Trade]:
        """Get all closed trades (with exit)."""
        return [t for t in self._trades if t.is_closed]

    def get_total_pnl(self, account_id: Optional[str] = None) -> float:
        """Get total realized PnL.

        Args:
            account_id: Optional account filter

        Returns:
            Total PnL in dollars
        """
        trades = (
            self.get_trades_by_account(account_id)
            if account_id
            else self._trades
        )
        return sum(t.pnl_dollars or 0 for t in trades if t.is_closed)

    def is_order_pending(self, order_id: str) -> bool:
        """Check if an order is currently pending.

        Args:
            order_id: Order ID to check

        Returns:
            True if order is pending
        """
        return order_id in self._pending_order_ids

    def get_pending_order_count(self) -> int:
        """Get count of pending orders."""
        return len(self._pending_order_ids)

    def clear_trades(self) -> int:
        """Clear all trades (for testing/reset).

        Returns:
            Number of trades cleared
        """
        count = len(self._trades)
        self._trades.clear()
        return count

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"OrderExecutionService("
            f"pending={len(self._pending_order_ids)}, "
            f"trades={len(self._trades)})"
        )
