"""PnLTracker - Real-time P&L tracking for per-account positions.

Tracks unrealized and realized P&L for open positions:
- Updates unrealized P&L on each tick
- Records realized P&L when positions are closed
- Propagates equity updates to RiskStateRegistry

CRITICAL: All financial calculations use Decimal for precision.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from ..adapters.zmq_models import Order, OrderResult, OrderSide

if TYPE_CHECKING:
    from .risk_registry import RiskStateRegistry
    from ..state.redis_state import RedisStateManager

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Open position for P&L tracking.

    Attributes:
        position_id: Unique identifier (order_id from original order)
        symbol: Trading symbol (e.g., "XAUUSD")
        side: Position direction (BUY = long, SELL = short)
        volume: Remaining open volume in lots
        entry_price: Average entry price
        current_price: Last mark-to-market price
        unrealized_pnl: Cached unrealized P&L (updated on tick)
        open_time: Timestamp when position was opened
    """

    position_id: str
    symbol: str
    side: OrderSide
    volume: Decimal
    entry_price: Decimal
    current_price: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    open_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PnLMetrics:
    """P&L metrics snapshot for an account.

    Attributes:
        current_equity: Balance + unrealized P&L
        balance: Current account balance
        unrealized_pnl: Sum of unrealized P&L from all open positions
        daily_pnl: Realized + unrealized P&L for today
        daily_pnl_percent: Daily P&L as percentage of starting balance
        total_drawdown_percent: Drawdown from peak equity
        open_positions_count: Number of open positions
    """

    current_equity: Decimal
    balance: Decimal
    unrealized_pnl: Decimal
    daily_pnl: Decimal
    daily_pnl_percent: Decimal
    total_drawdown_percent: Decimal
    open_positions_count: int


def get_multiplier(symbol: str) -> Decimal:
    """Get instrument multiplier for P&L calculations.

    For MVP, returns 1.0 for all forex pairs.
    MT5 already accounts for lot size in price/volume relationship.

    Args:
        symbol: Trading symbol

    Returns:
        Multiplier for P&L calculation (1.0 for forex)
    """
    # Future: Load from config file for indices/commodities
    return Decimal("1.0")


