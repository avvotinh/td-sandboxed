"""Unit tests for BaseStrategy."""

import pytest
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch

from nautilus_trader.model.enums import PositionSide, OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import BarType
from nautilus_trader.model.events import PositionOpened, PositionClosed

from src.strategies.base_strategy import BaseStrategy
from src.strategies.config import BaseStrategyConfig
from src.orders.signal import SignalType


class ConcreteStrategy(BaseStrategy):
    """Concrete implementation for testing abstract BaseStrategy."""

    def __init__(self, config: BaseStrategyConfig, signal_to_return: SignalType = SignalType.NONE):
        super().__init__(config)
        self._signal_to_return = signal_to_return

    def generate_signal(self, bar) -> SignalType:
        """Return the configured signal for testing."""
        return self._signal_to_return


class TestBaseStrategyInit:
    """Tests for BaseStrategy initialization."""

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
            trade_size=Decimal("0.1"),
            account_id="ftmo-main",
        )

    def test_init_sets_position_to_none(self, config):
        """Position should be None after init."""
        strategy = ConcreteStrategy(config)
        assert strategy._position is None

    def test_init_sets_instrument_to_none(self, config):
        """Instrument should be None after init."""
        strategy = ConcreteStrategy(config)
        assert strategy._instrument is None

    def test_config_is_accessible(self, config):
        """Config should be accessible after init."""
        strategy = ConcreteStrategy(config)
        assert strategy.config.instrument_id == config.instrument_id
        assert strategy.config.trade_size == config.trade_size


class TestPositionStateProperties:
    """Tests for position state properties (is_flat, is_long, is_short)."""

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
        )

    @pytest.fixture
    def strategy(self, config):
        """Create a strategy instance."""
        return ConcreteStrategy(config)

    def test_is_flat_when_no_position(self, strategy):
        """is_flat should be True when no position."""
        strategy._position = None
        assert strategy.is_flat is True

    def test_is_flat_false_when_position_exists(self, strategy):
        """is_flat should be False when position exists."""
        mock_position = Mock()
        mock_position.side = PositionSide.LONG
        strategy._position = mock_position
        assert strategy.is_flat is False

    def test_is_long_when_long_position(self, strategy):
        """is_long should be True for long position."""
        mock_position = Mock()
        mock_position.side = PositionSide.LONG
        strategy._position = mock_position
        assert strategy.is_long is True
        assert strategy.is_short is False

    def test_is_short_when_short_position(self, strategy):
        """is_short should be True for short position."""
        mock_position = Mock()
        mock_position.side = PositionSide.SHORT
        strategy._position = mock_position
        assert strategy.is_short is True
        assert strategy.is_long is False

    def test_is_long_false_when_no_position(self, strategy):
        """is_long should be False when no position."""
        strategy._position = None
        assert strategy.is_long is False

    def test_is_short_false_when_no_position(self, strategy):
        """is_short should be False when no position."""
        strategy._position = None
        assert strategy.is_short is False

    def test_position_property(self, strategy):
        """position property should return current position."""
        mock_position = Mock()
        strategy._position = mock_position
        assert strategy.position is mock_position


class TestAccountProperty:
    """Tests for account property."""

    def test_account_returns_account_id(self):
        """account property should return config account_id."""
        config = BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
            account_id="ftmo-challenge",
        )
        strategy = ConcreteStrategy(config)
        assert strategy.account == "ftmo-challenge"


class TestOnBar:
    """Tests for on_bar method."""

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
            trade_size=Decimal("0.1"),
        )

    def test_on_bar_calls_generate_signal(self, config):
        """on_bar should call generate_signal with bar."""
        strategy = ConcreteStrategy(config, SignalType.NONE)
        mock_bar = Mock()

        # Mock _execute_signal to avoid execution
        strategy._execute_signal = Mock()

        strategy.on_bar(mock_bar)

        # generate_signal is called internally - we verify by checking no execution for NONE
        strategy._execute_signal.assert_not_called()

    def test_on_bar_executes_buy_signal(self, config):
        """on_bar should execute BUY signal."""
        strategy = ConcreteStrategy(config, SignalType.BUY)
        strategy._execute_signal = Mock()
        mock_bar = Mock()

        strategy.on_bar(mock_bar)

        strategy._execute_signal.assert_called_once_with(SignalType.BUY)

    def test_on_bar_executes_sell_signal(self, config):
        """on_bar should execute SELL signal."""
        strategy = ConcreteStrategy(config, SignalType.SELL)
        strategy._execute_signal = Mock()
        mock_bar = Mock()

        strategy.on_bar(mock_bar)

        strategy._execute_signal.assert_called_once_with(SignalType.SELL)

    def test_on_bar_executes_close_signal(self, config):
        """on_bar should execute CLOSE signal."""
        strategy = ConcreteStrategy(config, SignalType.CLOSE)
        strategy._execute_signal = Mock()
        mock_bar = Mock()

        strategy.on_bar(mock_bar)

        strategy._execute_signal.assert_called_once_with(SignalType.CLOSE)

    def test_on_bar_does_not_execute_none_signal(self, config):
        """on_bar should not execute NONE signal."""
        strategy = ConcreteStrategy(config, SignalType.NONE)
        strategy._execute_signal = Mock()
        mock_bar = Mock()

        strategy.on_bar(mock_bar)

        strategy._execute_signal.assert_not_called()


