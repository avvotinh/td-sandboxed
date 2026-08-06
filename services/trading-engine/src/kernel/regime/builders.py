"""Shared constructors for regime components (Epic 15 story 15.1).

``build_extractor`` lives here (not beside an actor/router factory) so
``build_regime_actor`` (story 15.6) can construct a :class:`FeatureExtractor`
from an :class:`InstrumentRegimeConfig` without dragging in the strategy/actor
wiring — keeping this the single place that knows how a
:class:`FeatureExtractor` is assembled from config and avoiding an import
cycle through the Nautilus actor module.
"""

from __future__ import annotations

from src.config.firm_profile import InstrumentRegimeConfig
from src.kernel.indicators.adx import ADX
from src.kernel.indicators.bb_width import BollingerBandWidth
from src.kernel.indicators.ema_slope import EMASlope
from src.kernel.indicators.realized_vol import RealizedVolatility
from src.kernel.regime.features import FeatureExtractor


def build_extractor(
    bar_type: str,
    instrument_cfg: InstrumentRegimeConfig,
    warmup_bars: int,
) -> FeatureExtractor:
    """Assemble the four regime indicators + extractor for one ``bar_type``.

    Periods/windows come from the per-instrument config so FTMO and The5ers
    can calibrate independently. The single source of truth for which
    indicators back the rule-based classifier.
    """
    return FeatureExtractor(
        bar_type=bar_type,
        adx=ADX(period=instrument_cfg.adx_period),
        bb_width=BollingerBandWidth(
            period=instrument_cfg.bb_period,
            num_std=instrument_cfg.bb_stddev,
            baseline_window=instrument_cfg.bb_baseline_window,
        ),
        realized_vol=RealizedVolatility(window=instrument_cfg.realized_vol_window),
        ema_slope=EMASlope(
            period=instrument_cfg.ema_slope_period,
            lookback=instrument_cfg.ema_slope_lookback,
        ),
        warmup_bars=warmup_bars,
    )


__all__ = ["build_extractor"]
