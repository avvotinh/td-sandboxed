"""Unit tests for Signal and SignalType."""

import pytest
from datetime import datetime, timezone

from src.orders.signal import Signal, SignalType


class TestSignalType:
    """Tests for SignalType enum."""

    def test_signal_type_values(self):
        """Signal types should have correct values."""
        assert SignalType.BUY.value == "BUY"
        assert SignalType.SELL.value == "SELL"
        assert SignalType.CLOSE.value == "CLOSE"

    def test_is_entry_for_buy(self):
        """BUY should be an entry signal."""
        assert SignalType.BUY.is_entry() is True
        assert SignalType.BUY.is_exit() is False

    def test_is_entry_for_sell(self):
        """SELL should be an entry signal."""
        assert SignalType.SELL.is_entry() is True
        assert SignalType.SELL.is_exit() is False

    def test_is_exit_for_close(self):
        """CLOSE should be an exit signal."""
        assert SignalType.CLOSE.is_exit() is True
        assert SignalType.CLOSE.is_entry() is False


class TestSignal:
    """Tests for Signal model."""

    def test_create_buy_signal(self):
        """Should create a valid BUY signal."""
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="ma_crossover",
        )
        assert signal.signal_type == SignalType.BUY
        assert signal.symbol == "XAUUSD"
        assert signal.strategy_name == "ma_crossover"
        assert signal.is_buy is True
        assert signal.is_sell is False
        assert signal.is_close is False

    def test_create_sell_signal(self):
        """Should create a valid SELL signal."""
        signal = Signal(
            signal_type=SignalType.SELL,
            symbol="EURUSD",
            strategy_name="breakout",
        )
        assert signal.signal_type == SignalType.SELL
        assert signal.symbol == "EURUSD"
        assert signal.is_sell is True
        assert signal.is_buy is False
        assert signal.is_close is False

    def test_create_close_signal(self):
        """Should create a valid CLOSE signal."""
        signal = Signal(
            signal_type=SignalType.CLOSE,
            symbol="XAUUSD",
        )
        assert signal.signal_type == SignalType.CLOSE
        assert signal.is_close is True
        assert signal.is_buy is False
        assert signal.is_sell is False

    def test_timestamp_auto_generated(self):
        """Timestamp should be auto-generated."""
        before = datetime.now(timezone.utc)
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
        )
        after = datetime.now(timezone.utc)

        assert before <= signal.timestamp <= after

    def test_custom_timestamp(self):
        """Should accept custom timestamp."""
        custom_time = datetime(2025, 12, 22, 10, 0, 0)
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            timestamp=custom_time,
        )
        assert signal.timestamp == custom_time

    def test_metadata_default_none(self):
        """Metadata should default to None."""
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
        )
        assert signal.metadata is None

    def test_metadata_custom(self):
        """Should accept custom metadata."""
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            metadata={"indicator": "ema_cross", "value": 1.5},
        )
        assert signal.metadata == {"indicator": "ema_cross", "value": 1.5}

    def test_empty_symbol_raises_error(self):
        """Empty symbol should raise ValueError."""
        with pytest.raises(ValueError, match="symbol must not be empty"):
            Signal(signal_type=SignalType.BUY, symbol="")

    def test_strategy_name_default_empty(self):
        """Strategy name should default to empty string."""
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
        )
        assert signal.strategy_name == ""


class TestSignalRepr:
    """Tests for Signal string representation."""

    def test_repr_contains_type(self):
        """repr should contain signal type."""
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="test_strategy",
        )
        repr_str = repr(signal)
        assert "BUY" in repr_str
        assert "XAUUSD" in repr_str
        assert "test_strategy" in repr_str

    def test_repr_format(self):
        """repr should have expected format."""
        signal = Signal(
            signal_type=SignalType.SELL,
            symbol="EURUSD",
            strategy_name="breakout",
        )
        repr_str = repr(signal)
        assert repr_str == "Signal(SELL, symbol=EURUSD, strategy=breakout)"
