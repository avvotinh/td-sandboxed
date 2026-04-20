"""Unit tests for BacktestJobConfig and data-source specs (Story 8.8)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.backtesting.job_config import (
    BacktestJobConfig,
    FtmoSpec,
    ParquetDataSpec,
    SyntheticDataSpec,
    TimescaleDataSpec,
    UnsupportedInstrumentError,
    VenueSpec,
)


def _synth_job(**overrides) -> BacktestJobConfig:
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
            pattern="trending", count=500, start_price=1.10, seed=42
        ),
    )
    base.update(overrides)
    return BacktestJobConfig(**base)


@pytest.mark.unit
class TestBacktestJobConfig:
    def test_job_is_frozen(self) -> None:
        job = _synth_job()
        with pytest.raises(Exception):  # pydantic ValidationError
            job.strategy = "supertrend"  # type: ignore[misc]

    def test_with_strategy_params_returns_new_instance(self) -> None:
        job = _synth_job()
        new_job = job.with_strategy_params(fast_period=10)
        assert new_job is not job
        assert new_job.strategy_params["fast_period"] == 10
        assert new_job.strategy_params["slow_period"] == 20
        # original untouched
        assert job.strategy_params["fast_period"] == 5

    def test_with_strategy_params_deep_merges(self) -> None:
        job = _synth_job()
        new_job = job.with_strategy_params(**{"fast_period": 7})
        assert set(new_job.strategy_params.keys()) == set(
            job.strategy_params.keys()
        )

    def test_unknown_strategy_fails_fast(self) -> None:
        from src.backtesting.strategy_registry import UnknownStrategyError

        with pytest.raises(UnknownStrategyError):
            _synth_job(strategy="does_not_exist")

    def test_unsupported_instrument_symbol_raises(self) -> None:
        # Pydantic wraps ValueError subclasses in ValidationError but keeps
        # the message intact — the substring assert proves the cause.
        with pytest.raises((UnsupportedInstrumentError, ValidationError)) as exc:
            _synth_job(instrument_symbol="NOPE/ZZZ")
        assert "Unsupported instrument" in str(exc.value)

    def test_common_fx_symbols_supported(self) -> None:
        # Sanity — these should not raise.
        for sym in ("EUR/USD", "GBP/USD", "USD/JPY", "XAUUSD"):
            _synth_job(instrument_symbol=sym)

    def test_synthetic_spec_rejects_bad_pattern(self) -> None:
        with pytest.raises(Exception):
            SyntheticDataSpec(pattern="weird", count=10, start_price=1.0, seed=1)

    def test_timescale_spec_requires_range(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 2, 1, tzinfo=UTC)
        spec = TimescaleDataSpec(start=start, end=end)
        assert spec.start == start
        assert spec.end == end

    def test_timescale_spec_rejects_end_before_start(self) -> None:
        start = datetime(2024, 2, 1, tzinfo=UTC)
        end = datetime(2024, 1, 1, tzinfo=UTC)
        with pytest.raises(Exception):
            TimescaleDataSpec(start=start, end=end)

    def test_parquet_spec_accepts_path(self, tmp_path: Path) -> None:
        spec = ParquetDataSpec(path=tmp_path / "cache")
        assert spec.path == tmp_path / "cache"

    def test_parquet_spec_rejects_traversal(self) -> None:
        with pytest.raises((ValueError, ValidationError)) as exc:
            ParquetDataSpec(path=Path("../etc/passwd"))
        assert "traversal" in str(exc.value).lower()

    def test_ftmo_spec_rejects_traversal(self) -> None:
        with pytest.raises((ValueError, ValidationError)) as exc:
            FtmoSpec(preset_path=Path("../../etc/shadow"), account_id="a")
        assert "traversal" in str(exc.value).lower()

    def test_ftmo_spec_optional(self) -> None:
        job = _synth_job()
        assert job.ftmo is None
        job2 = _synth_job(
            ftmo=FtmoSpec(preset_path=Path("preset.yaml"), account_id="a")
        )
        assert job2.ftmo is not None
        assert job2.ftmo.account_id == "a"

    def test_window_override_narrows_date_range(self) -> None:
        start = datetime(2024, 1, 5, tzinfo=UTC)
        end = datetime(2024, 1, 20, tzinfo=UTC)
        job = _synth_job()
        narrowed = job.with_window(start=start, end=end)
        assert narrowed.start == start
        assert narrowed.end == end


@pytest.mark.unit
class TestJobConfigYamlRoundtrip:
    def test_from_yaml_reads_job(self, tmp_path: Path) -> None:
        yaml_text = (
            "strategy: ma_crossover\n"
            "instrument_symbol: EUR/USD\n"
            "bar_type_suffix: 1-MINUTE-BID-EXTERNAL\n"
            "venue:\n"
            "  name: SIM\n"
            "  starting_balance: '100000'\n"
            "  currency: USD\n"
            "strategy_params:\n"
            "  fast_period: 5\n"
            "  slow_period: 20\n"
            "  trade_size: '10000'\n"
            "data:\n"
            "  kind: synthetic\n"
            "  pattern: trending\n"
            "  count: 500\n"
            "  start_price: 1.10\n"
            "  seed: 42\n"
        )
        path = tmp_path / "job.yaml"
        path.write_text(yaml_text)
        job = BacktestJobConfig.from_yaml(path)
        assert job.strategy == "ma_crossover"
        assert isinstance(job.data, SyntheticDataSpec)
        assert job.data.count == 500
