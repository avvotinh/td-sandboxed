"""Collaborator bundles — pre-built dependency groups passed to orchestrators.

Story 10.2 introduces these dataclasses so :class:`RecoveryOrchestrator` and
:class:`LiveOrchestrator` can take pre-built collaborators (per the story
10.1 spec sketch), with construction logic centralised in
:func:`engine.build_lifecycle`. Optional fields reflect the conditional
build paths in the legacy engine: missing dependencies turn into ``None``
collaborators rather than constructor failures.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..orders.trade_db_writer import TradeDBWriter
from ..rules.violation_db_writer import ViolationDBWriter
from ..rules.violation_service import ViolationService
from ..snapshots.daily_snapshot_service import DailySnapshotService
from ..snapshots.snapshot_db_writer import SnapshotDBWriter
from ..state.cold_storage_service import ColdStorageService
from ..state.cold_storage_writer import ColdStorageWriter
from ..state.crash_recovery import CrashRecoveryManager
from ..state.daily_pnl_recalculator import DailyPnLRecalculator
from ..state.position_reconciler import PositionReconciler
from ..state.trading_resumer import TradingResumer


@dataclass(frozen=True)
class RecoveryCollaborators:
    """Pre-built collaborators wired into :class:`RecoveryOrchestrator`.

    Each field is ``None`` when the upstream config did not provide the
    dependencies needed to build that collaborator. The orchestrator
    handles the ``None`` case by skipping that recovery sub-step,
    matching the legacy engine.py conditional behaviour.
    """

    crash_recovery: CrashRecoveryManager | None = None
    position_reconciler: PositionReconciler | None = None
    pnl_recalculator: DailyPnLRecalculator | None = None
    trading_resumer: TradingResumer | None = None
    cold_storage_writer: ColdStorageWriter | None = None


@dataclass(frozen=True)
class LiveServiceBundle:
    """Pre-built auxiliary services managed by :class:`LiveOrchestrator`.

    Each entry is ``None`` when the upstream config lacked the deps to
    build the service. ``LiveOrchestrator.start`` and ``stop`` iterate
    over the present services in deterministic order.
    """

    cold_storage_service: ColdStorageService | None = None
    trade_db_writer: TradeDBWriter | None = None
    violation_db_writer: ViolationDBWriter | None = None
    violation_service: ViolationService | None = None
    daily_snapshot_writer: SnapshotDBWriter | None = None
    daily_snapshot_service: DailySnapshotService | None = None
