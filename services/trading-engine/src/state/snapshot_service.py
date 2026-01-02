"""SnapshotService - Periodic state snapshot service for crash recovery.

This service runs in the background, creating state snapshots for all
active accounts at configurable intervals (default: 5 seconds).

Architecture:
- Runs as an asyncio task in the trading engine
- Uses asyncio.gather for concurrent per-account snapshots
- Graceful start/stop with final snapshot on shutdown
- Error handling continues on per-account failures
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .snapshot import StateSnapshot

if TYPE_CHECKING:
    from ..accounts.account_manager import AccountManager
    from ..accounts.risk_registry import RiskStateRegistry
    from ..orders.position_tracker import PositionTracker
    from .redis_state import RedisStateManager

logger = logging.getLogger(__name__)


class SnapshotService:
    """Periodic state snapshot service for all active accounts.

    Creates snapshots every N seconds (configurable, default 5) containing:
    - Open positions and pending orders
    - Balance, equity, peak balance, daily starting balance
    - SHA256 checksum for integrity validation

    Snapshots are stored in Redis with 1-hour TTL for crash recovery.

    Example:
        service = SnapshotService(
            redis_manager=redis,
            account_manager=accounts,
            position_tracker=positions,
            risk_registry=registry,
        )
        await service.start()
        # ... trading runs ...
        await service.stop()  # Final snapshot before shutdown

    Attributes:
        SNAPSHOT_TTL_SECONDS: Redis key TTL for snapshots (1 hour)
    """

    SNAPSHOT_TTL_SECONDS = 3600  # 1 hour

    def __init__(
        self,
        redis_manager: RedisStateManager,
        account_manager: AccountManager,
        position_tracker: PositionTracker,
        risk_registry: RiskStateRegistry,
        interval_seconds: float = 5.0,
    ) -> None:
        """Initialize SnapshotService.

        Args:
            redis_manager: Redis state manager for snapshot persistence
            account_manager: Account manager for account list and status
            position_tracker: Position tracker for open positions
            risk_registry: Risk state registry for equity and balance metrics
            interval_seconds: Seconds between snapshot cycles (default: 5.0)
        """
        self._redis = redis_manager
        self._account_manager = account_manager
        self._position_tracker = position_tracker
        self._risk_registry = risk_registry
        self._interval = interval_seconds
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background snapshot loop.

        Creates an asyncio task that runs _snapshot_loop until stop() is called.
        Idempotent - calling start() when already running has no effect.
        """
        if self._running:
            logger.warning("SnapshotService already running")
            return

        self._running = True
        self._task = asyncio.create_task(
            self._snapshot_loop(),
            name="snapshot-service",
        )
        logger.info(
            "SnapshotService started with %.1f second interval",
            self._interval,
        )

    async def stop(self) -> None:
        """Stop the snapshot loop gracefully with a final snapshot.

        Performs one final snapshot cycle before stopping to ensure
        the most recent state is persisted for crash recovery.
        """
        if not self._running:
            logger.warning("SnapshotService not running")
            return

        self._running = False

        # Cancel the task
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Final snapshot before shutdown
        logger.info("Performing final snapshot before shutdown...")
        try:
            await self._snapshot_all_accounts()
        except Exception as e:
            logger.error("Final snapshot failed: %s", e)

        logger.info("SnapshotService stopped")

    async def _snapshot_loop(self) -> None:
        """Main snapshot loop - runs until stopped.

        Performs snapshot cycles at configured intervals.
        Continues running on errors (logs and retries next cycle).
        """
        while self._running:
            try:
                await self._snapshot_all_accounts()
            except Exception as e:
                logger.error("Snapshot cycle failed: %s", e)

            # Wait for next interval
            await asyncio.sleep(self._interval)

    async def _get_active_account_ids(self) -> list[str]:
        """Get IDs of accounts with 'active' status.

        Uses concurrent status fetches for better performance with many accounts.

        Returns:
            List of account IDs that are currently active
        """
        all_account_ids = self._account_manager.get_all_accounts()
        if not all_account_ids:
            return []

        # Fetch all statuses concurrently
        statuses = await asyncio.gather(
            *[
                self._account_manager.get_account_status(acc_id)
                for acc_id in all_account_ids
            ]
        )

        # Filter to active accounts
        return [
            acc_id
            for acc_id, status in zip(all_account_ids, statuses)
            if status == "active"
        ]

    async def _snapshot_all_accounts(self) -> None:
        """Snapshot all active accounts concurrently with performance logging.

        Uses asyncio.gather for concurrent snapshots.
        Logs timing and handles per-account errors without failing the cycle.
        """
        account_ids = await self._get_active_account_ids()
        if not account_ids:
            return

        start = time.perf_counter()
        results = await asyncio.gather(
            *[self._snapshot_account(acc_id) for acc_id in account_ids],
            return_exceptions=True,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Log results
        success_count = 0
        for acc_id, result in zip(account_ids, results):
            if isinstance(result, Exception):
                logger.error("Snapshot failed for %s: %s", acc_id, result)
            else:
                success_count += 1

        logger.debug(
            "Snapshot cycle completed in %.2fms for %d/%d accounts",
            elapsed_ms,
            success_count,
            len(account_ids),
        )

    async def _snapshot_account(self, account_id: str) -> None:
        """Create and save snapshot for a single account.

        Args:
            account_id: Account to snapshot

        Raises:
            Exception: If snapshot collection or save fails
        """
        snapshot = await self._collect_snapshot_data(account_id)
        await self._redis.save_snapshot(
            account_id,
            snapshot,
            ttl_seconds=self.SNAPSHOT_TTL_SECONDS,
        )
        logger.debug(
            "Saved snapshot for %s: equity=%s, positions=%d",
            account_id,
            snapshot.equity,
            len(snapshot.positions),
        )

    async def _collect_snapshot_data(self, account_id: str) -> StateSnapshot:
        """Collect all data needed for account snapshot.

        Sources:
        - positions: from PositionTracker (injected)
        - balance: from Redis account balance
        - equity, peak_equity, daily_starting_balance: from RiskStateRegistry (injected)

        Args:
            account_id: Account to collect data for

        Returns:
            StateSnapshot with computed checksum
        """
        # Get positions for this account
        positions = self._position_tracker.get_positions_dict(account_id)
        pending_orders: list[dict[str, Any]] = []  # Future: from order manager

        # Get balance from Redis
        balance = await self._redis.get_account_balance(account_id) or Decimal("0")

        # Get risk metrics from RiskStateRegistry
        risk_state = self._risk_registry.get_risk_state(account_id)
        if risk_state:
            equity = risk_state.current_equity
            peak_equity = risk_state.peak_equity  # Note: RiskState uses peak_equity
            daily_starting_balance = risk_state.daily_starting_balance
        else:
            # Fallback if no risk state available
            equity = balance
            peak_equity = balance
            daily_starting_balance = balance

        snapshot = StateSnapshot(
            account_id=account_id,
            timestamp=datetime.now(timezone.utc),
            positions=positions,
            pending_orders=pending_orders,
            account_balance=balance,
            equity=equity,
            peak_balance=peak_equity,  # Stored as peak_balance in snapshot
            daily_starting_balance=daily_starting_balance,
            checksum="",  # Will be computed below
        )
        snapshot.checksum = snapshot.compute_checksum()
        return snapshot
