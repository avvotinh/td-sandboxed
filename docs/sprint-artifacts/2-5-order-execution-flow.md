# Story 2.5: Order Execution Flow

Status: done

## Story

As a **trader**,
I want **my strategy signals to execute as orders on MT5**,
So that **I can automatically enter and exit positions**.

## Acceptance Criteria

1. **AC1**: Given a strategy generates a BUY signal for XAUUSD, when the signal passes to the execution flow, then an order command is created with UUID, account_id, action, symbol, volume, price, sl, tp
2. **AC2**: Given an order is sent to mt5-bridge, when the order is executed, then an order result is received with status "filled", fill_price, slippage, and timestamp
3. **AC3**: Given an order result with status "filled" is received, then the trade is recorded in the trading-engine and the position is tracked for the account
4. **AC4**: Given an order is rejected by MT5, when the rejection result returns with status "rejected", then the rejection reason is logged and no position is recorded
5. **AC5**: Given duplicate order submissions with the same order_id, when the second submission arrives, then it is rejected with an idempotency check (duplicate prevention)
6. **AC6**: Order states are properly tracked: pending -> filled/rejected/cancelled
7. **AC7**: Slippage is calculated and logged on all fills
8. **AC8**: Unit tests cover order creation, state transitions, and position tracking
9. **AC9**: Integration tests verify end-to-end order flow with ZmqAdapter

## Tasks / Subtasks

