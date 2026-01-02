"""State module - State management.

This module handles:
- Redis state snapshots
- Position reconciliation
- Crash recovery state
- Account status persistence

Exports:
- RedisStateManager: Async Redis state persistence
- StateSnapshot: Point-in-time account state for crash recovery
- SnapshotService: Periodic state snapshot service
- CrashRecoveryManager: Crash detection and recovery initiation
- CrashIndicatorResult: Result of crash indicator detection
- RecoveryResult: Result of startup sequence with recovery info
- PositionReconciler: Reconciles snapshot positions with MT5
- PositionDiscrepancy: Describes a mismatch between snapshot and MT5
- ReconciliationResult: Result of position reconciliation
- DiscrepancyType: Types of position discrepancies
"""

from .crash_recovery import CrashIndicatorResult, CrashRecoveryManager, RecoveryResult
from .position_reconciler import (
    DiscrepancyType,
    PositionDiscrepancy,
    PositionReconciler,
    ReconciliationResult,
)
from .redis_state import RedisStateManager
from .snapshot import StateSnapshot
from .snapshot_service import SnapshotService

__all__ = [
    "CrashIndicatorResult",
    "CrashRecoveryManager",
    "DiscrepancyType",
    "PositionDiscrepancy",
    "PositionReconciler",
    "ReconciliationResult",
    "RecoveryResult",
    "RedisStateManager",
    "SnapshotService",
    "StateSnapshot",
]
