"""Moving Average Crossover strategy.

This module implements a Moving Average Crossover strategy using
Exponential Moving Averages (EMA). The strategy generates BUY signals
on bullish crossovers (fast > slow) and SELL signals on bearish
crossovers (fast < slow).
"""

from __future__ import annotations

from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.orders.signal import SignalType
from src.strategies.base_strategy import BaseStrategy
from src.strategies.config import BaseStrategyConfig
from src.regime.states import RegimeState
from src.strategies.registry import register_strategy


class MACrossoverConfig(BaseStrategyConfig, frozen=True, kw_only=True):
    """Configuration for MA Crossover strategy.

    Attributes:
        fast_period: Period for fast EMA (default 20)
        slow_period: Period for slow EMA (default 50, must be > fast_period)
    """

    fast_period: int = 20
    slow_period: int = 50

    def __post_init__(self) -> None:
        """Validate configuration after initialization.

        Raises:
            ValueError: If periods are non-positive or slow_period <= fast_period.
        """
        if self.fast_period <= 0:
            raise ValueError(
                f"fast_period must be positive, got {self.fast_period}"
            )
        if self.slow_period <= 0:
            raise ValueError(
                f"slow_period must be positive, got {self.slow_period}"
            )
        if self.slow_period <= self.fast_period:
            raise ValueError(
                f"slow_period ({self.slow_period}) must be > fast_period ({self.fast_period})"
            )


@register_strategy(
    "ma_crossover",
    regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN],
)
class MACrossoverStrategy(BaseStrategy):
    """Moving Average Crossover strategy.

    Generates BUY signal on bullish crossover (fast crosses above slow),
    SELL signal on bearish crossover (fast crosses below slow).

    This strategy includes position reversal support - when a signal is
    generated in the opposite direction of an existing position, the
    existing position is closed and a new position is immediately opened.

    Example:
        config = MACrossoverConfig(
            instrument_id=instrument_id,
            bar_type=bar_type,
            fast_period=20,
            slow_period=50,
        )
        strategy = MACrossoverStrategy(config)
    """

    def __init__(self, config: MACrossoverConfig) -> None:
        """Initialize the MA Crossover strategy.

        Args:
            config: Strategy configuration with EMA periods
        """
        super().__init__(config)
        # Initialize EMA indicators
        self.fast_ema = ExponentialMovingAverage(config.fast_period)
        self.slow_ema = ExponentialMovingAverage(config.slow_period)
        # Track previous values for crossover detection
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None

    def on_start(self) -> None:
        """Called when strategy starts.

        Sets up instrument reference, subscribes to bars, and registers
        EMA indicators for automatic updates.
        """
        super().on_start()  # Sets instrument, subscribes to bars

        # Register indicators BEFORE requesting data
        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)

        self._log.info(
            f"MACrossover started: fast={self.config.fast_period}, "
            f"slow={self.config.slow_period}"
        )

    def on_reset(self) -> None:
        """Reset strategy state.

        Resets both EMA indicators and previous value tracking.
        Called when strategy needs to be reset to initial state.
        """
        self.fast_ema.reset()
        self.slow_ema.reset()
        self._prev_fast = None
        self._prev_slow = None

    def generate_signal(self, bar: Bar) -> SignalType:
        """Generate signal based on EMA crossover.

        Args:
            bar: The incoming bar data

        Returns:
            SignalType.BUY on bullish crossover,
            SignalType.SELL on bearish crossover,
            SignalType.NONE otherwise
        """
        # Wait for indicators to warm up
        if not self.fast_ema.initialized or not self.slow_ema.initialized:
            return SignalType.NONE

        fast = self.fast_ema.value
        slow = self.slow_ema.value

        signal = SignalType.NONE

        # Check for crossover (requires previous values)
        if self._prev_fast is not None and self._prev_slow is not None:
            # Bullish crossover: fast crosses above slow
            if self._prev_fast <= self._prev_slow and fast > slow:
                signal = SignalType.BUY
                self._log.info(f"Bullish crossover: fast={fast:.5f} > slow={slow:.5f}")
            # Bearish crossover: fast crosses below slow
            elif self._prev_fast >= self._prev_slow and fast < slow:
                signal = SignalType.SELL
                self._log.info(f"Bearish crossover: fast={fast:.5f} < slow={slow:.5f}")

        # Update previous values
        self._prev_fast = fast
        self._prev_slow = slow

        return signal

    def _execute_signal(self, signal: SignalType) -> None:
        """Execute signal with position reversal support.

        Handles position reversal by closing existing position and
        immediately entering in the opposite direction on the same bar.

        Args:
            signal: The signal to execute
        """
        if signal == SignalType.BUY:
            if self.is_short:
                self._log.info("Reversing: closing short, entering long")
                self._close_position()
            self._go_long()  # Immediate entry
        elif signal == SignalType.SELL:
            if self.is_long:
                self._log.info("Reversing: closing long, entering short")
                self._close_position()
            self._go_short()  # Immediate entry
        elif signal == SignalType.CLOSE:
            self._close_position()

    def _go_long(self) -> None:
        """Enter long position.

        Overrides base to allow entry even when not flat (for reversals).
        Creates and submits a market buy order.
        """
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self._instrument.make_qty(self.get_position_size(SignalType.BUY)),
        )
        self.submit_order(order)
        self._log.info(f"Going LONG with {self.config.trade_size}")

    def _go_short(self) -> None:
        """Enter short position.

        Overrides base to allow entry even when not flat (for reversals).
        Creates and submits a market sell order.
        """
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=self._instrument.make_qty(self.get_position_size(SignalType.SELL)),
        )
        self.submit_order(order)
        self._log.info(f"Going SHORT with {self.config.trade_size}")
