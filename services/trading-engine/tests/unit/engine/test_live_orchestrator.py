"""Unit tests for :class:`LiveOrchestrator` (story 10.2 — pre-built bundle)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.engine.collaborators import LiveServiceBundle
from src.engine.live_orchestrator import LiveOrchestrator


@pytest.mark.asyncio
async def test_start_with_empty_bundle_is_noop():
    """An empty LiveServiceBundle starts and stops without raising."""
    live = LiveOrchestrator(services=LiveServiceBundle())
    await live.start()
    await live.stop()
    assert live.cold_storage_service is None
    assert live.trade_db_writer is None
    assert live.violation_service is None


@pytest.mark.asyncio
async def test_start_calls_each_service_in_order():
    """Each present service in the bundle has its ``start()`` awaited."""
    cold_storage = AsyncMock()
    trade_writer = AsyncMock()
    violation_writer = AsyncMock()
    snapshot_writer = AsyncMock()
    daily_service = AsyncMock()

    bundle = LiveServiceBundle(
        cold_storage_service=cold_storage,
        trade_db_writer=trade_writer,
        violation_db_writer=violation_writer,
        violation_service=AsyncMock(),
        daily_snapshot_writer=snapshot_writer,
        daily_snapshot_service=daily_service,
    )

    live = LiveOrchestrator(services=bundle)
    await live.start()

    cold_storage.start.assert_awaited_once()
    trade_writer.start.assert_awaited_once()
    violation_writer.start.assert_awaited_once()
    snapshot_writer.start.assert_awaited_once()
    daily_service.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_runs_in_reverse_order_excluding_cold_storage():
    """``stop()`` tears down all services except ``ColdStorageService``."""
    cold_storage = AsyncMock()
    trade_writer = AsyncMock()
    violation_writer = AsyncMock()
    snapshot_writer = AsyncMock()
    daily_service = AsyncMock()

    bundle = LiveServiceBundle(
        cold_storage_service=cold_storage,
        trade_db_writer=trade_writer,
        violation_db_writer=violation_writer,
        violation_service=AsyncMock(),
        daily_snapshot_writer=snapshot_writer,
        daily_snapshot_service=daily_service,
    )

    live = LiveOrchestrator(services=bundle)
    await live.stop()

    daily_service.stop.assert_awaited_once()
    snapshot_writer.stop.assert_awaited_once()
    trade_writer.stop.assert_awaited_once()
    violation_writer.stop.assert_awaited_once()
    # Cold storage is intentionally left to GracefulShutdown
    cold_storage.stop.assert_not_called()


@pytest.mark.asyncio
async def test_stop_safe_when_partially_built():
    """Bundles with only some services still stop cleanly."""
    trade_writer = AsyncMock()
    bundle = LiveServiceBundle(trade_db_writer=trade_writer)
    live = LiveOrchestrator(services=bundle)
    await live.stop()
    trade_writer.stop.assert_awaited_once()


def test_property_forwarders_expose_bundle_members():
    """Read-only properties forward to the underlying bundle."""
    cold_storage = object()
    trade_writer = object()
    violation_service = object()

    bundle = LiveServiceBundle(
        cold_storage_service=cold_storage,
        trade_db_writer=trade_writer,
        violation_service=violation_service,
    )
    live = LiveOrchestrator(services=bundle)

    assert live.cold_storage_service is cold_storage
    assert live.trade_db_writer is trade_writer
    assert live.violation_service is violation_service
