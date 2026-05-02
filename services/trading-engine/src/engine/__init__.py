"""Trading engine package.

Story 10.1 split the former `engine.py` god-object into three focused
components. Story 10.2 promotes :class:`EngineConfig` into the single
source of truth for engine construction and consolidates all wiring into
:func:`build_lifecycle`:

- :class:`RecoveryOrchestrator` — cold-start recovery flow.
- :class:`LiveOrchestrator` — live-trading auxiliary services (skeleton —
  Nautilus ``LiveNode`` wiring lands in story 10.5).
- :class:`EngineLifecycle` — top-level coordinator.
- :class:`EngineConfig` — DI container with feature-flag derivation.

:class:`TradingEngine` is preserved as a thin wrapper around an
:class:`EngineLifecycle` for callers that still want the old
``engine.run()`` / ``engine.shutdown()`` shape (e.g. ``tests/conftest.py``).
"""
from __future__ import annotations

from ..orders.trade_db_writer import TradeDBWriter
from ..rules.violation_db_writer import ViolationDBWriter
from ..rules.violation_service import ViolationService
from ..snapshots.daily_snapshot_service import DailySnapshotService
from ..snapshots.snapshot_db_writer import SnapshotDBWriter
from ..state.cold_storage_service import ColdStorageService
from ..state.cold_storage_writer import ColdStorageWriter
from ..state.crash_recovery import CrashRecoveryManager, RecoveryResult
from ..state.daily_pnl_recalculator import DailyPnLRecalculator, RecalculationResult
from ..state.emergency_stop_handler import EmergencyStopHandler
from ..state.graceful_shutdown import GracefulShutdown, ShutdownResult
from ..state.position_reconciler import PositionReconciler, ReconciliationResult
from ..state.trading_resumer import ResumeResult, TradingResumer
from .collaborators import LiveServiceBundle, RecoveryCollaborators
from .config import EngineConfig, EngineConfigError, EngineFeatureFlags
from .lifecycle import EngineLifecycle
from .live_orchestrator import LiveOrchestrator
from .lock_lost import LockLostMediator
from .recovery_orchestrator import RecoveryOrchestrator, RecoveryOutcome


def _build_recovery_collaborators(
    config: EngineConfig,
    flags: EngineFeatureFlags,
    lock_lost_mediator: LockLostMediator,
) -> RecoveryCollaborators:
    if not flags.crash_recovery:
        return RecoveryCollaborators()

    cold_storage_writer = (
        ColdStorageWriter(config.database_url)
        if flags.cold_storage and config.database_url is not None
        else None
    )

    crash_recovery = CrashRecoveryManager(
        redis_manager=config.redis_manager,
        on_lock_lost=lock_lost_mediator,
        cold_storage_writer=cold_storage_writer,
    )

    position_reconciler = (
        PositionReconciler(
            zmq_adapter=config.zmq_adapter,
            redis_manager=config.redis_manager,
        )
        if flags.position_reconciliation
        else None
    )

    pnl_recalculator = (
        DailyPnLRecalculator(
            db_session_factory=config.db_session_factory,
            redis_manager=config.redis_manager,
            risk_registry=config.risk_registry,
            pnl_registry=config.pnl_registry,
            firm_registry=config.firm_registry,
            account_manager=config.account_manager,
        )
        if flags.pnl_recalculation
        else None
    )

    trading_resumer = (
        TradingResumer(
            redis_manager=config.redis_manager,
            account_manager=config.account_manager,
        )
        if flags.trading_resume
        else None
    )

    return RecoveryCollaborators(
        crash_recovery=crash_recovery,
        position_reconciler=position_reconciler,
        pnl_recalculator=pnl_recalculator,
        trading_resumer=trading_resumer,
        cold_storage_writer=cold_storage_writer,
    )


def _build_live_services(
    config: EngineConfig,
    flags: EngineFeatureFlags,
    cold_storage_writer: ColdStorageWriter | None,
) -> LiveServiceBundle:
    cold_storage_service: ColdStorageService | None = None
    if (
        flags.cold_storage
        and cold_storage_writer is not None
        and config.snapshot_service is not None
    ):
        cold_storage_service = ColdStorageService(
            cold_storage_writer=cold_storage_writer,
            snapshot_service=config.snapshot_service,
        )

    trade_db_writer: TradeDBWriter | None = None
    if flags.trade_audit and config.database_url is not None:
        trade_db_writer = TradeDBWriter(config.database_url)

    violation_db_writer: ViolationDBWriter | None = None
    violation_service: ViolationService | None = None
    if flags.violation_tracking and config.database_url is not None:
        violation_db_writer = ViolationDBWriter(config.database_url)
        violation_service = ViolationService(violation_db_writer)

    daily_snapshot_writer: SnapshotDBWriter | None = None
    daily_snapshot_service: DailySnapshotService | None = None
    if flags.daily_snapshots and config.database_url is not None:
        daily_snapshot_writer = SnapshotDBWriter(config.database_url)
        daily_snapshot_service = DailySnapshotService(
            db_writer=daily_snapshot_writer,
            redis_state=config.redis_manager,
            account_manager=config.account_manager,
            db_session_factory=config.db_session_factory,
            audit_service=config.audit_service,
            firm_registry=config.firm_registry,
        )

    return LiveServiceBundle(
        cold_storage_service=cold_storage_service,
        trade_db_writer=trade_db_writer,
        violation_db_writer=violation_db_writer,
        violation_service=violation_service,
        daily_snapshot_writer=daily_snapshot_writer,
        daily_snapshot_service=daily_snapshot_service,
    )


