"""LiveOrchestrator — owns the live-trading auxiliary services.

Story 10.1 carved this out as a skeleton; story 10.2 swaps the raw-deps
constructor for a pre-built :class:`LiveServiceBundle` so all
construction lives in :func:`engine.build_lifecycle`. Story 10.5 will
extend this class to build the Nautilus ``LiveNode``, attach
``PropFirmComplianceActor`` per account, and wire ``RedisDataClient`` +
``ZmqExecutionClient``.
"""
from __future__ import annotations

import logging

from ..orders.trade_db_writer import TradeDBWriter
from ..rules.violation_service import ViolationService
from ..state.cold_storage_service import ColdStorageService
from .collaborators import LiveServiceBundle

logger = logging.getLogger(__name__)


class LiveOrchestrator:
    """Manages the lifecycle of live-trading auxiliary services."""

    def __init__(self, services: LiveServiceBundle) -> None:
        self._services = services

    @property
    def cold_storage_service(self) -> ColdStorageService | None:
        return self._services.cold_storage_service

    @property
    def trade_db_writer(self) -> TradeDBWriter | None:
        return self._services.trade_db_writer

    @property
    def violation_service(self) -> ViolationService | None:
        return self._services.violation_service

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

    async def stop(self) -> None:
        """Stop services in reverse start order — best-effort.

        Note: :class:`ColdStorageService` is intentionally not stopped
        here — :meth:`GracefulShutdown._persist_final_state` owns that
        step so the final snapshot writes through cold storage before
        teardown. Callers without a graceful-shutdown handler keep the
        legacy gap.
        """
        if self._services.daily_snapshot_service is not None:
            await self._services.daily_snapshot_service.stop()
        if self._services.daily_snapshot_writer is not None:
            await self._services.daily_snapshot_writer.stop()
        if self._services.trade_db_writer is not None:
            await self._services.trade_db_writer.stop()
        if self._services.violation_db_writer is not None:
            await self._services.violation_db_writer.stop()
