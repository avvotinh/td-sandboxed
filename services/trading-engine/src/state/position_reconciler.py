"""Position reconciliation module for crash recovery.

This module provides position reconciliation between Redis snapshots and MT5
actual positions during crash recovery. MT5 is ALWAYS the source of truth.

Reconciliation Flow:
1. Query MT5 for actual open positions via ZmqAdapter
2. Compare with snapshot positions from Redis
3. Update local state to match MT5
4. Log all discrepancies for audit trail

Key Features:
- Volume tolerance (0.001 lots) for matching
- Critical discrepancy detection (side mismatch, >3 orphans, >10% exposure diff)
- Automatic state updates to match MT5
- Alert publishing for critical issues requiring manual intervention

Integration Points:
- ZmqAdapter.query_positions() for MT5 queries
- RedisStateManager.publish_alert() for critical alerts
- SnapshotService for saving reconciled snapshots
- CrashRecoveryManager.startup_sequence() triggers reconciliation
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..adapters.zmq_adapter import ZmqAdapter
    from ..adapters.zmq_models import MT5Position
    from .crash_recovery import CrashRecoveryManager
    from .redis_state import RedisStateManager
    from .snapshot import StateSnapshot

logger = logging.getLogger(__name__)


class DiscrepancyType(Enum):
    """Types of position discrepancies between snapshot and MT5."""

    ORPHAN_POSITION = "orphan_position"  # In snapshot, not in MT5
    UNKNOWN_POSITION = "unknown_position"  # In MT5, not in snapshot
    VOLUME_MISMATCH = "volume_mismatch"  # Volume differs
    SIDE_MISMATCH = "side_mismatch"  # Side differs (BUY vs SELL)


@dataclass
class PositionDiscrepancy:
    """Describes a mismatch between snapshot and MT5 positions.

    Attributes:
        discrepancy_type: Type of discrepancy detected
        account_id: Account where discrepancy was found
        symbol: Trading symbol (e.g., "XAUUSD")
        snapshot_side: Side in snapshot ("BUY" or "SELL") or None
        mt5_side: Side in MT5 ("BUY" or "SELL") or None
        snapshot_volume: Volume in snapshot or None
        mt5_volume: Volume in MT5 or None
        snapshot_entry_price: Entry price in snapshot or None
        mt5_entry_price: Entry price in MT5 or None
        details: Human-readable description of discrepancy
    """

    discrepancy_type: DiscrepancyType
    account_id: str
    symbol: str
    snapshot_side: str | None
    mt5_side: str | None
    snapshot_volume: Decimal | None
    mt5_volume: Decimal | None
    snapshot_entry_price: Decimal | None
    mt5_entry_price: Decimal | None
    details: str


@dataclass
class ReconciliationResult:
    """Result of position reconciliation for an account.

    Attributes:
        account_id: Account that was reconciled
        success: True if reconciliation completed without critical issues
        positions_verified: Number of positions that matched
        discrepancies: List of all discrepancies found
        positions_added: Positions added from MT5 (unknown to snapshot)
        positions_removed: Positions removed from snapshot (orphans)
        positions_updated: Positions updated (volume/side corrections)
        requires_manual_intervention: True if critical issues require manual review
        error_message: Error description if reconciliation failed
    """

    account_id: str
    success: bool
    positions_verified: int
    discrepancies: list[PositionDiscrepancy]
    positions_added: int
    positions_removed: int
    positions_updated: int
    requires_manual_intervention: bool
    error_message: str | None


class PositionReconciler:
    """Reconciles snapshot positions with MT5 actual positions.

    MT5 is ALWAYS the source of truth. This reconciler:
    1. Queries MT5 for current open positions
    2. Compares with snapshot positions
    3. Updates local state to match MT5
    4. Logs all discrepancies

    CRITICAL: Never duplicate orders during recovery.

    Example:
        reconciler = PositionReconciler(zmq_adapter, redis_manager)
        result = await reconciler.reconcile_account(account_id, snapshot)
        if result.requires_manual_intervention:
            # Block account until manual review
            pass

    Attributes:
        VOLUME_TOLERANCE: Tolerance for volume matching (0.001 lots)
        CRITICAL_ORPHAN_THRESHOLD: Number of orphans to trigger critical (3)
        CRITICAL_EXPOSURE_DIFF_PERCENT: Exposure difference to trigger critical (10%)
    """

    # Volume tolerance for position matching (0.001 lots)
    VOLUME_TOLERANCE = Decimal("0.001")

    # Critical discrepancy thresholds
    CRITICAL_ORPHAN_THRESHOLD = 3
    CRITICAL_EXPOSURE_DIFF_PERCENT = Decimal("10")

    def __init__(
        self,
        zmq_adapter: ZmqAdapter,
        redis_manager: RedisStateManager,
    ) -> None:
        """Initialize PositionReconciler.

        Args:
            zmq_adapter: ZMQ adapter for MT5 position queries
            redis_manager: Redis state manager for alerts and snapshots
                         (uses publish_alert() for critical notifications)
        """
        self._zmq = zmq_adapter
        self._redis = redis_manager

    async def reconcile_account(
        self,
        account_id: str,
        snapshot: StateSnapshot,
    ) -> ReconciliationResult:
        """Reconcile snapshot positions with MT5 for a single account.

        Sequence:
        1. Query MT5 for actual positions (with timeout handling)
        2. Compare with snapshot positions
        3. Log discrepancies
        4. Update local state to match MT5

        MT5 is ALWAYS source of truth.

        Args:
            account_id: Account to reconcile
            snapshot: Loaded snapshot with positions to compare

        Returns:
            ReconciliationResult with verification status
            On timeout: returns result with success=False, error_message set
        """
        import asyncio

        try:
            mt5_positions = await self._zmq.query_positions(account_id, timeout=10.0)
        except asyncio.TimeoutError:
            logger.error("MT5 query timeout for %s - marking for retry", account_id)
            return ReconciliationResult(
                account_id=account_id,
                success=False,
                positions_verified=0,
                discrepancies=[],
                positions_added=0,
                positions_removed=0,
                positions_updated=0,
                requires_manual_intervention=True,  # Block until MT5 reachable
                error_message="MT5 query timeout - unable to verify positions",
            )
        except RuntimeError as e:
            logger.error("ZMQ not connected for %s: %s", account_id, e)
            return ReconciliationResult(
                account_id=account_id,
                success=False,
                positions_verified=0,
                discrepancies=[],
                positions_added=0,
                positions_removed=0,
                positions_updated=0,
                requires_manual_intervention=True,
                error_message=f"ZMQ connection error: {e}",
            )

        # Get snapshot positions
        snapshot_positions = snapshot.positions

        # Match positions and detect discrepancies
        matched_pairs, discrepancies = self._match_positions(
            account_id, snapshot_positions, mt5_positions
        )

        # Calculate metrics
        positions_verified = len(matched_pairs)
        positions_removed = sum(
            1
            for d in discrepancies
            if d.discrepancy_type == DiscrepancyType.ORPHAN_POSITION
        )
        positions_added = sum(
            1
            for d in discrepancies
            if d.discrepancy_type == DiscrepancyType.UNKNOWN_POSITION
        )
        positions_updated = sum(
            1
            for d in discrepancies
            if d.discrepancy_type == DiscrepancyType.VOLUME_MISMATCH
        )

        # Check for critical discrepancies
        requires_manual = self._has_critical_discrepancies(
            discrepancies, snapshot_positions, mt5_positions
        )

        if requires_manual:
            await self._publish_manual_intervention_alert(account_id, discrepancies)

        # Apply state updates (only for non-critical discrepancies)
        # For critical discrepancies, we don't modify state - manual review required
        reconciled_positions = list(snapshot_positions)  # Start with copy

        if not requires_manual:
            # Apply all state updates to reconcile with MT5 (source of truth)
            for d in discrepancies:
                if d.discrepancy_type == DiscrepancyType.ORPHAN_POSITION:
                    # Remove orphan position from local state
                    orphan_pos = {
                        "symbol": d.symbol,
                        "side": d.snapshot_side,
                        "volume": str(d.snapshot_volume),
                    }
                    reconciled_positions = self._remove_orphan_from_state(
                        reconciled_positions, orphan_pos
                    )
                    logger.warning(
                        "Removed orphan position from state: %s %s %s",
                        d.symbol,
                        d.snapshot_side,
                        d.snapshot_volume,
                    )

                elif d.discrepancy_type == DiscrepancyType.UNKNOWN_POSITION:
                    # Add unknown MT5 position to local state
                    # Find the MT5 position from the list
                    for mt5_pos in mt5_positions:
                        if (
                            mt5_pos.symbol == d.symbol
                            and mt5_pos.side == d.mt5_side
                            and mt5_pos.volume == d.mt5_volume
                        ):
                            reconciled_positions = self._add_unknown_to_state(
                                reconciled_positions, mt5_pos
                            )
                            logger.warning(
                                "Added unknown position to state: %s %s %s",
                                d.symbol,
                                d.mt5_side,
                                d.mt5_volume,
                            )
                            break

                elif d.discrepancy_type == DiscrepancyType.VOLUME_MISMATCH:
                    # Update volume to MT5 value (source of truth)
                    reconciled_positions = self._update_position_volume(
                        reconciled_positions,
                        d.symbol,
                        d.mt5_side,
                        d.mt5_volume,
                    )
                    logger.warning(
                        "Updated position volume: %s %s -> %s",
                        d.symbol,
                        d.snapshot_volume,
                        d.mt5_volume,
                    )

            # Save reconciled snapshot to Redis
            await self._save_reconciled_snapshot(
                account_id, snapshot, reconciled_positions
            )

        # Log reconciliation summary
        self._log_reconciliation_summary(
            account_id,
            positions_verified,
            discrepancies,
            requires_manual,
        )

        return ReconciliationResult(
            account_id=account_id,
            success=not requires_manual,
            positions_verified=positions_verified,
            discrepancies=discrepancies,
            positions_added=positions_added,
            positions_removed=positions_removed,
            positions_updated=positions_updated,
            requires_manual_intervention=requires_manual,
            error_message=None,
        )

    def _validate_position_dict(self, position: dict) -> bool:
        """Validate position dict has required fields for matching.

        Required fields: symbol, side, volume

        Args:
            position: Position dict from snapshot

        Returns:
            True if valid, False if missing required fields
        """
        required = {"symbol", "side", "volume"}
        return all(field in position for field in required)

    def _match_positions(
        self,
        account_id: str,
        snapshot_positions: list[dict],
        mt5_positions: list[MT5Position],
    ) -> tuple[list[tuple], list[PositionDiscrepancy]]:
        """Match snapshot positions to MT5 positions.

        IMPORTANT: Validates position dicts before matching.
        Invalid positions are logged and treated as orphans.

        Matching criteria:
        1. Same symbol (exact match)
        2. Same side (BUY/SELL)
        3. Volume within tolerance (0.001 lots)

        Args:
            account_id: Account being reconciled
            snapshot_positions: Positions from snapshot
            mt5_positions: Positions from MT5

        Returns:
            (matched_pairs, discrepancies)
            matched_pairs: List of (snapshot_pos, mt5_pos) tuples
            discrepancies: List of unmatched or mismatched positions
        """
        matched_pairs: list[tuple] = []
        discrepancies: list[PositionDiscrepancy] = []

        # Validate and filter snapshot positions
        valid_positions: list[dict] = []
        for pos in snapshot_positions:
            if self._validate_position_dict(pos):
                valid_positions.append(pos)
            else:
                logger.warning(
                    "Invalid position dict, missing required fields: %s", pos
                )
                # Treat invalid positions as discrepancies (need investigation)
                discrepancies.append(
                    PositionDiscrepancy(
                        discrepancy_type=DiscrepancyType.ORPHAN_POSITION,
                        account_id=account_id,
                        symbol=pos.get("symbol", "UNKNOWN"),
                        snapshot_side=pos.get("side"),
                        mt5_side=None,
                        snapshot_volume=Decimal(pos["volume"])
                        if "volume" in pos
                        else None,
                        mt5_volume=None,
                        snapshot_entry_price=Decimal(pos["entry_price"])
                        if "entry_price" in pos
                        else None,
                        mt5_entry_price=None,
                        details=f"Invalid snapshot position (missing required fields): {pos}",
                    )
                )

        # Track which MT5 positions have been matched
        mt5_unmatched = list(mt5_positions)

        # Try to match each snapshot position
        for snap_pos in valid_positions:
            symbol = snap_pos["symbol"]
            side = snap_pos["side"]
            volume = Decimal(snap_pos["volume"])

            # Find matching MT5 position
            match_found = False
            for mt5_pos in mt5_unmatched:
                if mt5_pos.symbol == symbol:
                    # Check side match
                    if mt5_pos.side != side:
                        # Side mismatch is critical - same symbol, different direction
                        discrepancies.append(
                            self._create_side_mismatch_discrepancy(
                                account_id, snap_pos, mt5_pos
                            )
                        )
                        mt5_unmatched.remove(mt5_pos)
                        match_found = True
                        break

                    # Check volume match with tolerance
                    volume_diff = abs(mt5_pos.volume - volume)
                    if volume_diff <= self.VOLUME_TOLERANCE:
                        # Perfect match
                        matched_pairs.append((snap_pos, mt5_pos))
                        mt5_unmatched.remove(mt5_pos)
                        match_found = True
                        break
                    else:
                        # Volume mismatch - use MT5 as source of truth
                        discrepancies.append(
                            self._create_volume_mismatch_discrepancy(
                                account_id, snap_pos, mt5_pos
                            )
                        )
                        mt5_unmatched.remove(mt5_pos)
                        match_found = True
                        break

            if not match_found:
                # Orphan position - in snapshot but not in MT5
                discrepancies.append(
                    self._create_orphan_discrepancy(account_id, snap_pos)
                )

        # Any remaining MT5 positions are unknown to snapshot
        for mt5_pos in mt5_unmatched:
            discrepancies.append(
                self._create_unknown_discrepancy(account_id, mt5_pos)
            )

        return matched_pairs, discrepancies

    def _create_orphan_discrepancy(
        self,
        account_id: str,
        position: dict,
    ) -> PositionDiscrepancy:
        """Create discrepancy for orphan position (snapshot only).

        Args:
            account_id: Account ID
            position: Snapshot position dict

        Returns:
            PositionDiscrepancy for orphan position
        """
        return PositionDiscrepancy(
            discrepancy_type=DiscrepancyType.ORPHAN_POSITION,
            account_id=account_id,
            symbol=position["symbol"],
            snapshot_side=position["side"],
            mt5_side=None,
            snapshot_volume=Decimal(position["volume"]),
            mt5_volume=None,
            snapshot_entry_price=Decimal(position["entry_price"])
            if "entry_price" in position
            else None,
            mt5_entry_price=None,
            details=(
                f"Orphan position removed: {position['symbol']} "
                f"{position['side']} {position['volume']} lots"
            ),
        )

    def _create_unknown_discrepancy(
        self,
        account_id: str,
        mt5_position: MT5Position,
    ) -> PositionDiscrepancy:
        """Create discrepancy for unknown position (MT5 only).

        Args:
            account_id: Account ID
            mt5_position: MT5 position not in snapshot

        Returns:
            PositionDiscrepancy for unknown position
        """
        return PositionDiscrepancy(
            discrepancy_type=DiscrepancyType.UNKNOWN_POSITION,
            account_id=account_id,
            symbol=mt5_position.symbol,
            snapshot_side=None,
            mt5_side=mt5_position.side,
            snapshot_volume=None,
            mt5_volume=mt5_position.volume,
            snapshot_entry_price=None,
            mt5_entry_price=mt5_position.entry_price,
            details=(
                f"Unknown position found: {mt5_position.symbol} "
                f"{mt5_position.side} {mt5_position.volume} lots"
            ),
        )

    def _create_volume_mismatch_discrepancy(
        self,
        account_id: str,
        snapshot_pos: dict,
        mt5_position: MT5Position,
    ) -> PositionDiscrepancy:
        """Create discrepancy for volume mismatch.

        Args:
            account_id: Account ID
            snapshot_pos: Snapshot position dict
            mt5_position: MT5 position with different volume

        Returns:
            PositionDiscrepancy for volume mismatch
        """
        snapshot_volume = Decimal(snapshot_pos["volume"])
        return PositionDiscrepancy(
            discrepancy_type=DiscrepancyType.VOLUME_MISMATCH,
            account_id=account_id,
            symbol=mt5_position.symbol,
            snapshot_side=snapshot_pos["side"],
            mt5_side=mt5_position.side,
            snapshot_volume=snapshot_volume,
            mt5_volume=mt5_position.volume,
            snapshot_entry_price=Decimal(snapshot_pos["entry_price"])
            if "entry_price" in snapshot_pos
            else None,
            mt5_entry_price=mt5_position.entry_price,
            details=(
                f"Volume mismatch: {mt5_position.symbol} "
                f"snapshot={snapshot_volume} MT5={mt5_position.volume} "
                f"(using MT5 value)"
            ),
        )

    def _create_side_mismatch_discrepancy(
        self,
        account_id: str,
        snapshot_pos: dict,
        mt5_position: MT5Position,
    ) -> PositionDiscrepancy:
        """Create discrepancy for side mismatch (CRITICAL).

        Args:
            account_id: Account ID
            snapshot_pos: Snapshot position dict
            mt5_position: MT5 position with different side

        Returns:
            PositionDiscrepancy for side mismatch
        """
        return PositionDiscrepancy(
            discrepancy_type=DiscrepancyType.SIDE_MISMATCH,
            account_id=account_id,
            symbol=mt5_position.symbol,
            snapshot_side=snapshot_pos["side"],
            mt5_side=mt5_position.side,
            snapshot_volume=Decimal(snapshot_pos["volume"]),
            mt5_volume=mt5_position.volume,
            snapshot_entry_price=Decimal(snapshot_pos["entry_price"])
            if "entry_price" in snapshot_pos
            else None,
            mt5_entry_price=mt5_position.entry_price,
            details=(
                f"CRITICAL: Side mismatch for {mt5_position.symbol}: "
                f"snapshot={snapshot_pos['side']} MT5={mt5_position.side}"
            ),
        )

    def _has_critical_discrepancies(
        self,
        discrepancies: list[PositionDiscrepancy],
        snapshot_positions: list[dict],
        mt5_positions: list[MT5Position],
    ) -> bool:
        """Determine if any discrepancy requires manual intervention.

        Critical conditions:
        - Side mismatch (BUY vs SELL for same symbol)
        - More than 3 orphan positions
        - Total exposure difference > 10%

        Args:
            discrepancies: List of detected discrepancies
            snapshot_positions: Original snapshot positions
            mt5_positions: MT5 positions

        Returns:
            True if manual intervention required
        """
        # Check for side mismatch
        for d in discrepancies:
            if d.discrepancy_type == DiscrepancyType.SIDE_MISMATCH:
                logger.warning(
                    "CRITICAL: Side mismatch detected for %s on %s",
                    d.symbol,
                    d.account_id,
                )
                return True

        # Check orphan count
        orphan_count = sum(
            1
            for d in discrepancies
            if d.discrepancy_type == DiscrepancyType.ORPHAN_POSITION
        )
        if orphan_count > self.CRITICAL_ORPHAN_THRESHOLD:
            logger.warning(
                "CRITICAL: %d orphan positions detected (threshold: %d)",
                orphan_count,
                self.CRITICAL_ORPHAN_THRESHOLD,
            )
            return True

        # Check exposure difference
        snapshot_exposure = self._calculate_total_exposure(snapshot_positions)
        mt5_exposure = self._calculate_mt5_exposure(mt5_positions)

        if snapshot_exposure > 0:
            exposure_diff_percent = (
                abs(mt5_exposure - snapshot_exposure) / snapshot_exposure * 100
            )
            if exposure_diff_percent > self.CRITICAL_EXPOSURE_DIFF_PERCENT:
                logger.warning(
                    "CRITICAL: Exposure difference %.2f%% exceeds threshold %.2f%%",
                    exposure_diff_percent,
                    self.CRITICAL_EXPOSURE_DIFF_PERCENT,
                )
                return True

        return False

    def _calculate_total_exposure(self, positions: list[dict]) -> Decimal:
        """Calculate total exposure from snapshot positions.

        Args:
            positions: List of position dicts

        Returns:
            Total volume across all positions
        """
        total = Decimal("0")
        for pos in positions:
            if "volume" in pos:
                try:
                    total += Decimal(pos["volume"])
                except (ValueError, TypeError):
                    pass
        return total

    def _calculate_mt5_exposure(self, positions: list[MT5Position]) -> Decimal:
        """Calculate total exposure from MT5 positions.

        Args:
            positions: List of MT5Position objects

        Returns:
            Total volume across all positions
        """
        return sum((p.volume for p in positions), Decimal("0"))

    async def _publish_manual_intervention_alert(
        self,
        account_id: str,
        discrepancies: list[PositionDiscrepancy],
    ) -> None:
        """Publish alert requiring manual intervention.

        Uses existing RedisStateManager.publish_alert() method.
        This publishes to Redis pub/sub channel for notification service.

        Alert format (per Task 4.2 spec):
        {
            "type": "recovery_alert",
            "severity": "critical",
            "account_id": "ftmo-gold-001",
            "message": "Manual intervention required",
            "details": "Side mismatch detected: XAUUSD",
            "action": "Review positions before resuming trading"
        }

        Note: RedisStateManager.publish_alert() wraps this in its standard
        format with timestamp. The message includes all spec fields.

        Args:
            account_id: Account requiring intervention
            discrepancies: List of critical discrepancies
        """
        # Format discrepancy details
        details = self._format_discrepancy_details(discrepancies)

        # Build structured message per Task 4.2 spec
        alert_content = {
            "severity": "critical",
            "details": details,
            "action": "Review positions before resuming trading",
            "discrepancy_count": len(discrepancies),
        }

        # Publish alert with structured message
        await self._redis.publish_alert(
            account_id=account_id,
            alert_type="recovery_alert",
            message=f"Manual intervention required | {json.dumps(alert_content)}",
        )

        logger.critical(
            "Published manual intervention alert for %s: %s",
            account_id,
            details,
        )

    def _format_discrepancy_details(
        self,
        discrepancies: list[PositionDiscrepancy],
    ) -> str:
        """Format discrepancies for alert message.

        Args:
            discrepancies: List of discrepancies

        Returns:
            Formatted string summarizing discrepancies
        """
        side_mismatches = sum(
            1
            for d in discrepancies
            if d.discrepancy_type == DiscrepancyType.SIDE_MISMATCH
        )
        orphans = sum(
            1
            for d in discrepancies
            if d.discrepancy_type == DiscrepancyType.ORPHAN_POSITION
        )
        unknowns = sum(
            1
            for d in discrepancies
            if d.discrepancy_type == DiscrepancyType.UNKNOWN_POSITION
        )
        volume_mismatches = sum(
            1
            for d in discrepancies
            if d.discrepancy_type == DiscrepancyType.VOLUME_MISMATCH
        )

        parts = []
        if side_mismatches:
            parts.append(f"{side_mismatches} side mismatch(es)")
        if orphans:
            parts.append(f"{orphans} orphan position(s)")
        if unknowns:
            parts.append(f"{unknowns} unknown position(s)")
        if volume_mismatches:
            parts.append(f"{volume_mismatches} volume mismatch(es)")

        return ", ".join(parts) if parts else "No specific details"

    def _log_reconciliation_summary(
        self,
        account_id: str,
        positions_verified: int,
        discrepancies: list[PositionDiscrepancy],
        requires_manual: bool,
    ) -> None:
        """Log reconciliation completion summary.

        Args:
            account_id: Account reconciled
            positions_verified: Number of positions verified
            discrepancies: List of discrepancies found
            requires_manual: Whether manual intervention is required
        """
        if requires_manual:
            logger.warning(
                "Reconciliation incomplete for %s: %d positions verified, "
                "%d discrepancies found, MANUAL INTERVENTION REQUIRED",
                account_id,
                positions_verified,
                len(discrepancies),
            )
        elif discrepancies:
            logger.warning(
                "Reconciliation complete with warnings for %s: "
                "%d positions verified, %d discrepancies auto-resolved",
                account_id,
                positions_verified,
                len(discrepancies),
            )
            for d in discrepancies:
                logger.warning("  - %s", d.details)
        else:
            logger.info(
                "Reconciliation complete: %s - %d positions verified",
                account_id,
                positions_verified,
            )

    # =========================================================================
    # Task 5: Local State Updates (AC: 2, 3, 7)
    # =========================================================================

    def _remove_orphan_from_state(
        self,
        positions: list[dict],
        orphan: dict,
    ) -> list[dict]:
        """Remove orphan position from positions list.

        This handles positions that exist in snapshot but not in MT5.
        The position was likely closed while engine was down.

        Args:
            positions: Current positions list (will not be modified)
            orphan: Position dict to remove

        Returns:
            New positions list with orphan removed
        """
        # Create new list without the orphan
        return [
            p for p in positions
            if not (
                p.get("symbol") == orphan.get("symbol")
                and p.get("side") == orphan.get("side")
                and p.get("volume") == orphan.get("volume")
            )
        ]

    def _add_unknown_to_state(
        self,
        positions: list[dict],
        mt5_position: MT5Position,
    ) -> list[dict]:
        """Add MT5 position to positions list.

        This handles positions that exist in MT5 but not in snapshot.
        The position was likely opened while engine was down.

        Args:
            positions: Current positions list (will not be modified)
            mt5_position: MT5 position to add

        Returns:
            New positions list with MT5 position added
        """
        new_position = {
            "symbol": mt5_position.symbol,
            "side": mt5_position.side,
            "volume": str(mt5_position.volume),
            "entry_price": str(mt5_position.entry_price),
            "entry_time": mt5_position.entry_time,
            "ticket": str(mt5_position.ticket),  # Track MT5 ticket for reference
        }
        return positions + [new_position]

    def _update_position_volume(
        self,
        positions: list[dict],
        symbol: str,
        side: str,
        new_volume: Decimal,
    ) -> list[dict]:
        """Update position volume to match MT5 (source of truth).

        This handles volume mismatches - partial close during crash
        could cause snapshot to have stale volume.

        Args:
            positions: Current positions list (will not be modified)
            symbol: Position symbol to update
            side: Position side to update
            new_volume: MT5 volume (source of truth)

        Returns:
            New positions list with volume updated
        """
        updated = []
        for p in positions:
            if p.get("symbol") == symbol and p.get("side") == side:
                # Update volume to MT5 value
                updated_pos = p.copy()
                updated_pos["volume"] = str(new_volume)
                updated.append(updated_pos)
            else:
                updated.append(p)
        return updated

    async def _save_reconciled_snapshot(
        self,
        account_id: str,
        snapshot: StateSnapshot,
        reconciled_positions: list[dict],
    ) -> None:
        """Save updated snapshot after reconciliation.

        Creates new snapshot with:
        - Positions list from MT5 (source of truth)
        - Updated timestamp
        - New checksum

        Replaces old snapshot in Redis.

        Args:
            account_id: Account being reconciled
            snapshot: Original snapshot (for other fields)
            reconciled_positions: Updated positions list from MT5
        """
        from .snapshot import StateSnapshot as SnapshotClass

        # Create new snapshot with reconciled positions
        new_snapshot = SnapshotClass(
            account_id=account_id,
            timestamp=datetime.now(timezone.utc),
            positions=reconciled_positions,
            pending_orders=snapshot.pending_orders,
            account_balance=snapshot.account_balance,
            equity=snapshot.equity,
            peak_balance=snapshot.peak_balance,
            daily_starting_balance=snapshot.daily_starting_balance,
            checksum="",
        )
        new_snapshot.checksum = new_snapshot.compute_checksum()

        # Save to Redis
        await self._redis.save_snapshot(account_id, new_snapshot)

        logger.info(
            "Saved reconciled snapshot for %s with %d positions",
            account_id,
            len(reconciled_positions),
        )


async def run_position_reconciliation(
    reconciler: PositionReconciler,
    crash_recovery: "CrashRecoveryManager",
    accounts: list[str],
) -> dict[str, ReconciliationResult]:
    """Run reconciliation for all accounts needing recovery.

    Helper function for Engine integration.

    Args:
        reconciler: PositionReconciler instance
        crash_recovery: CrashRecoveryManager for snapshot access
        accounts: List of account IDs from recovery result

    Returns:
        Dict mapping account_id to ReconciliationResult
    """
    results: dict[str, ReconciliationResult] = {}

    for account_id in accounts:
        # Load and validate snapshot
        valid, snapshot = await crash_recovery.validate_snapshot_for_recovery(
            account_id
        )

        if not valid or snapshot is None:
            # No valid snapshot - start fresh (no positions to reconcile)
            logger.info(
                "No valid snapshot for %s - starting fresh (no reconciliation needed)",
                account_id,
            )
            results[account_id] = ReconciliationResult(
                account_id=account_id,
                success=True,
                positions_verified=0,
                discrepancies=[],
                positions_added=0,
                positions_removed=0,
                positions_updated=0,
                requires_manual_intervention=False,
                error_message=None,
            )
            continue

        # Reconcile with MT5
        result = await reconciler.reconcile_account(account_id, snapshot)
        results[account_id] = result

        if result.requires_manual_intervention:
            logger.warning(
                "Account %s requires manual intervention: %s",
                account_id,
                result.error_message or "Critical discrepancies found",
            )

    return results
