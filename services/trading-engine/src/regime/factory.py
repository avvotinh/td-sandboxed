"""Bootstrap factory for the regime-aware router (Epic 11 story 11.7).

When ``regime_config.enabled`` is ``False`` (the shipped default) the
factory returns the inner router unchanged — zero overhead, zero
behaviour change. When enabled, it builds one
:class:`FeatureExtractor` and one :class:`HysteresisFilter` per unique
``bar_type`` across the inner's bound accounts, plus the shared
:class:`RuleBasedRegimeClassifier` and :class:`RegimeAuditAdapter`,
and wires them into a :class:`RegimeAwareRouter`.

Symbols are derived from each ``bar_type`` string (e.g. the leading
``XAUUSD`` token of ``XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL``) so the
factory can pull the matching :class:`InstrumentRegimeConfig` from the
firm profile without an extra mapping table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from src.config.firm_profile import InstrumentRegimeConfig, RegimeConfig
from src.indicators.adx import ADX
from src.indicators.bb_width import BollingerBandWidth
from src.indicators.ema_slope import EMASlope
from src.indicators.realized_vol import RealizedVolatility
from src.regime.audit import RegimeAuditAdapter
from src.regime.classifier import RuleBasedRegimeClassifier
from src.regime.features import FeatureExtractor
from src.regime.hysteresis import HysteresisFilter
from src.regime.states import RegimeState
from src.rules.audit_logger import AuditEntry
from src.strategies.regime_routing import RegimeAwareRouter

if TYPE_CHECKING:
    from src.strategies.data_router import StrategyDataRouter


class _AuditWriter(Protocol):
    async def log_async(self, entry: AuditEntry) -> None: ...


def _symbol_from_bar_type(bar_type: str) -> str:
    """Extract the symbol leg from a NautilusTrader BarType string.

    ``XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL`` → ``XAUUSD``.
    """
    if not bar_type or "." not in bar_type:
        raise ValueError(
            f"bar_type {bar_type!r} is not in expected SYMBOL.VENUE-... form"
        )
    return bar_type.split(".", 1)[0]


def _build_extractor(
    bar_type: str, instrument_cfg: InstrumentRegimeConfig, warmup_bars: int
) -> FeatureExtractor:
    return FeatureExtractor(
        bar_type=bar_type,
        adx=ADX(period=instrument_cfg.adx_period),
        bb_width=BollingerBandWidth(
            period=instrument_cfg.bb_period,
            num_std=instrument_cfg.bb_stddev,
            baseline_window=instrument_cfg.bb_baseline_window,
        ),
        realized_vol=RealizedVolatility(
            window=instrument_cfg.realized_vol_window
        ),
        ema_slope=EMASlope(
            period=instrument_cfg.ema_slope_period,
            lookback=instrument_cfg.ema_slope_lookback,
        ),
        warmup_bars=warmup_bars,
    )


def build_regime_aware_router(
    inner: StrategyDataRouter,
    regime_config: RegimeConfig,
    audit_writer: _AuditWriter,
    strategy_regime_map: dict[str, frozenset[RegimeState] | None] | None = None,
) -> StrategyDataRouter | RegimeAwareRouter:
    """Wrap ``inner`` if the regime classifier is enabled, else return it.

    Args:
        inner: The plain data router that the regime wrapper delegates to.
        regime_config: Firm-level config block. ``enabled=False`` (shipped
            default) short-circuits with no wrapping.
        audit_writer: Project-wide :class:`AuditWriter` (story 10.3).
        strategy_regime_map: Optional pre-built map. If omitted, the
            factory pulls the live snapshot from
            :meth:`StrategyRegistry.get_all_regime_maps`.

    Returns:
        Either the original ``inner`` (disabled path) or a fully-wired
        :class:`RegimeAwareRouter` instance. Both expose the same
        ``route_bar`` / ``route_bar_async`` callback surface.
    """
    if not regime_config.enabled:
        return inner

    # Sorted so the "first instrument" classifier shortcut below is
    # deterministic across restarts; a set's iteration order is not.
    bar_types = sorted(
        {
            str(account.strategy_instance.config.bar_type)
            for account in inner.bound_accounts
            if account.strategy_instance is not None
        }
    )
    if not bar_types:
        # No bound strategies → no streams to gate; return the inner so
        # operators flipping the flag on an empty engine don't see it
        # break. The empty case is logically equivalent to enabled=False.
        return inner

    symbols = {_symbol_from_bar_type(bt) for bt in bar_types}
    if len(symbols) > 1:
        # Phase 1 ships a single classifier instance fed by one
        # instrument's thresholds. Multiple symbols would either need
        # per-symbol classifiers or a single threshold set covering all
        # — neither has been validated. Fail loudly rather than silently
        # classify EURUSD against XAUUSD's calibration.
        raise NotImplementedError(
            "RegimeConfig wiring supports a single instrument in Phase 1; "
            f"got symbols={sorted(symbols)}. Phase 2 will introduce "
            "per-symbol classifier instances."
        )

    extractors: dict[str, FeatureExtractor] = {}
    hysteresis: dict[str, HysteresisFilter] = {}
    for bt in bar_types:
        symbol = _symbol_from_bar_type(bt)
        instrument_cfg = regime_config.get_instrument(symbol)
        extractors[bt] = _build_extractor(
            bt, instrument_cfg, regime_config.warmup_bars
        )
        hysteresis[bt] = HysteresisFilter(
            bar_type=bt,
            confirmation_bars=regime_config.confirmation_bars,
            thresholds=instrument_cfg.thresholds,
        )

    if strategy_regime_map is None:
        from src.strategies.registry import StrategyRegistry

        strategy_regime_map = dict(StrategyRegistry.get_all_regime_maps())

    primary_symbol = next(iter(symbols))
    classifier = RuleBasedRegimeClassifier(
        regime_config.get_instrument(primary_symbol).thresholds
    )

    return RegimeAwareRouter(
        inner=inner,
        classifier=classifier,
        feature_extractors=extractors,
        hysteresis=hysteresis,
        audit=RegimeAuditAdapter(audit_writer),
        strategy_regime_map=strategy_regime_map,
    )


__all__ = ["build_regime_aware_router"]
