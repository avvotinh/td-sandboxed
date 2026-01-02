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
"""

from .crash_recovery import CrashIndicatorResult, CrashRecoveryManager, RecoveryResult
from .redis_state import RedisStateManager
from .snapshot import StateSnapshot
from .snapshot_service import SnapshotService

__all__ = [
    "CrashIndicatorResult",
    "CrashRecoveryManager",
    "RecoveryResult",
    "RedisStateManager",
    "SnapshotService",
    "StateSnapshot",
]
