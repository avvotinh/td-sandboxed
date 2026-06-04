"""``RegimeActor`` — regime classification as a NautilusTrader ``Actor`` (Epic 15 story 15.5).

Epic 11 ran the regime pipeline inside ``RegimeAwareRouter``, an external
bar-dispatch wrapper that gated by *withholding* the bar from disallowed
strategies. That router is wired into neither backtest nor live (see
``docs/epic-15-context.md``). A Nautilus ``Actor`` **cannot withhold** a bar —
the engine delivers every subscribed bar to every subscriber — so the model
inverts: the actor runs the **unchanged** classify → hysteresis pipeline in
``on_bar`` and *publishes* the confirmed regime into a shared
:class:`RegimeStateStore`. Strategies read that store at their entry-only order
seam (story 15.7) and suppress disallowed entries themselves. This is the same
inversion the compliance actor made (it became a reactive tracker because it
cannot prevent a fill) and gives a single pipeline that runs **identically in
backtest and live** — the epic's whole point.

Ordering: story 15.4 proved Nautilus dispatches ``Actor.on_bar`` before
``Strategy.on_bar`` for the same ``BarType`` regardless of add-order, so the
strategy reads the *current* bar's regime (same-bar contract; no one-bar-lag).

Audit (review **R-D**): a regime decision is *telemetry of a gating decision*,
not an ``account.*`` mutation (``account_id`` is ``None``), so the strict
audit-before-mutation double-entry rule does not apply and there is **no
dedicated buffer / deque**. The actor exposes a single synchronous
:data:`RegimeAuditHook`:

* **Backtest** (default, ``audit_to_db=False``): no hook → zero rows to the live
  ``audit_logs`` hypertable (review **R-E**), and the actor never touches an
  asyncio loop or the DB.
* **Live** (story 15.11, ``audit_to_db=True``): the hook is a closure that
  enqueues onto the *existing* bounded ``AuditWriter`` queue. Because ``on_bar``
  is sync and the queue is async, the closure uses a non-blocking enqueue and
  **degrades gracefully** (drop + warn on a full queue) — losing a telemetry row
  must never break regime publishing. A hook exception is therefore caught here,
  logged, and swallowed; publishing still happens.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.model.data import Bar, BarType

from src.regime.audit import to_audit_entry
from src.regime.classifier import RuleBasedRegimeClassifier
from src.regime.features import FeatureExtractor
from src.regime.hysteresis import HysteresisFilter
from src.regime.state_store import RegimeStateStore
from src.rules.audit_logger import AuditEntry

logger = logging.getLogger(__name__)

# A synchronous, non-blocking audit sink. Live wiring (15.11) binds this to a
# closure over the existing ``AuditWriter`` queue; backtest leaves it ``None``.
RegimeAuditHook = Callable[[AuditEntry], None]

_NS_PER_SECOND = 1_000_000_000


class RegimeActorConfig(ActorConfig, frozen=True):
    """Config for :class:`RegimeActor`.

    Attributes:
        primary_symbol: The instrument this actor classifies — informational,
            mirrors the design (``RegimeActorConfig.primary_symbol``) and keeps
            the bar-type parser from being re-introduced for logging.
        bar_type: ``BarType`` to subscribe to on start. When ``None`` the actor
            does not subscribe — used for unit tests that drive ``on_bar``
            directly (cf. ``PropFirmComplianceActorConfig.bar_type``).
        audit_to_db: When ``True`` *and* an audit hook is injected, each
            confirmed decision is sent to the hook. Defaults to ``False`` so a
            backtest writes zero rows to the live ``audit_logs`` hypertable
            (review R-E) and the actor stays loop-/DB-free (review R-D).
    """

    primary_symbol: str
    bar_type: BarType | None = None
    audit_to_db: bool = False


class RegimeActor(Actor):
    """Publishes the confirmed market regime per ``BarType`` into a shared store.

    The four pipeline components are injected **unchanged** from Epic 11 so the
    actor owns the single ``FeatureExtractor`` for its ``bar_type`` (indicators
    computed exactly once — single source of truth) and the regime decision is
    byte-identical to the router's. The actor only *orchestrates* and *publishes*;
    entry suppression lives in the strategy (story 15.7).
    """

    def __init__(
        self,
        config: RegimeActorConfig,
        *,
        classifier: RuleBasedRegimeClassifier,
        feature_extractor: FeatureExtractor,
        hysteresis: HysteresisFilter,
        regime_state: RegimeStateStore,
        audit_hook: RegimeAuditHook | None = None,
    ) -> None:
        super().__init__(config=config)
        self._config = config
        self._classifier = classifier
        self._extractor = feature_extractor
        self._hysteresis = hysteresis
        self._regime_state = regime_state
        self._audit_hook = audit_hook

    # ---- Nautilus Actor lifecycle ----------------------------------------

    def on_start(self) -> None:
        """Subscribe to bars so Nautilus dispatches ``on_bar`` (cf prop_firm_actor)."""
        if self._config.audit_to_db and self._audit_hook is None:
            # ``build_regime_actor`` (story 15.6) enforces audit_to_db == (hook
            # is not None), so this state is unreachable for factory-built
            # actors; the guard is for direct construction (e.g. unit tests). A
            # live wiring that sets audit_to_db=True but forgets the hook would
            # otherwise drop every regime audit row silently. Surface it once.
            logger.warning(
                "RegimeActor(%s): audit_to_db=True but no audit hook injected — "
                "regime decisions will NOT be persisted. Wire a hook (live path, "
                "story 15.11) or set audit_to_db=False.",
                self._config.primary_symbol,
            )
        if self._config.bar_type is not None:
            self.subscribe_bars(self._config.bar_type)

    def on_stop(self) -> None:
        """Unsubscribe cleanly.

        Catches only ``RuntimeError`` from ``unsubscribe_bars`` — Nautilus raises
        it when the actor is stopped before it fully subscribed (immediate
        shutdown). Any other exception is a programming error and propagates.
        """
        if self._config.bar_type is not None:
            try:
                self.unsubscribe_bars(self._config.bar_type)
            except RuntimeError:
                logger.debug(
                    "RegimeActor(%s).unsubscribe_bars raised (likely stopped "
                    "before fully subscribed); ignoring",
                    self._config.primary_symbol,
                    exc_info=True,
                )

    def on_bar(self, bar: Bar) -> None:
        """Run the unchanged classify → hysteresis pipeline and publish the regime.

        Sync per the Nautilus contract. During warmup the extractor returns
        ``None`` (no confirmed features) and the bar produces neither an audit
        row nor a publish — the same warmup skip the retired Epic-11 router
        applied at dispatch.
        """
        features = self._extractor.update(bar)
        if features is None:
            return  # warmup incomplete: no classification, no publish

        raw_state = self._classifier.decide(features)
        ts = self._bar_timestamp(bar)
        decision = self._hysteresis.apply(raw_state, ts, features)

        # Audit before publish (preserves the documented ordering even though
        # R-D no longer requires it for telemetry). Failures degrade gracefully.
        if self._config.audit_to_db and self._audit_hook is not None:
            try:
                self._audit_hook(to_audit_entry(decision))
            except Exception:  # noqa: BLE001 — telemetry must not break publishing
                logger.warning(
                    "RegimeActor audit hook failed for %s; dropping the row and "
                    "continuing to publish",
                    decision.bar_type,
                    exc_info=True,
                )

        self._regime_state.publish(decision)

    @staticmethod
    def _bar_timestamp(bar: Bar) -> datetime:
        """Nautilus ``ts_event`` (int ns since epoch) → tz-aware UTC datetime.

        Uses the bar's *event* time (its close), the same field the Epic 11
        router fed the hysteresis filter, so audit/decision timestamps match the
        bar boundary. (That never-wired router passed ``bar.ts_event`` as a raw
        ``int``, which would have failed ``RegimeDecision.__post_init__``'s
        tz-aware check had it ever run; the actor converts to a ``datetime``
        here, fixing it. Do NOT re-introduce a raw-int pass-through to "match"
        Epic 11.) Integer-second
        truncation is exact for boundary-aligned bars (M5+) and mirrors
        ``PropFirmComplianceActor``'s conversion (which uses ``ts_init`` because
        it tracks *when the rule engine ran*, a different semantic).
        """
        return datetime.fromtimestamp(bar.ts_event // _NS_PER_SECOND, tz=UTC)


__all__ = ["RegimeActor", "RegimeActorConfig", "RegimeAuditHook"]
