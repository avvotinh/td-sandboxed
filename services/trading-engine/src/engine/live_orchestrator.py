"""LiveOrchestrator — owns the live-trading auxiliary services.

Story 10.1 ships a thin skeleton that starts/stops the four live-time
services the god-object initialised inline (cold storage, trade audit,
violation tracking, daily snapshots). Story 10.5 will extend this class
to build the Nautilus `LiveNode`, attach `PropFirmComplianceActor` per
account, and wire `RedisDataClient` + `ZmqExecutionClient`.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..accounts.account_manager import AccountManager
from ..audit.audit_service import AuditService
from ..config.firm_registry import FirmRegistry
from ..orders.trade_db_writer import TradeDBWriter
from ..rules.violation_db_writer import ViolationDBWriter
from ..rules.violation_service import ViolationService
from ..snapshots.daily_snapshot_service import DailySnapshotService
from ..snapshots.snapshot_db_writer import SnapshotDBWriter
from ..state.cold_storage_service import ColdStorageService
from ..state.cold_storage_writer import ColdStorageWriter
from ..state.redis_state import RedisStateManager
from ..state.snapshot_service import SnapshotService

logger = logging.getLogger(__name__)


class LiveOrchestrator:
    """Manages the lifecycle of live-trading auxiliary services."""

    # TODO(10.2): collapse the 7 raw deps into pre-built service instances
    # supplied by the DI container; the spec sketch envisions
    # ``__init__(account_manager, snapshot_service, firm_registry)`` only.
    def __init__(
        self,
        snapshot_service: SnapshotService | None,
        redis_manager: RedisStateManager | None,
        account_manager: AccountManager | None,
        db_session_factory: async_sessionmaker[AsyncSession] | None,
        audit_service: AuditService | None,
        firm_registry: FirmRegistry | None,
        database_url: str | None,
    ) -> None:
        self._snapshot_service = snapshot_service
        self._redis_manager = redis_manager
        self._account_manager = account_manager
        self._db_session_factory = db_session_factory
        self._audit_service = audit_service
        self._firm_registry = firm_registry
        self._database_url = database_url

        self._cold_storage_service: ColdStorageService | None = None
        self._trade_db_writer: TradeDBWriter | None = None
        self._violation_db_writer: ViolationDBWriter | None = None
        self._violation_service: ViolationService | None = None
        self._daily_snapshot_writer: SnapshotDBWriter | None = None
        self._daily_snapshot_service: DailySnapshotService | None = None

    @property
    def cold_storage_service(self) -> ColdStorageService | None:
        return self._cold_storage_service

    @property
    def trade_db_writer(self) -> TradeDBWriter | None:
        return self._trade_db_writer

    @property
    def violation_service(self) -> ViolationService | None:
        return self._violation_service

    async def start(
        self, cold_storage_writer: ColdStorageWriter | None = None
    ) -> None:
        """Initialise auxiliary services. Skeleton — Nautilus wiring is 10.5."""
        await self._start_cold_storage(cold_storage_writer)
        await self._start_trade_audit()
        await self._start_violation_tracking()
        await self._start_daily_snapshots()

    async def stop(self) -> None:
        """Stop services in reverse order — best-effort, errors do not propagate.

        Note: :class:`ColdStorageService` is intentionally not stopped here —
        :meth:`GracefulShutdown._persist_final_state` owns that step so the
        final snapshot writes through cold storage before teardown. Callers
        without a graceful-shutdown handler keep the legacy gap.
        """
        if self._daily_snapshot_service is not None:
            await self._daily_snapshot_service.stop()
        if self._daily_snapshot_writer is not None:
            await self._daily_snapshot_writer.stop()
        if self._trade_db_writer is not None:
            await self._trade_db_writer.stop()
        if self._violation_db_writer is not None:
            await self._violation_db_writer.stop()

    async def _start_cold_storage(
        self, cold_storage_writer: ColdStorageWriter | None
    ) -> None:
        if cold_storage_writer is None:
            return
        if self._snapshot_service is None:
            logger.warning(
                "Cold storage requires snapshot_service, cold storage disabled"
            )
            return
        self._cold_storage_service = ColdStorageService(
            cold_storage_writer=cold_storage_writer,
            snapshot_service=self._snapshot_service,
        )
        await self._cold_storage_service.start()
        logger.info("Cold storage service initialized")

    async def _start_trade_audit(self) -> None:
        if self._database_url is None:
            logger.warning("No database URL — trade audit logging disabled")
            return
        self._trade_db_writer = TradeDBWriter(self._database_url)
        await self._trade_db_writer.start()
        logger.info("Trade audit writer initialized")

    async def _start_violation_tracking(self) -> None:
        if self._database_url is None:
            logger.warning("No database URL — violation tracking disabled")
            return
        self._violation_db_writer = ViolationDBWriter(self._database_url)
        await self._violation_db_writer.start()
        self._violation_service = ViolationService(self._violation_db_writer)
        logger.info("Violation tracking service initialized")

    async def _start_daily_snapshots(self) -> None:
        if self._database_url is None:
            logger.warning("No database URL — daily snapshots disabled")
            return
        if (
            self._redis_manager is None
            or self._account_manager is None
            or self._db_session_factory is None
        ):
            logger.warning(
                "Daily snapshots require redis_manager, account_manager, "
                "and db_session_factory"
            )
            return
        self._daily_snapshot_writer = SnapshotDBWriter(self._database_url)
        await self._daily_snapshot_writer.start()
        self._daily_snapshot_service = DailySnapshotService(
            db_writer=self._daily_snapshot_writer,
            redis_state=self._redis_manager,
            account_manager=self._account_manager,
            db_session_factory=self._db_session_factory,
            audit_service=self._audit_service,
            firm_registry=self._firm_registry,
        )
        await self._daily_snapshot_service.start()
        logger.info("Daily snapshot service initialized")
