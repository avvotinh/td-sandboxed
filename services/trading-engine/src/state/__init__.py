"""State module - State management.

This module handles:
- Redis state snapshots
- Position reconciliation
- Crash recovery state
- Account status persistence
- Daily P&L recalculation after recovery
- Trading resume after recovery

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
- DailyPnLRecalculator: Recalculates daily P&L from trade history
- RecalculatedPnL: Result of P&L recalculation
- RecalculationResult: Full result with success status
- TradingResumer: Resumes trading after crash recovery
- AccountResumeResult: Result of resuming a single account
- ResumeResult: Full result of trading resume operation
"""

from .crash_recovery import CrashIndicatorResult, CrashRecoveryManager, RecoveryResult
from .daily_pnl_recalculator import (
    DailyPnLRecalculator,
    RecalculatedPnL,
    RecalculationResult,
)
from .position_reconciler import (
    DiscrepancyType,
    PositionDiscrepancy,
    PositionReconciler,
    ReconciliationResult,
)
from .redis_state import RedisStateManager
from .snapshot import StateSnapshot
from .snapshot_service import SnapshotService
from .trading_resumer import AccountResumeResult, ResumeResult, TradingResumer

__all__ = [
    "AccountResumeResult",
    "CrashIndicatorResult",
    "CrashRecoveryManager",
    "DailyPnLRecalculator",
    "DiscrepancyType",
    "PositionDiscrepancy",
    "PositionReconciler",
    "RecalculatedPnL",
    "RecalculationResult",
    "ReconciliationResult",
    "RecoveryResult",
    "RedisStateManager",
    "ResumeResult",
    "SnapshotService",
    "StateSnapshot",
    "TradingResumer",
]
