"""Live session state.

This module handles:
- Redis state snapshots
- TimescaleDB cold storage backup (fallback for Redis)
- Position reconciliation
- Crash recovery state
- Per-account risk state and limit tracking

Exports:
- RedisStateManager: Async Redis state persistence
- StateSnapshot: Point-in-time account state for crash recovery
- StateSnapshotModel: SQLAlchemy model for TimescaleDB persistence
- ColdStorageWriter: TimescaleDB snapshot writer
- CrashRecoveryManager: Crash detection and recovery initiation
- CrashIndicatorResult: Result of crash indicator detection
- RecoveryResult: Result of startup sequence with recovery info
- PositionReconciler: Reconciles snapshot positions with MT5
- PositionDiscrepancy: Describes a mismatch between snapshot and MT5
- ReconciliationResult: Result of position reconciliation
- DiscrepancyType: Types of position discrepancies
- RiskState: Per-account risk counters
- AccountRiskManager: Applies risk limits to a RiskState
- RiskStateRegistry: Per-account RiskState lookup

Removed with ``src/accounts/`` (P3.2): the lifecycle services that took an
``AccountManager`` and fanned out across every account — SnapshotService,
ColdStorageService, DailyPnLRecalculator, TradingResumer, GracefulShutdown, EmergencyStopHandler.
They were multi-account orchestration by construction; P5.1 replaces them with
a single-account ``src/live/session.py``.
"""

from .cold_storage_writer import ColdStorageWriter
from .crash_recovery import CrashIndicatorResult, CrashRecoveryManager, RecoveryResult
from .position_reconciler import (
    DiscrepancyType,
    PositionDiscrepancy,
    PositionReconciler,
    ReconciliationResult,
)
from .redis_state import RedisStateManager
from .risk_manager import AccountRiskManager
from .risk_registry import RiskStateRegistry
from .risk_state import RiskState
from .snapshot import StateSnapshot
from .snapshot_db_model import StateSnapshotModel

__all__ = [
    "AccountRiskManager",
    "ColdStorageWriter",
    "CrashIndicatorResult",
    "CrashRecoveryManager",
    "DiscrepancyType",
    "PositionDiscrepancy",
    "PositionReconciler",
    "ReconciliationResult",
    "RecoveryResult",
    "RedisStateManager",
    "RiskState",
    "RiskStateRegistry",
    "StateSnapshot",
    "StateSnapshotModel",
]
