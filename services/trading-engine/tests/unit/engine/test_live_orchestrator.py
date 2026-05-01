"""Unit tests for :class:`LiveOrchestrator` skeleton (story 10.1)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine.live_orchestrator import LiveOrchestrator


def _make_orchestrator(**overrides) -> LiveOrchestrator:
    defaults = dict(
        snapshot_service=None,
        redis_manager=None,
        account_manager=None,
        db_session_factory=None,
        audit_service=None,
        firm_registry=None,
        database_url=None,
    )
    defaults.update(overrides)
    return LiveOrchestrator(**defaults)


@pytest.mark.asyncio
async def test_start_no_database_url_skips_all_db_services():
    """Without database_url, no auxiliary services are started."""
    live = _make_orchestrator()
    await live.start(cold_storage_writer=None)

    assert live.cold_storage_service is None
    assert live.trade_db_writer is None
    assert live.violation_service is None
    assert live._daily_snapshot_writer is None


@pytest.mark.asyncio
async def test_start_cold_storage_requires_snapshot_service():
    """Cold storage writer present but no snapshot_service → service stays None."""
    live = _make_orchestrator(snapshot_service=None)
    cold_writer = MagicMock()

    await live.start(cold_storage_writer=cold_writer)

    assert live.cold_storage_service is None


@pytest.mark.asyncio
async def test_start_initializes_all_services_when_deps_present():
    """All deps present → all four auxiliary services start; stop() tears them down."""
    snapshot_service = MagicMock()
    redis_manager = MagicMock()
    account_manager = MagicMock()
    session_factory = MagicMock()
    cold_writer = MagicMock()

    cold_storage_service = AsyncMock()
    trade_writer = AsyncMock()
    violation_writer = AsyncMock()
    snapshot_db_writer = AsyncMock()
    daily_snapshot_service = AsyncMock()

    live = _make_orchestrator(
        snapshot_service=snapshot_service,
        redis_manager=redis_manager,
        account_manager=account_manager,
        db_session_factory=session_factory,
        database_url="postgresql+asyncpg://test@localhost/test",
    )

    with patch(
        "src.engine.live_orchestrator.ColdStorageService",
        return_value=cold_storage_service,
    ), patch(
        "src.engine.live_orchestrator.TradeDBWriter",
        return_value=trade_writer,
    ), patch(
        "src.engine.live_orchestrator.ViolationDBWriter",
        return_value=violation_writer,
    ), patch(
        "src.engine.live_orchestrator.SnapshotDBWriter",
        return_value=snapshot_db_writer,
    ), patch(
        "src.engine.live_orchestrator.DailySnapshotService",
        return_value=daily_snapshot_service,
    ):
        await live.start(cold_storage_writer=cold_writer)

        assert live.cold_storage_service is cold_storage_service
        assert live.trade_db_writer is trade_writer
        assert live.violation_service is not None
        assert live._daily_snapshot_service is daily_snapshot_service

        cold_storage_service.start.assert_awaited_once()
        trade_writer.start.assert_awaited_once()
        violation_writer.start.assert_awaited_once()
        snapshot_db_writer.start.assert_awaited_once()
        daily_snapshot_service.start.assert_awaited_once()

        await live.stop()

        daily_snapshot_service.stop.assert_awaited_once()
        snapshot_db_writer.stop.assert_awaited_once()
        trade_writer.stop.assert_awaited_once()
        violation_writer.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_is_safe_when_start_was_never_called():
    """stop() is a no-op if no services were initialised."""
    live = _make_orchestrator()
    await live.stop()  # must not raise


@pytest.mark.asyncio
async def test_daily_snapshots_skipped_without_redis():
    """database_url present but redis missing → daily snapshots disabled."""
    live = _make_orchestrator(
        database_url="postgresql+asyncpg://test@localhost/test",
        redis_manager=None,
        account_manager=MagicMock(),
        db_session_factory=MagicMock(),
    )

    trade_writer = AsyncMock()
    violation_writer = AsyncMock()
    with patch(
        "src.engine.live_orchestrator.TradeDBWriter",
        return_value=trade_writer,
    ), patch(
        "src.engine.live_orchestrator.ViolationDBWriter",
        return_value=violation_writer,
    ):
        await live.start(cold_storage_writer=None)

    assert live._daily_snapshot_service is None
    assert live._daily_snapshot_writer is None
