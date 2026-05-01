"""Unit tests for AuditWriter — bounded queue + worker for audit persistence.

Story 10.3 introduces :class:`AuditWriter` to replace the fire-and-forget
``audit_task_done_callback`` pattern with a bounded ``asyncio.Queue`` + worker.
The class exposes two write paths:

- :meth:`log_sync`  — block caller until DB commit succeeds (safety-critical).
- :meth:`log_async` — enqueue for batched persistence (telemetry).

These tests mock the SQLAlchemy session factory so we exercise the queue,
worker batching, drain, and shutdown semantics without a real database.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audit.audit_writer import AuditWriter
from src.rules.audit_logger import AuditEntry


def _make_entry(account_id: str = "test", rule_name: str = "Test") -> AuditEntry:
    return AuditEntry(
        timestamp=datetime.now(timezone.utc),
        account_id=account_id,
        event_type="rule_check",
        rule_name=rule_name,
        rule_result="ALLOW",
    )


class _FakeSession:
    """Async-context-manager session that records add_all calls."""

    def __init__(self, sink: list[list[Any]]) -> None:
        self._sink = sink

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def begin(self) -> "_FakeBegin":
        return _FakeBegin()

    def add_all(self, models: list[Any]) -> None:
        self._sink.append(list(models))


class _FakeBegin:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


def _make_session_factory(sink: list[list[Any]]) -> Any:
    """Return a callable that produces fake sessions appending to ``sink``."""

    return lambda: _FakeSession(sink)


class TestAuditWriterLogSync:
    """log_sync persists entry immediately and blocks until commit returns."""

    @pytest.mark.asyncio
    async def test_log_sync_inserts_immediately(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(_make_session_factory(sink))

        await writer.log_sync(_make_entry())

        assert len(sink) == 1
        assert len(sink[0]) == 1

    @pytest.mark.asyncio
    async def test_log_sync_does_not_use_queue(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(_make_session_factory(sink))

        await writer.log_sync(_make_entry())

        assert writer.queue_size == 0

    @pytest.mark.asyncio
    async def test_log_sync_propagates_db_errors(self) -> None:
        def factory() -> Any:  # noqa: ANN401
            session = MagicMock()
            session.__aenter__ = AsyncMock(side_effect=RuntimeError("db down"))
            session.__aexit__ = AsyncMock()
            return session

        writer = AuditWriter(factory)

        with pytest.raises(RuntimeError, match="db down"):
            await writer.log_sync(_make_entry())


class TestAuditWriterLogAsync:
    """log_async enqueues entry and applies back-pressure when full."""

    @pytest.mark.asyncio
    async def test_log_async_enqueues_without_db_call(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(_make_session_factory(sink))

        await writer.log_async(_make_entry())

        assert writer.queue_size == 1
        assert sink == []

    @pytest.mark.asyncio
    async def test_log_async_back_pressure_when_full(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(_make_session_factory(sink), queue_size=2)

        await writer.log_async(_make_entry())
        await writer.log_async(_make_entry())

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(writer.log_async(_make_entry()), timeout=0.05)


class TestAuditWriterStartStop:
    """Lifecycle — start spawns worker, stop drains and cancels."""

    @pytest.mark.asyncio
    async def test_start_idempotent(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(_make_session_factory(sink))

        await writer.start()
        first_task = writer._worker_task  # type: ignore[attr-defined]
        await writer.start()

        assert writer._worker_task is first_task  # type: ignore[attr-defined]

        await writer.stop()

    @pytest.mark.asyncio
    async def test_stop_idempotent_when_not_running(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(_make_session_factory(sink))

        await writer.stop()  # must not raise

        assert writer.is_running is False

    @pytest.mark.asyncio
    async def test_stop_flushes_pending_entries(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(
            _make_session_factory(sink),
            batch_size=10,
            batch_timeout=0.01,
        )

        await writer.start()

        # Enqueue without giving worker time to drain
        for _ in range(5):
            await writer.log_async(_make_entry())

        await writer.stop()

        flushed = sum(len(batch) for batch in sink)
        assert flushed == 5
        assert writer.queue_size == 0
        assert writer.is_running is False


class TestAuditWriterWorkerBatching:
    """Worker drains queue in batches up to batch_size or batch_timeout."""

    @pytest.mark.asyncio
    async def test_worker_batches_up_to_batch_size(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(
            _make_session_factory(sink),
            batch_size=3,
            batch_timeout=5.0,
        )

        await writer.start()

        for _ in range(3):
            await writer.log_async(_make_entry())

        # Wait for at least one batch flush
        await writer.drain(timeout=1.0)
        await writer.stop()

        assert any(len(batch) == 3 for batch in sink)

    @pytest.mark.asyncio
    async def test_worker_flushes_partial_batch_on_timeout(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(
            _make_session_factory(sink),
            batch_size=100,
            batch_timeout=0.05,
        )

        await writer.start()

        await writer.log_async(_make_entry())

        await writer.drain(timeout=1.0)
        await writer.stop()

        # Single entry was flushed despite batch_size=100 because timeout fired
        flushed = sum(len(batch) for batch in sink)
        assert flushed == 1


class TestAuditWriterDrain:
    """drain() blocks until queue is empty and all entries persisted."""

    @pytest.mark.asyncio
    async def test_drain_returns_immediately_when_empty(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(_make_session_factory(sink))

        await writer.start()
        await writer.drain(timeout=1.0)  # nothing to wait for
        await writer.stop()

    @pytest.mark.asyncio
    async def test_drain_waits_for_queued_entries(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(
            _make_session_factory(sink),
            batch_size=10,
            batch_timeout=0.05,
        )

        await writer.start()

        for _ in range(7):
            await writer.log_async(_make_entry())

        await writer.drain(timeout=2.0)

        assert writer.queue_size == 0
        assert sum(len(batch) for batch in sink) == 7

        await writer.stop()

    @pytest.mark.asyncio
    async def test_drain_raises_on_timeout(self) -> None:
        """drain() raises asyncio.TimeoutError if the queue cannot be cleared in time."""

        sink: list[list[Any]] = []
        writer = AuditWriter(_make_session_factory(sink))
        # Do not start worker — entries cannot drain
        await writer.log_async(_make_entry())

        with pytest.raises(asyncio.TimeoutError):
            await writer.drain(timeout=0.05)


class TestAuditWriterUsageWarnings:
    """log_async on a non-running writer must warn — entries would be stranded."""

    @pytest.mark.asyncio
    async def test_log_async_without_start_emits_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(_make_session_factory(sink))

        with caplog.at_level("WARNING"):
            await writer.log_async(_make_entry())

        assert any(
            "before start()" in record.message for record in caplog.records
        ), caplog.text


class TestAuditWriterCancellationSafety:
    """Worker cancellation mid-batch must not leak queue.task_done() calls.

    Without this guarantee, ``drain()`` would deadlock on shutdown because
    ``Queue.join()`` waits on the unfinished_tasks counter.
    """

    @pytest.mark.asyncio
    async def test_stop_after_partial_collection_drains_cleanly(self) -> None:
        sink: list[list[Any]] = []
        # Long batch_timeout so the worker is still inside ``_collect_batch``
        # waiting for more entries when stop() cancels it.
        writer = AuditWriter(
            _make_session_factory(sink),
            batch_size=100,
            batch_timeout=10.0,
        )

        await writer.start()

        for _ in range(3):
            await writer.log_async(_make_entry())

        # Give the worker enough time to pull the first entry but not enough
        # to hit batch_timeout.
        await asyncio.sleep(0.05)

        await writer.stop()

        # Every queued entry persisted via _flush_remaining
        assert sum(len(batch) for batch in sink) == 3
        assert writer.queue_size == 0


class TestAuditWriterErrorHandling:
    """Worker keeps running even if one batch INSERT fails."""

    @pytest.mark.asyncio
    async def test_worker_continues_after_batch_failure(self) -> None:
        sink: list[list[Any]] = []
        attempt = {"count": 0}

        def factory() -> Any:  # noqa: ANN401
            attempt["count"] += 1
            if attempt["count"] == 1:
                # Fail on first batch only
                session = MagicMock()
                session.__aenter__ = AsyncMock(side_effect=RuntimeError("transient"))
                session.__aexit__ = AsyncMock()
                return session
            return _FakeSession(sink)

        writer = AuditWriter(
            factory,
            batch_size=1,
            batch_timeout=0.05,
        )

        await writer.start()
        await writer.log_async(_make_entry(rule_name="first"))
        # Wait briefly so the failing batch attempt completes
        await asyncio.sleep(0.1)
        await writer.log_async(_make_entry(rule_name="second"))
        await writer.drain(timeout=2.0)
        await writer.stop()

        # Second entry persisted via the working session
        assert sum(len(batch) for batch in sink) == 1


class TestAuditWriterIntegration:
    """End-to-end flow: enqueue → worker drains → DB receives entries."""

    @pytest.mark.asyncio
    async def test_burst_enqueue_then_drain(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(
            _make_session_factory(sink),
            batch_size=20,
            batch_timeout=0.02,
        )

        await writer.start()

        for i in range(50):
            await writer.log_async(_make_entry(rule_name=f"rule-{i}"))

        await writer.drain(timeout=3.0)
        await writer.stop()

        total = sum(len(batch) for batch in sink)
        assert total == 50

    @pytest.mark.asyncio
    async def test_mixed_sync_and_async(self) -> None:
        sink: list[list[Any]] = []
        writer = AuditWriter(_make_session_factory(sink), batch_timeout=0.02)

        await writer.start()

        await writer.log_sync(_make_entry(rule_name="sync-1"))
        await writer.log_async(_make_entry(rule_name="async-1"))
        await writer.log_sync(_make_entry(rule_name="sync-2"))

        await writer.drain(timeout=2.0)
        await writer.stop()

        total = sum(len(batch) for batch in sink)
        assert total == 3

    @pytest.mark.asyncio
    async def test_uses_audit_log_model_for_persistence(self) -> None:
        """Worker passes AuditLogModel instances (not raw entries) to add_all."""
        sink: list[list[Any]] = []
        writer = AuditWriter(_make_session_factory(sink), batch_timeout=0.02)

        with patch(
            "src.audit.audit_writer.AuditLogModel.from_audit_entry"
        ) as mock_from:
            mock_from.return_value = "MODEL"
            await writer.log_sync(_make_entry())

        assert mock_from.called
        assert sink == [["MODEL"]]