def _build_graceful_shutdown(
    config: EngineConfig,
    flags: EngineFeatureFlags,
) -> GracefulShutdown | None:
    if not flags.graceful_shutdown:
        return None
    return GracefulShutdown(
        redis_manager=config.redis_manager,
        account_manager=config.account_manager,
        snapshot_service=config.snapshot_service,
        zmq_adapter=config.zmq_adapter,
        audit_service=config.audit_service,
    )


def build_lifecycle(config: EngineConfig) -> EngineLifecycle:
    """Build a fully wired :class:`EngineLifecycle` from an :class:`EngineConfig`.

    The single source of truth for engine construction. Recovery
    artifacts (``CrashRecoveryManager``, ``ColdStorageService``) flow
    into :class:`GracefulShutdown` via late-binding inside
    :meth:`EngineLifecycle.run`.
    """
    flags = config.feature_flags()
    lock_lost_mediator = LockLostMediator()

    recovery_collaborators = _build_recovery_collaborators(
        config, flags, lock_lost_mediator
    )
    live_services = _build_live_services(
        config, flags, recovery_collaborators.cold_storage_writer
    )
    graceful_shutdown = _build_graceful_shutdown(config, flags)

    recovery = RecoveryOrchestrator(
        collaborators=recovery_collaborators,
        risk_registry=config.risk_registry,
        audit_service=config.audit_service,
    )
    live = LiveOrchestrator(
        services=live_services,
        account_manager=config.account_manager,
        audit_service=config.audit_service,
        rule_assignment_service=config.rule_assignment_service,
        risk_registry=config.risk_registry,
        pnl_registry=config.pnl_registry,
        redis_manager=config.redis_manager,
        validated_adapter=config.validated_adapter,
    )

    emergency_stop_handler: EmergencyStopHandler | None = None
    if flags.emergency_stop:
        emergency_stop_handler = EmergencyStopHandler(
            redis_manager=config.redis_manager,
            account_manager=config.account_manager,
            zmq_adapter=config.zmq_adapter,
            audit_service=config.audit_service,
        )

    return EngineLifecycle(
        recovery=recovery,
        live=live,
        graceful_shutdown=graceful_shutdown,
        audit_service=config.audit_service,
        lock_lost_mediator=lock_lost_mediator,
        exposure_reservation=config.exposure_reservation,
        emergency_stop_handler=emergency_stop_handler,
    )


class TradingEngine:
    """Backwards-compatibility wrapper around :class:`EngineLifecycle`.

    Accepts an :class:`EngineConfig` (or none for tests) and delegates
    every call to the wrapped lifecycle. The legacy 9-kwarg constructor
    surface was retired in 10.2 — callers that need partial dependencies
    should construct an :class:`EngineConfig` explicitly.

    Properties (``is_running``, ``recovery_result``,
    ``reconciliation_results``, ``pnl_recalculation_results``,
    ``resume_result``, ``shutdown_result``, ``trade_db_writer``) mirror
    the legacy surface for tests that haven't migrated yet.
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self._config = config if config is not None else EngineConfig.empty()
        self._lifecycle = build_lifecycle(self._config)

    @property
    def is_running(self) -> bool:
        return self._lifecycle.is_running

    @property
    def recovery_result(self) -> RecoveryResult | None:
        return self._lifecycle.recovery_result

    @property
    def reconciliation_results(self) -> dict[str, ReconciliationResult] | None:
        return self._lifecycle.reconciliation_results

    @property
    def pnl_recalculation_results(self) -> dict[str, RecalculationResult] | None:
        return self._lifecycle.pnl_recalculation_results

    @property
    def resume_result(self) -> ResumeResult | None:
        return self._lifecycle.resume_result

    @property
    def shutdown_result(self) -> ShutdownResult | None:
        return self._lifecycle.shutdown_result

    @property
    def trade_db_writer(self) -> TradeDBWriter | None:
        return self._lifecycle.trade_db_writer

    async def run(self) -> None:
        await self._lifecycle.run()

    async def shutdown(self) -> None:
        await self._lifecycle.shutdown()


__all__ = [
    "EngineConfig",
    "EngineConfigError",
    "EngineFeatureFlags",
    "EngineLifecycle",
    "LiveOrchestrator",
    "LiveServiceBundle",
    "LockLostMediator",
    "RecoveryCollaborators",
    "RecoveryOrchestrator",
    "RecoveryOutcome",
    "TradingEngine",
    "build_lifecycle",
]
