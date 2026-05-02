"""Regime-aware bar routing (Epic 11 story 11.7).

Wraps :class:`StrategyDataRouter` so each bar runs through the regime
classifier pipeline before per-account dispatch. The router presents
the same callback surface (``route_bar`` / ``route_bar_async``) so the
existing ``redis_adapter.set_bar_callback`` wiring works unchanged.

Per-bar pipeline:

1. Look up the per-``BarType`` :class:`FeatureExtractor`. A bar whose
   ``bar_type`` is unknown to the router is logged at WARNING and
   skipped — the router cannot reason about regimes for streams it was
   not configured to handle.
2. Update the extractor. ``None`` means warmup is incomplete; with the
   classifier output undefined, neither audit nor routing fires.
3. Run :class:`RuleBasedRegimeClassifier` on the features.
4. Confirm via the per-``BarType`` :class:`HysteresisFilter`.
5. **Audit before routing.** The audit hop is awaited (async path) or
   scheduled with ``asyncio.create_task`` (sync path) before any
   strategy dispatch — FTMO compliance pattern matches existing
   :class:`RuleEngine`.
6. ``HIGH_VOLATILITY`` is the global kill-switch: every account is
   skipped, including those registered with ``regimes=None``
   (always-allow).
7. For the remaining states, each bound account is admitted iff the
   classifier output is in the strategy's declared regime allow-list,
   or the strategy declared no allow-list at all.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Protocol

from src.regime.audit import RegimeAuditAdapter
from src.regime.classifier import RuleBasedRegimeClassifier
from src.regime.features import RegimeFeatures
from src.regime.hysteresis import HysteresisFilter
from src.regime.states import RegimeState

logger = logging.getLogger(__name__)


class _InnerRouter(Protocol):
    """Subset of :class:`StrategyDataRouter` the wrapper consumes."""

    @property
    def bound_accounts(self) -> list[Any]: ...

    def _route_bar_to_account(self, account: Any, bar: Any) -> None: ...

    def route_tick(self, tick: Any) -> None: ...

    async def route_tick_async(self, tick: Any) -> None: ...


class _ExtractorProtocol(Protocol):
    def update(self, bar: Any) -> RegimeFeatures | None: ...


class RegimeAwareRouter:
    """Drop-in replacement for :class:`StrategyDataRouter` adding regime gating."""

    def __init__(
        self,
        inner: _InnerRouter,
        classifier: RuleBasedRegimeClassifier,
        feature_extractors: Mapping[str, _ExtractorProtocol],
        hysteresis: Mapping[str, HysteresisFilter],
        audit: RegimeAuditAdapter,
        strategy_regime_map: Mapping[str, frozenset[RegimeState] | None],
    ) -> None:
        self._inner = inner
        self._classifier = classifier
        self._extractors = feature_extractors
        self._hysteresis = hysteresis
        self._audit = audit
        # Defensive snapshot: caller-supplied dicts are mutable, and a
        # post-construction mutation would silently change routing
        # decisions without re-issuing the audit row.
        self._regime_map = MappingProxyType(dict(strategy_regime_map))

    async def route_bar_async(self, bar: Any) -> None:
        bar_type = str(bar.bar_type)
        extractor = self._extractors.get(bar_type)
        if extractor is None:
            logger.warning(
                "RegimeAwareRouter: no extractor for bar_type %r — skipping bar",
                bar_type,
            )
            return

        features = extractor.update(bar)
        if features is None:
            return  # warmup incomplete; no audit, no dispatch

        raw_state = self._classifier.decide(features)
        decision = self._hysteresis[bar_type].apply(
            raw_state, bar.ts_event, features
        )

        # Audit before routing — FTMO double-entry discipline.
        await self._audit.log(decision)

        self._dispatch(decision.current_state, bar)

    def route_bar(self, bar: Any) -> None:
        """Schedule the regime pipeline as an event-loop task.

        Sync path matches the existing ``redis_adapter.set_bar_callback``
        signature and is invoked from inside the event loop. The audit-
        before-routing guarantee holds **inside the scheduled task** (the
        task awaits audit before dispatch), but ``route_bar`` itself
        returns before either has run. Callers that need the audit row
        visible to subsequent synchronous work must yield to the loop
        first; new call sites should prefer :meth:`route_bar_async`.
        """
        asyncio.create_task(self.route_bar_async(bar))

    def route_tick(self, tick: Any) -> None:
        """Pass tick data through to the inner router unchanged.

        Regime classification is a per-bar decision; ticks are not gated.
        Exposed so the existing ``zmq_adapter.set_tick_callback`` wiring
        can target the wrapper without a surprise ``AttributeError``.
        """
        self._inner.route_tick(tick)

    async def route_tick_async(self, tick: Any) -> None:
        await self._inner.route_tick_async(tick)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _dispatch(self, state: RegimeState, bar: Any) -> None:
        if state == RegimeState.HIGH_VOLATILITY:
            return  # global kill-switch
        for account in self._inner.bound_accounts:
            allowed = self._regime_map.get(account.strategy)
            if allowed is None or state in allowed:
                self._inner._route_bar_to_account(account, bar)


__all__ = ["RegimeAwareRouter"]
