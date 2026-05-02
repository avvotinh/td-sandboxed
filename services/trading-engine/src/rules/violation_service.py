"""Violation Service - Facade for recording rule violations."""

import logging
from typing import Any

from .base_rule import BaseRule, RuleResult
from .violation import RuleViolation
from .violation_db_writer import ViolationDBWriter

logger = logging.getLogger(__name__)


class ViolationService:
    """Facade for recording rule violations to TimescaleDB.

    Wraps ViolationDBWriter to provide typed convenience methods.
    No try/except internally - errors propagate to caller's done_callback.
    """

    def __init__(self, db_writer: ViolationDBWriter) -> None:
        self._db_writer = db_writer

    async def record_violation(
        self,
        rule: BaseRule,
        result: RuleResult,
        account_id: str,
        trade_id: str | None = None,
        signal_context: dict[str, Any] | None = None,
    ) -> None:
        """Record any type of violation (block or warn)."""
        violation = RuleViolation.from_rule_result(
            rule=rule,
            result=result,
            account_id=account_id,
            trade_id=trade_id,
            signal_context=signal_context,
        )
        await self._db_writer.add_violation(violation)

    async def record_block(
        self,
        rule: BaseRule,
        result: RuleResult,
        account_id: str,
        signal_context: dict[str, Any] | None = None,
    ) -> None:
        """Record a trade BLOCK violation. trade_id is always None."""
        await self.record_violation(
            rule=rule,
            result=result,
            account_id=account_id,
            trade_id=None,
            signal_context=signal_context,
        )

    async def record_warning(
        self,
        rule: BaseRule,
        result: RuleResult,
        account_id: str,
        trade_id: str | None = None,
        signal_context: dict[str, Any] | None = None,
    ) -> None:
        """Record a trade WARNING violation."""
        await self.record_violation(
            rule=rule,
            result=result,
            account_id=account_id,
            trade_id=trade_id,
            signal_context=signal_context,
        )
