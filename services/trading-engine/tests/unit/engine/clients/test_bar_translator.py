"""Unit tests for :mod:`bar_translator` (story 10.5b)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from nautilus_trader.model.data import Bar as NautilusBar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.identifiers import Venue

from src.adapters.redis_models import Bar as InternalBar
from src.engine.clients.bar_translator import (
    make_bar_type,
    parse_timeframe,
    to_nautilus_bar,
)


VENUE = Venue("MT5")


# ----- parse_timeframe ---------------------------------------------------


class TestParseTimeframe:
    @pytest.mark.parametrize(
        "raw,expected_step,expected_agg",
        [
            ("1m", 1, BarAggregation.MINUTE),
            ("5m", 5, BarAggregation.MINUTE),
            ("15m", 15, BarAggregation.MINUTE),
            ("30s", 30, BarAggregation.SECOND),
            ("1h", 1, BarAggregation.HOUR),
            ("4h", 4, BarAggregation.HOUR),
            ("1d", 1, BarAggregation.DAY),
            ("1w", 1, BarAggregation.WEEK),
        ],
    )
    def test_supported_timeframes(
        self, raw: str, expected_step: int, expected_agg: BarAggregation
    ) -> None:
        step, agg = parse_timeframe(raw)
        assert step == expected_step
        assert agg is expected_agg

    @pytest.mark.parametrize("tf", ["1M", "5H", " 1m "])
    def test_case_and_whitespace_normalised(self, tf: str) -> None:
        step, agg = parse_timeframe(tf)
        assert step == int(tf.strip()[:-1])

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            parse_timeframe("")

    def test_unsupported_suffix_raises(self) -> None:
        with pytest.raises(ValueError, match="suffix"):
            parse_timeframe("1y")

    def test_non_integer_step_raises(self) -> None:
        with pytest.raises(ValueError, match="integer"):
            parse_timeframe("xm")

    def test_zero_step_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            parse_timeframe("0m")


# ----- make_bar_type -----------------------------------------------------


class TestMakeBarType:
    def test_builds_canonical_bar_type(self) -> None:
        bt = make_bar_type("XAUUSD", "1m", VENUE)
        assert isinstance(bt, BarType)
        # Canonical string form is documented by Nautilus
        assert "XAUUSD.MT5" in str(bt)
        assert "1-MINUTE" in str(bt)
        assert "LAST" in str(bt)

    def test_explicit_price_type(self) -> None:
        bt = make_bar_type("EURUSD", "1h", VENUE, price_type=PriceType.MID)
        assert "MID" in str(bt)

    def test_invalid_timeframe_propagates(self) -> None:
        with pytest.raises(ValueError):
            make_bar_type("XAUUSD", "1y", VENUE)


# ----- to_nautilus_bar ---------------------------------------------------


def _make_internal_bar(**overrides) -> InternalBar:
    defaults = {
        "symbol": "XAUUSD",
        "timeframe": "1m",
        "time": datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
        "open": 1850.00,
        "high": 1851.50,
        "low": 1849.80,
        "close": 1850.45,
        "volume": 1234.5,
    }
    defaults.update(overrides)
    return InternalBar(**defaults)


class TestToNautilusBar:
    def test_converts_basic_bar(self) -> None:
        internal = _make_internal_bar()
        bar_type = make_bar_type("XAUUSD", "1m", VENUE)

        nautilus = to_nautilus_bar(internal, bar_type=bar_type)

        assert isinstance(nautilus, NautilusBar)
        assert nautilus.bar_type == bar_type
        assert float(nautilus.open) == 1850.00
        assert float(nautilus.high) == 1851.50
        assert float(nautilus.low) == 1849.80
        assert float(nautilus.close) == 1850.45
        assert float(nautilus.volume) == 1234.5

    def test_ts_event_matches_internal_time(self) -> None:
        ts = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        internal = _make_internal_bar(time=ts)
        bar_type = make_bar_type("XAUUSD", "1m", VENUE)

        nautilus = to_nautilus_bar(internal, bar_type=bar_type)

        expected_ns = int(ts.timestamp() * 1_000_000_000)
        assert nautilus.ts_event == expected_ns
        # ts_init defaults to ts_event
        assert nautilus.ts_init == expected_ns

    def test_explicit_ts_init_override(self) -> None:
        internal = _make_internal_bar()
        bar_type = make_bar_type("XAUUSD", "1m", VENUE)

        nautilus = to_nautilus_bar(
            internal, bar_type=bar_type, ts_init_ns=999_999_999
        )

        assert nautilus.ts_init == 999_999_999
        assert nautilus.ts_event != 999_999_999

    def test_price_precision_respected(self) -> None:
        internal = _make_internal_bar(open=1850.123456789)
        bar_type = make_bar_type("XAUUSD", "1m", VENUE)

        nautilus = to_nautilus_bar(
            internal, bar_type=bar_type, price_precision=2
        )
        assert str(nautilus.open) == "1850.12"

    def test_size_precision_respected(self) -> None:
        internal = _make_internal_bar(volume=1234.567)
        bar_type = make_bar_type("XAUUSD", "1m", VENUE)

        nautilus = to_nautilus_bar(
            internal, bar_type=bar_type, size_precision=1
        )
        assert str(nautilus.volume) == "1234.6"
