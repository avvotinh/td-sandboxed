"""Risk isolation service - Integration point for risk checks.

Connects RiskStateRegistry with AccountManager to:
- Update risk state on equity changes
- Check limits after trades
- Trigger account pauses on violations

CRITICAL: All operations are scoped to a single account.
One account's risk state NEVER affects another.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .account_manager import AccountManager
    from .risk_registry import RiskStateRegistry

logger = logging.getLogger(__name__)


@dataclass
class RuleConfig:
    """Configuration for a single risk rule.

    Attributes:
        rule_type: Type of rule (e.g., "daily_loss", "max_drawdown")
        limit: Limit percentage (e.g., 5.0 for 5%)
    """

    rule_type: str
    limit: Decimal


class RiskIsolationService:
    """Service that enforces per-account risk isolation.

    This is the integration point between:
    - RiskStateRegistry (per-account risk tracking)
    - AccountManager (account lifecycle)
    - Alert system (notifications)

    CRITICAL: All operations are scoped to a single account.
    One account's risk state NEVER affects another.

    Example:
        service = RiskIsolationService(account_manager, risk_registry)

        # Handle trade completion for Account A
        # This only updates Account A's state and checks Account A's limits
        await service.on_trade_completed(
            "account-a",
            realized_pnl=Decimal("-2500"),
            daily_loss_limit=Decimal("5.0"),
        )

        # Account B is completely unaffected
    """

    def __init__(
        self,
        account_manager: "AccountManager",
        risk_registry: "RiskStateRegistry",
    ) -> None:
        """Initialize risk isolation service.

        Args:
            account_manager: For pausing accounts on violations
            risk_registry: For per-account risk state tracking
        """
        self._account_manager = account_manager
        self._risk_registry = risk_registry

    async def on_equity_update(
        self,
        account_id: str,
        equity: Decimal,
        max_drawdown_limit: Decimal,
    ) -> None:
        """Handle equity update for ONLY the specified account.

        Args:
            account_id: Account receiving equity update
            equity: Current equity value
            max_drawdown_limit: Max drawdown percentage limit
        """
        # Update equity for ONLY this account
        await self._risk_registry.update_account_equity(account_id, equity)

        # Check drawdown for ONLY this account
        violated, current = await self._risk_registry.check_account_violation(
            account_id, "max_drawdown", max_drawdown_limit
        )

        if violated:
            await self._pause_for_violation(
                account_id,
                rule_type="max_drawdown",
                current_value=current,
                limit_value=max_drawdown_limit,
            )

    async def on_trade_completed(
        self,
        account_id: str,
        realized_pnl: Decimal,
        daily_loss_limit: Decimal,
    ) -> None:
        """Handle completed trade for ONLY the specified account.

        Args:
            account_id: Account that completed trade
            realized_pnl: Realized P&L from trade
            daily_loss_limit: Daily loss percentage limit
        """
        # Record trade for ONLY this account
        await self._risk_registry.record_account_trade(account_id, realized_pnl)

        # Check daily loss for ONLY this account
        violated, current = await self._risk_registry.check_account_violation(
            account_id, "daily_loss", daily_loss_limit
        )

        if violated:
            await self._pause_for_violation(
                account_id,
                rule_type="daily_loss",
                current_value=current,
                limit_value=daily_loss_limit,
            )

    async def check_pre_trade(
        self,
        account_id: str,
        rules: list[RuleConfig],
    ) -> bool:
        """Check if trade is allowed for ONLY the specified account.

        Args:
            account_id: Account to check
            rules: List of rules to validate against

        Returns:
            True if trade allowed, False if any rule would be violated
        """
        for rule in rules:
            violated, _ = await self._risk_registry.check_account_violation(
                account_id, rule.rule_type, rule.limit
            )
            if violated:
                logger.warning(
                    f"Pre-trade check failed for {account_id}: "
                    f"{rule.rule_type} limit would be exceeded"
                )
                return False
        return True

    async def _pause_for_violation(
        self,
        account_id: str,
        rule_type: str,
        current_value: Decimal,
        limit_value: Decimal,
    ) -> None:
        """Pause ONLY the specified account for rule violation.

        Args:
            account_id: Account to pause
            rule_type: Type of rule violated
            current_value: Current metric value
            limit_value: Limit that was exceeded
        """
        reason = (
            f"Rule violation: {rule_type} at {current_value:.2f}% "
            f"(limit: {limit_value:.2f}%)"
        )

        logger.warning(f"Pausing account {account_id}: {reason}")

        # Pause ONLY this account - others continue trading
        await self._account_manager.pause_for_rule_violation(
            account_id, rule_type, current_value, limit_value
        )

        # Record violation in Redis
        await self._risk_registry.record_violation(
            account_id, rule_type, current_value, limit_value
        )

    async def get_warning_level(
        self,
        account_id: str,
        limit_percent: Decimal,
    ) -> int | None:
        """Get warning level for an account's daily loss.

        Warning levels indicate how much of the daily loss limit has been consumed:
        - 70: First warning (70% of limit consumed)
        - 80: Second warning (80% of limit consumed)
        - 90: Critical warning (90% of limit consumed)

        Args:
            account_id: Account to check
            limit_percent: Daily loss limit percentage

        Returns:
            Warning level (70, 80, 90) or None if below 70% of limit
        """
        manager = await self._risk_registry.get_or_create(account_id)
        return manager.get_warning_level(limit_percent)