class PnLTracker:
    """Per-account P&L tracker for real-time position monitoring.

    Each account has its own isolated PnLTracker instance.
    No state is shared between accounts.

    Example:
        tracker = PnLTracker(
            account_id="ftmo-001",
            initial_balance=Decimal("100000"),
            risk_registry=registry,
            redis_manager=redis,
        )

        # On tick update
        await tracker.on_tick("XAUUSD", Decimal("1850.25"), Decimal("1850.50"))

        # On trade executed
        await tracker.on_trade_executed(order_result, order)

        # On position closed
        await tracker.on_position_closed("order-123", Decimal("1860.00"), Decimal("500.00"))

        # Get metrics
        metrics = tracker.get_pnl_metrics()
    """

    # Performance threshold in milliseconds (log warning if exceeded)
    TICK_PROCESSING_THRESHOLD_MS = 10.0

    def __init__(
        self,
        account_id: str,
        initial_balance: Decimal,
        risk_registry: "RiskStateRegistry",
        redis_manager: "RedisStateManager | None" = None,
    ) -> None:
        """Initialize P&L tracker for an account.

        Args:
            account_id: Unique account identifier
            initial_balance: Starting balance for calculations
            risk_registry: RiskStateRegistry for updating risk state
            redis_manager: Optional Redis manager for balance persistence
        """
        self._account_id = account_id
        self._balance = initial_balance
        self._risk_registry = risk_registry
        self._redis = redis_manager

        # Internal state - completely isolated per account
        self._positions: dict[str, Position] = {}
        self._daily_realized_pnl = Decimal("0")
        self._current_equity = initial_balance
        self._last_tick_time: datetime | None = None

    @property
    def account_id(self) -> str:
        """Get account identifier."""
        return self._account_id

    @property
    def balance(self) -> Decimal:
        """Get current balance."""
        return self._balance

    @property
    def equity(self) -> Decimal:
        """Get current equity (balance + unrealized P&L)."""
        return self._current_equity

    def has_position_for_symbol(self, symbol: str) -> bool:
        """Quick check if any positions exist for symbol.

        Used for fast-path optimization in tick processing.

        Args:
            symbol: Trading symbol to check

        Returns:
            True if any open positions exist for symbol
        """
        return any(p.symbol == symbol for p in self._positions.values())

    def get_open_positions_count(self) -> int:
        """Get count of open positions.

        Returns:
            Number of open positions
        """
        return len(self._positions)

    def get_total_exposure(self) -> Decimal:
        """Get total exposure (sum of position volumes * entry prices).

        Returns:
            Total exposure in account currency
        """
        total = Decimal("0")
        for position in self._positions.values():
            total += position.volume * position.entry_price * get_multiplier(position.symbol)
        return total

    def calculate_unrealized_pnl(self, position: Position, current_price: Decimal) -> Decimal:
        """Calculate unrealized P&L for a position.

        Formula:
        - LONG: (current_price - entry_price) * volume * multiplier
        - SHORT: (entry_price - current_price) * volume * multiplier

        Args:
            position: Position to calculate P&L for
            current_price: Current mark-to-market price

        Returns:
            Unrealized P&L in account currency (Decimal)
        """
        multiplier = get_multiplier(position.symbol)

        if position.side == OrderSide.BUY:
            # Long position: profit when price goes up
            pnl = (current_price - position.entry_price) * position.volume * multiplier
        else:
            # Short position: profit when price goes down
            pnl = (position.entry_price - current_price) * position.volume * multiplier

        return pnl

    def _recalculate_equity(self) -> Decimal:
        """Recalculate total equity from balance and unrealized P&L.

        Equity = Balance + Sum(unrealized P&L for all positions)

        Returns:
            Updated equity value
        """
        total_unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        self._current_equity = self._balance + total_unrealized
        return self._current_equity

    def _get_total_unrealized_pnl(self) -> Decimal:
        """Get sum of unrealized P&L from all positions.

        Returns:
            Total unrealized P&L
        """
        return sum(p.unrealized_pnl for p in self._positions.values())

    async def on_tick(self, symbol: str, bid: Decimal, ask: Decimal) -> None:
        """Handle tick update for a symbol.

        Updates unrealized P&L for all positions matching the symbol.
        Uses bid for SHORT positions, ask for LONG (conservative mark-to-market).

        Performance target: < 10ms per tick.

        Args:
            symbol: Trading symbol
            bid: Current bid price (Decimal)
            ask: Current ask price (Decimal)
        """
        start_time = time.perf_counter()

        # Fast path: no positions for this symbol
        if not self.has_position_for_symbol(symbol):
            return

        # Update each position matching the symbol
        for position in self._positions.values():
            if position.symbol != symbol:
                continue

            # Mark-to-market: use worst exit price for conservative valuation
            # LONG: exit at bid (lower price)
            # SHORT: exit at ask (higher price to buy back)
            if position.side == OrderSide.BUY:
                mark_price = bid
            else:
                mark_price = ask

            position.current_price = mark_price
            position.unrealized_pnl = self.calculate_unrealized_pnl(position, mark_price)

        # Recalculate total equity
        new_equity = self._recalculate_equity()

        # Update risk registry with new equity
        await self._risk_registry.update_account_equity(self._account_id, new_equity)

        self._last_tick_time = datetime.now(timezone.utc)

        # Performance monitoring
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        if elapsed_ms > self.TICK_PROCESSING_THRESHOLD_MS:
            logger.warning(
                f"P&L update slow for {self._account_id}: {elapsed_ms:.1f}ms for {symbol}"
            )

    async def on_trade_executed(self, order_result: OrderResult, order: Order) -> None:
        """Handle trade execution notification.

        Creates new position from order + result, updates balance for any
        immediate costs, and recalculates equity.

        Args:
            order_result: Execution result with fill_price
            order: Original order with volume and side
        """
        if not order_result.is_filled:
            logger.debug(
                f"Order {order.order_id} not filled (status={order_result.status}), skipping position creation"
            )
            return

        # Convert fill_price to Decimal
        fill_price = Decimal(str(order_result.fill_price)) if order_result.fill_price else Decimal("0")
        volume = Decimal(str(order.volume))

        # Check if we're adding to existing position or creating new
        existing_position = self._positions.get(order.order_id)
        if existing_position:
            # Partial fill case: update volume
            existing_position.volume += volume
            logger.info(
                f"Added to position {order.order_id}: +{volume} lots at {fill_price}"
            )
        else:
            # New position
            position = Position(
                position_id=order.order_id,
                symbol=order.symbol,
                side=order.action,
                volume=volume,
                entry_price=fill_price,
                current_price=fill_price,  # Initial mark = entry
                unrealized_pnl=Decimal("0"),  # No unrealized at entry
            )
            self._positions[order.order_id] = position
            logger.info(
                f"Opened position {order.order_id}: {order.action.value} {volume} {order.symbol} @ {fill_price}"
            )

        # Recalculate equity with new position
        new_equity = self._recalculate_equity()

        # Update risk registry
        await self._risk_registry.update_account_equity(self._account_id, new_equity)

        # Persist balance if Redis available
        if self._redis:
            await self._redis.save_account_balance(self._account_id, self._balance)

    async def on_position_closed(
        self,
        position_id: str,
        close_price: Decimal,
        realized_pnl: Decimal,
    ) -> None:
        """Handle position close notification.

        Removes position, adds realized P&L to daily totals,
        updates balance, and recalculates equity.

        Args:
            position_id: Position identifier to close
            close_price: Close/exit price
            realized_pnl: Realized profit/loss from the trade
        """
        position = self._positions.pop(position_id, None)
        if not position:
            logger.warning(f"Position not found for close: {position_id}")
            return

        # Add realized P&L to daily total
        self._daily_realized_pnl += realized_pnl

        # Update balance with realized P&L
        self._balance += realized_pnl

        # Record trade in risk registry (for daily P&L tracking)
        await self._risk_registry.record_account_trade(self._account_id, realized_pnl)

        # Persist balance if Redis available
        if self._redis:
            await self._redis.save_account_balance(self._account_id, self._balance)

        # Recalculate equity (now without closed position's unrealized)
        new_equity = self._recalculate_equity()
        await self._risk_registry.update_account_equity(self._account_id, new_equity)

        logger.info(
            f"Closed position {position_id}: {position.side.value} {position.volume} {position.symbol} "
            f"@ {close_price}, P&L: {realized_pnl}"
        )

    def get_pnl_metrics(self) -> PnLMetrics:
        """Get current P&L metrics snapshot.

        Returns:
            PnLMetrics with current equity, P&L, and position info
        """
        unrealized_pnl = self._get_total_unrealized_pnl()

        # Get risk state for additional metrics
        risk_state = self._risk_registry.get_risk_state(self._account_id)

        daily_starting_balance = risk_state.daily_starting_balance if risk_state else self._balance
        total_drawdown_percent = risk_state.total_drawdown_percent if risk_state else Decimal("0")

        # Daily P&L = realized (today) + unrealized (current positions)
        daily_pnl = self._daily_realized_pnl + unrealized_pnl

        # Calculate daily P&L percentage
        if daily_starting_balance > 0:
            daily_pnl_percent = (daily_pnl / daily_starting_balance) * 100
        else:
            daily_pnl_percent = Decimal("0")

        return PnLMetrics(
            current_equity=self._current_equity,
            balance=self._balance,
            unrealized_pnl=unrealized_pnl,
            daily_pnl=daily_pnl,
            daily_pnl_percent=daily_pnl_percent,
            total_drawdown_percent=total_drawdown_percent,
            open_positions_count=len(self._positions),
        )

    def reset_daily(self, starting_balance: Decimal) -> None:
        """Reset daily P&L counters at midnight UTC.

        Args:
            starting_balance: Balance at start of new trading day
        """
        self._daily_realized_pnl = Decimal("0")
        self._balance = starting_balance
        logger.debug(f"Reset daily P&L for {self._account_id}, starting balance: {starting_balance}")