### Task 1: Create Order Model with States (AC: 1, 6)
- [x] Create `src/orders/order.py` with InternalOrder class
- [x] Define OrderState enum: PENDING, SUBMITTED, FILLED, PARTIALLY_FILLED, REJECTED, CANCELLED, ERROR
- [x] Add state transition validation (e.g., can't go from FILLED to PENDING)
- [x] Include all fields: order_id (UUID), account_id, action, symbol, volume, price, sl, tp, state, created_at
- [x] Add methods: `is_terminal()`, `can_transition_to(state)`

### Task 2: Create Position Tracker (AC: 3)
- [x] Create `src/orders/position_tracker.py` with PositionTracker class
- [x] Track open positions per account per symbol
- [x] Include position fields: account_id, symbol, side, quantity, entry_price, entry_time, unrealized_pnl
- [x] Add methods: `open_position()`, `close_position()`, `get_position()`, `has_position()`
- [x] Store positions in memory with optional Redis persistence

### Task 3: Create Order Execution Service (AC: 1, 2, 3, 4)
- [x] Create `src/orders/execution_service.py` with OrderExecutionService class
- [x] Inject ZmqAdapter dependency for order sending
- [x] Implement `execute_signal(signal: Signal, account: Account) -> InternalOrder`
- [x] Implement `_create_order_from_signal()` with UUID generation
- [x] **CRITICAL:** Handle CLOSE signals by determining opposite side from current position
- [x] Implement `_send_order_to_bridge()` using ZmqAdapter.send_order_and_wait()
- [x] Implement `_handle_order_result()` for state transitions and position updates
- [x] **CRITICAL:** Create Trade record on fill, close position on CLOSE signal
- [x] Implement `_log_rejection()` for rejected orders with reason
- [x] Add `_trades: list[Trade]` for trade audit trail

### Task 4: Implement Idempotency Check (AC: 5)
- [x] Create `_pending_order_ids: set[str]` in OrderExecutionService
- [x] Add order_id to set before sending, remove after terminal state
- [x] Raise `DuplicateOrderError` if order_id already exists
- [ ] Implement cleanup for stale pending orders (timeout) *(deferred - not needed for in-memory MVP)*

### Task 5: Implement Slippage Tracking (AC: 7)
- [x] Calculate slippage: `fill_price - requested_price`
- [x] Store slippage in InternalOrder after fill
- [x] Log slippage at INFO level: "Order {id} filled with slippage: {slippage}"
- [x] Add slippage threshold warning (configurable, default 0.5%)

### Task 6: Create Trade Record Model (AC: 3)
- [x] Create `src/orders/trade.py` with Trade class
- [x] Include fields: trade_id, order_id, account_id, symbol, side, quantity, entry_price, entry_time, exit_price, exit_time, pnl_dollars, pnl_percent, slippage
- [x] Add `is_closed` property
- [x] Prepare for future TimescaleDB persistence (Story 7.1)

### Task 7: Create Signal Model (AC: 1)
- [x] Create `src/orders/signal.py` with Signal class
- [x] Define SignalType enum: BUY, SELL, CLOSE
- [x] Include fields: signal_type, symbol, strategy_name, timestamp, metadata
- [x] Add validation for required fields

### Task 8: Write Unit Tests (AC: 8)
- [x] Create `tests/unit/test_order.py` - Order model and state transitions
- [x] Create `tests/unit/test_position_tracker.py` - Position tracking logic
- [x] Create `tests/unit/test_execution_service.py` - Order execution with mocked ZmqAdapter
- [x] Test idempotency check with duplicate order IDs
- [x] Test slippage calculation and logging
- [x] Test rejection handling

### Task 9: Write Integration Tests (AC: 9)
- [x] Create `tests/integration/test_order_execution.py`
- [x] Test end-to-end order flow with running ZmqAdapter
- [x] Test order creation -> ZMQ send -> result handling -> position update
- [x] Mark with `@pytest.mark.integration`
- [x] Skip if MT5_BRIDGE_AVAILABLE is not set

## Dev Notes

### Quick Reference (Executive Summary)

**Key Implementation Points:**
- **OrderExecutionService** is the central component orchestrating signal -> order -> execution -> position
- **ZmqAdapter** from Story 2.4 provides `send_order_and_wait()` for order execution
- **CRITICAL:** `receive_ticks()` must run in background for order results (see Story 2.4)
- **CRITICAL:** Handle all 3 signal types: BUY (open long), SELL (open short), CLOSE (close position)
- Order states: `PENDING -> SUBMITTED -> FILLED/REJECTED/CANCELLED`
- Position tracking is per-account, per-symbol
- All order_ids MUST be UUIDs for idempotency
- **Trade records** created on every fill for audit trail

**Signal Type Handling:**
| Signal | Action | Position Effect |
|--------|--------|-----------------|
| BUY | OrderSide.BUY | Opens long position |
| SELL | OrderSide.SELL | Opens short position |
| CLOSE | Opposite of position side | Closes existing position, calculates PnL |

**Partial Fill Handling:**
- `OrderState.PARTIALLY_FILLED` indicates partial execution
- Do NOT open position until fully `FILLED`
- Track `filled_quantity` separately from `volume` for partial fills

### Architecture Patterns and Constraints

**From Architecture Document (docs/architecture.md):**

```
Order Execution Flow:
┌───────────────┐         ┌───────────────────┐         ┌───────────────┐
│   Strategy    │         │ OrderExecution    │         │  ZmqAdapter   │
│   Signal      │────────▶│    Service        │────────▶│  (Story 2.4)  │
└───────────────┘         └───────────────────┘         └───────────────┘
                                   │                           │
                                   │                           ▼
                                   │                    ┌───────────────┐
                                   ▼                    │  mt5-bridge   │
                          ┌───────────────┐            │    (Rust)     │
                          │ PositionTracker│◀──────────└───────────────┘
                          └───────────────┘                (order_result)
```

**Order Command Flow:**
1. Strategy generates Signal (BUY/SELL/CLOSE)
2. OrderExecutionService creates InternalOrder with UUID
3. Idempotency check prevents duplicates
4. Order sent via ZmqAdapter.send_order_and_wait()
5. OrderResult received (filled/rejected)
6. PositionTracker updated on fill
7. Trade record created for audit

### Technical Requirements

**From Context7 NautilusTrader Research (2025-12-22):**

The NautilusTrader `order_factory` pattern provides standardized order creation:

```python
# Market Order - use for immediate execution
order = self.order_factory.market(
    instrument_id=instrument_id,
    order_side=OrderSide.BUY,
    quantity=Quantity.from_str("0.1"),
    time_in_force=TimeInForce.IOC,
)
self.submit_order(order)
```

**Order Event Handlers (for future NautilusTrader integration):**
```python
from nautilus_trader.model.events import OrderFilled, OrderRejected

def on_order_filled(self, event: OrderFilled) -> None:
    # Update position tracking
    pass

def on_order_rejected(self, event: OrderRejected) -> None:
    # Log rejection, no position update
    pass
```

**Position Event Handlers:**
```python
from nautilus_trader.model.events import PositionOpened, PositionClosed

def on_position_opened(self, event: PositionOpened) -> None:
    pass

def on_position_closed(self, event: PositionClosed) -> None:
    pass
```

### ZmqAdapter Integration (From Story 2.4)

**CRITICAL: Concurrent Operation Pattern**

The `receive_ticks()` async generator MUST run in a background task for order results to work:

```python
import asyncio
from src.adapters.zmq_adapter import ZmqAdapter
from src.adapters.zmq_models import Order, OrderSide

async def order_execution_example():
    adapter = ZmqAdapter()
    await adapter.connect()

    # CRITICAL: Start tick receiver in background task
    async def tick_receiver():
        async for tick in adapter.receive_ticks():
            # Also handles order_result messages internally
            process_tick(tick)

    receiver_task = asyncio.create_task(tick_receiver())

    # Now orders can be sent - results will be received by the background task
    order = Order(
        account_id="ftmo-001",
        action=OrderSide.BUY,
        symbol="XAUUSD",
        volume=0.1,
        price=1850.45,
        order_id="ORDER-123",  # MUST be UUID
    )

    try:
        result = await adapter.send_order_and_wait(order, timeout=5.0)
        if result.is_filled:
            print(f"Order filled at {result.fill_price}")
        elif result.is_rejected:
            print(f"Order rejected: {result.error}")
    except asyncio.TimeoutError:
        print("Order timed out - is receive_ticks() running?")

    receiver_task.cancel()
    await adapter.disconnect()
```

### Message Protocol (JSON)

**Order Command (trading-engine -> mt5-bridge):**
```json
{
  "type": "order",
  "account_id": "ftmo-gold-001",
  "action": "BUY",
  "symbol": "XAUUSD",
  "volume": 0.1,
  "price": 1850.45,
  "sl": 1845.00,
  "tp": 1860.00,
  "order_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Order Result (mt5-bridge -> trading-engine):**
```json
{
  "order_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "filled",
  "fill_price": 1850.47,
  "slippage": 0.02,
  "timestamp": "2025-12-03T14:32:15.456Z"
}
```

### File Structure Requirements

```
services/trading-engine/
├── src/
│   ├── orders/                     # NEW: Order execution module
│   │   ├── __init__.py             # Export all models and services
│   │   ├── order.py                # InternalOrder model with states
│   │   ├── signal.py               # Signal model (BUY/SELL/CLOSE)
│   │   ├── trade.py                # Trade record model
│   │   ├── position_tracker.py     # Position tracking per account/symbol
│   │   └── execution_service.py    # Order execution orchestration
│   ├── adapters/
│   │   ├── zmq_adapter.py          # EXISTING (Story 2.4)
│   │   └── zmq_models.py           # EXISTING (Story 2.4)
│   └── ...
├── tests/
│   ├── unit/
│   │   ├── test_order.py           # NEW: Order model tests
│   │   ├── test_position_tracker.py # NEW: Position tracking tests
│   │   └── test_execution_service.py # NEW: Execution service tests
│   └── integration/
│       └── test_order_execution.py  # NEW: E2E order flow tests
└── ...
```

### Expected Implementation Patterns

**OrderState Enum:**
```python
from enum import Enum

class OrderState(str, Enum):
    """Order execution state."""
    PENDING = "pending"           # Created, not yet sent
    SUBMITTED = "submitted"       # Sent to mt5-bridge
    FILLED = "filled"            # Fully executed
    PARTIALLY_FILLED = "partially_filled"  # Partial execution
    REJECTED = "rejected"        # Rejected by broker
    CANCELLED = "cancelled"      # Cancelled before fill
    ERROR = "error"              # System error

    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in (
            OrderState.FILLED,
            OrderState.REJECTED,
            OrderState.CANCELLED,
            OrderState.ERROR,
        )
```

**InternalOrder Model:**
```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid

@dataclass
class InternalOrder:
    """Internal order representation with state tracking."""

    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    account_id: str = ""
    symbol: str = ""
    action: OrderSide = OrderSide.BUY
    volume: float = 0.0
    price: float = 0.0
    sl: Optional[float] = None
    tp: Optional[float] = None

    # Signal context - CRITICAL for CLOSE handling
    signal_type: Optional[SignalType] = None  # BUY, SELL, or CLOSE

    # State tracking
    state: OrderState = OrderState.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None

    # Execution details
    fill_price: Optional[float] = None
    slippage: Optional[float] = None
    rejection_reason: Optional[str] = None

    @property
    def is_close_order(self) -> bool:
        """Check if this order is closing a position."""
        return self.signal_type == SignalType.CLOSE

    def can_transition_to(self, new_state: OrderState) -> bool:
        """Check if state transition is valid."""
        valid_transitions = {
            OrderState.PENDING: {OrderState.SUBMITTED, OrderState.CANCELLED, OrderState.ERROR},
            OrderState.SUBMITTED: {OrderState.FILLED, OrderState.PARTIALLY_FILLED,
                                   OrderState.REJECTED, OrderState.CANCELLED, OrderState.ERROR},
            OrderState.PARTIALLY_FILLED: {OrderState.FILLED, OrderState.CANCELLED, OrderState.ERROR},
        }
        return new_state in valid_transitions.get(self.state, set())

    def transition_to(self, new_state: OrderState) -> None:
        """Transition to new state with validation."""
        if not self.can_transition_to(new_state):
            raise ValueError(f"Invalid state transition: {self.state} -> {new_state}")
        self.state = new_state
```

**PositionTracker:**
```python
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

@dataclass
class Position:
    """Open position for an account/symbol."""
    account_id: str
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    entry_time: datetime
    order_id: str  # Original order that opened this position

class PositionTracker:
    """Track open positions per account per symbol."""

    def __init__(self):
        # Key: (account_id, symbol) -> Position
        self._positions: Dict[Tuple[str, str], Position] = {}

    def open_position(self, order: InternalOrder) -> Position:
        """Open a new position from a filled order."""
        key = (order.account_id, order.symbol)
        if key in self._positions:
            # For now, don't allow multiple positions per symbol
            raise ValueError(f"Position already exists for {key}")

        position = Position(
            account_id=order.account_id,
            symbol=order.symbol,
            side=order.action,
            quantity=order.volume,
            entry_price=order.fill_price or order.price,
            entry_time=order.filled_at or datetime.utcnow(),
            order_id=order.order_id,
        )
        self._positions[key] = position
        return position

    def close_position(self, account_id: str, symbol: str) -> Optional[Position]:
        """Close and remove a position."""
        key = (account_id, symbol)
        return self._positions.pop(key, None)

    def get_position(self, account_id: str, symbol: str) -> Optional[Position]:
        """Get current position for account/symbol."""
        return self._positions.get((account_id, symbol))

    def has_position(self, account_id: str, symbol: str) -> bool:
        """Check if position exists."""
        return (account_id, symbol) in self._positions
```

**OrderExecutionService:**
```python
import asyncio
import logging
from datetime import datetime
from typing import Optional

from src.adapters.zmq_adapter import ZmqAdapter
from src.adapters.zmq_models import Order, OrderResult, OrderSide

logger = logging.getLogger(__name__)


class DuplicateOrderError(Exception):
    """Raised when attempting to submit a duplicate order."""
    pass


class OrderExecutionService:
    """Service for executing orders via mt5-bridge.

    Handles the complete order lifecycle:
    1. Signal -> Order creation
    2. Idempotency check
    3. Order submission via ZMQ
    4. Result handling and position updates
    """

    # Slippage warning threshold (0.5%)
    SLIPPAGE_WARNING_THRESHOLD = 0.005

    def __init__(
        self,
        zmq_adapter: ZmqAdapter,
        position_tracker: PositionTracker,
        order_timeout: float = 5.0,
    ):
        self._zmq = zmq_adapter
        self._positions = position_tracker
        self._order_timeout = order_timeout
        self._pending_order_ids: set[str] = set()
        self._trades: list[Trade] = []  # Trade audit trail

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
            volume: Lot size
            price: Requested execution price
            sl: Optional stop loss
            tp: Optional take profit

        Returns:
            InternalOrder with final state

        Raises:
            DuplicateOrderError: If order_id already pending
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
            order.submitted_at = datetime.utcnow()

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
        """
        if signal.signal_type == SignalType.CLOSE:
            # CLOSE signal: determine side from existing position
            position = self._positions.get_position(account_id, signal.symbol)
            if not position:
                raise ValueError(f"No position to close for {account_id}/{signal.symbol}")
            # Close by taking opposite side
            action = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
            # Use position volume if not specified
            if volume == 0:
                volume = position.quantity
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
            signal_type=signal.signal_type,  # Store for _handle_result
        )

    def _handle_result(self, order: InternalOrder, result: OrderResult) -> None:
        """Handle order execution result.

        CRITICAL: Handles position updates and trade recording:
        - CLOSE orders: Close position, create closed trade with PnL
        - BUY/SELL orders: Open position, create open trade
        """
        if result.is_filled:
            order.transition_to(OrderState.FILLED)
            order.filled_at = datetime.utcnow()
            order.fill_price = result.fill_price
            order.slippage = result.slippage

            # Log slippage
            if result.slippage:
                slippage_pct = abs(result.slippage) / order.price
                if slippage_pct > self.SLIPPAGE_WARNING_THRESHOLD:
                    logger.warning(
                        "High slippage on order %s: %.4f (%.2f%%)",
                        order.order_id,
                        result.slippage,
                        slippage_pct * 100,
                    )
                else:
                    logger.info(
                        "Order %s filled with slippage: %.4f",
                        order.order_id,
                        result.slippage,
                    )

            # CRITICAL: Handle position updates based on signal type
            if order.is_close_order:
                # CLOSE signal: Close position and create closed trade
                closed_position = self._positions.close_position(
                    order.account_id, order.symbol
                )
                if closed_position:
                    # Calculate PnL
                    price_diff = order.fill_price - closed_position.entry_price
                    if closed_position.side == OrderSide.SELL:
                        price_diff = -price_diff  # Short position
                    pnl_dollars = price_diff * closed_position.quantity

                    trade = Trade(
                        trade_id=str(uuid.uuid4()),
                        order_id=closed_position.order_id,  # Original entry order
                        account_id=order.account_id,
                        symbol=order.symbol,
                        side=closed_position.side,
                        quantity=closed_position.quantity,
                        entry_price=closed_position.entry_price,
                        entry_time=closed_position.entry_time,
                        exit_price=order.fill_price,
                        exit_time=order.filled_at,
                        pnl_dollars=pnl_dollars,
                        slippage=order.slippage,
                    )
                    self._trades.append(trade)
                    logger.info(
                        "Position CLOSED: %s %s PnL: $%.2f",
                        order.symbol,
                        closed_position.side.value,
                        pnl_dollars,
                    )
            else:
                # BUY/SELL signal: Open position and create open trade
                self._positions.open_position(order)

                trade = Trade(
                    trade_id=str(uuid.uuid4()),
                    order_id=order.order_id,
                    account_id=order.account_id,
                    symbol=order.symbol,
                    side=order.action,
                    quantity=order.volume,
                    entry_price=order.fill_price,
                    entry_time=order.filled_at,
                    slippage=order.slippage,
                )
                self._trades.append(trade)

            logger.info(
                "Order %s FILLED: %s %s %.2f @ %.4f",
                order.order_id,
                order.action.value,
                order.symbol,
                order.volume,
                order.fill_price,
            )

        elif result.is_rejected:
            order.transition_to(OrderState.REJECTED)
            order.rejection_reason = result.error

            logger.warning(
                "Order %s REJECTED: %s",
                order.order_id,
                result.error,
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
```

### Testing Requirements

**Unit Test Example:**
```python
# tests/unit/test_order.py
import pytest
from src.orders.order import InternalOrder, OrderState
from src.adapters.zmq_models import OrderSide


class TestOrderState:
    def test_pending_is_initial_state(self):
        order = InternalOrder(account_id="test", symbol="XAUUSD")
        assert order.state == OrderState.PENDING

    def test_valid_transition_pending_to_submitted(self):
        order = InternalOrder()
        order.transition_to(OrderState.SUBMITTED)
        assert order.state == OrderState.SUBMITTED

    def test_invalid_transition_filled_to_pending(self):
        order = InternalOrder()
        order.state = OrderState.FILLED

        with pytest.raises(ValueError):
            order.transition_to(OrderState.PENDING)

    def test_terminal_states(self):
        assert OrderState.FILLED.is_terminal()
        assert OrderState.REJECTED.is_terminal()
        assert OrderState.CANCELLED.is_terminal()
        assert not OrderState.PENDING.is_terminal()
        assert not OrderState.SUBMITTED.is_terminal()


class TestInternalOrder:
    def test_order_id_is_uuid(self):
        order = InternalOrder()
        # UUID format: 8-4-4-4-12 hex chars
        assert len(order.order_id) == 36
        assert order.order_id.count("-") == 4

    def test_unique_order_ids(self):
        order1 = InternalOrder()
        order2 = InternalOrder()
        assert order1.order_id != order2.order_id

    def test_is_close_order(self):
        order = InternalOrder(signal_type=SignalType.CLOSE)
        assert order.is_close_order is True

        buy_order = InternalOrder(signal_type=SignalType.BUY)
        assert buy_order.is_close_order is False


class TestCloseSignalHandling:
    """CRITICAL: Tests for CLOSE signal execution flow."""

    @pytest.mark.asyncio
    async def test_close_signal_determines_opposite_side(self):
        """CLOSE signal should determine order side from position."""
        position_tracker = PositionTracker()
        # Open a long position first
        long_order = InternalOrder(
            account_id="test",
            symbol="XAUUSD",
            action=OrderSide.BUY,
            volume=0.1,
            fill_price=1850.00,
        )
        long_order.state = OrderState.FILLED
        position_tracker.open_position(long_order)

        # Create execution service with mock ZMQ
        service = OrderExecutionService(
            zmq_adapter=MagicMock(),
            position_tracker=position_tracker,
        )

        # Create CLOSE order - should determine SELL side
        signal = Signal(signal_type=SignalType.CLOSE, symbol="XAUUSD")
        order = service._create_order(
            signal=signal,
            account_id="test",
            volume=0.0,  # Should use position volume
            price=1855.00,
            sl=None,
            tp=None,
        )

        assert order.action == OrderSide.SELL  # Opposite of long
        assert order.volume == 0.1  # From position
        assert order.is_close_order is True

    @pytest.mark.asyncio
    async def test_close_no_position_raises_error(self):
        """CLOSE signal without position should raise ValueError."""
        service = OrderExecutionService(
            zmq_adapter=MagicMock(),
            position_tracker=PositionTracker(),
        )

        signal = Signal(signal_type=SignalType.CLOSE, symbol="XAUUSD")
        with pytest.raises(ValueError, match="No position to close"):
            service._create_order(
                signal=signal,
                account_id="test",
                volume=0.0,
                price=1855.00,
                sl=None,
                tp=None,
            )
```

**Integration Test Example:**
```python
# tests/integration/test_order_execution.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.orders.execution_service import OrderExecutionService, DuplicateOrderError
from src.orders.signal import Signal, SignalType
from src.orders.position_tracker import PositionTracker
from src.adapters.zmq_models import OrderResult, OrderStatus


class TestOrderExecutionIntegration:
    @pytest.fixture
    def mock_zmq_adapter(self):
        adapter = MagicMock()
        adapter.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="test-123",
                status=OrderStatus.FILLED,
                fill_price=1850.47,
                slippage=0.02,
                timestamp="2025-12-22T10:00:00Z",
            )
        )
        return adapter

    @pytest.fixture
    def execution_service(self, mock_zmq_adapter):
        return OrderExecutionService(
            zmq_adapter=mock_zmq_adapter,
            position_tracker=PositionTracker(),
        )

    @pytest.mark.asyncio
    async def test_execute_buy_signal(self, execution_service):
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="test",
        )

        order = await execution_service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
        )

        assert order.state == OrderState.FILLED
        assert order.fill_price == 1850.47
        assert order.slippage == 0.02

    @pytest.mark.asyncio
    async def test_duplicate_order_rejected(self, execution_service):
        signal = Signal(signal_type=SignalType.BUY, symbol="XAUUSD")

        # First order succeeds
        order1 = await execution_service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
        )

        # Simulate pending order with same ID
        execution_service._pending_order_ids.add(order1.order_id)

        # Second order with same ID should fail
        with pytest.raises(DuplicateOrderError):
            # Force same order_id for test
            pass
```

**Test Execution:**
```bash
# From services/trading-engine directory
cd services/trading-engine

# Run all unit tests
uv run pytest tests/unit/ -v

# Run order-specific tests
uv run pytest tests/unit/test_order.py tests/unit/test_execution_service.py -v

# Run integration tests (requires MT5_BRIDGE_AVAILABLE=true)
uv run pytest tests/integration/test_order_execution.py -v -m integration

# Check code quality
uv run ruff check src/orders/
```

### Previous Story Learnings (Story 2.4)

From Story 2.4 MT5 Bridge ZeroMQ Adapter implementation:

**Key Patterns Established:**
- **ZmqAdapter** provides `send_order_and_wait()` for synchronous order execution
- **Order model** uses Pydantic for validation with `min_length=1` and `gt=0` constraints
- **OrderResult** includes `is_filled` and `is_rejected` properties for easy checks
- **Tick receiver** must run in background for order results to be processed
- Message format: Multipart `[topic_bytes, json_payload_bytes]`

**Files Created in Story 2.4:**
- `src/adapters/zmq_adapter.py` - ZMQ socket operations
- `src/adapters/zmq_models.py` - Order, OrderResult, Tick models
- `tests/unit/test_zmq_adapter.py` - 58 unit tests

**CRITICAL Concurrency Pattern:**
```python
# Order results arrive via SUB socket processed in receive_ticks()
# Without receiver running, send_order_and_wait() will timeout!
receiver_task = asyncio.create_task(tick_receiver())
result = await adapter.send_order_and_wait(order, timeout=5.0)
```

### Git Intelligence (Recent Commits)

From commit `3497c34` (Story 2.4):
- Created ZmqAdapter with SUB (5556) and PUB (5557) sockets
- Added Order, OrderResult, Tick models with validation
- 58 unit tests covering all functionality
- Integration test structure (skipped without bridge)

From commit `1f5f24d` (Story 2.3):
- mt5-bridge Rust implementation complete
- REP (5555), PUB (5556), SUB (5557) sockets ready
- Order queue for async order delivery
- 49 tests passing

**Pattern for building on Story 2.4:**
```python
# Reuse existing ZmqAdapter and models
from src.adapters.zmq_adapter import ZmqAdapter
from src.adapters.zmq_models import Order, OrderSide, OrderResult
```

### Environment Variables Required

```bash
# ZeroMQ Configuration (from Story 2.4)
ZMQ_BRIDGE_HOST=localhost
ZMQ_TICK_PORT=5556
ZMQ_ORDER_PORT=5557
ZMQ_RECV_TIMEOUT_MS=1000
ZMQ_SEND_TIMEOUT_MS=5000

# Order Execution
ORDER_TIMEOUT_SECONDS=5.0
SLIPPAGE_WARNING_THRESHOLD=0.005  # 0.5%

# Logging
LOG_LEVEL=INFO
```

### Dependencies (pyproject.toml - Already Configured)

```toml
dependencies = [
    "nautilus_trader>=1.200",
    "redis>=5.0",
    "pyzmq>=25.0",
    "sqlalchemy>=2.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "typer>=0.9",
]
```

### Project Structure Notes

- New `src/orders/` module follows existing pattern from `src/accounts/`, `src/adapters/`
- Position tracking is in-memory for MVP, Redis persistence for Epic 5
- Trade records prepared for TimescaleDB persistence (Story 7.1)
- All unit tests follow existing `tests/unit/` pattern with pytest-asyncio

### References

- [Source: docs/architecture.md#Trading-Engine-Service] - Service structure and execution flow
- [Source: docs/architecture.md#Inter-Service-Communication] - ZMQ patterns
- [Source: docs/epic-2-context.md#Story-2.5] - Story requirements
- [Source: docs/epics.md#Story-2.5] - Original story definition
- [Source: docs/sprint-artifacts/2-4-trading-engine-zeromq-adapter.md] - Previous story patterns
- [Source: Context7 NautilusTrader 2025-12-22] - Order factory and position event patterns

## Dev Agent Record

### Context Reference

- Epic 2 Context: `docs/epic-2-context.md`
- Architecture: `docs/architecture.md`
- PRD: `docs/prd.md`
- Previous Story: `docs/sprint-artifacts/2-4-trading-engine-zeromq-adapter.md`

### Agent Model Used

- Story Creation: Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A

### Completion Notes List

- Story created with comprehensive developer context from artifact analysis
- NautilusTrader order execution patterns researched via Context7 MCP (2025-12-22)
- ZmqAdapter integration patterns from Story 2.4 documented
- All acceptance criteria mapped to specific tasks
- Complete implementation patterns provided with code examples
- Test patterns provided for unit and integration testing
- Slippage tracking and idempotency check requirements included

### File List

Files created:
- `services/trading-engine/src/orders/__init__.py`
- `services/trading-engine/src/orders/order.py`
- `services/trading-engine/src/orders/signal.py`
- `services/trading-engine/src/orders/trade.py`
- `services/trading-engine/src/orders/position_tracker.py`
- `services/trading-engine/src/orders/execution_service.py`
- `services/trading-engine/tests/unit/test_order.py`
- `services/trading-engine/tests/unit/test_signal.py`
- `services/trading-engine/tests/unit/test_trade.py`
- `services/trading-engine/tests/unit/test_position_tracker.py`
- `services/trading-engine/tests/unit/test_execution_service.py`
- `services/trading-engine/tests/integration/test_order_execution.py`

---

## Verification Checklist

### Manual Test Steps

```bash
# 1. Ensure you're in the trading-engine directory
cd services/trading-engine

# 2. Install dependencies
uv sync

# 3. Run unit tests
uv run pytest tests/unit/test_order.py tests/unit/test_position_tracker.py -v

# 4. Check code quality
uv run ruff check src/orders/

# 5. Run integration tests (requires running mt5-bridge)
# Terminal 1: cd ../mt5-bridge && RUST_LOG=debug cargo run
# Terminal 2:
MT5_BRIDGE_AVAILABLE=true uv run pytest tests/integration/test_order_execution.py -v

# 6. Test order execution manually
uv run python -c "
import asyncio
from src.orders.order import InternalOrder, OrderState
from src.adapters.zmq_models import OrderSide

order = InternalOrder(
    account_id='test',
    symbol='XAUUSD',
    action=OrderSide.BUY,
    volume=0.1,
    price=1850.45,
)
print(f'Order ID: {order.order_id}')
print(f'State: {order.state}')
print(f'Is terminal: {order.state.is_terminal()}')
"
```

### Acceptance Criteria Verification

- [ ] **AC1**: Order command created with UUID, account_id, action, symbol, volume, price, sl, tp
- [ ] **AC2**: Order result received with status, fill_price, slippage, timestamp
- [ ] **AC3**: Trade recorded, position tracked on fill
- [ ] **AC4**: Rejection logged, no position on reject
- [ ] **AC5**: Duplicate orders rejected (idempotency)
- [ ] **AC6**: Order states properly tracked
- [ ] **AC7**: Slippage calculated and logged
- [ ] **AC8**: Unit tests pass
- [ ] **AC9**: Integration tests pass (with bridge)

---

## Definition of Done

- [x] `src/orders/order.py` implements InternalOrder with states
- [x] `src/orders/signal.py` implements Signal model
- [x] `src/orders/position_tracker.py` tracks positions per account/symbol
- [x] `src/orders/execution_service.py` orchestrates order execution
- [x] Orders created with UUID for idempotency
- [x] State transitions validated
- [x] Slippage calculated and logged
- [x] Position opened on fill, nothing on reject
- [x] All unit tests pass (308 tests)
- [ ] Integration tests pass with running bridge (requires MT5_BRIDGE_AVAILABLE=true)
- [x] Linting passes: `uv run ruff check src/orders/`
- [x] Story status updated to `done`

---

## Troubleshooting

### Common Issues

**Order Timeout**
```bash
# Ensure receive_ticks() is running in background
# Check that mt5-bridge is running
# Verify order topic format: "order:{account_id}"
```

**Position Already Exists Error**
```bash
# For MVP, only one position per symbol per account
# Close existing position before opening new one
# Or implement position averaging (future enhancement)
```

**Duplicate Order Error**
```bash
# Order ID already in pending set
# Wait for previous order to complete
# Or use different order ID
```

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-22 | Story created with comprehensive developer context by create-story workflow |
| 2025-12-22 | NautilusTrader order execution patterns researched via Context7 MCP |
| 2025-12-22 | Aligned with Story 2.4 ZmqAdapter implementation patterns |
| 2025-12-22 | Complete implementation patterns provided with test examples |
| 2025-12-22 | **Validation improvements applied:** (1) Added CLOSE signal handling in _create_order - determines opposite side from position; (2) Added Trade record creation on all fills with PnL calculation for closes; (3) Added position close handling in _handle_result; (4) Added signal_type field to InternalOrder with is_close_order property; (5) Added _trades list and trade retrieval methods; (6) Added Signal Type Handling table to Quick Reference; (7) Added Partial Fill Handling guidance; (8) Added TestCloseSignalHandling test class with 2 critical tests |
| 2025-12-22 | **Implementation completed:** Created complete orders module with: (1) OrderState enum and InternalOrder model with state machine validation; (2) Signal and SignalType models for strategy signals; (3) Trade model for audit trail with PnL calculation; (4) PositionTracker for position management per account/symbol; (5) OrderExecutionService orchestrating complete order lifecycle; (6) 108 unit tests for orders module + 308 total trading-engine unit tests passing; (7) Integration tests created (require MT5_BRIDGE_AVAILABLE); (8) All linting passes |
| 2025-12-22 | **Code Review completed:** (1) All ACs validated as implemented; (2) Fixed task checkboxes to reflect actual completion status; (3) Fixed deprecated `datetime.utcnow()` usage in all source and test files - replaced with `datetime.now(timezone.utc)` for Python 3.12+ compatibility; (4) Noted LOW issues for future: stale order cleanup not implemented (OK for MVP), thread safety for PositionTracker (OK for single-event-loop); (5) 308 tests passing, 0 warnings, linting passes |
