"""EngineConfig — DI container for the trading engine.

Story 10.2 promotes this dataclass into the **single source of truth** for
engine construction:

- :func:`engine.build_lifecycle` consumes an :class:`EngineConfig` and emits
  a fully wired :class:`EngineLifecycle`.
- :class:`engine.TradingEngine` accepts an :class:`EngineConfig` directly
  (with a no-arg form for tests using :meth:`EngineConfig.empty`).
- :meth:`feature_flags` exposes which subsystems are enabled given the
  dependencies present, so the builder can short-circuit instead of
  reaching into individual fields.

Fields stay optional because the engine still supports partial configs
(unit tests with no deps; CLI smoke checks with only Redis). The validator
guards against mutually inconsistent partial configs — e.g. ``database_url``
present but ``db_session_factory`` missing — that would silently disable
features at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..accounts.account_manager import AccountManager
from ..accounts.pnl_registry import PnLTrackerRegistry
from ..accounts.risk_registry import RiskStateRegistry
from ..adapters.zmq_adapter import ZmqAdapter
from ..audit.audit_service import AuditService
from ..config.firm_registry import FirmRegistry
from ..execution.exposure_reservation import ExposureReservation
from ..rules.assignment_service import RuleAssignmentService
from ..state.redis_state import RedisStateManager
from ..state.snapshot_service import SnapshotService


class EngineConfigError(ValueError):
    """Raised when an :class:`EngineConfig` describes an inconsistent setup."""


@dataclass(frozen=True)
class EngineFeatureFlags:
    """Derived view of which engine subsystems an :class:`EngineConfig` enables.

    The builder reads these flags rather than hand-checking individual
    dependencies, which keeps the conditional-construction logic in one
    place and makes the partial-config behaviour testable.
    """

    crash_recovery: bool
    cold_storage: bool
    position_reconciliation: bool
    pnl_recalculation: bool
    trading_resume: bool
    trade_audit: bool
    violation_tracking: bool
    daily_snapshots: bool
    graceful_shutdown: bool
    atomic_exposure_gate: bool
    live_sessions: bool
    emergency_stop: bool


@dataclass(frozen=True)
class EngineConfig:
    """All dependencies the trading engine may consume.

    Use :meth:`EngineConfig.empty` for tests that exercise the engine with
    no deps wired. Production callers populate every field; the builder
    skips features whose dependencies are absent.
    """

    redis_manager: RedisStateManager | None = None
    zmq_adapter: ZmqAdapter | None = None
    db_session_factory: async_sessionmaker[AsyncSession] | None = None
    risk_registry: RiskStateRegistry | None = None
    pnl_registry: PnLTrackerRegistry | None = None
    account_manager: AccountManager | None = None
    snapshot_service: SnapshotService | None = None
    database_url: str | None = None
    audit_service: AuditService | None = None
    firm_registry: FirmRegistry | None = None
    exposure_reservation: ExposureReservation | None = None
    rule_assignment_service: RuleAssignmentService | None = None

    def __post_init__(self) -> None:
        if self.database_url is not None and self.db_session_factory is None:
            raise EngineConfigError(
                "database_url is set but db_session_factory is missing — daily "
                "snapshots and audit features need both. Provide a session "
                "factory or unset database_url."
            )

    @classmethod
    def empty(cls) -> EngineConfig:
        """Return an :class:`EngineConfig` with every dep unset.

        Intended for unit tests that exercise the engine without external
        infrastructure. Production code should never use this.
        """
        return cls()

    def feature_flags(self) -> EngineFeatureFlags:
        """Compute which engine subsystems this config enables."""
        crash_recovery = self.redis_manager is not None
        cold_storage = crash_recovery and self.database_url is not None
        position_reconciliation = crash_recovery and self.zmq_adapter is not None
        pnl_recalculation = (
            crash_recovery
            and self.db_session_factory is not None
            and self.risk_registry is not None
            and self.pnl_registry is not None
        )
        trading_resume = crash_recovery and self.account_manager is not None
        trade_audit = self.database_url is not None
        violation_tracking = self.database_url is not None
        daily_snapshots = (
            self.database_url is not None
            and self.redis_manager is not None
            and self.account_manager is not None
            and self.db_session_factory is not None
        )
        graceful_shutdown = (
            self.redis_manager is not None and self.account_manager is not None
        )
        atomic_exposure_gate = self.exposure_reservation is not None
        live_sessions = (
            self.account_manager is not None
            and self.rule_assignment_service is not None
            and self.risk_registry is not None
        )
        emergency_stop = (
            self.redis_manager is not None
            and self.account_manager is not None
            and self.zmq_adapter is not None
            and self.audit_service is not None
        )
        return EngineFeatureFlags(
            crash_recovery=crash_recovery,
            cold_storage=cold_storage,
            position_reconciliation=position_reconciliation,
            pnl_recalculation=pnl_recalculation,
            trading_resume=trading_resume,
            trade_audit=trade_audit,
            violation_tracking=violation_tracking,
            daily_snapshots=daily_snapshots,
            graceful_shutdown=graceful_shutdown,
            atomic_exposure_gate=atomic_exposure_gate,
            live_sessions=live_sessions,
            emergency_stop=emergency_stop,
        )
