"""Bounded-queue audit writer.

Story 10.3 replaces the fire-and-forget ``audit_task_done_callback`` pattern
with a bounded ``asyncio.Queue`` + worker:

- :meth:`AuditWriter.log_sync` opens a session and commits the entry inline.
  Use this for any write to ``account.*`` tables: the audit row must hit the
  DB before the state mutation that follows.
- :meth:`AuditWriter.log_async` enqueues an entry; a background worker
  batches and INSERTs them. The queue applies back-pressure (``put`` blocks
  when full) so we cannot silently drop entries.
- :meth:`AuditWriter.drain` waits until every queued entry is persisted —
  called from :class:`GracefulShutdown` before the DB connection is closed.

The class uses the existing :class:`AuditLogModel` for persistence so the
on-disk schema stays identical to the legacy ``AuditDBWriter`` path.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..rules.audit_db_writer import AuditLogModel
from ..rules.audit_logger import AuditEntry

logger = logging.getLogger(__name__)


SessionFactory = Callable[[], AsyncSession] | async_sessionmaker[AsyncSession]


class AuditWriter:
    """Audit persistence with a bounded queue + drain-on-shutdown semantics.

    Args:
        session_factory: Callable returning an ``AsyncSession`` context
            manager. Typically the project's ``async_sessionmaker``.
        queue_size: Max in-flight async entries. ``put`` blocks once full
            (back-pressure) so callers cannot bypass durability by spamming.
        batch_size: Max entries per worker batch INSERT.
        batch_timeout: Seconds to wait for a full batch before flushing
            whatever is queued. Keeps p99 latency for low-volume periods low.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        queue_size: int = 10_000,
        batch_size: int = 100,
        batch_timeout: float = 0.5,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if batch_timeout <= 0:
            raise ValueError("batch_timeout must be positive")

        self._session_factory = session_factory
        self._queue: asyncio.Queue[AuditEntry] = asyncio.Queue(maxsize=queue_size)
        self._batch_size = batch_size
        self._batch_timeout = batch_timeout
        self._worker_task: asyncio.Task[None] | None = None
        self._running = False
        # Buffer for entries pulled by ``_collect_batch`` but not yet handed to
        # ``_batch_insert``. Cancellation between the two phases would leak the
        # ``_queue.get()`` calls (drain() would hang forever); the worker loop
        # marks them done explicitly when it catches CancelledError.
        self._pending_batch: list[AuditEntry] = []
        # Entries reclaimed when the worker is cancelled mid-batch — flushed
        # via ``_flush_remaining`` during stop().
        self._leftover: list[AuditEntry] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        """Start the background worker. Idempotent."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(
            self._worker_loop(), name="audit_writer_worker"
        )
        logger.info(
            "AuditWriter started (queue_size=%d, batch_size=%d, batch_timeout=%.2fs)",
            self._queue.maxsize,
            self._batch_size,
            self._batch_timeout,
        )

    async def stop(self) -> None:
        """Drain pending entries, cancel the worker, mark stopped. Idempotent."""
        if not self._running:
            return
        self._running = False

        # Best-effort drain before tearing down the worker.
        try:
            await self.drain(timeout=self._drain_timeout())
        except asyncio.TimeoutError:
            logger.warning(
                "AuditWriter.stop: drain timed out with %d entries still queued",
                self.queue_size,
            )

        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            except Exception:  # pragma: no cover — defensive
                logger.exception("AuditWriter worker raised on shutdown")
            self._worker_task = None

        # Final flush in case anything got enqueued during cancellation.
        await self._flush_remaining()
        logger.info("AuditWriter stopped")

    async def log_sync(self, entry: AuditEntry) -> None:
        """Persist ``entry`` immediately, blocking the caller until commit.

        Use for any write that must be durable before the next state
        mutation (account.* tables, emergency events, etc.). The exception
        is propagated to the caller; an audit failure must abort the
        accompanying mutation.
        """
        await self._batch_insert([entry])

    async def log_async(self, entry: AuditEntry) -> None:
        """Enqueue ``entry`` for batched persistence.

        Blocks if the queue is full (back-pressure). For telemetry / metrics
        events where the latency hit of a synchronous DB write is not
        warranted but durability is still required.
        """
        if not self._running:
            logger.warning(
                "AuditWriter.log_async called before start(); entry will sit in "
                "the queue until start() is called. Queue size: %d",
                self.queue_size,
            )
        await self._queue.put(entry)

    async def drain(self, timeout: float | None = None) -> None:
        """Wait until every queued entry is persisted.

        Args:
            timeout: Optional seconds to wait. ``None`` waits indefinitely.

        Raises:
            asyncio.TimeoutError: If ``timeout`` elapses before the queue
                is drained.
        """
        if timeout is None:
            await self._queue.join()
            return
        await asyncio.wait_for(self._queue.join(), timeout=timeout)

    async def _worker_loop(self) -> None:
        """Drain the queue forever, batching INSERTs."""
        while True:
            batch: list[AuditEntry] = []
            try:
                batch = await self._collect_batch()
            except asyncio.CancelledError:
                # Cancellation may strike after some entries have been pulled
                # off the queue but before they reach _batch_insert. Mark them
                # done so drain() does not deadlock; ``_flush_remaining`` (in
                # stop()) will persist them via get_nowait + log_sync.
                pending = list(self._pending_batch)
                self._pending_batch = []
                for entry in pending:
                    self._queue.task_done()
                    # Re-queue is impossible (queue may be closed by now); push
                    # back into the leftover list instead.
                    self._leftover.append(entry)
                raise
            try:
                if batch:
                    await self._batch_insert(batch)
            except Exception:
                logger.exception(
                    "AuditWriter worker failed to flush batch of %d entries",
                    len(batch),
                )
            finally:
                for _ in batch:
                    self._queue.task_done()

    async def _collect_batch(self) -> list[AuditEntry]:
        """Pull up to ``batch_size`` entries, capped by ``batch_timeout``."""
        self._pending_batch = []
        first = await self._queue.get()
        self._pending_batch.append(first)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._batch_timeout
        while len(self._pending_batch) < self._batch_size:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                nxt = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            self._pending_batch.append(nxt)

        batch = self._pending_batch
        self._pending_batch = []
        return batch

    async def _batch_insert(self, entries: list[AuditEntry]) -> None:
        """Persist a batch of entries inside a single transaction."""
        if not entries:
            return
        models = [AuditLogModel.from_audit_entry(entry) for entry in entries]
        async with self._session_factory() as session:
            async with session.begin():
                session.add_all(models)

    async def _flush_remaining(self) -> None:
        """Drain whatever is left without the worker running."""
        # Combine: (a) entries reclaimed from a cancelled in-flight batch and
        # (b) entries still sitting in the queue.
        leftover: list[AuditEntry] = list(self._leftover)
        self._leftover = []
        marked_done = 0
        while True:
            try:
                leftover.append(self._queue.get_nowait())
                marked_done += 1
            except asyncio.QueueEmpty:
                break
        if not leftover:
            return
        try:
            await self._batch_insert(leftover)
        except Exception:
            logger.exception(
                "AuditWriter failed to flush %d trailing entries on shutdown",
                len(leftover),
            )
        finally:
            # Only entries pulled via get_nowait() above need task_done — the
            # leftover-from-cancellation entries were already marked done in
            # the worker's CancelledError branch.
            for _ in range(marked_done):
                self._queue.task_done()

    def _drain_timeout(self) -> float:
        """Heuristic upper bound for drain during stop(); avoids hanging shutdown."""
        # Queue size × per-entry budget, capped at 30s — matches GracefulShutdown
        # PENDING_ORDER_TIMEOUT_SECONDS so the audit drain cannot outlast the
        # surrounding shutdown phase.
        return min(30.0, max(2.0, self.queue_size * 0.05))
