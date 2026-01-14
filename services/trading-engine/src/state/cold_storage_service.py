"""ColdStorageService - Periodic cold storage snapshot service.

Runs in background, writing state snapshots to TimescaleDB every 60 seconds
for all active accounts. Provides fallback recovery when Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .cold_storage_writer import ColdStorageWriter
from .snapshot import StateSnapshot

if TYPE_CHECKING:
    from .snapshot_service import SnapshotService

logger = logging.getLogger(__name__)


class ColdStorageService:
    """Periodic cold storage service for TimescaleDB backup.

    Creates snapshots every 60 seconds (configurable) for all active accounts.
    Works alongside SnapshotService (Redis) as a fallback.

    Example:
        service = ColdStorageService(
            cold_storage_writer=writer,
            snapshot_service=redis_snapshot_service,
        )
        await service.start()
        # ... trading runs ...
        await service.stop()
    """

    DEFAULT_INTERVAL_SECONDS = 60

    def __init__(
        self,
        cold_storage_writer: ColdStorageWriter,
        snapshot_service: SnapshotService,
        interval_seconds: float = 60.0,
    ) -> None:
        """Initialize ColdStorageService.

        Args:
            cold_storage_writer: Writer for TimescaleDB persistence.
            snapshot_service: Redis snapshot service for data collection.
            interval_seconds: Seconds between snapshot cycles (default: 60).
        """
        self._writer = cold_storage_writer
        self._snapshot_service = snapshot_service
        self._interval = interval_seconds
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background cold storage loop."""
        if self._running:
            logger.warning("ColdStorageService already running")
            return

        await self._writer.start()
        self._running = True
        self._task = asyncio.create_task(
            self._cold_storage_loop(),
            name="cold-storage-service",
        )
        logger.info(
            "ColdStorageService started with %.1f second interval",
            self._interval,
        )

    async def stop(self) -> None:
        """Stop the cold storage loop with final flush."""
        if not self._running:
            return

        self._running = False

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Final snapshot before shutdown
        logger.info("Performing final cold storage snapshot...")
        try:
            await self._snapshot_all_accounts()
        except Exception as e:
            logger.error("Final cold storage snapshot failed: %s", e)

        await self._writer.stop()
        logger.info("ColdStorageService stopped")

    async def _cold_storage_loop(self) -> None:
        """Main cold storage loop - runs until stopped."""
        while self._running:
            try:
                await self._snapshot_all_accounts()
            except Exception as e:
                logger.error("Cold storage cycle failed: %s", e)

            await asyncio.sleep(self._interval)

    async def _snapshot_all_accounts(self) -> None:
        """Collect and persist snapshots for all active accounts."""
        # Get active accounts from snapshot service's account manager
        account_ids = await self._snapshot_service._get_active_account_ids()
        if not account_ids:
            return

        start = time.perf_counter()
        snapshots: list[StateSnapshot] = []

        # Collect snapshots
        for account_id in account_ids:
            try:
                snapshot = await self._snapshot_service._collect_snapshot_data(
                    account_id
                )
                snapshots.append(snapshot)
            except Exception as e:
                logger.error("Failed to collect snapshot for %s: %s", account_id, e)

        # Persist to TimescaleDB
        if snapshots:
            await self._writer.write_snapshots(snapshots)

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.debug(
            "Cold storage cycle completed in %.2fms for %d accounts",
            elapsed_ms,
            len(snapshots),
        )

    @property
    def is_running(self) -> bool:
        """Whether the service is currently running."""
        return self._running
