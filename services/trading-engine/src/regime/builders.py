"""Shared constructors for regime components (Epic 15 story 15.1).

``build_extractor`` is lifted here out of :mod:`src.regime.factory` so the
forthcoming ``build_regime_actor`` (story 15.6) can construct a
:class:`FeatureExtractor` from an :class:`InstrumentRegimeConfig` **without**
importing ``factory`` — which pulls in ``strategies.regime_routing`` and would
create an import cycle through the Nautilus actor wiring. The factory keeps
calling this same function, so there is exactly one place that knows how a
``FeatureExtractor`` is assembled from config.
"""

from __future__ import annotations

from src.config.firm_profile import InstrumentRegimeConfig
from src.indicators.adx import ADX
from src.indicators.bb_width import BollingerBandWidth
from src.indicators.ema_slope import EMASlope
from src.indicators.realized_vol import RealizedVolatility
from src.regime.features import FeatureExtractor


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
