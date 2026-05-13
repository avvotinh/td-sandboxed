"""Unit tests for the ``run_backtest`` facade (Story 8.8).

The facade threads together the venue → instrument → data → strategy →
(optional) FTMO actor → run pipeline. We mock the ``BacktestRunner``
so the test is fast and focuses on composition + override merging.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.backtesting.job_config import (
    BacktestJobConfig,
    SyntheticDataSpec,
    VenueSpec,
)
from src.backtesting.result import BacktestResult
from src.backtesting.runner_facade import _normalise_parquet_index


def _base_job(**overrides) -> BacktestJobConfig:
    base = dict(
        strategy="ma_crossover",
        strategy_params={
            "fast_period": 5,
            "slow_period": 20,
            "trade_size": "10000",
        },
        venue=VenueSpec(
            name="SIM", starting_balance=Decimal("100000"), currency="USD"
        ),
        instrument_symbol="EUR/USD",
        bar_type_suffix="1-MINUTE-BID-EXTERNAL",
        data=SyntheticDataSpec(
            pattern="trending", count=100, start_price=1.10, seed=7
        ),
    )
    base.update(overrides)
    return BacktestJobConfig(**base)


@pytest.fixture
def fake_result() -> BacktestResult:
    return BacktestResult(
        strategy_name="ma_crossover",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 1, 2),
        initial_balance=Decimal("100000"),
        final_balance=Decimal("100500"),
    )


@pytest.mark.unit
class TestRunBacktestComposition:
    def test_calls_runner_in_correct_order(self, fake_result) -> None:
        from src.backtesting import runner_facade

        with (
            patch.object(runner_facade, "BacktestRunner") as runner_cls,
            patch.object(runner_facade, "_build_instrument") as build_instr,
            patch.object(runner_facade, "_build_bars") as build_bars,
            patch.object(
                runner_facade, "_read_final_balance", return_value=Decimal("100000")
            ),
        ):
            mock_runner = MagicMock()
            mock_runner.get_result.return_value = fake_result
            runner_cls.return_value = mock_runner
            build_instr.return_value = (MagicMock(id=MagicMock()), "EUR/USD.SIM")
            build_bars.return_value = [MagicMock(), MagicMock()]

            result = runner_facade.run_backtest(_base_job())

            # The canonical order: venue → instrument → data → strategy → run
            names = [c[0] for c in mock_runner.method_calls]
            def idx(name: str) -> int:
                return names.index(name)

            assert idx("add_venue") < idx("add_instrument")
            assert idx("add_instrument") < idx("add_data")
            assert idx("add_data") < idx("add_strategy")
            assert idx("add_strategy") < idx("run")
            assert result is fake_result

    def test_strategy_overrides_merge_into_config(self, fake_result) -> None:
        from src.backtesting import runner_facade

        with (
            patch.object(runner_facade, "BacktestRunner") as runner_cls,
            patch.object(runner_facade, "_build_instrument") as build_instr,
            patch.object(runner_facade, "_build_bars") as build_bars,
            patch.object(runner_facade, "_build_strategy") as build_strat,
            patch.object(
                runner_facade, "_read_final_balance", return_value=Decimal("100000")
            ),
        ):
            mock_runner = MagicMock()
            mock_runner.get_result.return_value = fake_result
            runner_cls.return_value = mock_runner
            build_instr.return_value = (MagicMock(), "EUR/USD.SIM")
            build_bars.return_value = []
            build_strat.return_value = MagicMock()

            runner_facade.run_backtest(
                _base_job(), strategy_overrides={"fast_period": 9}
            )

            # _build_strategy received the merged params
            _, kwargs = build_strat.call_args
            assert kwargs["params"]["fast_period"] == 9
            assert kwargs["params"]["slow_period"] == 20

    def test_dispose_called_even_on_run_failure(self, fake_result) -> None:
        from src.backtesting import runner_facade

        with (
            patch.object(runner_facade, "BacktestRunner") as runner_cls,
            patch.object(runner_facade, "_build_instrument") as build_instr,
            patch.object(runner_facade, "_build_bars") as build_bars,
        ):
            mock_runner = MagicMock()
            mock_runner.run.side_effect = RuntimeError("boom")
            runner_cls.return_value = mock_runner
            build_instr.return_value = (MagicMock(), "EUR/USD.SIM")
            build_bars.return_value = []

            with pytest.raises(RuntimeError, match="boom"):
                runner_facade.run_backtest(_base_job())

            mock_runner.dispose.assert_called_once()

    def test_window_forwarded_to_run(self, fake_result) -> None:
        from src.backtesting import runner_facade

        start = datetime(2024, 1, 5)
        end = datetime(2024, 1, 20)

        with (
            patch.object(runner_facade, "BacktestRunner") as runner_cls,
            patch.object(runner_facade, "_build_instrument") as build_instr,
            patch.object(runner_facade, "_build_bars") as build_bars,
            patch.object(
                runner_facade, "_read_final_balance", return_value=Decimal("100000")
            ),
        ):
            mock_runner = MagicMock()
            mock_runner.get_result.return_value = fake_result
            runner_cls.return_value = mock_runner
            build_instr.return_value = (MagicMock(), "EUR/USD.SIM")
            build_bars.return_value = []

            runner_facade.run_backtest(
                _base_job().with_window(start=start, end=end)
            )

            _, run_kwargs = mock_runner.run.call_args
            assert run_kwargs.get("start") == start
            assert run_kwargs.get("end") == end


@pytest.mark.unit
class TestNormaliseParquetIndex:
    """``_normalise_parquet_index`` accepts both parquet shapes the repo writes:
    ``CachedBarLoader``'s tz-aware DatetimeIndex and the stitch script's
    int64 ``time`` column with ``index=False``. Both must yield the same
    tz-aware DatetimeIndex shape before ``dataframe_to_bars`` consumes it.
    """

    def _ohlcv(self) -> dict[str, list[float]]:
        return {
            "open": [1.0, 2.0],
            "high": [1.5, 2.5],
            "low": [0.5, 1.5],
            "close": [1.2, 2.2],
            "volume": [100.0, 110.0],
        }

    def test_passes_through_tz_aware_index(self) -> None:
        idx = pd.DatetimeIndex(
            ["2024-01-01T00:00:00", "2024-01-01T00:05:00"], tz="UTC", name="time"
        )
        df = pd.DataFrame(self._ohlcv(), index=idx)
        out = _normalise_parquet_index(df, source="/tmp/cached.parquet")
        assert out.index is df.index
        assert "time" not in out.columns

    def test_converts_int_ms_time_column(self) -> None:
        rows = self._ohlcv()
        rows["time"] = [1704067200000, 1704067500000]  # 2024-01-01 00:00, 00:05 UTC ms
        df = pd.DataFrame(rows)
        out = _normalise_parquet_index(df, source="/tmp/stitched.parquet")
        assert isinstance(out.index, pd.DatetimeIndex)
        assert out.index.tz is not None
        assert "time" not in out.columns
        assert out.index[0] == pd.Timestamp("2024-01-01T00:00:00", tz="UTC")
        assert out.index[1] == pd.Timestamp("2024-01-01T00:05:00", tz="UTC")

    def test_rejects_naive_datetime_index(self) -> None:
        idx = pd.DatetimeIndex(["2024-01-01", "2024-01-02"], name="time")
        df = pd.DataFrame(self._ohlcv(), index=idx)
        with pytest.raises(ValueError, match="naive DatetimeIndex"):
            _normalise_parquet_index(df, source="/tmp/bad.parquet")

    def test_rejects_missing_time(self) -> None:
        df = pd.DataFrame(self._ohlcv())  # default RangeIndex, no time column
        with pytest.raises(ValueError, match="neither a DatetimeIndex nor a 'time' column"):
            _normalise_parquet_index(df, source="/tmp/no-time.parquet")
