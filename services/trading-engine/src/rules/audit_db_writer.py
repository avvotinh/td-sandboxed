"""Audit DB Writer - Batch persistence of audit entries to TimescaleDB.

This module provides the AuditDBWriter class that buffers audit entries
and periodically flushes them to TimescaleDB in batches for efficiency.

Key design decisions:
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
from typing import AsyncGenerator

from sqlalchemy import Column, DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .audit_logger import AuditEntry

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for audit models."""

    pass


class AuditLogModel(Base):
    """SQLAlchemy model for audit_logs hypertable.

    Maps to the TimescaleDB audit_logs table as defined in architecture:

    CREATE TABLE audit_logs (
        log_id UUID PRIMARY KEY,
        account_id VARCHAR(50) REFERENCES accounts(id),
        timestamp TIMESTAMPTZ NOT NULL,
        event_type VARCHAR(50) NOT NULL,
        rule_name VARCHAR(100),
        rule_result VARCHAR(20),
        current_value DECIMAL(18, 4),
        threshold_value DECIMAL(18, 4),
        order_id UUID,
        context JSONB,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """

    __tablename__ = "audit_logs"

    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(String(50), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    event_type = Column(String(50), nullable=False)
    rule_type = Column(String(50), nullable=True)
    rule_name = Column(String(100), nullable=True)
    rule_result = Column(String(20), nullable=True)
    current_value = Column(Numeric(18, 4), nullable=True)
    threshold_value = Column(Numeric(18, 4), nullable=True)
    order_id = Column(UUID(as_uuid=True), nullable=True)
    context = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_audit_entry(cls, entry: AuditEntry) -> "AuditLogModel":
        """Create an AuditLogModel from an AuditEntry.

        Args:
            entry: AuditEntry to convert.

        Returns:
            AuditLogModel instance.
        """
        # Convert order_id string to UUID if present
        order_uuid = None
        if entry.order_id:
            try:
                order_uuid = uuid.UUID(entry.order_id)
            except (ValueError, TypeError):
                # If order_id is not a valid UUID, store as None
                logger.debug("Order ID %s is not a valid UUID, storing as None", entry.order_id)

        return cls(
            log_id=uuid.uuid4(),
            account_id=entry.account_id,
            timestamp=entry.timestamp,
            event_type=entry.event_type,
            rule_type=entry.rule_type,
            rule_name=entry.rule_name,
            rule_result=entry.rule_result,
            current_value=Decimal(str(entry.current_value)) if entry.current_value is not None else None,
            threshold_value=Decimal(str(entry.threshold_value)) if entry.threshold_value is not None else None,
            order_id=order_uuid,
            context=entry.context,
        )


class AuditDBWriter:
    """Batched writer for persisting audit entries to TimescaleDB.

    The AuditDBWriter buffers audit entries and flushes them to the database
    either when the buffer reaches a size threshold or when the flush timer
    triggers.

    Attributes:
        database_url: PostgreSQL/TimescaleDB connection URL.
        batch_size: Number of entries to buffer before flushing (default: 100).
        flush_interval: Seconds between timer-based flushes (default: 60).

    Example:
        writer = AuditDBWriter("postgresql+asyncpg://user:pass@localhost/db")
        await writer.start()
        await writer.add_entry(entry)
        await writer.stop()  # Flushes remaining entries
    """

    def __init__(
        self,
        database_url: str,
        batch_size: int = 100,
        flush_interval: float = 60.0,
    ) -> None:
        """Initialize AuditDBWriter.

        Args:
            database_url: Async PostgreSQL connection URL (postgresql+asyncpg://...).
            batch_size: Number of entries to buffer before auto-flush.
            flush_interval: Seconds between timer-based flushes.
        """
        self._database_url = database_url
        self._batch_size = batch_size
        self._flush_interval = flush_interval

        # Buffer for pending entries
        self._buffer: list[AuditEntry] = []
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
            logger.warning("AuditDBWriter already running")
            return

        self._running = True
        self._flush_task = asyncio.create_task(
            self._flush_timer_loop(),
            name="audit_db_flush_timer",
        )
        logger.info(
            "AuditDBWriter started (batch_size=%d, flush_interval=%.1fs)",
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

        logger.info("AuditDBWriter stopped")

    async def add_entry(self, entry: AuditEntry) -> None:
        """Add an audit entry to the buffer.

        If the buffer reaches batch_size, triggers an immediate flush.

        Args:
            entry: AuditEntry to add.
        """
        should_flush = False
        async with self._buffer_lock:
            self._buffer.append(entry)
            should_flush = len(self._buffer) >= self._batch_size

        # Flush outside the lock to avoid blocking other adds
        # The flush method has its own lock for atomic buffer swap
        if should_flush:
            asyncio.create_task(self._flush_buffer())

    async def add_entries(self, entries: list[AuditEntry]) -> None:
        """Add multiple audit entries to the buffer.

        Args:
            entries: List of AuditEntry instances to add.
        """
        should_flush = False
        async with self._buffer_lock:
            self._buffer.extend(entries)
            should_flush = len(self._buffer) >= self._batch_size

        # Flush outside the lock to avoid blocking other adds
        if should_flush:
            asyncio.create_task(self._flush_buffer())

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
                logger.exception("Error in flush timer loop: %s", e)

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
                "Flushed %d audit entries to TimescaleDB",
                len(entries_to_flush),
            )
        except Exception as e:
            logger.exception(
                "Failed to flush %d audit entries: %s",
                len(entries_to_flush),
                e,
            )
            # Re-add entries to buffer on failure (best effort)
            async with self._buffer_lock:
                self._buffer = entries_to_flush + self._buffer

    async def _batch_insert(self, entries: list[AuditEntry]) -> None:
        """Insert a batch of entries to the database.

        Args:
            entries: List of AuditEntry instances to insert.
        """
        models = [AuditLogModel.from_audit_entry(entry) for entry in entries]

        async with self._session_factory() as session:
            async with session.begin():
                session.add_all(models)

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
