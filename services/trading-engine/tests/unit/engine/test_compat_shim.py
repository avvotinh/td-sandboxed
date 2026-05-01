"""Unit tests for the :class:`TradingEngine` backwards-compat shim and
:func:`build_lifecycle` factory in `src/engine/__init__.py` (story 10.1).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.engine import (
    EngineConfig,
    EngineLifecycle,
    LiveOrchestrator,
    RecoveryOrchestrator,
    TradingEngine,
    build_lifecycle,
)


def test_trading_engine_default_construction_matches_legacy_api():
    """`TradingEngine()` (no kwargs) produces a working instance."""
    engine = TradingEngine()
    assert engine.is_running is False
    assert engine.recovery_result is None
    assert engine.reconciliation_results is None
    assert engine.pnl_recalculation_results is None
    assert engine.resume_result is None
    assert engine.shutdown_result is None
    assert engine.trade_db_writer is None


def test_trading_engine_accepts_all_legacy_kwargs():
    """All 9 legacy kwargs flow into EngineConfig without error."""
    engine = TradingEngine(
        redis_manager=MagicMock(),
        zmq_adapter=MagicMock(),
        db_session_factory=MagicMock(),
        risk_registry=MagicMock(),
        pnl_registry=MagicMock(),
        account_manager=MagicMock(),
        snapshot_service=MagicMock(),
        database_url="postgresql+asyncpg://test@localhost/test",
        audit_service=MagicMock(),
        firm_registry=MagicMock(),
    )
    assert isinstance(engine._config, EngineConfig)
    assert isinstance(engine._lifecycle, EngineLifecycle)


def test_build_lifecycle_returns_engine_lifecycle():
    """`build_lifecycle(EngineConfig())` returns a wired EngineLifecycle."""
    config = EngineConfig()
    lifecycle = build_lifecycle(config)
    assert isinstance(lifecycle, EngineLifecycle)
    assert isinstance(lifecycle._recovery, RecoveryOrchestrator)
    assert isinstance(lifecycle._live, LiveOrchestrator)


@pytest.mark.asyncio
async def test_trading_engine_run_and_shutdown_delegate_to_lifecycle():
    """TradingEngine.run/shutdown delegate to the wrapped EngineLifecycle."""
    engine = TradingEngine()
    engine._lifecycle = MagicMock()
    engine._lifecycle.run = AsyncMock()
    engine._lifecycle.shutdown = AsyncMock()
    await engine.run()
    await engine.shutdown()
    engine._lifecycle.run.assert_awaited_once()
    engine._lifecycle.shutdown.assert_awaited_once()


def test_trading_engine_property_forwarders_return_lifecycle_state():
    """Each legacy property returns whatever the lifecycle exposes."""
    engine = TradingEngine()
    fake_lifecycle = MagicMock()
    fake_lifecycle.is_running = True
    fake_lifecycle.recovery_result = "recovery"
    fake_lifecycle.reconciliation_results = {"a": "b"}
    fake_lifecycle.pnl_recalculation_results = {"c": "d"}
    fake_lifecycle.resume_result = "resume"
    fake_lifecycle.shutdown_result = "shutdown"
    fake_lifecycle.trade_db_writer = "writer"
    engine._lifecycle = fake_lifecycle

    assert engine.is_running is True
    assert engine.recovery_result == "recovery"
    assert engine.reconciliation_results == {"a": "b"}
    assert engine.pnl_recalculation_results == {"c": "d"}
    assert engine.resume_result == "resume"
    assert engine.shutdown_result == "shutdown"
    assert engine.trade_db_writer == "writer"
