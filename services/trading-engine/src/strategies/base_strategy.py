"""Base trading strategy.

This module defines the BaseStrategy class which all trading strategies
must inherit from. It provides common functionality for signal generation,
position management, and order execution.
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from nautilus_trader.core.message import Event
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide, OrderType, PositionSide
from nautilus_trader.model.events import PositionClosed, PositionOpened
from nautilus_trader.trading.strategy import Strategy

from src.orders.signal import SignalType
from src.strategies.config import BaseStrategyConfig
from src.strategies.mixins.atr_stop_mixin import ATRStopMixin
from src.strategies.mixins.session_filter_mixin import SessionFilterMixin

if TYPE_CHECKING:
    from nautilus_trader.model.orders.list import OrderList
    from nautilus_trader.model.position import Position


class BaseStrategy(Strategy):
    """Base class for all trading strategies.

    Provides common functionality for signal generation, position
    management, and order execution. Subclasses must implement
    the `generate_signal()` method.

    Lifecycle:
        on_start() -> subscribe_bars() -> [bars arrive] -> on_bar()
        -> generate_signal() -> submit_order()
        -> on_event() <- PositionOpened/PositionClosed

    Example:
        class MyStrategy(BaseStrategy):
            def generate_signal(self, bar: Bar) -> SignalType:
                if some_condition:
                    return SignalType.BUY
                return SignalType.NONE
    """

    def __init__(self, config: BaseStrategyConfig) -> None:
        """Initialize the strategy.

        Args:
            config: Strategy configuration with instrument, bar type, trade size
        """
        super().__init__(config)  # CRITICAL: Initialize parent
        self._position: Position | None = None
        self._instrument = None

    # Position state properties (AC1, Task 4)
    @property
    def is_flat(self) -> bool:
        """Check if no position is open.

        Returns:
            True if no position is currently open
        """
        return self._position is None

    @property
    def is_long(self) -> bool:
        """Check if long position is open.

        Returns:
            True if a long position is currently open
        """
        return self._position is not None and self._position.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        """Check if short position is open.

        Returns:
            True if a short position is currently open
        """
        return self._position is not None and self._position.side == PositionSide.SHORT

    @property
    def position(self) -> Position | None:
        """Current open position, if any.

        Returns:
            The current Position or None if flat
        """
        return self._position

    @property
    def instrument(self):
        """Cached instrument reference.

        Returns:
            The instrument being traded
        """
        return self._instrument

    @property
    def account(self):
        """Reference to the account this strategy runs on.

        Returns:
            The account ID from the strategy configuration
        """
        return self.config.account_id

    # Lifecycle methods (AC1, Task 3)
    def on_start(self) -> None:
        """Called when strategy starts.

        Sets up instrument reference and subscribes to bar data.
        Subclasses can override to add indicator registration.
        """
        # Get instrument reference
        self._instrument = self.cache.instrument(self.config.instrument_id)
        if self._instrument is None:
            self._log.error(f"Instrument not found: {self.config.instrument_id}")
            self.stop()
            return

        # Subscribe to bar data
        self.subscribe_bars(self.config.bar_type)
        self._log.info(f"Strategy {self.id} started, subscribed to {self.config.bar_type}")

    def on_stop(self) -> None:
        """Called when strategy stops.

        Unsubscribes from bar data and cleans up.
        """
        self.unsubscribe_bars(self.config.bar_type)
        self._log.info(f"Strategy {self.id} stopped")

    def on_bar(self, bar: Bar) -> None:
        """Process incoming bar data.

        Calls generate_signal and executes if signal is not NONE.

        Args:
            bar: The incoming bar data
        """
        signal = self.generate_signal(bar)
        if signal != SignalType.NONE:
            self._execute_signal(signal)

    def on_tick(self, tick) -> None:
        """Process incoming tick data.

        Override in subclass to handle tick data.
        Default implementation does nothing.

        Args:
            tick: The incoming tick data
        """
        pass

    def on_event(self, event: Event) -> None:
        """Handle position events.

        Updates internal position state when positions are opened/closed.

        Args:
            event: The event to handle
        """
        if isinstance(event, PositionOpened):
            self._position = self.cache.position(event.position_id)
            self._log.info(
                f"Position opened: {self._position.side} @ {self._position.avg_px_open}"
            )
        elif isinstance(event, PositionClosed):
            if self._position and self._position.id == event.position_id:
                pnl = self._position.realized_pnl
                self._log.info(f"Position closed with PnL: {pnl}")
                self._position = None

    # Abstract method for subclasses (AC1)
    @abstractmethod
    def generate_signal(self, bar: Bar) -> SignalType:
        """Generate trading signal from bar data.

        Must be implemented by subclasses to define strategy logic.

        Args:
            bar: Latest bar data

        Returns:
            SignalType indicating action (BUY, SELL, CLOSE, or NONE)
        """
        raise NotImplementedError

    def get_position_size(self, signal: SignalType) -> float:
        """Get position size for a signal.

        Override in subclass for dynamic position sizing.
        Default returns the configured trade size.

        Args:
            signal: The signal type (BUY, SELL, CLOSE)

        Returns:
            Position size as a float
        """
        return float(self.config.trade_size)

    # Signal execution (AC3, Task 5)
    def _execute_signal(self, signal: SignalType) -> None:
        """Execute trading signal.

        Routes signal to appropriate order creation method.

        Args:
            signal: The signal to execute
        """
        if signal == SignalType.BUY:
            self._go_long()
        elif signal == SignalType.SELL:
            self._go_short()
        elif signal == SignalType.CLOSE:
            self._close_position()

    def _go_long(self) -> None:
        """Enter long position.

        Creates and submits a market buy order if currently flat.
        """
        if not self.is_flat:
            return

        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self._instrument.make_qty(self.get_position_size(SignalType.BUY)),
        )
        self.submit_order(order)
        self._log.info(f"Going LONG with {self.config.trade_size}")

    def _go_short(self) -> None:
        """Enter short position.

        Creates and submits a market sell order if currently flat.
        """
        if not self.is_flat:
            return

        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=self._instrument.make_qty(self.get_position_size(SignalType.SELL)),
        )
        self.submit_order(order)
        self._log.info(f"Going SHORT with {self.config.trade_size}")

    def _close_position(self) -> None:
        """Close current position.

        Closes all positions for the configured instrument.
        """
        if self._position:
            self.close_all_positions(self.config.instrument_id)
            self._log.info("Closing position")

    # --- Epic 8 helpers ----------------------------------------------------

    def _calculate_atr_stop(
        self,
        side: OrderSide,
        entry_price: Decimal,
        atr_value: Decimal,
        multiplier: Decimal,
    ) -> Decimal:
        """Convenience: ATR-based stop-loss price (delegates to ATRStopMixin)."""
        return ATRStopMixin.calculate_atr_stop(
            side=side,
            entry_price=entry_price,
            atr_value=atr_value,
            multiplier=multiplier,
        )

    def _in_session(
        self,
        ts: datetime,
        session_start: time,
        session_end: time,
        tz: str = "UTC",
    ) -> bool:
        """Convenience: trading-session predicate (delegates to SessionFilterMixin)."""
        return SessionFilterMixin.in_session(
            ts=ts,
            session_start=session_start,
            session_end=session_end,
            tz=tz,
        )

    def _build_bracket_args(
        self,
        side: OrderSide,
        quantity: Decimal,
        sl_price: Decimal,
        tp_price: Decimal,
    ) -> dict[str, Any]:
        """Build kwargs for ``OrderFactory.bracket()``.

        Pure: validates SL/TP placement vs. side, quantity > 0, and converts
        Decimal inputs to instrument-correct Quantity/Price via the cached
        instrument's ``make_qty`` / ``make_price``.
        """
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        if side == OrderSide.BUY and sl_price >= tp_price:
            raise ValueError(
                f"sl_price ({sl_price}) must be below tp_price ({tp_price}) for LONG"
            )
        if side == OrderSide.SELL and sl_price <= tp_price:
            raise ValueError(
                f"sl_price ({sl_price}) must be above tp_price ({tp_price}) for SHORT"
            )

        return {
            "instrument_id": self.config.instrument_id,
            "order_side": side,
            "quantity": self._instrument.make_qty(quantity),
            "entry_order_type": OrderType.MARKET,
            "sl_order_type": OrderType.STOP_MARKET,
            "tp_order_type": OrderType.LIMIT,
            "sl_trigger_price": self._instrument.make_price(sl_price),
            "tp_price": self._instrument.make_price(tp_price),
        }

    def _submit_bracket_order(
        self,
        side: OrderSide,
        quantity: Decimal,
        sl_price: Decimal,
        tp_price: Decimal,
    ) -> OrderList | None:
        """Submit a market bracket order (entry + linked SL + linked TP).

        Returns ``None`` (no submission) when:
        - a position is already open (``is_flat`` is False), or
        - ``quantity`` is non-positive (sizer signalled "cannot size safely").

        Callers can treat skipping as a normal outcome rather than an error.
        """
        if not self.is_flat:
            self._log.debug(
                "Skipping bracket submission — position already open"
            )
            return None
        if quantity <= 0:
            self._log.warning(
                f"Skipping bracket submission — non-positive quantity ({quantity}); "
                "sizer likely rejected the trade"
            )
            return None

        args = self._build_bracket_args(side, quantity, sl_price, tp_price)
        order_list = self._submit_bracket_via_factory(args)
        self._log.info(
            f"Bracket {side.name} qty={quantity} SL={sl_price} TP={tp_price}"
        )
        return order_list

    def _submit_bracket_via_factory(self, args: dict[str, Any]) -> OrderList:
        """Build the bracket OrderList via ``order_factory`` and submit it.

        Encapsulates the two Nautilus Cython calls so tests can patch this
        single seam without needing a live ``TradingNode``.
        """
        order_list = self.order_factory.bracket(**args)
        self.submit_order_list(order_list)
        return order_list

    # --- Epic 13 helpers (Phase 1: scale-out + trail) ---------------------
    #
    # Seam parameters (`Any` on Order / Quantity / Price) are intentional:
    # Nautilus Cython types do not participate in mypy's type graph, and
    # importing them just for annotation noise here adds no safety. When
    # mypy is wired into CI a follow-up can replace `Any` with Protocol
    # stubs covering the .order_type / .as_double / etc. surfaces we use.
    # TODO(mypy): replace Any with Protocol stubs once mypy is on.

    def _close_partial(self, fraction: Decimal) -> Any | None:
        """Close ``fraction`` of the current position via reduce-only market.

        Defensive cap: ``min(qty * fraction, qty - lot_step)`` prevents
        over-close caused by lot-rounding edges (e.g., target=0.999*1.0
        rounds up to a full close on coarse instruments). Implementation
        plan §2.2.

        Returns:
            The submitted Order, or ``None`` if flat / position too small
            for the cap to leave anything open.

        Raises:
            ValueError: if ``fraction`` is not in ``(0, 1)`` — closing 0
                is a no-op disguised as an order, closing >= 1 belongs in
                ``_close_position`` which uses the bracket-aware path.
        """
        if not (Decimal("0") < fraction < Decimal("1")):
            raise ValueError(
                f"fraction must be in (0, 1), got {fraction}"
            )
        if self._position is None:
            self._log.warning("_close_partial called while flat — no-op")
            return None

        current_qty = Decimal(str(self._position.quantity.as_double()))
        lot_step = Decimal(str(self._instrument.size_increment.as_double()))

        target_qty = current_qty * fraction
        # Subtract one lot step so the partial close cannot over-shoot
        # the position when the instrument's volume_step coarsens
        # ``target_qty`` upward at make_qty time.
        safe_max = current_qty - lot_step
        qty_to_close = min(target_qty, safe_max)

        if qty_to_close <= 0:
            self._log.warning(
                f"_close_partial skipped — current_qty={current_qty} "
                f"below lot_step={lot_step}; nothing to close partially"
            )
            return None

        side = (
            OrderSide.SELL
            if self._position.side == PositionSide.LONG
            else OrderSide.BUY
        )
        quantity = self._instrument.make_qty(qty_to_close)
        order = self._submit_market_reduce_only_via_factory(
            side=side, quantity=quantity
        )
        self._log.info(
            f"Partial close {fraction} of {current_qty} → {qty_to_close} "
            f"({side.name}, reduce_only=True)"
        )
        return order

    def _submit_market_reduce_only_via_factory(
        self, *, side: OrderSide, quantity: Any
    ) -> Any:
        """Build + submit a reduce-only market order. Tests patch this seam.

        Wraps the two Nautilus Cython calls (``order_factory.market`` +
        ``submit_order``) so unit tests can patch this single Python
        method instead of mocking ``Actor.cache`` (read-only).
        """
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=side,
            quantity=quantity,
            reduce_only=True,
        )
        self.submit_order(order)
        return order

    def _query_open_orders(self) -> list[Any]:
        """Return open orders for this strategy's instrument. Test seam.

        ``self.cache`` is read-only on Nautilus Actor — tests cannot
        replace it. Delegating through this helper lets tests stub a
        deterministic order list while the live path queries the cache.
        """
        return list(
            self.cache.orders_open(instrument_id=self.config.instrument_id)
        )

    def _find_active_sl_order(self) -> Any | None:
        """Locate the active STOP_MARKET (SL) order on this instrument.

        Returns the first match. Phase 1 strategies are single-fill, so
        a strategy should never be in a state with two SL orders active
        for the same position simultaneously — if that ever happens, the
        first-match policy keeps Phase 1 deterministic and the WARNING
        log leaves a breadcrumb for Phase 2 (multi-leg / scaled-in)
        debugging.
        """
        matches = [
            o for o in self._query_open_orders()
            if o.order_type == OrderType.STOP_MARKET
        ]
        if len(matches) > 1:
            self._log.warning(
                f"_find_active_sl_order: {len(matches)} STOP_MARKET orders "
                "found on instrument; taking first (Phase 1 single-fill "
                "should never produce multiple SLs)"
            )
        return matches[0] if matches else None

    def _modify_sl(self, new_sl_price: Decimal) -> bool:
        """Atomic SL modify via Nautilus ``Strategy.modify_order``.

        Backtest path: ``BacktestExecutionClient`` updates the order
        in-memory atomically. Live path: routes through
        ``ZmqExecutionClient._modify_order`` which currently raises
        ``NotImplementedError`` — Epic 14 unblocks this; until then,
        Epic 13 ships backtest-only.

        Returns:
            ``True`` if an SL was found and the modify request was
            issued; ``False`` if no STOP_MARKET order exists on this
            instrument.
        """
        sl_order = self._find_active_sl_order()
        if sl_order is None:
            self._log.warning("_modify_sl: no active SL order found")
            return False

        new_price = self._instrument.make_price(new_sl_price)
        self._modify_sl_order_via_strategy(
            sl_order=sl_order, trigger_price=new_price
        )
        self._log.info(f"Modified SL trigger to {new_sl_price}")
        return True

    def _modify_sl_order_via_strategy(
        self, *, sl_order: Any, trigger_price: Any
    ) -> None:
        """Call Nautilus ``Strategy.modify_order``. Tests patch this seam."""
        self.modify_order(order=sl_order, trigger_price=trigger_price)
