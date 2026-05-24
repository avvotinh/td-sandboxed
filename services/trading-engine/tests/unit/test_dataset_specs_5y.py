"""Validate the Epic 16 5-year acquisition dataset specs load + parse.

Guards the four ``configs/datasets/<symbol>-5y.yaml`` files against
schema drift / typos: each must round-trip through
:meth:`DatasetSpec.from_yaml`, carry the 4 acquisition timeframes, the
in_sample + oos_reserve windows, and a whitelisted symbol. The repo-root
``configs/`` dir is resolved relative to this test file so it works from
any CWD.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backtesting.dataset.spec import DatasetSpec, WindowKind

# test file → unit → tests → trading-engine → services → repo root
_DATASETS_DIR = (
    Path(__file__).resolve().parents[4] / "configs" / "datasets"
)

_EXPECTED_SYMBOL = {
    "xauusd-5y.yaml": "XAUUSD",
    "eurusd-5y.yaml": "EURUSD",
    "gbpusd-5y.yaml": "GBPUSD",
    "usdjpy-5y.yaml": "USDJPY",
}


@pytest.mark.unit
@pytest.mark.parametrize("filename", sorted(_EXPECTED_SYMBOL))
class TestFiveYearDatasetSpecs:
    def test_loads_and_symbol_matches(self, filename: str) -> None:
        spec = DatasetSpec.from_yaml(_DATASETS_DIR / filename)
        assert spec.symbol == _EXPECTED_SYMBOL[filename]

    def test_acquisition_timeframes(self, filename: str) -> None:
        spec = DatasetSpec.from_yaml(_DATASETS_DIR / filename)
        assert spec.timeframes == ("M5", "M15", "H1", "H4")

    def test_in_sample_then_oos_reserve_windows(self, filename: str) -> None:
        spec = DatasetSpec.from_yaml(_DATASETS_DIR / filename)
        kinds = {w.name: w.kind for w in spec.windows}
        assert kinds["in_sample"] == WindowKind.IN_SAMPLE
        assert kinds["oos_reserve"] == WindowKind.OOS_RESERVE

    def test_oos_reserve_is_held_out_after_in_sample(self, filename: str) -> None:
        # OOS must start exactly where in_sample ends — no overlap, no gap.
        spec = DatasetSpec.from_yaml(_DATASETS_DIR / filename)
        by_name = {w.name: w for w in spec.windows}
        assert by_name["oos_reserve"].start == by_name["in_sample"].end
