"""Trading engine package — split from the former `engine.py` god-object.

Story 10.1 carves the runtime into three focused components:
- :class:`RecoveryOrchestrator` — cold-start recovery flow.
- :class:`LiveOrchestrator` — live-trading auxiliary services (skeleton —
  Nautilus `LiveNode` wiring lands in story 10.5).
- :class:`EngineLifecycle` — top-level coordinator.

`TradingEngine` is preserved as a backwards-compatibility shim accepting
the same nine optional kwargs the legacy `__init__` took. Story 10.2
will replace this surface with the :class:`EngineConfig` DI container.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..accounts.account_manager import AccountManager
from ..accounts.pnl_registry import PnLTrackerRegistry
from ..accounts.risk_registry import RiskStateRegistry
from ..adapters.zmq_adapter import ZmqAdapter
from ..audit.audit_service import AuditService
from ..config.firm_registry import FirmRegistry
from ..state.daily_pnl_recalculator import RecalculationResult
from ..state.position_reconciler import ReconciliationResult
from ..state.redis_state import RedisStateManager
from ..state.snapshot_service import SnapshotService
from .config import EngineConfig
from .lifecycle import EngineLifecycle
from .live_orchestrator import LiveOrchestrator
from .recovery_orchestrator import RecoveryOrchestrator, RecoveryOutcome


def build_lifecycle(config: EngineConfig) -> EngineLifecycle:
    """Build an :class:`EngineLifecycle` from an :class:`EngineConfig`.

    Lives here as a temporary factory; story 10.2 promotes EngineConfig
    into a full DI container that owns construction.
    """
    recovery = RecoveryOrchestrator(
        redis_manager=config.redis_manager,
        zmq_adapter=config.zmq_adapter,
        db_session_factory=config.db_session_factory,
        risk_registry=config.risk_registry,
        pnl_registry=config.pnl_registry,
        account_manager=config.account_manager,
        firm_registry=config.firm_registry,
        audit_service=config.audit_service,
        database_url=config.database_url,
    )
    live = LiveOrchestrator(
        snapshot_service=config.snapshot_service,
        redis_manager=config.redis_manager,
        account_manager=config.account_manager,
        db_session_factory=config.db_session_factory,
        audit_service=config.audit_service,
        firm_registry=config.firm_registry,
        database_url=config.database_url,
    )
    return EngineLifecycle(
        recovery=recovery,
        live=live,
        audit_service=config.audit_service,
        redis_manager=config.redis_manager,
        account_manager=config.account_manager,
        snapshot_service=config.snapshot_service,
    )


class TradingEngine:
    """Backwards-compatibility shim wrapping :class:`EngineLifecycle`.

    Accepts the legacy 9 optional kwargs so existing CLI, tests, and
    fixtures continue to work unchanged. Internally builds a
    :class:`EngineConfig` and delegates to :class:`EngineLifecycle`.

    Properties (`is_running`, `recovery_result`, `reconciliation_results`,
    `pnl_recalculation_results`, `resume_result`, `shutdown_result`,
    `trade_db_writer`) mirror the legacy surface.
    """

    def __init__(
        self,
        redis_manager: RedisStateManager | None = None,
        zmq_adapter: ZmqAdapter | None = None,
        db_session_factory: async_sessionmaker[AsyncSession] | None = None,
        risk_registry: RiskStateRegistry | None = None,
        pnl_registry: PnLTrackerRegistry | None = None,
        account_manager: AccountManager | None = None,
        snapshot_service: SnapshotService | None = None,
        database_url: str | None = None,
        audit_service: AuditService | None = None,
        firm_registry: FirmRegistry | None = None,
    ) -> None:
        self._config = EngineConfig(
            redis_manager=redis_manager,
            zmq_adapter=zmq_adapter,
            db_session_factory=db_session_factory,
            risk_registry=risk_registry,
            pnl_registry=pnl_registry,
            account_manager=account_manager,
            snapshot_service=snapshot_service,
            database_url=database_url,
            audit_service=audit_service,
            firm_registry=firm_registry,
        )
        self._lifecycle = build_lifecycle(self._config)

    @property
    def is_running(self) -> bool:
        return self._lifecycle.is_running

    @property
    def recovery_result(self):  # type: ignore[no-untyped-def]
        return self._lifecycle.recovery_result

    @property
    def reconciliation_results(self) -> dict[str, ReconciliationResult] | None:
        return self._lifecycle.reconciliation_results

    @property
    def pnl_recalculation_results(self) -> dict[str, RecalculationResult] | None:
        return self._lifecycle.pnl_recalculation_results

    @property
    def resume_result(self):  # type: ignore[no-untyped-def]
        return self._lifecycle.resume_result

    @property
    def shutdown_result(self):  # type: ignore[no-untyped-def]
        return self._lifecycle.shutdown_result

    @property
    def trade_db_writer(self):  # type: ignore[no-untyped-def]
        return self._lifecycle.trade_db_writer

    async def run(self) -> None:
        await self._lifecycle.run()

    async def shutdown(self) -> None:
        await self._lifecycle.shutdown()


__all__ = [
    "EngineConfig",
    "EngineLifecycle",
    "LiveOrchestrator",
    "RecoveryOrchestrator",
    "RecoveryOutcome",
    "TradingEngine",
    "build_lifecycle",
]
