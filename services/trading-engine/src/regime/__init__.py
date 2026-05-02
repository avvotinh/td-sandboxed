"""Market regime classification — Phase 1 (rule-based).

Classifies market state into discrete regimes
(``TRENDING_UP``/``TRENDING_DOWN``/``RANGING``/``HIGH_VOLATILITY``) so the
strategy router can dispatch bars only to strategies suited for the
current regime. Phase 1 uses a deterministic rule-based classifier on
ADX + Bollinger band width + realized volatility + EMA slope. Phase 2
will replace the classifier with a Hidden Markov Model.

See ``docs/research/regime-classifier.md`` and
``docs/research/regime-classifier-architecture.md`` for the full design.
"""

from __future__ import annotations

from src.regime.audit import RegimeAuditAdapter
from src.regime.classifier import RuleBasedRegimeClassifier
from src.regime.decision import RegimeDecision
from src.regime.factory import build_regime_aware_router
from src.regime.features import FeatureExtractor, RegimeFeatures
from src.regime.hysteresis import HysteresisFilter
from src.regime.states import RegimeState

__all__ = [
    "FeatureExtractor",
    "HysteresisFilter",
    "RegimeAuditAdapter",
    "RegimeDecision",
    "RegimeFeatures",
    "RegimeState",
    "RuleBasedRegimeClassifier",
    "build_regime_aware_router",
]
