"""Base trading strategy.

This module defines the BaseStrategy class which all trading strategies
must inherit from. It provides common functionality for signal generation,
position management, and order execution.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from nautilus_trader.core.message import Event
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide, PositionSide
from nautilus_trader.model.events import PositionClosed, PositionOpened
from nautilus_trader.trading.strategy import Strategy

from src.orders.signal import SignalType
from src.strategies.config import BaseStrategyConfig

if TYPE_CHECKING:
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
