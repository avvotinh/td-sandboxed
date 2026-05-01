"""LiveOrchestrator — owns the live-trading auxiliary services.

Story 10.1 carved this out as a skeleton; story 10.2 swapped the raw-deps
constructor for a pre-built :class:`LiveServiceBundle` so all
construction lives in :func:`engine.build_lifecycle`. Story 10.5a added
the per-account session lifecycle (``add_account`` / ``remove_account``
/ ``reload_account``) plus crash isolation. Story 10.5e1 wires the
per-account components built by 10.5a/b/c (RuleEngine + compliance
actor + bar subscriptions) onto each session, and adds the periodic
health-surface push to Redis. Story 10.5d threads a per-account
equity provider — a closure over :class:`PnLTrackerRegistry` — into
each compliance actor so live ``on_bar`` rule checks use the engine's
authoritative equity instead of the Nautilus ``Portfolio``. The
Nautilus ``TradingNode`` factory glue that turns these components
into a running live event loop is deferred to 10.5e2.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from ..orders.trade_db_writer import TradeDBWriter
from ..rules.violation_service import ViolationService
from ..state.cold_storage_service import ColdStorageService
from .account_session import LiveAccountSession, SessionState
from .actors import build_compliance_actor
from .collaborators import LiveServiceBundle

if TYPE_CHECKING:
    from ..accounts.account_manager import AccountManager
    from ..accounts.models import AccountConfig
    from ..accounts.pnl_registry import PnLTrackerRegistry
    from ..accounts.risk_registry import RiskStateRegistry
    from ..audit.audit_service import AuditService
    from ..backtesting.prop_firm_actor import LiveEquityProvider
    from ..rules.assignment_service import RuleAssignmentService
    from ..state.redis_state import RedisStateManager

logger = logging.getLogger(__name__)


# Default timeframes a per-account live session subscribes to.
# Story 10.5e2 may make this firm-configurable.
DEFAULT_BAR_TIMEFRAMES: tuple[str, ...] = ("1m",)

# Health surface — Redis key + cadence (AC7).
HEALTH_REDIS_KEY = "health:trading-engine"
HEALTH_PUSH_INTERVAL_SECONDS = 5.0
HEALTH_REDIS_TTL_SECONDS = 30


@dataclass(frozen=True)
class LiveOrchestratorHealth:
    """Snapshot of the orchestrator's per-account health.

    Story 10.5a populates ``accounts_running`` / ``accounts_failed``;
    10.5e1 adds ``ts`` (snapshot timestamp) and the JSON-serialisable
    fields needed for the ``health:trading-engine`` Redis push. 10.5e2
    will fill ``last_bar_received_at`` / ``last_order_sent_at`` once
    the per-account ``LiveNode`` actually runs.
    """

    accounts_running: int
    accounts_failed: tuple[tuple[str, str], ...]
    ts: str = ""

    def to_redis_payload(self) -> str:
        """Serialise to a JSON string suitable for ``SETEX``."""
        payload = asdict(self)
        payload["accounts_failed"] = list(self.accounts_failed)
        return json.dumps(payload, separators=(",", ":"))


class LiveOrchestrator:
    """Manages the lifecycle of live-trading auxiliary services."""

    def __init__(
        self,
        services: LiveServiceBundle,
        *,
        account_manager: "AccountManager | None" = None,
        audit_service: "AuditService | None" = None,
        rule_assignment_service: "RuleAssignmentService | None" = None,
        risk_registry: "RiskStateRegistry | None" = None,
        pnl_registry: "PnLTrackerRegistry | None" = None,
        redis_manager: "RedisStateManager | None" = None,
        bar_timeframes: tuple[str, ...] = DEFAULT_BAR_TIMEFRAMES,
        health_push_interval: float = HEALTH_PUSH_INTERVAL_SECONDS,
        health_ttl_seconds: int = HEALTH_REDIS_TTL_SECONDS,
    ) -> None:
        self._services = services
        self._account_manager = account_manager
        self._audit_service = audit_service
        self._rule_assignment_service = rule_assignment_service
        self._risk_registry = risk_registry
        self._pnl_registry = pnl_registry
        self._redis_manager = redis_manager
        self._bar_timeframes = tuple(bar_timeframes)
        self._health_push_interval = health_push_interval
        self._health_ttl_seconds = health_ttl_seconds
        self._sessions: dict[str, LiveAccountSession] = {}
        self._health_task: asyncio.Task[None] | None = None

    @property
    def cold_storage_service(self) -> ColdStorageService | None:
        return self._services.cold_storage_service

    @property
    def trade_db_writer(self) -> TradeDBWriter | None:
        return self._services.trade_db_writer

    @property
    def violation_service(self) -> ViolationService | None:
        return self._services.violation_service

    @property
    def sessions(self) -> dict[str, LiveAccountSession]:
        """Read-only view of per-account sessions."""
        return dict(self._sessions)

    async def start(self) -> None:
        """Start every service present in the bundle, in fixed order."""
        if self._services.cold_storage_service is not None:
            await self._services.cold_storage_service.start()
            logger.info("Cold storage service started")
        if self._services.trade_db_writer is not None:
            await self._services.trade_db_writer.start()
            logger.info("Trade audit writer started")
        if self._services.violation_db_writer is not None:
            await self._services.violation_db_writer.start()
            logger.info("Violation tracking started")
        if self._services.daily_snapshot_writer is not None:
            await self._services.daily_snapshot_writer.start()
        if self._services.daily_snapshot_service is not None:
            await self._services.daily_snapshot_service.start()
            logger.info("Daily snapshot service started")

        # Per-account sessions — only when AccountManager is wired.
        if self._account_manager is not None:
            await self._start_all_sessions()

        # Health surface push — only when Redis is wired (AC7).
        if self._redis_manager is not None:
            self._health_task = asyncio.create_task(
                self._health_push_loop(),
                name="live_orchestrator_health_push",
            )

    async def stop(self) -> None:
        """Stop services in reverse start order — best-effort.

        Note: :class:`ColdStorageService` is intentionally not stopped
        here — :meth:`GracefulShutdown._persist_final_state` owns that
        step so the final snapshot writes through cold storage before
        teardown. Callers without a graceful-shutdown handler keep the
        legacy gap.
        """
        # Stop the health-push task before tearing anything else down so
        # we can't publish a snapshot mid-teardown that would be wrong.
        if self._health_task is not None:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
            self._health_task = None

        # Tear down per-account sessions first so they cannot post
        # writes to services that are about to stop.
        await self._stop_all_sessions()

        if self._services.daily_snapshot_service is not None:
            await self._services.daily_snapshot_service.stop()
        if self._services.daily_snapshot_writer is not None:
            await self._services.daily_snapshot_writer.stop()
        if self._services.trade_db_writer is not None:
            await self._services.trade_db_writer.stop()
        if self._services.violation_db_writer is not None:
            await self._services.violation_db_writer.stop()

    # ----- Per-account session management (story 10.5a) -------------------

    async def add_account(self, account_id: str) -> LiveAccountSession:
        """Hot-add an account session at runtime.

        Used after ``accounts add`` (Epic 9 P0.10) registers a new
        account with :class:`AccountManager`. Idempotent — calling for
        an already-running account returns the existing session.
        """
        if self._account_manager is None:
            raise RuntimeError(
                "LiveOrchestrator.add_account requires account_manager "
                "to be wired at construction"
            )

        existing = self._sessions.get(account_id)
        if existing is not None and existing.is_running:
            return existing

        session = LiveAccountSession(account_id=account_id)
        self._sessions[account_id] = session
        await self._start_session(session)
        return session

    async def remove_account(self, account_id: str) -> None:
        """Stop and drop the session for ``account_id``. No-op if absent."""
        session = self._sessions.pop(account_id, None)
        if session is None:
            return
        await self._stop_session(session)

    async def reload_account(self, account_id: str) -> LiveAccountSession:
        """Stop, then re-create the session for ``account_id``.

        Called by the ``account:phase-changed:{account_id}`` Redis
        subscriber after :func:`accounts.promote_account` flips the
        phase. 10.5e wires the subscription; 10.5a provides the
        operation it triggers.
        """
        await self.remove_account(account_id)
        return await self.add_account(account_id)

    def health(self) -> LiveOrchestratorHealth:
        """Return a synchronous health snapshot.

        Story 10.5e2 extends this with bar/order timestamps once the
        per-account ``LiveNode`` is mounted onto the session.
        """
        running = sum(
            1 for s in self._sessions.values() if s.state is SessionState.RUNNING
        )
        failed = tuple(
            (s.account_id, s.last_error or "unknown")
            for s in self._sessions.values()
            if s.state is SessionState.FAILED
        )
        return LiveOrchestratorHealth(
            accounts_running=running,
            accounts_failed=failed,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    # ----- Internals -----------------------------------------------------

    async def _start_all_sessions(self) -> None:
        """Build a session for every active account; isolate per-account failures."""
        if self._account_manager is None:
            raise RuntimeError(
                "_start_all_sessions called without account_manager wired"
            )
        account_ids = self._account_manager.get_active_account_ids()
        for account_id in account_ids:
            if account_id in self._sessions:
                continue
            session = LiveAccountSession(account_id=account_id)
            self._sessions[account_id] = session
            await self._start_session(session)

    async def _start_session(self, session: LiveAccountSession) -> None:
        """Bring a single session online with crash isolation.

        Story 10.5a only flips the state machine — 10.5b/c will
        construct the Nautilus ``LiveNode`` and clients here, then call
        :meth:`LiveAccountSession.attach_components`. A start failure
        pauses the affected account so other accounts keep trading
        (AC8 crash isolation).
        """
        try:
            await self._build_session_components(session)
            session.mark_running()
            logger.info("LiveAccountSession started: %s", session.account_id)
        except Exception as exc:
            session.mark_failed(repr(exc))
            await self._isolate_failed_session(session, exc)

    async def _build_session_components(
        self, session: LiveAccountSession
    ) -> None:
        """Resolve and attach the per-account components for a session.

        Story 10.5e1 — given the deps wired through :class:`EngineConfig`
        (``account_manager`` + ``rule_assignment_service`` + ``risk_registry``),
        resolve the per-account :class:`RuleEngine`, build the
        :class:`PropFirmComplianceActor`, and compute the
        ``bar_subscriptions`` list. Components are stashed on
        ``session.components`` so 10.5e2 can pick them up when it
        instantiates the per-account Nautilus ``TradingNode``.

        When the live-session deps are not wired (``EngineConfig.empty()``,
        unit tests), this method is a no-op — callers can still rely on
        the lifecycle skeleton from 10.5a.
        """
        if (
            self._account_manager is None
            or self._rule_assignment_service is None
        ):
            # Live-session feature disabled — skeleton only.
            return

        account_id = session.account_id
        account = self._account_manager.get_account(account_id)
        if account is None:
            raise RuntimeError(
                f"Account '{account_id}' is active but missing from "
                "AccountManager — cannot build live session"
            )

        # 1. Resolve rule engine for this account.
        rules = self._rule_assignment_service.get_rules_for_account(account)
        # Local import — RuleEngine pulls in heavy collaborators we
        # don't want at module import time for unit tests that use
        # ``EngineConfig.empty()``.
        from ..rules.engine import RuleEngine

        rule_engine = RuleEngine(account_id=account_id, rules=rules)

        # 2. Resolve initial balance for the compliance actor's
        # drawdown / peak baseline.
        initial_balance = self._resolve_initial_balance(account_id)

        # 3. Build the per-account live equity provider (story 10.5d).
        # The closure resolves the tracker each tick — late-binding
        # through ``pnl_registry.get`` keeps reload semantics correct
        # when ``reload_account`` swaps the tracker mid-life.
        equity_provider = self._build_equity_provider(account_id)

        # 4. Build the per-account compliance actor through the shared
        # factory (story 10.5a AC2). Venue/bar_type plumbing comes in
        # 10.5e2 once the per-account TradingNode is instantiated; the
        # equity_provider here drives ``on_bar`` rule checks from the
        # engine's per-account state.
        compliance_actor = build_compliance_actor(
            account_id=account_id,
            initial_balance=initial_balance,
            rule_engine=rule_engine,
            equity_provider=equity_provider,
        )

        # 5. Compute the bar subscriptions for the account's data feed.
        bar_subscriptions = self._compute_bar_subscriptions(account)

        session.attach_components(
            rule_engine=rule_engine,
            compliance_actor=compliance_actor,
            equity_provider=equity_provider,
            bar_subscriptions=bar_subscriptions,
            initial_balance=initial_balance,
        )

    def _build_equity_provider(
        self, account_id: str
    ) -> "LiveEquityProvider | None":
        """Return a per-account equity closure for the compliance actor.

        Story 10.5d — wraps :meth:`PnLTrackerRegistry.get` so the actor
        sees ``tracker.equity`` whenever the registry has a tracker for
        the account, ``None`` otherwise (warm-up before the first fill).
        The tracker is resolved on every call (rather than captured
        once) so :meth:`reload_account` can swap the tracker without
        leaving the closure pointed at a stale instance.

        Returns ``None`` when ``pnl_registry`` is not wired so the actor
        falls back to the Nautilus portfolio path used by backtest.
        """
        if self._pnl_registry is None:
            return None
        registry = self._pnl_registry

        def _provider(scope_account_id: str) -> Decimal | None:
            if scope_account_id != account_id:
                # Hard guard — mis-routed equity reads silently feeding
                # the wrong rule engine would be a P0 compliance bug.
                # Log first so the cause is visible even if Nautilus's
                # actor event loop swallows the exception above us.
                logger.error(
                    "equity_provider cross-account misuse: bound=%s called=%s",
                    account_id,
                    scope_account_id,
                )
                raise ValueError(
                    f"equity_provider bound to '{account_id}' "
                    f"but called with '{scope_account_id}'"
                )
            tracker = registry.get(account_id)
            if tracker is None:
                return None
            # ``Decimal(str(...))`` shields the rule engine from any
            # future internal-type drift in :class:`PnLTracker.equity`
            # (matches :meth:`_resolve_initial_balance` below).
            return Decimal(str(tracker.equity))

        return _provider

    def _resolve_initial_balance(self, account_id: str) -> Decimal:
        """Best-effort initial-balance resolution.

        Reads from :class:`RiskStateRegistry` if available — the
        ``daily_starting_balance`` field is the canonical anchor used by
        the recovery flow. Falls back to ``Decimal("0")`` so the actor
        constructor (which requires a Decimal) does not raise; the
        compliance metrics built off a zero baseline will be obviously
        wrong rather than subtly wrong.
        """
        if self._risk_registry is None:
            return Decimal("0")
        risk_state = self._risk_registry.get_risk_state(account_id)
        if risk_state is None:
            return Decimal("0")
        return Decimal(str(risk_state.daily_starting_balance))

    def _compute_bar_subscriptions(
        self, account: "AccountConfig"
    ) -> list[tuple[str, str]]:
        """Build the (symbol, timeframe) list this account should subscribe to.

        Driven by ``account.signal_filter.symbols`` × ``self._bar_timeframes``.
        Empty symbols ⇒ empty subscriptions; 10.5e2 will resolve a
        wildcard from the firm's instrument set when
        ``signal_filter.symbols`` is empty.
        """
        signal_filter = getattr(account, "signal_filter", None)
        symbols = list(getattr(signal_filter, "symbols", []) or [])
        if not symbols:
            return []
        return [(symbol, tf) for symbol in symbols for tf in self._bar_timeframes]

    async def _stop_all_sessions(self) -> None:
        for session in list(self._sessions.values()):
            await self._stop_session(session)

    async def _stop_session(self, session: LiveAccountSession) -> None:
        """Stop a single session — best effort, never raises."""
        try:
            await self._teardown_session_components(session)
        except Exception:
            logger.exception(
                "LiveAccountSession %s teardown raised", session.account_id
            )
        finally:
            session.mark_stopped()
            logger.info("LiveAccountSession stopped: %s", session.account_id)

    async def _teardown_session_components(
        self, session: LiveAccountSession
    ) -> None:
        """Hook for 10.5b/c to tear down Nautilus components."""
        # Intentionally empty in 10.5a — symmetrical with _build_session_components.
        return

    async def _isolate_failed_session(
        self,
        session: LiveAccountSession,
        exc: BaseException,
    ) -> None:
        """Crash-isolation: pause the failed account + audit + keep running others.

        Story 10.5a AC8 — a single account's failure must not bring
        down the engine. 10.5e will additionally raise a Telegram
        ``alerts:system:critical`` notification.
        """
        logger.error(
            "LiveAccountSession failed for %s: %s",
            session.account_id,
            exc,
            exc_info=exc,
        )

        # Best-effort pause — pause_account requires prior state, may raise
        # ValueError on accounts that never started.
        if self._account_manager is not None:
            try:
                await self._account_manager.pause_account(session.account_id)
            except Exception:
                logger.warning(
                    "Could not pause account %s after session failure",
                    session.account_id,
                    exc_info=True,
                )

        if self._audit_service is not None:
            try:
                await self._audit_service.log_system_event_sync(
                    event_subtype="node_crashed",
                    account_id=session.account_id,
                    message=f"Live session failed: {exc!r}",
                    level="ERROR",
                    context={"error": repr(exc)},
                )
            except Exception:
                logger.warning(
                    "Could not record node_crashed audit for %s",
                    session.account_id,
                    exc_info=True,
                )

    # ----- Health surface (story 10.5e1, AC7) ----------------------------

    async def _health_push_loop(self) -> None:
        """Publish a JSON health snapshot to Redis every ``health_push_interval``.

        Key: ``health:trading-engine`` (TTL ``health_ttl_seconds``).
        Cancellation is the canonical exit — :meth:`stop` cancels the
        task during shutdown.
        """
        if self._redis_manager is None:
            return
        while True:
            try:
                await self._publish_health_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Health push failed; continuing — will retry next tick"
                )
            try:
                await asyncio.sleep(self._health_push_interval)
            except asyncio.CancelledError:
                raise

    async def _publish_health_snapshot(self) -> None:
        """One-shot publish — separated for direct testability."""
        if self._redis_manager is None:
            return
        snapshot = self.health()
        await self._redis_manager.client.setex(
            HEALTH_REDIS_KEY,
            self._health_ttl_seconds,
            snapshot.to_redis_payload(),
        )