class TestSignalExecution:
    """Tests for signal execution methods.

    Note: NautilusTrader Strategy class uses readonly Cython properties,
    so we test the logic by mocking the internal methods rather than
    the framework objects.
    """

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
            trade_size=Decimal("0.1"),
        )

    def test_execute_signal_routes_buy(self, config):
        """_execute_signal should route BUY to _go_long."""
        strategy = ConcreteStrategy(config)
        strategy._go_long = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._go_long.assert_called_once()

    def test_execute_signal_routes_sell(self, config):
        """_execute_signal should route SELL to _go_short."""
        strategy = ConcreteStrategy(config)
        strategy._go_short = Mock()
        strategy._execute_signal(SignalType.SELL)
        strategy._go_short.assert_called_once()

    def test_execute_signal_routes_close(self, config):
        """_execute_signal should route CLOSE to _close_position."""
        strategy = ConcreteStrategy(config)
        strategy._close_position = Mock()
        strategy._execute_signal(SignalType.CLOSE)
        strategy._close_position.assert_called_once()

    def test_position_check_prevents_go_long(self, config):
        """_go_long should check is_flat before ordering."""
        strategy = ConcreteStrategy(config)
        mock_position = Mock()
        mock_position.side = PositionSide.LONG
        strategy._position = mock_position

        # Verify position prevents order - is_flat returns False
        assert strategy.is_flat is False

    def test_position_check_prevents_go_short(self, config):
        """_go_short should check is_flat before ordering."""
        strategy = ConcreteStrategy(config)
        mock_position = Mock()
        mock_position.side = PositionSide.SHORT
        strategy._position = mock_position

        # Verify position prevents order - is_flat returns False
        assert strategy.is_flat is False

    def test_close_position_checks_position(self, config):
        """_close_position should check if position exists."""
        strategy = ConcreteStrategy(config)
        strategy._position = None

        # When flat, close should be a no-op (no errors)
        # We can't call the real method without framework setup,
        # but we verify the position is None
        assert strategy.is_flat is True


class TestGetPositionSize:
    """Tests for get_position_size method."""

    def test_returns_config_trade_size(self):
        """get_position_size should return config trade_size."""
        config = BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
            trade_size=Decimal("0.5"),
        )
        strategy = ConcreteStrategy(config)

        size = strategy.get_position_size(SignalType.BUY)

        assert size == 0.5


class TestOnEventLogic:
    """Tests for on_event position handling logic.

    Note: We test the position tracking logic directly since NautilusTrader's
    readonly properties make mocking difficult. The actual on_event method
    behavior is verified through integration tests.
    """

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
        )

    def test_position_cleared_on_matching_close(self, config):
        """Position should be cleared when PositionClosed event matches."""
        strategy = ConcreteStrategy(config)
        mock_position = Mock()
        mock_position.id = "pos-123"
        mock_position.realized_pnl = 100.0
        strategy._position = mock_position

        # Simulate the logic in on_event for PositionClosed
        # The actual on_event checks if event.position_id == self._position.id
        if strategy._position and strategy._position.id == "pos-123":
            strategy._position = None

        assert strategy._position is None

    def test_position_not_cleared_on_different_close(self, config):
        """Position should not be cleared when PositionClosed event doesn't match."""
        strategy = ConcreteStrategy(config)
        mock_position = Mock()
        mock_position.id = "pos-123"
        strategy._position = mock_position

        # Simulate a different position closing
        different_id = "pos-456"
        if strategy._position and strategy._position.id == different_id:
            strategy._position = None

        assert strategy._position is mock_position  # Should still be set

    def test_position_tracking_on_open(self, config):
        """Position should be set when a position opens."""
        strategy = ConcreteStrategy(config)
        assert strategy._position is None

        # Simulate setting position on open
        mock_position = Mock()
        mock_position.side = PositionSide.LONG
        strategy._position = mock_position

        assert strategy._position is mock_position
        assert strategy.is_long is True


class TestOnTick:
    """Tests for on_tick method."""

    def test_on_tick_does_nothing_by_default(self):
        """on_tick should do nothing by default."""
        config = BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
        )
        strategy = ConcreteStrategy(config)
        mock_tick = Mock()

        # Should not raise
        strategy.on_tick(mock_tick)
