"""Unit tests for DataFrame → Nautilus Bar converter."""

from __future__ import annotations

import pandas as pd
import pytest
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from src.backtesting.bar_converter import dataframe_to_bars


pytestmark = pytest.mark.unit


@pytest.fixture
def eurusd_instrument():
    return TestInstrumentProvider.default_fx_ccy("EUR/USD")


@pytest.fixture
def eurusd_1min_bar_type(eurusd_instrument) -> BarType:
    return BarType.from_str(f"{eurusd_instrument.id}-1-MINUTE-BID-EXTERNAL")


def _make_df(rows: int = 5) -> pd.DataFrame:
    ts = pd.date_range("2026-04-17T00:00:00Z", periods=rows, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "open": [1.1000 + i * 0.0001 for i in range(rows)],
            "high": [1.1010 + i * 0.0001 for i in range(rows)],
            "low": [1.0995 + i * 0.0001 for i in range(rows)],
            "close": [1.1005 + i * 0.0001 for i in range(rows)],
            "volume": [1000 + i * 100 for i in range(rows)],
        },
        index=ts,
    )


class TestDataframeToBars:
    def test_output_length_matches_input(self, eurusd_instrument, eurusd_1min_bar_type) -> None:
        df = _make_df(5)
        bars = dataframe_to_bars(df, eurusd_1min_bar_type, eurusd_instrument)
        assert len(bars) == 5

    def test_output_contains_bar_objects(self, eurusd_instrument, eurusd_1min_bar_type) -> None:
        df = _make_df(3)
        bars = dataframe_to_bars(df, eurusd_1min_bar_type, eurusd_instrument)
        assert all(isinstance(b, Bar) for b in bars)

    def test_empty_dataframe_yields_empty_list(
        self, eurusd_instrument, eurusd_1min_bar_type
    ) -> None:
        df = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="UTC"),
        )
        bars = dataframe_to_bars(df, eurusd_1min_bar_type, eurusd_instrument)
        assert bars == []

    def test_missing_columns_raises(self, eurusd_instrument, eurusd_1min_bar_type) -> None:
        df = pd.DataFrame(
            {"open": [1.1], "close": [1.1]},
            index=pd.DatetimeIndex(["2026-04-17T00:00:00Z"], tz="UTC"),
        )
        with pytest.raises(ValueError, match="missing"):
            dataframe_to_bars(df, eurusd_1min_bar_type, eurusd_instrument)

    def test_prices_survive_roundtrip(
        self, eurusd_instrument, eurusd_1min_bar_type
    ) -> None:
        df = _make_df(2)
        bars = dataframe_to_bars(df, eurusd_1min_bar_type, eurusd_instrument)
        assert bars[0].close.as_double() == pytest.approx(df.iloc[0]["close"], abs=1e-5)
