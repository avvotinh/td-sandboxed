"""Unit tests for the chart-viewer payload builder (pure transforms)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest
from nautilus_trader.model.data import BarType

from src.backtesting.reports.chart_data import (
    PANE_LOWER,
    build_chart_payload,
    candles_from_dataframe,
    compute_indicator_series,
    trades_to_payload,
)
from src.backtesting.result import BacktestResult, SlUpdate, TradeRecord
from src.backtesting.synthetic_bars import generate_bars

pytestmark = pytest.mark.unit


_BAR_TYPE = BarType.from_str("XAUUSD.SIM-5-MINUTE-LAST-EXTERNAL")
_START = datetime(2024, 1, 1, tzinfo=UTC)
_START_NS = int(_START.timestamp() * 1_000_000_000)


def _bars(count: int):
    return generate_bars(
        pattern="trending",
        count=count,
        start_price=2000.0,
        seed=7,
        start_ts=_START_NS,
        bar_type=_BAR_TYPE,
        price_precision=3,
        volume_precision=2,
    )


def _df_from_bars(bars) -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [pd.Timestamp(b.ts_event, unit="ns", tz="UTC") for b in bars],
        name="time",
    )
    return pd.DataFrame(
        {
            "open": [b.open.as_double() for b in bars],
            "high": [b.high.as_double() for b in bars],
            "low": [b.low.as_double() for b in bars],
            "close": [b.close.as_double() for b in bars],
            "volume": [b.volume.as_double() for b in bars],
        },
        index=index,
    )


def _trade(**overrides) -> TradeRecord:
    defaults = dict(
        trade_id="SIM-1-001",
        symbol="XAUUSD.SIM",
        side="BUY",
        entry_ts=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        exit_ts=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        entry_price=Decimal("2000"),
        exit_price=Decimal("2010"),
        quantity=Decimal("1"),
        pnl=Decimal("10"),
        sl_price=Decimal("1995"),
        tp_price=Decimal("2020"),
    )
    defaults.update(overrides)
    return TradeRecord(**defaults)


class TestCandles:
    def test_epoch_seconds_and_ohlcv(self) -> None:
        bars = _bars(5)
        candles = candles_from_dataframe(_df_from_bars(bars))
        assert len(candles) == 5
        first = candles[0]
        assert first["time"] == int(_START.timestamp())
        assert set(first) == {"time", "open", "high", "low", "close", "volume"}
        assert first["high"] >= first["low"]

    def test_missing_volume_column_defaults_to_zero(self) -> None:
        df = _df_from_bars(_bars(3)).drop(columns=["volume"])
        candles = candles_from_dataframe(df)
        assert all(c["volume"] == 0.0 for c in candles)


class TestTrades:
    def test_basic_fields_and_sorting(self) -> None:
        later = _trade(
            trade_id="SIM-1-002",
            entry_ts=datetime(2024, 1, 2, tzinfo=UTC),
            exit_ts=datetime(2024, 1, 3, tzinfo=UTC),
        )
        rows = trades_to_payload([later, _trade()])
        assert [r["id"] for r in rows] == ["SIM-1-001", "SIM-1-002"]
        assert rows[0]["sl"] == 1995.0
        assert rows[0]["tp"] == 2020.0

    def test_sl_path_spans_trade_and_dedupes(self) -> None:
        entry = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        exit_ = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        trade = _trade(
            sl_updates=(
                SlUpdate(ts=datetime(2024, 1, 1, 10, 30, tzinfo=UTC), price=Decimal("2000")),
                SlUpdate(ts=datetime(2024, 1, 1, 11, 0, tzinfo=UTC), price=Decimal("2000")),
                SlUpdate(ts=datetime(2024, 1, 1, 11, 30, tzinfo=UTC), price=Decimal("2004")),
            )
        )
        [row] = trades_to_payload([trade])
        path = row["slPath"]
        assert path[0] == {"time": int(entry.timestamp()), "price": 1995.0}
        # Duplicate 2000 collapsed; final level carried to exit.
        assert [p["price"] for p in path] == [1995.0, 2000.0, 2004.0, 2004.0]
        assert path[-1]["time"] == int(exit_.timestamp())

    def test_no_sl_means_empty_path(self) -> None:
        [row] = trades_to_payload([_trade(sl_price=None)])
        assert row["sl"] is None
        assert row["slPath"] == []

    def test_same_bar_sl_updates_collapse_to_last_write(self) -> None:
        """Duplicate times would break lightweight-charts setData."""
        same_ts = datetime(2024, 1, 1, 10, 30, tzinfo=UTC)
        trade = _trade(
            sl_updates=(
                SlUpdate(ts=same_ts, price=Decimal("2000")),
                SlUpdate(ts=same_ts, price=Decimal("2002")),
            )
        )
        [row] = trades_to_payload([trade])
        times = [p["time"] for p in row["slPath"]]
        assert times == sorted(set(times)), "times must be strictly ascending"
        assert 2002.0 in [p["price"] for p in row["slPath"]]
        assert 2000.0 not in [p["price"] for p in row["slPath"]]


class TestIndicatorSeries:
    def test_supertrend_split_covers_every_bar_once(self) -> None:
        bars = _bars(80)
        times = [b.ts_event // 1_000_000_000 for b in bars]
        series = compute_indicator_series("supertrend", {}, bars, times)
        by_key = {s.key: s for s in series}
        up, down = by_key["supertrend_up"], by_key["supertrend_down"]
        assert len(up.points) == len(down.points) == 80
        # Warmup bars are whitespace on BOTH; after warmup exactly one
        # of up/down carries a value per bar.
        for pu, pd_ in zip(up.points, down.points, strict=True):
            assert ("value" in pu) + ("value" in pd_) <= 1

    def test_donchian_bands_present(self) -> None:
        bars = _bars(60)
        times = [b.ts_event // 1_000_000_000 for b in bars]
        series = compute_indicator_series(
            "donchian_breakout", {"channel_period": 10}, bars, times
        )
        keys = {s.key for s in series}
        assert {"donchian_upper", "donchian_lower"} <= keys
        upper = next(s for s in series if s.key == "donchian_upper")
        valued = [p for p in upper.points if "value" in p]
        assert valued, "expected post-warmup band values"

    def test_mean_reversion_has_rsi_pane_with_levels(self) -> None:
        bars = _bars(60)
        times = [b.ts_event // 1_000_000_000 for b in bars]
        series = compute_indicator_series(
            "mean_reversion", {"oversold": 0.25, "overbought": 0.75}, bars, times
        )
        rsi = next(s for s in series if s.key == "rsi")
        assert rsi.pane == PANE_LOWER
        assert rsi.levels == (0.25, 0.75)

    def test_trail_and_adx_series_are_opt_in(self) -> None:
        bars = _bars(60)
        times = [b.ts_event // 1_000_000_000 for b in bars]
        plain = compute_indicator_series("supertrend", {}, bars, times)
        assert {s.key for s in plain} == {"supertrend_up", "supertrend_down"}

        tactic = compute_indicator_series(
            "supertrend",
            {"trailing_enabled": True, "adx_gate_min": "25"},
            bars,
            times,
        )
        keys = {s.key for s in tactic}
        assert {"supertrend_trail", "adx"} <= keys
        adx = next(s for s in tactic if s.key == "adx")
        assert adx.levels == (25.0,)

    def test_unknown_strategy_degrades_to_generic_overlays(self) -> None:
        bars = _bars(30)
        times = [b.ts_event // 1_000_000_000 for b in bars]
        series = compute_indicator_series("orb", {}, bars, times)
        assert series == []

    def test_empty_bars_yield_empty_series_not_keyerror(self) -> None:
        for strategy in ("supertrend", "donchian_breakout", "mean_reversion"):
            series = compute_indicator_series(
                strategy,
                {"trailing_enabled": True, "adx_gate_min": "25"},
                [],
                [],
            )
            assert series, strategy
            assert all(s.points == [] for s in series)


class TestBuildPayload:
    def _result(self, trades=()) -> BacktestResult:
        return BacktestResult(
            strategy_name="supertrend",
            start=_START,
            end=datetime(2024, 1, 2, tzinfo=UTC),
            initial_balance=Decimal("100000"),
            final_balance=Decimal("100500"),
            trades=list(trades),
        )

    def test_payload_shape(self) -> None:
        bars = _bars(40)
        payload = build_chart_payload(
            df=_df_from_bars(bars),
            bars=bars,
            result=self._result([_trade()]),
            strategy_name="supertrend",
            params={},
            symbol="XAUUSD",
            timeframe="M5",
            window_label="in_sample",
        )
        assert payload["meta"]["symbol"] == "XAUUSD"
        assert payload["meta"]["tradeCount"] == 1
        assert payload["meta"]["winRate"] == 1.0
        assert len(payload["candles"]) == 40
        assert payload["indicators"], "expected indicator series"

    def test_misaligned_df_and_bars_raise(self) -> None:
        bars = _bars(10)
        df = _df_from_bars(bars).iloc[:-1]
        with pytest.raises(ValueError, match="misalign"):
            build_chart_payload(
                df=df,
                bars=bars,
                result=self._result(),
                strategy_name="supertrend",
                params={},
                symbol="XAUUSD",
                timeframe="M5",
                window_label="in_sample",
            )
