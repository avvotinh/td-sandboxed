"""Unit tests for the Result Contract v2 writer (docs/v2/01-architecture.md §4)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.backtesting.export.result_writer import (
    SCHEMA_VERSION,
    build_result_payload,
    make_run_id,
    timeframe_from_suffix,
    write_result_json,
)
from src.backtesting.job_config import (
    BacktestJobConfig,
    ParquetDataSpec,
    SyntheticDataSpec,
    VenueSpec,
)
from src.backtesting.result import (
    BacktestResult,
    BreachEvent,
    IndicatorSeries,
    SlUpdate,
    TradeRecord,
)

pytestmark = pytest.mark.unit


T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _trade(**overrides) -> TradeRecord:
    defaults = dict(
        trade_id="P-1",
        symbol="XAUUSD.SIM",
        side="BUY",
        entry_ts=T0,
        exit_ts=T0 + timedelta(hours=1),
        entry_price=Decimal("2000"),
        exit_price=Decimal("2010"),
        quantity=Decimal("100"),
        pnl=Decimal("1000.456"),
        sl_price=Decimal("1990"),
        tp_price=Decimal("2020"),
    )
    defaults.update(overrides)
    return TradeRecord(**defaults)


def _job(**overrides) -> BacktestJobConfig:
    defaults = dict(
        strategy="supertrend",
        strategy_params={"period": 10, "multiplier": 3.0},
        venue=VenueSpec(starting_balance=Decimal("100000")),
        instrument_symbol="XAUUSD",
        bar_type_suffix="5-MINUTE-LAST-EXTERNAL",
        data=SyntheticDataSpec(
            pattern="trending", count=100, start_price=2000.0
        ),
    )
    defaults.update(overrides)
    return BacktestJobConfig(**defaults)


def _result(**overrides) -> BacktestResult:
    defaults = dict(
        strategy_name="supertrend",
        start=T0,
        end=T0 + timedelta(days=1),
        initial_balance=Decimal("100000"),
        final_balance=Decimal("101000"),
        equity_curve=[
            (T0, Decimal("100000")),
            (T0 + timedelta(minutes=5), Decimal("100100")),
        ],
        trades=[_trade()],
    )
    defaults.update(overrides)
    return BacktestResult(**defaults)


class TestMakeRunId:
    def test_format(self) -> None:
        run_id = make_run_id("donchian_breakout", "XAUUSD", "M5")
        assert re.fullmatch(
            r"donchian_breakout-xauusd-m5-\d{8}-\d{6}", run_id
        )

    def test_slash_symbol_sanitized_for_filenames(self) -> None:
        run_id = make_run_id("ma_crossover", "EUR/USD", "M1")
        assert re.fullmatch(r"ma_crossover-eurusd-m1-\d{8}-\d{6}", run_id)


class TestTimeframeFromSuffix:
    @pytest.mark.parametrize(
        ("suffix", "expected"),
        [
            ("5-MINUTE-LAST-EXTERNAL", "M5"),
            ("15-MINUTE-LAST-EXTERNAL", "M15"),
            ("1-MINUTE-BID-EXTERNAL", "M1"),
            ("1-HOUR-LAST-EXTERNAL", "H1"),
            ("1-DAY-LAST-EXTERNAL", "D1"),
        ],
    )
    def test_known_shapes(self, suffix: str, expected: str) -> None:
        assert timeframe_from_suffix(suffix) == expected

    def test_unknown_shape_falls_back_to_suffix(self) -> None:
        assert timeframe_from_suffix("WEIRD-SHAPE") == "WEIRD-SHAPE"


class TestBuildResultPayload:
    def test_top_level_schema_keys(self) -> None:
        payload = build_result_payload(_result(), job=_job(), run_id="rid")
        assert set(payload) == {
            "schema_version",
            "run",
            "account",
            "trades",
            "equity_curve",
            "indicators",
            "metrics",
            "breaches",
        }
        assert payload["schema_version"] == SCHEMA_VERSION == "2"

    def test_run_section(self) -> None:
        payload = build_result_payload(
            _result(config_snapshot={"fingerprint": "abc123"}),
            job=_job(),
            run_id="my-run",
        )
        run = payload["run"]
        assert run["run_id"] == "my-run"
        assert run["strategy"] == "supertrend"
        assert run["symbol"] == "XAUUSD"
        assert run["timeframe"] == "M5"
        assert run["params"] == {"period": 10, "multiplier": 3.0}
        assert run["window"]["name"] == "synthetic"
        assert run["window"]["start"] == T0.isoformat()
        assert run["data_ref"]["fingerprint"] == "abc123"
        assert set(run["engine"]) == {"nautilus_version", "commit"}

    def test_decimal_params_serialize_as_json_numbers(self) -> None:
        job = _job(
            strategy_params={"sl_atr_mult": Decimal("1.5"), "period": 10}
        )
        params = build_result_payload(_result(), job=job, run_id="rid")[
            "run"
        ]["params"]
        assert params == {"sl_atr_mult": 1.5, "period": 10}
        assert isinstance(params["sl_atr_mult"], float)

    def test_parquet_data_ref_and_window_name(self) -> None:
        job = _job(
            data=ParquetDataSpec(
                path=Path("data/historical/XAUUSD/M5/in_sample.parquet")
            )
        )
        run = build_result_payload(_result(), job=job, run_id="rid")["run"]
        assert (
            run["data_ref"]["manifest"]
            == "data/historical/XAUUSD/M5/in_sample.parquet"
        )
        assert run["data_ref"]["fingerprint"] is None
        assert run["window"]["name"] == "in_sample"

    def test_account_section(self) -> None:
        payload = build_result_payload(_result(), job=_job(), run_id="rid")
        assert payload["account"] == {
            "initial_balance": 100000.0,
            "final_balance": 101000.0,
            "currency": "USD",
            "risk_profile": "demo",
        }

    def test_equity_curve_serialization(self) -> None:
        payload = build_result_payload(_result(), job=_job(), run_id="rid")
        assert payload["equity_curve"][0] == {
            "ts": T0.isoformat(),
            "equity": 100000.0,
        }
        assert len(payload["equity_curve"]) == 2

    def test_metrics_none_and_breaches(self) -> None:
        breach = BreachEvent(
            ts=T0,
            rule_name="daily_loss_limit",
            current_value=5.2,
            threshold_value=5.0,
            message="blocked",
        )
        payload = build_result_payload(
            _result(breaches=[breach]), job=_job(), run_id="rid"
        )
        assert payload["metrics"] is None
        assert payload["breaches"] == [
            {
                "ts": T0.isoformat(),
                "rule_name": "daily_loss_limit",
                "current_value": 5.2,
                "threshold_value": 5.0,
                "message": "blocked",
            }
        ]

    def test_indicator_points_use_epoch_seconds(self) -> None:
        series = IndicatorSeries(
            key="rsi",
            title="RSI (14)",
            pane="rsi",
            color="#ab47bc",
            points=((T0, 0.42),),
            levels=(0.3, 0.7),
        )
        payload = build_result_payload(
            _result(indicators=(series,)), job=_job(), run_id="rid"
        )
        [row] = payload["indicators"]
        assert row == {
            "key": "rsi",
            "title": "RSI (14)",
            "pane": "rsi",
            "color": "#ab47bc",
            "points": [{"time": int(T0.timestamp()), "value": 0.42}],
            "levels": [0.3, 0.7],
        }


class TestTradePayload:
    def _trades_of(self, trade: TradeRecord) -> dict:
        payload = build_result_payload(
            _result(trades=[trade]), job=_job(), run_id="rid"
        )
        [row] = payload["trades"]
        return row

    def test_long_trade_full_row(self) -> None:
        row = self._trades_of(_trade())
        assert row["side"] == "LONG"
        assert row["entry"] == {
            "ts": T0.isoformat(),
            "price": 2000.0,
            "kind": "market",
            "reason": None,
        }
        assert row["exit"]["price"] == 2010.0
        assert row["pnl"] == 1000.46  # 2dp rounding
        # LONG: (2010 - 2000) / (2000 - 1990) = 1.0
        assert row["r_multiple"] == 1.0
        assert row["sl"] == 1990.0
        assert row["tp"] == 2020.0
        # XAUUSD contract: 100 units = 1.0 lot
        assert row["quantity_lots"] == 1.0
        assert "quantity_units" not in row

    def test_short_r_multiple(self) -> None:
        row = self._trades_of(
            _trade(
                side="SELL",
                entry_price=Decimal("2000"),
                exit_price=Decimal("1990"),
                sl_price=Decimal("2005"),
                tp_price=Decimal("1980"),
            )
        )
        assert row["side"] == "SHORT"
        # SHORT: (2000 - 1990) / (2005 - 2000) = 2.0
        assert row["r_multiple"] == 2.0

    def test_r_multiple_null_without_sl(self) -> None:
        row = self._trades_of(_trade(sl_price=None, tp_price=None))
        assert row["r_multiple"] is None
        assert row["sl"] is None
        assert row["tp"] is None
        assert row["sl_path"] == []

    def test_r_multiple_null_on_non_positive_risk(self) -> None:
        # LONG with SL at entry → denominator 0 → null, not ZeroDivisionError.
        row = self._trades_of(_trade(sl_price=Decimal("2000")))
        assert row["r_multiple"] is None

    def test_sl_path_serialization_dedupes_same_ts(self) -> None:
        t1 = T0 + timedelta(minutes=5)
        t2 = T0 + timedelta(minutes=10)
        row = self._trades_of(
            _trade(
                sl_updates=(
                    SlUpdate(ts=t1, price=Decimal("1995")),
                    SlUpdate(ts=t1, price=Decimal("1996")),  # same-bar rewrite
                    SlUpdate(ts=t2, price=Decimal("2000")),
                )
            )
        )
        assert row["sl_path"] == [
            {"ts": t1.isoformat(), "price": 1996.0, "reason": None},
            {"ts": t2.isoformat(), "price": 2000.0, "reason": None},
        ]

    def test_unknown_symbol_falls_back_to_units(self) -> None:
        row = self._trades_of(_trade(symbol="BTCUSD.SIM"))
        assert row["quantity_units"] == 100.0
        assert "quantity_lots" not in row


class TestWriteResultJson:
    def test_round_trip_with_parent_creation(self, tmp_path: Path) -> None:
        payload = build_result_payload(_result(), job=_job(), run_id="rid")
        target = tmp_path / "results" / "rid.json"
        write_result_json(target, payload)
        assert json.loads(target.read_text()) == payload
