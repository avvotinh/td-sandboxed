"""Snapshot DB Writer - Direct persistence of daily account snapshots to TimescaleDB.

Low-volume writer (one snapshot per account per day) — no batch buffer needed.
Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE for idempotent upserts.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import AccountSnapshotModel

logger = logging.getLogger(__name__)

# Columns updated on upsert conflict (everything except id, account_id, snapshot_date, created_at)
_UPDATABLE_COLUMNS = [
    "snapshot_time",
    "opening_balance",
    "closing_balance",
    "high_balance",
    "low_balance",
    "daily_pnl",
    "daily_pnl_percent",
    "peak_balance",
    "drawdown_from_peak",
    "drawdown_percent",
    "trades_count",
    "winning_trades",
    "losing_trades",
    "total_volume",
]


class SnapshotDBWriter:
    """Direct writer for daily account snapshots (no batch buffer — low volume)."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_async_engine(
            database_url, echo=False, pool_size=3, max_overflow=5,
        )
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False,
        )
        self._running = False

    async def start(self) -> None:
        # Validate DB connectivity early so misconfig surfaces at startup, not midnight
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        self._running = True
        logger.info("SnapshotDBWriter started")

    async def stop(self) -> None:
        self._running = False
        await self._engine.dispose()
        logger.info("SnapshotDBWriter stopped")

    async def write_snapshot(self, snapshot_data: dict[str, Any]) -> None:
        """Write or update a daily account snapshot (upsert).

        Uses INSERT ... ON CONFLICT (account_id, snapshot_date) DO UPDATE
        so engine restarts don't create duplicate rows.
        """
        model = AccountSnapshotModel.from_snapshot_data(snapshot_data)
        values = {
            c.name: getattr(model, c.name)
            for c in AccountSnapshotModel.__table__.columns
            if c.name != "id" and c.name != "created_at"
        }

        stmt = insert(AccountSnapshotModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="account_snapshots_account_id_snapshot_date_key",
            set_={col: stmt.excluded[col] for col in _UPDATABLE_COLUMNS},
        )

        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(stmt)

        logger.debug(
            "Snapshot upserted: %s / %s",
            snapshot_data.get("account_id"),
            snapshot_data.get("snapshot_date"),
        )

    @property
    def is_running(self) -> bool:
        return self._running
