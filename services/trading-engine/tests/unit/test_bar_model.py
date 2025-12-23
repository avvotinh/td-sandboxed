"""Unit tests for Bar model.

Tests cover:
- Bar creation and validation
- JSON parsing from string and bytes
- Channel name property
- OHLCV field validation
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.adapters.redis_models import Bar


class TestBarCreation:
    """Tests for Bar model creation."""

    def test_valid_bar_creation(self):
        """Test creating a valid bar."""
        bar = Bar(
            symbol="XAUUSD",
            timeframe="1m",
            time=datetime.now(timezone.utc),
            open=1850.00,
            high=1851.50,
            low=1849.80,
            close=1850.45,
            volume=1234.5,
        )
        assert bar.symbol == "XAUUSD"
        assert bar.timeframe == "1m"
        assert bar.open == 1850.00
        assert bar.high == 1851.50
        assert bar.low == 1849.80
        assert bar.close == 1850.45
        assert bar.volume == 1234.5

    def test_bar_with_zero_volume(self):
        """Test bar allows zero volume."""
        bar = Bar(
            symbol="XAUUSD",
            timeframe="1m",
            time=datetime.now(timezone.utc),
            open=1850.00,
            high=1851.50,
            low=1849.80,
            close=1850.45,
            volume=0,
        )
        assert bar.volume == 0

    def test_bar_with_different_timeframes(self):
        """Test bar with various timeframes."""
        for tf in ["1m", "5m", "15m", "1h", "4h", "1d"]:
            bar = Bar(
                symbol="XAUUSD",
                timeframe=tf,
                time=datetime.now(timezone.utc),
                open=1850.00,
                high=1851.50,
                low=1849.80,
                close=1850.45,
                volume=100,
            )
            assert bar.timeframe == tf


class TestBarChannelName:
    """Tests for Bar channel_name property."""

    def test_channel_name_format(self):
        """Test channel name format: bars:{symbol}:{timeframe}."""
        bar = Bar(
            symbol="XAUUSD",
            timeframe="1m",
            time=datetime.now(timezone.utc),
            open=1850.00,
            high=1851.50,
            low=1849.80,
            close=1850.45,
            volume=100,
        )
        assert bar.channel_name == "bars:XAUUSD:1m"

    def test_channel_name_different_symbol(self):
        """Test channel name with different symbol."""
        bar = Bar(
            symbol="BTCUSD",
            timeframe="5m",
            time=datetime.now(timezone.utc),
            open=45000,
            high=45100,
            low=44900,
            close=45050,
            volume=100,
        )
        assert bar.channel_name == "bars:BTCUSD:5m"

    def test_channel_name_hourly_timeframe(self):
        """Test channel name with hourly timeframe."""
        bar = Bar(
            symbol="EURUSD",
            timeframe="1h",
            time=datetime.now(timezone.utc),
            open=1.0850,
            high=1.0860,
            low=1.0840,
            close=1.0855,
            volume=50000,
        )
        assert bar.channel_name == "bars:EURUSD:1h"


class TestBarFromJson:
    """Tests for Bar.from_json() class method."""

    def test_from_json_valid_string(self):
        """Test parsing Bar from valid JSON string."""
        json_data = """
        {
            "symbol": "XAUUSD",
            "timeframe": "1m",
            "time": "2025-12-03T14:32:00Z",
            "open": 1850.00,
            "high": 1851.50,
            "low": 1849.80,
            "close": 1850.45,
            "volume": 1234.5
        }
        """
        bar = Bar.from_json(json_data)
        assert bar.symbol == "XAUUSD"
        assert bar.timeframe == "1m"
        assert bar.open == 1850.00
        assert bar.high == 1851.50
        assert bar.low == 1849.80
        assert bar.close == 1850.45
        assert bar.volume == 1234.5

    def test_from_json_bytes(self):
        """Test parsing Bar from JSON bytes."""
        json_bytes = b'{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z","open":1850.00,"high":1851.50,"low":1849.80,"close":1850.45,"volume":1234.5}'
        bar = Bar.from_json(json_bytes)
        assert bar.symbol == "XAUUSD"
        assert bar.close == 1850.45

    def test_from_json_compact(self):
        """Test parsing Bar from compact JSON (no whitespace)."""
        json_data = '{"symbol":"BTCUSD","timeframe":"5m","time":"2025-12-03T14:00:00Z","open":45000,"high":45100,"low":44900,"close":45050,"volume":100}'
        bar = Bar.from_json(json_data)
        assert bar.symbol == "BTCUSD"
        assert bar.timeframe == "5m"

    def test_from_json_invalid_json(self):
        """Test from_json raises on invalid JSON."""
        with pytest.raises(json.JSONDecodeError):
            Bar.from_json("not valid json")

    def test_from_json_missing_field(self):
        """Test from_json raises on missing required field."""
        json_data = '{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z"}'
        with pytest.raises(ValueError):
            Bar.from_json(json_data)


class TestBarToJson:
    """Tests for Bar.to_json() method."""

    def test_to_json_serialization(self):
        """Test bar serialization to JSON."""
        bar = Bar(
            symbol="XAUUSD",
            timeframe="1m",
            time=datetime(2025, 12, 3, 14, 32, 0, tzinfo=timezone.utc),
            open=1850.00,
            high=1851.50,
            low=1849.80,
            close=1850.45,
            volume=1234.5,
        )
        json_str = bar.to_json()
        data = json.loads(json_str)

        assert data["symbol"] == "XAUUSD"
        assert data["timeframe"] == "1m"
        assert data["open"] == 1850.00
        assert data["volume"] == 1234.5


class TestBarValidation:
    """Tests for Bar field validation."""

    def test_high_must_be_gte_low(self):
        """Test high >= low validation."""
        with pytest.raises(ValueError, match="high must be >= low"):
            Bar(
                symbol="XAUUSD",
                timeframe="1m",
                time=datetime.now(timezone.utc),
                open=1850.00,
                high=1849.00,  # Invalid: less than low
                low=1850.00,
                close=1850.00,
                volume=100,
            )

    def test_high_equal_to_low_valid(self):
        """Test high == low is valid (doji candle)."""
        bar = Bar(
            symbol="XAUUSD",
            timeframe="1m",
            time=datetime.now(timezone.utc),
            open=1850.00,
            high=1850.00,
            low=1850.00,
            close=1850.00,
            volume=100,
        )
        assert bar.high == bar.low

    def test_volume_must_be_non_negative(self):
        """Test volume >= 0 validation."""
        with pytest.raises(ValueError):
            Bar(
                symbol="XAUUSD",
                timeframe="1m",
                time=datetime.now(timezone.utc),
                open=1850.00,
                high=1851.00,
                low=1849.00,
                close=1850.00,
                volume=-100,  # Invalid: negative
            )

    def test_open_must_be_positive(self):
        """Test open > 0 validation."""
        with pytest.raises(ValueError):
            Bar(
                symbol="XAUUSD",
                timeframe="1m",
                time=datetime.now(timezone.utc),
                open=0,  # Invalid: zero
                high=1851.00,
                low=1849.00,
                close=1850.00,
                volume=100,
            )

    def test_close_must_be_positive(self):
        """Test close > 0 validation."""
        with pytest.raises(ValueError):
            Bar(
                symbol="XAUUSD",
                timeframe="1m",
                time=datetime.now(timezone.utc),
                open=1850.00,
                high=1851.00,
                low=1849.00,
                close=-1850.00,  # Invalid: negative
                volume=100,
            )

    def test_symbol_must_not_be_empty(self):
        """Test symbol must not be empty."""
        with pytest.raises(ValueError):
            Bar(
                symbol="",  # Invalid: empty
                timeframe="1m",
                time=datetime.now(timezone.utc),
                open=1850.00,
                high=1851.00,
                low=1849.00,
                close=1850.00,
                volume=100,
            )

    def test_timeframe_must_not_be_empty(self):
        """Test timeframe must not be empty."""
        with pytest.raises(ValueError):
            Bar(
                symbol="XAUUSD",
                timeframe="",  # Invalid: empty
                time=datetime.now(timezone.utc),
                open=1850.00,
                high=1851.00,
                low=1849.00,
                close=1850.00,
                volume=100,
            )

    def test_symbol_whitespace_stripped(self):
        """Test symbol whitespace is stripped."""
        bar = Bar(
            symbol="  XAUUSD  ",
            timeframe="1m",
            time=datetime.now(timezone.utc),
            open=1850.00,
            high=1851.00,
            low=1849.00,
            close=1850.00,
            volume=100,
        )
        assert bar.symbol == "XAUUSD"

    def test_timeframe_whitespace_stripped(self):
        """Test timeframe whitespace is stripped."""
        bar = Bar(
            symbol="XAUUSD",
            timeframe=" 1m ",
            time=datetime.now(timezone.utc),
            open=1850.00,
            high=1851.00,
            low=1849.00,
            close=1850.00,
            volume=100,
        )
        assert bar.timeframe == "1m"


class TestBarTimestamp:
    """Tests for Bar timestamp handling."""

    def test_bar_with_utc_datetime(self):
        """Test bar with UTC datetime."""
        dt = datetime(2025, 12, 3, 14, 32, 0, tzinfo=timezone.utc)
        bar = Bar(
            symbol="XAUUSD",
            timeframe="1m",
            time=dt,
            open=1850.00,
            high=1851.50,
            low=1849.80,
            close=1850.45,
            volume=100,
        )
        assert bar.time == dt

    def test_bar_from_json_iso_timestamp(self):
        """Test bar from JSON with ISO timestamp."""
        json_data = '{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00+00:00","open":1850.00,"high":1851.50,"low":1849.80,"close":1850.45,"volume":100}'
        bar = Bar.from_json(json_data)
        assert bar.time.year == 2025
        assert bar.time.month == 12
        assert bar.time.day == 3
        assert bar.time.hour == 14
        assert bar.time.minute == 32


class TestBarRoundTrip:
    """Tests for Bar JSON round-trip."""

    def test_json_round_trip(self):
        """Test bar survives JSON serialization round-trip."""
        original = Bar(
            symbol="XAUUSD",
            timeframe="1m",
            time=datetime(2025, 12, 3, 14, 32, 0, tzinfo=timezone.utc),
            open=1850.00,
            high=1851.50,
            low=1849.80,
            close=1850.45,
            volume=1234.5,
        )

        json_str = original.to_json()
        restored = Bar.from_json(json_str)

        assert restored.symbol == original.symbol
        assert restored.timeframe == original.timeframe
        assert restored.open == original.open
        assert restored.high == original.high
        assert restored.low == original.low
        assert restored.close == original.close
        assert restored.volume == original.volume
