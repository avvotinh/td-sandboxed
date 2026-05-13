"""Unit tests for ``src.backtesting.dataset.baseline_harness``.

The harness orchestrates one ``BacktestJobConfig`` per strategy spec
against a fixed dataset window, dispatches ``run_backtest``, and stamps
``BacktestResult.config_snapshot`` with reproducibility metadata. Tests
inject a fake runner so we never spin up Nautilus.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.backtesting.data_cache import ContentHashFingerprint
from src.backtesting.dataset.baseline_harness import (
    BaselineConfig,
    StrategySpec,
    UnknownDatasetEntryError,
    run_baseline,
    timeframe_to_bar_suffix,
)
from src.backtesting.dataset.manifest import DatasetEntry, DatasetManifest
from src.backtesting.dataset.spec import WindowKind
from src.backtesting.job_config import (
    BacktestJobConfig,
    ParquetDataSpec,
    PropFirmSpec,
    VenueSpec,
)
from src.backtesting.result import BacktestResult


pytestmark = pytest.mark.unit


# --- Fixtures ---------------------------------------------------------


def _entry(
    timeframe: str,
    *,
    window_name: str = "in_sample",
    kind: WindowKind = WindowKind.IN_SAMPLE,
    parquet_path: Path = Path("/tmp/cache/XAUUSD/M5/in_sample.parquet"),
    row_count: int = 1000,
) -> DatasetEntry:
    return DatasetEntry(
        timeframe=timeframe,
        window_name=window_name,
        window_kind=kind,
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, tzinfo=UTC),
        parquet_path=parquet_path,
        fingerprint=ContentHashFingerprint(
            min_ts=1_000_000_000, max_ts=2_000_000_000, row_count=row_count
        ),
        row_count=row_count,
    )


def _manifest(entries: tuple[DatasetEntry, ...]) -> DatasetManifest:
    return DatasetManifest(
        spec_name="xauusd-validation",
        dataset_version="1.0.0",
        symbol="XAUUSD",
        generated_at=datetime(2026, 5, 3, 12, tzinfo=UTC),
        max_gap_hours=48.0,
        entries=entries,
    )


def _venue() -> VenueSpec:
    return VenueSpec(
        name="SIM",
        starting_balance=Decimal("100000"),
        currency="USD",
        commission_per_lot_usd=Decimal("7.0"),
    )


def _strategy(name: str, timeframe: str = "M5", **params) -> StrategySpec:
    return StrategySpec(
        name=name,
        timeframe=timeframe,
        bar_type_suffix=timeframe_to_bar_suffix(timeframe),
        params=params,
    )


@dataclass
class _FakeRunner:
    """Captures every job sent to ``run_backtest`` and returns a stub result."""

    jobs: list[BacktestJobConfig] = field(default_factory=list)
    overrides: list[dict[str, Any] | None] = field(default_factory=list)

    def __call__(
        self,
        job: BacktestJobConfig,
        *,
        strategy_overrides: dict[str, Any] | None = None,
    ) -> BacktestResult:
        self.jobs.append(job)
        self.overrides.append(strategy_overrides)
        return BacktestResult(
            strategy_name=job.strategy,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 1, tzinfo=UTC),
            initial_balance=Decimal(job.venue.starting_balance),
            final_balance=Decimal(job.venue.starting_balance),
        )


# --- Tests ------------------------------------------------------------


class TestTimeframeToBarSuffix:
    @pytest.mark.parametrize(
        ("tf", "expected"),
        [
            ("M1", "1-MINUTE-LAST-EXTERNAL"),
            ("M5", "5-MINUTE-LAST-EXTERNAL"),
            ("M15", "15-MINUTE-LAST-EXTERNAL"),
            ("M30", "30-MINUTE-LAST-EXTERNAL"),
            ("H1", "1-HOUR-LAST-EXTERNAL"),
            ("H4", "4-HOUR-LAST-EXTERNAL"),
            ("D1", "1-DAY-LAST-EXTERNAL"),
        ],
    )
    def test_known_timeframes(self, tf: str, expected: str) -> None:
        assert timeframe_to_bar_suffix(tf) == expected

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            timeframe_to_bar_suffix("W1")


class TestStrategySpec:
    def test_label_defaults_to_name(self) -> None:
        s = _strategy("ma_crossover")
        assert s.display_label == "ma_crossover"

    def test_explicit_label_used(self) -> None:
        s = StrategySpec(
            name="ma_crossover",
            timeframe="M5",
            bar_type_suffix="5-MINUTE-LAST-EXTERNAL",
            params={"fast_period": 5},
            label="ma_xover_fast",
        )
        assert s.display_label == "ma_xover_fast"

    def test_is_frozen(self) -> None:
        s = _strategy("ma_crossover")
        with pytest.raises((AttributeError, TypeError)):
            s.name = "other"  # type: ignore[misc]

    def test_params_are_read_only_view(self) -> None:
        # MappingProxyType raises TypeError on mutation. Callers cannot
        # reach back through the spec to alter what the harness saw.
        s = _strategy("ma_crossover", fast_period=5)
        with pytest.raises(TypeError):
            s.params["fast_period"] = 99  # type: ignore[index]

    def test_params_input_dict_decoupled(self) -> None:
        # Mutating the original dict after construction must not bleed
        # into the spec — `__post_init__` copies before wrapping.
        original: dict[str, Any] = {"fast_period": 5}
        s = StrategySpec(
            name="ma_crossover",
            timeframe="M5",
            bar_type_suffix="5-MINUTE-LAST-EXTERNAL",
            params=original,
        )
        original["fast_period"] = 99
        assert s.params["fast_period"] == 5

    def test_rejects_non_json_primitive_param(self) -> None:
        from decimal import Decimal

        with pytest.raises(TypeError, match="JSON-primitive"):
            StrategySpec(
                name="ma_crossover",
                timeframe="M5",
                bar_type_suffix="5-MINUTE-LAST-EXTERNAL",
                params={"risk": Decimal("0.01")},
            )


class TestRunBaselineDispatch:
    def test_dispatches_one_job_per_strategy(self) -> None:
        manifest = _manifest((_entry("M5"), _entry("M15", parquet_path=Path("/tmp/M15.parquet"))))
        cfg = BaselineConfig(
            run_label="phase-12a",
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            strategies=(
                _strategy("ma_crossover", timeframe="M5", fast_period=5, slow_period=20),
                _strategy("supertrend", timeframe="M15", period=10),
            ),
        )
        fake = _FakeRunner()
        results = run_baseline(cfg, runner=fake)

        assert len(results) == 2
        assert len(fake.jobs) == 2
        assert [j.strategy for j in fake.jobs] == ["ma_crossover", "supertrend"]

    def test_routes_each_strategy_to_correct_parquet_shard(self) -> None:
        m5_entry = _entry("M5", parquet_path=Path("/tmp/M5.parquet"))
        m15_entry = _entry("M15", parquet_path=Path("/tmp/M15.parquet"))
        manifest = _manifest((m5_entry, m15_entry))
        cfg = BaselineConfig(
            run_label="phase-12a",
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            strategies=(
                _strategy("ma_crossover", timeframe="M5"),
                _strategy("supertrend", timeframe="M15"),
            ),
        )
        fake = _FakeRunner()
        run_baseline(cfg, runner=fake)

        spec_a = fake.jobs[0].data
        spec_b = fake.jobs[1].data
        assert isinstance(spec_a, ParquetDataSpec)
        assert isinstance(spec_b, ParquetDataSpec)
        assert spec_a.path == Path("/tmp/M5.parquet")
        assert spec_b.path == Path("/tmp/M15.parquet")

    def test_passes_identical_venue_to_all_strategies(self) -> None:
        manifest = _manifest((_entry("M5"),))
        venue = _venue()
        cfg = BaselineConfig(
            run_label="phase-12a",
            manifest=manifest,
            window_name="in_sample",
            venue=venue,
            strategies=(
                _strategy("ma_crossover"),
                _strategy("orb"),
            ),
        )
        fake = _FakeRunner()
        run_baseline(cfg, runner=fake)

        for job in fake.jobs:
            assert job.venue == venue

    def test_attaches_prop_firm_when_provided(self, tmp_path) -> None:
        manifest = _manifest((_entry("M5"),))
        preset_path = tmp_path / "preset.yaml"
        preset_path.write_text("# placeholder\n")
        prop_firm = PropFirmSpec(preset_path=preset_path, account_id="ftmo-1")
        cfg = BaselineConfig(
            run_label="phase-12a",
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            prop_firm=prop_firm,
            strategies=(_strategy("ma_crossover"),),
        )
        fake = _FakeRunner()
        run_baseline(cfg, runner=fake)

        assert fake.jobs[0].prop_firm == prop_firm

    def test_uses_strategy_bar_type_suffix(self) -> None:
        manifest = _manifest((_entry("M5"),))
        cfg = BaselineConfig(
            run_label="phase-12a",
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            strategies=(
                _strategy("orb", timeframe="M5"),
            ),
        )
        fake = _FakeRunner()
        run_baseline(cfg, runner=fake)

        assert fake.jobs[0].bar_type_suffix == "5-MINUTE-LAST-EXTERNAL"

    def test_strategy_params_propagate(self) -> None:
        manifest = _manifest((_entry("M5"),))
        cfg = BaselineConfig(
            run_label="phase-12a",
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            strategies=(
                _strategy("ma_crossover", fast_period=7, slow_period=21),
            ),
        )
        fake = _FakeRunner()
        run_baseline(cfg, runner=fake)

        assert fake.jobs[0].strategy_params == {"fast_period": 7, "slow_period": 21}


class TestConfigSnapshot:
    def _run_one(self, *, runner: Callable | None = None) -> BacktestResult:
        manifest = _manifest((_entry("M5"),))
        cfg = BaselineConfig(
            run_label="phase-12a",
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            strategies=(
                _strategy("ma_crossover", fast_period=5, slow_period=20),
            ),
        )
        return run_baseline(cfg, runner=runner or _FakeRunner())[0]

    def test_snapshot_populated(self) -> None:
        result = self._run_one()
        assert result.config_snapshot is not None

    def test_snapshot_has_dataset_fingerprint(self) -> None:
        result = self._run_one()
        snapshot = result.config_snapshot
        assert snapshot is not None
        ds = snapshot["dataset"]
        assert ds["spec_name"] == "xauusd-validation"
        assert ds["dataset_version"] == "1.0.0"
        assert ds["symbol"] == "XAUUSD"
        assert ds["timeframe"] == "M5"
        assert ds["window_name"] == "in_sample"
        assert ds["fingerprint"]["sha256_short"] == ContentHashFingerprint(
            min_ts=1_000_000_000, max_ts=2_000_000_000, row_count=1000
        ).sha256()

    def test_snapshot_has_strategy_section(self) -> None:
        result = self._run_one()
        snapshot = result.config_snapshot
        assert snapshot is not None
        strat = snapshot["strategy"]
        assert strat["name"] == "ma_crossover"
        assert strat["params"] == {"fast_period": 5, "slow_period": 20}
        assert strat["timeframe"] == "M5"

    def test_snapshot_has_venue_section(self) -> None:
        result = self._run_one()
        snapshot = result.config_snapshot
        assert snapshot is not None
        venue = snapshot["venue"]
        assert venue["starting_balance"] == "100000"
        assert venue["currency"] == "USD"
        assert venue["commission_per_lot_usd"] == "7.0"

    def test_snapshot_records_regime_disabled_baseline(self) -> None:
        result = self._run_one()
        snapshot = result.config_snapshot
        assert snapshot is not None
        # Decision §5: baseline runs with regime classifier disabled.
        assert snapshot["regime_classifier_enabled"] is False

    def test_snapshot_has_run_label(self) -> None:
        result = self._run_one()
        snapshot = result.config_snapshot
        assert snapshot is not None
        assert snapshot["run_label"] == "phase-12a"


class TestErrors:
    def test_missing_window_raises(self) -> None:
        manifest = _manifest((_entry("M5"),))
        cfg = BaselineConfig(
            run_label="phase-12a",
            manifest=manifest,
            window_name="oos_reserve",  # not in manifest
            venue=_venue(),
            strategies=(_strategy("ma_crossover"),),
        )
        with pytest.raises(UnknownDatasetEntryError, match="oos_reserve"):
            run_baseline(cfg, runner=_FakeRunner())

    def test_missing_timeframe_raises(self) -> None:
        manifest = _manifest((_entry("M5"),))
        cfg = BaselineConfig(
            run_label="phase-12a",
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            strategies=(_strategy("supertrend", timeframe="M15"),),
        )
        with pytest.raises(UnknownDatasetEntryError, match="M15"):
            run_baseline(cfg, runner=_FakeRunner())

    def test_empty_strategies_returns_empty(self) -> None:
        manifest = _manifest((_entry("M5"),))
        cfg = BaselineConfig(
            run_label="phase-12a",
            manifest=manifest,
            window_name="in_sample",
            venue=_venue(),
            strategies=(),
        )
        results = run_baseline(cfg, runner=_FakeRunner())
        assert results == []

    def test_duplicate_strategy_label_rejected(self) -> None:
        manifest = _manifest((_entry("M5"),))
        # Two strategies with the same label must not coexist — the
        # comparison report (12.3) keys results by label.
        cfg_kwargs = {
            "run_label": "phase-12a",
            "manifest": manifest,
            "window_name": "in_sample",
            "venue": _venue(),
            "strategies": (
                _strategy("ma_crossover"),
                _strategy("ma_crossover"),  # same name → same default label
            ),
        }
        with pytest.raises(ValueError, match="duplicate"):
            BaselineConfig(**cfg_kwargs)
