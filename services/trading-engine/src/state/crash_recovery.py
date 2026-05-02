"""Crash recovery module for detecting and handling unclean shutdowns.

This module provides crash detection and recovery initiation for the trading engine.
It handles:
- Detection of previous crashes via missing shutdown flags and stale locks
- Process lock to prevent multiple engine instances
- Heartbeat to maintain lock ownership
- Account recovery detection from existing snapshots

Key Redis Keys:
- engine:shutdown:clean - Set on graceful shutdown, cleared at startup
- engine:lock:process - Exclusive lock with TTL, renewed by heartbeat

Architecture:
- CrashRecoveryManager is initialized before other engine components
- startup_sequence() runs first to detect crashes and acquire lock
- shutdown_sequence() runs last to set clean shutdown flag and release lock
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cold_storage_writer import ColdStorageWriter
    from .redis_state import RedisStateManager
    from .snapshot import StateSnapshot

# Type alias for lock lost callback
LockLostCallback = Callable[[], None]

logger = logging.getLogger(__name__)


@dataclass
class CrashIndicatorResult:
    """Result of crash indicator detection.

    Contains flags indicating what crash indicators were found
    and details for logging/debugging.

    Attributes:
        has_crash: True if any crash indicator was detected
        missing_shutdown_flag: True if clean shutdown flag was not found
        stale_heartbeat: True if process lock expired (heartbeat stopped)
        orphan_snapshots: List of account IDs with snapshots needing recovery
        details: Human-readable description of detected indicators
    """

    has_crash: bool
    missing_shutdown_flag: bool
    stale_heartbeat: bool
    orphan_snapshots: list[str]
    details: str


@dataclass
class RecoveryResult:
    """Result of startup sequence with recovery information.

    Returned by startup_sequence() to inform the engine about
    recovery state and which accounts need position reconciliation.

    Attributes:
        recovery_mode: True if engine is starting in recovery mode
        accounts_needing_recovery: List of account IDs with existing snapshots
        indicators: Detailed crash indicator results
    """

    recovery_mode: bool
    accounts_needing_recovery: list[str]
    indicators: CrashIndicatorResult


class CrashRecoveryManager:
    """Manages crash detection, recovery initiation, and process locking.

    This class handles the entire crash recovery lifecycle:
    1. On startup: Detect crash indicators, acquire process lock, start heartbeat
    2. During runtime: Heartbeat maintains lock ownership
    3. On shutdown: Stop heartbeat, set clean shutdown flag, release lock

    The process lock uses Redis SET NX EX for atomic acquisition with TTL.
    If the engine crashes, the lock expires and the next instance can acquire it.
    The heartbeat refreshes the lock TTL to prevent expiration during long operations.

    Example:
        manager = CrashRecoveryManager(redis_manager)
        result = await manager.startup_sequence()
        if result.recovery_mode:
            # Handle recovery for result.accounts_needing_recovery
            pass
        # ... trading runs ...
        await manager.shutdown_sequence()

    Attributes:
        SHUTDOWN_FLAG_KEY: Redis key for clean shutdown flag
        PROCESS_LOCK_KEY: Redis key for process lock
        HEARTBEAT_TTL_SECONDS: TTL for heartbeat detection (30s)
        LOCK_TTL_SECONDS: TTL for process lock (60s)
    """

    SHUTDOWN_FLAG_KEY = "engine:shutdown:clean"
    PROCESS_LOCK_KEY = "engine:lock:process"
    HEARTBEAT_TTL_SECONDS = 30
    LOCK_TTL_SECONDS = 60

    def __init__(
        self,
        redis_manager: RedisStateManager,
        on_lock_lost: LockLostCallback | None = None,
        cold_storage_writer: ColdStorageWriter | None = None,
    ) -> None:
        """Initialize CrashRecoveryManager.

        Args:
            redis_manager: Redis state manager for persistence operations
            on_lock_lost: Optional callback invoked when process lock is lost.
                         Use this to trigger emergency engine shutdown.
            cold_storage_writer: Optional TimescaleDB writer for fallback recovery.
                                When provided, snapshots are loaded from TimescaleDB
                                if Redis snapshot is unavailable.
        """
        self._redis = redis_manager
        self._cold_storage = cold_storage_writer
        self._recovery_mode = False
        self._heartbeat_running = False
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._on_lock_lost = on_lock_lost

    @property
    def recovery_mode(self) -> bool:
        """Check if engine is currently in recovery mode.

        Returns:
            True if recovery mode is active
        """
        return self._recovery_mode

    # =========================================================================
    # Clean Shutdown Flag Methods (Task 2)
    # =========================================================================

    async def set_clean_shutdown_flag(self) -> None:
        """Set flag indicating clean shutdown in progress.

        Called during graceful shutdown to indicate clean exit.
        Key pattern: engine:shutdown:clean
        Value: timestamp of shutdown
        TTL: None (cleared at startup)
        """
        await self._redis.client.set(
            self.SHUTDOWN_FLAG_KEY,
            datetime.now(timezone.utc).isoformat(),
        )
        logger.debug("Clean shutdown flag set")

    async def clear_clean_shutdown_flag(self) -> None:
        """Clear clean shutdown flag at startup.

        If flag exists at startup, previous shutdown was clean.
        Absence of flag after startup = crash recovery needed.
        """
        await self._redis.client.delete(self.SHUTDOWN_FLAG_KEY)
        logger.debug("Clean shutdown flag cleared")

    async def has_clean_shutdown_flag(self) -> bool:
        """Check if clean shutdown flag exists.

        Returns:
            True if previous shutdown was clean, False if crash/kill
        """
        result = await self._redis.client.exists(self.SHUTDOWN_FLAG_KEY)
        return result > 0

    # =========================================================================
    # Process Lock Methods (Task 3)
    # =========================================================================

    async def acquire_process_lock(self) -> bool:
        """Acquire exclusive process lock using Redis SET NX EX.

        Prevents multiple engine instances from running simultaneously.
        Lock auto-expires after LOCK_TTL_SECONDS if process dies.

        Returns:
            True if lock acquired, False if another instance running

        Key pattern: engine:lock:process
        Value: hostname:pid:timestamp
        TTL: 60 seconds (auto-renewed by heartbeat)
        """
        lock_value = (
            f"{socket.gethostname()}:{os.getpid()}:"
            f"{datetime.now(timezone.utc).isoformat()}"
        )
        result = await self._redis.client.set(
            self.PROCESS_LOCK_KEY,
            lock_value,
            nx=True,
            ex=self.LOCK_TTL_SECONDS,
        )
        if result:
            logger.info("Process lock acquired: %s", lock_value)
        else:
            existing = await self._redis.client.get(self.PROCESS_LOCK_KEY)
            logger.warning("Failed to acquire process lock. Existing: %s", existing)
        return result is True

    async def release_process_lock(self) -> None:
        """Release process lock on graceful shutdown."""
        await self._redis.client.delete(self.PROCESS_LOCK_KEY)
        logger.debug("Process lock released")

    async def refresh_process_lock(self) -> bool:
        """Refresh process lock TTL (call from heartbeat loop).

        Returns:
            True if lock refreshed, False if lost (should exit)
        """
        result = await self._redis.client.expire(
            self.PROCESS_LOCK_KEY,
            self.LOCK_TTL_SECONDS,
        )
        return result > 0

    # =========================================================================
    # Heartbeat Methods (Task 4)
    # =========================================================================

    async def start_heartbeat(self) -> None:
        """Start background heartbeat task that renews process lock.

        Heartbeat interval: HEARTBEAT_TTL_SECONDS / 2 (15 seconds)
        """
        if self._heartbeat_running:
            logger.warning("Heartbeat already running")
            return

        self._heartbeat_running = True
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name="crash-recovery-heartbeat",
        )
        logger.info("Heartbeat started with %.1f second interval", self.HEARTBEAT_TTL_SECONDS / 2)

    async def stop_heartbeat(self) -> None:
        """Stop heartbeat task."""
        if not self._heartbeat_running:
            return

        self._heartbeat_running = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        logger.info("Heartbeat stopped")

    async def _heartbeat_loop(self) -> None:
        """Background loop that refreshes process lock."""
        interval = self.HEARTBEAT_TTL_SECONDS / 2  # 15 seconds
        while self._heartbeat_running:
            try:
                if not await self.refresh_process_lock():
                    logger.critical("Lost process lock! Another instance may be running.")
                    # Trigger emergency shutdown via callback if registered
                    if self._on_lock_lost is not None:
                        self._on_lock_lost()
                    break
            except Exception as e:
                logger.error("Heartbeat failed: %s", e)
            await asyncio.sleep(interval)

    # =========================================================================
    # Crash Indicator Detection Methods (Task 1)
    # =========================================================================

    async def _check_stale_heartbeat(self) -> bool:
        """Check for stale/missing heartbeat indicating previous instance died.

        Stale heartbeat detection logic:
        - If PROCESS_LOCK_KEY exists but we can't acquire it = another instance running (not crash)
        - If PROCESS_LOCK_KEY doesn't exist (TTL expired) AND shutdown flag missing = crash
        - The lock key has 60s TTL, refreshed every 15s by heartbeat
        - If process crashes, heartbeat stops, lock expires after 60s max

        Returns:
            True if stale heartbeat detected (crash indicator), False otherwise
        """
        lock_exists = await self._redis.client.exists(self.PROCESS_LOCK_KEY) > 0
        shutdown_clean = await self.has_clean_shutdown_flag()

        # If lock doesn't exist AND no clean shutdown = previous instance crashed
        # The lock expired because heartbeat stopped (crash)
        if not lock_exists and not shutdown_clean:
            return True
        return False

    async def check_crash_indicators(self) -> CrashIndicatorResult:
        """Check for indicators of previous unclean shutdown.

        Checks three crash indicators:
        1. Missing clean shutdown flag - no graceful exit marker
        2. Stale heartbeat - lock expired without clean shutdown
        3. Orphan snapshots - accounts with state but no clean shutdown

        Returns:
            CrashIndicatorResult with detected indicators
        """
        missing_shutdown_flag = not await self.has_clean_shutdown_flag()
        stale_heartbeat = await self._check_stale_heartbeat()
        orphan_snapshots = await self.get_accounts_needing_recovery()

        # Determine if we have a crash condition
        has_crash = missing_shutdown_flag and (stale_heartbeat or len(orphan_snapshots) > 0)

        # Build details string
        details_parts = []
        if missing_shutdown_flag:
            details_parts.append("No clean shutdown flag found")
        if stale_heartbeat:
            details_parts.append("Stale heartbeat detected (lock expired)")
        if orphan_snapshots:
            details_parts.append(f"Found {len(orphan_snapshots)} accounts with orphan snapshots")

        details = "; ".join(details_parts) if details_parts else "No crash indicators"

        return CrashIndicatorResult(
            has_crash=has_crash,
            missing_shutdown_flag=missing_shutdown_flag,
            stale_heartbeat=stale_heartbeat,
            orphan_snapshots=orphan_snapshots,
            details=details,
        )

    async def initiate_recovery(self, indicators: CrashIndicatorResult) -> None:
        """Start recovery process for detected crash indicators.

        Sets recovery mode flag and logs recovery initiation.
        Actual recovery (position reconciliation) is handled by Story 5.3.

        Args:
            indicators: Crash indicators from check_crash_indicators()
        """
        self._recovery_mode = True
        logger.warning(
            "Recovery mode: Previous session did not shut down cleanly. %s",
            indicators.details,
        )

    async def clear_crash_indicators(self) -> None:
        """Clear all crash indicators after successful recovery.

        Called after recovery completes to reset state for normal operation.
        """
        self._recovery_mode = False
        logger.info("Crash indicators cleared, recovery complete")

    # =========================================================================
    # Recovery Account Detection Methods (Task 5)
    # =========================================================================

    async def get_accounts_needing_recovery(self) -> list[str]:
        """Get list of account IDs that have snapshots needing recovery.

        Scans for snapshot:*:latest keys and returns account IDs.
        These accounts had state at crash and need position reconciliation.

        Returns:
            List of account IDs with existing snapshots
        """
        account_ids = []
        async for key in self._redis.client.scan_iter("snapshot:*:latest"):
            # Extract account_id from key pattern snapshot:{id}:latest
            parts = key.split(":")
            if len(parts) == 3:
                account_ids.append(parts[1])
        return account_ids

    # Maximum age for snapshots to be considered valid for recovery (1 hour)
    SNAPSHOT_MAX_AGE_SECONDS = 3600
    # Maximum age for TimescaleDB snapshots (7 days - matches retention policy)
    COLD_STORAGE_MAX_AGE_SECONDS = 7 * 24 * 3600

    async def _load_account_snapshot(self, account_id: str) -> StateSnapshot | None:
        """Load snapshot from Redis, fallback to TimescaleDB if unavailable.

        Recovery priority:
        1. Redis snapshot (preferred - more recent, 5-second intervals)
        2. TimescaleDB snapshot (fallback - 60-second intervals, 7-day retention)

        Args:
            account_id: Account to load snapshot for

        Returns:
            StateSnapshot if found in either source, None if unavailable
        """
        # Try Redis first (preferred - more recent)
        redis_snapshot = await self._redis.get_snapshot(account_id)
        if redis_snapshot is not None:
            logger.debug("Loaded snapshot from Redis for %s", account_id)
            return redis_snapshot

        # Fallback to TimescaleDB
        if self._cold_storage is not None:
            logger.info(
                "Redis snapshot unavailable, using TimescaleDB fallback for %s",
                account_id,
            )
            db_snapshot = await self._cold_storage.get_latest_snapshot(account_id)
            if db_snapshot is not None:
                logger.info(
                    "Loaded snapshot from TimescaleDB for %s (timestamp: %s)",
                    account_id,
                    db_snapshot.timestamp.isoformat(),
                )
                return db_snapshot

        logger.warning("No snapshot available for %s (Redis or TimescaleDB)", account_id)
        return None

    async def validate_snapshot_for_recovery(
        self, account_id: str
    ) -> tuple[bool, StateSnapshot | None]:
        """Validate snapshot is usable for recovery.

        Checks:
        - Snapshot exists (Redis or TimescaleDB fallback)
        - Checksum is valid
        - Timestamp is recent enough (within 1 hour for Redis, 7 days for TimescaleDB)

        Args:
            account_id: Account to validate snapshot for

        Returns:
            (is_valid, snapshot) tuple
        """
        snapshot = await self._load_account_snapshot(account_id)
        if snapshot is None:
            return False, None

        if not snapshot.validate_checksum():
            logger.warning(
                "Snapshot checksum invalid for %s, will need fresh state",
                account_id,
            )
            return False, None

        # Check timestamp recency
        # Use longer threshold for TimescaleDB snapshots (checked by source)
        age_seconds = (datetime.now(timezone.utc) - snapshot.timestamp).total_seconds()
        max_age = self.SNAPSHOT_MAX_AGE_SECONDS

        # If from cold storage (no Redis snapshot available), allow 7-day-old snapshots
        redis_snapshot = await self._redis.get_snapshot(account_id)
        if redis_snapshot is None and self._cold_storage is not None:
            max_age = self.COLD_STORAGE_MAX_AGE_SECONDS

        if age_seconds > max_age:
            logger.warning(
                "Snapshot too old for %s (%.0f seconds, max %.0f), will need fresh state",
                account_id,
                age_seconds,
                max_age,
            )
            return False, None

        return True, snapshot

    # =========================================================================
    # Engine Integration Methods (Task 6)
    # =========================================================================

    async def startup_sequence(self) -> RecoveryResult:
        """Execute full startup sequence with crash detection.

        Sequence:
        1. Check for crash indicators
        2. If crash detected, enter recovery mode
        3. Acquire process lock (fail if another instance)
        4. Clear old shutdown flag
        5. Start heartbeat
        6. Return recovery accounts list

        Returns:
            RecoveryResult with status and accounts needing recovery

        Raises:
            RuntimeError: If another instance is already running
        """
        # Check for crash indicators (includes snapshot scan)
        indicators = await self.check_crash_indicators()

        if indicators.has_crash:
            await self.initiate_recovery(indicators)

        # Acquire process lock
        if not await self.acquire_process_lock():
            raise RuntimeError(
                "Another instance is already running. Cannot start engine."
            )

        # Clear shutdown flag (we're starting fresh)
        await self.clear_clean_shutdown_flag()

        # Start heartbeat
        await self.start_heartbeat()

        # Reuse accounts from indicators to avoid redundant SCAN
        # (orphan_snapshots already contains account IDs from check_crash_indicators)
        return RecoveryResult(
            recovery_mode=self._recovery_mode,
            accounts_needing_recovery=indicators.orphan_snapshots,
            indicators=indicators,
        )

    async def shutdown_sequence(self) -> None:
        """Execute graceful shutdown sequence.

        Sequence:
        1. Stop heartbeat
        2. Set clean shutdown flag
        3. Release process lock
        """
        await self.stop_heartbeat()
        await self.set_clean_shutdown_flag()
        await self.release_process_lock()
        logger.info("Graceful shutdown completed with clean flag set")
