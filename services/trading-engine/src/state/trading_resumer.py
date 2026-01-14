"""Trading resume module for crash recovery.

Handles resuming trading operations after successful crash recovery.
This is the final step in the recovery sequence:
1. Story 5.1: Snapshot loaded
2. Story 5.2: Crash detected, recovery initiated
3. Story 5.3: Positions reconciled with MT5
4. Story 5.4: Daily P&L recalculated
5. Story 5.5: Trading resumed (THIS MODULE)

Resume Logic:
- Accounts that were "active" before crash → Resume trading
- Accounts that were "paused" before crash → Remain paused
- Accounts that were "stopped" before crash → Remain stopped
- Accounts requiring manual intervention → Block (set to error)

CRITICAL: Only resume accounts that passed ALL recovery checks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..accounts.account_manager import AccountManager
    from .daily_pnl_recalculator import RecalculationResult
    from .position_reconciler import ReconciliationResult
    from .redis_state import RedisStateManager

logger = logging.getLogger(__name__)


@dataclass
class AccountResumeResult:
    """Result of attempting to resume a single account.

    Attributes:
        account_id: Account that was processed
        resumed: True if account was resumed to active trading
        previous_status: Status before crash (from snapshot)
        current_status: Status after resume attempt
        reason: Why account was/wasn't resumed
    """

    account_id: str
    resumed: bool
    previous_status: str
    current_status: str
    reason: str


@dataclass
class ResumeResult:
    """Result of trading resume operation after recovery.

    Attributes:
        success: True if resume completed without errors
        accounts_resumed: Number of accounts that resumed trading
        accounts_skipped: Number of accounts that remained paused/stopped
        accounts_blocked: Number of accounts blocked due to manual intervention
        recovery_duration: Time from crash detection to trading resume
        account_results: Per-account resume results
        notification_sent: True if notification was published
    """

    success: bool
    accounts_resumed: int
    accounts_skipped: int
    accounts_blocked: int
    recovery_duration: timedelta
    account_results: list[AccountResumeResult]
    notification_sent: bool


class TradingResumer:
    """Resumes trading operations after successful crash recovery.

    This class handles the final step of the recovery sequence:
    1. Determine which accounts should resume trading
    2. Restore account status based on pre-crash state
    3. Start signal processing for active accounts
    4. Send notification about recovery completion

    CRITICAL: Only resumes accounts that:
    - Were "active" before crash (from snapshot)
    - Passed position reconciliation successfully
    - Passed P&L recalculation successfully

    Accounts that were "paused" or "stopped" before crash remain
    in their pre-crash state - they are NOT auto-started.

    Example:
        resumer = TradingResumer(
            redis_manager=redis_manager,
            account_manager=account_manager,
        )
        result = await resumer.resume_trading_after_recovery(
            reconciliation_results=recon_results,
            pnl_results=pnl_results,
            recovery_start_time=start_time,
        )
    """

    def __init__(
        self,
        redis_manager: RedisStateManager,
        account_manager: AccountManager,
    ) -> None:
        """Initialize TradingResumer.

        Args:
            redis_manager: Redis state manager for snapshot access and notifications
            account_manager: Account manager for starting account tasks
        """
        self._redis = redis_manager
        self._account_manager = account_manager

    async def _get_pre_crash_status(self, account_id: str) -> str | None:
        """Get account status from before crash.

        IMPORTANT: This reads the current Redis status, which represents
        the pre-crash state because:
        1. Story 5.3 (reconciliation) does NOT modify account status
        2. Story 5.4 (P&L recalc) does NOT modify account status
        3. Account status is only modified by THIS story during resume

        If this assumption changes, consider:
        - Storing pre-crash status in CrashRecoveryManager at recovery start
        - Adding account_status field to StateSnapshot

        Args:
            account_id: Account to get pre-crash status for

        Returns:
            Pre-crash status string ("active", "paused", "stopped", "error")
            Returns "stopped" if status cannot be determined
        """
        status = await self._redis.get_account_status(account_id)
        if status is None:
            logger.warning(
                "No pre-crash status found for %s, defaulting to 'stopped'",
                account_id,
            )
            return "stopped"
        return status

    async def _should_resume_account(
        self,
        account_id: str,
        reconciliation_result: ReconciliationResult | None,
        pnl_result: RecalculationResult | None,
    ) -> tuple[bool, str]:
        """Determine if account should resume trading.

        Resume conditions (ALL must be true):
        1. Pre-crash status was "active"
        2. Position reconciliation succeeded (no manual intervention)
        3. P&L recalculation succeeded (or was skipped with valid reason)

        Args:
            account_id: Account to evaluate
            reconciliation_result: Result from position reconciliation (Story 5.3)
            pnl_result: Result from P&L recalculation (Story 5.4)

        Returns:
            (should_resume, reason) tuple
        """
        # Check pre-crash status
        pre_crash_status = await self._get_pre_crash_status(account_id)

        if pre_crash_status != "active":
            return False, f"Pre-crash status was '{pre_crash_status}', not 'active'"

        # Check reconciliation result
        if reconciliation_result is not None:
            if reconciliation_result.requires_manual_intervention:
                return False, "Requires manual intervention after reconciliation"
            if not reconciliation_result.success:
                return False, f"Reconciliation failed: {reconciliation_result.error_message}"

        # Check P&L recalculation result
        if pnl_result is not None:
            if not pnl_result.success:
                # P&L failure uses fallback - still safe to resume
                logger.warning(
                    "P&L recalculation failed for %s, using snapshot values",
                    account_id,
                )

        return True, "All recovery checks passed"

    async def _resume_account(self, account_id: str) -> AccountResumeResult:
        """Resume trading for a single account.

        Steps:
        1. Spawn account task via AccountManager (sets status to active)
        2. Log successful resume

        CRITICAL: Uses AccountManager._spawn_account_task() which:
        - Initializes rules for the account
        - Creates asyncio task for account loop
        - Sets up signal processing
        - Sets account status to "active" in Redis

        Args:
            account_id: Account to resume

        Returns:
            AccountResumeResult with details
        """
        pre_crash_status: str | None = None
        try:
            # Get pre-crash status for logging
            pre_crash_status = await self._get_pre_crash_status(account_id)

            # Spawn account task (this also sets status to active)
            await self._account_manager._spawn_account_task(account_id)

            logger.info(
                "Account %s resumed trading (was '%s' before crash)",
                account_id,
                pre_crash_status,
            )

            return AccountResumeResult(
                account_id=account_id,
                resumed=True,
                previous_status=pre_crash_status or "unknown",
                current_status="active",
                reason="Resumed successfully",
            )

        except Exception as e:
            logger.error("Failed to resume account %s: %s", account_id, e)
            return AccountResumeResult(
                account_id=account_id,
                resumed=False,
                previous_status=pre_crash_status or "unknown",
                current_status="error",
                reason=f"Resume failed: {e}",
            )

    async def _send_recovery_notification(
        self,
        accounts_resumed: int,
        accounts_skipped: int,
        accounts_blocked: int,
        recovery_duration: timedelta,
    ) -> bool:
        """Send notification about recovery completion via Redis pub/sub.

        Publishes to channel: alerts:system
        Message format: JSON with recovery details

        Args:
            accounts_resumed: Number of accounts that resumed trading
            accounts_skipped: Number of accounts that remained paused/stopped
            accounts_blocked: Number of accounts blocked due to errors
            recovery_duration: Time taken for recovery

        Returns:
            True if notification sent successfully
        """
        try:
            message = {
                "type": "recovery_complete",
                "accounts_resumed": accounts_resumed,
                "accounts_skipped": accounts_skipped,
                "accounts_blocked": accounts_blocked,
                "recovery_duration_seconds": recovery_duration.total_seconds(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": f"Recovery complete: {accounts_resumed} accounts resumed trading",
            }

            await self._redis.client.publish(
                "alerts:system",
                json.dumps(message),
            )

            logger.info("Recovery notification sent")
            return True

        except Exception as e:
            logger.warning("Failed to send recovery notification: %s", e)
            return False

    async def resume_trading_after_recovery(
        self,
        reconciliation_results: dict[str, ReconciliationResult],
        pnl_results: dict[str, RecalculationResult],
        recovery_start_time: datetime,
    ) -> ResumeResult:
        """Resume trading for all eligible accounts after recovery.

        Called as the final step of crash recovery sequence:
        1. Story 5.1: Snapshot loaded
        2. Story 5.2: Crash detected, recovery initiated
        3. Story 5.3: Positions reconciled with MT5
        4. Story 5.4: Daily P&L recalculated
        5. Story 5.5: Trading resumed (THIS METHOD)

        Args:
            reconciliation_results: Results from Story 5.3 position reconciliation
            pnl_results: Results from Story 5.4 P&L recalculation
            recovery_start_time: When crash detection started (for duration calc)

        Returns:
            ResumeResult with summary and per-account details
        """
        account_results: list[AccountResumeResult] = []
        accounts_resumed = 0
        accounts_skipped = 0
        accounts_blocked = 0

        # Process all accounts that went through recovery
        all_accounts = set(reconciliation_results.keys()) | set(pnl_results.keys())

        for account_id in all_accounts:
            recon_result = reconciliation_results.get(account_id)
            pnl_result = pnl_results.get(account_id)

            should_resume, reason = await self._should_resume_account(
                account_id, recon_result, pnl_result
            )

            if should_resume:
                result = await self._resume_account(account_id)
                if result.resumed:
                    accounts_resumed += 1
                else:
                    accounts_blocked += 1
                account_results.append(result)
            else:
                # Account not resumed - log why
                pre_status = await self._get_pre_crash_status(account_id)

                # Determine if account should be blocked (error state) or skipped
                # Block if: manual intervention required OR reconciliation failed
                should_block = (
                    (recon_result and recon_result.requires_manual_intervention)
                    or (recon_result and not recon_result.success)
                )

                if should_block:
                    accounts_blocked += 1
                    current_status = "error"
                    # CRITICAL: Set Redis status to error so account is blocked
                    await self._redis.save_account_status(account_id, "error")
                    logger.warning(
                        "Account %s blocked - set to error state: %s",
                        account_id,
                        reason,
                    )
                else:
                    accounts_skipped += 1
                    current_status = pre_status or "stopped"
                    # Don't modify Redis status - account keeps its pre-crash status

                account_results.append(
                    AccountResumeResult(
                        account_id=account_id,
                        resumed=False,
                        previous_status=pre_status or "unknown",
                        current_status=current_status,
                        reason=reason,
                    )
                )
                logger.info(
                    "Account %s not resumed: %s",
                    account_id,
                    reason,
                )

        # Calculate recovery duration
        recovery_duration = datetime.now(timezone.utc) - recovery_start_time

        # Send notification
        notification_sent = await self._send_recovery_notification(
            accounts_resumed, accounts_skipped, accounts_blocked, recovery_duration
        )

        # Log summary (use "complete" not "successful" since accounts may be blocked)
        log_level = logging.WARNING if accounts_blocked > 0 else logging.INFO
        logger.log(
            log_level,
            "Recovery complete. Trading resumed for %d accounts "
            "(skipped: %d, blocked: %d) in %.2f seconds",
            accounts_resumed,
            accounts_skipped,
            accounts_blocked,
            recovery_duration.total_seconds(),
        )

        return ResumeResult(
            success=True,
            accounts_resumed=accounts_resumed,
            accounts_skipped=accounts_skipped,
            accounts_blocked=accounts_blocked,
            recovery_duration=recovery_duration,
            account_results=account_results,
            notification_sent=notification_sent,
        )
