"""Unit tests for the :class:`TradingEngine` backwards-compat shim,
:class:`EngineConfig` validation, and :func:`build_lifecycle` factory
in `src/engine/__init__.py` (story 10.2).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.engine import (
    EngineConfig,
    EngineConfigError,
    EngineLifecycle,
    LiveOrchestrator,
    RecoveryOrchestrator,
    TradingEngine,
    build_lifecycle,
)


def test_trading_engine_default_construction_is_empty_config():
    """`TradingEngine()` (no args) wires an empty config."""
    engine = TradingEngine()
    assert engine.is_running is False
    assert engine.recovery_result is None
    assert engine.reconciliation_results is None
    assert engine.pnl_recalculation_results is None
    assert engine.resume_result is None
    assert engine.shutdown_result is None
    assert engine.trade_db_writer is None


def test_trading_engine_accepts_engine_config():
    """`TradingEngine(EngineConfig(...))` wires the supplied deps."""
    config = EngineConfig(redis_manager=MagicMock())
    engine = TradingEngine(config)
    assert engine._config is config
    assert isinstance(engine._lifecycle, EngineLifecycle)


def test_engine_config_empty_factory_returns_no_op_config():
    """`EngineConfig.empty()` exposes the no-deps config used by tests."""
    config = EngineConfig.empty()
    assert config.redis_manager is None
    assert config.database_url is None


def test_engine_config_rejects_database_url_without_session_factory():
    """``__post_init__`` flags database_url without db_session_factory."""
    with pytest.raises(EngineConfigError):
        EngineConfig(database_url="postgresql+asyncpg://localhost/test")


def test_feature_flags_match_dependency_groups():
    """``feature_flags`` derives the active subsystems from present deps."""
    redis = MagicMock()
    account_manager = MagicMock()
    risk_registry = MagicMock()
    pnl_registry = MagicMock()
    session_factory = MagicMock()

    config = EngineConfig(
        redis_manager=redis,
        zmq_adapter=MagicMock(),
        db_session_factory=session_factory,
        risk_registry=risk_registry,
        pnl_registry=pnl_registry,
        account_manager=account_manager,
        snapshot_service=MagicMock(),
        database_url="postgresql+asyncpg://localhost/test",
    )

    flags = config.feature_flags()
    assert flags.crash_recovery is True
    assert flags.cold_storage is True
    assert flags.position_reconciliation is True
    assert flags.pnl_recalculation is True
    assert flags.trading_resume is True
    assert flags.trade_audit is True
    assert flags.violation_tracking is True
    assert flags.daily_snapshots is True
    assert flags.graceful_shutdown is True


def test_feature_flags_partial_config_disables_dependent_features():
    """Without a Redis manager, every Redis-dependent feature is disabled."""
    flags = EngineConfig().feature_flags()
    assert flags.crash_recovery is False
    assert flags.cold_storage is False
    assert flags.position_reconciliation is False
    assert flags.pnl_recalculation is False
    assert flags.trading_resume is False
    assert flags.trade_audit is False
    assert flags.violation_tracking is False
    assert flags.daily_snapshots is False
    assert flags.graceful_shutdown is False


def test_build_lifecycle_returns_engine_lifecycle_with_orchestrators():
    """`build_lifecycle(EngineConfig())` returns a wired EngineLifecycle."""
    lifecycle = build_lifecycle(EngineConfig.empty())
    assert isinstance(lifecycle, EngineLifecycle)
    assert isinstance(lifecycle._recovery, RecoveryOrchestrator)
    assert isinstance(lifecycle._live, LiveOrchestrator)
    # Empty config → no graceful shutdown wired
    assert lifecycle._graceful_shutdown is None


@pytest.mark.asyncio
async def test_trading_engine_run_and_shutdown_delegate_to_lifecycle():
    engine = TradingEngine()
    engine._lifecycle = MagicMock()
    engine._lifecycle.run = AsyncMock()
    engine._lifecycle.shutdown = AsyncMock()
    await engine.run()
    await engine.shutdown()
    engine._lifecycle.run.assert_awaited_once()
    engine._lifecycle.shutdown.assert_awaited_once()


def test_trading_engine_property_forwarders_return_lifecycle_state():
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
