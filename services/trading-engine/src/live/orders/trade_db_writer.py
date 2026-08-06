"""Trade DB Writer - Batch persistence of trade records to TimescaleDB.

This module provides the TradeDBWriter class that buffers trade records
and periodically flushes them to TimescaleDB in batches for efficiency.

Key design decisions (matching AuditDBWriter for consistency):
- Batch buffering: Configurable size threshold (default: 100 entries)
- Timer-based flush: Periodic flush (default: 60 seconds)
- Graceful shutdown: Final buffer flush on engine stop
- Non-blocking: All operations are async
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, AsyncGenerator, Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .db_models import TradeRecord

if TYPE_CHECKING:
    from .trade import Trade

logger = logging.getLogger(__name__)


class TradeDBWriter:
    """Batched writer for persisting trade records to TimescaleDB.

    The TradeDBWriter buffers trade records and flushes them to the database
    either when the buffer reaches a size threshold or when the flush timer
    triggers. Follows the same pattern as AuditDBWriter for consistency.

    Attributes:
        database_url: PostgreSQL/TimescaleDB connection URL.
        batch_size: Number of entries to buffer before flushing (default: 100).
        flush_interval: Seconds between timer-based flushes (default: 60).

    Example:
        writer = TradeDBWriter("postgresql+asyncpg://user:pass@localhost/db")
        await writer.start()
        await writer.write_trade_entry(trade, strategy_name="ma_crossover")
        await writer.stop()  # Flushes remaining entries
    """

    def __init__(
        self,
        database_url: str,
        batch_size: int = 100,
        flush_interval: float = 60.0,
    ) -> None:
        """Initialize TradeDBWriter.

        Args:
            database_url: Async PostgreSQL connection URL (postgresql+asyncpg://...).
            batch_size: Number of entries to buffer before auto-flush.
            flush_interval: Seconds between timer-based flushes.
        """
        self._database_url = database_url
        self._batch_size = batch_size
        self._flush_interval = flush_interval

        # Buffer for pending trade records
        self._buffer: list[TradeRecord] = []
        self._buffer_lock = asyncio.Lock()

        # SQLAlchemy async engine and session factory
        self._engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Flush timer task
        self._flush_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the batch writer and flush timer.

        This should be called when the engine starts.
        """
        if self._running:
            logger.warning("TradeDBWriter already running")
            return

        self._running = True
        self._flush_task = asyncio.create_task(
            self._flush_timer_loop(),
            name="trade_db_flush_timer",
        )
        logger.info(
            "TradeDBWriter started (batch_size=%d, flush_interval=%.1fs)",
            self._batch_size,
            self._flush_interval,
        )

    async def stop(self) -> None:
        """Stop the batch writer and flush remaining entries.

        This should be called during graceful engine shutdown.
        """
        if not self._running:
            return

        self._running = False

        # Cancel flush timer
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        # Final flush of remaining entries
        await self._flush_buffer()

        # Close engine
        await self._engine.dispose()

        logger.info("TradeDBWriter stopped")

    async def write_trade_entry(
        self,
        trade: "Trade",
        strategy_name: str,
        signal_reason: Optional[str] = None,
        signal_metadata: Optional[dict] = None,
    ) -> None:
        """Add a new trade entry to the buffer.

        If the buffer reaches batch_size, triggers an immediate flush.

        Args:
            trade: Trade dataclass instance to persist.
            strategy_name: REQUIRED - name of strategy that generated the trade.
            signal_reason: Optional reason extracted from signal.metadata.get('reason').
            signal_metadata: Optional signal metadata dict.

        Raises:
            ValueError: If strategy_name is None or empty.
        """
        record = TradeRecord.from_trade(trade, strategy_name, signal_reason, signal_metadata)

        should_flush = False
        async with self._buffer_lock:
            self._buffer.append(record)
            should_flush = len(self._buffer) >= self._batch_size

        # Flush outside the lock to avoid blocking other adds
        if should_flush:
            asyncio.create_task(self._flush_buffer())

    async def update_trade_exit(
        self,
        trade_id: str,
        exit_price: float,
        exit_time: datetime,
        pnl_dollars: float,
        pnl_percent: float,
    ) -> None:
        """Update existing trade with exit details.

        This is called when a position is closed to update the trade record
        with exit price, time, and PnL calculations.

        IMPORTANT: Flushes the buffer first to ensure the entry record exists
        in the database before attempting the UPDATE.

        Args:
            trade_id: UUID of the trade to update.
            exit_price: The exit price.
            exit_time: The exit timestamp.
            pnl_dollars: Profit/loss in dollars.
            pnl_percent: Profit/loss as percentage.
        """
        try:
            # Flush buffer first to ensure entry record is in DB
            await self._flush_buffer()
            async with self._session_factory() as session:
                async with session.begin():
                    stmt = (
                        update(TradeRecord)
                        .where(TradeRecord.trade_id == uuid.UUID(trade_id))
                        .values(
                            exit_price=Decimal(str(exit_price)),
                            exit_time=exit_time,
                            pnl_dollars=Decimal(str(pnl_dollars)),
                            pnl_percent=Decimal(str(pnl_percent)),
                            status="closed",
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
                    result = await session.execute(stmt)

                    if result.rowcount == 0:
                        logger.warning(
                            "Trade record not found for update: %s (entry may not be flushed yet)",
                            trade_id[:8],
                        )
                    else:
                        logger.debug(
                            "Trade exit updated: %s, PnL: $%.2f (%.2f%%)",
                            trade_id[:8],
                            pnl_dollars,
                            pnl_percent,
                        )

        except Exception as e:
            logger.warning(
                "Failed to update trade exit for %s: %s",
                trade_id[:8],
                e,
            )

    async def _flush_timer_loop(self) -> None:
        """Background loop that flushes buffer periodically."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                if self._buffer:
                    await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in trade flush timer loop: %s", e)

    async def _flush_buffer(self) -> None:
        """Flush all buffered entries to the database.

        Thread-safe: Uses lock to swap out buffer atomically.
        """
        # Atomically swap out the buffer
        async with self._buffer_lock:
            if not self._buffer:
                return
            entries_to_flush = self._buffer
            self._buffer = []

        try:
            await self._batch_insert(entries_to_flush)
            logger.debug(
                "Flushed %d trade entries to TimescaleDB",
                len(entries_to_flush),
            )
        except Exception as e:
            logger.exception(
                "Failed to flush %d trade entries: %s",
                len(entries_to_flush),
                e,
            )
            # Re-add entries to buffer on failure (best effort)
            async with self._buffer_lock:
                self._buffer = entries_to_flush + self._buffer

    async def _batch_insert(self, records: list[TradeRecord]) -> None:
        """Insert a batch of trade records to the database.

        Args:
            records: List of TradeRecord instances to insert.
        """
        async with self._session_factory() as session:
            async with session.begin():
                session.add_all(records)

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get an async session for direct database access.

        This is useful for CLI queries.

        Yields:
            AsyncSession for database queries.
        """
        async with self._session_factory() as session:
            yield session

    @property
    def buffer_size(self) -> int:
        """Current number of entries in the buffer."""
        return len(self._buffer)

    @property
    def is_running(self) -> bool:
        """Whether the writer is currently running."""
        return self._running
