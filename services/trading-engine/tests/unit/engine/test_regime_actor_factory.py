"""Story 15.6 — shared regime-actor factory tests.

``build_regime_actor`` mirrors ``build_compliance_actor``: collaborators in,
actor out, used identically by the backtest (``attach_regime``, story 15.8) and
live (``node_factory`` / ``LiveOrchestrator``, story 15.10/15.11) paths so the
regime pipeline cannot drift between simulation and production. ``enabled=False``
returns ``None`` (zero overhead, the shipped default).
"""
from __future__ import annotations

import pytest

from nautilus_trader.model.data import BarType

from src.config.firm_profile import (
    InstrumentRegimeConfig,
    RegimeConfig,
    RegimeThresholds,
)
from src.engine.actors import build_regime_actor
from src.kernel.regime.actor import RegimeActor
from src.kernel.regime.classifier import RuleBasedRegimeClassifier
from src.kernel.regime.hysteresis import HysteresisFilter
from src.kernel.regime.state_store import RegimeStateStore
from src.rules.audit_logger import AuditEntry

pytestmark = pytest.mark.unit

BAR_TYPE = BarType.from_str("XAUUSD.SIM-5-MINUTE-LAST-EXTERNAL")
BAR_TYPE_STR = "XAUUSD.SIM-5-MINUTE-LAST-EXTERNAL"


def _thresholds() -> RegimeThresholds:
    return RegimeThresholds(
        adx_trend_min=20.0,
        adx_strong_trend=40.0,
        bb_width_low_pct=0.1,
        bb_width_high_pct=0.5,
        realized_vol_high=0.02,
        ema_slope_trend_threshold=0.001,
    )


def _instrument_cfg() -> InstrumentRegimeConfig:
    return InstrumentRegimeConfig(
        timeframe="M5",
        thresholds=_thresholds(),
        adx_period=14,
        bb_period=20,
        bb_stddev=2.0,
        bb_baseline_window=200,
        realized_vol_window=20,
        ema_slope_period=50,
        ema_slope_lookback=5,
    )


def _regime_config(
    *, enabled: bool = True, symbol: str = "XAUUSD"
) -> RegimeConfig:
    return RegimeConfig(
        enabled=enabled,
        confirmation_bars=2,
        warmup_bars=200,
        feature_window=200,
        instruments={symbol: _instrument_cfg()},
    )


class TestDisabled:
    def test_disabled_returns_none(self) -> None:
        # Shipped default: no actor, no extractor, zero overhead. The caller
        # leaves the strategy's store unset → _regime_admits returns True
        # (byte-identical to today).
        actor = build_regime_actor(
            regime_config=_regime_config(enabled=False),
            bar_type=BAR_TYPE,
            regime_state=RegimeStateStore(),
        )
        assert actor is None


class TestEnabled:
    def test_returns_regime_actor(self) -> None:
        actor = build_regime_actor(
            regime_config=_regime_config(),
            bar_type=BAR_TYPE,
            regime_state=RegimeStateStore(),
        )
        assert isinstance(actor, RegimeActor)

    def test_primary_symbol_derived_from_bar_type(self) -> None:
        actor = build_regime_actor(
            regime_config=_regime_config(),
            bar_type=BAR_TYPE,
            regime_state=RegimeStateStore(),
        )
        assert actor is not None
        assert actor._config.primary_symbol == "XAUUSD"

    def test_bar_type_set_for_subscription(self) -> None:
        # The actor subscribes to this BarType on_start — must be the real
        # Nautilus object, not None.
        actor = build_regime_actor(
            regime_config=_regime_config(),
            bar_type=BAR_TYPE,
            regime_state=RegimeStateStore(),
        )
        assert actor is not None
        assert actor._config.bar_type == BAR_TYPE


class TestSingleSourceOfTruth:
    def test_single_extractor_built_for_bar_type(self) -> None:
        # SSOT: the actor owns the one FeatureExtractor for its bar_type,
        # keyed by the string form the hysteresis/store use.
        actor = build_regime_actor(
            regime_config=_regime_config(),
            bar_type=BAR_TYPE,
            regime_state=RegimeStateStore(),
        )
        assert actor is not None
        assert actor._extractor.bar_type == BAR_TYPE_STR
        # warmup_bars is passed through from the config, not hardcoded.
        assert actor._extractor.warmup_bars == _regime_config().warmup_bars

    def test_shared_store_is_the_injected_object(self) -> None:
        # The caller injects this exact store into the strategy too (15.7/15.8);
        # identity must be preserved or the strategy reads a different store.
        store = RegimeStateStore()
        actor = build_regime_actor(
            regime_config=_regime_config(),
            bar_type=BAR_TYPE,
            regime_state=store,
        )
        assert actor is not None
        assert actor._regime_state is store


class TestPipelineWiring:
    def test_classifier_uses_instrument_thresholds(self) -> None:
        cfg = _regime_config()
        actor = build_regime_actor(
            regime_config=cfg,
            bar_type=BAR_TYPE,
            regime_state=RegimeStateStore(),
        )
        assert actor is not None
        assert isinstance(actor._classifier, RuleBasedRegimeClassifier)
        assert actor._classifier.thresholds == cfg.get_instrument("XAUUSD").thresholds

    def test_hysteresis_from_config(self) -> None:
        cfg = _regime_config()
        actor = build_regime_actor(
            regime_config=cfg,
            bar_type=BAR_TYPE,
            regime_state=RegimeStateStore(),
        )
        assert actor is not None
        assert isinstance(actor._hysteresis, HysteresisFilter)
        assert actor._hysteresis.bar_type == BAR_TYPE_STR
        assert actor._hysteresis.confirmation_bars == 2
        assert actor._hysteresis.thresholds == cfg.get_instrument("XAUUSD").thresholds


class TestAuditHook:
    def test_no_hook_means_audit_to_db_false(self) -> None:
        # Backtest path (R-E): no hook → audit_to_db False → zero rows to the
        # live audit_logs hypertable.
        actor = build_regime_actor(
            regime_config=_regime_config(),
            bar_type=BAR_TYPE,
            regime_state=RegimeStateStore(),
        )
        assert actor is not None
        assert actor._config.audit_to_db is False
        assert actor._audit_hook is None

    def test_hook_enables_audit_to_db(self) -> None:
        # Live path (15.11): a hook over the existing AuditWriter queue → the
        # factory turns audit_to_db on so the actor emits, and can never produce
        # the (audit_to_db=True, hook=None) misconfiguration.
        def hook(_entry: AuditEntry) -> None:
            return None

        actor = build_regime_actor(
            regime_config=_regime_config(),
            bar_type=BAR_TYPE,
            regime_state=RegimeStateStore(),
            audit_hook=hook,
        )
        assert actor is not None
        assert actor._config.audit_to_db is True
        assert actor._audit_hook is hook


class TestUnknownSymbol:
    def test_unknown_symbol_raises_keyerror(self) -> None:
        # bar_type's symbol has no InstrumentRegimeConfig → fail loudly rather
        # than classify against the wrong instrument's calibration.
        cfg = _regime_config(symbol="EURUSD")
        with pytest.raises(KeyError):
            build_regime_actor(
                regime_config=cfg,
                bar_type=BAR_TYPE,  # XAUUSD — not configured
                regime_state=RegimeStateStore(),
            )
