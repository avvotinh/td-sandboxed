"""Unit tests for RegimeFeatures + FeatureExtractor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest
from nautilus_trader.model.data import Bar

from src.indicators.adx import ADX
from src.indicators.bb_width import BollingerBandWidth
from src.indicators.ema_slope import EMASlope
from src.indicators.realized_vol import RealizedVolatility
from src.regime.features import FeatureExtractor, RegimeFeatures

pytestmark = pytest.mark.unit


def _make_extractor(warmup_bars: int = 30) -> FeatureExtractor:
    return FeatureExtractor(
        bar_type="XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL",
        adx=ADX(period=5),
        bb_width=BollingerBandWidth(period=10, num_std=2.0, baseline_window=20),
        realized_vol=RealizedVolatility(window=10, annualisation_factor=1.0),
        ema_slope=EMASlope(period=10, lookback=5),
        warmup_bars=warmup_bars,
    )


class TestRegimeFeaturesDataclass:
    def test_is_frozen(self) -> None:
        features = RegimeFeatures(
            adx=20.0,
            plus_di=15.0,
            minus_di=10.0,
            bb_width_pct=0.5,
            realized_vol=0.02,
            ema_slope=0.001,
            is_warmed_up=True,
        )
        with pytest.raises(FrozenInstanceError):
            features.adx = 30.0  # type: ignore[misc]

    def test_field_count(self) -> None:
        from dataclasses import fields

        names = {f.name for f in fields(RegimeFeatures)}
        assert names == {
            "adx",
            "plus_di",
            "minus_di",
            "bb_width_pct",
            "realized_vol",
            "ema_slope",
            "is_warmed_up",
        }

    def test_can_be_unwarmed(self) -> None:
        """Tests can construct unwarmed features for classifier UNKNOWN tests."""
        features = RegimeFeatures(
            adx=0.0,
            plus_di=0.0,
            minus_di=0.0,
            bb_width_pct=0.0,
            realized_vol=0.0,
            ema_slope=0.0,
            is_warmed_up=False,
        )
        assert features.is_warmed_up is False


class TestFeatureExtractorWarmup:
    def test_returns_none_before_warmup_bars(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        extractor = _make_extractor(warmup_bars=30)
        for i in range(10):
            assert extractor.update(make_bar(close=2400.0 + i)) is None

    def test_warmup_progress_grows_monotonically(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        extractor = _make_extractor(warmup_bars=30)
        progresses: list[float] = []
        for i in range(40):
            extractor.update(make_bar(close=2400.0 + i))
            progresses.append(extractor.warmup_progress)
        assert progresses[0] < progresses[10]
        assert progresses[10] < progresses[29]
        # Caps at 1.0 once warmup_bars reached.
        assert progresses[-1] == 1.0
        # Monotonic non-decreasing.
        for a, b in zip(progresses, progresses[1:], strict=False):
            assert b >= a

    def test_returns_features_after_warmup(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        extractor = _make_extractor(warmup_bars=30)
        result = None
        for i in range(40):
            result = extractor.update(make_bar(close=2400.0 + i))
        assert isinstance(result, RegimeFeatures)
        assert result.is_warmed_up is True


class TestFeatureExtractorOutput:
    def test_features_reflect_uptrend(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        extractor = _make_extractor(warmup_bars=30)
        result = None
        for i in range(50):
            result = extractor.update(make_bar(close=2400.0 + i * 1.5))
        assert result is not None
        assert result.ema_slope > 0
        assert result.plus_di > result.minus_di
        # Strong steady trend → ADX rises above 25.
        assert result.adx > 25

    def test_features_reflect_downtrend(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        extractor = _make_extractor(warmup_bars=30)
        result = None
        for i in range(50):
            result = extractor.update(make_bar(close=2400.0 - i * 1.5))
        assert result is not None
        assert result.ema_slope < 0
        assert result.minus_di > result.plus_di

    def test_features_reflect_flat_ranging(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        extractor = _make_extractor(warmup_bars=30)
        result = None
        for _ in range(50):
            result = extractor.update(make_bar(close=2400.0))
        assert result is not None
        assert result.ema_slope == pytest.approx(0.0, abs=1e-9)
        assert result.realized_vol == pytest.approx(0.0)


class TestFeatureExtractorEdgeCases:
    def test_invalid_warmup_bars_raises(self) -> None:
        with pytest.raises(ValueError, match="warmup_bars"):
            FeatureExtractor(
                bar_type="X",
                adx=ADX(period=5),
                bb_width=BollingerBandWidth(period=5, num_std=2.0, baseline_window=10),
                realized_vol=RealizedVolatility(window=5),
                ema_slope=EMASlope(period=5, lookback=3),
                warmup_bars=0,
            )

    def test_empty_bar_type_raises(self) -> None:
        with pytest.raises(ValueError, match="bar_type"):
            FeatureExtractor(
                bar_type="",
                adx=ADX(period=5),
                bb_width=BollingerBandWidth(period=5, num_std=2.0, baseline_window=10),
                realized_vol=RealizedVolatility(window=5),
                ema_slope=EMASlope(period=5, lookback=3),
                warmup_bars=10,
            )

    def test_returns_none_if_indicators_not_initialized(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        """Even past warmup_bars, features only emerge once every indicator
        has reported its first value."""
        # Use a small warmup_bars so the bar count check passes early, but
        # an indicator (ADX) needs ~2*period bars to initialize.
        extractor = FeatureExtractor(
            bar_type="X",
            adx=ADX(period=14),  # needs 28 bars
            bb_width=BollingerBandWidth(period=5, num_std=2.0, baseline_window=10),
            realized_vol=RealizedVolatility(window=5),
            ema_slope=EMASlope(period=5, lookback=3),
            warmup_bars=10,
        )
        # At 15 bars the warmup_bars threshold (10) is met, but ADX(14) is
        # not yet initialised — extractor must still return None.
        result = None
        for i in range(15):
            result = extractor.update(make_bar(close=2400.0 + i))
        assert result is None

    def test_all_indicators_isolated_per_extractor(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        """Two extractors with independent indicators must not share state."""
        ext1 = _make_extractor(warmup_bars=15)
        ext2 = _make_extractor(warmup_bars=15)
        for i in range(30):
            ext1.update(make_bar(close=2400.0 + i * 2.0))   # uptrend
            ext2.update(make_bar(close=2400.0 - i * 2.0))   # downtrend
        f1 = ext1.update(make_bar(close=2460.0))
        f2 = ext2.update(make_bar(close=2340.0))
        assert f1 is not None and f2 is not None
        assert f1.ema_slope > 0
        assert f2.ema_slope < 0
