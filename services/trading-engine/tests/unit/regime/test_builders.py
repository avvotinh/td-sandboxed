"""Unit tests for the lifted regime extractor builder (Epic 15 story 15.1)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.indicators.adx import ADX
from src.indicators.bb_width import BollingerBandWidth
from src.indicators.ema_slope import EMASlope
from src.indicators.realized_vol import RealizedVolatility
from src.regime.builders import build_extractor
from src.regime.features import FeatureExtractor


def _cfg() -> SimpleNamespace:
    # build_extractor only reads these attributes off the InstrumentRegimeConfig;
    # a stub keeps the unit test free of the full firm-profile pydantic model.
    return SimpleNamespace(
        adx_period=14,
        bb_period=20,
        bb_stddev=2.0,
        bb_baseline_window=200,
        realized_vol_window=20,
        ema_slope_period=50,
        ema_slope_lookback=5,
    )


@pytest.mark.unit
class TestBuildExtractor:
    def test_returns_feature_extractor_with_bar_type_and_warmup(self) -> None:
        ext = build_extractor("XAUUSD.SIM-5-MINUTE-LAST-EXTERNAL", _cfg(), warmup_bars=200)
        assert isinstance(ext, FeatureExtractor)
        assert ext.bar_type == "XAUUSD.SIM-5-MINUTE-LAST-EXTERNAL"
        assert ext.warmup_bars == 200

    def test_wires_all_four_indicators(self) -> None:
        ext = build_extractor("EURUSD.SIM-15-MINUTE-LAST-EXTERNAL", _cfg(), warmup_bars=50)
        assert isinstance(ext._adx, ADX)
        assert isinstance(ext._bb_width, BollingerBandWidth)
        assert isinstance(ext._realized_vol, RealizedVolatility)
        assert isinstance(ext._ema_slope, EMASlope)

    def test_per_bar_type_isolation(self) -> None:
        # The factory builds one extractor per bar_type; the indicator
        # instances must NOT be shared across streams (would cross-contaminate
        # M5 and M15 state).
        a = build_extractor("XAUUSD.SIM-5-MINUTE-LAST-EXTERNAL", _cfg(), warmup_bars=200)
        b = build_extractor("XAUUSD.SIM-15-MINUTE-LAST-EXTERNAL", _cfg(), warmup_bars=200)
        assert a is not b
        assert a._adx is not b._adx
        assert a._ema_slope is not b._ema_slope
