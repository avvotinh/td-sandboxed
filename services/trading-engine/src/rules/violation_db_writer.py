"""Rule Violation DB Writer - Batch persistence to TimescaleDB rule_violations hypertable."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Column, DateTime, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .audit_db_writer import Base
from .violation import RuleViolation

logger = logging.getLogger(__name__)


class RuleViolationModel(Base):
    """SQLAlchemy ORM model for rule_violations hypertable.

    Maps all 17 columns from init.sql exactly.
    """

    __tablename__ = "rule_violations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    rule_type = Column(String(50), nullable=False)
    rule_name = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False)
    current_value = Column(Numeric(18, 4), nullable=True)
    threshold_value = Column(Numeric(18, 4), nullable=True)
    threshold_percent = Column(Numeric(8, 4), nullable=True)
    action_taken = Column(String(50), nullable=False)
    trade_id = Column(UUID(as_uuid=True), nullable=True)
    order_blocked = Column(Boolean, default=False)
    message = Column(Text, nullable=True)
    context = Column(JSONB, nullable=True)
    acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_violation(cls, violation: RuleViolation) -> "RuleViolationModel":
        """Convert a RuleViolation dataclass to an ORM model instance.

        Validates severity and action_taken against DB CHECK constraints.
        """
        valid_severities = {"INFO", "WARNING", "CRITICAL", "FATAL"}
        if violation.severity not in valid_severities:
            raise ValueError(
                f"Invalid severity '{violation.severity}'. Must be one of {valid_severities}"
            )

        valid_actions = {"blocked", "warned", "notified", "logged"}
        if violation.action_taken not in valid_actions:
            raise ValueError(
                f"Invalid action_taken '{violation.action_taken}'. Must be one of {valid_actions}"
            )

        return cls(
            account_id=violation.account_id,
            timestamp=violation.timestamp,
            rule_type=violation.rule_type,
            rule_name=violation.rule_name,
            severity=violation.severity,
            current_value=Decimal(str(violation.current_value)) if violation.current_value is not None else None,
            threshold_value=Decimal(str(violation.threshold_value)) if violation.threshold_value is not None else None,
            threshold_percent=Decimal(str(violation.threshold_percent)) if violation.threshold_percent is not None else None,
            action_taken=violation.action_taken,
            trade_id=uuid.UUID(violation.trade_id) if violation.trade_id else None,
            order_blocked=violation.order_blocked,
            message=violation.message,
            context=violation.context or None,
            acknowledged=violation.acknowledged,
            acknowledged_at=violation.acknowledged_at,
        )


class ViolationDBWriter:
    """Batched writer for persisting rule violations to TimescaleDB.

    Follows same pattern as AuditDBWriter for consistency.
    """

    def __init__(
        self,
        database_url: str,
        batch_size: int = 100,
        flush_interval: float = 60.0,
    ) -> None:
        self._database_url = database_url
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._buffer: list[RuleViolationModel] = []
        self._buffer_lock = asyncio.Lock()

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

        self._flush_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the batch writer and flush timer."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(
            self._flush_timer_loop(),
            name="violation_db_flush_timer",
        )
        logger.info(
            "ViolationDBWriter started (batch=%d, interval=%.1fs)",
            self._batch_size,
            self._flush_interval,
        )

    async def stop(self) -> None:
        """Stop the batch writer and flush remaining entries."""
        if not self._running:
            return
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self._flush_buffer()
        await self._engine.dispose()
        logger.info("ViolationDBWriter stopped")

    async def add_violation(self, violation: RuleViolation) -> None:
        """Add violation to buffer for batch persistence."""
        model = RuleViolationModel.from_violation(violation)
        should_flush = False
        async with self._buffer_lock:
            self._buffer.append(model)
            should_flush = len(self._buffer) >= self._batch_size
        if should_flush:
            task = asyncio.create_task(self._flush_buffer())
            task.add_done_callback(self._flush_task_done)

    @staticmethod
    def _flush_task_done(task: asyncio.Task) -> None:
        """Callback for batch-threshold flush tasks to log errors."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.warning("Batch flush task failed: %s", exc)

    async def _flush_timer_loop(self) -> None:
        """Periodically flush buffer to database."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                if self._buffer:
                    await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in violation flush timer loop: %s", e)

    async def _flush_buffer(self) -> None:
        """Flush buffered violations to TimescaleDB."""
        async with self._buffer_lock:
            if not self._buffer:
                return
            entries_to_flush = self._buffer
            self._buffer = []

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add_all(entries_to_flush)
            logger.debug("Flushed %d violations to TimescaleDB", len(entries_to_flush))
        except Exception:
            logger.exception("Failed to flush %d violations, re-adding to buffer", len(entries_to_flush))
            async with self._buffer_lock:
                self._buffer = entries_to_flush + self._buffer

    @property
    def buffer_size(self) -> int:
        """Current number of entries in the buffer."""
        return len(self._buffer)

    @property
    def is_running(self) -> bool:
        """Whether the writer is currently running."""
        return self._running
