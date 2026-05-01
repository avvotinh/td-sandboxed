"""LiveOrchestrator — owns the live-trading auxiliary services.

Story 10.1 carved this out as a skeleton; story 10.2 swapped the raw-deps
constructor for a pre-built :class:`LiveServiceBundle` so all
construction lives in :func:`engine.build_lifecycle`. Story 10.5a adds
the per-account session lifecycle (``add_account`` / ``remove_account``
/ ``reload_account``) plus crash isolation; 10.5b/c will plug Nautilus
``LiveNode`` + ``RedisDataClient`` + ``ZmqExecutionClient`` into each
session via :meth:`LiveAccountSession.attach_components`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..orders.trade_db_writer import TradeDBWriter
from ..rules.violation_service import ViolationService
from ..state.cold_storage_service import ColdStorageService
from .account_session import LiveAccountSession, SessionState
from .collaborators import LiveServiceBundle

if TYPE_CHECKING:
    from ..accounts.account_manager import AccountManager
    from ..audit.audit_service import AuditService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveOrchestratorHealth:
    """Snapshot of the orchestrator's per-account health.

    Story 10.5a populates ``accounts_running`` / ``accounts_failed``;
    10.5e adds ``last_bar_received_at`` / ``last_order_sent_at`` and
    publishes the snapshot to ``health:trading-engine`` Redis key.
    """

    accounts_running: int
    accounts_failed: tuple[tuple[str, str], ...]


class LiveOrchestrator:
    """Manages the lifecycle of live-trading auxiliary services."""

    def __init__(
        self,
        services: LiveServiceBundle,
        *,
        account_manager: "AccountManager | None" = None,
        audit_service: "AuditService | None" = None,
    ) -> None:
        self._services = services
        self._account_manager = account_manager
        self._audit_service = audit_service
        self._sessions: dict[str, LiveAccountSession] = {}

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

    async def stop(self) -> None:
        """Stop services in reverse start order — best-effort.

        Note: :class:`ColdStorageService` is intentionally not stopped
        here — :meth:`GracefulShutdown._persist_final_state` owns that
        step so the final snapshot writes through cold storage before
        teardown. Callers without a graceful-shutdown handler keep the
        legacy gap.
        """
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

        Story 10.5e extends this with bar/order timestamps and
        publishes the result to Redis.
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
        """Hook for 10.5b/c to attach Nautilus components.

        Today this is intentionally empty — 10.5a only introduces the
        lifecycle skeleton. The hook exists so subclassing or
        monkey-patching is unnecessary when the rest of 10.5 lands.
        """
        # Intentionally empty in 10.5a. 10.5b: attach RedisDataClient.
        # 10.5c: attach ZmqExecutionClient. 10.5d: attach
        # PropFirmComplianceActor + LiveNode and call node.start_async.
        return

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
