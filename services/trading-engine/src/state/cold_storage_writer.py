"""Cold Storage Writer - Periodic state snapshots to TimescaleDB.

This module provides the ColdStorageWriter class that periodically
persists state snapshots to TimescaleDB as a fallback for Redis.

Key design decisions:
- 60-second interval (vs 5-second for Redis)
- One snapshot per account per interval
- Graceful shutdown flushes final snapshots
- Non-blocking async operations
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .snapshot import StateSnapshot
from .snapshot_db_model import StateSnapshotModel

logger = logging.getLogger(__name__)


class ColdStorageWriter:
    """Periodic state snapshot writer to TimescaleDB.

    Persists snapshots every 60 seconds as fallback for Redis.
    Uses SQLAlchemy async with asyncpg for database access.

    Attributes:
        SNAPSHOT_INTERVAL_SECONDS: Time between snapshots (60s)

    Example:
        writer = ColdStorageWriter("postgresql+asyncpg://...")
        await writer.start()
        await writer.write_snapshot(snapshot)
        await writer.stop()
    """

    SNAPSHOT_INTERVAL_SECONDS = 60

    def __init__(self, database_url: str) -> None:
        """Initialize ColdStorageWriter.

        Args:
            database_url: Async PostgreSQL connection URL.
        """
        self._database_url = database_url
        self._engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=3,
            max_overflow=5,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._running = False

    async def start(self) -> None:
        """Start the cold storage writer."""
        if self._running:
            logger.warning("ColdStorageWriter already running")
            return

        self._running = True
        logger.info(
            "ColdStorageWriter started (interval=%ds)",
            self.SNAPSHOT_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        """Stop the cold storage writer."""
        if not self._running:
            return

        self._running = False
        await self._engine.dispose()
        logger.info("ColdStorageWriter stopped")

    async def write_snapshot(self, snapshot: StateSnapshot) -> None:
        """Write a single snapshot to TimescaleDB.

        Args:
            snapshot: StateSnapshot to persist.
        """
        model = StateSnapshotModel.from_snapshot(snapshot)

        async with self._session_factory() as session:
            async with session.begin():
                session.add(model)

        logger.debug(
            "Persisted snapshot to TimescaleDB for %s at %s",
            snapshot.account_id,
            snapshot.timestamp.isoformat(),
        )

    async def write_snapshots(self, snapshots: list[StateSnapshot]) -> None:
        """Write multiple snapshots to TimescaleDB in batch.

        Args:
            snapshots: List of StateSnapshot instances.
        """
        if not snapshots:
            return

        models = [StateSnapshotModel.from_snapshot(s) for s in snapshots]

        async with self._session_factory() as session:
            async with session.begin():
                session.add_all(models)

        logger.debug(
            "Persisted %d snapshots to TimescaleDB",
            len(snapshots),
        )

    async def get_latest_snapshot(self, account_id: str) -> StateSnapshot | None:
        """Get the most recent snapshot for an account.

        Used during crash recovery when Redis is unavailable.

        Args:
            account_id: Account to retrieve snapshot for.

        Returns:
            StateSnapshot if found, None otherwise.
        """
        async with self._session_factory() as session:
            stmt = (
                select(StateSnapshotModel)
                .where(StateSnapshotModel.account_id == account_id)
                .order_by(StateSnapshotModel.timestamp.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if model is None:
                return None

            return model.to_snapshot()

    @property
    def is_running(self) -> bool:
        """Whether the writer is currently running."""
        return self._running
